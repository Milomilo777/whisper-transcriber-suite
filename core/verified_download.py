"""Download one pinned file: resumable, cancellable, checked before it lands.

The shared helper for files whose exact size and SHA-256 the app knows in
advance (the llama.cpp runtime archive of ``core.llama_runtime``; later the
models). ``download_verified`` guarantees:

* Work offline refuses the download before any request is sent;
* a free-space check before the first byte;
* bytes go to ``<dest>.part``; a cut connection or a cancel keeps that file,
  and the next call resumes it with an HTTP ``Range`` request (a server that
  ignores the range is detected and the download restarts from zero);
* the destination appears only after the byte count AND the SHA-256 match,
  with one ``os.replace`` -- so a half or forged file is never seen under
  the real name; a mismatching ``.part`` is deleted, never resumed;
* one download per destination across threads and processes (an OS file lock
  next to the file, dropped by the OS when its process dies).

Stdlib only (``urllib``), Tk-free; safe to import from the worker, the
server and the UI.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Generator

from . import offline

logger = logging.getLogger(__name__)

_USER_AGENT = "WhisperTranscriberSuite"
# Kept free beyond the file itself, so a download never fills the disk.
_FREE_SPACE_MARGIN = 64 * 1024 * 1024
# How many times one call starts over after the server ignored or refused
# the resume range.
_MAX_RESTARTS = 1


class DownloadError(RuntimeError):
    """A download failed; the message is readable as-is."""


class DownloadCancelled(DownloadError):
    """The cancel event was set; the ``.part`` file is kept for a resume."""


ProgressCallback = Callable[[int, int], None]


def part_path(dest: Path) -> Path:
    """Where the bytes of ``dest`` collect until they are verified."""
    return dest.with_name(dest.name + ".part")


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def is_verified(path: Path, size: int, sha256: str) -> bool:
    """True when ``path`` is a file of exactly ``size`` bytes with that SHA-256."""
    try:
        if not path.is_file() or path.stat().st_size != size:
            return False
        return file_sha256(path) == sha256.lower()
    except OSError:
        return False


@contextlib.contextmanager
def exclusive_lock(path: Path, busy_message: str) -> Generator[None]:
    """Hold ``path`` (a lock file) against other threads and processes.

    Non-blocking: a held lock raises :class:`DownloadError` with
    ``busy_message`` at once, since the other holder is doing the same work
    right now. The OS drops the lock when its process dies, so a crash never
    leaves it held. A file system without locks (some network drives) goes
    on without one, logged.
    """
    from .config import _lock_is_contended

    fh = open(path, "a+b")
    locked = False
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as e:
            if _lock_is_contended(e):
                raise DownloadError(busy_message) from e
            logger.warning("Could not lock %s (%s); going on without the lock", path, e)
        try:
            yield
        finally:
            if locked:
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    finally:
        fh.close()


def replace_with_retry(src: Path, dst: Path, attempts: int = 10, delay: float = 0.5) -> None:
    """``os.replace`` that waits out a Windows virus scanner holding a fresh file.

    Windows refuses to rename a file (or a folder holding one) that another
    program has open, and scanners open every new DLL and archive for a
    moment. Other errors, and the last refusal, are raised.
    """
    import time

    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never from https to anything else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if req.full_url.lower().startswith("https:") and not newurl.lower().startswith("https:"):
            raise urllib.error.HTTPError(
                newurl, code, f"refused a redirect away from https to {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnlyRedirects)


def _check_free_space(folder: Path, needed: int) -> None:
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return  # unknown: let the write itself fail if the disk is full
    if free < needed + _FREE_SPACE_MARGIN:
        raise DownloadError(
            f"Not enough free disk space in {folder}: the download needs "
            f"{(needed + _FREE_SPACE_MARGIN) / 1e6:.0f} MB, {free / 1e6:.0f} MB are free."
        )


_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)


def _resume_offset(response: object, offset: int) -> int:
    """Where the body of ``response`` starts: ``offset`` for a matching 206, else 0.

    A 200 means the server ignored the range and sends the whole file; a 206
    for a different range is treated the same way (start over).
    """
    status = getattr(response, "status", 200)
    if offset and status == 206:
        m = _CONTENT_RANGE_RE.match(response.headers.get("Content-Range") or "")  # type: ignore[attr-defined]
        if m and int(m.group(1)) == offset:
            return offset
    return 0


def download_verified(
    url: str,
    dest: Path,
    *,
    size: int,
    sha256: str,
    what: str,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    chunk_size: int = 1 << 18,
    timeout: float = 60.0,
) -> Path:
    """Download ``url`` to ``dest`` if it is not there yet; return ``dest``.

    ``size`` and ``sha256`` are the pinned values the file must match.
    ``what`` names the action for the Work offline refusal ("downloading
    ..."). ``progress_cb(done_bytes, total_bytes)`` is called as bytes
    arrive (from this thread). Raises :class:`DownloadCancelled` when
    ``cancel_event`` is set, :class:`DownloadError` on any other failure,
    and ``core.offline.OfflineModeError`` while Work offline is on.
    """
    sha256 = sha256.lower()
    if is_verified(dest, size, sha256):
        return dest
    offline.require_online(what)
    dest.parent.mkdir(parents=True, exist_ok=True)
    busy = ("This file is already being downloaded (another window of the app?); "
            "wait for that download to finish.")
    with exclusive_lock(dest.with_name(dest.name + ".lock"), busy):
        if is_verified(dest, size, sha256):  # the lock holder before us finished it
            return dest
        part = part_path(dest)

        def fetch_whole_file() -> None:
            for _attempt in range(_MAX_RESTARTS + 1):
                if _fetch(url, part, size=size, what=what, progress_cb=progress_cb,
                          cancel_event=cancel_event, chunk_size=chunk_size, timeout=timeout):
                    return
            raise DownloadError(f"Could not download {what}: the server kept refusing the resume.")

        resumed = part.is_file()
        fetch_whole_file()
        if resumed and file_sha256(part) != sha256:
            # The kept prefix may be from another file (an older pin, a server
            # that changed it): fetch the whole file once before giving up.
            logger.info("Resumed %s does not verify; downloading it again from the start", dest.name)
            _unlink(part)
            fetch_whole_file()
        if file_sha256(part) != sha256:
            _unlink(part)
            raise DownloadError(
                f"The file for {what} does not match its pinned checksum; it was deleted, "
                "not installed. Try again later."
            )
        try:
            replace_with_retry(part, dest)
        except OSError as e:
            raise DownloadError(f"Could not save the file for {what}: {e}") from e
    logger.info("Downloaded and verified %s (%d bytes)", dest, size)
    return dest


def _fetch(
    url: str,
    part: Path,
    *,
    size: int,
    what: str,
    progress_cb: ProgressCallback | None,
    cancel_event: threading.Event | None,
    chunk_size: int,
    timeout: float,
) -> bool:
    """Bring ``part`` to ``size`` bytes. False = start over (the range was refused)."""
    offset = part.stat().st_size if part.is_file() else 0
    if offset > size:
        _unlink(part)
        offset = 0
    if offset == size:
        return True
    _check_free_space(part.parent, size - offset)
    headers = {"User-Agent": _USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as r:
            start = _resume_offset(r, offset)
            if offset and not start:
                logger.info("Server ignored the resume range for %s; starting over", url)
            done = start
            last_pct = -1
            with open(part, "r+b" if start else "wb") as f:
                f.seek(start)
                f.truncate()
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadCancelled(f"Cancelled {what}; it resumes next time.")
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    if done + len(chunk) > size:
                        f.close()
                        _unlink(part)
                        raise DownloadError(
                            f"The file for {what} is larger than expected; it was deleted."
                        )
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb is not None:
                        pct = done * 100 // size if size else 100
                        if pct != last_pct:
                            last_pct = pct
                            progress_cb(done, size)
                f.flush()
                os.fsync(f.fileno())
    except DownloadError:
        raise
    except offline.OfflineModeError:
        raise
    except urllib.error.HTTPError as e:
        if e.code == 416 and offset:  # the range is past the server's end
            _unlink(part)
            return False
        raise DownloadError(f"Could not download {what}: {e}") from e
    except Exception as e:  # noqa: BLE001 -- network drops, timeouts, cut streams
        raise DownloadError(
            f"Could not download {what}: {e}. Try again; it resumes where it stopped."
        ) from e
    if done < size:
        raise DownloadError(
            f"The download for {what} stopped early ({done} of {size} bytes). "
            "Try again; it resumes where it stopped."
        )
    return True


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not delete %s: %s", path, e)
