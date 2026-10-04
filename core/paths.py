"""Resolve where bundled resources (bin/, faster_whisper assets) live.

Three runtime contexts:

  * onefile pyinstaller exe  ->  sys._MEIPASS (a temp extract dir)
  * onedir  pyinstaller exe  ->  dirname(sys.executable)
  * python source            ->  repo root (parent of this file's parent)

Use ``resource_base()`` for anything that was bundled into the exe at
build time. Anything that has to *persist* between runs (user config,
history db, downloaded model cache) belongs under platformdirs, not
here.
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path


def resource_base() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return str(meipass)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return str(Path(__file__).resolve().parent.parent)


def bin_dir() -> str:
    return os.path.join(resource_base(), "bin")


def bundled_binary(name: str) -> str:
    """Absolute path to a bundled binary; falls back to PATH lookup name."""
    exe = f"{name}.exe" if os.name == "nt" else name
    candidate = os.path.join(bin_dir(), exe)
    if not os.path.isfile(candidate):
        return name
    if os.name != "nt":
        _ensure_executable(candidate)
    return candidate


def clear_bundled_quarantine() -> None:
    """macOS app: drop ``com.apple.quarantine`` from the bundled bin/ tools.

    A .dmg downloaded with a browser tags every file in the app with the
    quarantine flag, the bundled yt-dlp/ffmpeg/deno included. Gatekeeper
    then holds a still-quarantined tool ("can't be opened because Apple
    cannot check it") and kills it -- e.g. when the bundled yt-dlp is run
    from Terminal; verified on macOS 10.15 (held 5 min, then SIGKILL). The
    user already chose to open this app, so its own helpers need no second
    check. Called once at startup; never raises. A read-only (translocated)
    bundle simply keeps the flag. Folder-style tools (yt-dlp's onedir build:
    an executable plus its libraries) are cleared recursively, since every
    file in them carries its own flag.
    """
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return
    base = bin_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        # Contents/MacOS/bin entries are symlinks into Contents/Frameworks/bin;
        # removexattr follows them, so the real files are cleared.
        path = os.path.join(base, name)
        _remove_quarantine_xattr(path)
        if os.path.isdir(path):
            # os.walk does not descend into symlinked dirs, so no loops.
            for root, dirs, files in os.walk(os.path.realpath(path)):
                for entry in dirs + files:
                    _remove_quarantine_xattr(os.path.join(root, entry))


@functools.lru_cache(maxsize=1)
def _libc():  # loaded once: the onedir yt-dlp alone has ~270 entries
    import ctypes

    return ctypes.CDLL(None, use_errno=True)


def _remove_quarantine_xattr(path: str) -> None:
    try:
        # removexattr(path, name, options); options 0 follows symlinks.
        _libc().removexattr(os.fsencode(path), b"com.apple.quarantine", 0)
    except Exception:  # noqa: BLE001
        pass


def _ensure_executable(path: str) -> None:
    """Best-effort ``chmod +x`` for a bundled POSIX binary.

    PyInstaller's ``datas`` copy (used to bundle ``bin/`` into the macOS
    .app via ``whisper_project_mac.spec``) does not reliably preserve the
    source files' executable bit through COLLECT/BUNDLE on every PyInstaller
    version. A bundled ffmpeg/ffprobe/ffplay/yt-dlp that lost +x would make
    every ``subprocess`` call against it fail with "Permission denied" —
    so re-assert +x here, once per resolved path. Never raises: a read-only
    bundle (the common case once installed) simply keeps whatever bit it
    already has, and chmod failing there is harmless.
    """
    try:
        st = os.stat(path)
        if not (st.st_mode & 0o111):
            os.chmod(path, st.st_mode | 0o111)
    except OSError:
        pass
