"""JavaScript runtime for yt-dlp (Deno) -- YouTube needs one.

Since late 2025 yt-dlp solves YouTube's JavaScript challenges with an
external JS runtime. Without one it prints "No supported JavaScript runtime
could be found", some or all YouTube formats go missing, and downloads fail
more and more often (open issue #8 in docs/MACOS_BUILD_NOTES.md; it affects
Windows too). yt-dlp only auto-detects a ``deno`` on PATH, which almost no
user of this app has.

This module:

* finds a Deno the app can hand to yt-dlp -- one bundled next to yt-dlp in
  ``bin/``, one this app installed into the user cache, or one on PATH;
* builds the matching ``--js-runtimes deno:<path>`` arguments, added to every
  yt-dlp call (download, format lookup, subtitles, web server, Video Tiling);
* installs Deno on demand (one click in the Download tab): the official
  release zip from github.com/denoland/deno, verified against the SHA-256
  file published next to it, unpacked into the user cache (no admin rights).

Tk-free; safe to import from the worker, the server and the UI.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Callable

from .config import user_cache_dir
from .paths import bundled_binary

logger = logging.getLogger(__name__)

# Official release assets ("latest" redirects to the newest stable release).
_RELEASE_BASE = "https://github.com/denoland/deno/releases/latest/download"
# Roughly what the one-time download weighs (zip); shown in the prompt.
DENO_DOWNLOAD_MB = 42

_install_lock = threading.Lock()


def _exe_name() -> str:
    return "deno.exe" if os.name == "nt" else "deno"


def installed_deno_path() -> Path:
    """Where the on-demand install puts Deno (may not exist yet)."""
    return user_cache_dir() / "tools" / "deno" / _exe_name()


def find_deno(*, include_path: bool = True) -> str | None:
    """Path of a usable Deno, or None.

    Order: bundled next to yt-dlp (``bin/``), installed by this app, then
    (unless ``include_path`` is False) one on PATH.
    """
    bundled = bundled_binary("deno")
    if os.path.isabs(bundled) and os.path.isfile(bundled):
        return bundled
    installed = installed_deno_path()
    if installed.is_file():
        return str(installed)
    if not include_path:
        return None
    on_path = shutil.which("deno")
    return on_path or None


# yt-dlp gained --js-runtimes (with its YouTube JS-challenge solver) in
# 2025.11.12. Passing the option to an older yt-dlp fails EVERY call with
# "no such option", so it is only added when the binary is new enough.
_MIN_YT_DLP_FOR_JS_RUNTIMES = (2025, 11, 12)
_yt_dlp_version_cache: dict[tuple[str, float], tuple[int, ...]] = {}


def yt_dlp_version(path: str | None = None) -> tuple[int, ...]:
    """Version of the yt-dlp the app runs, e.g. (2026, 8, 19); () if unknown.

    Asked once per binary (cached by path + modification time, so a
    self-update is noticed). The first call runs ``yt-dlp --version`` --
    about a second for the Windows exe -- so call it off the Tk thread.
    """
    import subprocess

    exe = path or bundled_binary("yt-dlp")
    resolved = exe if os.path.isabs(exe) else (shutil.which(exe) or "")
    if not resolved:
        return ()
    try:
        key = (resolved, os.path.getmtime(resolved))
    except OSError:
        return ()
    if key in _yt_dlp_version_cache:
        return _yt_dlp_version_cache[key]
    version: tuple[int, ...] = ()
    try:
        kwargs: dict[str, object] = {"capture_output": True, "text": True, "timeout": 30}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run([resolved, "--version"], **kwargs)  # type: ignore[call-overload]
        m = re.match(r"\s*(\d{4})\.(\d{1,2})\.(\d{1,2})", res.stdout or "")
        if res.returncode == 0 and m:
            version = tuple(int(g) for g in m.groups())
    except Exception:  # noqa: BLE001
        version = ()
    _yt_dlp_version_cache[key] = version
    return version


def yt_dlp_js_args(yt_dlp_path: str | None = None) -> list[str]:
    """``--js-runtimes deno:<path>`` for yt-dlp, or [] when not applicable.

    Only for a Deno this app bundles or installed: yt-dlp finds one on PATH
    by itself. And only when the yt-dlp in use knows the option (see
    ``_MIN_YT_DLP_FOR_JS_RUNTIMES``). May run ``yt-dlp --version`` once --
    call it off the Tk thread.
    """
    path = find_deno(include_path=False)
    if not path:
        return []
    version = yt_dlp_version(yt_dlp_path)
    if not version or version < _MIN_YT_DLP_FOR_JS_RUNTIMES:
        return []
    return ["--js-runtimes", f"deno:{path}"]


_NO_RUNTIME_RE = re.compile(
    r"no supported javascript runtime|js runtimes?: none"
    r"|javascript runtime (?:is )?required|n challenge solving failed",
    re.IGNORECASE,
)


def mentions_missing_js_runtime(text: str) -> bool:
    """True when yt-dlp output says it lacked a JavaScript runtime."""
    return bool(_NO_RUNTIME_RE.search(text or ""))


def is_youtube_url(url: str) -> bool:
    """YouTube (incl. youtu.be, music, shorts) -- the site that needs Deno."""
    host = re.sub(r"^[a-z]+://", "", (url or "").strip().lower()).split("/", 1)[0]
    host = host.split("@")[-1].split(":")[0]
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def release_asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """Deno release zip for this OS/CPU, or None when Deno has no build."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {
        "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "arm64": "aarch64", "aarch64": "aarch64",
    }.get(machine)
    if arch is None:
        return None
    target = {
        "windows": f"{arch}-pc-windows-msvc",
        "darwin": f"{arch}-apple-darwin",
        "linux": f"{arch}-unknown-linux-gnu",
    }.get(system)
    return f"deno-{target}.zip" if target else None


def _expected_sha256(checksum_text: str) -> str:
    """The SHA-256 in a Deno ``.sha256sum`` file.

    Linux/macOS files use ``<hash>  <name>``; the Windows one is PowerShell's
    ``Get-FileHash`` table (``Hash : <HASH>``) -- take the 64-hex token.
    """
    m = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text or "")
    if not m:
        raise RuntimeError("the Deno checksum file has no SHA-256 in it")
    return m.group(1).lower()


def _download(url: str, dest: Path, progress_cb: Callable[[int], None] | None,
              cancel_event: threading.Event | None) -> None:
    import requests

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        last_pct = -1
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Deno download cancelled")
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    pct = int(done * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        progress_cb(pct)


def install_deno(
    progress_cb: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    *,
    base_url: str = _RELEASE_BASE,
) -> str:
    """Download, verify and unpack Deno into the user cache; return its path.

    Raises RuntimeError with a readable message on any failure (no Deno build
    for this machine, network, checksum mismatch). Serialised; a concurrent
    caller finds the finished install.
    """
    asset = release_asset_name()
    if asset is None:
        raise RuntimeError(
            f"Deno has no build for this computer ({platform.system()} "
            f"{platform.machine()})."
        )
    with _install_lock:
        target = installed_deno_path()
        if target.is_file():
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(target.parent)) as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / asset
            try:
                import requests

                sums = requests.get(f"{base_url}/{asset}.sha256sum", timeout=60)
                sums.raise_for_status()
                expected = _expected_sha256(sums.text)
                _download(f"{base_url}/{asset}", zip_path, progress_cb, cancel_event)
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001 -- network errors, HTTP errors
                raise RuntimeError(f"Could not download Deno: {e}") from e
            digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            if digest != expected:
                raise RuntimeError(
                    "The downloaded Deno does not match its published checksum; "
                    "it was not installed."
                )
            with zipfile.ZipFile(zip_path) as zf:
                member = next(
                    (n for n in zf.namelist() if os.path.basename(n) == _exe_name()),
                    None,
                )
                if member is None:
                    raise RuntimeError("The Deno download did not contain the program.")
                extracted = Path(zf.extract(member, tmp_dir / "x"))
            if os.name != "nt":
                extracted.chmod(extracted.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.replace(extracted, target)  # same volume: atomic
        logger.info("Deno installed at %s", target)
        return str(target)


def deno_version(path: str | None = None) -> str:
    """``deno --version`` first line (e.g. "deno 2.9.7 ..."), or ""."""
    import subprocess

    exe = path or find_deno()
    if not exe:
        return ""
    try:
        kwargs: dict[str, object] = {"capture_output": True, "text": True, "timeout": 20}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run([exe, "--version"], **kwargs)  # type: ignore[call-overload]
        return (res.stdout or "").splitlines()[0].strip() if res.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""
