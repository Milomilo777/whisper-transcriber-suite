"""Pinned v2.3.1 -> current -> uninstall gate on a disposable clean Windows VM.

Neither installer receives /DIR: the default Program Files path is asserted.
Failures retain diagnostics and never trigger an automatic cleanup uninstall.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.request
import uuid

BASELINE_VERSION = "2.3.1"
BASELINE_URL = "https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v2.3.1/WhisperTranscriberSuite-Installer-Windows-v2.3.1.exe"
BASELINE_SHA256 = "97d86d9cda0ed1eb2d7edf967b374dc59a3c7a472bc43f9e4f3c20432054f435"
BASELINE_SIZE = 251072859
APP_NAME = "Whisper Transcriber Suite"
APP_ID = "{BD640ACA-1EDB-4F9F-890E-C2DC04221871}_is1"
SENTINEL_FOLDERS = ("app", "core", "bin", "assets", "python", "Lib")


class GateError(RuntimeError):
    pass


class GateTimeout(GateError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def require_windows_admin() -> None:
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise GateError("Requires 64-bit Windows Python on a disposable clean VM")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise GateError("Requires an already elevated runner; no elevation is attempted")


def shell_folder(csidl: int) -> Path:
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) != 0:
        raise GateError(f"Cannot resolve Windows shell folder {csidl}")
    return Path(buffer.value)


def default_paths() -> tuple[Path, Path, Path]:
    return (shell_folder(0x26) / "WhisperTranscriberSuite",
            shell_folder(0x17) / APP_NAME, shell_folder(0x19))


def registered_versions() -> list[str]:
    import winreg
    found = []
    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    try:
                        version = str(winreg.QueryValueEx(handle, "DisplayVersion")[0])
                    except FileNotFoundError:
                        version = "<missing DisplayVersion>"
                    found.append(version)
            except FileNotFoundError:
                pass
    return found


def baseline_installer(work: Path, cached: Path | None) -> Path:
    path = cached.resolve() if cached else work / "baseline-v2.3.1.exe"
    if cached is None:
        with urllib.request.urlopen(BASELINE_URL, timeout=60) as response, path.open("xb") as target:
            received = 0
            while block := response.read(65536):
                received += len(block)
                if received > BASELINE_SIZE:
                    raise GateError("Historical installer exceeds the pinned size")
                target.write(block)
    if path.stat().st_size != BASELINE_SIZE or sha256_file(path) != BASELINE_SHA256:
        raise GateError("Historical installer does not match the pinned v2.3.1 size/SHA-256")
    return path


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_checked(argv: list[str], label: str, work: Path, *, installer: bool = False) -> None:
    if installer:
        # -Wait includes descendants, including Inno's temporary uninstaller.
        # https://learn.microsoft.com/powershell/module/microsoft.powershell.management/start-process
        arguments = subprocess.list2cmdline(argv[1:])
        command = ("$ErrorActionPreference='Stop'; $p=Start-Process -WindowStyle Hidden "
                   f"-FilePath {ps_literal(argv[0])} -ArgumentList {ps_literal(arguments)} "
                   "-Wait -PassThru; exit $p.ExitCode")
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONSAFEPATH"):
        env.pop(name, None)
    env.update(WTS_PROFILE_DIR=str(work / "private-profile"), PYTHONDONTWRITEBYTECODE="1")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (work / f"{label}-process.log").open("xb") as log:
        try:
            result = subprocess.run(argv, cwd=work, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=600, creationflags=flags)
        except subprocess.TimeoutExpired as error:
            raise GateTimeout(
                f"{label} timed out; descendants may remain. Abort and discard this VM; "
                "do not run another installer or cleanup uninstall on it"
            ) from error
    if result.returncode:
        raise GateError(f"{label} exited {result.returncode}; see {label}-process.log")


def setup_arguments(path: Path, log: Path) -> list[str]:
    return [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
            "/ALLUSERS", "/TASKS=desktopicon", f"/LOG={log}"]


def assert_sentinels(sentinels: dict[Path, str], phase: str) -> None:
    for path, expected in sentinels.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise GateError(f"{phase} destroyed or changed sentinel: {path}")


def assert_version(root: Path, expected: str, work: Path, label: str) -> None:
    code = (f"import sys; sys.path.insert(0, {str(root)!r}); import core; "
            f"assert core.__version__ == {expected!r}, core.__version__; print(core.__version__)")
    run_checked([str(root / "python/python.exe"), "-I", "-c", code], label, work)
    versions = registered_versions()
    if not versions or any(version != expected for version in versions):
        raise GateError(f"{label}: wrong uninstall registration versions: {versions}")


def execute_gate(new: Path, expected: str, work: Path, cached: Path | None, report: dict) -> None:
    require_windows_admin()
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", expected):
        raise GateError("Expected version must be numeric dotted")
    if tuple(map(int, expected.split("."))) <= tuple(map(int, BASELINE_VERSION.split("."))):
        raise GateError("The new build must be newer than the pinned historical installer")
    root, group, desktop = default_paths()
    report["install_root"] = str(root)
    if (root.exists() or root.is_symlink() or group.exists() or group.is_symlink()
            or list(desktop.glob(f"{APP_NAME} *.lnk")) or registered_versions()):
        raise GateError("Requires a clean machine: existing install, registration or shortcuts detected")
    old = baseline_installer(work, cached)
    new = new.resolve(strict=True)
    new_sha = sha256_file(new)
    if new_sha == BASELINE_SHA256:
        raise GateError("The new build is the historical installer; refusing a same-installer upgrade")
    report.update(baseline_url=BASELINE_URL, baseline_sha256=BASELINE_SHA256,
                  baseline_version=BASELINE_VERSION, new_sha256=new_sha,
                  expected_version=expected, completed=[])
    old_links = [group / f"{APP_NAME} {BASELINE_VERSION}.lnk",
                 desktop / f"{APP_NAME} {BASELINE_VERSION}.lnk"]
    new_links = [group / f"{APP_NAME} {expected}.lnk", desktop / f"{APP_NAME} {expected}.lnk"]
    run_checked(setup_arguments(old, work / "old-install.log"), "old-install", work, installer=True)
    assert_version(root, BASELINE_VERSION, work, "old-version")
    if not all(path.is_file() for path in old_links):
        raise GateError("Historical install did not create both default Start-menu/Desktop shortcuts")
    report["completed"].append("historical-install-default-program-files")
    sentinels = {}
    name = f"user-preservation-{uuid.uuid4().hex}.bin"
    for folder in SENTINEL_FOLDERS:
        directory = root / folder
        if not directory.is_dir():
            raise GateError(f"Historical installed folder missing: {directory}")
        path = directory / name
        with path.open("xb") as stream:
            stream.write(b"Whisper QA synthetic user original\x00" + os.urandom(32))
        sentinels[path] = sha256_file(path)
    report["sentinels"] = {str(path): digest for path, digest in sentinels.items()}
    run_checked(setup_arguments(new, work / "new-install.log"), "upgrade", work, installer=True)
    assert_sentinels(sentinels, "upgrade")
    assert_version(root, expected, work, "new-version")
    if any(path.exists() for path in old_links) or not all(path.is_file() for path in new_links):
        raise GateError("Upgrade left historical shortcuts or failed to create current shortcuts")
    smoke = Path(__file__).resolve().with_name("smoke_windows_install.py")
    run_checked([str(root / "python/python.exe"), str(smoke), str(root), expected], "installed-smoke", work)
    report["completed"].append("upgrade-preserves-sentinels-and-retires-old-shortcuts")
    run_checked([str(root / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                 "/NORESTART", f"/LOG={work / 'uninstall.log'}"], "uninstall", work, installer=True)
    assert_sentinels(sentinels, "uninstall")
    tracked = [root / name for name in ("python/python.exe", "python/pythonw.exe", "gui.py", "core/__init__.py")]
    if any(path.exists() for path in tracked) or registered_versions():
        raise GateError("Uninstall left tracked executables/source or an uninstall registration")
    if any(path.exists() for path in old_links + new_links + [group / f"Uninstall {APP_NAME}.lnk"]):
        raise GateError("Uninstall left an application shortcut")
    report["completed"].append("uninstall-preserves-sentinels-and-removes-tracked-app")
    report["status"] = "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--baseline-installer", type=Path)
    parser.add_argument("--confirm-clean-machine", action="store_true", required=True)
    args = parser.parse_args(argv)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAILED"}
    try:
        execute_gate(args.installer, args.expected_version, work, args.baseline_installer, report)
    except GateTimeout as error:
        report.update(error=f"GateTimeout: {error}", discard_machine_required=True)
        print(report["error"], file=sys.stderr)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    finally:
        (work / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
