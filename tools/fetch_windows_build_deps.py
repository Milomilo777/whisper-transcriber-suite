"""Download the Windows build's third-party files at pinned versions and verify every byte.

The list lives in platform/windows/build-deps.json: one entry per download with a fixed URL, its
byte size and a SHA-256 the upstream project publishes. A download whose size or hash differs is
deleted and the run fails, so nothing unverified ever reaches bin/. Files taken out of an archive
are checked against their own recorded SHA-256 as well.

Usage (standard library only, Python 3.10+):
  python tools/fetch_windows_build_deps.py                 fill bin/ (files already verified are kept)
  python tools/fetch_windows_build_deps.py --check         verify bin/ against the list, no network
                                           [--root DIR]    ... or a built/installed tree
                                           [--select NAME] ... limited to one entry (repeatable)
  python tools/fetch_windows_build_deps.py --only NAME --out FILE
                                                           one raw download, e.g. the Python tarball
                                                           (build_embed_installer.bat) or Inno Setup
build_embed_installer.bat and .github/workflows/windows-installer.yml call it; docs/BUILD.md
explains how to move a pin to a newer version.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, BinaryIO

ROOT = Path(__file__).resolve().parent.parent
PINS = ROOT / "platform" / "windows" / "build-deps.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20

Opener = Callable[..., BinaryIO]


class FetchError(RuntimeError):
    """A download or a file did not match its pin."""


def load_pins(path: Path = PINS) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        deps = json.load(fh)["deps"]
    errors = validate(deps)
    if errors:
        raise FetchError(f"{path}: " + "; ".join(errors))
    return deps


def _safe_relative(path: str) -> bool:
    p = PurePosixPath(path)
    return bool(path) and "\\" not in path and not p.is_absolute() and ".." not in p.parts \
        and ":" not in path


def validate(deps: list[dict[str, Any]]) -> list[str]:
    """Every problem in the list; empty when it can be used."""
    errors: list[str] = []
    seen: set[str] = set()
    targets: set[str] = set()
    for i, dep in enumerate(deps):
        name = dep.get("name")
        where = f"entry {i} ({name})"
        if not isinstance(name, str) or not name:
            errors.append(f"{where}: missing name")
        elif name in seen:
            errors.append(f"{where}: duplicate name")
        else:
            seen.add(name)
        url = dep.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"{where}: url must be https")
        size = dep.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            errors.append(f"{where}: size must be a positive integer")
        if not isinstance(dep.get("sha256"), str) or not _SHA256.match(dep["sha256"]):
            errors.append(f"{where}: sha256 must be 64 lowercase hex digits")
        files = dep.get("files")
        if not isinstance(files, list):
            errors.append(f"{where}: files must be a list")
            continue
        for f in files:
            to = f.get("to") if isinstance(f, dict) else None
            if not isinstance(to, str) or not _safe_relative(to):
                errors.append(f"{where}: bad target path {to!r}")
                continue
            if to.lower() in targets:
                errors.append(f"{where}: {to} is written twice")
            targets.add(to.lower())
            if not isinstance(f.get("sha256"), str) or not _SHA256.match(f["sha256"]):
                errors.append(f"{where}: {to}: sha256 must be 64 lowercase hex digits")
            member = f.get("member")
            if member is None:
                if f.get("sha256") != dep.get("sha256"):
                    errors.append(f"{where}: {to} is the download itself, so its sha256 must match")
            elif not isinstance(member, str) or not _safe_relative(member):
                errors.append(f"{where}: bad archive member {member!r}")
    return errors


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects (GitHub and Hugging Face send downloads to a CDN), but only to https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"refused a redirect to a non-https URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirects())


class _Incomplete(OSError):
    """The server closed the connection before the pinned size arrived (retried)."""


def _default_opener(url: str, timeout: float) -> BinaryIO:
    req = urllib.request.Request(url, headers={"User-Agent": "wts-build-fetch/1"})
    return _OPENER.open(req, timeout=timeout)


def download(dep: dict[str, Any], dest: Path, *, opener: Opener = _default_opener,
             retries: int = 3, timeout: float = 120.0) -> None:
    """Write dep's URL to dest; raise FetchError unless size and SHA-256 both match.

    Network errors and a body cut short are retried; a full-size body with the wrong hash
    or a body larger than the pin fails at once.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        h = hashlib.sha256()
        size = 0
        try:
            with opener(dep["url"], timeout) as resp, open(part, "wb") as out:
                for block in iter(lambda: resp.read(_CHUNK), b""):
                    size += len(block)
                    if size > dep["size"]:
                        raise FetchError(f"{dep['name']}: download is larger than {dep['size']} bytes")
                    h.update(block)
                    out.write(block)
            if size < dep["size"]:
                raise _Incomplete(f"connection closed after {size} of {dep['size']} bytes")
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            part.unlink(missing_ok=True)
            last_error = exc
            print(f"[fetch] {dep['name']}: attempt {attempt}/{retries} failed: {exc}", flush=True)
            if attempt < retries:
                time.sleep(2 * attempt)
            continue
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        if size != dep["size"] or h.hexdigest() != dep["sha256"]:
            part.unlink(missing_ok=True)
            raise FetchError(
                f"{dep['name']}: got {size} bytes sha256 {h.hexdigest()}, "
                f"pinned {dep['size']} bytes sha256 {dep['sha256']}"
            )
        os.replace(part, dest)
        return
    raise FetchError(f"{dep['name']}: download failed after {retries} attempts: {last_error}")


def _target_ok(root: Path, f: dict[str, Any]) -> bool:
    path = root / f["to"]
    return path.is_file() and sha256_file(path) == f["sha256"]


def install(dep: dict[str, Any], root: Path, *, opener: Opener = _default_opener) -> list[str]:
    """Put dep's files under root. Returns the target paths written (empty if all were present)."""
    files = dep["files"]
    if all(_target_ok(root, f) for f in files):
        return []
    with tempfile.TemporaryDirectory(prefix="wts-fetch-") as tmp:
        archive = Path(tmp) / "download"
        download(dep, archive, opener=opener)
        staged: list[tuple[Path, Path]] = []
        for i, f in enumerate(files):
            out = Path(tmp) / f"file{i}"
            if f.get("member") is None:
                shutil.copyfile(archive, out)
            else:
                try:
                    with zipfile.ZipFile(archive) as zf, zf.open(f["member"]) as src, \
                            open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst, _CHUNK)
                except KeyError:
                    raise FetchError(f"{dep['name']}: archive has no member {f['member']}") from None
            got = sha256_file(out)
            if got != f["sha256"]:
                raise FetchError(f"{dep['name']}: {f['to']} has sha256 {got}, pinned {f['sha256']}")
            staged.append((out, root / f["to"]))
        # Every file verified before any target is touched.
        for out, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_target = target.with_name(target.name + ".part")
            shutil.copyfile(out, tmp_target)
            os.replace(tmp_target, target)
    return [f["to"] for f in files]


def check(deps: list[dict[str, Any]], root: Path) -> list[str]:
    """Target files that are missing or differ from their pin."""
    problems = []
    for dep in deps:
        for f in dep["files"]:
            path = root / f["to"]
            if not path.is_file():
                problems.append(f"missing: {f['to']}")
            elif sha256_file(path) != f["sha256"]:
                problems.append(f"differs from the pin: {f['to']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch and verify the pinned Windows build files.")
    ap.add_argument("--pins", type=Path, default=PINS, help="pin list (default: %(default)s)")
    ap.add_argument("--root", type=Path, default=ROOT, help="where target paths start")
    ap.add_argument("--check", action="store_true", help="verify the targets, download nothing")
    ap.add_argument("--only", metavar="NAME", help="download one entry as-is (needs --out)")
    ap.add_argument("--out", type=Path, help="output file for --only")
    ap.add_argument("--select", metavar="NAME", action="append", default=[],
                    help="fill or check only this entry (repeatable)")
    args = ap.parse_args(argv)
    try:
        deps = load_pins(args.pins)
        unknown = set(args.select) - {d["name"] for d in deps}
        if unknown:
            raise FetchError(f"no entry named {', '.join(sorted(unknown))} in {args.pins}")
        if args.select:
            deps = [d for d in deps if d["name"] in args.select]
        if args.only:
            if args.out is None:
                ap.error("--only needs --out")
            dep = next((d for d in deps if d["name"] == args.only), None)
            if dep is None:
                raise FetchError(f"no entry named {args.only!r} in {args.pins}")
            download(dep, args.out)
            print(f"[fetch] {dep['name']} {dep['version']}: verified -> {args.out}")
            return 0
        if args.check:
            problems = check(deps, args.root)
            for p in problems:
                print(f"[fetch] {p}")
            print(f"[fetch] check: {'FAIL' if problems else 'ok'}")
            return 1 if problems else 0
        for dep in deps:
            if not dep["files"]:
                continue
            written = install(dep, args.root)
            state = "written: " + ", ".join(written) if written else "already present"
            print(f"[fetch] {dep['name']} {dep['version']}: verified, {state}", flush=True)
        return 0
    except FetchError as exc:
        print(f"[fetch] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
