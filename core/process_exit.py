"""End the desktop app's process once its own teardown is finished.

Closing the window ends Tk's ``mainloop`` and ``App.on_exit`` has already stopped the
workers, the server and the tray and closed the history database. Python would still
wait at interpreter exit for every non-daemon thread, and a model download started in
this process (huggingface_hub runs it on an 8-thread ``ThreadPoolExecutor``, which
cannot be interrupted) kept the process alive, window-less and holding the Windows
``AppMutex``, until the whole model was fetched. A killed download is safe: the next
run resumes the ``.incomplete`` blobs (see ``core.model_manager``).

All threads this app starts itself are daemon threads, and it registers no ``atexit``
handlers of its own, so nothing it must save is left to run after this point.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)


def _hard_exit(code: int) -> None:
    """End the process at once, skipping interpreter shutdown (tests replace this)."""
    os._exit(code)


def _blocking_threads() -> list[str]:
    """Names of non-daemon threads that would make a normal exit wait."""
    me = threading.current_thread()
    return [t.name for t in threading.enumerate() if t is not me and t.is_alive() and not t.daemon]


def _flush_streams() -> None:
    # A stream can be None (pythonw), closed, or a broken pipe: none of that may stop the exit.
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        if stream is None:
            continue
        try:
            stream.flush()
        except (OSError, ValueError):
            pass


def end_process(code: int = 0) -> None:
    """Flush the logs and the standard streams, then end the process with *code*.

    Call it only after the app's orderly teardown. Never use it to hide a crash: an
    exception must propagate so ``sys.excepthook`` (``app.crash_report``) sees it.
    """
    blockers = _blocking_threads()
    if blockers:
        logger.info(
            "Ending the process without waiting for %d background thread(s): %s",
            len(blockers), ", ".join(blockers),
        )
    try:
        logging.shutdown()
    except Exception:  # noqa: BLE001 - nothing may keep the process alive now
        pass
    _flush_streams()
    _hard_exit(code)
