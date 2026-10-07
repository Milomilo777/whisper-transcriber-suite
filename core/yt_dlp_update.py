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
folder ("onedir") builds, which the macOS app bundles. ``can_self_update`` is
False there and the app keeps using the bundled copy.

An update never runs while a yt-dlp download runs, and a download that starts
during an update waits for it (``download_running`` / ``update_cached_copy``).

Tk-free; safe to import from the worker, the server and the UI.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Mapping

from . import offline
from ._proc import kill_process_tree, new_session_kwargs
from .config import user_cache_dir
from .js_runtime import find_deno, mentions_missing_js_runtime, yt_dlp_version
from .paths import bundled_binary

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

AUTO_INTERVAL = timedelta(hours=24)
#: Roughly what one update downloads (the Windows yt-dlp.exe); shown on the bar.
DOWNLOAD_MB = 18
UPDATE_TIMEOUT_S = 180
#: How long a download start waits for a running update before going ahead:
#: the updater itself plus two ``--version`` calls (up to 120 s each on a
#: slow first start) and the copy.
WAIT_FOR_UPDATE_S = UPDATE_TIMEOUT_S + 2 * 120 + 60

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
    """Where the user-writable copy lives (may not exist yet)."""
    return cached_dir() / _exe_name()


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
    """True when the bundled yt-dlp is a single-file build we can copy.

    A bare name (no bundled binary; PATH lookup on Linux/macOS from source)
    gives nothing to copy. yt-dlp's folder builds (an executable next to an
    ``_internal`` folder; the macOS app bundles one) refuse ``--update``.
    """
    path = bundled if bundled is not None else bundled_binary("yt-dlp")
    if not (os.path.isabs(path) and os.path.isfile(path)):
        return False
    real = os.path.realpath(path)
    return not os.path.isdir(os.path.join(os.path.dirname(real), "_internal"))


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
        bundled = bundled_binary("yt-dlp")
        if os.path.isabs(bundled) and os.path.isfile(bundled):
            state["bundled"] = {
                "path": _norm(bundled),
                "fingerprint": _fingerprint(bundled),
                "version": list(ask(bundled)),
            }
        cached = cached_path()
        fingerprint = _fingerprint(cached)
        if _rejected(previous, fingerprint):
            state["cached"] = {"fingerprint": fingerprint, "version": [], "rejected": True}
        elif fingerprint is not None:
            version = ask(str(cached))
            # An empty version = the copy did not answer --version: never used.
            state["cached"] = {"fingerprint": fingerprint, "version": list(version)}
        _save_state(state)
        return state


def refresh_state_if_stale(*, version_of: VersionOf | None = None) -> bool:
    """Re-ask the versions when a copy changed since the record (e.g. the app
    was updated with a newer bundled yt-dlp). Returns True when it did.
    Skipped while an update runs: the update records the versions itself."""
    with _cond:
        if _updating:
            return False
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


def begin_download(key: object, *, timeout: float = WAIT_FOR_UPDATE_S) -> None:
    """Register a running yt-dlp download; first waits (bounded) for an update."""
    with _cond:
        _cond.wait_for(lambda: not _updating, timeout=timeout)
        _running.add(key)


def end_download(key: object) -> None:
    """Unregister a download. Safe to call for a key that never began."""
    with _cond:
        _running.discard(key)
        _cond.notify_all()


@contextlib.contextmanager
def download_running(*, timeout: float = WAIT_FOR_UPDATE_S) -> Generator[None, None, None]:
    key = object()
    begin_download(key, timeout=timeout)
    try:
        yield
    finally:
        end_download(key)


def downloads_running() -> int:
    with _cond:
        return len(_running)


def wait_while_updating(timeout: float = WAIT_FOR_UPDATE_S) -> bool:
    """Block until no update runs (bounded). True when none runs any more."""
    with _cond:
        return _cond.wait_for(lambda: not _updating, timeout=timeout)


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
    output lines.
    """
    global _updating
    bundled = bundled_binary("yt-dlp")
    if not can_self_update(bundled):
        return UpdateResult(
            "unsupported",
            message="This copy of the app cannot update its video downloader by itself.",
        )
    if offline.is_offline():
        return UpdateResult("offline", message=offline.message("updating the video downloader"))
    with _cond:
        if _updating:
            return UpdateResult("busy", message="The video downloader is already being updated.")
        if _running:
            return UpdateResult(
                "busy", message="A download is running; the video downloader is not updated during one."
            )
        _updating = True
    try:
        return _update(bundled, log or (lambda _m: None), timeout, run, version_of or yt_dlp_version)
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
    # A rejection is remembered by size and modification time. It belongs to the
    # file just replaced; a new file with the same two numbers (written within
    # one timer tick) must not inherit it.
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
