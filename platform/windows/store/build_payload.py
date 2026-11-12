"""Build a Store-specific ONEDIR payload using explicit, fresh output paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

PYINSTALLER_VERSION = "6.22.3"
SOURCE_TREES = ("app", "core", "assets", "bin", "platform/windows")
CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
PROBE = """import importlib.metadata as m,json,sys
print(json.dumps({'python':sys.version,'platform':sys.platform,'dependencies':{d.metadata['Name']:d.version for d in m.distributions() if d.metadata.get('Name')}},sort_keys=True))
"""


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_revision(repo_root: Path) -> tuple[str, str]:
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root),
        check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(repo_root), check=True, capture_output=True, text=True).stdout.strip()
    return revision, status


def _source_inputs(repo_root: Path) -> dict[str, str]:
    """Hash actual build inputs, including untracked source and ignored bin files."""
    files = {path for pattern in ("*.py", "*.spec", "requirements*.txt") for path in repo_root.glob(pattern)}
    files.update(repo_root / name for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
                                              "platform/ffmpeg-source.json") if (repo_root / name).exists())
    def check(path: Path) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Build source must not contain a symlink/reparse point: {path}")
    def fail_walk(error: OSError) -> None:
        raise error
    for name in SOURCE_TREES:
        root = repo_root / name
        if not root.exists():
            continue
        check(root)
        for directory, directories, names in os.walk(root, followlinks=False, onerror=fail_walk):
            directories[:] = sorted(name for name in directories if name not in CACHE_DIRECTORIES)
            for name in directories + names:
                check(Path(directory) / name)
            files.update(Path(directory) / name for name in names if not name.endswith((".pyc", ".pyo")))
    result = {}
    for path in sorted(files):
        check(path)
        if not path.is_file():
            raise ValueError(f"Expected regular build input: {path}")
        result[path.relative_to(repo_root).as_posix()] = _hash(path)
    return result


def _input_digest(inputs: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _probe_environment(python: Path) -> dict:
    return json.loads(subprocess.run([str(python), "-c", PROBE], check=True,
        capture_output=True, text=True).stdout)


def _freeze_source(repo_root: Path, destination: Path, inputs: dict[str, str]) -> None:
    """Copy captured inputs to a new private build tree and verify every byte."""
    destination.mkdir()
    for name, expected in inputs.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with (repo_root / name).open("rb") as source, target.open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        if _hash(target) != expected:
            raise ValueError(f"Source changed while freezing build input: {name}")
        target.chmod(target.stat().st_mode & ~stat.S_IWRITE)
    if _source_inputs(destination) != inputs:
        raise ValueError("Frozen source snapshot differs from captured build inputs")


def build_payload(*, repo_root: Path, python: Path, build_dir: Path, dist_dir: Path,
                  work_dir: Path, makeappx: Path, sdk_version: str, download_policy: str,
                  scratch_fixture: bool = False) -> dict:
    """Record exact inputs and invoke the delegated Store specification.

    The selected SDK is recorded for subsequent packaging; PyInstaller does not
    invoke MakeAppx. Scratch mode is explicitly recorded and never a release gate.
    """
    if download_policy == "omit":
        raise ValueError("Download-omitting application guards are not wired; only retain builds are available")
    if download_policy != "retain":
        raise ValueError("An explicit retain or omit download policy is required")
    raw_outputs = tuple(Path(path) for path in (build_dir, dist_dir, work_dir))
    repo_root, python, build_dir, dist_dir, work_dir, makeappx = (
        Path(path).resolve() for path in (repo_root, python, build_dir, dist_dir, work_dir, makeappx))
    outputs = (build_dir, dist_dir, work_dir)
    for output in outputs:
        if repo_root.is_relative_to(output):
            raise ValueError("Build outputs must not contain the source repository")
        if any(output.is_relative_to(repo_root / name) for name in SOURCE_TREES):
            raise ValueError("Build outputs must be outside source input directories")
    for left in outputs:
        for right in outputs:
            if left != right and (left.is_relative_to(right) or right.is_relative_to(left)):
                raise ValueError("Build, dist and work directories must be disjoint")
    if len(set(outputs)) != 3:
        raise ValueError("Build, dist and work directories must be distinct")
    for output in raw_outputs:
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Build output already exists: {output}")
    spec = repo_root / "platform/windows/store/whisper_project_store.spec"
    hook = repo_root / "platform/windows/store/runtime_hook.py"
    for required in (python, makeappx, spec, hook, repo_root / "core/distribution.py",
                     repo_root / "whisper_project_onedir.spec", repo_root / "LICENSE", repo_root / "THIRD_PARTY_NOTICES.md"):
        if not required.is_file():
            raise ValueError(f"Required build input is missing: {required}")
    if not sdk_version.strip():
        raise ValueError("The selected SDK version must be recorded")
    revision, source_status = _source_revision(repo_root)
    if source_status and not scratch_fixture:
        raise ValueError("Build from committed source, or explicitly select --scratch-fixture")
    source_inputs = _source_inputs(repo_root)
    source_date_epoch = subprocess.run(["git", "show", "-s", "--format=%ct", revision],
        cwd=str(repo_root), check=True, capture_output=True, text=True).stdout.strip()
    if not source_date_epoch.isdecimal():
        raise ValueError("Git did not return a numeric source commit timestamp")
    probe = _probe_environment(python)
    versions = {name.lower(): value for name, value in probe["dependencies"].items()}
    if versions.get("pyinstaller") != PYINSTALLER_VERSION:
        raise ValueError(f"The build interpreter must contain PyInstaller {PYINSTALLER_VERSION}")
    if probe.get("platform") != "win32":
        raise ValueError("The selected build interpreter must run on Windows")
    for output in outputs:
        output.mkdir(parents=True)
    marker = build_dir / "STORE_BUILD.json"
    marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True,
                                 "download_policy": download_policy}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["WTS_STORE_MARKER_PATH"] = str(marker)
    environment["PYINSTALLER_CONFIG_DIR"] = str(work_dir / "pyinstaller-config")
    snapshot = build_dir / "source-snapshot"
    environment["PYTHONPATH"] = str(snapshot)
    environment["PYTHONHASHSEED"] = "0"
    environment["SOURCE_DATE_EPOCH"] = source_date_epoch
    frozen_spec = snapshot / spec.relative_to(repo_root)
    command = [str(python), "-m", "PyInstaller", "--distpath", str(dist_dir),
               "--workpath", str(work_dir), str(frozen_spec)]
    receipt = {"schema": 1, "status": "prepared", "source_revision": revision,
        "source_dirty": bool(source_status), "source_status_sha256": hashlib.sha256(source_status.encode("utf-8")).hexdigest(),
        "source_input_hashes": source_inputs, "source_inputs_sha256": _input_digest(source_inputs), "source_inputs_verified": False,
        "source_input_trees": list(SOURCE_TREES),
        "source_snapshot": "source-snapshot", "source_date_epoch": source_date_epoch, "python_hash_seed": "0",
        "scratch_fixture": scratch_fixture, "python": probe["python"],
        "python_executable_sha256": _hash(python), "dependencies": probe["dependencies"],
        "sdk": {"version": sdk_version, "makeappx_sha256": _hash(makeappx), "used_by_payload_build": False},
        "specification_sha256": _hash(spec), "base_specification_sha256": _hash(repo_root / "whisper_project_onedir.spec"),
        "runtime_hook_sha256": _hash(hook), "distribution_policy_sha256": _hash(repo_root / "core/distribution.py"),
        "marker_sha256": _hash(marker), "download_policy": download_policy}
    receipt_path = build_dir / "build-receipt.json"
    def save_receipt():
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    save_receipt()
    try:
        _freeze_source(repo_root, snapshot, source_inputs)
        with (build_dir / "pyinstaller.log").open("x", encoding="utf-8") as log:
            subprocess.run(command, cwd=str(snapshot), env=environment, check=True,
                           stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        executable = dist_dir / "WhisperTranscriberSuite/WhisperTranscriberSuite.exe"
        packaged_marker = executable.parent / "STORE_BUILD.json"
        if not executable.is_file() or executable.stat().st_size == 0 or not packaged_marker.is_file():
            raise ValueError("PyInstaller did not create the required ONEDIR executable and Store marker")
        if _hash(packaged_marker) != receipt["marker_sha256"]:
            raise ValueError("The packaged Store marker differs from the selected build policy")
        after_revision, after_status = _source_revision(repo_root)
        after_inputs = _source_inputs(repo_root)
        frozen_inputs = _source_inputs(snapshot)
        receipt["source_revision_after"] = after_revision
        receipt["source_dirty_after"] = bool(after_status)
        receipt["source_inputs_sha256_after"] = _input_digest(after_inputs)
        if (after_revision, after_status, after_inputs) != (revision, source_status, source_inputs):
            receipt["changed_source_inputs"] = sorted(name for name in source_inputs.keys() | after_inputs.keys()
                                                      if source_inputs.get(name) != after_inputs.get(name))
            raise ValueError("Source revision, working-tree status, or build input bytes changed during PyInstaller")
        if frozen_inputs != source_inputs:
            raise ValueError("Frozen source snapshot changed during PyInstaller")
        if (_probe_environment(python) != probe or _hash(python) != receipt["python_executable_sha256"]
                or _hash(makeappx) != receipt["sdk"]["makeappx_sha256"] or _hash(marker) != receipt["marker_sha256"]):
            raise ValueError("Build interpreter, SDK or selected marker inputs changed during PyInstaller")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            notice = executable.parent / name
            if not notice.is_file() or _hash(notice) != source_inputs[name]:
                raise ValueError(f"Standalone ONEDIR payload is missing the exact {name} notice")
        receipt["source_inputs_verified"] = True
        receipt["payload_executable_sha256"] = _hash(executable)
        receipt["status"] = "built"
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["failure_type"] = type(exc).__name__
        save_receipt()
        raise
    save_receipt()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("repo-root", "python", "build-dir", "dist-dir", "work-dir", "makeappx"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--sdk-version", required=True)
    parser.add_argument("--download-policy", choices=("retain", "omit"), required=True)
    parser.add_argument("--scratch-fixture", action="store_true")
    args = parser.parse_args()
    result = build_payload(**vars(args))
    print(json.dumps({"status": result["status"], "source_revision": result["source_revision"],
                      "scratch_fixture": result["scratch_fixture"]}, sort_keys=True))


if __name__ == "__main__":
    main()
