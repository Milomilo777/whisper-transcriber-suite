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
import glob
import hashlib
import itertools
import json
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO, Callable, Generator

from . import offline

logger = logging.getLogger(__name__)

_USER_AGENT = "WhisperTranscriberSuite"
# Kept free beyond the file itself, so a download never fills the disk.
_FREE_SPACE_MARGIN = 64 * 1024 * 1024
# How many times one call starts over after the server ignored or refused
# the resume range.
_MAX_RESTARTS = 1
_PART_WINDOWS = os.name == "nt"


class DownloadError(RuntimeError):
    """A download failed; the message is readable as-is."""


class DownloadCancelled(DownloadError):
    """The cancel event was set; the ``.part`` file is kept for a resume."""


def raise_if_cancelled(event: threading.Event | None, what: str) -> None:
    """Honor cancellation at a safe download or installation boundary."""
    if event is not None and event.is_set():
        raise DownloadCancelled(f"Cancelled {what}; it resumes next time.")


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
def exclusive_lock(path: Path, busy_message: str, *, strict: bool = False) -> Generator[None]:
    """Hold ``path`` (a lock file) against other threads and processes.

    Non-blocking: a held lock raises :class:`DownloadError` with
    ``busy_message`` at once, since the other holder is doing the same work
    right now. The OS drops the lock when its process dies, so a crash never
    leaves it held. A file system without locks (some network drives) goes
    on without one, logged, unless ``strict`` requires confirmed ownership.
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
            if strict:
                raise DownloadError(f"Could not lock model publication: {e}") from e
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


def part_stat(path: Path, *, recover: bool = False) -> os.stat_result | None:
    """Inspect a partial without following aliases into another file."""
    if recover:
        _sweep_private_parts(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise DownloadError("The saved partial is not a private regular file; use another download folder.")
    return info


def _part_identity(info: os.stat_result) -> tuple[int, int]:
    if not stat.S_ISREG(info.st_mode) or not info.st_ino:
        raise DownloadError("The partial file identity could not be verified.")
    return info.st_dev, info.st_ino


def _copy_prefix(source: BinaryIO, target: BinaryIO, size: int,
                 check_cancel: Callable[[], None]) -> None:
    while size:
        check_cancel()
        chunk = source.read(min(size, 1 << 20))
        if not chunk:
            raise DownloadError("The saved prefix changed while it was copied.")
        target.write(chunk)
        size -= len(chunk)
    target.flush()
    os.fsync(target.fileno())


def _publish_part_exclusive(source: Path, target: Path,
                            check_cancel: Callable[[], None], *,
                            record_created: Callable[[tuple[int, int]], None] = lambda _: None,
                            ) -> tuple[int, int]:
    """Publish without replacing a file another writer inserted at target."""
    identity = _part_identity(source.stat())
    if _PART_WINDOWS:
        os.rename(source, target)  # Windows rename refuses an existing target.
    else:
        try:
            os.link(source, target)
        except FileExistsError:
            raise
        except OSError:
            # Filesystems without hardlinks still get exclusive publication.
            size = source.stat().st_size
            _check_free_space(target.parent, size)
            with open(source, "rb") as reader, open(target, "x+b") as writer:
                identity = _part_identity(os.fstat(writer.fileno()))
                record_created(identity)
                _copy_prefix(reader, writer, size, check_cancel)
        source.unlink()
    return identity


def _record_private_state(folder: Path, record: dict) -> None:
    # A forced exit must leave either the old or the complete new record.
    pending = folder / "state.next"
    with open(pending, "x", encoding="utf-8") as state:
        json.dump(record, state)
        state.flush()
        os.fsync(state.fileno())
    os.replace(pending, folder / "state.json")


def _sweep_private_parts(path: Path) -> None:
    """Recover or remove at most 32 confirmed, unlocked preparation records."""
    pattern = glob.escape(f".{path.name[:64]}.private-") + "*"
    for folder in itertools.islice(path.parent.glob(pattern), 32):
        remove_folder = False
        try:
            info = folder.lstat()
            if (not stat.S_ISDIR(info.st_mode) or folder.is_symlink()
                    or getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                continue
            pending = folder / "state.next"
            state = pending if os.path.lexists(pending) else folder / "state.json"
            if state.is_symlink() or state.stat().st_size > 4096:
                continue
            record = json.loads(state.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or record.get("schema") != 1
                    or record.get("part") != str(path.absolute())
                    or type(record.get("offset")) is not int or record["offset"] < 0):
                continue
            old, private = tuple(record["old"]), tuple(record["private"])
            published = tuple(record.get("published", private))
            if any(len(value) != 2 or any(type(n) is not int for n in value)
                   for value in (old, private, published)):
                continue
            lease = folder / "lease"
            if lease.is_symlink():
                continue
            with exclusive_lock(lease, "Partial preparation is still active", strict=True):
                if {p.name for p in folder.iterdir()} - {"prefix", "previous", "state.json", "state.next", "lease"}:
                    continue
                previous, prefix = folder / "previous", folder / "prefix"
                files = [(p, expected) for p, expected in ((previous, old), (prefix, private))
                         if os.path.lexists(p)]
                if any(p.is_symlink() or _part_identity(p.lstat()) != expected for p, expected in files):
                    continue
                try:
                    current = path.lstat()
                except FileNotFoundError:
                    current = None
                if current is not None and (not stat.S_ISREG(current.st_mode)
                        or getattr(current, "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                    continue
                if current is None and previous.exists():
                    def record_created(created: tuple[int, int]) -> None:
                        record["published"] = created
                        _record_private_state(folder, record)
                    restored = _publish_part_exclusive(previous, path, lambda: None,
                                                       record_created=record_created)
                    current = part_stat(path)
                    if current is None or _part_identity(current) != restored:
                        continue
                    old = restored
                if current is None:
                    continue
                current_id = _part_identity(current)
                if current_id not in (old, private, published):
                    continue
                if current_id == published and current.st_size < record["offset"]:
                    # A no-hardlink filesystem can die during exclusive copy.
                    # Only this recorded new inode may be repaired in place.
                    saved = prefix if prefix.exists() else previous
                    if not saved.exists() or saved.stat().st_size < record["offset"]:
                        continue
                    with open(saved, "rb") as reader, open(path, "r+b") as writer:
                        if (_part_identity(os.fstat(writer.fileno())) != published
                                or _part_identity(path.lstat()) != published):
                            continue
                        _copy_prefix(reader, writer, record["offset"], lambda: None)
                for p, _ in files:
                    p.unlink(missing_ok=True)
                (folder / "state.json").unlink(missing_ok=True)
                pending.unlink(missing_ok=True)
                remove_folder = True
            if remove_folder:
                lease.unlink()
                folder.rmdir()
        except (OSError, ValueError, TypeError, KeyError, DownloadError):
            # Unknown data and live leases are never cleanup permission.
            continue


def prepare_part(path: Path, offset: int, *,
                 check_cancel: Callable[[], None] = lambda: None) -> tuple[int, int] | None:
    """Detach an existing prefix before network I/O; link counts may lie."""
    if offset < 0:
        raise DownloadError("The saved partial has an invalid resume offset.")
    _sweep_private_parts(path)
    before = part_stat(path)
    if offset and (before is None or before.st_size < offset):
        raise DownloadError("The saved partial changed before it could be resumed.")
    check_cancel()
    if before is None:
        return None
    identity = _part_identity(before)
    _check_free_space(path.parent, offset)
    scratch = Path(tempfile.mkdtemp(prefix=f".{path.name[:64]}.private-", dir=path.parent))
    snapshot, previous = scratch / "prefix", scratch / "previous"
    moved = keep = False
    lease = exclusive_lock(scratch / "lease", "Partial preparation is already active", strict=True)
    lease.__enter__()
    try:
        with open(path, "rb") as reader, open(snapshot, "x+b") as writer:
            opened = os.fstat(reader.fileno())
            current = part_stat(path)
            if (current is None or _part_identity(opened) != identity
                    or _part_identity(current) != identity):
                raise DownloadError("The saved partial changed before it could be copied.")
            record = {"schema": 1, "part": str(path.absolute()), "old": identity,
                      "private": _part_identity(os.fstat(writer.fileno())), "offset": offset}
            _record_private_state(scratch, record)
            def record_created(created: tuple[int, int]) -> None:
                record["published"] = created
                _record_private_state(scratch, record)
            _copy_prefix(reader, writer, offset, check_cancel)
            after = os.fstat(reader.fileno())
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                raise DownloadError("The saved partial changed while it was copied.")
        if offset == before.st_size:
            os.utime(snapshot, ns=(before.st_atime_ns, before.st_mtime_ns))
        check_cancel()
        current = part_stat(path)
        if current is None or _part_identity(current) != identity:
            raise DownloadError("The saved partial changed before it could be detached.")
        # Claim the old entry rather than overwriting it. A raced-in file is
        # retained and restored without ever opening it for modification.
        os.rename(path, previous)
        moved = True
        if _part_identity(previous.stat()) != identity:
            raise DownloadError("The saved partial changed while it was detached.")
        private = _publish_part_exclusive(snapshot, path, check_cancel, record_created=record_created)
        current = part_stat(path)
        if current is None or _part_identity(current) != private:
            raise DownloadError("The private partial changed before it could be opened.")
        return private
    except BaseException:
        if moved:
            # Recovery itself can fail; preserve the claimed bytes first.
            keep = True
            if not os.path.lexists(path):
                try:
                    _publish_part_exclusive(previous, path, lambda: None, record_created=record_created)
                except Exception:  # noqa: BLE001 - never erase a failed recovery
                    pass
            keep = previous.exists()
            if keep:
                logger.warning("The earlier saved partial is retained at %s", previous)
        raise
    finally:
        lease.__exit__(None, None, None)
        if not keep:
            for owned in (snapshot, previous, scratch / "state.json", scratch / "state.next", scratch / "lease"):
                try:
                    owned.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                scratch.rmdir()
            except OSError:
                pass


@contextlib.contextmanager
def open_part(path: Path, offset: int, *,
              prepared: tuple[int, int] | None = None) -> Generator[BinaryIO, None, None]:
    """Write only a freshly owned inode, never a preexisting file's bytes."""
    identity = prepared if prepared is not None else prepare_part(path, offset)
    with open(path, "r+b" if identity is not None else "x+b") as stream:
        opened = os.fstat(stream.fileno())
        current = part_stat(path)
        opened_identity = _part_identity(opened)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not opened.st_ino
                or current is None or opened_identity != _part_identity(current)
                or (identity is not None and opened_identity != identity)):
            raise DownloadError("The saved partial changed before it could be written.")
        stream.seek(offset)
        stream.truncate()
        yield stream


def replace_with_retry(src: Path, dst: Path, attempts: int = 10, delay: float = 0.5, *,
                       check_cancel: Callable[[], None] | None = None) -> None:
    """``os.replace`` that waits out a Windows virus scanner holding a fresh file.

    Windows refuses to rename a file (or a folder holding one) that another
    program has open, and scanners open every new DLL and archive for a
    moment. Other errors, and the last refusal, are raised.
    """
    import time

    for attempt in range(attempts):
        if check_cancel is not None:
            check_cancel()
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


def urlopen_https_only(req, timeout: float):  # noqa: ANN001
    """``urllib.request.urlopen`` that never follows a redirect from https to
    another scheme (what the request carries would travel in clear).

    Used for the small best-effort fetches and posts (online config, update
    check, usage statistics, problem report). A replaced
    ``urllib.request.urlopen`` (a test double) is honoured as it is.
    """
    stdlib = getattr(urllib.request.urlopen, "__module__", "") == "urllib.request"
    if not stdlib:
        return urllib.request.urlopen(req, timeout=timeout)
    return _opener.open(req, timeout=timeout)


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
    def check_cancel() -> None:
        raise_if_cancelled(cancel_event, what)
    check_cancel()
    sha256 = sha256.lower()
    if is_verified(dest, size, sha256):
        check_cancel()
        return dest
    offline.require_online(what)
    dest.parent.mkdir(parents=True, exist_ok=True)
    busy = ("This file is already being downloaded (another window of the app?); "
            "wait for that download to finish.")
    with exclusive_lock(dest.with_name(dest.name + ".lock"), busy, strict=True):
        check_cancel()
        if is_verified(dest, size, sha256):  # the lock holder before us finished it
            check_cancel()
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
        check_cancel()
        resumed_hash = file_sha256(part) if resumed else None
        check_cancel()
        if resumed and resumed_hash != sha256:
            # The kept prefix may be from another file (an older pin, a server
            # that changed it): fetch the whole file once before giving up.
            logger.info("Resumed %s does not verify; downloading it again from the start", dest.name)
            _unlink(part)
            fetch_whole_file()
        check_cancel()
        checksum = file_sha256(part)
        check_cancel()
        if checksum != sha256:
            _unlink(part)
            raise DownloadError(
                f"The file for {what} does not match its pinned checksum; it was deleted, "
                "not installed. Try again later."
            )
        try:
            replace_with_retry(part, dest, check_cancel=check_cancel)
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
    info = part_stat(part, recover=True)
    offset = info.st_size if info is not None else 0
    if offset > size:
        _unlink(part)
        offset = 0
    if offset == size:
        return True
    # A network share may retain an aliased original while its private prefix
    # is copied. Reserve both that prefix and the remaining transfer.
    _check_free_space(part.parent, size)
    def check_cancel() -> None:
        raise_if_cancelled(cancel_event, what)
    prepared = prepare_part(part, offset, check_cancel=check_cancel)
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
            with open_part(part, start, prepared=prepared) as f:
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
