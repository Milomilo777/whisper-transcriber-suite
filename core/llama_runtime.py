"""llama.cpp runtime for "Ask (offline)": pinned download, verify, install.

The offline question-answering feature runs llama.cpp's ``llama-server`` as
a child process (docs/DECISIONS.md, ADR 0013). It is not
bundled: on first use the app downloads the official release archive for
this OS/CPU, checks it against the size and SHA-256 pinned below, unpacks it
safely and moves the whole folder into place in one rename:

    user_cache_dir()/tools/llama.cpp/<tag>/llama-server[.exe] (+ its libraries)

This module only installs and checks the runtime; starting and stopping the
server is a separate step. Pins are bumped by hand (docs/BUILD.md,
"llama.cpp runtime pins"): llama.cpp publishes a prerelease every few hours
and its ``releases/latest`` points at an old dummy release, so the app never
follows "latest".

Tk-free; safe to import from the worker, the server and the UI.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from . import verified_download
from .config import user_cache_dir
from .paths import resource_base

logger = logging.getLogger(__name__)

# Pinned llama.cpp release. Sizes and SHA-256 are the GitHub asset digests;
# every asset was checked with `gh attestation verify <file> -R ggml-org/llama.cpp`
# (built by ggml-org/llama.cpp release-publish.yml on master).
LLAMA_CPP_TAG = "b11514"
_RELEASE_BASE = "https://github.com/ggml-org/llama.cpp/releases/download"


@dataclass(frozen=True)
class RuntimeAsset:
    name: str
    size: int
    sha256: str


ASSETS: dict[tuple[str, str], RuntimeAsset] = {
    ("windows", "x86_64"): RuntimeAsset(
        "llama-b11514-bin-win-cpu-x64.zip", 19_484_487,
        "5a1d6ba1b414ab0234b12e29d911b3b8fe63051b4455215e184cf74870eac596"),
    ("windows", "aarch64"): RuntimeAsset(
        "llama-b11514-bin-win-cpu-arm64.zip", 12_317_658,
        "02ab20653c1110cdb5b112c74bfa0519498ff108da15a44d61a0ec1dc724b43a"),
    ("darwin", "aarch64"): RuntimeAsset(
        "llama-b11514-bin-macos-arm64.tar.gz", 12_047_566,
        "e16abae5c048b77e0e8608728b162d88295bda6abbe449a8ba85c95fa734ee24"),
    ("darwin", "x86_64"): RuntimeAsset(
        "llama-b11514-bin-macos-x64.tar.gz", 11_576_025,
        "45f8fafe9b6c187edd81d83c45a4404fe9a14427a5a288926b3a68ec65826bad"),
    ("linux", "x86_64"): RuntimeAsset(
        "llama-b11514-bin-ubuntu-x64.tar.gz", 17_793_295,
        "b2b617fb28e9d1444235c30bb09a3704789a1840e16ead58a5f7be6eeae8beef"),
}

# The official macOS binaries are built for macOS 13.3 and newer.
MIN_MACOS = (13, 3)

_ARCH = {
    "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
    "arm64": "aarch64", "aarch64": "aarch64",
}

_WHAT = "downloading the offline AI engine (llama.cpp)"
# A staging folder older than this was left by a crash; a younger one may
# belong to an install running right now in another window.
_STALE_STAGING_S = 6 * 60 * 60.0

_install_lock = threading.Lock()


class UnsafeArchiveError(RuntimeError):
    """The archive holds a path or link that would land outside its folder."""


# ---------------------------------------------------------------- platform


def _mac_version() -> tuple[int, ...] | None:
    text = platform.mac_ver()[0]
    try:
        return tuple(int(p) for p in text.split(".")) if text else None
    except ValueError:
        return None


def unsupported_reason(
    system: str | None = None,
    machine: str | None = None,
    mac_version: tuple[int, ...] | None = None,
) -> str:
    """Why the pinned runtime cannot run on this computer; "" when it can."""
    system = system or platform.system()
    machine = machine or platform.machine()
    key = (system.lower(), _ARCH.get(machine.lower(), machine.lower()))
    if key not in ASSETS:
        return f"The offline AI engine (llama.cpp) has no build for {system} {machine}."
    if key[0] == "darwin":
        version = mac_version if mac_version is not None else _mac_version()
        if version is not None and version < MIN_MACOS:
            shown = ".".join(str(p) for p in version)
            return (
                "The offline AI engine (llama.cpp) needs macOS "
                f"{MIN_MACOS[0]}.{MIN_MACOS[1]} or newer; this Mac runs macOS {shown}."
            )
    return ""


def asset_for(
    system: str | None = None,
    machine: str | None = None,
    mac_version: tuple[int, ...] | None = None,
) -> RuntimeAsset | None:
    """The pinned release archive for this OS/CPU, or None (see ``unsupported_reason``)."""
    if unsupported_reason(system, machine, mac_version):
        return None
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    return ASSETS[(system, _ARCH.get(machine, machine))]


def release_url(asset: RuntimeAsset, base_url: str = _RELEASE_BASE) -> str:
    return f"{base_url}/{LLAMA_CPP_TAG}/{asset.name}"


# ---------------------------------------------------------------- locations


def server_exe_name() -> str:
    return "llama-server.exe" if os.name == "nt" else "llama-server"


def runtime_root() -> Path:
    return user_cache_dir() / "tools" / "llama.cpp"


def runtime_dir() -> Path:
    """The folder of the pinned runtime (may not exist yet)."""
    return runtime_root() / LLAMA_CPP_TAG


def installed_server() -> Path | None:
    """``llama-server`` of the installed pinned runtime, or None."""
    exe = runtime_dir() / server_exe_name()
    return exe if exe.is_file() else None


# ---------------------------------------------------------------- extraction


_WINDOWS_DEVICE_RE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)


def _checked_member_path(name: str) -> PurePosixPath:
    """The archive member ``name`` as a relative path, or UnsafeArchiveError.

    Refused: absolute paths, drive letters, ``..`` parts, ``:`` anywhere (on
    Windows ``a:b`` writes an alternate data stream), and parts Windows would
    silently rewrite (a trailing dot or space, device names such as ``nul``),
    which could make two members land on one file.
    """
    norm = name.replace("\\", "/")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if norm.startswith("/") or ":" in norm or ".." in parts or not parts:
        raise UnsafeArchiveError(f"The llama.cpp archive holds an unsafe path: {name!r}")
    if any(p.endswith((".", " ")) or _WINDOWS_DEVICE_RE.match(p) for p in parts):
        raise UnsafeArchiveError(f"The llama.cpp archive holds a name Windows cannot keep: {name!r}")
    return PurePosixPath(*parts)


def _inside(root: Path, rel: PurePosixPath) -> Path:
    target = (root / rel).resolve()
    base = root.resolve()
    if os.path.commonpath([str(base), str(target)]) != str(base):
        raise UnsafeArchiveError(f"The llama.cpp archive holds a path outside its folder: {rel}")
    return target


def _extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        checked = []
        for info in infos:
            rel = _checked_member_path(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise UnsafeArchiveError(f"The llama.cpp archive holds a link: {info.filename!r}")
            checked.append((info, rel, _inside(dest, rel)))
        for info, _rel, target in checked:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def _extract_tar(archive: Path, dest: Path) -> None:
    """Unpack a tarball whose links are all plain names in their own folder.

    The official tarballs only link ``libfoo.0.dylib -> libfoo.0.6.0.dylib``
    style names side by side, so anything else is refused: a link target with
    a folder part, hard links, special files, and any member below a link (a
    path written through a link). Checking link targets one by one cannot see
    chains of links; this rule leaves no chain to follow, also on Pythons
    without tarfile's ``data`` filter.
    """
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        links: set[PurePosixPath] = set()
        for m in members:
            rel = _checked_member_path(m.name)
            _inside(dest, rel)
            if m.issym():
                target = m.linkname
                if not target or any(c in target for c in "/\\:") or target in (".", ".."):
                    raise UnsafeArchiveError(
                        f"The llama.cpp archive holds a link outside its folder: {m.name!r} -> {target!r}")
                links.add(rel)
            elif not (m.isreg() or m.isdir()):
                raise UnsafeArchiveError(f"The llama.cpp archive holds a special file or hard link: {m.name!r}")
        for m in members:
            rel = _checked_member_path(m.name)
            if any(parent in links for parent in rel.parents):
                raise UnsafeArchiveError(f"The llama.cpp archive writes through a link: {m.name!r}")
        if hasattr(tarfile, "data_filter"):
            try:
                tf.extractall(dest, members=members, filter="data")
            except tarfile.FilterError as e:
                raise UnsafeArchiveError(f"The llama.cpp archive was refused: {e}") from e
        else:  # Python without extraction filters: the checks above are the guard
            tf.extractall(dest, members=members)


def extract_archive(archive: Path, dest: Path) -> None:
    """Unpack a ``.zip`` or ``.tar.gz`` into ``dest``, refusing anything that escapes it.

    Every member is checked before the first byte is written, so a refused
    archive leaves at most an empty ``dest``.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        _extract_zip(archive, dest)
    else:
        _extract_tar(archive, dest)


def _single_root(folder: Path) -> Path:
    """The archive's only top folder (``llama-b11514/`` in the tarballs), else ``folder``."""
    entries = list(folder.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink():
        return entries[0]
    return folder


# ---------------------------------------------------------------- install


def _sweep_stale_staging(root: Path) -> None:
    cutoff = time.time() - _STALE_STAGING_S
    for p in root.glob(".staging-*"):
        try:
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _move_into_place(src: Path, final: Path, trash: Path) -> None:
    """Rename ``src`` to ``final``; a broken ``final`` is moved to ``trash`` first.

    Retried briefly on Windows, where a virus scanner often still holds a
    freshly written DLL. A ``final`` that another window completed meanwhile
    wins: ``src`` is then simply left for the caller's clean-up.
    """
    if final.exists() and not (final / server_exe_name()).is_file():
        verified_download.replace_with_retry(final, trash)
    if (final / server_exe_name()).is_file():
        return
    verified_download.replace_with_retry(src, final)


def install_runtime(
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    *,
    base_url: str = _RELEASE_BASE,
    asset: RuntimeAsset | None = None,
) -> Path:
    """Download, verify and install the pinned runtime; return ``llama-server``'s path.

    Idempotent and serialised. ``progress_cb(done_bytes, total_bytes)``
    follows the download. Raises ``core.offline.OfflineModeError`` while
    Work offline is on, ``verified_download.DownloadCancelled`` on cancel
    (the partial download resumes next time), :class:`UnsafeArchiveError`
    for an archive that tries to escape its folder, and RuntimeError with a
    readable message otherwise. A failed install leaves no runtime folder.
    """
    if asset is None:
        reason = unsupported_reason()
        if reason:
            raise RuntimeError(reason)
        asset = asset_for()
        assert asset is not None
    with _install_lock:
        existing = installed_server()
        if existing is not None:
            ensure_vc_runtime(existing.parent)  # the system's runtime may have changed since
            return existing
        root = runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        busy = "Another window of the app is installing the offline AI engine; wait for it to finish."
        with verified_download.exclusive_lock(root / ".install.lock", busy):
            return _install_locked(root, asset, base_url, progress_cb, cancel_event)


def _install_locked(
    root: Path,
    asset: RuntimeAsset,
    base_url: str,
    progress_cb: Callable[[int, int], None] | None,
    cancel_event: threading.Event | None,
) -> Path:
    existing = installed_server()
    if existing is not None:  # another window finished it while we waited
        return existing
    _sweep_stale_staging(root)
    archive = root / "downloads" / asset.name
    verified_download.download_verified(
        release_url(asset, base_url), archive,
        size=asset.size, sha256=asset.sha256, what=_WHAT,
        progress_cb=progress_cb, cancel_event=cancel_event,
    )
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    try:
        extract_archive(archive, staging / "x")
        top = _single_root(staging / "x")
        exe = top / server_exe_name()
        if not exe.is_file():
            raise RuntimeError(
                f"The llama.cpp download has no {server_exe_name()} program; it was not installed."
            )
        if os.name != "nt":
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if sys.platform == "darwin":
            _clear_quarantine(top)
        missing = ensure_vc_runtime(top)
        if missing:
            logger.warning("llama.cpp runtime installed, but %s", vc_runtime_message(missing))
        _move_into_place(top, runtime_dir(), staging / "old")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    try:
        archive.unlink()
    except OSError as e:
        logger.info("Could not delete the llama.cpp archive %s: %s", archive, e)
    exe = installed_server()
    if exe is None:
        raise RuntimeError("The llama.cpp runtime could not be moved into place.")
    logger.info("llama.cpp %s installed at %s", LLAMA_CPP_TAG, exe.parent)
    return exe


def _clear_quarantine(folder: Path) -> None:
    from .paths import _remove_quarantine_xattr

    for dirpath, dirnames, filenames in os.walk(folder):
        for entry in dirnames + filenames:
            _remove_quarantine_xattr(os.path.join(dirpath, entry))


# ---------------------------------------------------------------- VC++ runtime (Windows)

VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# Lists the DLLs this module copied into a runtime folder (only those are
# ever removed again; the llama.cpp archive itself ships none of them).
_VC_MARKER = ".app-vc-runtime"
# Process exit codes of a program Windows could not load: DLL not found,
# entry point not found (an older DLL), wrong image format.
LOADER_FAILURES = frozenset({0xC0000135, 0xC0000139, 0xC000007B})


def _file_version(path: Path) -> tuple[int, int, int, int] | None:
    """A Windows file's version resource (e.g. (14, 44, 35211, 0)), or None."""
    if sys.platform != "win32" or not path.is_file():
        return None
    import ctypes
    from ctypes import wintypes

    class _FixedFileInfo(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "signature", "struc_version", "file_version_ms", "file_version_ls",
            "product_version_ms", "product_version_ls", "flags_mask", "flags",
            "os", "type", "subtype", "date_ms", "date_ls")]

    try:
        ver = ctypes.WinDLL("version")
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [
            ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        ver.VerQueryValueW.restype = wintypes.BOOL
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not ptr.value:
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(_FixedFileInfo)).contents
        ms, ls = info.file_version_ms, info.file_version_ls
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except (OSError, AttributeError, ValueError):
        return None


def _system_dll_version(name: str) -> tuple[int, int, int, int] | None:
    return _file_version(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / name)


def _app_dll_dirs() -> list[Path]:
    """Folders where this app keeps its own copy of the VC++ runtime.

    The Windows installer and Portable ZIP put Microsoft's DLLs next to the
    bundled Python (``python\\``); a PyInstaller build keeps them in its base.
    """
    seen: list[Path] = []
    for d in (Path(sys.executable).parent, Path(resource_base()), Path(resource_base()) / "python"):
        if d.is_dir() and d not in seen:
            seen.append(d)
    return seen


def plan_vc_runtime(
    system_version: Callable[[str], tuple[int, ...] | None],
    app_version: Callable[[Path], tuple[int, ...] | None],
    app_dirs: list[Path],
) -> tuple[dict[str, Path], list[str]]:
    """Which app copies of the VC++ DLLs to put beside ``llama-server``, and what is missing.

    A DLL beside the program wins over the system one, so the app's copy is
    used only when it is NEWER than the system's (or the system has none):
    an older runtime than the one llama.cpp was built against fails to load.
    """
    copies: dict[str, Path] = {}
    missing: list[str] = []
    for name in VC_RUNTIME_DLLS:
        best: Path | None = None
        best_version = system_version(name)
        for d in app_dirs:
            cand = d / name
            if not cand.is_file():
                continue
            version = app_version(cand) or (0,)
            if best_version is None or version > best_version:
                best, best_version = cand, version
        if best is not None:
            copies[name] = best
        elif best_version is None:
            missing.append(name)
    return copies, missing


def ensure_vc_runtime(folder: Path) -> list[str]:
    """Windows: make the VC++ runtime loadable for the ``llama-server`` in ``folder``.

    Copies the app's own (Microsoft-signed, app-local) DLLs into ``folder``
    when they are newer than the system's, removes copies it made earlier
    that the system has since overtaken, and returns the DLLs neither side
    has. Elsewhere: nothing to do, ``[]``.
    """
    if sys.platform != "win32":
        return []
    copies, missing = plan_vc_runtime(_system_dll_version, _file_version, _app_dll_dirs())
    marker = folder / _VC_MARKER
    try:
        ours = set(marker.read_text(encoding="utf-8").split())
    except OSError:
        ours = set()
    for name in VC_RUNTIME_DLLS:
        local = folder / name
        src = copies.get(name)
        if src is None:
            if name in ours:
                try:
                    local.unlink()
                except FileNotFoundError:
                    pass
                except OSError as e:
                    logger.warning("Could not remove the old %s copy: %s", local, e)
                    continue
                ours.discard(name)
            continue
        try:
            shutil.copy2(src, local)
            ours.add(name)
        except OSError as e:
            logger.warning("Could not copy %s beside llama-server: %s", src, e)
            if _system_dll_version(name) is None:
                missing.append(name)
    try:
        if ours:
            marker.write_text("\n".join(sorted(ours)) + "\n", encoding="utf-8")
        elif marker.exists():
            marker.unlink()
    except OSError as e:
        logger.warning("Could not update %s: %s", marker, e)
    return missing


def vc_runtime_message(missing: list[str]) -> str:
    names = " and ".join(missing) if missing else "its DLLs"
    return (
        "The offline AI engine needs the Microsoft Visual C++ 2015-2022 runtime "
        f"({names}), which this computer lacks or has in an old version. Install it "
        f"from {VC_REDIST_URL} and try again."
    )


# ---------------------------------------------------------------- checks


def child_env() -> dict[str, str]:
    """The environment for a ``llama-server`` child.

    llama-server reads its options from ``LLAMA_ARG_*`` variables and ggml
    loads backends from ``GGML_*`` paths: anything set on the user's system
    must not change what the app starts. Library injection variables are
    dropped too, and a frozen (PyInstaller) app gives the child the user's
    own ``LD_LIBRARY_PATH`` back instead of the bundle's, so llama-server
    loads its own libraries, not the app's.
    """
    env = {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(("LLAMA_", "GGML_", "DYLD_")) and k.upper() != "LD_PRELOAD"
    }
    if getattr(sys, "frozen", False):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def server_version(exe: Path) -> str:
    """``llama-server --version``'s version line; RuntimeError when it cannot start.

    A Windows loader failure (a missing or too old VC++ runtime) becomes the
    message with the Microsoft download link.
    """
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL, "capture_output": True, "text": True,
        "timeout": 60, "cwd": str(exe.parent), "env": child_env(),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run([str(exe), "--version"], **kwargs)  # type: ignore[call-overload]
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"Could not start llama-server: {e}") from e
    if sys.platform == "win32" and (res.returncode & 0xFFFFFFFF) in LOADER_FAILURES:
        raise RuntimeError(vc_runtime_message([]))
    output = f"{res.stdout or ''}\n{res.stderr or ''}"
    if res.returncode != 0:
        tail = [ln for ln in output.splitlines() if ln.strip()][-1:] or [""]
        raise RuntimeError(f"llama-server failed to start (exit code {res.returncode}). {tail[0]}".strip())
    m = re.search(r"^version:.*$", output, re.MULTILINE)
    if m:
        return m.group(0).strip()
    return next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
