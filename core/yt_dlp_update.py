"""A user-writable yt-dlp copy that updates itself.

YouTube changes its pages often, and an old yt-dlp then fails with "HTTP Error
403" or "Signature extraction failed" until a newer yt-dlp is installed. The
bundled copy lives in the install folder (Program Files for the Windows
installer), which a standard user cannot write, so it could only be refreshed
by a new app release or an administrator.

This module keeps a second copy at ``user_cache_dir()/tools/yt-dlp/`` (the
Deno helper lives beside it in ``tools/deno``) and updates it with yt-dlp's own
``--update-to stable``: yt-dlp downloads the new build from its GitHub release,
checks it against the release's SHA2-256SUMS and swaps it in, renaming the
current file back if the swap fails. No download or checksum code of our own.
The first update starts from a copy of the bundled binary. The bundled copy is
never touched and stays the fallback.

``resolve_yt_dlp_path`` returns whichever of the two copies is newer, from the
versions recorded in ``state.json`` beside the copy, so it runs no subprocess
and is cheap enough for the Tk thread. A copy whose size or modification time
no longer matches the record, or that failed ``--version``, is not used.

Only single-file yt-dlp builds can update themselves: yt-dlp refuses for its
folder ("onedir") builds, which the macOS app bundles. There, "Update it"
installs yt-dlp's official folder build instead (``_install_onedir``): the
latest stable release's ``yt-dlp_macos.zip`` (its single-file build unpacks
itself on every run, about 25 s per call), over https to GitHub's own hosts
only, checked against the release's SHA2-256SUMS, unpacked safely into a new
versioned folder beside the old one and started once with ``--version``;
``state.json`` points at the new folder only then, and the old one is removed.
Installing and updating are the same steps, and yt-dlp's own ``--update-to``
is not used there. A Mac older than that build's minimum macOS (10.15), or one
where the downloaded build did not start, keeps the bundled copy and the
"install the newest app version" advice (``can_self_update`` is False).

An update never runs while a yt-dlp download runs, and a download that starts
during an update waits for it (``download_running`` / ``update_cached_copy``).

Tk-free; safe to import from the worker, the server and the UI.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import logging
import os
import platform
import re
import shutil
import secrets
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any, Callable, Generator, Mapping

from . import offline
from ._proc import kill_process_tree, new_session_kwargs
from .config import user_cache_dir
from .js_runtime import find_deno, mentions_missing_js_runtime, yt_dlp_version
from .paths import bundled_binary
from .updates import RELEASES_PAGE_URL

logger = logging.getLogger(__name__)

#: ``yt_dlp_update_mode`` values: offer an update when a download fails in a
#: way an old yt-dlp causes (default), update before a download at most once a
#: day, or never touch it.
MODE_ASK = "ask"
MODE_AUTO = "auto"
MODE_NEVER = "never"
MODES = (MODE_ASK, MODE_AUTO, MODE_NEVER)

#: Where yt-dlp's own updater goes (it builds these URLs itself; listed here so
#: docs/CONFIG.md's network table is checked against them).
RELEASE_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
RELEASE_DOWNLOADS_URL = "https://github.com/yt-dlp/yt-dlp/releases/"

#: macOS "Update it" (``_install_onedir``): yt-dlp's folder build, taken from the
#: latest stable release and listed in the same release's checksum file. The
#: README calls its single-file twin "Universal MacOS (10.15+) standalone
#: executable"; the zip holds ``yt-dlp_macos`` beside ``_internal/`` (universal).
BOOTSTRAP_ASSET = "yt-dlp_macos.zip"
ONEDIR_EXE = "yt-dlp_macos"
CHECKSUMS_ASSET = "SHA2-256SUMS"
RELEASE_LATEST_URL = RELEASE_DOWNLOADS_URL + "latest/download/"
#: The only hosts a download may be redirected to (GitHub's own file hosts).
TRUSTED_HOSTS = frozenset({
    "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
})
#: The oldest macOS the file runs on, from yt-dlp's README.
MACOS_MIN = (10, 15)
#: After a verified download did not start (twice), how long that macOS is left alone.
REFUSAL_DAYS = 30
#: How long the folder an update replaced stays (a lookup that started from it keeps its files).
RETIRED_GRACE = timedelta(hours=1)
#: Held while the macOS install or its clean-up runs (one app instance at a time).
LOCK_NAME = "update.lock"
#: What the macOS zip weighs (53,923,637 bytes in release 2026.08.19); shown on the bar.
DOWNLOAD_MB_MACOS = 54
#: Far above the real size; a longer answer is not the zip.
BOOTSTRAP_MAX_BYTES = 150 * 1024 * 1024
#: Limits for unpacking the zip (162 entries and 130 MB in release 2026.08.19).
ONEDIR_MAX_FILES = 3000
ONEDIR_MAX_UNPACKED_BYTES = 600 * 1024 * 1024
#: The whole macOS download, checksum list included (a slow link needs minutes).
BOOTSTRAP_TIMEOUT_S = 600
_SOCKET_TIMEOUT_S = 30
_CHECKSUMS_MAX_BYTES = 256 * 1024
_PIECE_BYTES = 64 * 1024
_USER_AGENT = "WhisperTranscriberSuite-yt-dlp-download"
# ``/yt-dlp/yt-dlp/releases/download/<tag>/<file>``: the tag GitHub resolved
# "latest" to, so the checksum list and the file come from one release.
_RELEASE_TAG_RE = re.compile(r"^/yt-dlp/yt-dlp/releases/download/(\d+(?:\.\d+)*)/")
_ONEDIR_DIR_RE = re.compile(r"onedir-[0-9A-Za-z._-]{1,80}")
_ONEDIR_ANY_RE = re.compile(r"onedir-[0-9A-Za-z._-]+")

AUTO_INTERVAL = timedelta(hours=24)
#: Roughly what one update downloads (the Windows yt-dlp.exe); shown on the bar.
DOWNLOAD_MB = 18
UPDATE_TIMEOUT_S = 180
#: How long a download start waits for a running update before going ahead:
#: the updater itself plus two ``--version`` calls (up to 120 s each on a slow
#: first start) and the copy. On a Mac (``wait_bound``): the zip download plus
#: four ``--version`` calls (the check is asked twice) and the unpacking.
WAIT_FOR_UPDATE_S = UPDATE_TIMEOUT_S + 2 * 120 + 60
WAIT_FOR_UPDATE_MACOS_S = BOOTSTRAP_TIMEOUT_S + 4 * 120 + 60

_STATE_NAME = "state.json"

# What an outdated yt-dlp prints when a site changed under it. yt-dlp ends its
# extractor errors with "Confirm you are on the latest version using yt-dlp -U".
_OUTDATED_RE = re.compile(
    r"http error 403"
    r"|(?:signature|nsig|\bn|\bsig) (?:function )?extraction failed"
    r"|unable to extract"
    r"|confirm you are on the latest version",
    re.IGNORECASE,
)

# What yt-dlp's updater answers when this build cannot update itself although
# it is a single file: a package-manager, pip or other unofficial build
# (yt_dlp/update.py _NON_UPDATEABLE_REASONS). It only says so when a newer
# release exists, so the answer is remembered in state.json (``unsupported``)
# instead of starting the updater again before every download.
_NON_UPDATEABLE_RE = re.compile(
    r"auto-update is not supported"
    r"|this executable cannot be updated"
    r"|cannot update when running from source"
    r"|installed yt-dlp (?:from a manual build|with a package manager|with pip)"
    r"|unofficial build of yt-dlp"
    r"|use that to update",
    re.IGNORECASE,
)

_cond = threading.Condition()
_running: set[object] = set()
_updating = False
# Serialises refresh_state (ask the versions, stat, write state.json), so a
# slow refresh can never write an older record after a newer one.
_state_lock = threading.RLock()


def update_mode(cfg: Mapping[str, Any]) -> str:
    """The configured mode; anything unknown is the default ("ask")."""
    mode = str(cfg.get("yt_dlp_update_mode") or "").strip().lower()
    return mode if mode in MODES else MODE_ASK


def _exe_name() -> str:
    return "yt-dlp.exe" if os.name == "nt" else "yt-dlp"


def cached_dir() -> Path:
    return user_cache_dir() / "tools" / "yt-dlp"


def cached_path() -> Path:
    """Where the user-writable copy lives (may not exist yet). On a Mac with an
    installed folder build: the program inside the folder ``state.json`` names."""
    if _is_macos():
        rec = _installed_onedir(load_state())
        if rec is not None:
            return cached_dir() / rec["dir"] / ONEDIR_EXE
    return cached_dir() / _exe_name()


def _installed_onedir(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The record of the installed macOS folder build, or None. Its folder name
    is checked, so a hand-edited record cannot point outside the cache."""
    rec = state.get("onedir")
    if isinstance(rec, dict) and isinstance(rec.get("dir"), str) and _ONEDIR_DIR_RE.fullmatch(rec["dir"]):
        return rec
    return None


def version_label(version: tuple[int, ...] | list[int]) -> str:
    """(2026, 8, 19) -> "2026.08.19"; "" when unknown."""
    if not version:
        return ""
    return ".".join(str(p) if i == 0 else f"{p:02d}" for i, p in enumerate(version))


def looks_outdated(text: str) -> bool:
    """True when yt-dlp output reads like a site change an update may fix."""
    return bool(_OUTDATED_RE.search(text or ""))


def should_offer_update(text: str) -> bool:
    """A failure an update may fix: an outdated-yt-dlp sign, or "no JavaScript
    runtime" while Deno is installed (then only a newer yt-dlp can use it)."""
    if looks_outdated(text):
        return True
    return mentions_missing_js_runtime(text) and find_deno() is not None


def auto_update_due(last: object, now: datetime) -> bool:
    """Mode "auto": True when the last completed check is 24 h old or unknown.

    ``last`` is the stored ISO timestamp. An unparsable value, or one without
    a UTC offset (a hand-edited config; subtracting a naive time from an aware
    one raises TypeError), counts as "never checked".
    """
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last))
        return now - last_dt >= AUTO_INTERVAL
    except (ValueError, TypeError):
        return True


def can_self_update(bundled: str | None = None) -> bool:
    """True when this app can keep a self-updating yt-dlp copy.

    Either the bundled yt-dlp is a single-file build we can copy, or this is a
    Mac that can install yt-dlp's folder build (``bootstrap_possible``).
    """
    path = bundled if bundled is not None else bundled_binary("yt-dlp")
    return _can_copy_bundled(path) or bootstrap_possible()


def _can_copy_bundled(path: str) -> bool:
    """True when the bundled yt-dlp is a single-file build we can copy.

    A bare name (no bundled binary; PATH lookup on Linux/macOS from source)
    gives nothing to copy. yt-dlp's folder builds (an executable next to an
    ``_internal`` folder; the macOS app bundles one) refuse ``--update``, and
    so do package-manager and other unofficial single-file builds, which
    this module learns from the updater's answer and records.
    """
    if not (os.path.isabs(path) and os.path.isfile(path)):
        return False
    real = os.path.realpath(path)
    if os.path.isdir(os.path.join(os.path.dirname(real), "_internal")):
        return False
    return not _marked_unsupported(load_state(), path)


def _is_macos() -> bool:
    return sys.platform == "darwin"


def macos_version() -> tuple[int, ...]:
    """(13, 7) for macOS 13.7.8; () when unknown or not macOS."""
    try:
        text = platform.mac_ver()[0]
    except Exception:  # noqa: BLE001 -- unknown means "do not block"
        return ()
    m = re.match(r"\s*(\d+)(?:\.(\d+))?", text or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else ()


def bootstrap_possible() -> bool:
    """True on a Mac that may install yt-dlp's folder build.

    Not below ``MACOS_MIN`` (that Mac keeps the bundled copy), and not on a
    macOS where a verified download did not start (``bootstrap_refused``; a
    newer macOS tries again). An unknown macOS version is not held back: the
    start check after the download decides.
    """
    if not _is_macos():
        return False
    version = macos_version()
    if version and version < MACOS_MIN:
        return False
    return not _bootstrap_refused(load_state(), version)


def _bootstrap_refused(state: Mapping[str, Any], version: tuple[int, ...]) -> bool:
    """True while a verified download is known not to start on this macOS. The
    record expires (``REFUSAL_DAYS``) so a transient cause is not final."""
    rec = state.get("bootstrap_refused")
    if not isinstance(rec, dict) or rec.get("macos") != list(version):
        return False
    try:
        return now_utc() < datetime.fromisoformat(str(rec.get("until")))
    except (ValueError, TypeError):
        return False  # unreadable or without a UTC offset: try again


def download_mb() -> int:
    """About how many MB an update downloads on this system, for the bar."""
    return DOWNLOAD_MB_MACOS if _is_macos() else DOWNLOAD_MB


def _marked_unsupported(state: Mapping[str, Any], bundled: str) -> bool:
    """True when yt-dlp's updater refused exactly this bundled binary before
    (see ``_NON_UPDATEABLE_RE``); another binary (a new app version) is
    tried again."""
    rec = state.get("unsupported")
    return (
        isinstance(rec, dict)
        and rec.get("path") == _norm(bundled)
        and rec.get("fingerprint") == _fingerprint(bundled)
    )


def _fingerprint(path: str | Path) -> list[int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return [st.st_size, st.st_mtime_ns]


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _as_version(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    if not all(isinstance(p, int) and not isinstance(p, bool) for p in value):
        return ()
    return tuple(value)


def _state_path() -> Path:
    return cached_dir() / _STATE_NAME


def load_state() -> dict[str, Any]:
    """The recorded versions, or {} when missing or unreadable."""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _rejected(state: Mapping[str, Any], fingerprint: list[int] | None) -> bool:
    """True when the record marks exactly this file as rejected (a build that
    could not be verified, which could not be removed either)."""
    rec = state.get("cached")
    return (
        fingerprint is not None
        and isinstance(rec, dict)
        and rec.get("rejected") is True
        and rec.get("fingerprint") == fingerprint
    )


def choose_path(bundled: str, cached: Path, state: Mapping[str, Any]) -> str:
    """The newer of the bundled and the cached copy; the bundled one if in doubt.

    The cached copy is used only when its record has a version (it answered
    ``--version``), its size and modification time still match the record,
    and that version is newer than the bundled one's. A bundled binary that changed since the record (the app
    was updated) counts as unknown, so the bundled one is used until
    ``refresh_state`` has asked both again.
    """
    rec = state.get("cached")
    if not isinstance(rec, dict):
        return bundled
    if rec.get("fingerprint") != _fingerprint(cached):
        return bundled
    cached_v = _as_version(rec.get("version"))
    if not cached_v:
        return bundled
    if os.path.isabs(bundled) and os.path.isfile(bundled):
        brec = state.get("bundled")
        if (
            not isinstance(brec, dict)
            or brec.get("path") != _norm(bundled)
            or brec.get("fingerprint") != _fingerprint(bundled)
        ):
            return bundled
        bundled_v = _as_version(brec.get("version"))
        if bundled_v and bundled_v >= cached_v:
            return bundled
    return str(cached)


def resolve_yt_dlp_path() -> str:
    """The yt-dlp to run: the newer copy, else the bundled one. Never raises."""
    bundled = bundled_binary("yt-dlp")
    try:
        return choose_path(bundled, cached_path(), load_state())
    except Exception:  # noqa: BLE001 -- the bundled copy always works as before
        logger.exception("Could not read the yt-dlp copy's state; using the bundled one")
        return bundled


VersionOf = Callable[[str], "tuple[int, ...]"]


def refresh_state(*, version_of: VersionOf | None = None) -> dict[str, Any]:
    """Ask both copies for their version and record it. Runs subprocesses:
    call it off the Tk thread."""
    ask = version_of or yt_dlp_version
    with _state_lock:
        previous = load_state()
        state: dict[str, Any] = {}
        for key in ("unsupported", "bootstrap_refused", "onedir"):
            if isinstance(previous.get(key), dict):
                state[key] = previous[key]
        if isinstance(previous.get("onedir_retired"), list):
            state["onedir_retired"] = previous["onedir_retired"]
        bundled = bundled_binary("yt-dlp")
        if os.path.isabs(bundled) and os.path.isfile(bundled):
            fingerprint = _fingerprint(bundled)
            version = ask(bundled) or _known_version(
                previous.get("bundled"), fingerprint, path=_norm(bundled),
            )
            state["bundled"] = {
                "path": _norm(bundled),
                "fingerprint": fingerprint,
                "version": list(version),
            }
        cached = cached_path()
        fingerprint = _fingerprint(cached)
        if _rejected(previous, fingerprint):
            state["cached"] = {"fingerprint": fingerprint, "version": [], "rejected": True}
        elif fingerprint is not None:
            # No carry-over here: a copy that does not answer is not used,
            # the bundled one is the safe fallback.
            version = ask(str(cached))
            # An empty version = the copy did not answer --version: never used.
            state["cached"] = {"fingerprint": fingerprint, "version": list(version)}
        _save_state(state)
        return state


def _known_version(
    rec: object, fingerprint: list[int] | None, *, path: str | None = None,
) -> tuple[int, ...]:
    """The version recorded for exactly this file, or ().

    For the bundled copy: a ``--version`` that fails once (a slow first
    start, a virus scanner holding the file) must not overwrite a good
    record of the same, unchanged file with ``[]``, which stuck until the
    file changed and made a cached copy win by default. A changed file (a
    new app version) is never given an old version.
    """
    if fingerprint is None or not isinstance(rec, dict):
        return ()
    if rec.get("fingerprint") != fingerprint or rec.get("rejected") is True:
        return ()
    if path is not None and rec.get("path") != path:
        return ()
    return _as_version(rec.get("version"))


def refresh_state_if_stale(*, version_of: VersionOf | None = None) -> bool:
    """Re-ask the versions when a copy changed since the record (e.g. the app
    was updated with a newer bundled yt-dlp). Returns True when it did.
    Skipped while an update runs: the update records the versions itself."""
    with _cond:
        if _updating:
            return False
    prune_old_installs()
    cached = cached_path()
    fingerprint = _fingerprint(cached)
    if fingerprint is None:
        return False
    state = load_state()
    rec = state.get("cached")
    stale = not isinstance(rec, dict) or rec.get("fingerprint") != fingerprint
    bundled = bundled_binary("yt-dlp")
    if os.path.isabs(bundled) and os.path.isfile(bundled):
        brec = state.get("bundled")
        stale = stale or (
            not isinstance(brec, dict)
            or brec.get("path") != _norm(bundled)
            or brec.get("fingerprint") != _fingerprint(bundled)
        )
    if stale:
        refresh_state(version_of=version_of)
    return stale


# Downloads and updates never overlap -------------------------------------------


def wait_bound() -> float:
    """How long a download start waits for a running update (longer on a Mac,
    where an update downloads and unpacks a folder build)."""
    return WAIT_FOR_UPDATE_MACOS_S if _is_macos() else WAIT_FOR_UPDATE_S


def begin_download(key: object, *, timeout: float | None = None) -> None:
    """Register a running yt-dlp download; first waits (bounded) for an update."""
    with _cond:
        _cond.wait_for(lambda: not _updating, timeout=wait_bound() if timeout is None else timeout)
        _running.add(key)


def end_download(key: object) -> None:
    """Unregister a download. Safe to call for a key that never began."""
    with _cond:
        _running.discard(key)
        _cond.notify_all()


@contextlib.contextmanager
def download_running(*, timeout: float | None = None) -> Generator[None, None, None]:
    key = object()
    begin_download(key, timeout=timeout)
    try:
        yield
    finally:
        end_download(key)


def downloads_running() -> int:
    with _cond:
        return len(_running)


def wait_while_updating(timeout: float | None = None) -> bool:
    """Block until no update runs (bounded). True when none runs any more."""
    with _cond:
        return _cond.wait_for(lambda: not _updating, timeout=wait_bound() if timeout is None else timeout)


@dataclass(frozen=True)
class UpdateResult:
    """``status``: "updated", "current" (already the newest), "failed", "busy"
    (a download or another update runs), "unsupported" (no single-file
    yt-dlp to copy) or "offline" (Work offline is on). ``completed``:
    yt-dlp's updater ran and answered (a new
    version, "up to date", or a build this module then rejected); a timeout,
    an updater error such as no network, or a skipped run is not a completed
    check, so the automatic mode does not wait 24 h after it."""

    status: str
    before: tuple[int, ...] = ()
    after: tuple[int, ...] = ()
    message: str = ""
    completed: bool = False


def run_killing_tree(
    cmd: list[str], *, timeout: float, capture_output: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[Any]:
    """``subprocess.run`` whose timeout ends the WHOLE process tree.

    ``subprocess.run`` kills only the direct child on a timeout. A PyInstaller
    onefile yt-dlp is a bootloader plus the real yt-dlp as its child, so the
    child lived on: it could still swap the binary in after "timed out" was
    reported, and its ``_MEI*`` temp folder leaked. Raises
    ``subprocess.TimeoutExpired`` like ``subprocess.run``.
    """
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    # Never the caller's stdin (a worker's command pipe) unless the caller says so.
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    with subprocess.Popen(cmd, **{**new_session_kwargs(), **kwargs}) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _end_tree(proc)
            proc.communicate()  # reap it and close the pipes
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _end_tree(proc: subprocess.Popen[Any]) -> None:
    """Kill ``proc``'s descendants first, so a onefile bootloader can still
    exit by itself and delete its ``_MEI*`` folder; kill the rest of the
    tree if it lingers."""
    try:
        import psutil  # type: ignore[import-not-found] # noqa: PLC0415

        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
    except Exception:  # noqa: BLE001 -- psutil missing or the parent already gone
        logger.debug("could not list the update's child processes", exc_info=True)
    try:
        proc.wait(timeout=5.0)
        return
    except subprocess.TimeoutExpired:
        pass
    kill_process_tree(proc, force=True)


#: Advice for a failure an old yt-dlp causes when this copy of the app cannot
#: update yt-dlp by itself (``can_self_update`` False).
OUTDATED_HINT = (
    "the video downloader in this app may be out of date and cannot update "
    "itself here: install the newest version of this app and retry "
    f"(download page: {RELEASES_PAGE_URL})."
)

_UNSUPPORTED_TEXT = (
    "This copy of the app cannot update its video downloader by itself; "
    "a new app version brings a newer one."
)


def update_cached_copy(
    *,
    log: Callable[[str], None] | None = None,
    timeout: float = UPDATE_TIMEOUT_S,
    run: Callable[..., Any] = run_killing_tree,
    version_of: VersionOf | None = None,
) -> UpdateResult:
    """Bring the user-writable copy to the newest stable yt-dlp.

    Blocking (network; up to ``timeout`` seconds): call it off the Tk thread.
    Refuses with "busy" while a download runs. ``log`` receives yt-dlp's own
    output lines. A Mac installs yt-dlp's folder build from the latest release
    (``_install_onedir``); every other system copies the bundled one.
    """
    global _updating
    bundled = bundled_binary("yt-dlp")
    if not can_self_update(bundled):
        return UpdateResult("unsupported", message=_UNSUPPORTED_TEXT)
    if offline.is_offline():
        return UpdateResult("offline", message=offline.refused("updating the video downloader"))
    with _cond:
        if _updating:
            return UpdateResult("busy", message="The video downloader is already being updated.")
        if _running:
            return UpdateResult(
                "busy", message="A download is running; the video downloader is not updated during one."
            )
        _updating = True
    try:
        say = log or (lambda _m: None)
        ask = version_of or yt_dlp_version
        if _can_copy_bundled(bundled):
            return _update(bundled, say, timeout, run, ask)
        return _install_onedir(bundled, say, ask)
    except Exception as e:  # noqa: BLE001 -- e.g. the cache folder is not writable
        logger.exception("yt-dlp update failed")
        return UpdateResult("failed", message=str(e) or type(e).__name__)
    finally:
        with _cond:
            _updating = False
            _cond.notify_all()


def _seed(bundled: str, target: Path) -> None:
    """Copy the bundled binary into place (temp name, then an atomic rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):  # a build rejected earlier (_discard_copy)
        target.with_name(target.name + ".rejected").unlink()
    tmp = target.with_name(target.name + ".copy")
    shutil.copyfile(bundled, tmp)
    if os.name != "nt":
        tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, target)
    _forget_cached_record()


def _forget_cached_record() -> None:
    """Drop the record of the copy just replaced. A rejection is remembered by
    size and modification time; a new file with the same two numbers (written
    within one timer tick) must not inherit it."""
    with _state_lock:
        state = load_state()
        if state.pop("cached", None) is not None:
            _save_state(state)


def _discard_copy(target: Path, *, version_of: VersionOf) -> None:
    """Remove an unusable copy and record that. A file that cannot be removed
    (held by another program, e.g. a virus scanner) is renamed away; if even
    that fails, the record marks exactly this file as rejected, so it is
    neither used nor updated, and the next update copies the bundled one
    over it."""
    try:
        target.unlink()
    except OSError:
        try:
            os.replace(target, target.with_name(target.name + ".rejected"))
        except OSError:
            logger.warning("Could not remove the unusable yt-dlp copy at %s", target)
            with _state_lock:
                state = load_state()
                state["cached"] = {
                    "fingerprint": _fingerprint(target), "version": [], "rejected": True,
                }
                _save_state(state)
            return
    refresh_state(version_of=version_of)


def _last_error(output: str) -> str:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR")]
    return (errors or lines or [""])[-1]


def _update(
    bundled: str,
    log: Callable[[str], None],
    timeout: float,
    run: Callable[..., Any],
    version_of: VersionOf,
) -> UpdateResult:
    target = cached_path()
    bundled_v = version_of(bundled)
    usable = target.is_file() and not _rejected(load_state(), _fingerprint(target))
    cached_v = version_of(str(target)) if usable else ()
    if not cached_v or (bundled_v and bundled_v > cached_v):
        # Missing, broken, or older than the bundled one (the app itself was
        # updated meanwhile): start again from the bundled copy.
        try:
            _seed(bundled, target)
        except OSError as e:
            refresh_state(version_of=version_of)
            return UpdateResult("failed", message=f"Could not copy the video downloader: {e}")
        log(f"Copied the bundled yt-dlp {version_label(bundled_v)} to {target}")
        cached_v = version_of(str(target))
        if not cached_v:
            _discard_copy(target, version_of=version_of)
            return UpdateResult("failed", message="The copied video downloader does not start.")
    return _run_updater(bundled, target, cached_v, log, timeout, run, version_of)


def _run_updater(
    bundled: str,
    target: Path,
    cached_v: tuple[int, ...],
    log: Callable[[str], None],
    timeout: float,
    run: Callable[..., Any],
    version_of: VersionOf,
) -> UpdateResult:
    """Run yt-dlp's own ``--update-to stable`` on the user-writable copy."""
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "cwd": str(target.parent),
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = run([str(target), "--update-to", "stable"], **kwargs)
    except subprocess.TimeoutExpired:
        refresh_state(version_of=version_of)
        return UpdateResult("failed", before=cached_v, message="The update timed out.")
    except OSError as e:
        refresh_state(version_of=version_of)
        return UpdateResult("failed", before=cached_v, message=f"Could not run the update: {e}")

    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    for line in output.splitlines():
        if line.strip():
            log(line.strip())
    if proc.returncode != 0 and _NON_UPDATEABLE_RE.search(output):
        # This build can never update itself: remember it for this bundled
        # binary, so no later download starts the updater again.
        refresh_state(version_of=version_of)
        with _state_lock:
            state = load_state()
            state["unsupported"] = {"path": _norm(bundled), "fingerprint": _fingerprint(bundled)}
            _save_state(state)
        return UpdateResult(
            "unsupported", before=cached_v, completed=True,
            message=_UNSUPPORTED_TEXT,
        )
    if "skipping verification" in output.lower():
        # yt-dlp installs a build it could not check against SHA2-256SUMS
        # (the release lacked the line) and only refuses to restart into it.
        # Do not run it: drop the copy; the bundled one is used again.
        _discard_copy(target, version_of=version_of)
        return UpdateResult(
            "failed", before=cached_v, completed=True,
            message="The new version could not be verified, so it is not used.",
        )
    state = refresh_state(version_of=version_of)
    rec = state.get("cached")
    after = _as_version(rec.get("version")) if isinstance(rec, dict) else ()
    if not after:
        _discard_copy(target, version_of=version_of)
        return UpdateResult(
            "failed", before=cached_v, completed=True,
            message="The updated video downloader does not start, so it is not used.",
        )
    if after > cached_v:
        return UpdateResult("updated", before=cached_v, after=after, completed=True)
    if proc.returncode == 0:
        return UpdateResult("current", before=cached_v, after=after, completed=True)
    # yt-dlp's updater gave up (offline, GitHub unreachable or rate-limited):
    # nothing was checked, so the automatic mode tries again next time.
    return UpdateResult(
        "failed", before=cached_v, after=after, completed=False,
        message=_last_error(output) or f"yt-dlp exited with code {proc.returncode}",
    )


# macOS: the first update installs yt-dlp's folder build -------------------------


class _BootstrapFailed(Exception):
    """A download that must not be used. ``message`` is plain words for the
    bar. ``completed``: the answer is final (a wrong checksum, a file that does
    not start), so the automatic mode does not try again for 24 h."""

    def __init__(self, message: str, *, completed: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.completed = completed


def _check_release_url(url: str) -> None:
    """Raise unless ``url`` is https on a GitHub release host (default port,
    no user name): the only places the macOS download may come from."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        parts, port = None, -1
    if (
        parts is None
        or parts.scheme != "https"
        or (parts.hostname or "").lower() not in TRUSTED_HOSTS
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
    ):
        raise _BootstrapFailed(
            "The download was sent to an address the app does not trust, so it was not used.",
            completed=True,
        )


class _TrustedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to ``TRUSTED_HOSTS`` over https, and remember them."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urllib.parse.urljoin(req.full_url, newurl)
        _check_release_url(target)
        self.seen.append(target)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext | None:
    """The system's trusted roots plus certifi's: a Python without a system
    certificate store (python.org builds) still verifies GitHub."""
    try:
        import certifi  # noqa: PLC0415
    except ImportError:
        return None
    try:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        return None
    return context


def _network_failure(exc: BaseException) -> _BootstrapFailed:
    """Plain words for a failed request or read. Nothing was installed."""
    if isinstance(exc, offline.OfflineModeError):
        return _BootstrapFailed(str(exc))
    if isinstance(exc, urllib.error.HTTPError):
        if 300 <= exc.code < 400:  # a redirect urllib itself refuses (other scheme, too many)
            return _BootstrapFailed(
                "The download was sent to an address the app does not trust, so it was not used.",
                completed=True,
            )
        return _BootstrapFailed(
            f"GitHub answered with an error ({exc.code}), so nothing was downloaded."
        )
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLError):
        return _BootstrapFailed(
            "The secure connection to GitHub could not be verified, so nothing was downloaded."
        )
    if isinstance(reason, TimeoutError):
        return _BootstrapFailed("The download timed out.")
    return _BootstrapFailed("The internet connection is not working, or GitHub cannot be reached.")


def _time_left(deadline: float) -> float:
    """Seconds until ``deadline`` (a ``time.monotonic`` value); raises when it has passed."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise _BootstrapFailed("The download timed out.")
    return left


def _open_release(url: str, deadline: float) -> tuple[Any, _TrustedRedirects]:
    """GET ``url`` (a trusted address) and return the open answer plus the
    redirects followed. The system proxy settings apply, as for any urllib call.
    Connecting and each wait for data end at the socket timeout or, if sooner,
    at ``deadline``."""
    _check_release_url(url)
    timeout = min(_SOCKET_TIMEOUT_S, _time_left(deadline))
    redirects = _TrustedRedirects()
    handlers: list[Any] = [redirects]
    context = _ssl_context()
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        return opener.open(request, timeout=timeout), redirects
    except (OSError, http.client.HTTPException) as e:
        raise _network_failure(e) from e


def _read_piece(resp: Any) -> bytes:
    """Whatever the connection has next (at most 64 KiB; waits only for the first
    byte), so the caller checks its deadline between pieces. ``read(n)`` would
    keep waiting until n bytes arrived, however slowly."""
    read = getattr(resp, "read1", None) or resp.read
    try:
        return read(_PIECE_BYTES)
    except (OSError, http.client.HTTPException) as e:
        raise _network_failure(e) from e


def _release_tag(urls: list[str]) -> str:
    """The release tag in the first GitHub release URL among ``urls``, or ""."""
    for url in urls:
        parts = urllib.parse.urlsplit(url)
        if (parts.hostname or "").lower() == "github.com":
            m = _RELEASE_TAG_RE.match(parts.path)
            if m:
                return m.group(1)
    return ""


def _tag_version(tag: str) -> tuple[int, ...]:
    """(2026, 8, 19) for the tag "2026.08.19"; () for anything else."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", tag):
        return ()
    return tuple(int(p) for p in tag.split("."))


def _expected_hash(checksums: str, name: str) -> str:
    """The SHA-256 SHA2-256SUMS lists for exactly ``name`` (``<hash>  <name>``
    or ``<hash> *<name>`` lines), lower case."""
    for line in checksums.splitlines():
        m = re.fullmatch(r"\s*([0-9A-Fa-f]{64})\s+\*?(\S+)\s*", line)
        if m and m.group(2) == name:
            return m.group(1).lower()
    raise _BootstrapFailed(
        "The release has no checksum for the macOS build, so it was not installed."
    )


def _fetch_checksum(asset: str, deadline: float) -> tuple[str, str]:
    """(release tag, expected SHA-256 of ``asset``) of the latest stable release."""
    resp, redirects = _open_release(RELEASE_LATEST_URL + CHECKSUMS_ASSET, deadline)
    raw = bytearray()
    with resp:
        while True:
            _time_left(deadline)
            piece = _read_piece(resp)
            if not piece:
                break
            raw += piece
            if len(raw) > _CHECKSUMS_MAX_BYTES:
                raise _BootstrapFailed("The checksum list is larger than expected, so it was not used.")
    tag = _release_tag(redirects.seen)
    return tag, _expected_hash(bytes(raw).decode("utf-8", errors="replace"), asset)


def _too_big() -> _BootstrapFailed:
    return _BootstrapFailed("The download is larger than expected, so it was not installed.")


def _download_checked(url: str, out: IO[bytes], expected: str, deadline: float) -> None:
    """Write ``url`` to ``out`` and raise unless it is complete and its SHA-256
    is ``expected``, all before ``deadline``."""
    resp, _redirects = _open_release(url, deadline)
    digest = hashlib.sha256()
    received = 0
    with resp:
        try:
            length: int | None = int(resp.headers.get("Content-Length"))
        except (TypeError, ValueError):
            length = None
        if length is not None and length > BOOTSTRAP_MAX_BYTES:
            raise _too_big()
        while True:
            _time_left(deadline)
            chunk = _read_piece(resp)
            if not chunk:
                break
            received += len(chunk)
            if received > BOOTSTRAP_MAX_BYTES:
                raise _too_big()
            digest.update(chunk)
            out.write(chunk)
    if received == 0 or (length is not None and received != length):
        raise _BootstrapFailed("The download was cut short, so it was not installed.")
    if digest.hexdigest() != expected:
        raise _BootstrapFailed(
            "The downloaded file does not match its published checksum, so it was not installed.",
            completed=True,
        )


def _remember_refusal() -> None:
    """Record that a verified download did not start on this macOS."""
    with _state_lock:
        state = load_state()
        state["bootstrap_refused"] = {
            "macos": list(macos_version()),
            "until": (now_utc() + timedelta(days=REFUSAL_DAYS)).isoformat(),
        }
        _save_state(state)


# --- safe extraction ------------------------------------------------------------


def _unsafe() -> _BootstrapFailed:
    return _BootstrapFailed(
        "The download contains an unsafe file path, so it was not installed.", completed=True,
    )


def _entry_path(root: str, name: str) -> str:
    """Where the archive entry ``name`` goes under ``root``; raises for an
    absolute or drive path, a backslash, ``..`` or anything that lands outside."""
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"[A-Za-z]:", name):
        raise _unsafe()
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise _unsafe()
    path = os.path.normpath(os.path.join(root, *parts))
    if path == root or os.path.commonpath([root, path]) != root:
        raise _unsafe()
    return path


def _link_target(root: str, path: str, target: str) -> str:
    """``target`` of the link at ``path`` when it stays inside ``root``."""
    if not target or "\x00" in target or target.startswith("/") or re.match(r"[A-Za-z]:", target):
        raise _unsafe()
    resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
    if os.path.commonpath([root, resolved]) != root:
        raise _unsafe()
    return target


def _plan_extraction(z: zipfile.ZipFile, root: str) -> list[tuple[zipfile.ZipInfo, str, str, str]]:
    """Check every entry before anything is written: (info, path, kind, link
    target) with kind "dir", "file" or "link". Raises for too many files, too
    much data, a path outside ``root``, a repeated name, a device or other
    special file, a link leaving ``root`` or a file below a link, or when the
    program ``yt-dlp_macos`` is not a regular file at the top."""
    infos = z.infolist()
    if len(infos) > ONEDIR_MAX_FILES:
        raise _BootstrapFailed("The download holds more files than expected, so it was not installed.")
    if sum(i.file_size for i in infos) > ONEDIR_MAX_UNPACKED_BYTES:
        raise _BootstrapFailed("The download unpacks larger than expected, so it was not installed.")
    plan: list[tuple[zipfile.ZipInfo, str, str, str]] = []
    seen: set[str] = set()
    links: set[str] = set()
    for info in infos:
        path = _entry_path(root, info.filename)
        if path in seen:
            raise _unsafe()
        seen.add(path)
        fmt = stat.S_IFMT(info.external_attr >> 16)
        target = ""
        if info.is_dir():
            kind = "dir"
        elif fmt in (0, stat.S_IFREG):
            kind = "file"
        elif fmt == stat.S_IFLNK and info.file_size <= 4096:
            kind = "link"
            try:
                target = _link_target(root, path, z.read(info).decode("utf-8"))
            except UnicodeDecodeError:
                raise _unsafe() from None
            links.add(path)
        else:
            raise _unsafe()  # a device, a pipe, a socket, an over-long link
        plan.append((info, path, kind, target))
    for _info, path, _kind, _target in plan:
        parent = os.path.dirname(path)
        while len(parent) > len(root):
            if parent in links:
                raise _unsafe()  # written through a link
            parent = os.path.dirname(parent)
    program = os.path.join(root, ONEDIR_EXE)
    if not any(path == program and kind == "file" for _i, path, kind, _t in plan):
        raise _BootstrapFailed("The download does not contain the program, so it was not installed.")
    return plan


def _extract_onedir(source: Path | IO[bytes], dest: Path) -> None:
    """Unpack the release zip (a path or the hashed bytes) into the empty folder ``dest``.

    Everything is checked first (``_plan_extraction``); files keep the
    permission bits of the archive (owner rwx, group/other rx at most: no
    setuid/setgid/sticky, nothing writable by others); links are created last
    and every one of them must still resolve inside ``dest`` once all exist.
    The caller removes
    ``dest`` when this raises.
    """
    root = os.path.abspath(dest)
    try:
        with zipfile.ZipFile(source) as z:
            plan = _plan_extraction(z, root)
            for _info, path, kind, _target in plan:
                if kind == "dir":
                    os.makedirs(path, exist_ok=True)
                    os.chmod(path, 0o755)
            for info, path, kind, _target in plan:
                if kind != "file":
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with z.open(info) as src, open(path, "xb") as out:
                    shutil.copyfileobj(src, out)
                mode = (info.external_attr >> 16) & 0o755
                os.chmod(path, (mode or 0o644) | 0o600)
            real_root = os.path.realpath(root)
            for _info, path, kind, target in plan:
                if kind != "link":
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.symlink(target, path)
            for _info, path, kind, _target in plan:
                # After all exist: a later link can retarget an earlier one.
                if kind == "link" and os.path.commonpath([real_root, os.path.realpath(path)]) != real_root:
                    raise _unsafe()
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as e:
        raise _BootstrapFailed("The download is not a valid archive, so it was not installed.") from e


# --- the install ----------------------------------------------------------------


def _try_lock(handle: IO[bytes]) -> bool:
    """Take the exclusive lock on ``handle`` without waiting; False when another
    process holds it. Only a POSIX system (the Mac) locks; elsewhere the install
    route is never used."""
    if sys.platform == "win32":
        return True
    import fcntl  # noqa: PLC0415

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def _install_lock() -> Generator[bool, None, None]:
    """Hold ``update.lock`` in the cache folder: one install or clean-up at a
    time across app instances. Yields False when another process holds it."""
    folder = cached_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_NAME, "a+b") as handle:
        yield _try_lock(handle)  # closing the file releases the lock


def _parse_time(value: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return moment if moment.tzinfo is not None else None


def _prune_onedirs(keep: str) -> None:
    """Remove the installed folders other than ``keep`` once they are old
    enough. Call with the install lock held.

    A folder the install replaced is "retired" in ``state.json`` and stays for
    ``RETIRED_GRACE``, so a format lookup that started from it keeps its files.
    Any other stray folder (an interrupted install's ``.part``, a folder no
    record names) goes when its own age passes the same grace, which also
    protects the install itself if ``state.json`` is briefly unreadable.
    """
    try:
        entries = list(cached_dir().iterdir())
    except OSError:
        return
    now = now_utc()
    retired: dict[str, Any] = {}
    for rec in load_state().get("onedir_retired") or []:
        if isinstance(rec, dict) and isinstance(rec.get("dir"), str):
            retired[rec["dir"]] = rec.get("at")
    for entry in entries:
        name = entry.name
        try:
            if entry.is_symlink() or not entry.is_dir() or not _ONEDIR_ANY_RE.fullmatch(name) or name == keep:
                continue
            since = _parse_time(retired[name]) if name in retired else None
            if since is None:
                since = datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
            if now - since < RETIRED_GRACE:
                continue
            shutil.rmtree(entry)
            retired.pop(name, None)
        except OSError:
            logger.warning("Could not remove the old yt-dlp folder %s", entry, exc_info=True)
    remaining = [
        {"dir": d, "at": a} for d, a in retired.items() if d != keep and (cached_dir() / d).is_dir()
    ]
    try:
        with _state_lock:
            state = load_state()
            if (state.get("onedir_retired") or []) != remaining:
                if remaining:
                    state["onedir_retired"] = remaining
                else:
                    state.pop("onedir_retired", None)
                _save_state(state)
    except OSError:
        logger.warning("Could not record the retired yt-dlp folders", exc_info=True)


def prune_old_installs() -> None:
    """Remove retired macOS folders whose grace has passed. Off the Tk thread;
    does nothing off macOS, during an update or while another process holds the
    install lock."""
    if not _is_macos():
        return
    with _cond:
        if _updating:
            return
    try:
        with _install_lock() as got:
            if got:
                rec = _installed_onedir(load_state())
                _prune_onedirs(rec["dir"] if rec else "")
    except OSError:
        logger.warning("Could not clean up the old yt-dlp folders", exc_info=True)


def _remove_tree(path: Path | None) -> None:
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def _install_onedir(
    bundled: str, log: Callable[[str], None], version_of: VersionOf,
) -> UpdateResult:
    """Install the latest stable release's ``yt-dlp_macos.zip`` (first install
    and update are the same steps), holding the install lock so two app
    instances never install or clean up at the same time."""
    try:
        with _install_lock() as got:
            if not got:
                return UpdateResult(
                    "busy",
                    message="Another copy of the app is updating the video downloader right now. "
                    "Try again in a minute.",
                )
            return _install_locked(bundled, log, version_of)
    except OSError as e:  # the lock file itself
        return UpdateResult("failed", message=f"Could not save the video downloader: {e}")


def _install_locked(
    bundled: str, log: Callable[[str], None], version_of: VersionOf,
) -> UpdateResult:
    """The install proper, with the install lock held.

    The checksum list comes first (its redirect names the tag); nothing more is
    fetched when that tag is not newer than the installed folder and the
    bundled copy. Otherwise that tag's zip is read into memory under one
    deadline for the whole call (host, size, length and SHA-256 checked, and
    the very bytes that were hashed are what gets unpacked), unpacked safely
    into a ``.part`` folder and started with ``--version`` (asked twice). Only
    then does the folder get its final name and ``state.json`` point at it; the
    old folder is retired (removed after ``RETIRED_GRACE``). Any failure removes
    everything this call made and leaves the previous install, or the bundled
    copy, in use.
    """
    deadline = time.monotonic() + BOOTSTRAP_TIMEOUT_S
    folder = cached_dir()
    part: Path | None = None
    final: Path | None = None
    switched = False
    try:
        tag, expected = _fetch_checksum(BOOTSTRAP_ASSET, deadline)
        previous = _installed_onedir(load_state())
        _prune_onedirs(previous["dir"] if previous else "")
        installed_v: tuple[int, ...] = ()
        if previous is not None and (folder / previous["dir"] / ONEDIR_EXE).is_file():
            installed_v = version_of(str(folder / previous["dir"] / ONEDIR_EXE))
        have = max(installed_v, version_of(bundled))
        latest = _tag_version(tag)
        if latest and have and latest <= have:
            return UpdateResult("current", before=have, after=have, completed=True)
        url = (
            f"{RELEASE_DOWNLOADS_URL}download/{tag}/{BOOTSTRAP_ASSET}"
            if tag else RELEASE_LATEST_URL + BOOTSTRAP_ASSET
        )
        log(f"Downloading yt-dlp {tag or '(latest)'} ({BOOTSTRAP_ASSET}, about {DOWNLOAD_MB_MACOS} MB)")
        archive = io.BytesIO()
        _download_checked(url, archive, expected, deadline)
        part = Path(tempfile.mkdtemp(prefix="onedir-", suffix=".part", dir=str(folder)))
        _extract_onedir(archive, part)
        archive.close()
        program = part / ONEDIR_EXE
        program.chmod(0o755)
        # Asked twice: the first start of new files can be very slow and time
        # out (dyld checks them once), which must not stick as "does not run here".
        if not version_of(str(program)) and not version_of(str(program)):
            if not installed_v:  # a working install keeps the updates available
                _remember_refusal()
            raise _BootstrapFailed(
                "The downloaded video downloader does not start on this Mac, so it is not used.",
                completed=True,
            )
        final = folder / f"onedir-{tag or 'latest'}-{secrets.token_hex(3)}"
        os.replace(part, final)
        part = None
        with _state_lock:  # the switch: only now does state.json name the new folder
            state = load_state()
            retired_before = [r for r in (state.get("onedir_retired") or []) if isinstance(r, dict)]
            retired = list(retired_before)
            if previous is not None:
                retired.append({"dir": previous["dir"], "at": now_utc().isoformat()})
            state["onedir"] = {"dir": final.name, "tag": tag, "sha256": expected}
            if retired:
                state["onedir_retired"] = retired
            state.pop("cached", None)
            _save_state(state)
        switched = True
        after = _as_version((refresh_state(version_of=version_of).get("cached") or {}).get("version"))
        if not after:  # cannot happen right after the check; never leave a broken pointer
            with _state_lock:
                state = load_state()
                if previous is not None:
                    state["onedir"] = previous
                else:
                    state.pop("onedir", None)
                if retired_before:
                    state["onedir_retired"] = retired_before
                else:
                    state.pop("onedir_retired", None)
                state.pop("cached", None)
                _save_state(state)
            switched = False
            refresh_state(version_of=version_of)
            raise _BootstrapFailed(
                "The installed video downloader does not start, so it is not used.", completed=True,
            )
        _prune_onedirs(final.name)
        log(f"Installed yt-dlp {version_label(after)} in {final}")
        return UpdateResult("updated", before=have, after=after, completed=True)
    except _BootstrapFailed as e:
        return UpdateResult("failed", message=e.message, completed=e.completed)
    except OSError as e:
        return UpdateResult("failed", message=f"Could not save the video downloader: {e}")
    finally:
        _remove_tree(part)
        if not switched:
            _remove_tree(final)


def result_text(result: UpdateResult) -> str:
    """One plain sentence about an update, for the bar and the log."""
    if result.status == "updated":
        return (
            f"The video downloader was updated to {version_label(result.after)}. "
            "Try the download again."
        )
    if result.status == "current":
        return (
            f"The video downloader is already the newest version "
            f"({version_label(result.after)}). The problem is probably with the "
            "site or this video."
        )
    if result.status == "failed":
        return (
            f"Could not update the video downloader: {result.message} "
            "The app keeps using the version it has."
        )
    return result.message


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
