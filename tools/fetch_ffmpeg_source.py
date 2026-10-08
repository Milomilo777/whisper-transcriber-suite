"""Download the corresponding source of the bundled GPL FFmpeg builds, ready to attach to a release.

The FFmpeg binaries the app ships are GPL-3.0 builds, so every release carries a copy of the
matching source next to its files (docs/RELEASE_PROCESS.md). The pins live in
platform/ffmpeg-source.json (URL, byte size, SHA-256) and reuse the download and verify code of
tools/fetch_windows_build_deps.py: a file whose size or hash differs is deleted and the run fails,
so only verified tarballs ever land in the output folder.

Usage (standard library only, Python 3.10+):
  python tools/fetch_ffmpeg_source.py --out DIR --app-version X.Y.Z
                                      [--platform windows|macos|all]   (default: all)
  python tools/fetch_ffmpeg_source.py --out DIR --app-version X.Y.Z --check
                                      verify files already in DIR, no network
Files are named after the release, so they sort after the installer, the Portable ZIP and the
macOS disk images on the release page.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under `python -I`
import fetch_windows_build_deps as _fetch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PINS = ROOT / "platform" / "ffmpeg-source.json"
PLATFORMS = ("windows", "macos")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_NAME = re.compile(r"[A-Za-z0-9._-]+")

FetchError = _fetch.FetchError


def load_pins(path: Path = PINS) -> list[dict[str, Any]]:
    """The pin list; raises FetchError for anything the shared validator or this tool rejects."""
    with open(path, encoding="utf-8") as fh:
        deps = json.load(fh)["deps"]
    errors = _fetch.validate(deps)
    seen_platforms: set[str] = set()
    asset_names: set[str] = set()
    for dep in deps:
        where = f"entry {dep.get('name')}"
        if dep.get("files") != []:
            errors.append(f"{where}: files must be an empty list (the download is the product)")
        if dep.get("platform") not in PLATFORMS:
            errors.append(f"{where}: platform must be one of {', '.join(PLATFORMS)}")
        else:
            seen_platforms.add(dep["platform"])
        template = dep.get("asset_name")
        if not isinstance(template, str) or "{app_version}" not in template \
                or not _NAME.fullmatch(template.replace("{app_version}", "0.0.0")):
            errors.append(f"{where}: asset_name must be a plain file name containing {{app_version}}")
        elif template in asset_names:
            errors.append(f"{where}: asset_name {template} is used twice")
        else:
            asset_names.add(template)
    if seen_platforms != set(PLATFORMS):
        errors.append("the pin list must cover every platform: " + ", ".join(PLATFORMS))
    if errors:
        raise FetchError(f"{path}: " + "; ".join(errors))
    return deps


def asset_name(dep: dict[str, Any], app_version: str) -> str:
    if not _VERSION.fullmatch(app_version):
        raise FetchError(f"app version {app_version!r} is not of the form X.Y.Z")
    return dep["asset_name"].replace("{app_version}", app_version)


def _verified(path: Path, dep: dict[str, Any]) -> bool:
    return path.is_file() and path.stat().st_size == dep["size"] \
        and _fetch.sha256_file(path) == dep["sha256"]


def select(deps: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    if platform != "all" and platform not in PLATFORMS:
        raise FetchError(f"unknown platform {platform!r}")
    return [d for d in deps if platform in ("all", d["platform"])]


def fetch(deps: list[dict[str, Any]], out: Path, app_version: str, *,
          opener: _fetch.Opener = _fetch._default_opener) -> list[Path]:
    """Put every dep's verified tarball in out under its release name; returns the paths."""
    paths = []
    for dep in deps:
        target = out / asset_name(dep, app_version)
        if _verified(target, dep):
            print(f"[ffmpeg-source] {target.name}: already present, verified", flush=True)
        else:
            _fetch.download(dep, target, opener=opener)
            print(f"[ffmpeg-source] {target.name}: {dep['version']}: verified", flush=True)
        paths.append(target)
    return paths


def check(deps: list[dict[str, Any]], out: Path, app_version: str) -> list[str]:
    """Problems with the files in out; empty when every tarball is present and matches its pin."""
    problems = []
    for dep in deps:
        target = out / asset_name(dep, app_version)
        if not target.is_file():
            problems.append(f"missing: {target.name}")
        elif not _verified(target, dep):
            problems.append(f"differs from the pin: {target.name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch and verify the bundled FFmpeg's source tarballs.")
    ap.add_argument("--pins", type=Path, default=PINS, help="pin list (default: %(default)s)")
    ap.add_argument("--out", type=Path, required=True, help="folder for the tarballs")
    ap.add_argument("--app-version", required=True, metavar="X.Y.Z",
                    help="the release the files are attached to (used in the file names)")
    ap.add_argument("--platform", choices=(*PLATFORMS, "all"), default="all",
                    help="which builds' source to fetch (a Windows-only release needs 'windows')")
    ap.add_argument("--check", action="store_true", help="verify files already in --out, no network")
    args = ap.parse_args(argv)
    try:
        deps = select(load_pins(args.pins), args.platform)
        if args.check:
            problems = check(deps, args.out, args.app_version)
            for p in problems:
                print(f"[ffmpeg-source] {p}")
            print(f"[ffmpeg-source] check: {'FAIL' if problems else 'ok'}")
            return 1 if problems else 0
        fetch(deps, args.out, args.app_version)
        return 0
    except FetchError as exc:
        print(f"[ffmpeg-source] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
