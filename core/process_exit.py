"""End the desktop app's process once its own teardown is finished.

Closing the window ends Tk's ``mainloop`` and ``App.on_exit`` has already stopped the
workers, the server and the tray and closed the history database. Python would still
wait at interpreter exit for every non-daemon thread, and a model download started in
this process (huggingface_hub runs it on an 8-thread ``ThreadPoolExecutor``, which
cannot be interrupted) kept the process alive, window-less and holding the Windows
``AppMutex``, until the whole model was fetched. A killed download is safe: the next
run resumes the ``.incomplete`` blobs (see ``core.model_manager``).

All threads this app starts itself are daemon threads and it registers no ``atexit``
handlers of its own. The one background job that must not be cut is an on-demand package
install (its merge phase); ``App.on_exit`` stops pip and waits for it before the window is
destroyed (``core.optional_deps.wait_until_idle``), so nothing is left to run after this
point except best-effort work such as a usage-stats POST.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

#: Longest the final flush (Sentry, log handlers, standard streams) may take before the
#: process ends anyway: a stuck handler (a network log share, a blocked pipe) must not
#: keep the window-less process alive.
FLUSH_TIMEOUT_S = 3.0
#: How long Sentry may take to send what it still holds.
_SENTRY_FLUSH_S = 2


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


def _flush_everything() -> None:
    """Sentry (if the app loaded it), then the log handlers, then the standard streams."""
    sentry = sys.modules.get("sentry_sdk")
    if sentry is not None:
        try:
            sentry.flush(timeout=_SENTRY_FLUSH_S)
        except Exception:  # noqa: BLE001 - an unsent crash report must not block the exit
            pass
    try:
        logging.shutdown()
    except Exception:  # noqa: BLE001 - nothing may keep the process alive now
        pass
    _flush_streams()


def _say_flush_timed_out() -> None:
    """Best-effort note on file descriptor 2 that the flush was cut; never blocks the exit.

    Not a Python stream and not the log: the stuck flush may hold a stream's lock (a
    stderr pipe nobody reads), and a write to the same stream would wait behind it for
    ever. Even ``os.write`` can block on a full pipe, so it runs on a daemon thread that
    is waited for only a moment.
    """
    message = b"exit: the final flush did not finish in time; ending anyway" + bytes([10])

    def _write() -> None:
        try:
            os.write(2, message)
        except (OSError, ValueError):
            pass

    note = threading.Thread(target=_write, name="exit-note", daemon=True)
    note.start()
    note.join(0.2)


def end_process(code: int = 0) -> None:
    """Flush Sentry, the logs and the standard streams, then end the process with *code*.

    The flush runs on a daemon thread that is waited for at most ``FLUSH_TIMEOUT_S``: the
    process ends then even if a handler is stuck.

    Call it only after the app's orderly teardown. Never use it to hide a crash: an
    exception must propagate so ``sys.excepthook`` (``app.crash_report``) sees it.
    """
    blockers = _blocking_threads()
    if blockers:
        logger.info(
            "Ending the process without waiting for %d background thread(s): %s",
            len(blockers), ", ".join(blockers),
        )
    flusher = threading.Thread(target=_flush_everything, name="exit-flush", daemon=True)
    flusher.start()
    flusher.join(FLUSH_TIMEOUT_S)
    if flusher.is_alive():
        _say_flush_timed_out()
    _hard_exit(code)
