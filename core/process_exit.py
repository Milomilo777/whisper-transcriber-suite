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
import subprocess
import sys
import threading
import time
from collections.abc import Callable

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

    try:
        note = threading.Thread(target=_write, name="exit-note", daemon=True)
        note.start()
    except RuntimeError:  # e.g. "can't start new thread": the note is optional, the exit is not
        return
    note.join(0.2)


# --- restart: start the app again once this process has ended --------------------------------

_relaunch: list[list[str]] = []


def relaunch_command() -> list[str] | None:
    """The command that starts this app again (no arguments), or None where that is not supported.

    Windows only: the frozen exe, or the interpreter with the ``gui.py`` this run started from
    (what the installer's shortcuts start). Elsewhere the caller keeps "restart the app yourself".
    """
    if sys.platform != "win32" or not sys.executable:
        return None
    if getattr(sys, "frozen", False):
        return [sys.executable]
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script.lower().endswith(".py") or not os.path.isfile(script):
        return None
    return [sys.executable, script]


def request_relaunch(command: list[str] | None = None) -> bool:
    """Ask :func:`end_process` to start the app again after it has ended. False if unsupported."""
    command = command or relaunch_command()
    if not command:
        return False
    _relaunch[:] = [list(command)]
    return True


def cancel_relaunch() -> None:
    _relaunch.clear()


def relaunch_requested() -> bool:
    return bool(_relaunch)


#: Argument the replacement process gets: it waits for the old process (this PID) to be gone.
WAIT_FOR_PID_ARG = "--wait-for-pid"
#: Longest the replacement waits for the old process before it starts anyway.
WAIT_FOR_PID_TIMEOUT_S = 20.0
_STILL_ACTIVE = 259


def pid_alive(pid: int) -> bool:
    """True while process ``pid`` runs. Never raises; an unreadable PID counts as gone."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = getattr(ctypes, "windll").kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
            if not handle:
                return False
            try:
                code = ctypes.c_ulong(0)
                if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    return False
                return code.value == _STILL_ACTIVE
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:  # noqa: BLE001 - not knowing is not a reason to hang the start
        logger.debug("Could not look at process %s", pid, exc_info=True)
        return False


def consume_wait_for_pid(
    argv: list[str],
    *,
    alive: Callable[[int], bool] = pid_alive,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = WAIT_FOR_PID_TIMEOUT_S,
) -> list[str]:
    """Handle ``--wait-for-pid N`` at the very start of the program (before any single-instance
    lock or config write): wait, at most ``timeout`` seconds, until process N has ended. Returns
    ``argv`` without the option, so nothing later sees it and a restart never repeats it."""
    if WAIT_FOR_PID_ARG not in argv:
        return argv
    at = argv.index(WAIT_FOR_PID_ARG)
    rest = argv[:at] + argv[at + 2:]
    try:
        pid = int(argv[at + 1])
    except (IndexError, ValueError):
        logger.warning("Ignoring %s without a process id", WAIT_FOR_PID_ARG)
        return argv[:at] + argv[at + 1:]
    deadline = clock() + timeout
    while alive(pid):
        if clock() >= deadline:
            logger.warning("Process %s is still running after %.0f s; starting anyway", pid, timeout)
            break
        sleep(0.1)
    return rest


def _spawn_relaunch() -> None:
    """Start the requested command detached; a failure is logged, the exit goes on."""
    if not _relaunch:
        return
    # The replacement waits for this process to end (it starts before the hard exit below): a
    # single-instance check or a file this process still holds must not reject it.
    command = _relaunch[0] + [WAIT_FOR_PID_ARG, str(os.getpid())]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(  # noqa: S603 - our own interpreter and script
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=flags, cwd=os.path.dirname(_relaunch[0][-1]) or None,
        )
    except (OSError, ValueError):
        logger.exception("Could not start the app again")


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
    _spawn_relaunch()
    _hard_exit(code)
