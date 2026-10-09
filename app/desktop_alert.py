"""A desktop notification when a transcription job finishes, on macOS (card C2.73).

Windows has its tray toast (``app.widgets.tray``); the Mac has no tray, so a finished job used to
make only the chime. ``job_done`` is the one place the completion signal fans out to a desktop
notification: it does nothing off macOS, so Windows and Linux behave exactly as before.

How the notification is posted (proved in the macOS 13 VM, see ``docs/MACOS_BUILD_NOTES.md``):
``/usr/bin/osascript`` runs a fixed three-line AppleScript whose ``run`` handler reads the text and
the title from its ARGUMENTS (``item 1 of argv``). The text goes to the process as list items after
``--``, never into the script and never through a shell, so quotes, backslashes, new lines, a
leading ``-`` and Persian text need no escaping and cannot become code. The process runs on a
worker thread with a timeout: the Tk thread never waits for it.

Limits, by design of ``display notification``: the notification belongs to "Script Editor" (the
host of ``osascript``), so clicking it opens Script Editor, not this app; the app cannot make a
click bring its window forward, and nothing here promises that. No pyobjc and no dependency.

The existing "Chime on completion" setting (View menu, ``chime_on_complete``) is the only
completion-cue setting there is, so it also switches this notification off; no second option.
A notification is posted only while the person is not looking at the app (see
``window_has_focus``: the app is active and its window is on screen): a person looking at the
window already sees the result card.

The banner follows the chime's completion events, one banner per user job, on the job's last stage:
a finished transcription (``job_done``), a finished download (``download_done``, only when no
transcription follows it), a finished subtitle burn (``burn_done``: a manual burn, or the end of a
"Make subtitled video" chain, whose transcription stage posts nothing). When the last transcription
of a queue of two or more finishes, one summary replaces that job's own banner. A chain that ends in
an error posts one "Subtitled video not made" banner (``chain_failed``); other failures and
cancellations post nothing.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from typing import Any

from app import mac_native

logger = logging.getLogger(__name__)

#: Absolute path: a GUI app's PATH is minimal, and a bare name would run whatever comes first.
OSASCRIPT = "/usr/bin/osascript"
#: Seconds before a stuck ``osascript`` is killed (it normally returns in well under a second).
OSASCRIPT_TIMEOUT_S = 15

#: Short on purpose: a banner cuts a title at about 35 characters, and its icon is Script Editor's,
#: so the app's name is what tells the person whose notification this is.
APP_TITLE = "Whisper Transcriber Suite"

#: View-menu wording on macOS, where the setting also controls the notification.
MAC_CHIME_LABEL = "Chime and notify on completion"
_DEFAULT_CHIME_LABEL = "Chime on completion"

#: Two jobs further apart than this (finish to start) are not the same queue run.
BATCH_GAP_S = 120

# The whole script. The two items it shows are arguments, never part of this text.
_SCRIPT = (
    "on run argv",
    "display notification (item 1 of argv) with title (item 2 of argv)",
    "end run",
)

# A lone surrogate (a file name Python could not decode) cannot be sent to a process as UTF-8.
_SURROGATE = re.compile(r"[\ud800-\udfff]")

# Finished jobs of the current queue run (process-wide; reset by the tests' autouse fixture).
_batch: dict[str, Any] = {"count": 0, "last_end": None}
_threads: list[threading.Thread] = []
_missing_logged = False
_nsapp_unknown_logged = False


def reset_for_tests() -> None:
    global _missing_logged, _nsapp_unknown_logged
    _batch.update(count=0, last_end=None)
    _threads.clear()
    _missing_logged = False
    _nsapp_unknown_logged = False


def join_pending_for_tests(timeout: float = 5.0) -> None:
    for thread in list(_threads):
        thread.join(timeout)
    _threads.clear()


# ------------------------------------------------------------------------- osascript

def _clean(text: str) -> str:
    """``text`` as a process argument: no NUL (exec refuses it), no lone surrogate (not UTF-8)."""
    return _SURROGATE.sub(chr(0xFFFD), text.replace("\x00", ""))


def build_osascript_argv(text: str, title: str, osascript: str | None = None) -> list[str]:
    """The argument list that shows ``text`` under ``title``; both are passed as items, verbatim."""
    argv = [osascript or OSASCRIPT]
    for line in _SCRIPT:
        argv += ["-e", line]
    return argv + ["--", _clean(text), _clean(title)]


def _run(argv: list[str]) -> None:
    """Run ``osascript`` (worker thread); every failure is logged, none raised."""
    try:
        done = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=OSASCRIPT_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("Desktop notification: osascript did not finish in %d s", OSASCRIPT_TIMEOUT_S)
    except OSError as exc:
        logger.warning("Desktop notification could not start osascript: %s", exc)
    except Exception:  # noqa: BLE001 - a worker thread has no caller to receive it
        logger.exception("Desktop notification failed unexpectedly")
    else:
        if done.returncode != 0:
            detail = (done.stderr or b"").decode("utf-8", "replace").strip()
            logger.warning("Desktop notification failed (osascript exit %s): %s",
                           done.returncode, detail[:200])


def post_notification(text: str, title: str) -> None:
    """Show a notification; returns at once (the work happens on a daemon thread)."""
    global _missing_logged
    if not os.path.exists(OSASCRIPT):
        if not _missing_logged:
            _missing_logged = True
            logger.info("Desktop notification skipped: %s not found", OSASCRIPT)
        return
    argv = build_osascript_argv(text, title)
    thread = threading.Thread(target=_run, args=(argv,), name="mac-notify", daemon=True)
    _threads[:] = [t for t in _threads if t.is_alive()]
    _threads.append(thread)
    thread.start()


# ---------------------------------------------------------------------- when to post

def _on_mac() -> bool:
    return sys.platform == "darwin"


def _ns_app_active() -> bool | None:
    """``[NSApp isActive]`` through the Objective-C runtime; None where that cannot be asked.

    Tk's own focus is not enough. Measured on macOS 13 / Tk 8.6.16 (docs/MACOS_BUILD_NOTES.md):
    with another app in front, or with the app hidden (Cmd+H), ``focus -displayof`` still names a
    widget while the app is inactive. No pyobjc and no System Events: the same ``ctypes`` calls
    ``tools/mac_native_probe.py`` uses.
    """
    if not _on_mac():
        return None
    try:
        path = ctypes.util.find_library("objc")
        if not path:
            return None
        lib = ctypes.PyDLL(path)
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        ns_app_class = lib.objc_getClass(b"NSApplication")
        if not ns_app_class:
            return None
        shared = ctypes.PYFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            ("objc_msgSend", lib))(ns_app_class, lib.sel_registerName(b"sharedApplication"))
        if not shared:
            return None
        active = ctypes.PYFUNCTYPE(ctypes.c_byte, ctypes.c_void_p, ctypes.c_void_p)(
            ("objc_msgSend", lib))(shared, lib.sel_registerName(b"isActive"))
        return bool(active)
    except (OSError, AttributeError, ctypes.ArgumentError):
        return None


def window_has_focus(app: Any) -> bool:
    """True when the person is looking at the app: it is the active app (``[NSApp isActive]``) and
    its main window is on screen (mapped, not minimised or hidden).

    Tk's own keyboard focus is deliberately NOT consulted: it is wrong both ways on macOS 13 /
    Tk 8.6.16 (measured). With another app in front or after Cmd+H it still names a widget while
    the app is inactive; with the app in front and the person having just clicked a tab, no widget
    holds the focus (``focus_displayof()`` is None), which used to post a banner over a window the
    person was looking at. A minimised main window leaves the app active, so the window state is
    checked as well. A window or an NSApp that cannot answer counts as "not looking" (logged once
    for NSApp): an extra banner is harmless, a missing one is not.
    """
    try:
        if str(app.state()) in ("iconic", "withdrawn"):
            return False
    except tk.TclError:
        return False
    except AttributeError:
        pass
    try:
        if not app.winfo_ismapped():
            return False
    except tk.TclError:
        return False
    except AttributeError:
        pass
    active = _ns_app_active()
    if active is None:
        global _nsapp_unknown_logged
        if not _nsapp_unknown_logged:
            _nsapp_unknown_logged = True
            logger.info("Desktop notification: cannot ask NSApp whether the app is active; "
                        "the app counts as being in the background")
        return False
    return active


def _cue_enabled(app: Any) -> bool:
    """The View menu's completion-cue setting (live value), else the saved one."""
    var = getattr(app, "chime_on_complete_var", None)
    try:
        if var is not None:
            return bool(var.get())
    except (tk.TclError, AttributeError):
        pass
    config = getattr(app, "app_config", None) or {}
    return bool(config.get("chime_on_complete", True))


def _pending(app: Any, task: Any) -> bool:
    return any(t is not task and getattr(t, "status", "") in ("waiting", "running")
               for t in getattr(app, "queue", ()))


def _count_this_job(task: Any, queue_busy: bool) -> int:
    """How many jobs the current queue run has finished, this one included; resets at its end."""
    start, end = getattr(task, "start_time", None), getattr(task, "end_time", None)
    last = _batch["last_end"]
    if last is not None and isinstance(start, (int, float)) and start - last > BATCH_GAP_S:
        _batch.update(count=0, last_end=None)       # a count left by a queue that ended in an error
    total = _batch["count"] + 1
    if queue_busy:
        _batch.update(count=total, last_end=end if isinstance(end, (int, float)) else last)
    else:
        _batch.update(count=0, last_end=None)
    return total


def _enabled(app: Any) -> bool:
    """macOS, not shutting down, and the completion-cue setting is on."""
    return mac_native.is_aqua(app) and not getattr(app, "_closing", False) and _cue_enabled(app)


def _burn_follows(task: Any) -> bool:
    """True for the transcription stage of a "Make subtitled video" chain: the burn is its last
    stage and posts the banner."""
    return bool(getattr(getattr(task, "source_download", None), "make_subbed_video", False))


def job_done(app: Any, task: Any, output_count: int) -> None:
    """A transcription job finished: notify the desktop (macOS, app in the background). Never raises."""
    try:
        if not _enabled(app) or _burn_follows(task):
            return
        busy = _pending(app, task)
        total = _count_this_job(task, busy)
        if window_has_focus(app):
            return
        if not busy and total >= 2:
            post_notification(f"Queue done: {total} files transcribed", APP_TITLE)
            return
        name = os.path.basename(str(getattr(task, "file_path", "")))
        if getattr(task, "no_speech", False):
            text = f"Finished, but no speech was recognised: {name}"
        elif output_count == 0:
            text = f"Finished, but no output files were found: {name}"
        else:
            text = f"Done: {name} ({output_count} output file{'' if output_count == 1 else 's'})"
        post_notification(text, APP_TITLE)
    except Exception:  # noqa: BLE001 - a notification must never break the result card
        logger.exception("Desktop notification failed")


def job_ended(app: Any, task: Any) -> None:
    """A transcription job ended in any way (done, failed, cancelled): when nothing else waits or
    runs the queue is idle, so the finished-jobs count of that queue run starts over. Never raises."""
    try:
        if mac_native.is_aqua(app) and not _pending(app, task):
            _batch.update(count=0, last_end=None)
    except Exception:  # noqa: BLE001
        logger.debug("Desktop notification: could not reset the queue count", exc_info=True)


def _notify_if_away(app: Any, text: str) -> None:
    try:
        if _enabled(app) and not window_has_focus(app):
            post_notification(text, APP_TITLE)
    except Exception:  # noqa: BLE001 - a notification must never break the completion code
        logger.exception("Desktop notification failed")


def download_done(app: Any, saved_path: str) -> None:
    """A download finished and nothing (no transcription) follows it. Never raises."""
    _notify_if_away(app, f"Downloaded: {os.path.basename(str(saved_path))}")


def chain_failed(app: Any, dl: Any, error: str) -> None:
    """A "Make subtitled video" chain ended in an error (its transcription stage posted nothing, so
    this is the job's only banner). Never raises."""
    try:
        name = os.path.basename(str(getattr(dl, "saved_path", "") or "")) or str(getattr(dl, "title", "") or "")
        if str(error).startswith("No speech"):
            text = f"Subtitled video not made, no speech was found: {name}"
        else:
            text = f"Subtitled video not made: {name}"
        _notify_if_away(app, text)
    except Exception:  # noqa: BLE001 - a notification must never break the chain's closing
        logger.exception("Desktop notification failed")


def burn_done(app: Any, out_path: str) -> None:
    """A subtitle burn finished (the last stage of a chained download, or a manual burn)."""
    _notify_if_away(app, f"Subtitled video ready: {os.path.basename(str(out_path))}")


def chime_menu_label(widget: Any) -> str:
    """The View-menu text of the completion-cue setting: neutral wording on macOS only."""
    return MAC_CHIME_LABEL if mac_native.is_aqua(widget) else _DEFAULT_CHIME_LABEL
