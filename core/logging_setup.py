"""Centralized logging configuration.

The Tk app and the worker subprocess both call ``setup_logging`` once at
startup. The worker uses ``stream=sys.stderr`` so its JSON-on-stdout protocol
is never polluted.
"""
from __future__ import annotations

import logging
import logging.handlers
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

    formatter = logging.Formatter(LOG_FORMAT)

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
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)
    return folder
