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
A notification is posted only while the app has no Tk focus (it is in the background, minimised
or hidden): a person looking at the window already sees the result card. One per finished job; when
the last job of a queue of two or more finishes, one summary replaces that job's own notification.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import tkinter as tk
from typing import Any

from app import mac_native

logger = logging.getLogger(__name__)

#: Absolute path: a GUI app's PATH is minimal, and a bare name would run whatever comes first.
OSASCRIPT = "/usr/bin/osascript"
#: Seconds before a stuck ``osascript`` is killed (it normally returns in well under a second).
OSASCRIPT_TIMEOUT_S = 15

JOB_TITLE = "Whisper Transcriber Suite — transcription done"
QUEUE_TITLE = "Whisper Transcriber Suite — queue done"

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


def reset_for_tests() -> None:
    global _missing_logged
    _batch.update(count=0, last_end=None)
    _threads.clear()
    _missing_logged = False


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

def window_has_focus(app: Any) -> bool:
    """True when this app has the keyboard focus (Tk's view, not System Events').

    ``focus_displayof`` is None while the app is in the background, minimised or hidden. A Tk
    that cannot answer counts as "no focus": an extra banner is harmless.
    """
    try:
        return app.focus_displayof() is not None
    except (tk.TclError, AttributeError):
        return False


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


def job_done(app: Any, task: Any, output_count: int) -> None:
    """A transcription job finished: notify the desktop (macOS, app in the background). Never raises."""
    try:
        if not mac_native.is_aqua(app) or getattr(app, "_closing", False) or not _cue_enabled(app):
            return
        busy = _pending(app, task)
        total = _count_this_job(task, busy)
        if window_has_focus(app):
            return
        if not busy and total >= 2:
            post_notification(f"{total} files transcribed", QUEUE_TITLE)
            return
        name = os.path.basename(str(getattr(task, "file_path", "")))
        post_notification(
            f"Wrote {output_count} output file{'' if output_count == 1 else 's'} for {name}",
            JOB_TITLE)
    except Exception:  # noqa: BLE001 - a notification must never break the result card
        logger.exception("Desktop notification failed")


def chime_menu_label(widget: Any) -> str:
    """The View-menu text of the completion-cue setting: neutral wording on macOS only."""
    return MAC_CHIME_LABEL if mac_native.is_aqua(widget) else _DEFAULT_CHIME_LABEL
