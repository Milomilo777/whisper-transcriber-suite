"""Centralized logging configuration.

The Tk app and the worker subprocess both call ``setup_logging`` once at
startup. The worker uses ``stream=sys.stderr`` so its JSON-on-stdout protocol
is never polluted.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import time
from pathlib import Path

from .config import user_log_dir

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
LOG_FILENAME = "app.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

UI_LOGGER_NAME = "whisper.ui"

# worker_log_filename() gives every worker process its own file, and
# core/voice_clone_worker.py names its own voiceclone-worker-<pid>.log;
# nothing else ever removes them, so the log dir would grow one file per
# worker (plus rotations) forever. _prune_worker_logs() keeps the newest
# few and drops the stale rest. The globs below must match exactly the
# two known producer names — a bare "*worker-*.log*" also catches
# unrelated user files that merely contain "worker-" (e.g. a dropped-in
# "reworker-output.log") and would delete them.
WORKER_LOG_KEEP = 10
WORKER_LOG_MAX_AGE_DAYS = 14
_WORKER_LOG_GLOBS = ("worker-*.log*", "voiceclone-worker-*.log*")

_configured = False

# A signed download link (CDN policy / signature / key id) carries its secret
# in the query string, and some third-party libraries log the full URL. Every
# log handler formats through RedactingFormatter so none of it reaches a file.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_REDACTED_TAIL = "?<redacted>"
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
_YOUTUBE_KEEP = ("v", "list")
_PLAIN_ID_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


def _youtube_query(query: str) -> str:
    """The ``v`` / ``list`` parameters of a YouTube query (plain ids only)."""
    kept = []
    for part in query.split("&"):
        name, sep, value = part.partition("=")
        if sep and name in _YOUTUBE_KEEP and _PLAIN_ID_RE.match(value):
            kept.append(f"{name}={value}")
    return ("?" + "&".join(kept)) if kept else _REDACTED_TAIL


def _redact_url(token: str) -> str:
    """One URL (everything up to whitespace) cut to scheme://host/path.

    User info is stripped only from the authority (before the first ``/``,
    ``?`` or ``#``); everything from the first ``?`` or ``#`` on is dropped,
    whatever characters it holds. Idempotent.
    """
    scheme_end = token.index("//") + 2
    scheme, rest = token[:scheme_end], token[scheme_end:]
    cut = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=len(rest))
    authority, remainder = rest[:cut], rest[cut:]
    authority = authority.rpartition("@")[2]
    q = min((i for i in (remainder.find(c) for c in "?#") if i >= 0), default=-1)
    if q < 0:
        return f"{scheme}{authority}{remainder}"
    path, tail = remainder[:q], remainder[q:]
    if tail == _REDACTED_TAIL:
        mark = _REDACTED_TAIL
    elif tail.startswith("?"):
        host = authority.lower().rpartition(":")[0] if authority.count(":") == 1 else authority.lower()
        query = tail[1:].split("#", 1)[0]
        mark = _youtube_query(query) if host in _YOUTUBE_HOSTS else _REDACTED_TAIL
    else:
        mark = ""  # a bare fragment
    return f"{scheme}{authority}{path}{mark}"


def redact_urls(text: str) -> str:
    """``text`` with every http(s) URL cut to scheme://host/path.

    User info, query string and fragment are dropped (a dropped query is
    shown as ``?<redacted>``; a YouTube link keeps its ``v`` and ``list``
    ids). A URL ends at the first whitespace, so nothing after a ``?``
    survives. Applying it twice gives the same text.
    """
    return _URL_RE.sub(lambda m: _redact_url(m.group(0)), text)


# Log messages carry text the app does not control (a video title, a file name
# with a newline, a value read back from hardware.json, an HTTP request line).
# Every character str.splitlines() treats as a line break is shown as an escape
# so such a value cannot start a second, forged log line.
_LINE_BREAKS = {
    ord("\n"): "\\n", ord("\r"): "\\r", ord("\x0b"): "\\x0b",
    ord("\x0c"): "\\x0c", ord("\x85"): "\\x85",
    ord(" "): "\\u2028", ord(" "): "\\u2029",
}


class RedactingFormatter(logging.Formatter):
    """A Formatter whose whole output (message and traceback) is URL-redacted.

    The message is also kept to one line: line breaks in it are escaped. The
    traceback that follows keeps its own lines.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        one_line = message.translate(_LINE_BREAKS)
        if one_line != message:
            # A copy, so another handler of the same record sees the original.
            record = logging.makeLogRecord(record.__dict__)
            record.msg, record.args = one_line, None
        return redact_urls(super().format(record))



def _prune_worker_logs(log_dir: Path) -> None:
    """Best-effort cleanup of stale per-process worker logs.

    Deletes files older than ``WORKER_LOG_MAX_AGE_DAYS``, always keeping
    the ``WORKER_LOG_KEEP`` most recent worker-named files so a long-lived
    process's own log is never unlinked out from under its open handler.
    ``app.log`` and unrelated files are never touched. Never raises: a
    file that is locked by another process is simply skipped.
    """
    try:
        found: dict[Path, float] = {}
        for glob in _WORKER_LOG_GLOBS:
            for p in log_dir.glob(glob):
                if p.is_file() and p not in found:
                    found[p] = p.stat().st_mtime
        candidates = sorted(found, key=lambda p: found[p], reverse=True)
    except OSError:
        return
    cutoff = time.time() - WORKER_LOG_MAX_AGE_DAYS * 24 * 60 * 60
    for path in candidates[WORKER_LOG_KEEP:]:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _quiet_third_parties():
    for name in ("urllib3", "requests", "huggingface_hub", "filelock"):
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(level: str = "INFO", stream=None, filename: str | None = None):
    """Configure the root logger. Idempotent; safe to call more than once.

    ``filename`` overrides the default ``app.log`` so a second process can
    own its OWN log file. A ``RotatingFileHandler`` rolls over by renaming
    the active file (app.log -> app.log.1); on Windows you cannot rename a
    file another process still holds open, so when the GUI process and any
    worker subprocess share one app.log the rollover raises
    ``PermissionError`` (WinError 32), logging swallows it, the rotation
    silently fails and the file grows past the 5 MB x 3 cap. The worker
    therefore passes a per-process name (``worker-<pid>.log``) so each
    process rotates its own file independently.

    Also calls :func:`_prune_worker_logs` so the per-process files don't
    accumulate forever.
    """
    global _configured

    log_dir = user_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    _prune_worker_logs(log_dir)
    log_file = log_dir / (filename or LOG_FILENAME)

    root = logging.getLogger()
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(numeric)

    if _configured:
        return log_file

    formatter = RedactingFormatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(stream or sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _quiet_third_parties()

    _configured = True
    return log_file


def worker_log_filename(pid: int | None = None) -> str:
    """Per-process worker log name so each worker rotates its own file
    instead of fighting the GUI process over a single shared app.log
    (see ``setup_logging`` for the Windows-rename rationale)."""
    import os

    return f"worker-{pid if pid is not None else os.getpid()}.log"


def get_ui_logger() -> logging.Logger:
    """The user-facing log channel. Used by the Tk console widget feed."""
    return logging.getLogger(UI_LOGGER_NAME)


def open_log_folder():
    """Open the platformdirs log directory in the OS file manager."""
    import os
    import subprocess

    folder = user_log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], stdin=subprocess.DEVNULL, check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], stdin=subprocess.DEVNULL, check=False)
    return folder
