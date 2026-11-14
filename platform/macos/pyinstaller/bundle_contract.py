"""Bind a tested macOS bundle to its packaged copy without following symlinks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys
import tempfile


def version(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", value, flags=re.ASCII):
        raise ValueError("Invalid macOS deployment version")
    parts = tuple(int(part) for part in value.split("."))
    padded = parts + (0, 0)
    return padded[0], padded[1], padded[2]


def _plist(app: Path) -> dict:
    with (app / "Contents/Info.plist").open("rb") as stream:
        value = plistlib.load(stream)
    for key in ("CFBundleShortVersionString", "LSMinimumSystemVersion"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError("Missing bundle identity: " + key)
    version(value["LSMinimumSystemVersion"])
    return value


def require_supported_host(app: Path, host: str) -> None:
    minimum = _plist(app)["LSMinimumSystemVersion"]
    if version(host) < version(minimum):
        raise ValueError(
            f"Build host {host} is below the supported deployment target {minimum}; "
            "this app has no supported-host validation and cannot be packaged for release"
        )


def bundle_manifest(app: Path) -> dict:
    app = Path(app)
    if app.is_symlink() or not app.is_dir():
        raise ValueError("Expected a real application directory")
    info = _plist(app)
    rows = []

    def walk(directory: Path):
        for path in sorted(directory.iterdir()):
            metadata = path.lstat()
            relative = path.relative_to(app).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                if not path.resolve(strict=True).is_relative_to(app.resolve()):
                    raise ValueError("Bundle symlink escapes the application: " + relative)
                rows.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
            elif stat.S_ISDIR(metadata.st_mode):
                rows.append({"path": relative, "kind": "directory"})
                walk(path)
            elif stat.S_ISREG(metadata.st_mode):
                with path.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Bundle changed while hashing")
                rows.append({"path": relative, "kind": "file", "bytes": metadata.st_size,
                             "executable": metadata.st_mode & 0o111, "sha256": digest})
            else:
                raise ValueError("Unexpected bundle entry: " + relative)

    walk(app)
    return {"schema": 1, "version": info["CFBundleShortVersionString"],
            "minimum": info["LSMinimumSystemVersion"], "entries": rows}


def verify_manifest(app: Path, expected: dict) -> None:
    if expected.get("schema") != 1 or not expected.get("entries"):
        raise ValueError("Missing verified application manifest")
    if bundle_manifest(app) != expected:
        raise ValueError("Packaged application differs from the verified application")


def require_native_imports(app: Path) -> None:
    # The builder imports only this standard-library helper; native imports
    # happen in the copied frozen app, bounded by the same probe process owner.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from core.hardware_probe import _run_command, NATIVE_COMPONENT_MODULES
    executable = app / "Contents/MacOS/Whisper Transcriber Suite"
    with tempfile.TemporaryDirectory(prefix="wts-bundle-probe-") as directory:
        result = Path(directory) / "result.json"
        report = _run_command([str(executable), "--hardware-probe-worker", "native-components", str(result)], result, 120.0)
    if report.get("native_components") != list(NATIVE_COMPONENT_MODULES):
        raise ValueError("Frozen native-component verification is incomplete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("host", "manifest", "verify", "native"))
    parser.add_argument("app", type=Path)
    parser.add_argument("value", nargs="?", help="host version or manifest path")
    args = parser.parse_args()
    if args.action == "native":
        require_native_imports(args.app)
    elif args.action == "host":
        require_supported_host(args.app, args.value)
    elif args.action == "manifest":
        manifest = Path(args.value)
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump(bundle_manifest(args.app), stream, ensure_ascii=False, indent=2)
    else:
        with Path(args.value).open(encoding="utf-8") as stream:
            verify_manifest(args.app, json.load(stream))


if __name__ == "__main__":
    main()
