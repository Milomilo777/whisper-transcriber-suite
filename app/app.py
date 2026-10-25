"""The Tk root. Wires services + dialogs + widgets together."""
from __future__ import annotations

import gc
import logging
import os
import re
import sys
import threading
import time
import tkinter as tk
from datetime import date
from queue import Empty, Full, Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping

import sv_ttk

from app.dialogs.advanced import AdvancedDialog
from app.dialogs.model_download import ModelDownloadDialog
from app.dialogs.quick_start import (
    QuickStartChoice,
    QuickStartDialog,
    apply_choice,
    short_model_name,
    should_show,
)
from app.dialogs import language_suggestion, share_page, ui_language
from app import desktop_alert, mac_native, rtl_layout, shortcuts
from app.i18n import N_, _, ngettext, pgettext, plain, translate
from app.dialogs.transcript_viewer import confirm_unsaved_before_exit as confirm_unsaved_viewers_before_exit
from app.dialogs.transcript_viewer import dirty_viewers as _dirty_viewers_now
from app.dialogs.transcript_viewer import open_viewer as _open_transcript_viewer
from app.domain.task_outputs import (
    pick_transcript_json,
    task_output_file,
    task_output_folder,
    task_srt_output,
    task_transcript_json,
)
from app.domain.tasks import TranscriptionTask, VideoDownloadTask
from app.observability import init_sentry, send_launch_ping_async
from app.services.download_service import DownloadService
from app.services.format_service import FormatService
from app.services.integrations_service import IntegrationsService
from app.services.transcription_service import (
    HEADLESS_READY_TIMEOUT_S,
    TranscriptionService,
)
from app.dialogs.statistics import show_statistics as _show_stats
from app.dpi import place_over, px, remember_scale, scaled_size, work_area
from app.dpi import scaled as dpi_scaled
from app.widgets.console import apply_console_theme, build_console, insert_log_line
from app.widgets.disclosure import Disclosure
from app.widgets.error_dialog import show_error
from app.widgets.wrap_row import WrapRow
from app.widgets.notice import notify
from app.widgets import subtitle_edit as subtitle_edit_ui
from app.widgets.platform import open_file as _open_file_helper
from app.widgets.platform import open_folder as _open_folder_helper
from app.widgets.platform import folder_action_label, folder_label, reveal_label
from app.widgets.live_tab import build_live_tab, stop_live_session
from app.widgets.live_tab import apply_theme as live_tab_theme
from app.widgets.live_tab import save_before_exit as live_save_before_exit
from app.widgets.smtv_tab import build_smtv_tab
from app.widgets.voice_clone_tab import build_voice_clone_tab, stop_voice_clone_worker
from app.widgets.tabs import (
    build_download_tab,
    build_queue_tab,
    build_server_tab,
    build_transcribe_tab,
    sync_transcribe_empty_state,
)
from app.widgets.tray import TrayController
from core import __version__ as _APP_VERSION
from core import offline, subtitle_edit, task_settings
from app.theme import (
    mac_appearance, script_fonts, system_appearance, theme_colours, tokens, win_chrome, win_taskbar,
)
from app.theme.bidi_display import ltr_base
from core._proc import kill_process_tree
from core.config import (
    _PROJECT_KEY_RANGES,
    load_config,
    save_config,
    webhook_secret_from_input,
    webhook_secret_valid,
)
from core.history import EXIT_REASON, HistoryDB
from core.task import apply_run_options
from core.hub import voice_clone_tab_enabled
from core.logging_setup import get_ui_logger, open_log_folder, setup_logging
from core.paths import bin_dir as _resource_bin_dir
from core.paths import bundled_binary as _bundled_binary
from core.paths import same_file as _same_file
from app.domain.speed_text import speed_cell_text, task_summary_text
from core.watcher import FolderWatcher

logger = logging.getLogger(__name__)

# Menu labels the update notice decorates with a dot (_refresh_update_signs).
# English msgids (N_): translate() them where they are shown. The menus remember the index of
# each item, so no lookup ever goes by the (translated) label.
_HELP_MENU_LABEL = N_("Help")
_CHECK_FOR_UPDATES_LABEL = N_("Check for updates...")
_ABOUT_MENU_LABEL = N_("About")
_WORK_OFFLINE_LABEL = N_("Work offline")
# core.star_invite's two lines, marked here: the app shows them, and core/ is not translated.
# tests/app/test_i18n_app_walk.py keeps them equal to core's English.
_STAR_ABOUT_LINE = N_("Like the app? A star on its GitHub page helps other people find it.")
_STAR_BAR_TEXT = N_("Enjoying it? A star on GitHub helps other people find it.")
# An app left open keeps checking about once a day (the date throttle in
# _maybe_quiet_update_check still applies).
_UPDATE_RECHECK_MS = 24 * 60 * 60 * 1000
# A launch check that finds a release while a job runs keeps the bar back and
# looks again this often until the queue is idle (_retry_update_bar).
_UPDATE_BAR_RETRY_MS = 2 * 60 * 1000

# What App._confirm_backend_switch is asked about (advanced.py and hardware_wizard.py pass
# the same strings).
BACKEND_SWITCH_ENGINE = "engine"
BACKEND_SWITCH_MODEL = "model"
BACKEND_SWITCH_HARDWARE = "hardware"
_BACKEND_SWITCH_KINDS = frozenset({BACKEND_SWITCH_ENGINE, BACKEND_SWITCH_MODEL,
                                   BACKEND_SWITCH_HARDWARE})


def backend_switch_texts(kind: str, n: int) -> tuple[str, str]:
    """Title and question of the "stop the running transcription?" prompt for ``kind``.

    One whole message per kind (no translated phrase is set into another sentence), with
    the plural forms for the ``n`` running transcriptions.
    """
    if kind == BACKEND_SWITCH_MODEL:
        return _("Change the Whisper model?"), ngettext(
            "{n} transcription is running right now. Changing the model stops it immediately "
            "-- more abruptly than a normal Cancel, so more progress may be lost."
            "\n\nChange it anyway?",
            "{n} transcriptions are running right now. Changing the model stops them "
            "immediately -- more abruptly than a normal Cancel, so more progress may be lost."
            "\n\nChange it anyway?",
            n)
    if kind == BACKEND_SWITCH_HARDWARE:
        return _("Apply now?"), ngettext(
            "{n} transcription is running right now. Applying the new hardware setting now "
            "stops it immediately -- more abruptly than a normal Cancel, so more progress may "
            "be lost.\n\nApply it now? Choose No to let it finish; the setting is then used "
            "after the app is restarted.",
            "{n} transcriptions are running right now. Applying the new hardware setting now "
            "stops them immediately -- more abruptly than a normal Cancel, so more progress "
            "may be lost.\n\nApply it now? Choose No to let it finish; the setting is then "
            "used after the app is restarted.",
            n)
    if kind == BACKEND_SWITCH_ENGINE:
        return _("Switch transcription engine?"), ngettext(
            "{n} transcription is running right now. Switching engines stops it immediately "
            "-- more abruptly than a normal Cancel, so more progress may be lost."
            "\n\nSwitch anyway?",
            "{n} transcriptions are running right now. Switching engines stops them "
            "immediately -- more abruptly than a normal Cancel, so more progress may be lost."
            "\n\nSwitch anyway?",
            n)
    raise ValueError(f"unknown backend switch kind: {kind!r}")


def offline_question(what: str) -> str:
    """The question App.ensure_online asks before ``what`` while Work offline is on.

    ``what`` is the action's English name (it also goes to the log). Each known action has
    its own whole message, so no translated phrase is set into another sentence; an action
    missing here gets a message without its name (and a warning in the log).
    """
    if what == "Checking for updates":
        return _("Checking for updates needs the internet, and Work offline is on, so the "
                 "app makes no network connection.\n\nTurn Work offline off now?")
    if what == "Installing the YouTube helper":
        return _("Installing the YouTube helper needs the internet, and Work offline is on, "
                 "so the app makes no network connection.\n\nTurn Work offline off now?")
    if what == "Updating the video downloader":
        return _("Updating the video downloader needs the internet, and Work offline is on, "
                 "so the app makes no network connection.\n\nTurn Work offline off now?")
    if what == "Downloading this link":
        return _("Downloading this link needs the internet, and Work offline is on, so the "
                 "app makes no network connection.\n\nTurn Work offline off now?")
    if what == "Fetching the subtitles of this link":
        return _("Fetching the subtitles of this link needs the internet, and Work offline "
                 "is on, so the app makes no network connection.\n\nTurn Work offline off "
                 "now?")
    logger.warning("ensure_online: no message for the action %r; asking without its name", what)
    return _("This needs the internet, and Work offline is on, so the app makes no network "
             "connection.\n\nTurn Work offline off now?")


# The actions offline_question knows (tests check every ensure_online caller against it).
OFFLINE_ACTIONS = (
    "Checking for updates", "Installing the YouTube helper", "Updating the video downloader",
    "Downloading this link", "Fetching the subtitles of this link",
)


def _today() -> date:
    """Today's local date (one seam for the update-notice tests)."""
    return date.today()


def cancel_pending_after_callbacks(root: tk.Misc) -> None:
    """Cancel every pending ``after()`` callback of the interpreter, at Tcl level only.

    ``Misc.after_cancel`` also deletes the callback's Tcl command, but that command
    belongs to whichever widget called ``after()``. Deleted through the root, it stays
    listed by its owner (the scrollable tab page's canvas runs its own ``after()`` loop),
    so the owner's ``destroy()`` raises ``TclError: can't delete Tcl command``, the root
    is never destroyed and the process keeps running behind a half-empty window. A plain
    ``after cancel`` stops the callbacks; each owner deletes its own commands when it is
    destroyed.
    """
    try:
        ids = root.tk.splitlist(root.tk.call("after", "info"))
    except tk.TclError:
        return
    for cb_id in ids:
        try:
            root.tk.call("after", "cancel", cb_id)
        except tk.TclError:
            logger.debug("after() callback %s already gone", cb_id, exc_info=True)


def _set_enabled(button: "ttk.Button", enabled: bool) -> None:
    """Enable or disable a ttk button, touching it only when its state changes.

    The action bars are recomputed every 500 ms; on a visible tab each ``state()`` call
    repaints the button even when nothing changed (part of the idle CPU load on macOS).
    """
    if button.instate(["disabled"]) == enabled:
        button.state(["!disabled"] if enabled else ["disabled"])


def _show_file_in_box(app: Any, path: str) -> None:
    """Put ``path`` in the File or video link box with its END in sight: an Entry shows the
    start of a long path, so the file name and extension were cut off (round-2 screenshot
    critics, 2026-10-21). Only for paths the app writes; typing is left alone. A function, not
    a method, so the test doubles that run the drop and Browse code need nothing new."""
    app.fv.set(path)
    entry = _inst_attr(app, "file_entry")  # absent on test doubles
    if entry is not None:
        entry.icursor("end")
        entry.xview_moveto(1.0)
        # Again once Tk has laid out a tab that was just shown (a drop or a Recent file from
        # another tab): an Entry that is not mapped has no width to scroll against.
        entry.after_idle(lambda: entry.xview_moveto(1.0))


def _select_the_running_task(tree: Any, row_map: dict[str, Any], tasks: list[Any],
                             last: Any) -> Any | None:
    """Select the one running task in ``tree`` and return it, or return None and change nothing.

    Only when nothing is selected or only ended rows are, exactly one task runs, and it is not
    ``last`` (the task picked before: a selection the user cleared stays cleared)."""
    selected = [row_map.get(i) for i in tree.selection()]
    if any(t is not None and getattr(t, "status", "") not in ("finished", "cancelled", "error")
           for t in selected):
        return None
    running = [t for t in tasks if getattr(t, "status", "") == "running"]
    if len(running) != 1 or running[0] is last:
        return None
    iids = _iids_for_tasks(row_map, running)
    if not iids:
        return None
    tree.selection_set(iids)
    tree.see(iids[0])
    return running[0]


def _same_rows(
    shown: "list[tuple[Any, tuple[str, ...], tuple[str, ...]]] | None",
    rows: "list[tuple[Any, tuple[str, ...], tuple[str, ...]]]",
) -> bool:
    """True when ``rows`` (task, cell texts, tags) equal what the Queue tree shows.

    Tasks are compared by identity, never by ``==``: a task object that replaced another
    with identical text must still rebuild the tree so ``row_map`` points at the new one.
    """
    if shown is None or len(shown) != len(rows):
        return False
    return all(
        a[0] is b[0] and a[1] == b[1] and a[2] == b[2] for a, b in zip(shown, rows)
    )


def _iids_for_tasks(
    row_map: dict[str, Any], tasks: "list[Any]"
) -> list[str]:
    """Map task objects back to their (new) Treeview iids after a rebuild.

    refresh() rebuilds the tree every tick with fresh iids, wiping the
    selection. Given the freshly-built ``row_map`` (iid -> task) and the
    tasks that were selected before the rebuild, return the iids that now
    hold those same task objects (by identity), preserving tree order and
    dropping any task that has since left the queue. Pure + Tk-free so the
    selection-preservation contract can be unit-tested.
    """
    wanted = {id(t) for t in tasks}
    if not wanted:
        return []
    return [iid for iid, t in row_map.items() if id(t) in wanted]


def _inst_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read an attribute from the instance dict only.

    ``getattr(obj, name, default)`` is unsafe on a bare ``App.__new__(App)``
    test double: ``tkinter.Misc.__getattr__`` proxies any missing attribute
    to ``self.tk``, which is itself missing, so the lookup recurses forever
    (see the same gotcha documented in tests/core/test_model_selector.py).
    Reading ``__dict__`` cannot recurse and answers the useful question:
    "was this attribute actually assigned yet?".
    """
    return obj.__dict__.get(name, default)


#: How long an exit waits (window hidden) for a package install to leave its merge phase.
INSTALL_EXIT_WAIT_S = 30.0


def _stop_installs_on_exit() -> None:
    """Stop on-demand package installs and wait (bounded) for the merge phase."""
    try:
        from core import optional_deps

        optional_deps.request_stop_installs()
        if not optional_deps.wait_until_idle(INSTALL_EXIT_WAIT_S):
            logger.warning(
                "A package install was still running %.0f s after the exit request%s; "
                "ending anyway", INSTALL_EXIT_WAIT_S,
                " (in its merge phase: a leftover .bak folder may remain in the "
                "extras folder)" if optional_deps.installs_merging() else "",
            )
    except Exception:  # noqa: BLE001 - the exit must go on
        logger.exception("Could not stop the package installs on exit")


def _resume_prompt_text(rows: list[dict[str, Any]]) -> str:
    """The resume offer's sentence, worded after why the jobs stopped.

    Rows ended by a confirmed exit carry ``EXIT_REASON``; a crash leaves no
    error text. All closed on purpose: say so (a quit is not a crash); mixed:
    stay neutral.
    """
    n = len(rows)
    closed = sum(1 for r in rows if (r.get("error") or "") == EXIT_REASON)
    # One whole sentence per cause, each with its plural forms.
    if closed == n:
        return ngettext(
            "We found {n} transcription that was interrupted when the app was closed. "
            "Resume it now?",
            "We found {n} transcriptions that were interrupted when the app was closed. "
            "Resume them now?", n)
    if closed == 0:
        return ngettext(
            "We found {n} transcription that was interrupted by a previous crash. "
            "Resume it now?",
            "We found {n} transcriptions that were interrupted by a previous crash. "
            "Resume them now?", n)
    return ngettext(
        "We found {n} transcription that was interrupted the last time the app ran. "
        "Resume it now?",
        "We found {n} transcriptions that were interrupted the last time the app ran. "
        "Resume them now?", n)


def _record_exit_interruptions(history: Any, active: list[Any]) -> None:
    """Mark this app's running transcription rows as ended by a confirmed exit."""
    if history is None:
        return
    ids = [int(getattr(t, "history_id", 0) or 0) for t in active]
    try:
        n = history.mark_transcriptions_closed_by_user(ids)
    except Exception:  # noqa: BLE001
        logger.warning("Could not record the exit on the running jobs", exc_info=True)
        return
    if n:
        logger.info("Exit confirmed with %d running transcription(s)", n)


def _resolve_theme(name: str) -> str:
    """"light" / "dark" for a saved choice; "system" asks the OS (app.theme.system_appearance)."""
    return system_appearance.resolve_theme(name)


def _resolve_entry_file() -> str:
    """Where does ``bin/`` live? Frozen exe sits beside it; source uses gui.py."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "gui.py",
    )


def _split_dnd_paths(raw: str) -> list[str]:
    """Split a tkdnd ``<<Drop>>`` payload into individual paths.

    tkdnd packs all dropped items into one string: space-separated
    tokens, with any token that contains a space wrapped in ``{...}``.
    We intentionally do NOT use ``Tk.splitlist`` here: Tcl's list
    parser treats a leading ``\\\\`` as an escaped backslash and
    collapses it to a single one, so a UNC path like
    ``{\\\\server\\share\\my file.mp4}`` comes back as
    ``\\server\\share\\my file.mp4`` — no longer a valid UNC path, and
    the dropped network file is then silently dropped by the later
    ``os.path.isfile`` gate. This brace/space splitter preserves the
    backslashes verbatim so UNC drops survive (local ``C:\\`` and mapped
    ``Z:\\`` paths were never affected, having no leading ``\\\\``).
    """
    raw = raw.strip()
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] == " ":
            i += 1
        if i >= n:
            break
        if raw[i] == "{":
            # Scan for the CLOSING brace of this token. '{' and '}' are legal
            # filename characters, so a naive raw.find('}') split a real file
            # like 'my clip {v2}.mp4' at the inner '}', producing two bogus
            # tokens that both fail the later os.path.isfile gate (the file
            # is then silently not enqueued). Honour brace nesting AND only
            # accept a '}' as the token delimiter when it is followed by
            # end-of-string or a space (i.e. it really ends the token), so
            # embedded literal braces inside a filename survive. Backslashes
            # are NOT treated as escapes here: tkdnd's <<Drop>> payload keeps
            # them literal (UNC paths like \\server\share rely on that).
            j = i + 1
            depth = 1
            close = -1
            while j < n:
                c = raw[j]
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 1 and (j + 1 >= n or raw[j + 1] == " "):
                        # The real end of the brace-wrapped token.
                        close = j
                        break
                    if depth > 1:
                        depth -= 1
                    # else: a depth-1 '}' NOT at a token boundary is a
                    # literal brace inside the filename — leave depth alone
                    # and keep scanning for the true close.
                j += 1
            if close == -1:
                # Unbalanced brace — take the rest as one token.
                out.append(raw[i + 1:])
                break
            out.append(raw[i + 1:close])
            i = close + 1
        else:
            j = i
            while j < n and raw[j] != " ":
                j += 1
            out.append(raw[i:j])
            i = j
    return out


def _file_uri_to_path(uri: str) -> str:
    """Convert a ``file://`` URI to a local filesystem path.

    Handles the common shapes a drop target sees:
    ``file:///C:/dir/clip.mp4`` (Windows), ``file:///home/u/clip.mp4``
    (POSIX), and the UNC form ``file://server/share/clip.mp4``. Returns ""
    when ``uri`` isn't a ``file://`` URI or can't be parsed, so the caller
    can fall through to its unsupported-scheme path.
    """
    if not uri.startswith("file://"):
        return ""
    from urllib.parse import urlsplit
    from urllib.request import url2pathname
    try:
        parts = urlsplit(uri)
        # A non-empty netloc on file:// is a UNC host (file://server/share);
        # localhost/empty is the ordinary local-file case.
        netloc = parts.netloc
        # url2pathname decodes the %XX escapes itself; decoding first as well would turn
        # an encoded '%41' or '#' in a file name into a second, different character.
        path = url2pathname(parts.path)
        if netloc and netloc.lower() != "localhost":
            return r"\\{}{}".format(netloc, path)
        return path
    except Exception:  # noqa: BLE001
        return ""


# Watched folder: a new file is queued once its size and modification time
# stayed the same at _WATCH_STABLE_CHECKS checks in a row, _WATCH_CHECK_MS
# apart. One unchanged pair 1.2 s apart let a copy that paused for a moment
# through half-written. A file that stays empty is dropped after
# _WATCH_EMPTY_CHECKS checks (about two minutes).
_WATCH_CHECK_MS = 1200
_WATCH_STABLE_CHECKS = 2
_WATCH_EMPTY_CHECKS = 100


def _file_signature(path: str) -> tuple[int, int] | None:
    """``(size, mtime_ns)`` of ``path``, or None when it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _watch_stability_step(
    prev: tuple[int, int], now: tuple[int, int], same_checks: int,
) -> tuple[str, int]:
    """One stability check of a watched file: ``(verdict, same_checks)``.

    ``verdict`` is "ready" (queue it), "wait" (check again later) or
    "empty" (still zero bytes after _WATCH_EMPTY_CHECKS checks: give up).
    """
    if now != prev:
        return "wait", 0
    same_checks += 1
    if now[0] == 0:
        return ("empty", same_checks) if same_checks >= _WATCH_EMPTY_CHECKS else ("wait", same_checks)
    if same_checks >= _WATCH_STABLE_CHECKS:
        return "ready", same_checks
    return "wait", same_checks


_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")


def _saved_geometry_visible(geom: str, point_visible: Callable[[int, int], bool]) -> bool:
    """False when a saved ``WxH+X+Y`` puts the title bar off every monitor.

    The middle of the title bar is the point the user must be able to grab.
    A geometry without a position (``WxH``) is always fine.
    """
    m = _GEOMETRY_RE.match(geom.strip())
    if m is None:
        return True
    width = int(m.group(1))
    x, y = int(m.group(3).replace("+", "", 1)), int(m.group(4).replace("+", "", 1))
    return point_visible(x + width // 2, y + 10)


def _point_on_a_monitor(x: int, y: int) -> bool:
    """True when the screen point lies on a connected monitor.

    Windows asks the system (MonitorFromPoint); elsewhere there is no cheap
    check, so the window manager is trusted to place the window.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        monitor_defaulttonull = 0
        return bool(user32.MonitorFromPoint(wintypes.POINT(x, y), monitor_defaulttonull))
    except Exception:  # noqa: BLE001 - a failed check must not hide the window
        return True


def _clean_pasted_path(text: str) -> str:
    """The path inside what a user pasted into the file field.

    Explorer's "Copy as path" wraps the path in double quotes, a paste can
    bring spaces or a line break along, and Linux file managers copy
    ``file://`` URIs. URLs and plain paths come back stripped only.
    """
    cleaned = text.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("file://"):
        cleaned = _file_uri_to_path(cleaned) or cleaned
    return cleaned


def _media_files_in_folder(folder: str) -> list[str]:
    """Top-level media files inside a dropped folder (sorted, stable order).

    Only the folder's own files are scanned — deliberately no recursion, so
    dropping e.g. a drive root can't silently enqueue thousands of files.
    Media-ness comes from core.watcher's single extension list. Returns []
    on any listing error (permissions, folder vanished mid-drop).
    """
    from core.watcher import is_media_file

    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out: list[str] = []
    for name in names:
        full = os.path.join(folder, name)
        if os.path.isfile(full) and is_media_file(full):
            out.append(full)
    return out


# --- About dialog content (pure, Tk-free, unit-testable) -------------------
# The About dialog's text and links live in these two module-level helpers so
# they can be unit-tested without ever building a tk.Tk() root. The dialog in
# App._show_about only walks the returned data structures into widgets.

# A section is (title, [(subsection_title, [bullet, ...]), ...]).
AboutSection = tuple[str, list[tuple[str, list[str]]]]


def new_issue_url() -> str:
    """A GitHub "new issue" link with the app version and system filled in.

    Only the version, the operating system and the Python version go into the
    form: no file names, paths or settings. The person sees and edits the text
    in the browser before anything is sent.
    """
    import platform
    import urllib.parse

    from core.updates import NEW_ISSUE_URL

    body = (
        "**What happened?**\n\n\n**What did you expect?**\n\n\n**Steps to reproduce**\n1. \n\n"
        "---\n"
        f"App version: {_APP_VERSION}\n"
        f"System: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"Python: {platform.python_version()}\n"
    )
    return NEW_ISSUE_URL + "?" + urllib.parse.urlencode({"body": body})


def _open_new_issue() -> None:
    import webbrowser

    webbrowser.open(new_issue_url())


def build_about_sections() -> list[AboutSection]:
    """Return the full, plain-language feature inventory for the About dialog.

    Many capabilities ship enabled-by-default but live behind the Advanced
    dialog or have no surface in the main UI, so this is the canonical
    "what does this app actually do" reference and is intentionally
    exhaustive. Pure data: no Tk, no I/O — safe to call from a test.
    """
    return [
        (_("What's new in this version"), [
            (_("Highlights"), [
                _("Make a subtitled video: burn the subtitles into a copy of "
                "the video, with progress and a Stop button"),
                _("Translate speech straight to English, and share a "
                "transcript as a single web page"),
                _("Work offline: one switch that keeps the app off the network"),
                _("Speed and time left for every job, and taskbar progress on "
                "Windows"),
                _("A more native Mac app: Open With, the Dock, the menus and "
                "notifications, and a video downloader that updates itself"),
                _("Quick start on the first launch, a \"Try it now\" sample "
                "clip, and quiet notices instead of message boxes"),
            ]),
        ]),
        (_("Transcription engine"), [
            (_("Input"), [
                _("Any audio or video file ffmpeg can read"),
                _("Drag-and-drop one or many files onto the window"),
                _("Browse… ({shortcut}) for single or multi-select",
                  shortcut=shortcuts.accel_text('o')),
                _("Recent-files submenu (last 10 from history)"),
            ]),
            (_("Models"), [
                _("Whisper Large v3 (default, ~3 GB)"),
                _("Whisper Large v3 Turbo (~5× faster, ~1.6 GB)"),
                _("Distil Large v3.5 (fastest English-only, ~1.5 GB)"),
                _("Picker lives in the Advanced dialog"),
            ]),
            (_("Backends (pluggable)"), [
                _("Local Whisper via faster-whisper — the default, runs "
                "offline once its model is downloaded, your audio never "
                "leaves your computer"),
                _("whisper.cpp via pywhispercpp — optional, quantised, "
                "kinder to weak CPUs"),
                _("NVIDIA Parakeet TDT v3 via transformers — optional, "
                "local, multilingual"),
                _("Switch in the Advanced dialog under Backend"),
            ]),
            (_("Cloud transcription (optional, uploads your audio)"), [
                _("Off by default. These send your audio to Google, so they "
                "break the offline guarantee — only use them on purpose."),
                _("Gemini (simple API key): paste one free key from "
                "aistudio.google.com and it just works. Free tier is about "
                "60 minutes a month."),
                _("Google Cloud Speech-to-Text (service account): a "
                "purpose-built transcription service with real word "
                "timestamps and speaker labels — the only engine here "
                "that combines all three: real word-level timestamps, "
                "speaker diarization, and a cheap Batch mode for long "
                "files. New accounts get 60 free minutes a month plus a "
                "$300 / 90-day credit."),
                _("It needs a service-account JSON file — set it under "
                "Advanced › Backend, where a \"How do I get this file?\" "
                "button walks you through it step by step."),
                _("Batch mode (Cloud Speech-to-Text): about 75% cheaper "
                "(~$0.004/minute vs ~$0.016/minute standard) but slower — "
                "usually ready within 24 hours — and needs a Cloud "
                "Storage bucket. Good for large jobs you are not waiting "
                "on."),
            ]),
            (_("Hardware"), [
                _("Autodetect at first launch (CUDA / NPU / DirectML / CPU)"),
                _("Choice persisted in hardware.json"),
                _("Manual override in the Advanced dialog"),
            ]),
            (_("Quality controls"), [
                _("Voice Activity Detection (Silero VAD), tunable"),
                _("Word-level timestamps (opt-in)"),
                _("Optional stable-ts word-alignment refinement"),
                _("Optional Demucs vocal-separation pre-processing"),
            ]),
        ]),
        (_("Output formats"), [
            (_("Files written next to your source"), [
                _("SubRip — .srt"),
                _("WebVTT — .vtt"),
                _("Whisper JSON — .json (segments + word-level data)"),
                _("Plain text — .txt"),
                _("Tab-separated — .tsv"),
                _("LRC lyrics — .lrc"),
                _("Markdown — .md"),
                _("Microsoft Word — .docx"),
                _("PDF — via reportlab"),
            ]),
            (_("Round-trip"), [
                _("oTranscribe import (.otr → .srt)"),
                _("oTranscribe export (.srt → .otr) for manual editing"),
                _("ELAN import/export (.eaf)"),
                _("InqScribe import/export (.inqscr / [hh:mm:ss.ff])"),
                _("Express Scribe export (.txt / [hh:mm:ss]) — export only"),
            ]),
            (_("Templating"), [
                _("output_filename_template config key with tokens "
                "{base} {ext} {lang} {date} {speaker_count}"),
                _("Sibling subdirectories created on the fly"),
            ]),
        ]),
        (_("Post-processing"), [
            (_("Per-file extras"), [
                _("Speaker diarisation (sherpa-onnx, no HF token)"),
                _("Auto-chapter markers (long-silence heuristic)"),
                _("Hallucination detector — flags suspect segments "
                "in the viewer (red rows)"),
            ]),
            (_("Optional local LLM"), [
                _("Qwen2.5-1.5B-Instruct, download-on-first-use"),
                _("Summaries, Q&A, AI-generated chapter titles"),
                _("Off by default; opt in from the Advanced dialog"),
            ]),
        ]),
        (_("Video download"), [
            (_("Sources"), [
                _("Any URL yt-dlp supports (YouTube, Vimeo, …)"),
                # The video-site feature stays English-only: never wrapped, never in a catalog.
                "Supreme Master TV episode pages "
                "(multi-quality + article text + series parts)",
            ]),
            (_("Pipeline options"), [
                _("Format/quality picker per URL"),
                _("Audio-only mode (MP3 / m4a / opus)"),
                _("Subtitle download + burn-in to video"),
                _("SponsorBlock category skipping"),
                _("Auto-transcribe after download"),
                _("Cookies from browser — download login-walled / "
                "age-gated content (Facebook / Instagram / TikTok, "
                "some YouTube Shorts)"),
            ]),
        ]),
        (_("Web / LAN access"), [
            (_("Share transcription from a browser"), [
                _("One click on the \"Web / LAN access\" tab opens a simple "
                "web page served by this app — no app to install on the "
                "other devices"),
                _("Loopback by default: only this computer can reach it "
                "(no firewall prompt)"),
                _("Optional \"Share on local network\" so phones and other "
                "PCs can use it (your system may ask to allow the firewall — "
                "click Allow)"),
                _("Optional access password if you want to limit who can use it"),
                _("Use it only on a network you trust — it is not encrypted"),
            ]),
        ]),
        (_("Transcript viewer"), [
            (_("Open via"), [
                _("Help → Open transcript viewer…"),
                _("Last-Result card → View transcript"),
            ]),
            (_("Editing"), [
                _("Find / replace ({shortcut}), case-insensitive default",
                  shortcut=shortcuts.accel_text('f')),
                _("Speaker rename — rewrites every same-labelled segment"),
                _("Remove fillers — strips uh/um/er… with whole-word regex"),
                _("Atomic save ({shortcut})", shortcut=shortcuts.accel_text('s')),
            ]),
            (_("Playback"), [
                _("Embedded VLC when python-vlc + libvlc are installed"),
                _("Click-to-seek on any segment"),
                _("Karaoke — active word wrapped in [brackets] as VLC plays"),
            ]),
            (_("Display"), [
                _("Word-confidence colour coding "
                "(green ≥ 0.85, amber ≥ 0.6, red below)"),
                _("Type-as-you-search filter"),
            ]),
        ]),
        (_("Workflow + system integration"), [
            (_("Queue"), [
                _("Multi-file batch with per-file progress"),
                _("Parallel workers (configurable, default 2)"),
                _("Right-click any item for Pause, Resume, Cancel, "
                "Re-run, and Remove — per task"),
                _("Cancel a running job (Esc)"),
            ]),
            (_("Automation"), [
                _("Watched folder — auto-enqueue files dropped in"),
                _("Windows Explorer right-click "
                "\"Transcribe with Whisper Transcriber Suite\" (optional install task)"),
                _("Per-folder .whisperproject.json overrides"),
            ]),
            (_("Desktop"), [
                _("System tray + minimise-to-tray (opt-in)"),
                _("Native Windows toast on completion + chime"),
                _("High-DPI scaling"),
                _("Light / dark / system theme"),
            ]),
            (_("Reliability"), [
                _("Crash-auto-resume — re-enqueues interrupted files"),
                _("Worker subprocess with 5 s heartbeat + 30 s watchdog"),
                _("history.db opens in WAL mode + integrity check"),
                _("--safe-mode CLI flag backs up config and re-runs first-run"),
            ]),
        ]),
        (_("Updates"), [
            (_("Staying current"), [
                _("Daily check against GitHub for a newer version (on by "
                "default) — it only "
                "tells you; it never downloads or installs on its own"),
                _("A newer version shows a quiet bar under the menu: What's "
                "new, Download (the file for this kind of install), Later "
                "(again in 3, 7, then 14 days, then about once a month; "
                "never while a job runs) or Skip this version"),
                _("Run it any time from Help → Check for updates…; turn the "
                "daily check off in Advanced → App behaviour"),
                _("When you install the newer Setup it upgrades in place over "
                "the old version — you do NOT need to uninstall first"),
            ]),
        ]),
        (_("Search + statistics"), [
            (_("History"), [
                _("Every finished job recorded in SQLite history.db"),
                _("File → Recent files (last 10)"),
                _("File → Statistics… — total minutes transcribed, etc."),
            ]),
        ]),
        (_("Keyboard shortcuts"), [
            (_("Global"), [
                _("{shortcut} — Browse for files", shortcut=shortcuts.accel_text('o')),
                _("{shortcut} — Transcribe selected", shortcut=shortcuts.accel_text('Return')),
                _("Esc — Cancel running job"),
                (_("{shortcut} — Quit (bypasses minimise-to-tray)", shortcut=shortcuts.accel_text('q'))
                 if shortcuts.is_mac() else
                 _("{shortcut} — Exit (bypasses minimise-to-tray)", shortcut=shortcuts.accel_text('q'))),
            ]),
            (_("Viewer"), [
                _("{shortcut} — Find / replace", shortcut=shortcuts.accel_text('f')),
                _("{shortcut} — Save edits", shortcut=shortcuts.accel_text('s')),
            ]),
        ]),
        (_("Privacy"), [
            (_("Default"), [
                _("Local engines transcribe on this computer; your audio "
                "is not uploaded"),
                _("The cloud backends above are the exception — they upload "
                "audio only when you choose one and start a job"),
                _("Network use: update check, online app settings, model "
                "downloads on first use, usage statistics — the full list "
                "is in the project's docs on GitHub (docs/CONFIG.md, "
                "Network use)"),
                _("File → Work offline stops all network use; anything that "
                "needs the internet then says so (config: work_offline)"),
            ]),
            (_("Usage statistics"), [
                _("Sent after each finished transcription; on by default. "
                "Switch: Help → Usage statistics, or Advanced → App "
                "behaviour (config: telemetry_opt_in)"),
                _("What is sent: model, language, audio length, processing "
                "time, job status, word count, app version, OS name/version, "
                "CPU and memory size, and the two-letter country of the OS "
                "region setting; the payload never includes the file's name "
                "or folder, the computer name or an IP address"),
                _("Launch ping and Sentry crash reports: only when "
                "WHISPER_TELEMETRY_URL / SENTRY_DSN are set"),
            ]),
        ]),
    ]


def build_about_links() -> list[tuple[str, str]]:
    """Return (label, url) pairs of helpful links for the About dialog.

    Pure data: the dialog binds each to ``webbrowser.open``. The releases
    URL is sourced from ``core.updates`` so it tracks the repo move note
    there (single source of truth for the GitHub coordinates).
    """
    from core.updates import RELEASES_PAGE_URL

    return [
        (_("Downloads & new versions (GitHub releases)"), RELEASES_PAGE_URL),
        (_("Get a free Gemini API key — aistudio.google.com"),
         "https://aistudio.google.com/apikey"),
        (_("Google Cloud console (service account, billing)"),
         "https://console.cloud.google.com"),
        (_("Cloud setup guide — Gemini (paste a key)"),
         "https://github.com/Milomilo777/whisper-transcriber-suite"
         "/blob/master/docs/CLOUD_STT.md"),
        (_("Cloud setup guide — Google Cloud Speech-to-Text"),
         "https://github.com/Milomilo777/whisper-transcriber-suite"
         "/blob/master/docs/CLOUD_STT_GOOGLE.md"),
    ]


#: Longest list of file names the "not updated" message shows; the rest is counted.
_MAX_FILES_LISTED = 8


def _not_updated_message(left: list[str]) -> str:
    """The text of the box shown when the exit gave up on some export rebuilds.

    File names, not paths; a name that two folders share also gets its folder, so the person can
    tell the files apart; a long list is cut and counted.
    """
    paths = list(dict.fromkeys(left))
    counts: dict[str, int] = {}
    for path in paths:
        counts[os.path.basename(path)] = counts.get(os.path.basename(path), 0) + 1
    labels = []
    for path in paths:
        name = os.path.basename(path)
        folder = os.path.basename(os.path.dirname(path))
        labels.append(f"{name} ({folder})" if counts[name] > 1 and folder else name)
    shown = labels[:_MAX_FILES_LISTED]
    lines = [f"  {label}" for label in shown]
    if len(labels) > len(shown):
        rest = len(labels) - len(shown)
        lines.append("  " + ngettext("...and {n} more", "...and {n} more", rest))
    return _(
        "Your transcript was saved, but these files were still being rebuilt when the "
        "app had to close, so they still hold the old text:\n\n{files}\n\n"
        "To update them, open the transcript again and save it once more. "
        "The transcript (JSON) and the other files are saved.",
        files="\n".join(lines),
    )


def _viewable_parent(app: Any) -> Any:
    """``app`` as the parent of a message box when its window is showing, else None (a window
    hidden in the tray, or a stand-in, cannot be the parent of a visible box)."""
    try:
        if isinstance(app, tk.Misc) and app.winfo_viewable():
            return app
    except tk.TclError:
        pass
    return None


def _warn_exports_not_updated(app: Any, left: list[str]) -> None:
    """Tell the person which files kept the old text (an ordinary modal; they dismiss it).

    Shown after the wait window is gone and before the app tears down; the exit is never
    blocked by a failure here (the transcripts are saved and the log names the files).
    """
    app._exit_prompt_open = True  # a second close press must not stack another exit
    try:
        messagebox.showwarning(
            _("Some files were not updated"), _not_updated_message(left),
            parent=_viewable_parent(app))
    except Exception:  # noqa: BLE001 - never block the exit
        logger.exception("Could not show the 'exports not updated' message")
    finally:
        app._exit_prompt_open = False


def _finish_viewer_exports(app: Any) -> None:
    """Wait (at most 30 s) for the transcript viewers' export rebuilds before the app ends.

    Only what exists on ``app`` is used (the exit tests pass stand-ins): its title says why
    the window stays, its event loop keeps running, its log names what was not rebuilt. When the
    limit is reached with files still old, a message box names them (the exit goes on after the
    person dismisses it); the transcript itself was saved before the wait began.
    """
    from app.dialogs.transcript_viewer import finish_exports_before_exit

    dialog: tk.Toplevel | None = None

    def _say(_working: int) -> None:
        nonlocal dialog
        if dialog is None and isinstance(app, tk.Misc):
            dialog = _open_exit_wait_dialog(app)

    app._exit_prompt_open = True  # a second close press must not stack another exit
    # While waiting, the queue pump starts nothing new (loop()); results that finish are
    # still collected and saved by their own pollers.
    app._exit_waiting = True
    try:
        left = finish_exports_before_exit(on_wait=_say, pump=getattr(app, "update", None))
    except Exception:  # noqa: BLE001 - the transcripts are saved: never block the exit
        logger.exception("Waiting for the viewers' exports failed")
        left = []
    finally:
        app._exit_waiting = False
        app._exit_prompt_open = False
        if dialog is not None:
            try:
                dialog.grab_release()
                dialog.destroy()
            except tk.TclError:
                pass
    if left:
        app.log(
            "Closed before these exports were rebuilt; they keep the old text: "
            + ", ".join(os.path.basename(p) for p in left)
        )
        _warn_exports_not_updated(app, left)


def _open_exit_wait_dialog(app: tk.Misc) -> tk.Toplevel | None:
    """A small modal "Finishing exports before closing" window; None if it cannot be made.

    The grab keeps clicks and keys away from the transcript viewers and the main window while
    the exports finish (a viewer typed into now would lose its edits at the exit). It stands
    on its own, centred on the screen, so it is also seen when the app was hidden in the tray.
    """
    try:
        dlg = tk.Toplevel(app)
        dlg.title("Whisper Transcriber Suite")  # the product name is not translated
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # it closes itself
        body = ttk.Frame(dlg, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=_("Finishing exports before closing…"),
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(
            body, justify="left", wraplength=360,
            text=_("Your transcripts are saved. The other files next to them are being "
                   "updated with the same text; the app closes as soon as they are done."),
        ).pack(anchor="w", pady=(6, 10))
        bar = ttk.Progressbar(body, mode="indeterminate", length=320)
        bar.pack(fill="x")
        bar.start(20)
        dlg.update_idletasks()
        x = max(0, (dlg.winfo_screenwidth() - dlg.winfo_reqwidth()) // 2)
        y = max(0, (dlg.winfo_screenheight() - dlg.winfo_reqheight()) // 3)
        dlg.geometry(f"+{x}+{y}")
        try:
            dlg.attributes("-topmost", True)
        except tk.TclError:
            pass
        dlg.update()
        dlg.grab_set()
        return dlg
    except tk.TclError:
        logger.warning("Could not show the exit wait window", exc_info=True)
        return None


class App(tk.Tk):
    """The Tk root.

    Many attributes are populated *after* construction by the tab-
    builder functions in :mod:`app.widgets.tabs` (``fv``, ``pb``,
    every ``*_var`` and ``*_combo``, etc.). They live as forward-
    declared annotations on the class so pyright sees them and so
    refactoring tools follow them; the actual assignment still
    happens in the tab builder.
    """

    entry_file: str = _resolve_entry_file()

    # --- forward declarations of attributes assigned after init -----------
    # Transcribe tab
    fv: tk.StringVar
    file_entry: "ttk.Entry"
    overall_row: "ttk.Frame"
    overall_var: tk.StringVar
    vad_enabled_var: tk.BooleanVar
    word_timestamps_var: tk.BooleanVar
    translate_var: tk.BooleanVar
    translate_check: ttk.Checkbutton
    # Queue tab
    tree: "ttk.Treeview"
    pb: "ttk.Progressbar"
    row_map: dict[str, Any]
    # R2 per-task action bar (assigned in tabs.build_queue_tab).
    queue_action_buttons: dict[str, "ttk.Button"]
    queue_action_bar: "ttk.Frame"  # above the Queue list, as on the Download tab
    queue_result_buttons: dict[str, "ttk.Button"]  # "view", "folder": a finished job's result
    queue_select_hint: "ttk.Label"  # "Select a job in the list..." while nothing is selected
    # Download tab
    download_url_var: tk.StringVar
    # Download tab "Log-in cookies" picker (mirrors Advanced › Downloads).
    download_cookies_var: tk.StringVar
    download_cookies_combo: "ttk.Combobox"
    download_folder_var: tk.StringVar
    # "Install YouTube helper" (Deno for yt-dlp; core.js_runtime).
    js_runtime_button: "ttk.Button"
    format_status_label: "ttk.Label"
    _js_runtime_installing: bool = False
    # v1.0.3 — optional time-range slice on the Download tab. Both
    # vars are created by tabs.build_download_tab and are per-job
    # (DownloadService clears them after enqueue, no config save).
    download_start_time_var: tk.StringVar
    download_end_time_var: tk.StringVar
    # Transcribe-tab time-slice (created by tabs.build_transcribe_tab).
    transcribe_start_time_var: tk.StringVar
    transcribe_end_time_var: tk.StringVar
    # Web / LAN access tab (created by tabs.build_server_tab).
    server_port_var: tk.IntVar
    server_share_lan_var: tk.BooleanVar
    server_token_var: tk.StringVar
    server_https_enabled_var: tk.BooleanVar
    server_webhook_url_var: tk.StringVar
    server_webhook_secret_var: tk.StringVar
    server_status_var: tk.StringVar
    server_url_var: tk.StringVar
    server_toggle_btn: "ttk.Button"
    server_open_btn: "ttk.Button"
    # Phone QR code under the address (shown while shared on the network).
    server_qr_frame: "ttk.Frame"
    server_qr_label: "ttk.Label"
    server_qr_note_var: tk.StringVar
    server_url_label: "ttk.Label"
    # Download-tab position sliders (created by tabs.build_download_tab).
    download_start_scale: "ttk.Scale"
    download_end_scale: "ttk.Scale"
    download_duration_var: tk.StringVar
    download_mode_var: tk.StringVar
    download_mode_combo: "ttk.Combobox"
    audio_format_var: tk.StringVar
    audio_format_combo: "ttk.Combobox"
    video_format_var: tk.StringVar
    video_format_combo: "ttk.Combobox"
    output_format_var: tk.StringVar
    output_format_combo: "ttk.Combobox"
    download_subtitles_var: tk.BooleanVar
    subtitle_lang_var: tk.StringVar
    subtitle_lang_combo: "ttk.Combobox"
    subtitle_status_var: tk.StringVar
    auto_transcribe_var: tk.BooleanVar
    # A link handed over by the Transcribe button: FormatService starts its download once
    # the link's formats are listed ("" = none waiting).
    pending_link_start: str = ""
    make_subbed_video_var: tk.BooleanVar
    # "Use the subtitles" shortcut (built in tabs.build_download_tab;
    # shown/hidden by update_caption_shortcut_state based on what the most
    # recent format lookup found — see app.services.format_service).
    caption_shortcut_status_var: tk.StringVar
    caption_shortcut_button: "ttk.Button"
    # "Subtitles available: ..." line under the link field (update_caption_bar).
    caption_bar_var: tk.StringVar
    caption_bar_label: "ttk.Label"
    smtv_download_all_parts_var: tk.BooleanVar
    # Diarization toggle (Transcribe tab)
    diarization_check: "ttk.Checkbutton"
    diarization_var: tk.BooleanVar
    diarization_speakers_label: "ttk.Label"
    transcribe_time_range_label: "ttk.Label"  # the Speakers count packs back in front of it
    diarization_speakers_var: tk.StringVar
    diarization_speakers_combo: "ttk.Combobox"
    diarization_help_icon: "ttk.Label"
    # Quick-options row on the Transcribe tab
    transcribe_lang_var: tk.StringVar
    # The line beside the Transcribe button: the chosen file's name and size, a link, or why not.
    transcribe_ready_var: tk.StringVar
    # While a job the tab started runs: the button beside that line, and the redraw App.refresh calls.
    transcribe_show_in_queue_btn: "ttk.Button"
    sync_transcribe_ready: "Callable[[], None]"
    mixed_lang_var: tk.BooleanVar
    transcribe_lang2_var: tk.StringVar
    transcribe_lang2_frame: "ttk.Frame"
    device_var: tk.StringVar
    compute_type_var: tk.StringVar
    # Engine picker row on the Transcribe tab (built in tabs.py).
    transcribe_engine_var: tk.StringVar
    transcribe_engine_combo: "ttk.Combobox"
    engine_status_var: tk.StringVar
    engine_status_label: "ttk.Label"
    # Deep (import-based) EngineStatus results cached by value so the picker
    # markers can reflect them without re-probing every engine on the UI
    # thread; cleared whenever the Advanced dialog closes (credentials /
    # installs may have changed while it was open).
    _engine_deep_statuses: "dict[str, Any]"
    # Model picker row on the Transcribe tab (built in tabs.py).
    transcribe_model_var: tk.StringVar
    transcribe_model_advisor_btn: "ttk.Button"
    transcribe_model_combo: "ttk.Combobox"
    _transcribe_model_label_to_slug: "dict[str, str]"
    model_status_var: tk.StringVar
    model_status_label: "ttk.Label"
    # Accuracy row (Fast / Balanced / Best, core/accuracy.py) and the "More options"
    # disclosure on the Transcribe tab, built in tabs.py. The engine + model pickers
    # above live in transcribe_expert_frame, which is never shown.
    transcribe_expert_frame: "ttk.Frame"
    transcribe_accuracy_var: tk.StringVar
    transcribe_accuracy_combo: "ttk.Combobox"
    transcribe_accuracy_pick: "ttk.Frame"
    transcribe_accuracy_note_var: tk.StringVar
    transcribe_accuracy_check_link: "ttk.Label"
    transcribe_more_options: "Disclosure"
    download_more_options: "Disclosure"
    download_quality_row: "WrapRow"
    download_after_row: "WrapRow"
    _transcribe_accuracy_label_to_level: "dict[str, str]"
    _accuracy_ram_gb: float  # this computer's memory; 0 = unknown
    _accuracy_choice: "str | None"  # the level picked or shown last; None = Custom
    # The level a person picked in this session (None = none, or a Custom model since):
    # only this one follows a language change.
    _accuracy_picked_level: "str | None"
    # The "a model trained for <language>" line (ADR 0015), built in tabs.py.
    language_model_anchor: "ttk.Frame"
    language_model_row: "ttk.Frame"
    language_model_hint_var: tk.StringVar
    language_model_button: "ttk.Button"
    # R3: GPU/CPU device badge. The text var is set in update_model_state();
    # the two Labels (Transcribe-tab header + Queue-tab status line) are built
    # in tabs.py and registered here so apply_device_badge can recolour them.
    device_badge_var: tk.StringVar
    device_badge_labels: "list[ttk.Label]"
    device_badge_tip: str
    hotwords_var: tk.StringVar
    format_status_var: tk.StringVar
    # The real yt-dlp/SMTV failure reason from the most recent format
    # lookup, or "" when the lookup succeeded (or hasn't run yet). Lets
    # enqueue_from_form show the user WHY a URL has no formats instead of
    # a generic "wait for formats to load" that's misleading when the
    # lookup already failed and never will load. Set in format_service.
    format_lookup_error: str
    download_tree: "ttk.Treeview"
    download_row_map: dict[str, Any]
    # R2 per-download action bar (assigned in tabs.build_download_tab).
    download_action_buttons: dict[str, "ttk.Button"]
    download_action_bar: "ttk.Frame"  # above the downloads table
    # Set by format_service.lookup_formats / _apply_smtv_formats
    _smtv_episode: Any | None
    # Set by tabs.build_download_tab — toggles the series checkbox.
    # Signature: (visible: bool) -> None
    _smtv_series_toggle: Any
    # Console widget (built by app.widgets.console.build_console)
    txt: "tk.Text"
    # Optional history DB; None when SQLite init fails
    history: "HistoryDB | None"
    # Last-result card on the Transcribe tab
    last_result_frame: "ttk.LabelFrame"
    last_result_empty_var: tk.StringVar
    last_result_empty_label: "ttk.Label"
    last_result_body: "ttk.Frame"
    last_result_title_var: tk.StringVar
    last_result_files_frame: "ttk.Frame"
    # Transcribe-tab empty-state block (shown while the queue is empty)
    transcribe_empty_state: "ttk.Frame"
    transcribe_empty_headline_var: tk.StringVar
    transcribe_browse_row: "ttk.Frame"
    transcribe_sample_row: "ttk.Frame | None"  # the sample button under Browse; None without a sample
    transcribe_has_sample: bool
    # True once drag-and-drop is wired (tkinterdnd2 present and registered)
    _dnd_ready: bool
    # Queue-tab empty-state placeholder
    queue_empty_var: tk.StringVar
    queue_empty_label: "ttk.Label"
    queue_failure_var: tk.StringVar
    queue_failure_label: "ttk.Label"
    # Whether to chime the system bell when a job finishes (View menu)
    chime_on_complete_var: tk.BooleanVar
    # Recent-files submenu rebuilt every time it opens
    _recent_menu: tk.Menu
    # System tray + watched-folder controllers (created lazily)
    tray: "TrayController | None"
    _folder_watcher: "FolderWatcher | None"
    # When True, on_exit treats Tk close as a true exit even when
    # minimise_to_tray is on (set by TrayController._exit_app).
    _exit_from_tray: bool

    def __init__(self) -> None:
        super().__init__()
        if sys.platform == "darwin":
            # A blinking insert cursor costs 35-50% CPU in Tk/aqua while a text
            # box has the focus (measured on macOS 13); a steady caret does not.
            self.option_add("*Text.insertOffTime", 0)
        # Window-title base carries the version so the user can always see
        # which build is running (title bar / taskbar / Alt-Tab).
        self._base_title = f"Whisper Transcriber Suite v{_APP_VERSION}"
        # Cached deep EngineStatus results, keyed by backend value. The
        # pickers overlay these onto their cheap statuses so an engine's
        # "unavailable" marker appears as soon as it has really been probed.
        self._engine_deep_statuses = {}
        self.title(self._base_title)
        # Make any on-demand-installed optional packages importable so
        # feature-availability checks (e.g. stable-ts alignment) see them.
        try:
            from core.optional_deps import activate as _activate_extras
            from core.optional_deps import start_leftover_sweep as _sweep_extras
            _activate_extras()
            # Undo what an install cut short by a crash or an exit left behind.
            _sweep_extras()
        except Exception:  # noqa: BLE001
            pass
        self._install_icon()
        # High-DPI scaling: pick up the system DPI so fonts and
        # paddings don't shrink to dollhouse size on 150 % displays.
        self._apply_hidpi_scaling()
        # Restore the user's saved window geometry if any; falls back
        # to a sensible default. _save_window_geometry persists it on
        # the WM_DELETE_WINDOW exit path.
        saved_geom = load_config().get("window_geometry") or ""
        # "960x640..." was the old fixed default, not a size the user chose;
        # the tabs have outgrown it (labels were truncated, lists cut off),
        # so treat it like "no saved size" and fit the screen instead.
        if (
            isinstance(saved_geom, str) and saved_geom.count("x") == 1
            and not saved_geom.startswith("960x640")
            # Saved on a monitor that is gone (a laptop undocked): the window
            # would open where nobody can see or reach it.
            and _saved_geometry_visible(saved_geom, _point_on_a_monitor)
        ):
            try:
                self.geometry(saved_geom)
            except Exception:  # noqa: BLE001
                self._apply_default_geometry()
        else:
            self._apply_default_geometry()
        # Nothing previously stopped the user (or a stale saved
        # window_geometry from an older, less-crowded layout) from
        # shrinking the window below the size every tab's layout is
        # actually laid out for — pack(side="left") rows don't wrap,
        # they silently clip. 960x640 is the app's own chosen default,
        # not an arbitrary number; this only stops shrinking below it,
        # growing is unaffected.
        self.minsize(*scaled_size(self, 960, 640))
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

        # Per-instance queues (no more module-globals — AUDIT B3 fix).
        self.queue: list[TranscriptionTask] = []
        self.download_queue: list[VideoDownloadTask] = []
        self.download_current: VideoDownloadTask | None = None

        self.status_var = tk.StringVar(value=_("Initializing..."))
        # R3: device badge state created up-front so a worker "ready" event
        # firing before the tabs are built can't AttributeError. The Labels
        # register themselves in tabs.py; apply_device_badge recolours them.
        self.device_badge_var = tk.StringVar(value="")
        self.device_badge_labels: list[ttk.Label] = []
        self.device_badge_tip = ""
        self.model_ready = False
        self.model_loading = False
        self.model_setup_running = False
        self.workers: list[dict[str, Any]] = []
        # Audit A13: bound the inter-thread event queues. 2000 is
        # well above normal traffic (~1-5 events/s per worker) but
        # caps memory in catastrophic cases (Tk frozen, thousands
        # of files dropped into the watcher at once). Producers
        # block on Full rather than OOM the process — easier to
        # diagnose.
        self.worker_events: Queue = Queue(maxsize=2000)
        self.worker_ready = False
        # Background threads (burn-subs worker, hardware-wizard benchmark,
        # tray clicks, …) can't call self.after() directly on Python 3.14
        # (RuntimeError; undefined on earlier 3.x). They push callables
        # here; _drain_main_calls() runs them on the Tk main thread.
        # Created before _build_tabs: tab builders start background probes
        # (e.g. the engine-status check) whose post_to_main used to land
        # before this queue existed -> AttributeError in that thread and
        # the result silently lost.
        self._main_thread_calls: Queue = Queue(maxsize=2000)
        self.app_config = load_config()
        # Work offline, held in memory from here on (before the crash
        # reporter and the launch ping, which both ask it).
        offline.set_offline(offline.flag_from(self.app_config))
        if offline.is_offline():
            self.title(_("{title} — Work offline", title=self._base_title))
        setup_logging(self.app_config.get("log_level", "INFO"))
        init_sentry()
        send_launch_ping_async()
        self._ui_logger = get_ui_logger()
        logger.info("App startup; theme=%s", self.app_config.get("theme", "dark"))
        self.theme_var = tk.StringVar(value=self.app_config.get("theme", "light"))
        # macOS: pin each window's title bar to the theme mode BEFORE it is resolved ("System" must
        # be set back to auto first: Tk's isdark answer comes from the window's own appearance).
        mac_appearance.set_enabled(self.app_config.get("native_window_theme", True))
        mac_appearance.install(self, self.theme_var.get())
        start_theme = _resolve_theme(self.theme_var.get())
        sv_ttk.set_theme(start_theme)
        theme_colours.fix_accent_button(self)
        script_fonts.apply_theme_fonts(self)
        theme_colours.apply(self, start_theme)
        win_chrome.set_enabled(self.app_config.get("native_window_theme", True))
        win_chrome.install(self, start_theme)
        win_taskbar.set_enabled(self.app_config.get("native_taskbar", True))
        self._system_theme_watch = system_appearance.SystemThemeWatcher(
            self, self._on_system_theme_change)
        self._sync_system_theme_watch(self.theme_var.get())
        remember_scale(self)
        # 0 = automatic: one job at a time on a CPU, two on a GPU (TranscriptionService.worker_limit).
        self.parallel_workers = max(0, int(self.app_config.get("parallel_workers", 0)))
        self.next_worker_id = 1
        self.format_events: Queue = Queue(maxsize=2000)
        self.download_events: Queue = Queue(maxsize=2000)
        self.audio_format_map: dict[str, dict[str, Any]] = {}
        self.video_format_map: dict[str, dict[str, Any]] = {}
        self.current_video_title = ""
        self.current_video_language = ""
        # code -> "manual" / "auto"; set by format_service after each
        # lookup, read by update_caption_shortcut_state.
        self.current_video_caption_langs: dict[str, str] = {}
        self.format_lookup_after: str | None = None

        # Services
        self.format_service = FormatService(self)
        self.download_service = DownloadService(self)
        self.transcription_service = TranscriptionService(self)
        self.integrations_service = IntegrationsService(self)
        # Optional in-process web / LAN server (built lazily on first
        # Start so importing core.server — and its model load — is paid
        # only when the user actually turns it on). None = never started.
        self._server_handle: Any = None
        # True while a start/stop worker thread is in flight, so the
        # toggle button can't be double-fired into a half-built state.
        self._server_busy = False

        # SQLite history (Phase 3a). Mark any pre-crash row as interrupted on launch.
        try:
            self.history = HistoryDB()
            interrupted = self.history.mark_interrupted_on_launch()
            # Only the owning instance offers crash resume: the other's
            # "interrupted" rows may be on offer (or re-queued) there.
            self._history_owner = interrupted is not None
            if interrupted is None:
                logger.info("Another app instance owns the history; running rows left alone")
            elif interrupted:
                logger.info("Marked %d running rows as interrupted on launch", interrupted)
        except Exception as e:  # noqa: BLE001
            logger.warning("history.db unavailable: %s", e)
            self.history = None

        # Update notice (core.updates + app.widgets.update_bar): the bar is
        # built on first use; the last check result feeds its buttons.
        self._update_bar: Any = None
        self._latest_update: Any = None
        self._whats_new_window: Any = None
        self._update_bar_shown_this_launch = False
        # The timer of a bar held back while a job runs (_retry_update_bar).
        self._update_bar_retry_id: Any = None
        # "The video downloader may be out of date" bar (core.yt_dlp_update):
        # offered after a download or format lookup fails the way an
        # outdated yt-dlp fails; "Not now" keeps it away for this launch.
        self._yt_dlp_bar: Any = None
        self._yt_dlp_bar_dismissed = False
        self._yt_dlp_updating = False
        # True while the bar shows only the offer (not an update's progress or
        # result): a later successful lookup or download takes it down again.
        self._yt_dlp_offer_open = False
        # The gentle star invitation (core.star_invite): local counters in
        # app_config, the bar is built on first use.
        self._star_bar: Any = None
        self._star_stamp_first_run()

        self._build_menu()
        # macOS: the app menu, Finder "Open With" and the Dock icon call back
        # into the app. Registered before the first event-loop turn so a file
        # that launched the app waits in a queue instead of being lost.
        self._start_ran = False
        self._hub_setup_open = False
        mac_native.install(self)
        self._refresh_update_signs()
        # Right-to-left interface: every dialog is mirrored once when it first shows; the
        # tabs are mirrored one by one at the end of _build_tabs (the root is never).
        rtl_layout.install_window_hook(self)
        self._build_tabs()
        self.txt = build_console(self, theme=_resolve_theme(self.theme_var.get()))
        self._refresh_offline_status()

        # Wire global keyboard shortcuts now that the widgets exist:
        #   Ctrl+O          → Browse for a file to transcribe
        #   Ctrl+Enter      → Start transcribing whatever is in the
        #                     file picker
        #   Esc             → Cancel the currently-running task
        #   Ctrl+Q          → Quit (same as File → Exit)
        # Ctrl on Windows/Linux, Command on macOS (app/shortcuts.py).
        if not shortcuts.is_mac():
            # On macOS the File menu's Browse item carries the Command-O
            # accelerator itself; a second root bind could fire twice.
            shortcuts.bind_shortcut(self, "o", self.browse)
        shortcuts.bind_shortcut(self, "Return", self.add)
        self.bind("<Escape>", lambda _e: self._cancel_running())
        if not shortcuts.is_mac():
            # Ctrl+Q always exits — same convention as File→Exit. On macOS
            # Command-Q arrives through the native app-menu Quit instead
            # (tk::mac::Quit, registered by _install_quit_handler once the
            # attributes on_exit reads exist, see below).
            shortcuts.bind_shortcut(self, "q", self._force_exit)

        # Opt-in drag-and-drop on the main window. tkinterdnd2 is in
        # requirements.txt but the desktop app stays usable even if
        # the import fails — we just log and skip.
        self._install_drag_drop()

        # System tray + watched folder. Both are best-effort: missing
        # dependencies (pystray / Pillow / watchdog) silently disable
        # the feature rather than blocking app startup.
        self.tray = None
        self._folder_watcher = None
        self._exit_from_tray = False
        # Flag flipped to True at the top of on_exit so watcher
        # callbacks / stability-check ticks short-circuit before
        # touching destroyed widgets. Keep watched_after_ids so
        # each path only schedules ONE stability-check ladder.
        self._closing = False
        self._exit_waiting = False  # True while on_exit waits for viewer exports (loop() starts nothing)
        # Cmd+Q / app-menu Quit / Dock Quit (macOS) reach on_exit, which reads
        # tray, _exit_from_tray and _closing: install only once they exist.
        self._install_quit_handler()
        # Last error text per loop() step, so a step that keeps failing is
        # logged once instead of twice a second (see _log_loop_error).
        self._loop_errors: dict[str, str] = {}
        # Last Tk callback error shown in the console (report_callback_exception).
        self._last_callback_error = ""
        # True while the quick start window is open (see _on_start).
        self._quick_start_open = False
        self._watched_after_ids: dict[str, str] = {}
        # Watched files waiting for the model to load before they are queued,
        # so a second event for the same file meanwhile does not queue it twice.
        self._watched_pending: set[str] = set()
        # Thread-safe queue drained on the Tk main thread by
        # _drain_watched_paths. watchdog fires callbacks from a
        # background thread; on Python 3.14 calling self.after()
        # from a non-main thread raises RuntimeError. Routing
        # through this queue lets us bounce safely.
        #
        # Sibling queue: _main_thread_calls (below) — same idea, but
        # for arbitrary callables coming from ANY background thread
        # (burn-subs worker, hardware-wizard benchmark, tray clicks).
        # _watched_path_queue is filesystem-watcher → main thread;
        # _main_thread_calls is any-thread → main thread.
        self._watched_path_queue: Queue = Queue(maxsize=2000)
        # (_main_thread_calls itself is created near the top of __init__,
        # before _build_tabs -- see the comment there.)
        self._install_tray()
        self._install_clipboard_keys()
        self._install_text_context_menu()
        self._restart_watched_folder()
        self.after(250, self._drain_watched_paths)
        self.after(50, self._drain_main_calls)

        # Auto-resume after crash: history.mark_interrupted() above
        # flipped rows from running → interrupted. If any of those
        # files still exist on disk, offer to re-enqueue them.
        self.after(700, self._maybe_offer_crash_resume)

        # Bound the partials/ dir: sweep orphaned resume slices + aged-out
        # checkpoints so a killed/declined run doesn't accumulate forever.
        self.after(1500, self._sweep_partials_at_startup)
        # First run, Windows: offer the language the regional format and the keyboard point to.
        self.after(2500, lambda: language_suggestion.maybe_suggest(self))

        self.after(100, self._on_start)
        self.after(300, self.loop)

        # GitHub update check (on by default). Fired ~4 s after launch
        # so it never competes with first-paint / model-setup work. The
        # check runs on a daemon thread; it is gated by
        # update_check_enabled AND a once-per-day throttle, and it stays
        # SILENT unless an update is actually available (no nagging when
        # up to date, offline, or on a private repo); a found update shows
        # the quiet bar, never a dialog. See _run_update_check /
        # core.updates.
        self.after(4000, self._maybe_quiet_update_check)
        # Re-read the versions of the bundled and the updated yt-dlp copy when
        # either changed since they were recorded (after an app update);
        # local only, and a no-op until the copy exists.
        self.after(6000, self._refresh_yt_dlp_versions)

    def _sweep_partials_at_startup(self) -> None:
        """Off-thread best-effort cleanup of the partials/ checkpoint dir."""
        import threading as _t

        def _work() -> None:
            try:
                from core import _checkpoint
                removed = _checkpoint.sweep_partials()
                if removed:
                    logger.info(
                        "Startup sweep removed %d stale partial file(s).", removed
                    )
            except Exception:  # noqa: BLE001
                logger.debug("partials sweep failed", exc_info=True)
            # What a crashed or killed run left of a subtitle burn (journal-driven).
            try:
                from core import burn_subs
                burn_subs.sweep_stale_burns()
            except Exception:  # noqa: BLE001
                logger.warning("burn leftovers sweep failed", exc_info=True)

        _t.Thread(target=_work, name="partials-sweep", daemon=True).start()

    # Bootstrap ---------------------------------------------------------------
    def _on_start(self) -> None:
        # First-run windows: quick start, then the Hub Folder picker.
        #
        # v1.0.3 — lazy model load.
        # We used to call ``transcription_service.start_standby()`` here
        # (and in the hub-setup callbacks) so the Whisper model was
        # already in RAM when the user clicked Transcribe. That cost
        # ~1.5 GB of idle memory + a CPU spike on EVERY launch, even
        # for sessions where the user never transcribed (e.g. opened
        # the app just to browse history or download a video).
        #
        # The worker now spawns on the first transcribe request via
        # ``TranscriptionService.ensure_worker_ready``, which shows a
        # short modal "Loading Whisper model…" dialog. Do NOT re-add
        # the standby calls here — the trade-off is intentional.
        #
        # A new install first gets the quick start window (language, Fast or
        # Best quality, output folder). Finish also settles the model folder;
        # Skip falls through to the hub-setup dialog, as before.
        # Both first-run windows are created below, in this one call; files
        # macOS handed over earlier (mac_native) may now wait for them.
        self._start_ran = True
        if should_show(self.app_config):
            try:
                self._quick_start_open = True
                from core.sample_clip import bundled_clip_path

                def _try_sample_soon() -> None:
                    # After the dialog is gone, so the model prompt is not under it.
                    self.after(200, self.try_sample_clip)

                QuickStartDialog(
                    self, self.app_config, on_done=self._on_quick_start_done,
                    on_try_sample=_try_sample_soon if bundled_clip_path() else None,
                )
                return
            except Exception as e:  # noqa: BLE001
                self._quick_start_open = False
                logger.warning("Quick start window failed: %s", e)
        self._ensure_hub_folder()

    def _on_quick_start_done(self, choice: QuickStartChoice | None) -> None:
        """Save the quick start outcome, then sync the widgets that show it."""
        self._quick_start_open = False
        apply_choice(self.app_config, choice)
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save the quick start choices")
            self.log(f"Could not save the quick start choices: {e}")
        if choice is None:
            self._ensure_hub_folder()
            return
        var = getattr(self, "download_folder_var", None)
        if var is not None:
            var.set(self.app_config.get("download_folder", ""))
        # The language the user just named is this session's Transcribe language (the picker
        # still opens on Auto next launch); before, the window chose the model with it and the
        # tab kept showing Auto (found in a click-through test, 2026-10-21).
        from app.dialogs.quick_start import language_name_for
        lang_var = getattr(self, "transcribe_lang_var", None)
        name = language_name_for(choice.language)
        if lang_var is not None and name:
            lang_var.set(name)
        self._refresh_model_selector()
        # The engine row was probed at start-up, before the model folder existed;
        # re-probe it (and drop the cached verdicts) so it agrees with the model row.
        self._refresh_engine_selector()
        self.log(
            f"Quick start: model {self.app_config.get('whisper_model')}, downloads go to "
            f"{self.app_config.get('download_folder')}. The model downloads on the first "
            "transcription."
        )

    def _ensure_hub_folder(self) -> None:
        """First-run Hub Folder picker, when no model folder is set yet."""
        # The hub-setup dialog still fires on first launch so the user
        # picks where models live; we just don't preload the model.
        from core import hub as _hub

        if _hub.is_hub_configured(self.app_config):
            return

        try:
            from app.dialogs.hub_setup import ensure_hub_configured

            def _hub_picked(path: str) -> None:
                self._hub_setup_open = False
                self.log(f"Model hub folder set to: {path}")
                try:
                    self.app_config = load_config()
                except Exception:  # noqa: BLE001
                    pass
                # The model rows were worked out before this folder was chosen.
                self._refresh_model_selector()
                self._refresh_engine_selector()

            # Open until on_done (Choose and Cancel both call it); the macOS
            # file queue waits for it (mac_native.ready_for_documents).
            self._hub_setup_open = True
            ensure_hub_configured(
                self, self.app_config,
                on_done=_hub_picked,
            )
        except Exception as e:  # noqa: BLE001
            self._hub_setup_open = False
            logger.warning("Hub setup dialog failed: %s", e)

    # Menu --------------------------------------------------------------------
    def _build_menu(self) -> None:
        # Tk's macOS (Aqua) port gives the app menu, the Window menu and the
        # Help menu their native form (app/mac_native.py); Windows and Linux
        # build the menu bar exactly as before.
        aqua = mac_native.is_aqua(self)
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(**shortcuts.menu_item(_("Browse..."), "o", gap=26), command=self.browse)
        # Recent files submenu — populated from history.db at menu-open
        # time so it always reflects the latest run. Skips when history
        # is None (SQLite init failed) and shows a single disabled
        # "(no recent files)" placeholder.
        self._recent_menu = tk.Menu(f, tearoff=0, postcommand=self._populate_recent_menu)
        f.add_cascade(label=_("Recent files"), menu=self._recent_menu)
        f.add_separator()
        f.add_command(label=_("Convert transcript..."), command=self.convert_transcript)
        f.add_separator()
        f.add_command(label=_("Statistics..."), command=self.show_statistics)
        f.add_separator()
        # Work offline (core.offline): no network connection at all while
        # ticked. Same config key as the Advanced → App behaviour checkbox;
        # open_advanced_dialog re-syncs this item after the dialog closes.
        self.work_offline_var = tk.BooleanVar(value=offline.is_offline())
        f.add_checkbutton(
            label=translate(_WORK_OFFLINE_LABEL),
            variable=self.work_offline_var,
            command=self._toggle_work_offline,
        )
        if not shortcuts.is_mac():
            f.add_separator()
            # File→Exit bypasses the minimise-to-tray redirect. When the
            # user explicitly clicks Exit they mean exit; the redirect is
            # only for the window-close (X) button. macOS has no Exit item
            # here: the app menu already carries "Quit <App>".
            f.add_command(**shortcuts.menu_item(_("Exit"), "q", gap=34),
                          command=self._force_exit)
        if aqua:
            # Command-W closes the front secondary window (viewer, dialog) with
            # its own close handler; it never closes the main window.
            f.add_separator()
            f.add_command(
                **shortcuts.menu_item(_("Close Window"), "w"),
                command=lambda: mac_native.close_front_window(self),
            )

        v = tk.Menu(m, tearoff=0)
        # The label is display only; the radio button stores the English value.
        for label, value in ((pgettext("theme", "Light"), "light"),
                             (pgettext("theme", "Dark"), "dark"),
                             (pgettext("theme", "System"), "system")):
            v.add_radiobutton(label=label, value=value, variable=self.theme_var, command=self.apply_theme)
        v.add_separator()
        # Audible-cue toggle. Stored in app_config so the user's choice
        # survives a restart. Default ON — first-time users want to
        # know when a long job completes.
        self.chime_on_complete_var = tk.BooleanVar(
            value=bool(self.app_config.get("chime_on_complete", True))
        )
        v.add_checkbutton(
            label=desktop_alert.chime_menu_label(self),
            variable=self.chime_on_complete_var,
            command=self._save_chime_pref,
        )
        v.add_separator()
        # The same chooser as the globe button above the tabs.
        v.add_command(label=_("Interface language…"), command=self.open_ui_language_chooser)

        h = tk.Menu(m, tearoff=0, **mac_native.help_menu_kwargs(self))
        h.add_command(label=_("Open transcript viewer..."), command=self._open_transcript_viewer_picker)
        h.add_command(label=_("Search transcripts..."), command=self._open_search_dialog)
        h.add_separator()
        # oTranscribe round-trip — used to be a button on the Transcribe
        # tab; moved here in the UI simplification pass because it's a
        # secondary workflow (most users never touch it), and consumer
        # transcription apps (MacWhisper, Buzz, Aiko) keep
        # secondary imports under a menu.
        h.add_command(
            label=_("Import oTranscribe (.otr) → SRT..."),
            command=self.integrations_service.import_otr_to_srt,
        )
        h.add_command(label=_("Open oTranscribe website..."),
                      command=self.integrations_service.open_otranscribe)
        h.add_separator()
        h.add_command(label=folder_label(_("Open log folder"), _("Open Log Folder in Finder")),
                      command=self.open_log_folder)
        # For AI assistants: the `claude mcp add` command for this app's MCP
        # endpoint, with the live port filled in (the password stays a
        # placeholder — the clipboard never carries the real one).
        h.add_command(label=_("Copy MCP setup"), command=self.copy_mcp_setup)
        h.add_separator()
        # Manual update check — always runs (ignores the once-per-day
        # throttle the quiet launch check obeys) and DOES report the
        # "you're up to date" / "couldn't reach the server" cases, unlike
        # the silent launch check. Never downloads/installs anything.
        # _refresh_update_signs adds a dot to this item (and, off macOS, to the
        # "Help" title) while a newer version is known (the passive sign).
        h.add_command(label=translate(_CHECK_FOR_UPDATES_LABEL),
                      command=self._check_for_updates_manual)
        self._help_menu = h
        self._check_updates_index = h.index("end")
        h.add_separator()
        # The usage-statistics switch, reachable without opening Advanced.
        # Same config key as the Advanced → App behaviour checkbox: the dialog
        # reads app_config when it opens, and open_advanced_dialog re-syncs
        # this item after the dialog closes, so the two never disagree.
        self.telemetry_opt_in_var = tk.BooleanVar(
            value=bool(self.app_config.get("telemetry_opt_in", True))
        )
        h.add_checkbutton(
            label=_("Usage statistics"),
            variable=self.telemetry_opt_in_var,
            command=self._save_telemetry_pref,
        )
        # Report a problem sits right above About. About is the last Help item
        # (the usual place), one click from Help. On macOS it lives in the app
        # menu instead ("About <App>", wired to tkAboutDialog by
        # mac_native.install), so Help does not repeat it.
        h.add_separator()
        h.add_command(label=_("Report a problem…"),
                      command=lambda: self._open_problem_report(self))
        if not aqua:
            h.add_command(label=translate(_ABOUT_MENU_LABEL), command=self._show_about)
        m.add_cascade(label=pgettext("menu", "File"), menu=f)
        m.add_cascade(label=pgettext("menu", "View"), menu=v)
        if aqua:
            # The standard Window menu: Minimize, Zoom, Bring All to Front and
            # the list of open windows are added by macOS itself.
            m.add_cascade(
                label=pgettext("menu", "Window"),
                menu=tk.Menu(m, tearoff=0, **mac_native.window_menu_kwargs(self)),
            )
        # macOS adds its search field only to a Help menu titled exactly "Help" (see
        # _refresh_update_signs), so the Aqua title stays English.
        m.add_cascade(label=_HELP_MENU_LABEL if aqua else translate(_HELP_MENU_LABEL), menu=h)
        self._menubar = m
        self._help_cascade_index = m.index("end")
        self.config(menu=m)

    def _populate_recent_menu(self) -> None:
        """Re-populate the File > Recent files submenu from history.db.

        Called automatically by Tk every time the user opens the
        submenu (via the ``postcommand`` hook), so the list is always
        current. We list the last 10 file_paths from the history.db
        transcriptions table; an "Open file" click sets fv + selects
        the Transcribe tab without auto-enqueueing.
        """
        menu = self._recent_menu
        menu.delete(0, "end")
        history = getattr(self, "history", None)
        rows: list[dict[str, Any]] = []
        if history is not None:
            try:
                rows = history.list_transcriptions(limit=10) or []
            except Exception:  # noqa: BLE001
                rows = []
        # Paths the user cleared via "Clear list" are hidden until a new
        # transcription re-adds them. Stored in config.json (the storage
        # this app manages) because HistoryDB has no clear method.
        dismissed: set[str] = set(self.app_config.get("recent_files_dismissed") or [])
        if not rows:
            menu.add_command(label=_("(no recent files)"), state="disabled")
            return
        seen: set[str] = set()
        added = 0
        for row in rows:
            path = row.get("file_path") if isinstance(row, dict) else None
            if not path or path in seen or path in dismissed:
                continue
            seen.add(path)
            label = f"{os.path.basename(path)}  —  {os.path.dirname(path)[:48]}"
            menu.add_command(
                label=label,
                command=lambda p=path: self._open_recent(p),
            )
            added += 1
            if added >= 10:
                break
        if added == 0:
            # Every history row is currently dismissed (the user clicked
            # "Clear list"); show the empty placeholder instead of a lone
            # "Clear list" that has nothing to clear.
            menu.add_command(label=_("(no recent files)"), state="disabled")
            return
        menu.add_separator()
        menu.add_command(label=_("Clear list"), command=self._clear_recent)

    def _burn_subs_for(self, task: TranscriptionTask) -> None:
        """Burn the task's SRT into a new MP4.

        Uses the SRT the task really wrote (``task.output_paths``), so a
        re-run burns its own subtitles, not the previous run's. Runs ffmpeg
        in a daemon thread so the UI stays responsive on long videos. On
        completion, surfaces a log line + chimes + opens the output folder.
        Failure logs via messagebox.
        """
        from core import burn_subs

        base, _unused = os.path.splitext(task.file_path)
        srt_path = task_srt_output(task)
        if srt_path is None:
            messagebox.showwarning(
                _("No SRT found"),
                _("This task has no SRT file on disk. Add SRT to the output "
                  "formats and run it again.\nLooked for:\n{path}", path=f"{base}.srt"),
                parent=self,
            )
            return
        # Suggest "<base>-subbed.mp4" so the source is never clobbered.
        suggested = base + "-subbed.mp4"
        out_path = filedialog.asksaveasfilename(
            parent=self,
            title=_("Save burned-in video as..."),
            initialdir=os.path.dirname(os.path.abspath(task.file_path)),
            initialfile=os.path.basename(suggested),
            defaultextension=".mp4",
            filetypes=[(_("MP4 video"), "*.mp4"), (_("All files"), "*.*")],
        )
        if not out_path:
            return

        self.log(f"Burning subtitles into {os.path.basename(out_path)}...")

        def worker() -> None:
            try:
                final_out = burn_subs.burn(task.file_path, srt_path, out_path) or out_path
                # Tk methods touched from a thread → route via the
                # main-thread queue (self.after(0, ...) from a worker
                # raises RuntimeError on Python 3.14).
                self.post_to_main(lambda p=final_out: self._burn_subs_done(p))
            except burn_subs.BurnCancelled:
                # The app is closing (burn_subs.abandon_active_burns).
                logger.info("Subtitle burn stopped: %s", out_path)
            except Exception as e:  # noqa: BLE001
                # Audit B3: log the stack trace before the lossy
                # UI string-conversion so postmortem diagnosis is
                # possible from logs alone.
                logger.exception(
                    "burn_subs.burn failed: file=%s out=%s",
                    task.file_path, out_path,
                )
                msg = str(e)
                self.post_to_main(lambda: self._burn_subs_failed(msg))

        from core._threads import safe_thread
        safe_thread(worker, name="burn-subs")

    def _burn_subs_done(self, out_path: str) -> None:
        self.log(f"✓ Burned subtitles → {out_path}")
        if getattr(self, "chime_on_complete_var", None) is not None:
            try:
                if self.chime_on_complete_var.get():
                    self.bell()
            except Exception:  # noqa: BLE001
                pass
        desktop_alert.burn_done(self, out_path)
        self._open_folder(os.path.dirname(out_path) or ".", select=out_path)

    def _burn_subs_failed(self, msg: str) -> None:
        self.log(f"Burn-subs failed: {msg}")
        messagebox.showerror(_("Burn subtitles failed"), msg, parent=self)

    def _open_transcript_viewer_picker(self) -> None:
        """Open the transcript viewer with a file picker."""
        _open_transcript_viewer(self, None)

    def _open_search_dialog(self) -> None:
        """Open the full-text search dialog over every saved transcript."""
        from app.dialogs.search_dialog import open_search_dialog
        open_search_dialog(self)

    def open_transcript_viewer_for(
        self, file_path: str, json_path: str | None = None,
        language: str | None = None,
    ) -> None:
        """Open the viewer for the transcript JSON belonging to a task.

        Used by the Last Result card's and queue menu's "View transcript"
        button so the user is one click away from the just-finished output.

        Prefer the ACTUAL .json the worker reported writing (``json_path``,
        usually pulled from ``task.output_paths``): the basename can differ
        from the source media when the output was templated or relocated, so
        recomputing ``splitext(file_path)[0] + '.json'`` would miss it and
        pop a confusing file picker even though a real transcript exists.
        Only when no known JSON is on disk do we fall back to recomputing the
        beside-input name, and finally to an explanation that offers the
        picker. ``language`` (the
        task's chosen or detected language) reaches the viewer for its
        per-script fonts; a file picked by hand gets none.
        """
        # The task's own source is the viewer's media: pairing by the JSON's
        # name misses re-runs ("name (1).json") and relocated outputs.
        if json_path and os.path.isfile(json_path):
            _open_transcript_viewer(
                self, json_path, language=language, media_path=file_path
            )
            return
        base, _unused = os.path.splitext(file_path)
        guessed = base + ".json"
        if os.path.isfile(guessed):
            _open_transcript_viewer(
                self, guessed, language=language, media_path=file_path
            )
        else:
            # The viewer reads and saves .json files only; a run that wrote
            # just srt/vtt/... (json not among the formats) has nothing to open.
            # Say so, and still let the user pick a .json by hand.
            if messagebox.askyesno(
                _("View transcript"),
                _("No transcript .json was saved for {name}: "
                  "the viewer opens .json files only. Turn on \"Whisper JSON\" in the "
                  "output formats to get one next time. "
                  "Choose a .json file yourself?", name=os.path.basename(file_path)),
                parent=self,
            ):
                _open_transcript_viewer(self, None)

    def _save_shareable_page_for(
        self, file_path: str, json_path: str, language: str | None = None,
    ) -> None:
        """Last Result card: save the task's transcript JSON as a shareable web page,
        linking the task's own source media."""
        try:
            segments = share_page.load_transcript(json_path)
        except (OSError, ValueError) as e:
            messagebox.showerror(
                translate(share_page.BUTTON_TEXT),
                _("Could not read {path}:\n{error}", path=json_path, error=e),
                parent=self,
            )
            return
        share_page.save_shareable_page(
            self,
            segments=segments,
            media_path=file_path,
            json_path=json_path,
            chapters=share_page.load_chapters(json_path),
            language=language,
        )

    @staticmethod
    def _task_json_output(task: Any) -> str | None:
        """Return the transcript .json path the task actually wrote, if known.

        Reads ``task.output_paths`` (the exact files the worker reported),
        the source of truth for the viewer, robust to templated/relocated
        output names. The auto-chapters ``.chapters.json`` sidecar is not a
        transcript and is never returned (None when json was not an output).
        """
        return task_transcript_json(task)


    def _open_recent(self, path: str) -> None:
        if not os.path.isfile(path):
            messagebox.showwarning(
                _("File missing"),
                _("That file is no longer at:\n{path}", path=path),
                parent=self,
            )
            return
        self.nb.select(self.t1)  # first: the box scrolls best once its tab is shown
        _show_file_in_box(self, path)

    def _clear_recent(self) -> None:
        """Clear the File > Recent files list.

        HistoryDB has no clear method (and core/history.py is owned
        elsewhere), so instead of deleting history rows we hide the
        currently-listed paths via a dismissed-set persisted in config.json
        — the storage this app already manages. _populate_recent_menu
        filters these out, so the submenu shows "(no recent files)" until
        new transcriptions arrive. This is a true clear of the *list* the
        user sees, without touching the underlying history DB.
        """
        history = getattr(self, "history", None)
        # Snapshot whatever the menu would currently show and add it to the
        # dismissed set. New transcriptions (paths not in the set) reappear.
        paths: list[str] = []
        if history is not None:
            try:
                rows = history.list_transcriptions(limit=10) or []
            except Exception:  # noqa: BLE001
                rows = []
            for row in rows:
                p = row.get("file_path") if isinstance(row, dict) else None
                if isinstance(p, str) and p:
                    paths.append(p)
        dismissed = set(self.app_config.get("recent_files_dismissed") or [])
        dismissed.update(paths)
        self.app_config["recent_files_dismissed"] = sorted(dismissed)
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to persist cleared recent-files list")
            self.log(f"Could not save cleared recent list: {e}")

    def _save_download_prefs(self) -> None:
        """Write the Download tab's remembered state (the "More options" disclosure) to disk."""
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save the Download tab preferences")
            self.log(f"Could not save preference: {e}")

    def _save_chime_pref(self) -> None:
        self.app_config["chime_on_complete"] = bool(self.chime_on_complete_var.get())
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save chime preference")
            self.log(f"Could not save preference: {e}")

    def _save_telemetry_pref(self) -> None:
        """Help → Usage statistics: store the choice like the Advanced checkbox does."""
        on = bool(self.telemetry_opt_in_var.get())
        self.app_config["telemetry_opt_in"] = on
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save the usage-statistics choice")
            self.log(f"Could not save preference: {e}")
            return
        self.log("Usage statistics: on." if on else "Usage statistics: off (nothing is sent).")

    def _sync_telemetry_menu(self) -> None:
        """Make the Help menu item show the current config (after the Advanced dialog)."""
        var = getattr(self, "telemetry_opt_in_var", None)
        if var is not None:
            var.set(bool(self.app_config.get("telemetry_opt_in", True)))

    def _toggle_work_offline(self) -> None:
        """File → Work offline: apply and store the ticked state."""
        self._set_work_offline(bool(self.work_offline_var.get()))

    def _set_work_offline(self, on: bool) -> None:
        """Turn Work offline on or off for this process and store the choice.

        The in-memory switch changes first, so nothing in this process goes
        online after the click even if the save fails; worker processes read
        the saved file, so a failed save is reported.
        """
        self.app_config[offline.CONFIG_KEY] = on
        if on and not offline.is_offline():
            offline.reset_activity()
        offline.set_offline(on)
        var = getattr(self, "work_offline_var", None)
        if var is not None:
            var.set(on)
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save the Work offline choice")
            text = _(
                "Could not save the Work offline choice ({error}); a transcription "
                "that starts a new worker follows the old setting.", error=e,
            )
            self.log(text)
            notify(self, text, "warning")
        if on:
            self.log(
                "Work offline: on. From now on the app starts no network "
                "connection; a download or install already running finishes first."
            )
            if _inst_attr(self, "_update_bar") is not None:
                self._hide_update_bar()
            self._hide_star_bar()
        else:
            self.log("Work offline: off.")
            self._retry_refused_link_lookup()
        self._refresh_window_title()
        self._refresh_offline_status()

    def _retry_refused_link_lookup(self) -> None:
        """Look the pasted link up again when only Work offline had stopped it."""
        error = str(getattr(self, "format_lookup_error", "") or "")
        url_var = getattr(self, "download_url_var", None)
        service = getattr(self, "format_service", None)
        if (
            error.startswith("Offline mode is on")
            and url_var is not None and url_var.get().strip()
            and service is not None
        ):
            service.lookup_formats()

    def _sync_offline_menu(self) -> None:
        """After the Advanced dialog: the File menu item and the switch follow the config."""
        on = offline.flag_from(self.app_config)
        was = offline.is_offline()
        if on and not was:
            offline.reset_activity()
        offline.set_offline(on)
        var = getattr(self, "work_offline_var", None)
        if var is not None:
            var.set(on)
        if on and not was:
            if _inst_attr(self, "_update_bar") is not None:
                self._hide_update_bar()
            self._hide_star_bar()
        elif was and not on:
            self._retry_refused_link_lookup()
        self._refresh_window_title()
        self._refresh_offline_status()

    def _refresh_offline_status(self) -> None:
        """Show the Work offline line (and its Network log button) only while the switch is on."""
        nb = _inst_attr(self, "nb")
        if nb is None:
            return  # before the tabs exist; called again once they do
        bar = _inst_attr(self, "_offline_bar")
        if not offline.is_offline():
            if bar is not None:
                bar.hide()
            return
        if bar is None:
            from app.widgets.offline_status import OfflineStatusBar
            bar = OfflineStatusBar(self, post_to_main=self.post_to_main)
            rtl_layout.mirror_tree(bar)
            self._offline_bar = bar
        bar.show(before=nb)

    def ensure_online(self, what: str) -> bool:
        """True when ``what`` may use the network; asks to turn Work offline off first.

        ``what`` names the action in English, one of ``OFFLINE_ACTIONS`` (e.g. "Downloading
        this link"): the question is that action's own message (:func:`offline_question`),
        the log line keeps the English. Saying no leaves the switch on and the action is not
        started.
        """
        if not offline.is_offline():
            return True
        from tkinter import messagebox
        if not messagebox.askyesno(
            _("Offline mode is on"),
            offline_question(what),
            parent=self,
        ):
            self.log(offline.refused(what.lower()[:1] + what[1:]))
            return False
        self._set_work_offline(False)
        return True

    def _show_about(self) -> None:
        """A full feature inventory in a scrollable Toplevel.

        Many capabilities ship enabled-by-default but live behind
        the Advanced dialog or have no surface in the main UI; this
        dialog is the canonical "what does this app actually do"
        reference and is intentionally exhaustive.
        """
        dlg = tk.Toplevel(self)
        dlg.title(_("About Whisper Transcriber Suite"))
        dlg.transient(self)
        about_w, about_h = scaled_size(dlg, 680, 620)
        dlg.geometry("%dx%d" % (about_w, about_h))
        mac_native.centre_over(dlg, self, about_w, about_h)
        place_over(dlg, self, about_w, about_h)
        dlg.minsize(*scaled_size(dlg, 560, 480))

        header = ttk.Frame(dlg, padding=(16, 14, 16, 8))
        header.pack(fill="x")
        from core import __version__ as _app_ver
        ttk.Label(
            header,
            text=f"Whisper Transcriber Suite — v{_app_ver}",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=_(
                "A desktop app that turns audio and video into "
                "subtitles on your own computer. Powered by OpenAI "
                "Whisper via faster-whisper. No account and no API key "
                "needed."
            ),
            wraplength=px(640),
            justify="left",
            foreground=tokens.themed(tokens.TEXT_MUTED),
        ).pack(anchor="w", pady=(4, 0))
        # Passive update sign: the newest version seen, unless skipped.
        from core import updates as _updates
        newer = _updates.passive_sign_version(self.app_config, _app_ver)
        if newer:
            ttk.Label(
                header,
                text=_("Version {version} is available. Help → Check for updates… shows it.",
                   version=newer),
            ).pack(anchor="w", pady=(4, 0))
        # One quiet line: the repo page (never /stargazers, it has no Star button).
        star_line = ttk.Label(
            header, text=translate(_STAR_ABOUT_LINE), foreground=tokens.themed(tokens.LINK),
            cursor="hand2",
        )
        star_line.pack(anchor="w", pady=(4, 0))
        star_line.bind("<Button-1>", lambda _e: self._star_open_page())

        body_frame = ttk.Frame(dlg, padding=(16, 4, 16, 8))
        body_frame.pack(fill="both", expand=True)
        text = tk.Text(
            body_frame, wrap="word", borderwidth=0, highlightthickness=0,
            font=("TkDefaultFont", 9), padx=4, pady=4,
        )
        scroll = ttk.Scrollbar(body_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        text.tag_configure(
            "section", font=("TkDefaultFont", 10, "bold"),
            spacing1=8, spacing3=2,
        )
        text.tag_configure(
            "subsection", font=("TkDefaultFont", 9, "bold"),
            lmargin1=14, lmargin2=14, spacing1=4,
        )
        text.tag_configure(
            "bullet", lmargin1=28, lmargin2=42, spacing1=1, spacing3=1,
        )

        sections = build_about_sections()

        for section_title, subsections in sections:
            text.insert("end", section_title + "\n", "section")
            for sub_title, bullets in subsections:
                text.insert("end", sub_title + "\n", "subsection")
                for line in bullets:
                    text.insert("end", "• " + line + "\n", "bullet")

        # Helpful links — each rendered as a clickable, underlined row that
        # opens in the default browser. A per-link Text tag carries the URL
        # so one bound handler can serve them all.
        import webbrowser

        text.tag_configure(
            "link", foreground=tokens.themed(tokens.LINK), underline=True,
            lmargin1=28, lmargin2=42, spacing1=1, spacing3=1,
        )
        text.insert("end", _("Helpful links") + "\n", "section")
        for idx, (label, url) in enumerate(build_about_links()):
            tag = f"link-{idx}"
            text.tag_configure(tag)

            def _open(_e: object, _u: str = url) -> None:
                webbrowser.open(_u)

            text.tag_bind(tag, "<Button-1>", _open)
            text.tag_bind(
                tag, "<Enter>",
                lambda _e: text.configure(cursor="hand2"),
            )
            text.tag_bind(
                tag, "<Leave>",
                lambda _e: text.configure(cursor=""),
            )
            text.insert("end", "• " + label + "\n", ("link", tag))

        text.configure(state="disabled")

        # The credit gets its own row: next to the buttons it was cut off on
        # narrow windows (seen on macOS 10.15).
        credit_row = ttk.Frame(dlg, padding=(16, 4, 16, 0))
        credit_row.pack(fill="x")
        footer = ttk.Frame(dlg, padding=(16, 6, 16, 14))
        footer.pack(fill="x")
        ttk.Button(footer, text=_("OK"), command=dlg.destroy).pack(side="right")
        ttk.Button(footer, text=_("Report a problem…"),
                   command=lambda: self._open_problem_report(dlg)).pack(side="right", padx=(0, 8))
        # The project's home is this repository; translation-robot co-wrote it.
        credit = ttk.Label(
            credit_row,
            text=_("{site}  ·  co-author: {author}",
                   site="github.com/Milomilo777/whisper-transcriber-suite",
                   author="translation-robot"),
            foreground=tokens.themed(tokens.LINK), cursor="hand2",
        )
        credit.pack(side="left")

        def _open_repo(_e: object) -> None:
            import webbrowser
            from core.updates import REPO_URL
            webbrowser.open(REPO_URL)

        credit.bind("<Button-1>", _open_repo)

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        try:
            dlg.grab_set()
        except tk.TclError:
            pass

    def _open_problem_report(self, parent: tk.Misc) -> None:
        """About → Report a problem: a short message without a GitHub account."""
        from app.dialogs.problem_report import open_problem_report

        open_problem_report(parent, self.app_config, new_issue_url())

    def show_statistics(self) -> None:
        _show_stats(self)

    def convert_transcript(self) -> None:
        """File → Convert transcript: parse a transcript file and re-emit it
        in another text format, written beside the input.

        Keeps the UI minimal: an open dialog for the source, a small themed
        format chooser, then a synchronous write (parsing a subtitle file is
        instant — no worker thread needed). All errors surface in a messagebox;
        nothing here can raise out of the Tk event loop.
        """
        from core import convert as _convert

        in_path = filedialog.askopenfilename(
            parent=self,
            title=_("Convert transcript — pick the source file"),
            filetypes=[
                (_("Transcripts"), "*.json *.srt *.vtt *.tsv *.otr *.eaf *.inqscr *.txt"),
                ("SubRip", "*.srt"),
                ("WebVTT", "*.vtt"),
                ("TSV", "*.tsv"),
                ("Whisper JSON", "*.json"),
                ("oTranscribe", "*.otr"),
                ("ELAN", "*.eaf"),
                ("InqScribe", "*.inqscr *.txt"),
                (_("All files"), "*.*"),
            ],
        )
        if not in_path:
            return

        fmt = self._ask_convert_format(in_path)
        if not fmt:
            return

        try:
            out_path = _convert.convert_file(in_path, fmt)
        except _convert.ConvertError as e:
            messagebox.showerror(_("Convert transcript"), str(e), parent=self)
            return
        except OSError as e:
            messagebox.showerror(
                _("Convert transcript"),
                _("Could not write the output file: {error}", error=e),
                parent=self,
            )
            return

        self.log(f"Converted {os.path.basename(in_path)} -> {out_path}")
        if messagebox.askyesno(
            _("Convert transcript"),
            _("Wrote:\n{path}\n\nReveal it in Finder?", path=out_path) if shortcuts.is_mac()
            else _("Wrote:\n{path}\n\nOpen its folder?", path=out_path),
            parent=self,
        ):
            try:
                _open_folder_helper(os.path.dirname(out_path) or ".", select=out_path)
            except Exception as e:  # noqa: BLE001
                self.log(f"Could not open output folder: {e}")

    # Shown first in the Convert-transcript format picker, ahead of the
    # rest of core.convert.CONVERT_TARGETS (alphabetical) — these four are
    # what almost every user actually wants; burying them alphabetically
    # among internal-registry names like "elan" / "smtv_docx" made the
    # common case require scrolling/hunting (UX pass, 2026-07-04).
    _COMMON_CONVERT_FORMATS = ("srt", "vtt", "txt", "json")

    def _ask_convert_format(self, in_path: str) -> str | None:
        """Small themed modal: pick the target format. Returns it or None.

        Defaults to ``srt`` unless the source already is ``.srt`` (then
        ``json``), so the common one-click case never re-emits the same format.

        The combobox shows "name (.ext)" rather than the bare registry key
        (e.g. "elan (.eaf)", "smtv_docx (.docx)") since the on-disk extension
        often differs from the internal name and users otherwise have no way
        to tell what file they're about to get.
        """
        from core import convert as _convert

        src_ext = os.path.splitext(in_path)[1].lower().lstrip(".")
        all_targets = list(_convert.CONVERT_TARGETS)
        ordered = [f for f in self._COMMON_CONVERT_FORMATS if f in all_targets]
        ordered += sorted(f for f in all_targets if f not in ordered)
        labels = {f: f"{f} (.{_convert.output_extension_for(f)})" for f in ordered}
        label_to_fmt = {v: k for k, v in labels.items()}
        choices = [labels[f] for f in ordered]

        default = "json" if src_ext == "srt" else "srt"
        if default not in ordered:
            default = ordered[0]

        dlg = tk.Toplevel(self)
        dlg.title(_("Convert transcript"))
        dlg.transient(self)
        dlg.resizable(False, False)
        result: dict[str, str | None] = {"fmt": None}

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, text=_("Source: {name}", name=os.path.basename(in_path)),
            foreground=tokens.themed(tokens.TEXT_MUTED),
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text=_("Convert to format:")).pack(anchor="w")
        fmt_var = tk.StringVar(value=labels[default])
        ttk.Combobox(
            body, textvariable=fmt_var, state="readonly",
            values=choices, width=22,
        ).pack(anchor="w", pady=(4, 12))

        def _ok() -> None:
            result["fmt"] = label_to_fmt.get(fmt_var.get(), fmt_var.get())
            dlg.destroy()

        def _cancel() -> None:
            result["fmt"] = None
            dlg.destroy()

        btns = ttk.Frame(body)
        btns.pack(fill="x")
        ttk.Button(btns, text=_("Convert"), command=_ok).pack(side="right")
        ttk.Button(btns, text=_("Cancel"), command=_cancel).pack(
            side="right", padx=(0, 8)
        )
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        dlg.bind("<Return>", lambda _e: _ok())
        dlg.bind("<Escape>", lambda _e: _cancel())
        place_over(dlg, self)
        dlg.grab_set()
        self.wait_window(dlg)
        return result["fmt"]

    def open_log_folder(self) -> None:
        path = open_log_folder()
        if path:
            logger.info("Opened log folder: %s", path)
        else:
            logger.warning("Could not open the log folder")

    def _restyle(self, name: str) -> None:
        """Draw the app, its open dialogs and (Windows) their title bars in theme ``name``."""
        mac_appearance.apply_all(self, name)
        resolved = _resolve_theme(name)
        sv_ttk.set_theme(resolved)
        theme_colours.fix_accent_button(self)
        script_fonts.apply_theme_fonts(self)
        theme_colours.apply(self, resolved)
        win_chrome.apply_all(self, resolved)
        if hasattr(self, "live_model_menu"):
            live_tab_theme(self)
        if hasattr(self, "txt") and self.txt is not None:
            apply_console_theme(self.txt, resolved)

    def _sync_system_theme_watch(self, name: str) -> None:
        """Watch the OS light/dark choice only while the theme mode is "system"."""
        watch = getattr(self, "_system_theme_watch", None)
        if watch is None:
            return
        if name == "system":
            watch.start()
        else:
            watch.stop()

    def _on_system_theme_change(self) -> None:
        """The OS switched light/dark: follow it when the mode is "system" (nothing is saved)."""
        if getattr(self, "_closing", False):
            return
        name = self.theme_var.get()
        if name != "system" or _resolve_theme(name) == tokens.current_theme():
            return
        self._restyle(name)

    def apply_theme(self) -> None:
        name = self.theme_var.get()
        self._restyle(name)
        self._sync_system_theme_watch(name)
        self.app_config["theme"] = name
        # Guard the save like every other pref handler (Audit B1 / FB-01): a
        # disk/permissions failure inside this Tk callback must not raise out
        # of the event loop — log it and tell the user, don't crash silently.
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save theme preference")
            self.log(f"Could not save theme setting: {e}")

    def _install_quit_handler(self) -> None:
        """macOS: send Cmd+Q, the app-menu Quit and the Dock Quit through the
        same exit path as File -> Exit.

        Tk's Aqua default for ``::tk::mac::Quit`` calls ``exit`` at once, so a
        running transcription was dropped with no question (Windows asks via
        ``on_exit``). Other windowing systems have no such command; Ctrl+Q and
        the window's close button are bound separately.
        """
        try:
            aqua = str(self.tk.call("tk", "windowingsystem")) == "aqua"
        except tk.TclError:
            logger.debug("Could not query the windowing system", exc_info=True)
            return
        if aqua:
            self.createcommand("::tk::mac::Quit", self._force_exit)

    def _force_exit(self) -> None:
        """Bypass the minimise-to-tray redirect and exit immediately.

        Called by File → Exit, Ctrl+Q, and the tray menu's Exit item.
        The window's X button (WM_DELETE_WINDOW) continues to honour
        the minimise-to-tray preference.
        """
        self._exit_from_tray = True
        self.on_exit()

    def on_exit(self) -> None:
        # A second Cmd+Q / Ctrl+Q / close press while a question is open must
        # neither stack another dialog nor, first of all, minimise to the tray:
        # hiding the window would take the open question with it.
        if getattr(self, "_exit_prompt_open", False):
            return
        if getattr(self, "_closing", False):
            return

        # Optional minimise-to-tray: when the user has enabled tray
        # support in the Advanced dialog and the tray icon is running,
        # the window's close (X) button hides the window instead of
        # tearing down. File → Exit / Ctrl+Q route through
        # _force_exit() which sets _exit_from_tray=True so they
        # always exit regardless of the preference.
        if (
            not self._exit_from_tray
            and bool(self.app_config.get("minimise_to_tray", False))
            and self.tray is not None
            and self.tray.is_supported()
        ):
            try:
                self.withdraw()
                self.log("Window minimised to tray. Right-click the tray icon to exit.")
            except Exception:  # noqa: BLE001
                pass
            return

        active = [t for t in self.queue if t.status not in ("finished", "cancelled", "error")]
        active_downloads = [
            t for t in self.download_queue if t.status not in ("finished", "cancelled", "error")
        ]
        if active or active_downloads or App.active_server_jobs(self):
            self._exit_prompt_open = True
            # Quit on macOS, Exit elsewhere (shortcuts.quit_label), as whole sentences.
            if shortcuts.is_mac():
                title = _("Quit with queued tasks")
                question = _("There are queued or running tasks. Quit anyway?")
            else:
                title = _("Exit with queued tasks")
                question = _("There are queued or running tasks. Exit anyway?")
            try:
                confirmed = messagebox.askyesno(
                    title,
                    question,
                    parent=self,
                    default="no",
                )
            finally:
                self._exit_prompt_open = False
            if not confirmed:
                # Declining must NOT freeze the app. _closing is the sole
                # gate that lets loop()/_drain_main_calls/_drain_watched_paths
                # re-arm their after() callbacks; setting it before this
                # return left it stuck True (it is only reset in __init__),
                # permanently killing the queue pump and the drains.
                #
                # Also reset the one-shot exit override: _force_exit /
                # tray Exit set _exit_from_tray=True to bypass the
                # minimise-to-tray redirect above. If we don't clear it on
                # the decline path, the flag stays True for the rest of the
                # session, so the window's X button no longer honours the
                # minimise-to-tray preference (it falls straight through to
                # teardown). The latch is otherwise only reset in __init__.
                self._exit_from_tray = False
                return

        # Unsaved work is asked about after "exit anyway?" and before anything
        # irreversible, in this order: transcript viewers with unsaved edits
        # (Save / Discard / Cancel each; a Save must succeed), then the live
        # transcript. Cancel at any of them keeps the app open untouched. The
        # live question comes last because answering "No" there also marks its
        # text as deliberately dropped (no autosave at teardown).
        self._exit_prompt_open = True
        try:
            try:
                keep_open = not confirm_unsaved_viewers_before_exit()
            except Exception:  # noqa: BLE001
                # Edits are at stake: an unexpected failure keeps the app open.
                logger.exception("Transcript viewer exit check failed")
                keep_open = True
            if not keep_open:
                # The live transcript exists only in the Live tab's widget: offer
                # to save it (Cancel, or cancelling the save dialog, keeps the app
                # open; anything that arrives after this is autosaved at teardown).
                try:
                    keep_open = not live_save_before_exit(self)
                except Exception:  # noqa: BLE001
                    logger.exception("Live transcript exit check failed")
                    keep_open = False
        finally:
            self._exit_prompt_open = False
        if keep_open:
            self._exit_from_tray = False
            return

        # The process ends right after the teardown below and kills worker threads, so a
        # transcript viewer's export rebuild (a Word file can take tens of seconds) is
        # waited for first, within a limit, with the window still showing why.
        decided = list(_dirty_viewers_now())  # kept dirty on purpose (Discard), not asked again
        _finish_viewer_exports(self)
        # Nothing could be typed into a viewer meanwhile (the wait window holds the grab),
        # but whatever became dirty anyway is asked about now, never dropped by the exit.
        self._exit_prompt_open = True
        try:
            try:
                if not confirm_unsaved_viewers_before_exit(decided):  # asks only if one is dirty
                    self._exit_from_tray = False
                    return
            except Exception:  # noqa: BLE001 - edits are at stake: stay open
                logger.exception("Transcript viewer exit check failed")
                self._exit_from_tray = False
                return
        finally:
            self._exit_prompt_open = False

        # Confirmation passed (or there was nothing to confirm): flip the
        # closing flag so watcher events / stability-checks in flight
        # short-circuit before touching destroyed widgets.
        self._closing = True
        # No restyle of windows that are about to be destroyed (getattr: the exit tests use stand-ins).
        theme_watch = getattr(self, "_system_theme_watch", None)
        if theme_watch is not None:
            theme_watch.stop()
        # Persist window size + position so the next launch reopens at
        # the same shape. Runs *before* terminating subprocesses so it
        # never sees a broken state.
        self._save_window_geometry()
        # Hide the window before the teardown below: stopping a busy worker
        # can take several seconds, and a visible window that no longer
        # repaints looks like a hang.
        try:
            self.withdraw()
        except tk.TclError:
            logger.debug("Could not hide the window before exit", exc_info=True)
        # The window is hidden now: whatever fails below, destroy() must
        # still run, or the process lives on with no window to close.
        try:
            if self._folder_watcher is not None:
                try:
                    self._folder_watcher.stop()
                except Exception:  # noqa: BLE001
                    pass
            if self.tray is not None:
                try:
                    self.tray.stop()
                except Exception:  # noqa: BLE001
                    pass
            try:
                for task in self.download_queue:
                    # Snapshot once (see cancel_download): a worker thread may null
                    # task.process between the test and the poll(), which would raise
                    # AttributeError mid-teardown.
                    proc = task.process
                    if proc is not None and proc.poll() is None:
                        # Tree-kill so yt-dlp's ffmpeg merge child dies too (a bare
                        # terminate() orphans it, holding the .part/output handle).
                        try:
                            kill_process_tree(proc, force=False)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop downloads on exit")
            # A running subtitle burn (a chained download's, or the manual
            # "Burn subtitles" one) runs on a daemon thread that dies with the
            # process: stop its ffmpeg and remove the hidden .burn-* partial,
            # the work folder and the empty placeholder it leaves in the
            # user's folder (only files that burn created).
            try:
                from core import burn_subs
                burn_subs.abandon_active_burns()
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop the running subtitle burns on exit")
            # Stop the Live tab BEFORE the transcription workers: it owns its
            # own worker subprocess plus a capture thread holding the audio
            # device, and both would outlive the window otherwise.
            try:
                stop_live_session(self)
            except Exception:  # noqa: BLE001
                pass
            # Same reasoning as the Live tab: its own worker subprocess (a
            # separate, independent one -- see core.voice_clone_worker) plus
            # any in-progress mic recording must not outlive the window.
            try:
                stop_voice_clone_worker(self)
            except Exception:  # noqa: BLE001
                pass
            # A pip install (any window's) is stopped like a Cancel, then waited
            # for: its merge phase cannot be interrupted, and the process ends
            # right after this teardown.
            try:
                _stop_installs_on_exit()
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop installs on exit")
            # Stop the in-process web / LAN server so its socket + worker
            # thread don't linger after the window closes.
            try:
                self._shutdown_server_on_exit()
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop LAN server on exit")
            # The user confirmed: record these jobs as closed on purpose, so the
            # next launch does not call them a crash. Their rows are still
            # 'running'; the resume offer and the checkpoint stay as they are.
            # The prompts above pump the event loop, so a job (a watched folder's
            # file) may have started since `active` was taken: it is stopped by
            # this exit too.
            try:
                started_meanwhile = [
                    t for t in self.queue
                    if t.status not in ("finished", "cancelled", "error")
                    and not any(t is known for known in active)
                ]
                _record_exit_interruptions(
                    getattr(self, "history", None), active + started_meanwhile)
            except Exception:  # noqa: BLE001
                logger.exception("Could not record exit interruptions")
            try:
                # Cancel first: the worker then saves its resume checkpoint.
                self.transcription_service.stop_all(cancel_running=True)
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop the transcription workers on exit")
            # A job that finished inside the stop window has its outputs on disk:
            # record it as finished so the next launch does not offer it again.
            try:
                self.transcription_service.settle_done_on_exit()
            except Exception:  # noqa: BLE001
                logger.exception("Could not record jobs that finished during exit")
            # Close the history DB connection (and checkpoint its WAL) on a
            # clean exit — the GUI never did, leaking the connection + the
            # -wal/-shm sidecars until interpreter teardown. Mirrors gui.py.
            history = getattr(self, "history", None)
            if history is not None:
                try:
                    history.close()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            self.destroy()

    def destroy(self) -> None:  # type: ignore[override]
        win_taskbar.shutdown()
        # Stop the tray icon thread on every teardown path, not only
        # on_exit (idempotent there). A live pystray loop keeps its own
        # message thread plus a reference to this App alive after destroy.
        # wait=False: on Linux without a system tray icon.stop() can block,
        # and destroy() must never stall (on_exit already waited if needed).
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.stop(wait=False)
            except Exception:  # noqa: BLE001
                logger.exception("Could not stop the tray icon")
        # Cancel every pending after() callback before tearing down the
        # Tcl interpreter. Otherwise the service poll loops fire one last
        # time after destroy() and spam the console with
        #   invalid command name "<id>poll"
        # because their bound-method Tcl command no longer exists. The
        # cancel must not delete other widgets' commands (see the helper).
        cancel_pending_after_callbacks(self)
        try:
            state = getattr(self, "smtv_state", None)
            if state is not None and hasattr(state, "destroy"):
                state.destroy()
            super().destroy()
        except Exception:  # noqa: BLE001 - any failure here must still end mainloop
            # A half-finished teardown leaves the root alive, so mainloop()
            # would keep the process running with nothing left to close.
            logger.exception("Window teardown failed; ending the event loop anyway")
            self.quit()

    # Tabs --------------------------------------------------------------------
    def open_ui_language_chooser(self) -> None:
        """The language chooser: the globe button above the tabs and View > Interface language."""
        ui_language.open_chooser(self)

    def _build_tabs(self) -> None:
        # The language button sits in the top-right corner above the tabs, in every language.
        ui_language.build_button(self, self)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.t1 = ttk.Frame(self.nb)
        self.t2 = ttk.Frame(self.nb)
        self.t3 = ttk.Frame(self.nb)
        self.t5 = ttk.Frame(self.nb)
        self.t6 = ttk.Frame(self.nb)
        self.t7 = ttk.Frame(self.nb)
        self.t8 = ttk.Frame(self.nb)
        # Tab order (2026-09-23, owner review): the core transcribe flow
        # first, then the other ways audio comes in (downloads, live
        # capture), then the standalone tools, then settings-like tabs.
        # The Supreme Master TV introduction is ALWAYS the last tab --
        # keep it last when adding a new one.
        self.nb.add(self.t1, text=pgettext("tab", "Transcribe"))
        self.nb.add(self.t2, text=_("Transcription Queue"))
        self.nb.add(self.t3, text=_("Download Videos"))
        self.nb.add(self.t6, text=pgettext("tab", "Live"))
        # Clone Your Voice / Text to Voice is opt-in at install time
        # (no_voice_clone.flag via voice_clone_tab_enabled); it is simply
        # not added when disabled. The voice-clone worker is spawned
        # lazily on first Generate, so a skipped tab leaves nothing to
        # tear down.
        self._voice_clone_tab_visible = voice_clone_tab_enabled()
        if self._voice_clone_tab_visible:
            self.nb.add(self.t7, text=_("Clone Your Voice / Text to Voice"))
        self.nb.add(self.t5, text=_("Web / LAN access"))
        # The video-site tab stays English-only (never wrapped, never in a catalog).
        self.nb.add(self.t8, text="Supreme Master TV")
        # The taller tabs scroll when the window is shorter than their
        # content (e.g. a 768 px laptop screen) instead of cutting it off;
        # on a big window they fill it exactly as before.
        from app.widgets.tabs import fit_or_scroll

        # Scrolls when the window is shorter than the tab (a long Last result card), so
        # the drop zone keeps its height and the log below the tabs keeps its lines.
        build_transcribe_tab(self, fit_or_scroll(self.t1))
        build_queue_tab(self, self.t2)
        build_live_tab(self, fit_or_scroll(self.t6))
        build_download_tab(self, fit_or_scroll(self.t3))
        build_smtv_tab(self, self.t8)
        build_server_tab(self, fit_or_scroll(self.t5))
        if self._voice_clone_tab_visible:
            build_voice_clone_tab(self, fit_or_scroll(self.t7))
        # Right-to-left interface (app.rtl_layout): mirror each finished tab once, right-align
        # the tab strip and reverse its order. The video-site tab keeps its English layout.
        # Widgets packed later use rtl_layout.pack_kw at their call site. (Plain function
        # calls: a test runs _build_tabs on a bare Tk host.)
        rtl_layout.keep_ltr(self.t8)
        for tab in (self.t1, self.t2, self.t3, self.t5, self.t6, self.t7, self.t8):
            rtl_layout.mirror_tree(tab)
        rtl_layout.mirror_notebook(self.nb)

    def _save_auto_transcribe_pref(self) -> None:
        self.app_config["auto_transcribe_after_download"] = bool(self.auto_transcribe_var.get())
        try:
            save_config(self.app_config)
        except Exception as e:
            # Audit B1 / FB-01: config-save failures must NOT be
            # silent. The user has just toggled a preference; if
            # the disk write fails (permission denied, antivirus
            # lock), they need to know — otherwise their choice
            # silently reverts on the next launch.
            logger.exception("Failed to save auto-transcribe preference")
            self.log(f"Could not save preference: {e}")
        self.update_caption_shortcut_state()  # its offer shows only while the box is ticked

    def _on_download_cookies_selected(self) -> None:
        """Download tab "Log-in cookies" pick: save it and re-check the URL.

        Same config key as Advanced › Downloads. A pasted link that failed
        the lookup for want of a log-in is looked up again right away.
        """
        from app.domain.cookies import cookie_browser_value

        var = getattr(self, "download_cookies_var", None)
        if var is None:
            return
        value = cookie_browser_value(var.get())
        if value == str(self.app_config.get("cookies_from_browser") or ""):
            return
        self.app_config["cookies_from_browser"] = value
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save cookies-from-browser preference")
            self.log(f"Could not save preference: {e}")
        self.log(
            f"Downloads now use log-in cookies from {value}." if value
            else "Downloads no longer use browser log-in cookies."
        )
        url_var = getattr(self, "download_url_var", None)
        if url_var is not None and url_var.get().strip():
            self.format_service.schedule_lookup()

    def sync_cookies_browser_from_config(self) -> None:
        """Refresh the Download tab's cookies picker after Advanced saved it."""
        from app.domain.cookies import cookie_browser_choices, cookie_browser_label

        var = getattr(self, "download_cookies_var", None)
        combo = getattr(self, "download_cookies_combo", None)
        if var is None or combo is None:
            return
        current = str(self.app_config.get("cookies_from_browser") or "")
        try:
            combo.configure(values=cookie_browser_choices(current))
            var.set(cookie_browser_label(current))
        except tk.TclError:
            pass

    def _sync_diarization_speakers_option(self) -> None:
        """Show the Speakers count only while speaker detection is on (greyed out it
        still looked like a setting that applies: screenshot review, 2026-10-21)."""
        combo = _inst_attr(self, "diarization_speakers_combo")
        if combo is None:
            return

        try:
            diar_var = _inst_attr(self, "diarization_var")
            if diar_var is None:
                return
            diar_enabled = bool(diar_var.get())
            if not diar_enabled:
                combo.state(["disabled"])
            else:
                combo.state(["!disabled"])
            label = _inst_attr(self, "diarization_speakers_label")
            if label is None:
                return
            if not diar_enabled:
                label.pack_forget()
                combo.pack_forget()
            elif not combo.winfo_manager():
                # back in front of "Time range", where build_transcribe_tab put it
                anchor = _inst_attr(self, "transcribe_time_range_label")
                where = {"before": anchor} if anchor is not None else {}
                label.pack(**rtl_layout.pack_kw(label, side="left", **where))
                combo.pack(**rtl_layout.pack_kw(combo, side="left", padx=(6, 2), **where))
        except tk.TclError:
            logger.debug("Could not sync the speakers option", exc_info=True)

    def _save_transcribe_prefs(self) -> None:
        # vad_enabled is intentionally NOT written here, same reasoning as
        # hotwords below: vad_enabled_var has no matching widget on this
        # tab (build_transcribe_tab's "vars without a matching widget are
        # simply not packed" note), so it is frozen at whatever
        # config.json held when the tab was built.
        # AdvancedDialog._save_and_close's new "Enable VAD" checkbox
        # (2026-08-15) is the real editor of cfg["vad_enabled"] now —
        # writing the stale var here would silently revert that checkbox
        # the moment the user touched the language dropdown or a checkbox
        # on this tab, the exact same clobbering bug hotwords had.
        self.app_config["word_timestamps"] = bool(self.word_timestamps_var.get())
        translate_var = _inst_attr(self, "translate_var")
        if translate_var is not None:
            self.app_config["translate_to_english"] = bool(translate_var.get())
            self._refresh_model_status()  # the CPU speed hint never suggests turbo for translation
        if _inst_attr(self, "diarization_var") is not None:
            self.app_config["diarization_enabled"] = bool(self.diarization_var.get())

        spk_var = _inst_attr(self, "diarization_speakers_var")
        if spk_var is not None:
            spk_val = spk_var.get().strip()
            if spk_val.lower() == "auto":
                self.app_config["diarization_num_speakers"] = -1
            else:
                # The underlying setting is validated when workers load config.
                # We also reuse the validation bounds configured centrally.
                try:
                    num_speakers = int(spk_val)
                    lower_bound, upper_bound = _PROJECT_KEY_RANGES.get(
                        "diarization_num_speakers", (-1, 100)
                    )
                    if not (lower_bound <= num_speakers <= upper_bound):
                        raise ValueError("Out of bounds")
                    self.app_config["diarization_num_speakers"] = num_speakers
                except ValueError:
                    logger.warning(
                        "Invalid diarization_num_speakers '%s'; falling back to Auto (-1)",
                        spk_val
                    )
                    self.app_config["diarization_num_speakers"] = -1

        # transcribe_language is intentionally NOT persisted: the picker
        # resets to "Auto" every launch (user request). The choice still
        # lives in transcribe_lang_var for the rest of the session.
        self._refresh_language_model_hint()
        if getattr(self, "device_var", None) is not None:
            self.app_config["device"] = self.device_var.get()
        if getattr(self, "compute_type_var", None) is not None:
            self.app_config["compute_type"] = self.compute_type_var.get()
        # hotwords is intentionally NOT written here. hotwords_var has no
        # matching widget on this tab (see build_transcribe_tab's "vars
        # without a matching widget are simply not packed" note) — it is
        # frozen at whatever config.json held when the tab was built, and
        # AdvancedDialog._save_and_close is the only real editor of
        # cfg["hotwords"]. Writing hotwords_var's stale value here used to
        # silently clobber a hotwords edit made in Advanced the moment the
        # user touched the language dropdown or a checkbox on this tab
        # afterward — a real, confirmed data-loss bug (2026-08-15).
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save transcribe preferences")
            self.log(f"Could not save preferences: {e}")

    def _on_transcribe_language_changed(self) -> None:
        """The Language picker: save as any option does, then resolve the Accuracy level
        again for the new language (its Balanced or Best may be another model)."""
        self._save_transcribe_prefs()
        self._refresh_accuracy_row(language_changed=True)

    def open_advanced_dialog(self) -> None:
        dlg = AdvancedDialog(self)
        # Block (nested event loop) until the modal dialog closes, then re-sync
        # the Transcribe-tab engine + model pickers in case the backend,
        # model, or model folder was changed in Advanced settings.
        try:
            self.wait_window(dlg)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_engine_selector()
        self._refresh_model_selector()
        self._sync_telemetry_menu()
        self._sync_offline_menu()
        self._apply_update_setting()

    def _confirm_backend_switch(
        self,
        parent: "tk.Misc | None" = None,
        *,
        kind: str = BACKEND_SWITCH_ENGINE,
    ) -> bool:
        """True if it's safe to stop_all() workers for an engine switch.

        stop_worker() is a hard terminate (shutdown request, then
        terminate/kill), not the cooperative per-task Cancel -- so
        switching engines while a transcription is actually running can
        lose more progress than a normal Cancel would, with no warning.
        Asks first when any worker has an assigned task; returns True with
        no prompt when nothing is actually running.

        ``kind`` names what the caller is about to do (``BACKEND_SWITCH_*``: "engine",
        "model", "hardware"); each has its own whole title and question.
        """
        if kind not in _BACKEND_SWITCH_KINDS:
            raise ValueError(f"unknown backend switch kind: {kind!r}")
        svc = getattr(self, "transcription_service", None)
        if svc is None:
            return True
        busy = [w for w in svc.active_workers() if w.get("task") is not None]
        if not busy:
            return True
        from tkinter import messagebox
        title, question = backend_switch_texts(kind, len(busy))
        return messagebox.askyesno(
            title,
            question,
            parent=parent or self,
            default="no",
        )

    def _on_engine_selected(self) -> None:
        """Persist the Transcribe-tab engine pick and restart the worker so the
        new engine takes effect on the next transcription.

        The live worker snapshots ``transcribe_backend`` at spawn and the
        dispatch prefers that stale value, so a fresh worker is required for a
        switch to take effect — the same mechanism a model change uses.
        """
        from core.backends import availability as _eng

        evar = _inst_attr(self, "transcribe_engine_var")
        if evar is None:
            return
        value = _eng.engine_value_for_label(evar.get()) or _eng.FALLBACK_ENGINE
        old = str(self.app_config.get("transcribe_backend") or "")
        if value != old:
            if not self._confirm_backend_switch():
                evar.set(_eng.VALUE_TO_LABEL.get(old, evar.get()))
                self._refresh_engine_picker_labels()
                return
            self.app_config["transcribe_backend"] = value
            try:
                save_config(self.app_config)
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to save engine selection")
                self.log(f"Could not save engine selection: {e}")
            try:
                self.transcription_service.stop_all()
            except Exception as e:  # noqa: BLE001
                self.log(f"Could not restart the transcription worker: {e}")
            self.log(
                f"Transcription engine set to {value}. "
                "It will be used on the next transcription."
            )
        self._refresh_engine_status()
        self._sync_model_picker_for_engine()

    def _refresh_engine_status(self) -> None:
        """Update the Transcribe-tab engine readiness line for the current pick.

        Paints an immediate cheap/neutral line synchronously (so startup and
        selection never block), then kicks off the REAL readiness probe
        (``deep=True`` — genuinely checks installs, model presence, keys) on
        a short-lived background thread via :meth:`probe_engine_status`. This
        keeps the UI responsive even when a heavy native-lib import is slow.
        """
        var = getattr(self, "engine_status_var", None)
        if var is None:
            return
        try:
            from core.backends import availability as _eng

            evar = _inst_attr(self, "transcribe_engine_var")
            label = evar.get() if evar is not None else ""
            value = _eng.engine_value_for_label(label) or self.app_config.get(
                "transcribe_backend"
            )
            value = _eng.normalise_engine(value)

            # 1) Immediate, cheap, non-blocking paint — "Checking…" so the
            #    user sees something right away while the real probe runs.
            var.set(_("Checking…"))
            lbl = getattr(self, "engine_status_label", None)
            if lbl is not None:
                try:
                    lbl.configure(foreground=tokens.themed(tokens.TEXT_MUTED))
                except Exception:  # noqa: BLE001
                    pass

            # 2) Real probe on a daemon thread — never blocks the UI thread.
            seq = int(getattr(self, "_engine_status_seq", 0)) + 1
            self._engine_status_seq = seq

            def _on_result(st: Any, _seq: int = seq) -> None:
                self._engine_status_answered = _seq
                self._apply_engine_status(value, st)

            self.probe_engine_status(value, _on_result)
            # 3) Safety net: the deep probe imports native libraries on a
            #    thread and has no timeout of its own. If it never answers
            #    (seen on macOS 10.15), "Checking…" stayed up forever; after
            #    a while show the cheap status instead. A late real result
            #    still replaces it.
            self.after(
                self._ENGINE_PROBE_FALLBACK_MS,
                lambda: self._engine_status_fallback(seq, value),
            )
        except Exception:  # noqa: BLE001
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass

    # How long the Transcribe-tab status line waits for the deep engine probe
    # before falling back to the cheap status (see _refresh_engine_status).
    _ENGINE_PROBE_FALLBACK_MS = 15000
    # Generation of the last status refresh / of the last probe that answered.
    _engine_status_seq: int = 0
    _engine_status_answered: int = 0

    def _engine_status_fallback(self, seq: int, value: str) -> None:
        """Replace a still-pending "Checking…" with the cheap engine status."""
        if seq != getattr(self, "_engine_status_seq", 0):
            return  # a newer refresh owns the line
        if getattr(self, "_engine_status_answered", 0) >= seq:
            return  # the real probe already answered
        var = getattr(self, "engine_status_var", None)
        if var is None:
            return
        try:
            if var.get() != _("Checking…"):
                return
            from core.backends import availability as _eng

            st = _eng.engine_status(value, self.app_config, deep=False)
            logger.warning(
                "Engine readiness probe for %s did not answer in %.0f s; "
                "showing the quick status instead.",
                value, self._ENGINE_PROBE_FALLBACK_MS / 1000,
            )
            var.set(_eng.format_engine_status(st))
            lbl = getattr(self, "engine_status_label", None)
            if lbl is not None:
                lbl.configure(foreground=tokens.themed(tokens.SUCCESS_TEXT) if st.ready else tokens.themed(tokens.WARNING_TEXT))
        except Exception:  # noqa: BLE001 -- a status line must never raise
            logger.exception("Engine status fallback failed")

    def probe_engine_status(
        self,
        value: str,
        on_result: Callable[[Any], None],
        *,
        cfg: Mapping[str, Any] | None = None,
    ) -> None:
        """Deep-probe one engine on a daemon thread; ``on_result`` runs on Tk.

        Shared by the Transcribe-tab status line and the Advanced dialog's
        warning row so the GC-off thread discipline below exists in exactly
        one place. ``on_result`` is always dispatched through
        :meth:`post_to_main` — never called on the probe thread.

        ``cfg`` overrides the snapshot the probe reads (the Advanced dialog
        passes its own live, not-yet-saved field values here so a credential
        typed but not Saved is reflected immediately instead of showing this
        app's last-saved config). Defaults to ``self.app_config`` — the
        Transcribe tab has no separate live-edit layer, so it never needs to
        pass this.
        """
        from core.backends import availability as _eng

        cfg_snapshot = dict(cfg) if cfg is not None else dict(self.app_config)

        def _probe() -> None:
            # GC disabled for this ENTIRE probe thread, not just the
            # engine_status() call — a real crash was confirmed
            # (2026-08-15, Python 3.14) three times, each narrower fix
            # disproven by the next instrumented full-suite rerun:
            # (1) GC firing mid-import inside engine_status() faulted a
            # C-extension class-registration step; (2) narrowing the
            # gc.disable() window to just that call "fixed" it once,
            # then a later rerun faulted one line later in a plain
            # EngineStatus(...) dataclass construction; (3) widening the
            # window to the whole engine_status() try/finally "fixed" it
            # again, then ANOTHER rerun faulted right after gc.enable()
            # returned, inside the post_to_main() call below. gc.disable
            # ()/gc.enable() are PROCESS-GLOBAL, not thread-local — every
            # other thread's allocations pile up ungarbage-collected
            # while this one holds GC off, so re-enabling it here was
            # itself triggering an immediate, larger-than-usual
            # collection at the exact moment this thread kept running.
            # Holding GC off for the probe's ENTIRE body (including
            # post_to_main) removes that re-enable-triggers-a-collision
            # window too. See core/backends/google_cloud_stt.py's
            # matching comment and ADR 0008 in docs/DECISIONS.md for the
            # full three-round story — treat this as a mitigation that
            # has repeatedly needed widening, not a proven-complete fix.
            was_gc_enabled = gc.isenabled()
            gc.disable()
            try:
                try:
                    st = _eng.engine_status(value, cfg_snapshot, deep=True)
                except Exception as e:  # noqa: BLE001
                    st = _eng.EngineStatus(value, False, str(e) or "probe failed")
                # post_to_main, NOT self.after: this runs on a daemon
                # thread, and off-thread after() raises on Python 3.14.
                self.post_to_main(lambda: on_result(st))
            finally:
                if was_gc_enabled:
                    gc.enable()

        threading.Thread(target=_probe, daemon=True).start()

    def _engine_picker_options(self) -> "list[Any]":
        """Readiness-aware engine picker options, cached deep results applied.

        Cheap probes only (never imports a heavy backend on the UI thread);
        any engine that has been deep-probed before contributes its cached
        result so its "unavailable" marker can't flip back.
        """
        from core.backends import availability as _eng

        return _eng.engine_options(
            self.app_config,
            deep=False,
            statuses=_inst_attr(self, "_engine_deep_statuses"),
        )

    def _refresh_engine_picker_labels(self) -> None:
        """Re-render the engine combobox labels with availability markers.

        Keeps the current pick selected by VALUE (never by label text) while
        the labels round-trip through the display/parse helpers, so a label
        gaining or losing its marker can't change which engine is selected.
        Disables the whole control only when no engine has a usable path —
        the documented fallback for a picker whose entries can't be greyed
        individually.
        """
        combo = _inst_attr(self, "transcribe_engine_combo")
        if combo is None:
            return
        try:
            from core.backends import availability as _eng

            options = self._engine_picker_options()
            from app.widgets.tabs import combo_width

            labels = [o.display_label for o in options]
            # The refreshed labels can carry the longer "⚠ unavailable" mark: size the box again.
            combo.configure(values=labels, width=combo_width(labels))
            combo.configure(
                state="readonly" if any(o.ready for o in options) else "disabled"
            )
            evar = _inst_attr(self, "transcribe_engine_var")
            if evar is None:
                return
            current_value = _eng.engine_value_for_label(evar.get())
            if current_value is None:
                current_value = _eng.normalise_engine(
                    self.app_config.get("transcribe_backend")
                )
            for opt in options:
                if opt.value == current_value:
                    if evar.get() != opt.display_label:
                        evar.set(opt.display_label)
                    break
        except Exception:  # noqa: BLE001
            logger.debug("Could not refresh engine picker labels", exc_info=True)

    def _apply_engine_status(self, probed_value: str, st: Any) -> None:
        """Apply a background-probed ``EngineStatus`` to the status label.

        Runs on the Tk main thread (posted via :meth:`post_to_main`). Drops
        the result if the user switched engines mid-probe (stale-race guard)
        or if the widgets were destroyed in the meantime (shutdown guard).
        Also caches the verdict and refreshes the picker markers, so an
        engine that turns out to be blocked is marked before the user can
        commit to it.
        """
        try:
            from core.backends import availability as _eng

            var = getattr(self, "engine_status_var", None)
            lbl = getattr(self, "engine_status_label", None)
            if var is None:
                return
            if lbl is not None:
                try:
                    if not lbl.winfo_exists():
                        return
                except Exception:  # noqa: BLE001
                    return

            evar = _inst_attr(self, "transcribe_engine_var")
            current_label = evar.get() if evar is not None else ""
            current_value = _eng.normalise_engine(
                _eng.engine_value_for_label(current_label)
                or self.app_config.get("transcribe_backend")
            )
            if current_value != probed_value:
                return  # stale — the user picked a different engine meanwhile

            cache = _inst_attr(self, "_engine_deep_statuses")
            if cache is not None:
                cache[probed_value] = st
            self._refresh_engine_picker_labels()

            if st.ready:
                color = tokens.themed(tokens.SUCCESS_TEXT)
            else:
                color = tokens.themed(tokens.WARNING_TEXT)
            var.set(_eng.format_engine_status(st))
            if lbl is not None:
                try:
                    lbl.configure(foreground=color)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _refresh_engine_selector(self) -> None:
        """Re-sync the Transcribe-tab engine picker to the saved backend (e.g.
        after the Advanced dialog changed it), then refresh the status line."""
        evar = _inst_attr(self, "transcribe_engine_var")
        if evar is None:
            return
        # The Advanced dialog may have changed credentials or installed a
        # backend, so cached deep verdicts are no longer trustworthy.
        cache = _inst_attr(self, "_engine_deep_statuses")
        if cache is not None:
            cache.clear()
        try:
            from core.backends import availability as _eng

            value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
            options = self._engine_picker_options()
            label = next(
                (o.display_label for o in options if o.value == value), None
            )
            if label and label != evar.get():
                evar.set(label)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_engine_status()
        self._sync_model_picker_for_engine()

    def _on_model_selected(self) -> None:
        """Persist the Transcribe-tab Whisper-model pick and restart the
        worker so the new model takes effect on the next transcription.

        Mirrors _on_engine_selected: the live worker snapshots the model at
        spawn, so rewriting cfg alone would leave the OLD model loaded until
        the process happened to restart. Same rewrite AdvancedDialog's model
        picker does in _save_and_close (cfg["whisper_model"] + cfg["model"]
        + cfg["model_path"]), just triggered from this tab's combobox
        instead of a Save button.
        """
        from core.model_manager import (
            DEFAULT_MODEL_SLUG,
            catalog_resolve_entry,
        )

        mvar = getattr(self, "transcribe_model_var", None)
        label_to_slug = getattr(self, "_transcribe_model_label_to_slug", None)
        if mvar is None or not label_to_slug:
            return
        new_slug = label_to_slug.get(mvar.get() or "", DEFAULT_MODEL_SLUG)
        old_slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
        if new_slug == old_slug:
            return
        entry = catalog_resolve_entry(self.app_config, new_slug)
        if entry is None:
            self.log(f"Unknown model slug {new_slug!r}; keeping current model.")
            return
        # stop_all() below is a hard stop: never kill a running transcription
        # without asking (the engine picker already asked; this one did not).
        if not self._confirm_backend_switch(kind=BACKEND_SWITCH_MODEL):
            slug_to_label = {s: lbl for lbl, s in label_to_slug.items()}
            mvar.set(slug_to_label.get(old_slug, mvar.get()))
            return
        self.app_config["whisper_model"] = new_slug
        self.app_config["model"] = entry
        self.app_config["model_path"] = ""
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save model selection")
            self.log(f"Could not save model selection: {e}")
        try:
            self.transcription_service.stop_all()
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not restart the transcription worker: {e}")
        self.log(
            f"Whisper model changed to {new_slug}. It will be used on the "
            "next transcription."
        )
        self._refresh_model_status()
        self._sync_translate_option()
        self._refresh_language_model_hint()
        self._refresh_accuracy_row()

    def _sync_model_picker_for_engine(self) -> None:
        """Grey out the Whisper-model picker when the picked engine can't use it.

        The model catalog only drives the Faster-Whisper engine; whisper.cpp,
        NVIDIA Parakeet and the two cloud engines each use their own model.
        Leaving this picker live under those engines invited the user to
        "change" a model the next transcription would silently ignore — the
        unusable-combination class this feature greys out.
        """
        combo = _inst_attr(self, "transcribe_model_combo")
        if combo is None:
            return
        try:
            active = self._engine_uses_whisper_model()
            combo.configure(state="readonly" if active else "disabled")
            advisor = _inst_attr(self, "transcribe_model_advisor_btn")
            if advisor is not None:
                advisor.state(["!disabled"] if active else ["disabled"])
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync the model picker state", exc_info=True)
        self._refresh_model_status()
        self._sync_translate_option()
        self._refresh_language_model_hint()
        self._refresh_accuracy_row()

    def _refresh_accuracy_row(self, *, language_changed: bool = False) -> None:
        """Redraw the Transcribe tab's Accuracy row (core/accuracy.py).

        The combo shows the level whose model is the saved one, or "Custom (current
        setting)" when none has it; the note line names the model and its download, or
        the engine while another engine is picked (its model is not Whisper's). After a
        language change the level a person picked in this session is resolved again for
        the new language, which may switch the model (the note says what downloads); a
        level that was only shown, a Custom model and a running job are never touched.
        """
        combo = _inst_attr(self, "transcribe_accuracy_combo")
        var = _inst_attr(self, "transcribe_accuracy_var")
        note_var = _inst_attr(self, "transcribe_accuracy_note_var")
        if combo is None or var is None or note_var is None:
            return
        from core import accuracy as _acc
        from core.backends import availability as _eng
        from core.model_manager import DEFAULT_MODEL_SLUG, approx_download_size_text, model_downloaded

        language = self._selected_transcribe_language()
        ram_gb = float(self.__dict__.get("_accuracy_ram_gb") or 0.0)
        slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG).strip()
        uses_model = self._engine_uses_whisper_model()
        choice = self.__dict__.get("_accuracy_choice")
        picked = self.__dict__.get("_accuracy_picked_level")
        if uses_model and language_changed and picked is not None and not self._transcribing_now():
            wanted = _acc.model_for_level(language, picked, ram_gb)
            if wanted != slug and self._switch_transcribe_model(wanted):
                return  # _on_model_selected redrew the row for the new model
        pick = _inst_attr(self, "transcribe_accuracy_pick")
        link = _inst_attr(self, "transcribe_accuracy_check_link")
        try:
            if not uses_model:
                self._accuracy_choice = None
                value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
                note_var.set(_("Engine: {name} (change in Advanced settings)",
                               name=_eng.VALUE_TO_LABEL.get(value, value)))
                if pick is not None:
                    pick.pack_forget()
                if link is not None:
                    link.pack_forget()
                return
            picks = _acc.models_by_level(language, ram_gb)
            level = choice if choice in picks and picks[choice] == slug else _acc.level_for_model(
                slug, language, ram_gb)
            self._accuracy_choice = level
            if level is None and not language_changed:
                self._accuracy_picked_level = None  # a model picked in Advanced settings
            labels = dict(self.__dict__.get("_transcribe_accuracy_label_to_level") or {})
            level_to_label = {lvl: lbl for lbl, lvl in labels.items()}
            values = list(labels)
            if level is None:
                values.append(_("Custom (current setting)"))
            if list(combo.cget("values") or ()) != values:
                combo.configure(values=values)
            shown = level_to_label.get(level or "", values[-1])
            if var.get() != shown:
                var.set(shown)
            model = short_model_name(self.app_config, slug)
            size = approx_download_size_text(self.app_config, slug)
            if model_downloaded(self.app_config, slug):
                note = _("{model} model: already downloaded", model=model)
            elif size:
                note = _("{model} model: {size} download on first use", model=model, size=size)
            else:
                note = _("{model} model: downloads on first use", model=model)
            note_var.set(note)
            if pick is not None and not pick.winfo_manager():
                pick.pack(**rtl_layout.pack_kw(pick, side="left"))
            if link is not None and not link.winfo_manager():
                link.pack(**rtl_layout.pack_kw(link, side="left", padx=(12, 0)))
        except Exception:  # noqa: BLE001
            logger.debug("Could not redraw the Accuracy row", exc_info=True)

    def _on_accuracy_selected(self) -> None:
        """Pick the level's model for the current language exactly as the Model picker
        does (config rewrite + worker restart, see _on_model_selected); a declined
        "stop the running job?" leaves the model and the row as they were."""
        var = _inst_attr(self, "transcribe_accuracy_var")
        labels = self.__dict__.get("_transcribe_accuracy_label_to_level") or {}
        if var is None:
            return
        level = labels.get(var.get())
        if level is not None:
            from core import accuracy as _acc
            from core.model_manager import DEFAULT_MODEL_SLUG

            ram_gb = float(self.__dict__.get("_accuracy_ram_gb") or 0.0)
            wanted = _acc.model_for_level(self._selected_transcribe_language(), level, ram_gb)
            # Remembered before the switch, so the redraw keeps this level when two
            # levels share a model (a small computer where every level is Small).
            self._accuracy_choice = level
            self._accuracy_picked_level = level
            if wanted != str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG).strip():
                self._switch_transcribe_model(wanted)
        self._refresh_accuracy_row()

    def _transcribing_now(self) -> bool:
        """True while any worker has a task: a language change then never asks to stop it."""
        svc = getattr(self, "transcription_service", None)
        try:
            return svc is not None and any(w.get("task") is not None for w in svc.active_workers())
        except Exception:  # noqa: BLE001
            return False

    def open_model_advisor(self) -> None:
        """Transcribe tab "Check this computer": suggest models for this hardware."""
        try:
            from app.dialogs.model_advisor import open_model_advisor

            open_model_advisor(self, self)
        except Exception as e:  # noqa: BLE001
            logger.exception("Model advisor failed to open")
            self.log(f"Could not open the model advisor: {e}")

    def _engine_uses_whisper_model(self) -> bool:
        """True while the picked engine actually uses the Whisper-model
        catalog (Faster-Whisper only)."""
        from core.backends import availability as _eng

        evar = _inst_attr(self, "transcribe_engine_var")
        label = evar.get() if evar is not None else ""
        value = _eng.engine_value_for_label(label)
        if value is None:
            value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
        return value == "faster_whisper"

    def _model_picker_disabled_reason(self) -> str:
        """Hover text while the model picker is greyed out; "" when active.

        Wired through ``bind_tooltip`` as a callable so it always describes
        the engine that is picked *now*.
        """
        combo = _inst_attr(self, "transcribe_model_combo")
        if combo is None:
            return ""
        try:
            if str(combo.cget("state")) != "disabled":
                return ""
        except Exception:  # noqa: BLE001
            return ""
        from core.backends import availability as _eng

        evar = _inst_attr(self, "transcribe_engine_var")
        label = evar.get() if evar is not None else ""
        value = _eng.engine_value_for_label(label)
        if value is None:
            value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
        engine_label = _eng.VALUE_TO_LABEL.get(value, value)
        return _(
            "The {engine} engine uses its own model. This picker only "
            "applies to the Faster-Whisper engine, so a change here would "
            "have no effect.", engine=engine_label,
        )

    def _refresh_model_status(self) -> None:
        """Update the Transcribe-tab model-downloaded status line.

        A plain on-disk existence check (core.model_manager.model_downloaded)
        -- cheap and import-free, unlike _refresh_engine_status's deep probe,
        so this runs synchronously on the main thread with no background
        thread needed. While the picker is disabled (non-Faster-Whisper
        engine), says so instead of pretending the model still matters.
        """
        var = _inst_attr(self, "model_status_var")
        if var is None:
            return
        try:
            if not self._engine_uses_whisper_model():
                var.set(_("Only used by Faster-Whisper"))
                return

            from core.model_manager import DEFAULT_MODEL_SLUG, model_downloaded

            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
            if model_downloaded(self.app_config, slug):
                text = _("✓ Downloaded")
            else:
                text = _("Downloads automatically on first use")
            # The picker's own labels already say "[needs download]", so on a slow
            # CPU the narrow status line carries the speed hint instead.
            var.set(self._cpu_speed_hint(slug) or text)
        except Exception:  # noqa: BLE001
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass

    def _cpu_speed_hint(self, slug: str) -> str:
        """"Faster on this CPU: …" once a worker has reported the CPU and ``slug`` has a
        lighter twin (core.hardware.faster_cpu_model); "" otherwise. The log gets the
        full sentence once per model and session."""
        if not self.__dict__.get("_runs_on_cpu"):
            return ""
        from core import hardware as _hw
        from core.model_manager import MODEL_REGISTRY

        pick = _hw.faster_cpu_model(
            slug, translate=bool(self.app_config.get("translate_to_english")),
        )
        if pick is None:
            return ""
        faster, ratio = pick
        name = str(MODEL_REGISTRY[faster]["label"]).split(" — ")[0]
        logged: set[str] = self.__dict__.setdefault("_cpu_speed_hint_logged", set())
        if slug not in logged:
            logged.add(slug)
            self.log(_(
                "Transcription runs on the CPU here, where the {model} model takes about "
                "twice as long as the audio. {faster} is about {ratio}x faster with nearly "
                "the same accuracy: pick it in Advanced settings, or use Check this computer "
                "on the Transcribe tab.",
                model=slug, faster=name, ratio=f"{ratio:.1f}",
            ))
        return _("Faster on this CPU: {model} (about {ratio}x)", model=name, ratio=f"{ratio:.1f}")

    def _translate_unsupported_reason(self) -> str:
        """One-line reason the English-translation option cannot run with the
        engine picked on the Transcribe tab and the saved model; "" when it can."""
        from core.backends import availability as _eng
        from core.translate_task import unsupported_reason

        evar = _inst_attr(self, "transcribe_engine_var")
        label = evar.get() if evar is not None else ""
        value = _eng.engine_value_for_label(label)
        if value is None:
            value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
        return unsupported_reason(dict(self.app_config, transcribe_backend=value))

    def _sync_translate_option(self) -> None:
        """Grey out the "English translation" checkbox where Whisper cannot
        translate (other engines, turbo and English-only models); the reason
        is its hover text."""
        check = _inst_attr(self, "translate_check")
        if check is None:
            return
        try:
            check.state(["disabled"] if self._translate_unsupported_reason() else ["!disabled"])
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync the translate option", exc_info=True)

    def _language_label(self, code: str) -> str:
        """Shown (translated) name of a Whisper language code, e.g. "fa" -> "Persian"."""
        from app.domain.languages import SUBTITLE_LANGUAGES, subtitle_language_label
        from core.language_models import normalize
        name = next((n for n, c in SUBTITLE_LANGUAGES if normalize(c) == code), code)
        return subtitle_language_label(name)

    def _refresh_language_model_hint(self) -> None:
        """Show or hide the Transcribe tab's "a model trained for <language>" line (ADR 0015).

        Offers a one-language model when the picked language has one that is not in use,
        and the way back when such a model is in use for another language or Auto.
        """
        row = _inst_attr(self, "language_model_row")
        var = _inst_attr(self, "language_model_hint_var")
        button = _inst_attr(self, "language_model_button")
        if row is None or var is None or button is None:
            return
        from core import language_models as lm
        state = lm.suggestion(self.app_config, self._selected_transcribe_language())
        if state is None:
            row.pack_forget()
            return
        kind, model = state
        language = self._language_label(model.language)
        if kind == "offer":
            var.set(_("A model trained for {language} is available: {name} (about {size} GB).",
                      language=language, name=model.name, size=f"{model.size_gb:.1f}"))
            button.configure(text=_("Use it"))
        else:
            var.set(_("{name} writes {language} only, whatever language is picked.",
                      name=model.name, language=language))
            button.configure(text=_("Switch back"))
        if not row.winfo_manager():
            row.pack(fill="x", pady=(6, 0), after=_inst_attr(self, "language_model_anchor"))

    def _on_language_model_button(self) -> None:
        """"Use it" / "Switch back" on the language-model line: confirm, rewrite the engine and
        model keys, restart the worker, and re-sync the pickers."""
        from core import language_models as lm
        from core.model_manager import MODEL_REGISTRY
        # Recompute: the config may have changed since the line was drawn (Advanced settings).
        state = lm.suggestion(self.app_config, self._selected_transcribe_language())
        if not state:
            self._refresh_language_model_hint()
            return
        kind, model = state
        language = self._language_label(model.language)
        if kind == "offer":
            repo = (MODEL_REGISTRY.get(model.model, {}).get("hf_repo") if model.engine == lm.ENGINE_WHISPER
                    else model.model)
            text = _(
                "Use {name} for {language}?\n\n"
                "Reported: {claim}. These are published figures on the publisher's own test "
                "sets; this app has not measured them.\n\n"
                "Download: about {size} GB from huggingface.co/{repo}, on the next "
                "transcription. Licence: {licence}.\nFigures from: {source}",
                name=model.name, language=language, claim=model.claim,
                size=f"{model.size_gb:.1f}", repo=repo, licence=model.licence, source=model.source,
            )
            text += "\n\n" + _(
                "It writes {language} only, whatever language is picked: pick Switch back for "
                "other languages.", language=language)
            if model.engine == lm.ENGINE_TRANSFORMERS:
                text += " " + _(
                    "It runs on the local transformers engine, which installs once the first "
                    "time (about 1 GB more), gives no word-level timestamps and ignores the "
                    "Whisper options (hot words, prompt).")
            if not messagebox.askyesno(_("Model for {language}", language=language), text, parent=self):
                return
        if not self._confirm_backend_switch(kind=BACKEND_SWITCH_MODEL):
            return
        if kind == "offer":
            lm.apply_language_model(self.app_config, model)
            self.log(f"Using {model.name} ({model.model}) for {model.language}; source: {model.source}")
        else:
            lm.restore_previous(self.app_config)
            self.log(f"Switched back from {model.name} to the previous engine and model.")
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save the language model choice")
            self.log(f"Could not save the model choice: {e}")
        try:
            self.transcription_service.stop_all()
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not restart the transcription worker: {e}")
        self._refresh_engine_selector()
        self._refresh_model_selector()
        self._refresh_language_model_hint()

    def _refresh_model_selector(self) -> None:
        """Re-sync the Transcribe-tab model picker to the saved slug (e.g.
        after the Advanced dialog changed the model or the model folder),
        then refresh its status line."""
        mvar = getattr(self, "transcribe_model_var", None)
        if mvar is None:
            return
        try:
            from core.model_manager import DEFAULT_MODEL_SLUG, catalog_models

            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
            labeled = catalog_models(self.app_config)
            label_to_slug = {lbl: s for s, lbl in labeled}
            slug_to_label = {s: lbl for s, lbl in labeled}
            self._transcribe_model_label_to_slug = label_to_slug
            label = slug_to_label.get(slug)
            if label and label != mvar.get():
                mvar.set(label)
        except Exception:  # noqa: BLE001
            pass
        self._sync_model_picker_for_engine()

    # Generic helpers ---------------------------------------------------------
    def yt_dlp_path(self) -> str:
        # The newer of the bundled bin/yt-dlp[.exe] and the user-writable copy
        # that updates itself (core.yt_dlp_update); the bare name when neither
        # exists, so Linux/Mac fall back to a yt-dlp on PATH.
        from core.yt_dlp_update import resolve_yt_dlp_path
        return resolve_yt_dlp_path()

    def bin_path(self) -> str:
        # Point yt-dlp's --ffmpeg-location at our bin/ ONLY when a bundled
        # ffmpeg actually lives there. On Linux/Mac with ffmpeg on PATH
        # (no bundled copy) return "" so the flag is omitted and yt-dlp
        # discovers ffmpeg itself instead of failing on an empty bin dir.
        return _resource_bin_dir() if os.path.dirname(_bundled_binary("ffmpeg")) else ""

    def browse(self) -> None:
        """Pick one or more files.

        The dialog supports multi-select; if the user picks several
        files we enqueue each. Single-file selection still just
        populates the file-picker entry without auto-enqueueing —
        keeps the muscle-memory of "Browse → Transcribe" intact.
        """
        from core.media_types import MEDIA_EXTENSIONS

        chosen = filedialog.askopenfilenames(
            parent=self,
            filetypes=[(_("Audio and video"), " ".join("*" + ext for ext in MEDIA_EXTENSIONS)),
                       (_("All files"), "*.*")],
        )
        if not chosen:
            return
        if len(chosen) == 1:
            _show_file_in_box(self, chosen[0])
            return
        # Several files started every one at once without a word (deep review, 2026-10-21):
        # one question first. A drop is a deliberate act and is not asked.
        if not messagebox.askyesno(
            _("Add files"),
            ngettext("Add {n} file to the queue? Each one becomes its own transcription job.",
                     "Add {n} files to the queue? Each one becomes its own transcription job.",
                     len(chosen)),
            parent=self,
        ):
            return
        count = self._bulk_enqueue(list(chosen))
        if count:
            self.log(f"Enqueued {count} files via Browse...")

    def browse_download_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.download_folder_var.set(folder)
            self.app_config["download_folder"] = folder
            # Guard the save like every other pref handler (Audit B1 / FB-01):
            # a disk/permissions failure must not raise out of the Tk callback.
            try:
                save_config(self.app_config)
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to save download folder preference")
                self.log(f"Could not save download folder setting: {e}")

    def update_download_mode(self) -> None:
        audio_only = self.download_mode_var.get() == "Audio"
        if audio_only:
            self.video_format_combo.configure(state="disabled")
            outputs = ("mp3", "m4a", "aac", "opus", "flac", "wav")
            if self.output_format_var.get() not in outputs:
                self.output_format_var.set("mp3")
        else:
            self.video_format_combo.configure(state="readonly")
            outputs = ("mp4", "mkv", "webm")
            if self.output_format_var.get() not in outputs:
                self.output_format_var.set("mp4")
        self.output_format_combo["values"] = outputs

    def update_subtitle_state(self) -> None:
        if self.download_subtitles_var.get():
            self.subtitle_lang_combo.configure(state="readonly")
        else:
            self.subtitle_lang_combo.configure(state="disabled")
            self.subtitle_status_var.set("")

    def update_js_runtime_prompt(self, url: str | None = None) -> None:
        """Show "Install YouTube helper" while a YouTube link is loaded and
        yt-dlp has no JavaScript runtime (Deno) to solve YouTube's challenges."""
        button = getattr(self, "js_runtime_button", None)
        if button is None:
            return
        from core.js_runtime import find_deno, is_youtube_url

        if url is None:
            var = getattr(self, "download_url_var", None)
            url = var.get() if var is not None else ""
        needed = bool(
            is_youtube_url(url or "") and find_deno() is None
            and not getattr(self, "_js_runtime_installing", False)
        )
        try:
            packed = bool(button.winfo_manager())
            if needed and not packed:
                # Before the status text, so a long error can't push it out.
                label = getattr(self, "format_status_label", None)
                if label is not None:
                    button.pack(**rtl_layout.pack_kw(button, side="left", padx=(0, 10), before=label))
                else:
                    button.pack(**rtl_layout.pack_kw(button, side="left", padx=(0, 10)))
            elif not needed and packed:
                button.pack_forget()
        except tk.TclError:
            pass

    def install_js_runtime(self) -> None:
        """Download + verify Deno into the user cache, off the Tk thread."""
        if getattr(self, "_js_runtime_installing", False):
            return
        if not self.ensure_online("Installing the YouTube helper"):
            return
        from core.js_runtime import DENO_DOWNLOAD_MB, install_deno

        self._js_runtime_installing = True
        button = getattr(self, "js_runtime_button", None)
        if button is not None:
            try:
                button.state(["disabled"])
            except tk.TclError:
                pass
        self.format_status_var.set(
            _("Installing the YouTube helper (Deno, about {size} MB)…", size=DENO_DOWNLOAD_MB)
        )

        def _progress(pct: int) -> None:
            if pct % 5 == 0:
                self.post_to_main(lambda: self.format_status_var.set(
                    _("Installing the YouTube helper… {percent}%", percent=pct)
                ))

        def _work() -> None:
            try:
                path = install_deno(progress_cb=_progress)
                result, error = path, ""
            except Exception as e:  # noqa: BLE001
                logger.exception("Deno install failed")
                result, error = "", str(e)
            self.post_to_main(lambda: self._js_runtime_install_done(result, error))

        from core._threads import safe_thread
        safe_thread(_work, name="deno-install")

    def _js_runtime_install_done(self, path: str, error: str) -> None:
        self._js_runtime_installing = False
        button = getattr(self, "js_runtime_button", None)
        if button is not None:
            try:
                button.state(["!disabled"])
            except tk.TclError:
                pass
        if error:
            self.format_status_var.set(_("Could not install the YouTube helper: {error}", error=error))
            self.log(f"YouTube helper (Deno) install failed: {error}")
            return
        self.log(f"YouTube helper installed: {path}")
        self.update_js_runtime_prompt()
        url_var = getattr(self, "download_url_var", None)
        if url_var is not None and url_var.get().strip():
            self.format_service.schedule_lookup()  # look the link up again with Deno
        else:
            self.format_status_var.set(_("YouTube helper installed."))

    def update_caption_bar(self) -> None:
        """Show which subtitles the looked-up video has under the link field.

        Hidden when there are none, and never for an SMTV episode (it writes
        its own transcript with every download).
        """
        var = getattr(self, "caption_bar_var", None)
        label = getattr(self, "caption_bar_label", None)
        if var is None or label is None:
            return
        from app.domain.languages import SUBTITLE_LANGUAGES, caption_availability_text

        text = ""
        if getattr(self, "_smtv_episode", None) is None:
            chosen = self.subtitle_lang_var.get() if hasattr(self, "subtitle_lang_var") else ""
            chosen_codes = next((c for n, c in SUBTITLE_LANGUAGES if n == chosen), "")
            prefer = [c.strip() for c in chosen_codes.split(",")]
            prefer.append(getattr(self, "current_video_language", "") or "")
            text = caption_availability_text(
                getattr(self, "current_video_caption_langs", None) or {}, prefer
            )
        var.set(text)
        if text:
            label.pack(**rtl_layout.pack_kw(label, anchor="w", pady=(2, 0)))
        else:
            label.pack_forget()

    def update_caption_shortcut_state(self) -> None:
        """Show/hide the "Use the subtitles" shortcut.

        Called after every format lookup (see app.services.format_service)
        and whenever the subtitle-language combo changes. Independent of
        the "Subtitles" checkbox above it -- this is a separate
        action, not a modifier of the main Download button. The shortcut
        is yt-dlp-specific (SMTV episodes download from the site's own
        server), so it never applies while an SMTV episode is loaded.
        """
        self.update_caption_bar()
        status_var = getattr(self, "caption_shortcut_status_var", None)
        button = getattr(self, "caption_shortcut_button", None)
        if status_var is None or button is None:
            return
        # "Use them instead of transcribing?" makes sense only when the download will be
        # transcribed (deep review, 2026-10-21); _save_auto_transcribe_pref calls this again.
        tick = getattr(self, "auto_transcribe_var", None)
        if getattr(self, "_smtv_episode", None) is not None or (tick is not None and not tick.get()):
            status_var.set("")
            button.pack_forget()
            return

        from app.domain.languages import (
            SUBTITLE_LANGUAGES, caption_language_name, resolve_caption_kind, subtitle_language_label,
        )

        sub_lang_name = self.subtitle_lang_var.get() if hasattr(self, "subtitle_lang_var") else ""
        lang_code_csv = next(
            (code for name, code in SUBTITLE_LANGUAGES if name == sub_lang_name), ""
        )
        caption_langs = getattr(self, "current_video_caption_langs", None) or {}
        kind = resolve_caption_kind(
            caption_langs, lang_code_csv, fallback_lang=self.current_video_language
        )
        if not kind:
            status_var.set("")
            button.pack_forget()
            return

        # sub_lang_name is the stored English name: shown translated. The detected
        # language is a caption code ("en"), shown by its name: the bar said "en" (screenshot
        # reviews, 2026-10-21); a code with no known name stays as it is.
        code = self.current_video_language
        label = subtitle_language_label(sub_lang_name) if (
            sub_lang_name and sub_lang_name != "Automatic") else (
            subtitle_language_label(caption_language_name(code)) if code else code
        )
        # Whole sentences: one with the language's name, one for "the detected language".
        if kind == "manual" and label:
            text = _("This video already has {language} subtitles made by the uploader. "
                     "Use them instead of transcribing?", language=label)
        elif kind == "manual":
            text = _("This video already has subtitles made by the uploader. "
                     "Use them instead of transcribing?")
        elif label:
            text = _("This video has automatic {language} subtitles. Use them instead of "
                     "transcribing? (They can be less accurate.)", language=label)
        else:
            text = _("This video has automatic subtitles. Use them instead of "
                     "transcribing? (They can be less accurate.)")
        status_var.set(text)
        button.pack(**rtl_layout.pack_kw(button, side="left", padx=(10, 0)))

    def model_status(self, msg: str) -> None:
        # Display only. Worker readiness is tracked authoritatively via the
        # worker's 'ready' event → TranscriptionService.update_model_state();
        # don't latch model_ready off a log-line substring — any line that
        # merely contained "Model loaded" (an echo, a future diagnostic)
        # could desync the app-global flag from real worker state (P2-30).
        # The log keeps the message as it is; the status bar gets a short plain line, and
        # engine diagnostics leave it unchanged.
        from app.domain.status_line import status_line

        line = status_line(msg)
        if line is not None:
            self.status_var.set(line)
        self.log(msg)

    # R3: device badge --------------------------------------------------------
    def register_device_badge_label(self, label: "ttk.Label", tier_label: str = "") -> None:
        """Register a badge Label so apply_device_badge can recolour it.

        Called by tabs.py for each placement (Transcribe header + Queue
        status line). Stores an optional tier label used in the tooltip.
        """
        self.device_badge_labels.append(label)
        if tier_label:
            self.device_badge_tip = tier_label
        self._bind_device_badge_tooltip(label)

    def apply_device_badge(self, text: str, kind: str, worker: dict[str, Any]) -> None:
        """Set the badge text + colour from the worker's effective device.

        ``kind`` is one of ``gpu`` (green), ``cpu`` (grey), ``cpu_downgraded``
        (amber). Colours come through ``tokens.themed`` so each keeps 4.5:1 on
        the current theme's panel. The tooltip is refreshed with the full detail.
        """
        self.device_badge_var.set(text)
        colour = {
            "gpu": tokens.themed(tokens.CHIP_GPU),             # green — running on the GPU
            "cpu": tokens.themed(tokens.TEXT_MUTED),           # grey — nothing to fix on a CPU-only PC
            "cpu_downgraded": tokens.themed(tokens.CHIP_CPU),  # amber — GPU asked, fell back to CPU
        }.get(kind, "")
        req = str(worker.get("requested_device") or "")
        ct = str(worker.get("compute_type") or "")
        dev = str(worker.get("device") or "")
        # The device and its compute type are data ("cuda (float16)"); each hover text is one
        # whole message.
        device = f"{dev or 'cpu'} ({ct})" if ct else (dev or "cpu")
        if kind == "cpu_downgraded" and req:
            tip = _(
                "Requested {requested} but it was unavailable. Transcribing on {device}. "
                "CPU is much slower than a GPU. If you have an NVIDIA card, "
                "open Advanced > Re-detect hardware: it says why the GPU is "
                "not used and can install the missing NVIDIA library.",
                requested=req, device=device,
            )
        elif kind in ("cpu", "cpu_downgraded"):
            tip = _(
                "Transcribing on {device}. CPU is much slower than a GPU. If you have an "
                "NVIDIA card, open Advanced > Re-detect hardware: it says why the GPU is "
                "not used and can install the missing NVIDIA library.",
                device=device,
            )
        else:
            tip = _("Transcribing on {device}", device=device)
        self.device_badge_tip = tip
        on_cpu = kind in ("cpu", "cpu_downgraded")
        if on_cpu != bool(self.__dict__.get("_runs_on_cpu")):
            self.__dict__["_runs_on_cpu"] = on_cpu
            refresh = getattr(self, "_refresh_model_status", None)
            if callable(refresh):  # stand-in objects (tests, early startup) may lack it
                refresh()
        for label in self.device_badge_labels:
            try:
                if colour:
                    label.configure(foreground=colour)
                label.configure(text=text)
            except Exception:  # noqa: BLE001
                pass

    def _bind_device_badge_tooltip(self, widget: "ttk.Label") -> None:
        """Lightweight hover tooltip showing the full device detail.

        Uses the shared tooltip helper with a getter (not a plain string)
        since ``device_badge_tip`` is rewritten on every model-state change
        after this is first bound.
        """
        from app.widgets.tooltip import bind_tooltip

        bind_tooltip(widget, lambda: self.device_badge_tip, wraplength=320)

    def warn_cpu_once(self, downgraded: bool) -> None:
        """One-time modal + log warning that transcription is on CPU (slower).

        Only invoked by TranscriptionService when the situation is actionable
        (a CUDA->CPU downgrade, or a GPU detected-but-unusable). Kept short.
        """
        if downgraded:
            msg = _(
                "Your GPU could not be used, so transcription is running on "
                "the CPU — this is much slower.\n\n"
                "This usually means an NVIDIA library (cuBLAS) is missing or "
                "the GPU needs a newer driver (not a corrupt model). Open "
                "Advanced > Re-detect hardware for the exact reason and a fix."
            )
        else:
            msg = _(
                "An NVIDIA GPU was detected but cannot be used yet, so "
                "transcription is running on the CPU — this is much slower.\n\n"
                "Open Advanced > Re-detect hardware: it shows the exact reason "
                "and can install the missing NVIDIA library."
            )
        self.log(msg.replace("\n\n", " "))
        try:
            messagebox.showwarning(_("Running on CPU (slower)"), msg, parent=self)
        except Exception:  # noqa: BLE001
            pass

    # Modal model setup -------------------------------------------------------
    def ensure_model_with_modal(self, mandatory: bool = False) -> bool:
        if self.model_ready:
            self.status_var.set(_("Model loaded"))
            return True
        return self._open_model_download_modal(mandatory=mandatory)

    def download_model_now(self) -> bool:
        """Force the model-download modal for the CONFIGURED slug.

        Unlike ``ensure_model_with_modal``, this does NOT short-circuit on the
        app-global ``model_ready`` flag. The Advanced "Download now" button
        targets one specific model's bytes; once ANY model was loaded,
        ``model_ready`` was True and the old gate made "Download now" a silent
        no-op. ``ensure_model`` is idempotent (a fast MD5 check when the bytes
        are already present), so opening the modal here is safe even if some
        model is loaded.
        """
        return self._open_model_download_modal(mandatory=False)

    def _open_model_download_modal(self, mandatory: bool = False) -> bool:
        if self.model_setup_running:
            return False
        self.model_setup_running = True
        dialog = ModelDownloadDialog(self)
        self.wait_window(dialog)
        self.model_setup_running = False
        if dialog.success:
            # v1.0.3 — lazy model load.
            # Used to call ``transcription_service.start_standby()``
            # here to spawn a worker the moment the model bytes
            # finished downloading. We no longer preload — the worker
            # spawns on the first transcribe via
            # ``ensure_worker_ready``, which puts up its own modal.
            # Just log that the bytes are ready.
            self.log("Model downloaded.")
            # The Transcribe tab's "Model not downloaded yet" / "Downloads
            # automatically on first use" lines were computed before the
            # download; recompute them now.
            self._refresh_model_status()
            self._refresh_engine_status()
            return True
        self.model_ready = False
        self.status_var.set(_("Model is required"))
        if mandatory:
            self.log("Model setup was cancelled or failed.")
        return False

    # On-demand optional dependencies (slim build) ---------------------------
    def _offer_optional_install(self, feature: str, friendly: str, size_hint: str) -> bool:
        """If a slim-build optional feature's package is missing, offer a
        one-time download. Returns True if usable (already present or just
        installed), False if declined/failed — the caller then proceeds
        without the feature (the worker skips it gracefully).
        """
        import threading

        import core.optional_deps as optional_deps
        if optional_deps.is_available(feature):
            return True
        if not optional_deps.can_install():
            self.log(f"{friendly}: not included in this app -- continuing without it. "
                     + optional_deps.FROZEN_INSTALL_MESSAGE)
            return False
        # ``friendly`` is an English msgid (N_ at the call); the log lines keep it English.
        name = translate(friendly)
        if not messagebox.askyesno(
            _("{feature} needs a download", feature=name),
            _("{feature} needs a one-time download of about {size} "
              "(PyTorch + support files).\n\nDownload and install it now?\n"
              "Choose No to continue this time without it.", feature=name, size=size_hint),
            parent=self,
        ):
            self.log(f"{friendly}: skipped the optional download — continuing without it.")
            return False
        win = tk.Toplevel(self)
        win.title(_("Installing {feature}", feature=name))
        win.transient(self)
        win.resizable(False, False)
        ttk.Label(
            win,
            text=_("Downloading and installing {feature} (~{size}).\n"
                   "This happens once and can take a few minutes…", feature=name, size=size_hint),
            justify="left",
        ).pack(padx=18, pady=(16, 8))
        bar = ttk.Progressbar(win, mode="indeterminate", length=px(340))
        bar.pack(padx=18, pady=(0, 12))
        bar.start(12)
        state = {"ok": False, "done": False}
        cancel_event = threading.Event()

        def _request_cancel() -> None:
            # Set the event so optional_deps.install terminates pip and
            # returns False promptly; the window closes via _poll once the
            # worker thread observes it. Without this, closing the modal
            # left pip running orphaned and the bar could spin forever on a
            # stalled download.
            cancel_event.set()
            try:
                cancel_btn.config(state="disabled", text=_("Cancelling…"))
            except tk.TclError:
                pass

        cancel_btn = ttk.Button(win, text=_("Cancel"), command=_request_cancel)
        cancel_btn.pack(pady=(0, 14))
        win.protocol("WM_DELETE_WINDOW", _request_cancel)
        place_over(win, self)

        def _work() -> None:
            # self.log writes the Tk text widget directly; this runs off
            # the main thread, so marshal every line through post_to_main.
            def _safe_log(line: str) -> None:
                self.post_to_main(lambda: self.log(line))
            try:
                state["ok"] = optional_deps.install(
                    feature, log_cb=_safe_log, cancel_event=cancel_event
                )
            except Exception as e:  # noqa: BLE001
                self.post_to_main(lambda e=e: self.log(f"{friendly} install failed: {e}"))
            finally:
                state["done"] = True

        threading.Thread(target=_work, name="optdeps-install", daemon=True).start()

        def _poll() -> None:
            if state["done"]:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                return
            self.after(200, _poll)

        self.after(200, _poll)
        self.wait_window(win)
        return self._finish_optional_install(bool(state["ok"]), friendly)

    def _finish_optional_install(self, ok: bool, friendly: str) -> bool:
        """What follows a finished install; quiet when the app is already closing.

        An exit stops the install (``optional_deps.request_stop_installs``) and destroys the
        window, so the install ends here with the Tk root gone: no log line, no worker
        restart then.
        """
        if getattr(self, "_closing", False):
            return ok
        if ok:
            try:
                self.log(f"{friendly} installed.")
            except tk.TclError:
                logger.debug("The app closed before the install result was logged", exc_info=True)
                return ok
            # A live worker activated its sys.path BEFORE this install, so
            # restart workers to pick up the new package on the next task.
            try:
                self.transcription_service.stop_all()
            except Exception:  # noqa: BLE001
                pass
            return True
        return False

    # Adding tasks ------------------------------------------------------------
    def add(self) -> None:
        text = _clean_pasted_path(self.fv.get())
        if not text:
            # Nothing to transcribe yet: open the file picker instead of a log line the user may
            # not see (click-through test, 2026-10-21).
            self.browse()
            return
        # YouTube / yt-dlp URL detection — if the user pastes a URL
        # into the Transcribe file field, route it through the
        # Download tab with auto-transcribe-after-download on. The
        # download flow is the established way to fetch network
        # media; we just connect the dots.
        if text.startswith(("http://", "https://")):
            try:
                self.download_url_var.set(text)
                if hasattr(self, "auto_transcribe_var"):
                    self.auto_transcribe_var.set(True)
                    # The download chain reads the saved setting, not the tick box: without
                    # this the file downloaded and was never transcribed (found in a
                    # click-through test, 2026-10-21).
                    self._save_auto_transcribe_pref()
                # The user clicked Transcribe: start the download by itself as soon as the
                # link's formats are listed (FormatService), instead of waiting for a
                # second click on Download.
                from core.integrations import smtv as smtv_mod
                self.pending_link_start = smtv_mod.clean_url(text)
                self.nb.select(self.t3)
                self.log(
                    f"Link: it downloads first, then transcribes; starting as soon as the "
                    f"link is read: {text[:60]}"
                )
            except Exception as e:  # noqa: BLE001
                self.log(f"URL handoff failed: {e}")
            return
        # Local-path sanity: a deleted / mistyped path would otherwise
        # enqueue a task that only fails deep in the worker with a cryptic
        # error. Catch it here where we can give a clear message.
        if not os.path.isfile(text):
            self.log(f"File not found — pick an existing file: {text}")
            # The red line beside the button already says "File not found"; the click opens the
            # file picker, as with an empty box, instead of doing nothing visible (review, 2026-10-21).
            self.browse()
            return
        # A README picked by mistake used to be queued anyway and fail as a bare "error"
        # row (click-through test, 2026-10-21): turn it away here, with the reason.
        from core.watcher import is_transcribable

        if not is_transcribable(text):
            name = os.path.basename(text)
            self.log(f"Not queued: {name} is not an audio or video file.")
            show_error(
                self, _("Cannot transcribe this file"),
                _("{name} is not an audio or video file. Choose an audio or video file, "
                  "or paste a video link.", name=name),
            )
            return
        if not self._confirm_english_only_model():
            return
        if not self._ensure_transcribe_ready():
            return
        # Per-task language override + optional clip range. The cleaned path,
        # never the raw field: quotes or a leading space would reach the worker.
        task = TranscriptionTask(text)
        self._apply_task_options(task)
        if self._same_job_active(task):
            # A second click (the button showed no change) queued the same job twice
            # (screenshot reviews, 2026-10-21): show the one that is there. Another part of
            # the same file (a different time range) is a new job and still goes in.
            self.nb.select(self.t2)
            self.log(f"Already in the queue: {os.path.basename(text)}")
            return
        self.queue.append(task)
        self.pb["value"] = 0
        self.nb.select(self.t2)
        self.log(f"Queued: {os.path.basename(text)}")
        self.refresh()

    def show_task_in_queue(self, task: "TranscriptionTask | None") -> None:
        """The Transcribe tab's "Show in Queue": open the Queue with ``task``'s row selected."""
        self.nb.select(self.t2)
        if task is None:
            return
        iids = _iids_for_tasks(self.row_map, [task])
        if iids:
            self.tree.selection_set(iids)
            self.tree.focus(iids[0])
            self.tree.see(iids[0])

    def _same_job_active(self, task: TranscriptionTask) -> bool:
        """True when a waiting, running or paused job already does ``task``: the same
        file and the same time range (None/None = the whole file)."""
        key = (os.path.normcase(os.path.abspath(task.file_path)),
               getattr(task, "clip_start", None), getattr(task, "clip_end", None))
        for existing in self.queue:
            if getattr(existing, "status", "") not in ("waiting", "running", "paused"):
                continue
            other = (os.path.normcase(os.path.abspath(existing.file_path)),
                     getattr(existing, "clip_start", None), getattr(existing, "clip_end", None))
            if other == key:
                return True
        return False

    def try_sample_clip(self) -> None:
        """"Try it now": transcribe the bundled sample clip with the chosen model.

        Goes through the same gates as Transcribe (model download prompt, worker load);
        the transcript opens in the viewer when the task finishes (``open_sample_result``).
        """
        from core import sample_clip

        try:
            path = sample_clip.prepare_working_copy()
        except OSError as e:
            self.log(f"Could not prepare the sample clip: {e}")
            show_error(
                self, _("Sample clip unavailable"),
                _("Could not copy the sample clip into your data folder."), detail=str(e),
            )
            return
        if path is None:
            self.log("The sample clip is missing from this install.")
            show_error(
                self, _("Sample clip missing"),
                _("The sample clip could not be found in this install.")
            )
            return
        if any(
            t.file_path == path and t.status in ("waiting", "running", "paused")
            for t in self.queue
        ):
            self.log("The sample clip is already in the queue.")
            self.nb.select(self.t2)
            return
        if not self._ensure_transcribe_ready():
            return
        task = TranscriptionTask(path)
        task.language = sample_clip.SAMPLE_CLIP_LANGUAGE
        task.open_when_done = True
        self.queue.append(task)
        self.pb["value"] = 0
        self.nb.select(self.t2)
        self.log("Queued the sample clip; its transcript opens when it is done.")
        self.refresh()

    def open_sample_result(self, task: TranscriptionTask) -> None:
        """Show the finished sample clip's transcript: the viewer, else the first output."""
        json_path = self._task_json_output(task)
        if json_path and os.path.isfile(json_path):
            self.open_transcript_viewer_for(
                task.file_path, json_path, task.language or task.detected_language
            )
            return
        for out in task.output_paths or ():
            if os.path.isfile(out):
                self._open_file(out)
                return
        self.log("The sample clip finished but no transcript file was found.")

    def _ensure_transcribe_ready(self) -> bool:
        """Run the one-time transcribe gates; True if a task may be enqueued.

        Shared by add() and _bulk_enqueue so the model-download modal,
        the optional-alignment offer, and the worker spawn happen exactly
        ONCE per user action — not once per file in a multi-file batch.

        First-transcribe gating:
          1. If the model bytes are not on disk → download dialog.
          2. Then call ensure_worker_ready to lazy-load the model into a
             worker subprocess. v1.0.3: was previously preloaded at startup;
             deferring it here saves ~1.5 GB of idle RAM in sessions where the
             user never clicks Transcribe.
        """
        if not self._model_bytes_present():
            if self.model_setup_running:
                self.log("Model download already in progress — please wait.")
                return False
            if not messagebox.askyesno(
                _("Whisper model required"),
                self._model_download_question(),
                parent=self,
            ):
                self.log("Transcription cancelled: the Whisper model is required.")
                return False
            if not self.ensure_model_with_modal():
                self.log("Transcription cancelled: the Whisper model is not ready.")
                return False
        # Slim build: if word-alignment is enabled but its (large, optional)
        # package isn't installed, offer the one-time download BEFORE the
        # worker spawns so the worker activates with it present. Declining
        # is fine — the worker skips alignment gracefully.
        if self.app_config.get("alignment") == "stable_ts":
            self._offer_optional_install("alignment", N_("Word-timestamp alignment"), "700 MB")
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Transcription cancelled: model load was cancelled")
            return False
        return True

    def _model_download_size_hint(self) -> str:
        """Return e.g. "about 500 MB, " for the configured model ("" if unknown)."""
        try:
            from core.model_manager import (
                DEFAULT_MODEL_SLUG,
                approx_download_size_text,
            )
            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
            text = approx_download_size_text(self.app_config, slug)
        except Exception:  # noqa: BLE001 -- a size hint must never block the prompt
            text = ""
        return f"{text}, " if text else ""

    def _model_download_question(self) -> str:
        """The "Whisper model required" question, with the download size when it is known."""
        size = self._model_download_size_hint().rstrip(", ")
        if size:
            return _("The Whisper model must be downloaded before the first transcription. "
                     "Download it now? ({size}, one time only)", size=size)
        return _("The Whisper model must be downloaded before the first transcription. "
                 "Download it now? (one time only)")

    def _selected_transcribe_language(self) -> str | None:
        """The Transcribe-tab language as a code, or None for auto-detect."""
        lang_choice = getattr(self, "transcribe_lang_var", None)
        if lang_choice is None:
            return None
        choice = lang_choice.get().strip()
        if not choice or choice.lower() == "auto":
            return None
        from app.domain.languages import SUBTITLE_LANGUAGES
        code = next((c for name, c in SUBTITLE_LANGUAGES if name == choice), "")
        return code or None

    def _selected_language_pair(self) -> tuple[tuple[str, str] | None, str]:
        """Mixed-language audio: (the two codes, "") when it applies, else (None, why not).

        The reason is "" when the option is simply off; otherwise it says why
        this file falls back to one language.
        """
        var = self.__dict__.get("mixed_lang_var")
        if var is None or not var.get():
            return None, ""
        first = self._selected_transcribe_language()
        if not first:
            return None, _("Mixed-language audio needs the first language picked in Language (not Auto).")
        from app.domain.languages import SUBTITLE_LANGUAGES
        name = self.transcribe_lang2_var.get().strip()
        second = next((c for n, c in SUBTITLE_LANGUAGES if n == name), "")
        # Whisper's own codes: "zh-Hans,zh-CN" and "zh-Hant,zh-TW" are one spoken
        # language to it, and some picker languages (Irish, Zulu, ...) it does not know.
        from core.transcriber import _normalize_language
        w_first, w_second = _normalize_language(first), _normalize_language(second)
        if not w_first or not w_second:
            return None, _("Mixed-language audio supports only languages Whisper knows; "
                           "{language} is not one of them.",
                           language=self.transcribe_lang2_var.get().strip() if not w_second
                           else self.transcribe_lang_var.get().strip())
        if w_second == w_first:
            return None, _("Mixed-language audio needs two different languages.")
        backend = str(self.app_config.get("transcribe_backend") or "faster_whisper").strip().lower()
        if backend != "faster_whisper":
            return None, _("Mixed-language audio works with the faster-whisper engine only.")
        if bool(self.app_config.get("translate_to_english", False)):
            return None, _("Mixed-language audio does not combine with English translation.")
        return (first, second), ""

    def _note_mixed_not_applied(self, name: str) -> None:
        """Downloads and the watched folder keep one language: say so while the tick box is on."""
        var = self.__dict__.get("mixed_lang_var")
        if var is not None and var.get():
            self.log(_("Mixed-language audio applies to files added on the Transcribe tab; "
                       "{name} uses one language.", name=name))

    def _confirm_english_only_model(self) -> bool:
        """Before queueing: guide the user off an English-only model when the
        language is not English (auto-detect included).

        An English-only model turns other speech into wrong English text
        without any error, so the same dialog as the Live tab offers the
        model's multilingual twin. True when queueing may go ahead.
        """
        try:
            if not self._engine_uses_whisper_model():
                return True
        except Exception:  # noqa: BLE001
            return True
        from core.model_manager import (
            DEFAULT_MODEL_SLUG,
            approx_download_size_text,
            english_only_mismatch,
            model_downloaded,
            multilingual_counterpart,
        )

        language = self._selected_transcribe_language()
        slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG).strip()
        if not english_only_mismatch(self.app_config, slug, language):
            return True
        kept: set[tuple[str, str]] = self.__dict__.setdefault("_english_only_kept", set())
        if (slug, language or "") in kept:
            return True
        if self.__dict__.get("_english_only_asking"):
            return False  # a second drop while the question is open
        from app.dialogs import english_only_model as dlg

        alt = multilingual_counterpart(self.app_config, slug)
        name = ""
        lang_var = getattr(self, "transcribe_lang_var", None)
        if language and lang_var is not None:
            # The variable keeps the English name (the stored value); show it translated.
            from app.domain.languages import subtitle_language_label
            name = subtitle_language_label(lang_var.get().strip())
        prompt = dlg.EnglishOnlyPrompt(
            model=slug, language=name, alternative=alt,
            reason=(_("About the same size and speed, and it understands {language}.",
                      language=name) if name
                    else _("About the same size and speed, and it understands other languages.")),
            size_text=approx_download_size_text(self.app_config, alt),
            downloaded=model_downloaded(self.app_config, alt),
        )
        self.__dict__["_english_only_asking"] = True
        try:
            choice = dlg.ask_english_only(self, prompt)
        finally:
            self.__dict__["_english_only_asking"] = False
        if choice == dlg.CHOICE_SWITCH:
            if self._switch_transcribe_model(alt):
                return True
            self.log("Not queued: the Whisper model was not changed.")
            return False
        if choice == dlg.CHOICE_KEEP:
            kept.add((slug, language or ""))
            return True
        if choice == dlg.CHOICE_CHOOSE:
            # The full model list is the Advanced dialog's picker (the tab's own Model
            # combo is built but never shown since the Accuracy row replaced it).
            try:
                self.after(50, self.open_advanced_dialog)
            except Exception:  # noqa: BLE001
                logger.debug("Could not open the model picker", exc_info=True)
        self.log("Not queued: the Whisper model understands English only.")
        return False

    def _warn_english_only(self, language: str | None, name: str) -> None:
        """Queueing nobody watches (watched folder, transcribe after download)
        cannot ask, so an English-only model with another language is said
        in the log instead."""
        try:
            if not self._engine_uses_whisper_model():
                return
            from core.model_manager import (
                DEFAULT_MODEL_SLUG,
                english_only_mismatch,
                multilingual_counterpart,
            )

            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG).strip()
            if not english_only_mismatch(self.app_config, slug, language):
                return
            alt = multilingual_counterpart(self.app_config, slug)
        except Exception:  # noqa: BLE001 -- a warning must never block queueing
            logger.debug("English-only check failed", exc_info=True)
            return
        self.log(
            f"Warning: {name} will be transcribed with the '{slug}' model, which "
            "understands English only; speech in another language comes out as "
            f"wrong English text. Pick '{alt}' or another multilingual model in "
            "the Transcribe tab."
        )

    def _switch_transcribe_model(self, slug: str) -> bool:
        """Point the Transcribe-tab picker at ``slug`` the way a user pick does."""
        mvar = getattr(self, "transcribe_model_var", None)
        label_to_slug = getattr(self, "_transcribe_model_label_to_slug", None) or {}
        label = next((lbl for lbl, s in label_to_slug.items() if s == slug), None)
        if mvar is None or label is None:
            self.log(f"Could not switch to the '{slug}' model; pick it in Advanced settings.")
            return False
        mvar.set(label)
        self._on_model_selected()
        return str(self.app_config.get("whisper_model") or "") == slug

    def _apply_task_options(self, task: TranscriptionTask) -> None:
        """Apply the Transcribe-tab language + clip-range options to a task.

        Shared by add() and _bulk_enqueue so a bulk-enqueued file gets the
        same per-task language override and optional time-slice as a single
        file enqueued through Transcribe.
        """
        # Per-task language override. The picker shows "Auto" for the
        # default Whisper auto-detect; any other value is a language
        # name that maps to a known code via app.domain.languages.
        code = self._selected_transcribe_language()
        # (only when the Transcribe tab built the tick box; minimal stand-ins in tests have none)
        pair, why_not = (self._selected_language_pair() if self.__dict__.get("mixed_lang_var") is not None
                         else (None, ""))
        if pair:
            task.languages = pair
        else:
            if why_not:
                self.log(why_not + " " + _("This file uses one language."))
            if code:
                task.language = code
        # "English translation" option: Whisper's own translate task, only
        # where the engine and model can do it (the checkbox is disabled
        # otherwise, and the worker refuses an unsupported combination).
        if bool(self.app_config.get("translate_to_english", False)):
            reason = self._translate_unsupported_reason()
            if reason:
                self.log(f"English translation skipped for this file: {reason}")
            else:
                task.whisper_task = "translate"
        # Optional time-slice (Transcribe-tab time range): transcribe only
        # [start, end]. A 0:00:00 / blank bound is "unset", so leaving both
        # at 0:00:00 transcribes the whole file.
        if hasattr(self, "transcribe_start_time_var"):
            from app.services.download_service import _parse_timecode
            task.clip_start = _parse_timecode(self.transcribe_start_time_var.get()) or None
            task.clip_end = _parse_timecode(self.transcribe_end_time_var.get()) or None

    def _bulk_enqueue(self, paths: "list[str]") -> int:
        """Enqueue many files as transcription tasks in one shot.

        Multi-file Browse and multi-file drag-and-drop both call this instead
        of looping add() per path: add() re-pops the ~3 GB model-download
        modal and re-runs the tab-switch + full-tree refresh() PER FILE, which
        is jarring for a 20-file drop. Here the model/worker gate runs ONCE up
        front, every existing file is enqueued with the same language/clip
        options, and refresh() runs ONCE at the end. Returns the count
        enqueued (0 if the gate was declined or no path existed).
        """
        from core.watcher import is_transcribable

        files = [p for p in paths if p and os.path.isfile(p)]
        # Files that are not audio or video would only become failed jobs.
        skipped = [p for p in files if not is_transcribable(p)]
        if skipped:
            files = [p for p in files if p not in skipped]
            names = ", ".join(os.path.basename(p) for p in skipped[:5])
            more = f" (+{len(skipped) - 5} more)" if len(skipped) > 5 else ""
            self.log(f"Not queued, not audio or video: {names}{more}")
        if not files:
            if skipped:
                show_error(
                    self, _("Cannot transcribe these files"),
                    _("None of the chosen files is audio or video."),
                    detail="\n".join(os.path.basename(p) for p in skipped),
                )
            return 0
        if not self._confirm_english_only_model():
            return 0
        if not self._ensure_transcribe_ready():
            return 0
        count = 0
        for path in files:
            task = TranscriptionTask(path)
            self._apply_task_options(task)
            if self._same_job_active(task):
                # Same rule as add(): a job already waiting, running or paused for this
                # file (and time range) is not queued a second time.
                self.log(f"Already in the queue: {os.path.basename(path)}")
                continue
            self.queue.append(task)
            count += 1
        if count:
            self.pb["value"] = 0
            self.nb.select(self.t2)
            self.refresh()
        return count

    def _model_bytes_present(self) -> bool:
        """True when the Whisper model files are already on disk.

        Cheap probe used by the lazy-load enqueue gate to decide
        whether to surface the model download dialog. The resolved model
        folder must hold its ``model.bin``: a folder alone can be a
        killed download, which the worker then fails to load. Deeper
        corruption still surfaces via the worker's ``startup_error``.
        """
        try:
            from core.hub import (
                default_hub_folder,
                model_folder_for,
                model_weights_present,
            )

            mp = str(self.app_config.get("model_path") or "").strip()
            if mp and model_weights_present(mp):
                return True

            model_info = self.app_config.get("model") or {}
            model_name = ""
            if isinstance(model_info, dict):
                model_name = str(model_info.get("name") or "").strip()
            if not model_name:
                model_name = str(self.app_config.get("whisper_model") or "").strip()
            if not model_name:
                model_name = "faster-whisper-large-v3"

            hub_folder = str(self.app_config.get("hub_folder") or "").strip()
            if not hub_folder:
                hub_folder = str(default_hub_folder())

            return model_weights_present(model_folder_for(hub_folder, model_name))
        except Exception:  # noqa: BLE001
            return False

    def enqueue_transcription_from_download(
        self, file_path: str, language: str, source_download: "Any" = None
    ) -> None:
        """Auto-transcribe-after-download wiring: push a task without freezing.

        Runs on the Tk main thread (the download-complete handler). A
        cold Whisper-model load takes 10–60 s, and the old code waited
        for the worker's ``ready`` event synchronously here — which
        froze the whole UI after every download with the checkbox on
        (the "Transcribe after download freezes the app" bug).

        Instead we spawn a worker if none is alive yet and poll for
        readiness with ``after()`` so the event loop keeps running; the
        task is enqueued the moment a worker reports ready. If the load
        never completes we drop the task rather than queue one that can
        never run.
        """
        base = os.path.basename(file_path)

        def _enqueue() -> None:
            # The model-load wait can run up to ~120 s. If the user cancelled
            # or removed this download during that window, don't resurrect it
            # — re-stamping 'transcribing' and enqueuing a transcription for a
            # download they explicitly cancelled (Audit P2-3).
            if source_download is not None and getattr(
                source_download, "status", None
            ) in ("cancelled", "error"):
                return
            task = TranscriptionTask(file_path)
            if hasattr(task, "language"):
                setattr(task, "language", language)
            # Link the originating download row to this transcription so
            # the Download tab shows "transcribing" + live progress, then
            # flips back to "finished" when the transcription ends.
            if source_download is not None:
                task.source_download = source_download
                source_download.transcription_task = task
                source_download.status = "transcribing"
                self.refresh_download_queue()
            self.queue.append(task)
            self._warn_english_only(language or None, base)
            App._note_mixed_not_applied(self, base)  # a class call: test stand-ins lack it
            self.refresh()

        def _on_timeout() -> None:
            self.log(f"Auto-transcribe skipped: model load timed out for {base} — {HEADLESS_READY_TIMEOUT_S} s")
            if source_download is None:
                return
            source_download.transcription_task = None
            if getattr(source_download, "status", None) in ("cancelled", "error"):
                pass  # the user's Cancel (or an error) stands
            elif getattr(source_download, "make_subbed_video", False):
                from app.services.subbed_video import end_chain
                end_chain(
                    self, source_download, "error",
                    error="The Whisper model did not load in time; no subtitled video was made.",
                )
                return
            else:
                source_download.status = "finished"
            self.refresh_download_queue()

        self._when_worker_ready(
            _enqueue,
            on_timeout=_on_timeout,
            loading_label=f"will transcribe {base} when ready.",
        )

    def _when_worker_ready(
        self,
        on_ready: Callable[[], None],
        *,
        on_timeout: Callable[[], None] | None = None,
        loading_label: str = "",
    ) -> None:
        """Run ``on_ready`` on the Tk main thread once a transcription
        worker is loaded, without blocking the event loop.

        Every main-thread enqueue path (auto-transcribe-after-download,
        crash-resume, watched-folder) used to call
        ``ensure_worker_ready(headless=True)``, which blocks on a
        ``threading.Event.wait`` for up to the model-load timeout. Those
        handlers run on the Tk main thread, so a cold model load froze
        the whole UI. This spawns a worker if none is alive and polls
        for readiness with ``after()`` instead; ``on_timeout`` (if
        given) runs when the load doesn't finish within the timeout.
        """
        svc = self.transcription_service
        if svc.ready_workers():
            on_ready()
            return
        # Spawn a worker if none is alive yet — but don't spawn a second
        # if one is already loading (a parallel path may have started it).
        if not svc.active_workers():
            svc.start_worker(temporary=False)
            if loading_label:
                self.log(f"Loading Whisper model — {loading_label}")
        deadline = time.monotonic() + HEADLESS_READY_TIMEOUT_S

        def _await_ready() -> None:
            if svc.ready_workers():
                on_ready()
                return
            if time.monotonic() >= deadline:
                if on_timeout is not None:
                    on_timeout()
                return
            self.after(400, _await_ready)

        self.after(400, _await_ready)

    def add_download(self) -> None:
        self.download_service.enqueue_from_form()

    # Right-click context menus -----------------------------------------------
    def menu_row(self, e: tk.Event) -> None:
        item = self.tree.identify_row(e.y)
        if not item:
            return
        sel = self.tree.selection()
        # If the right-clicked row is part of a multi-row selection, act
        # on the whole selection (bulk) rather than resetting to one row.
        if item in sel and len(sel) > 1:
            tasks = [t for t in (self.row_map.get(i) for i in sel) if t]
            if tasks:
                self._bulk_task_menu(tasks, e)
            return
        self.tree.selection_set(item)
        task = self.row_map.get(item)
        if not task:
            return
        # Drive the menu entries from the SAME pure helper the always-visible
        # action bar uses (button_states_for_status), so the two can never
        # disagree about which actions a status offers.
        from app.widgets.tabs import button_states_for_status
        states = button_states_for_status(task.status)
        m = tk.Menu(self, tearoff=0)
        if states["pause"]:
            m.add_command(label=_("Pause"), command=lambda: self.pause(task))
        if states["resume"] and task.status == "paused":
            m.add_command(label=_("Resume"), command=lambda: self.resume(task))
        if states["cancel"]:
            m.add_command(label=_("Cancel"), command=lambda: self.cancel(task))
        if task.status == "waiting" and states["remove"]:
            m.add_command(label=_("Remove"), command=lambda: self.remove_task(task))
        if task.status in ("finished", "cancelled", "error"):
            if task.status == "finished":
                m.add_command(
                    label=_("Export → oTranscribe (.otr)"),
                    command=lambda: self.integrations_service.export_task_to_otr(task),
                )
                m.add_command(
                    label=_("Burn subtitles into video..."),
                    command=lambda: self._burn_subs_for(task),
                )
                m.add_command(
                    label=_("View transcript"),
                    command=lambda: self.open_transcript_viewer_for(
                        task.file_path, self._task_json_output(task),
                        task.language or task.detected_language,
                    ),
                )
                out_file = task_output_file(task)
                m.add_command(
                    label=folder_action_label(
                        _("Open output folder"), _("Open Output Folder in Finder"), out_file),
                    command=lambda: self._open_folder(task_output_folder(task), select=out_file),
                )
                m.add_separator()
            # No "Resume" for a cancelled job (button_states_for_status): Re-run only.
            if states["rerun"]:
                m.add_command(label=_("Re-run"), command=lambda: self._rerun_task(task))
            if states["remove"]:
                m.add_command(label=_("Remove"), command=lambda: self.remove_task(task))
        m.tk_popup(e.x_root, e.y_root)

    def _task_has_checkpoint(self, task: TranscriptionTask) -> bool:
        """True when a cancelled task has a resumable partial on disk.

        Cheap, defensive probe shared by menu_row and the action bar so
        both surface "Resume" under the same condition. Any failure (the
        checkpoint module missing, a bad path) is swallowed — the probe
        must never block the menu or the action-bar refresh.

        Goes straight to ``core._checkpoint`` (a tiny, dependency-light
        module — just hashlib/json/os/pathlib) rather than through
        ``core.transcriber.has_resumable_checkpoint``: that one-line
        wrapper forces the FIRST import of the whole faster_whisper /
        ctranslate2 backend stack onto the Tk main thread, synchronously,
        inside a probe that runs on every 500 ms refresh tick for every
        selected row. That is exactly the kind of front-end wiring fault
        that froze the whole app the moment a task was first cancelled —
        the probe only ever needed a cheap file-existence check.
        """
        if getattr(task, "status", "") != "cancelled":
            return False
        try:
            from core import _checkpoint
            return bool(_checkpoint.has_checkpoint(task.file_path))
        except Exception:  # noqa: BLE001
            return False

    def download_menu_row(self, e: tk.Event) -> None:
        item = self.download_tree.identify_row(e.y)
        if not item:
            return
        sel = self.download_tree.selection()
        if item in sel and len(sel) > 1:
            tasks = [t for t in (self.download_row_map.get(i) for i in sel) if t]
            if tasks:
                self._bulk_download_menu(tasks, e)
            return
        task = self.download_row_map.get(item)
        if not task:
            return
        from app.services.download_service import _is_smtv_task
        from app.widgets.tabs import download_button_states_for_status
        saved_dl = getattr(task, "saved_path", None)
        has_file_dl = bool(saved_dl) and os.path.isfile(saved_dl) if saved_dl else False
        dstates = download_button_states_for_status(
            task.status, is_smtv=_is_smtv_task(task), has_saved_file=has_file_dl
        )
        m = tk.Menu(self, tearoff=0)
        if task.status in ("waiting", "running", "transcribing", "burning"):
            # "transcribing" = the download finished and handed off to an
            # auto-transcribe; Cancel here stops that linked task too
            # (cancel_download unlinks + cancels transcription_task).
            # "burning" = the subtitled-video burn; Cancel kills its ffmpeg.
            if dstates["pause"]:
                m.add_command(label=_("Pause"), command=lambda: self.pause_download(task))
            m.add_command(label=_("Cancel"), command=lambda: self.cancel_download(task))
        elif task.status == "paused":
            m.add_command(label=_("Resume"), command=lambda: self.resume_download(task))
            m.add_command(label=_("Cancel"), command=lambda: self.cancel_download(task))
        elif task.status in ("finished", "cancelled", "error"):
            saved = getattr(task, "saved_path", None)
            if task.status == "finished" and saved and os.path.isfile(saved):
                m.add_command(
                    label=_("Open file"),
                    command=lambda p=saved: self._open_file(p),
                )
            reveal_target = saved if task.status == "finished" and saved and os.path.isfile(saved) else None
            m.add_command(
                label=folder_action_label(
                    _("Open download folder"), _("Open Download Folder in Finder"), reveal_target),
                command=lambda: self._open_folder(task.folder, select=reveal_target),
            )
            m.add_command(label=_("Re-run"), command=lambda: self._rerun_download(task))
            m.add_command(label=_("Remove"), command=lambda: self.remove_download(task))
        m.tk_popup(e.x_root, e.y_root)

    # --- bulk (multi-select) queue actions -----------------------------------
    def _bulk_apply(self, tasks: list[Any], fn: Callable[[Any], Any]) -> None:
        for t in list(tasks):
            try:
                fn(t)
            except Exception:  # noqa: BLE001
                pass

    def _resumable_tasks(self, tasks: list[Any]) -> list[Any]:
        # See _task_has_checkpoint: go straight to the lightweight
        # core._checkpoint module rather than core.transcriber, which
        # would force the heavy faster_whisper/ctranslate2 backend
        # import onto the Tk main thread for a plain file-existence check.
        try:
            from core import _checkpoint
        except Exception:  # noqa: BLE001
            return []
        out: list[Any] = []
        for t in tasks:
            if getattr(t, "status", "") == "cancelled":
                try:
                    if _checkpoint.has_checkpoint(t.file_path):
                        out.append(t)
                except Exception:  # noqa: BLE001
                    pass
        return out

    def _active_dup_in_queue(self, file_path: str) -> bool:
        """True if a non-terminal queue task already targets ``file_path``.

        Re-run / Resume re-enqueue a fresh task from a terminal (finished /
        cancelled / error) row. Without this guard, double-clicking Re-run
        (or re-running while a previous re-run of the same file is still
        waiting / running) enqueues a SECOND concurrent transcription of the
        same file — wasted work and confusing duplicate rows. Mirrors the
        watched-folder dedup in :meth:`_enqueue_watched_file`: skip only when
        a same-path task is still pending; a finished/cancelled/error row
        does not block a fresh re-run.
        """
        for existing in self.queue:
            try:
                # Status first: a finished row costs no filesystem calls (this
                # runs on the Tk thread, once per queue row, per candidate).
                if getattr(existing, "status", "") in ("finished", "cancelled", "error"):
                    continue
                if _same_file(os.path.abspath(existing.file_path), os.path.abspath(file_path)):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _bulk_rerun(self, tasks: list[Any]) -> None:
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Re-run cancelled: model load was cancelled")
            return
        for t in tasks:
            if self._active_dup_in_queue(t.file_path):
                self.log(
                    f"Re-run skipped: {os.path.basename(t.file_path)} is "
                    f"already in the queue."
                )
                continue
            nt = TranscriptionTask(t.file_path)
            if getattr(t, "language", None):
                nt.language = t.language
            nt.languages = getattr(t, "languages", None)
            # Preserve the time-range slice across re-run (mirrors the Download
            # tab's _rerun_download fix) — without this a clipped row re-runs
            # the WHOLE file instead of the slice the user picked.
            nt.clip_start = getattr(t, "clip_start", None)
            nt.clip_end = getattr(t, "clip_end", None)
            nt.whisper_task = getattr(t, "whisper_task", "transcribe")
            self.queue.append(nt)
        self.refresh()

    def _bulk_resume(self, tasks: list[Any]) -> None:
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Resume cancelled: model load was cancelled")
            return
        for t in tasks:
            if self._active_dup_in_queue(t.file_path):
                self.log(
                    f"Resume skipped: {os.path.basename(t.file_path)} is "
                    f"already in the queue."
                )
                continue
            nt = TranscriptionTask(t.file_path)
            if getattr(t, "language", None):
                nt.language = t.language
            nt.languages = getattr(t, "languages", None)
            nt.clip_start = getattr(t, "clip_start", None)
            nt.clip_end = getattr(t, "clip_end", None)
            nt.whisper_task = getattr(t, "whisper_task", "transcribe")
            # Continue with the options the interrupted run started with.
            task_settings.inherit(nt, t)
            nt.resume = True
            nt.cancelled = False
            self.queue.append(nt)
        self.refresh()

    def _bulk_task_menu(self, tasks: list[Any], e: tk.Event) -> None:
        active = [t for t in tasks if t.status in ("waiting", "running", "paused")]
        terminal = [t for t in tasks if t.status in ("finished", "cancelled", "error")]
        if not active and not terminal:
            return
        m = tk.Menu(self, tearoff=0)
        if active:
            m.add_command(label=_("Cancel selected ({count})", count=len(active)),
                          command=lambda ts=active: self._bulk_apply(ts, self.cancel))
        if terminal:
            m.add_command(label=_("Re-run selected ({count})", count=len(terminal)),
                          command=lambda ts=terminal: self._bulk_rerun(ts))
            # No "Resume selected" for cancelled jobs: Re-run only (button_states_for_status).
            m.add_command(label=_("Remove selected ({count})", count=len(terminal)),
                          command=lambda ts=terminal: self._bulk_apply(ts, self.remove_task))
        waiting = [t for t in tasks if t.status == "waiting"]
        if waiting:
            # Not-yet-started rows leave the list too, as the Remove button does.
            m.add_command(label=_("Remove waiting ({count})", count=len(waiting)),
                          command=lambda ts=waiting: self._bulk_apply(ts, self.remove_task))
        m.tk_popup(e.x_root, e.y_root)

    def _bulk_download_menu(self, tasks: list[Any], e: tk.Event) -> None:
        active = [t for t in tasks if t.status in ("waiting", "running", "transcribing", "burning")]
        terminal = [t for t in tasks if t.status in ("finished", "cancelled", "error")]
        if not active and not terminal:
            return
        m = tk.Menu(self, tearoff=0)
        if active:
            m.add_command(label=_("Cancel selected ({count})", count=len(active)),
                          command=lambda ts=active: self._bulk_apply(ts, self.cancel_download))
        if terminal:
            m.add_command(label=_("Re-run selected ({count})", count=len(terminal)),
                          command=lambda ts=terminal: self._bulk_apply(ts, self._rerun_download))
            m.add_command(label=_("Remove selected ({count})", count=len(terminal)),
                          command=lambda ts=terminal: self._bulk_apply(ts, self.remove_download))
        m.tk_popup(e.x_root, e.y_root)

    def _open_folder(self, folder: str, select: str | None = None) -> None:
        _open_folder_helper(folder, parent=self, select=select)

    def _rerun_task(self, task: TranscriptionTask) -> None:
        # Right-click re-run is an interactive action: show the
        # lazy-load modal if no worker is alive yet.
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Re-run cancelled: model load was cancelled")
            return
        if self._active_dup_in_queue(task.file_path):
            self.log(
                f"Re-run skipped: {os.path.basename(task.file_path)} is "
                f"already in the queue."
            )
            return
        new_task = TranscriptionTask(task.file_path)
        if getattr(task, "language", None):
            new_task.language = task.language
        new_task.languages = getattr(task, "languages", None)
        new_task.clip_start = getattr(task, "clip_start", None)
        new_task.clip_end = getattr(task, "clip_end", None)
        new_task.whisper_task = getattr(task, "whisper_task", "transcribe")
        self.queue.append(new_task)
        self.refresh()

    def resume_task(self, task: TranscriptionTask) -> None:
        """Re-enqueue a cancelled task to resume from its checkpoint.

        We don't try to revive the original task object in place: the
        cancel path tore down its worker and the row is in a terminal
        state. A fresh TranscriptionTask carrying ``resume=True`` is
        clearer for the user (a new Queue row appears) and matches
        the existing ``_rerun_task`` pattern.

        The worker side falls back to a full re-run if the checkpoint
        turns out to be stale at validation time, so the user always
        gets an output.
        """
        # Interactive — surface the lazy-load modal if needed.
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Resume cancelled: model load was cancelled")
            return
        if self._active_dup_in_queue(task.file_path):
            self.log(
                f"Resume skipped: {os.path.basename(task.file_path)} is "
                f"already in the queue."
            )
            return
        new_task = TranscriptionTask(task.file_path)
        if getattr(task, "language", None):
            new_task.language = task.language
        new_task.languages = getattr(task, "languages", None)
        new_task.clip_start = getattr(task, "clip_start", None)
        new_task.clip_end = getattr(task, "clip_end", None)
        new_task.whisper_task = getattr(task, "whisper_task", "transcribe")
        # Continue with the options the interrupted run started with.
        task_settings.inherit(new_task, task)
        new_task.resume = True
        new_task.cancelled = False
        self.queue.append(new_task)
        self.refresh()

    def _rerun_download(self, task: VideoDownloadTask) -> None:
        from app.domain.tasks import VideoDownloadTask as VDT
        copy = VDT(
            task.url, task.folder, task.format_label, task.format_info, task.title,
            subtitles_enabled=task.subtitles_enabled,
            subtitle_lang=task.subtitle_lang,
            detected_language=task.detected_language,
            # Preserve the time-range slice — without this a re-run silently
            # fetched the full video instead of the slice the user picked.
            section_start=task.section_start,
            section_end=task.section_end,
            # Preserve the caption-only shortcut — without this a retry of
            # a failed "use captions instead" task would silently fall
            # back to a full media download.
            caption_only=task.caption_only,
            caption_kind=task.caption_kind,
            make_subbed_video=getattr(task, "make_subbed_video", False),
        )
        self.download_queue.append(copy)
        self.refresh_download_queue()
        self.download_service.process_queue()

    def set_download_duration(self, seconds: float) -> None:
        """Point the Download-tab position sliders at the probed video
        length. seconds <= 0 (live / unknown / SMTV) leaves them disabled."""
        dur = max(0.0, float(seconds or 0.0))
        self._download_duration = dur
        start = getattr(self, "download_start_scale", None)
        end = getattr(self, "download_end_scale", None)
        if start is None or end is None:
            return
        # Reset the slider knobs to 0 WITHOUT firing _on_download_scale —
        # otherwise the (debounced) probe would wipe a range the user just
        # typed into the Start/End fields.
        self._suppress_scale_cb = True
        try:
            for sc in (start, end):
                sc.configure(to=dur if dur > 0 else 1.0)
                sc.set(0.0)
                sc.state(["!disabled"] if dur > 0 else ["disabled"])
        finally:
            self._suppress_scale_cb = False
        if getattr(self, "download_duration_var", None) is not None:
            from app.services.download_service import _fmt_timecode
            self.download_duration_var.set(
                _("video length {length} — drag to set the range", length=_fmt_timecode(dur))
                if dur > 0 else ""
            )

    def _sync_download_scale_from_text(self, which: str) -> None:
        """Move the position slider to match its Start/End field after a
        direct edit (typing, not dragging).

        _on_download_scale only writes slider -> field. Without this, typing
        a value directly left the slider at its old (usually 0:00:00)
        position -- invisible until the user later touched EITHER slider,
        at which point that slider's stale position silently overwrote the
        just-typed value back to wherever the knob visually still sat.
        """
        if getattr(self, "_suppress_scale_cb", False):
            return
        dur = getattr(self, "_download_duration", 0.0)
        if dur <= 0:
            return
        scale = getattr(
            self, "download_start_scale" if which == "start" else "download_end_scale",
            None,
        )
        if scale is None:
            return
        var = self.download_start_time_var if which == "start" else self.download_end_time_var
        try:
            raw = var.get()
        except Exception:  # noqa: BLE001
            return
        from app.services.download_service import _parse_timecode
        secs = _parse_timecode(raw)
        if secs is None:
            # Mid-typing (e.g. "0:0") or garbled -- leave the slider alone
            # rather than snapping it to a meaningless position.
            return
        secs = max(0.0, min(dur, secs))
        self._suppress_scale_cb = True
        try:
            scale.set(secs)
        finally:
            self._suppress_scale_cb = False

    def _on_download_scale(self, which: str, value: str) -> None:
        """A position slider moved — write its timecode into the matching
        Start/End field (0:00:00 stays the 'unset' sentinel).

        If the user drags one knob past the other, keep the visible range
        non-crossing by snapping the other knob to the same point. That keeps
        the UI readable even though the backend also sanitises invalid ranges.
        """
        if getattr(self, "_suppress_scale_cb", False):
            return
        # No probed video length → ignore stray drags (a disabled ttk.Scale
        # still accepts the mouse, and the range would be a useless 0..1s).
        if getattr(self, "_download_duration", 0.0) <= 0:
            return
        from app.services.download_service import _fmt_timecode, _parse_timecode
        try:
            secs = float(value)
        except (TypeError, ValueError):
            return
        tc = _fmt_timecode(secs)
        if which == "start":
            self.download_start_time_var.set(tc)
            end_raw = ""
            try:
                end_raw = self.download_end_time_var.get()
            except Exception:  # noqa: BLE001
                end_raw = ""
            end_secs = _parse_timecode(end_raw)
            if end_secs is not None and end_secs > 0 and secs > end_secs:
                end_scale = getattr(self, "download_end_scale", None)
                self._suppress_scale_cb = True
                try:
                    self.download_end_time_var.set(tc)
                    if end_scale is not None:
                        end_scale.set(secs)
                finally:
                    self._suppress_scale_cb = False
        else:
            self.download_end_time_var.set(tc)
            start_raw = ""
            try:
                start_raw = self.download_start_time_var.get()
            except Exception:  # noqa: BLE001
                start_raw = ""
            start_secs = _parse_timecode(start_raw)
            if start_secs is not None and start_secs > 0 and secs < start_secs:
                start_scale = getattr(self, "download_start_scale", None)
                self._suppress_scale_cb = True
                try:
                    self.download_start_time_var.set(tc)
                    if start_scale is not None:
                        start_scale.set(secs)
                finally:
                    self._suppress_scale_cb = False

    def cancel_download(self, task: VideoDownloadTask) -> None:
        # Terminal-status guard (mirrors cancel()): the Esc question or a
        # context menu can still be open when the download ends, and a late
        # "yes" would turn a finished download into a cancelled one and
        # cancel the transcription that follows it.
        if getattr(task, "status", "") in ("finished", "cancelled", "error"):
            return
        # Paused, or waiting to start again: no worker runs that would clean
        # up after the cancel, so do its part (partial files, history row).
        no_worker = task.status in ("paused", "waiting")
        task.cancelled = True
        # Clear any pause hold so the (now cancelled) task can't be mistaken
        # for resumable, and a stale torn-down "paused" event can't resurrect
        # it (the _finish stale-pause guard only spares running/waiting).
        task.paused = False
        task.status = "cancelled"
        # Freeze the Elapsed column at the cancel moment.
        if task.end_time is None:
            task.end_time = time.time()
        # Snapshot task.process ONCE: the download worker thread can null it
        # (in _run_task's finally / _media_phase / _subtitle_phase) between
        # the truthiness test and the .poll() call, which on the shared
        # attribute would dereference None -> AttributeError on the Tk thread.
        proc = task.process
        if proc is not None and proc.poll() is None:
            # Tree-kill so the ffmpeg merge/extract child dies with yt-dlp;
            # otherwise it keeps the .part/output handle open and the
            # follow-up unlink/replace can fail with PermissionError.
            try:
                kill_process_tree(proc, force=False)
            except Exception:  # noqa: BLE001
                pass
        # If the download had already handed off to auto-transcribe, stop
        # that too and unlink it — otherwise the transcription keeps running
        # and finish_task would later overwrite this "cancelled" status.
        tr = getattr(task, "transcription_task", None)
        if tr is not None:
            task.transcription_task = None
            try:
                tr.source_download = None
                self.cancel(tr)
            except Exception:  # noqa: BLE001
                pass
        cancel_stopped = getattr(_inst_attr(self, "download_service"), "cancel_stopped", None)
        if no_worker and callable(cancel_stopped):
            cancel_stopped(task)
        self.refresh_download_queue()

    def remove_download(self, task: VideoDownloadTask) -> None:
        if task in self.download_queue:
            self.download_queue.remove(task)
        self.refresh_download_queue()

    def pause_download(self, task: VideoDownloadTask) -> None:
        """R2 "pause" for a download = STOP-AND-CONTINUE (not a true freeze).

        yt-dlp has no live pause signal, so we tear the process down the
        same way ``cancel_download`` does (reusing kill_process_tree) BUT:
          * land on status "paused" (not "cancelled"),
          * KEEP the partial .part file so resume can continue it,
          * only HOLD a linked auto-transcribe (don't cancel it permanently).

        SMTV downloads can't be paused (no HTTP Range on the CDN stream), so
        the action bar disables Pause for them; this method also guards.
        """
        from app.services.download_service import _is_smtv_task
        # Only a RUNNING download can be paused. A not-yet-started "waiting"
        # download has no process to stop-and-continue, and pausing it would
        # just strand it in "paused" (the action bar offers Cancel for waiting
        # rows, not Pause). Mirrors download_button_states_for_status.
        if task.status != "running":
            return
        if _is_smtv_task(task):
            self.log("Pause is unavailable for SMTV downloads (no resume point).")
            return
        task.paused = True
        task.status = "paused"
        if task.end_time is None:
            task.end_time = time.time()
        # Snapshot once (see cancel_download): the worker thread may null
        # task.process between the test and the .poll(), which would raise
        # AttributeError on the Tk thread and skip the tree-kill.
        proc = task.process
        if proc is not None and proc.poll() is None:
            # Same tree-kill as cancel so the ffmpeg child dies with yt-dlp
            # and releases the .part handle — but we do NOT delete the .part.
            try:
                kill_process_tree(proc, force=False)
            except Exception:  # noqa: BLE001
                pass
        # Hold (don't cancel) any linked auto-transcribe: keep it referenced
        # so a resume can re-establish the hand-off. The download row stops
        # mirroring its progress because the status is no longer "transcribing".
        if self.download_current is task:
            self.download_current = None
        self.refresh_download_queue()
        # Let the next waiting download (if any) start now that this one
        # released the single-download slot.
        self.download_service.process_queue()

    def resume_download(self, task: VideoDownloadTask) -> None:
        """Re-enqueue a paused download so yt-dlp continues its .part.

        build_download_command passes ``-c``/``--continue``, so re-running
        the SAME task resumes from the existing fragment instead of
        restarting at zero. We don't build a fresh task (unlike _rerun_
        download) precisely so the partial keeps its identity.
        """
        if task.status != "paused":
            return
        task.paused = False
        task.cancelled = False
        task.status = "waiting"
        task.end_time = None
        if task not in self.download_queue:
            self.download_queue.append(task)
        self.refresh_download_queue()
        self.download_service.process_queue()

    # --- R2: always-visible Download action bar ------------------------------
    def _selected_downloads(self) -> list[VideoDownloadTask]:
        tree = getattr(self, "download_tree", None)
        if tree is None:
            return []
        return [
            t for t in (self.download_row_map.get(i) for i in tree.selection()) if t
        ]

    def _download_button_states(self, task: VideoDownloadTask) -> dict[str, bool]:
        """Which action-bar buttons ``task`` allows (the pure helper, fed the
        facts it needs); shared by the bar's enabled state and its dispatcher."""
        from app.services.download_service import _is_smtv_task
        from app.widgets.tabs import download_button_states_for_status

        saved = getattr(task, "saved_path", None)
        return download_button_states_for_status(
            getattr(task, "status", ""),
            is_smtv=_is_smtv_task(task),
            has_saved_file=bool(saved) and os.path.isfile(saved),
        )

    def _download_action_apply(
        self, fn: "Callable[[VideoDownloadTask], Any]", key: str,
    ) -> None:
        """Run a per-download handler over the selected rows that allow the
        action ``key``, then refresh the action-bar enabled state.

        A mixed selection enables a button when ANY selected row allows it,
        so the dispatcher filters by the same rule (like the Queue tab's
        bar): Remove and Re-run have no status guard of their own, and
        applied to every row they hid a running download (its process and
        download slot stayed active, its Pause/Cancel controls were gone)
        and queued a copy of it.
        """
        for t in list(self._selected_downloads()):
            if not self._download_button_states(t).get(key):
                continue
            try:
                fn(t)
            except Exception:  # noqa: BLE001
                pass
        self._update_download_action_bar()

    def _download_action_open(self) -> None:
        """Open button — opens the saved file of a finished download, else
        falls back to its download folder."""
        for t in list(self._selected_downloads()):
            saved = getattr(t, "saved_path", None)
            if t.status == "finished" and saved and os.path.isfile(saved):
                self._open_file(saved)
            elif getattr(t, "folder", ""):
                self._open_folder(t.folder)

    def _update_download_action_bar(self) -> None:
        """Enable/disable Download action-bar buttons for the selection.

        Recomputed on <<TreeviewSelect>> and inside refresh_download_queue
        (which rebuilds the tree each tick) so a row whose status flipped
        never leaves a stale button enabled. Uses the same pure helper
        (download_button_states_for_status) as the design contract."""
        buttons = getattr(self, "download_action_buttons", None)
        if not buttons:
            return
        from app.widgets.tabs import DOWNLOAD_ACTION_KEYS

        merged = {k: False for k in DOWNLOAD_ACTION_KEYS}
        for t in self._selected_downloads():
            for k, v in self._download_button_states(t).items():
                if v:
                    merged[k] = True
        for key, btn in buttons.items():
            _set_enabled(btn, bool(merged.get(key)))

    def pause(self, t: TranscriptionTask) -> None:
        # Only a task actually running on a worker can be paused.
        # Pausing a still-"waiting" task would flip it to "paused", and
        # dispatch_waiting only picks up "waiting" — it would never run.
        if t.status != "running":
            return
        t.paused = True
        t.status = "paused"
        # Cooperative: the worker's reader thread flips its task.paused
        # and the transcriber waits between segments.
        self.transcription_service.send_control(t, "pause")
        self.refresh()

    def resume(self, t: TranscriptionTask) -> None:
        if t.status != "paused":
            return
        t.paused = False
        t.status = "running"
        self.transcription_service.send_control(t, "resume")
        self.refresh()

    def cancel(self, t: TranscriptionTask) -> None:
        # Terminal-status guard (mirrors pause()/resume()): a right-click menu
        # left open while the task finished could otherwise flip a just-
        # completed task back to "cancelled".
        if getattr(t, "status", "") in ("finished", "cancelled", "error"):
            return
        t.cancelled = True
        t.status = "cancelled"
        # Freeze the Elapsed column at the cancel moment so the user
        # sees how long the task actually ran before they stopped it.
        if getattr(t, "end_time", None) is None:
            t.end_time = time.time()
        # Cooperative cancel: tell the worker to stop at the next segment
        # boundary. The transcriber flushes a resumable checkpoint and the
        # worker emits "done", which finish_task() routes to release (and
        # retire, if temporary) the worker — so a partial run is no longer
        # lost the way a hard kill+restart lost it. The liveness watchdog
        # still reaps a worker that wedges instead of honouring the cancel.
        if not self.transcription_service.send_control(t, "cancel"):
            self.log("Cancelled (task was not yet running on a worker).")
            # No worker will report this task, so finish_task never runs:
            # release the Download row that waits on it here.
            self._release_waiting_download(t)
            desktop_alert.job_ended(self, t)
        else:
            self.log("Cancelling task; saving a resume checkpoint...")
        # The status line kept "<name>: 7% done — <last words>" and the overall bar its value
        # after a Cancel (screenshot reviews, 2026-10-21): say it was cancelled.
        status = _inst_attr(self, "status_var")  # stand-in objects (tests) may lack these
        if status is not None:
            status.set(_("{name}: cancelled at {percent}%",
                         name=os.path.basename(t.file_path), percent=int(getattr(t, "progress", 0) or 0)))
        if _inst_attr(self, "pb") is not None:
            self.update_overall_progress()
        self.refresh()

    def _release_waiting_download(self, t: TranscriptionTask) -> None:
        dl = getattr(t, "source_download", None)
        if dl is None or getattr(dl, "status", None) != "transcribing":
            return
        t.source_download = None
        dl.transcription_task = None
        if getattr(dl, "make_subbed_video", False):
            from app.services.subbed_video import after_transcription
            after_transcription(self, dl, t, False)
            return
        dl.status = "finished"
        self.refresh_download_queue()

    def remove_task(self, t: TranscriptionTask) -> None:
        if t.status == "waiting":
            # Never started, so no worker reports it: release the Download row that waits on
            # it, as cancel() does, or that row stays "transcribing" for good (review, 2026-10-21).
            self._release_waiting_download(t)
            desktop_alert.job_ended(self, t)
        if t in self.queue:
            self.queue.remove(t)
        self.refresh()

    # --- R2: always-visible Queue action bar ---------------------------------
    def _selected_tasks(self) -> list[TranscriptionTask]:
        """Tasks currently selected in the Queue Treeview (may be empty)."""
        tree = getattr(self, "tree", None)
        if tree is None:
            return []
        return [t for t in (self.row_map.get(i) for i in tree.selection()) if t]

    def _action_bar_apply(
        self, fn: "Callable[[TranscriptionTask], Any]", *, active_only: bool,
        also_waiting: bool = False,
    ) -> None:
        """Run a per-task handler over the current Queue selection.

        ``active_only`` restricts Pause/Cancel to waiting/running/paused
        rows; Re-run/Remove (active_only=False) apply to terminal rows, and
        Remove (``also_waiting``) to not-yet-started rows too.
        Shared by the action-bar buttons; mirrors the bulk context menu.
        """
        active = {"waiting", "running", "paused"}
        terminal = {"finished", "cancelled", "error"}
        wanted = active if active_only else terminal | ({"waiting"} if also_waiting else set())
        for t in list(self._selected_tasks()):
            if getattr(t, "status", "") in wanted:
                try:
                    fn(t)
                except Exception:  # noqa: BLE001
                    pass
        self._update_queue_action_bar()

    def _action_bar_resume(self) -> None:
        """Resume button — paused tasks resume in place. A cancelled job is re-run, not
        resumed (button_states_for_status)."""
        for t in list(self._selected_tasks()):
            if getattr(t, "status", "") == "paused":
                self.resume(t)
        self._update_queue_action_bar()

    def _update_queue_action_bar(self) -> None:
        """Enable/disable the Queue action-bar buttons for the selection.

        Recomputed on <<TreeviewSelect>> AND inside refresh() (which
        rebuilds the tree every tick), so the buttons never reflect a
        stale row. Uses the same button_states_for_status helper as
        menu_row. With a multi-row selection a button is enabled when it
        is valid for ANY selected row (matching the bulk menu).
        """
        buttons = getattr(self, "queue_action_buttons", None)
        if not buttons:
            return
        from app.widgets.tabs import QUEUE_ACTION_KEYS, button_states_for_status

        merged = {k: False for k in QUEUE_ACTION_KEYS}
        for t in self._selected_tasks():
            # No checkpoint probe: a cancelled job offers Re-run only, and a disk check here
            # ran every 500 ms for a selected row.
            states = button_states_for_status(getattr(t, "status", ""))
            for k, v in states.items():
                if v:
                    merged[k] = True
        for key, btn in buttons.items():
            _set_enabled(btn, bool(merged.get(key)))
        from app.widgets.tabs import queue_result_task

        hint = _inst_attr(self, "queue_select_hint")
        if hint is not None:
            # After the five buttons, only while nothing is selected.
            if self._selected_tasks():
                if hint.winfo_manager():
                    hint.pack_forget()
            elif not hint.winfo_manager():
                hint.pack(**rtl_layout.pack_kw(hint, side="left", padx=(6, 0), after=buttons["remove"]))
        task = queue_result_task(list(self._selected_tasks()))
        result_buttons = getattr(self, "queue_result_buttons", {})
        if "view" in result_buttons:
            # The viewer opens a transcript .json only; a run without that format would get a
            # "choose a .json yourself?" question instead (review, 2026-10-21).
            # No speech: no transcript was written and the result card shows no viewer either.
            _set_enabled(result_buttons["view"],
                         task is not None and not getattr(task, "no_speech", False)
                         and task_transcript_json(task, must_exist=True) is not None)
        if "folder" in result_buttons:
            _set_enabled(result_buttons["folder"], task is not None)
            # The context menu's name for the same action ("Reveal in Finder" on macOS).
            text = folder_action_label(_("Open output folder"), _("Open Output Folder in Finder"),
                                       task_output_file(task) if task is not None else None)
            if str(result_buttons["folder"].cget("text")) != text:
                result_buttons["folder"].configure(text=text)
        self._sync_queue_failure_line()

    def _action_bar_view_transcript(self) -> None:
        """"View transcript" under the Queue: the selected finished job's transcript."""
        from app.widgets.tabs import queue_result_task

        task = queue_result_task(list(self._selected_tasks()))
        if task is not None:
            self.open_transcript_viewer_for(
                task.file_path, self._task_json_output(task), task.language or task.detected_language,
            )

    def _action_bar_open_folder(self) -> None:
        """"Open output folder" under the Queue: where the selected finished job's files are."""
        from app.widgets.tabs import queue_result_task

        task = queue_result_task(list(self._selected_tasks()))
        if task is not None:
            self._open_task_output_folder(task)

    def _open_task_output_folder(self, task: "TranscriptionTask") -> None:
        self._open_folder(task_output_folder(task), select=task_output_file(task))

    def _sync_queue_failure_line(self) -> None:
        """Show why the selected failed job failed under the action bar, or hide the line."""
        var = getattr(self, "queue_failure_var", None)
        label = getattr(self, "queue_failure_label", None)
        if var is None or label is None:
            return
        from app.widgets.tabs import queue_failure_line

        line = queue_failure_line(list(self._selected_tasks()))
        if var.get() != line:
            var.set(line)
        shown = bool(label.winfo_manager())
        if line and not shown:
            bar = _inst_attr(self, "queue_action_bar")  # absent on test doubles
            if bar is not None:
                label.pack(fill="x", padx=10, pady=(0, 6), after=bar)
            else:
                label.pack(fill="x", padx=10, pady=(0, 6))
        elif not line and shown:
            label.pack_forget()

    def clear_completed(self) -> None:
        self.queue[:] = [t for t in self.queue if t.status not in ("finished", "cancelled", "error")]
        self.refresh()

    def clear_completed_downloads(self) -> None:
        """Download-tab counterpart to clear_completed() above -- the
        Queue tab has always had this; the Download tab didn't."""
        self.download_queue[:] = [
            t for t in self.download_queue if t.status not in ("finished", "cancelled", "error")
        ]
        self.refresh_download_queue()

    # Web / LAN access server -------------------------------------------------
    def _save_server_prefs(self) -> None:
        """Persist the port / share-on-LAN / token choices."""
        try:
            port = int(self.server_port_var.get())
        except (tk.TclError, ValueError):
            port = 8765
        port = port if 1 <= port <= 65535 else 8765
        self.app_config["server_port"] = port
        self.app_config["server_share_lan"] = bool(self.server_share_lan_var.get())
        self.app_config["server_token"] = self.server_token_var.get().strip()
        self.app_config["server_https_enabled"] = bool(
            self.server_https_enabled_var.get())
        self.app_config["server_webhook_url"] = (
            self.server_webhook_url_var.get().strip())
        # The field trims the spaces around what was typed (a pasted secret
        # often carries one) and nothing else. The trimmed value must be a
        # usable header value, else it is not saved and the old one stays.
        typed_secret = webhook_secret_from_input(
            self.server_webhook_secret_var.get())
        if not typed_secret or webhook_secret_valid(typed_secret):
            self.app_config["server_webhook_secret"] = typed_secret
        else:
            self.log(
                "The webhook secret was not saved: it has a character that "
                "cannot be used in an HTTP header (a line break, a tab or a "
                "character outside Latin-1).")
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save web/LAN server preferences")
            self.log(f"Could not save Web / LAN settings: {e}")

    def _server_is_running(self) -> bool:
        h = self._server_handle
        return h is not None and h.is_running()

    def toggle_server(self) -> None:
        """One-click Start/Stop for the web / LAN server (idempotent).

        The bind + (first-time) model load happen on a daemon thread so
        the UI never freezes; the result is marshalled back onto the Tk
        main thread via post_to_main. Re-entrancy is guarded by
        ``_server_busy`` so a double-click can't start two servers.
        """
        if self._server_busy:
            return
        self._save_server_prefs()
        if self._server_is_running():
            self._stop_server_async()
        else:
            self._start_server_async()

    def _start_server_async(self) -> None:
        import threading as _t

        try:
            port = int(self.server_port_var.get())
        except (tk.TclError, ValueError):
            port = int(self.app_config.get("server_port", 8765))
        # Clamp an out-of-range typed port (0, >65535, negative) to the
        # default, mirroring _save_server_prefs. _save_server_prefs only
        # clamps app_config; it does NOT rewrite server_port_var, so without
        # this the raw typed value would flow into find_available_port, which
        # rejects it and silently binds a random ephemeral port instead.
        port = port if 1 <= port <= 65535 else 8765
        share_lan = bool(self.server_share_lan_var.get())
        token = self.server_token_var.get().strip()
        # The password the server runs with: the phone link must carry this
        # one, not whatever is typed into the field later.
        self._server_token_in_use = token
        https = bool(self.server_https_enabled_var.get())
        webhook_url = self.server_webhook_url_var.get().strip()
        webhook_secret = webhook_secret_from_input(
            self.server_webhook_secret_var.get())
        webhook_header = str(
            self.app_config.get("server_webhook_header_name", "") or "")
        max_upload_mb = int(self.app_config.get("server_max_upload_mb", 512))

        self._server_busy = True
        self.server_toggle_btn.config(state="disabled")
        self.server_status_var.set(_("Starting..."))
        self.server_url_var.set("")

        def _work() -> None:
            try:
                from core.server import HOST_LAN, HOST_LOOPBACK, ServerHandle
                host = HOST_LAN if share_lan else HOST_LOOPBACK
                handle = ServerHandle()
                # Register the handle BEFORE start(). start() can block on a
                # model load ("Starting…"); if the user quits during that
                # window, _shutdown_server_on_exit must already see the handle
                # so it can stop it. The handle is start-idempotent and
                # is_running() stays False until the serve thread is alive, so
                # an early stop() on a not-yet-started handle is a safe no-op.
                self._server_handle = handle
                # auto_port: if the chosen port is busy the handle falls
                # back to a free one rather than failing — we report what
                # it actually bound.
                handle.start(host, port, token, max_upload_mb=max_upload_mb,
                             https=https, webhook_url=webhook_url,
                             webhook_secret=webhook_secret,
                             webhook_header=webhook_header)
                if not handle.is_running():
                    # stop() cancelled the start (the app is exiting).
                    logger.info("Web / LAN server start was cancelled")
                    return
                urls = handle.urls()
                bound_port = handle.port
                self.post_to_main(
                    lambda: self._on_server_started(urls, bound_port, share_lan)
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("Web / LAN server failed to start")
                msg = str(e)
                self.post_to_main(lambda: self._on_server_failed(msg))

        _t.Thread(target=_work, name="server-start", daemon=True).start()

    def _stop_server_async(self) -> None:
        import threading as _t

        handle = self._server_handle
        self._server_busy = True
        self.server_toggle_btn.config(state="disabled")
        self.server_status_var.set(_("Stopping..."))

        def _work() -> None:
            try:
                if handle is not None:
                    handle.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Web / LAN server failed to stop cleanly")
            finally:
                self._server_handle = None
                self.post_to_main(self._on_server_stopped)

        _t.Thread(target=_work, name="server-stop", daemon=True).start()

    def _on_server_started(
        self, urls: list[str], port: int, share_lan: bool
    ) -> None:
        self._server_busy = False
        # Reflect the port the server actually bound (auto-port fallback).
        # save_config can raise OSError/PermissionError (disk full, an
        # antivirus lock on config.json, a read-only profile); that must NOT
        # skip the button-re-enable / status / url updates below — otherwise
        # the server is live but its only toggle stays greyed out and the
        # status is stuck "Starting...". So catch OSError too AND persist
        # only after the UI is restored.
        try:
            if int(self.server_port_var.get()) != port:
                self.server_port_var.set(port)
                self.app_config["server_port"] = port
                try:
                    save_config(self.app_config)
                except OSError:
                    logger.exception("Failed to persist auto-bound server port")
        except (tk.TclError, ValueError):
            pass
        self.server_toggle_btn.config(
            text=_("Stop web access"), state="normal")
        self.server_open_btn.config(state="normal")
        primary = urls[0] if urls else f"http://127.0.0.1:{port}/"
        if share_lan and len(urls) > 1:
            self.server_status_var.set(
                _("Running. On this PC and on your network."))
            self.server_url_var.set(
                _("This PC:  {local_url}\nNetwork:  {network_url}",
                  local_url=urls[0], network_url=urls[1]))
            self._show_phone_link(urls[1], self.__dict__.get("_server_token_in_use", ""))
        elif share_lan:
            # LAN sharing was requested but the network address could not be
            # determined (LAN-IP detection failed — no active network
            # interface, VPN-only, etc.). The server is bound on all
            # interfaces and IS reachable from the network if you know this
            # PC's IP; we just can't display it. Say so distinctly instead of
            # the misleading "Running on this computer." (local-only) line.
            self.server_status_var.set(
                _("Running. Network sharing on, but your network address "
                  "couldn't be detected."))
            self.server_url_var.set(primary)
            self._hide_phone_link()
        else:
            self.server_status_var.set(_("Running on this computer."))
            self.server_url_var.set(primary)
            self._hide_phone_link()
        self.log(f"Web / LAN access started: {primary}")

    def _on_server_failed(self, message: str) -> None:
        self._server_busy = False
        self._server_handle = None
        self.server_toggle_btn.config(text=_("Start web access"), state="normal")
        self.server_open_btn.config(state="disabled")
        self.server_status_var.set(pgettext("web access status", "Off"))
        self.server_url_var.set("")
        self._hide_phone_link()
        messagebox.showerror(
            _("Could not start web access"),
            _("The web / LAN server could not start.\n\n{error}", error=message),
            parent=self,
        )

    def _on_server_stopped(self) -> None:
        self._server_busy = False
        self.server_toggle_btn.config(text=_("Start web access"), state="normal")
        self.server_open_btn.config(state="disabled")
        self.server_status_var.set(pgettext("web access status", "Off"))
        self.server_url_var.set("")
        self._hide_phone_link()
        self.log("Web / LAN access stopped.")

    def _show_phone_link(self, network_url: str, token: str) -> None:
        """Show the QR code of the network address (plus password) under it."""
        from core.phone_link import phone_url, qr_png_base64

        self._phone_link = phone_url(network_url, token)
        # __dict__, not getattr: on a widget-less App (tests) Tk.__getattr__ recurses
        frame = self.__dict__.get("server_qr_frame")
        if frame is None:
            return
        data = qr_png_base64(self._phone_link, scale=max(3, px(4)))
        if data:
            self._phone_qr_image = tk.PhotoImage(data=data)  # keep a reference
            self.server_qr_label.config(image=self._phone_qr_image)
        else:
            self._phone_qr_image = None
            self.server_qr_label.config(image="")
        steps = (_("Scan this code with your phone's camera, or open the network address in its "
                   "browser. The phone must be on the same Wi-Fi network as this PC.")
                 if data else
                 _("Open the network address in your phone's browser. The phone must be on the "
                   "same Wi-Fi network as this PC."))
        if network_url.startswith("https:"):
            steps += " " + _("With HTTPS on, the phone first warns about the certificate: this "
                             "app made it itself, so continue to the page.")
        if token:
            steps += " " + _("The code and the copied link include your access password: show "
                             "them only to people who may use this page.")
        self.server_qr_note_var.set(steps)
        frame.pack(**rtl_layout.pack_kw(frame, anchor="w", pady=(0, 12), after=self.server_url_label))

    def _hide_phone_link(self) -> None:
        self._phone_link = ""
        self._phone_qr_image = None
        frame = self.__dict__.get("server_qr_frame")
        if frame is not None:
            self.server_qr_label.config(image="")
            frame.pack_forget()

    def copy_phone_link(self) -> None:
        """Put the phone link (network address, plus the password if set) on the clipboard."""
        link = self.__dict__.get("_phone_link", "")
        if not link:
            return
        self.clipboard_clear()
        self.clipboard_append(link)
        self.log(_("Phone link copied."))

    def copy_mcp_setup(self) -> None:
        """Copy the ``claude mcp add`` command for this app's MCP endpoint.

        The port is the one the server is bound to while it runs (a free
        port the app picked because the chosen one was busy), else the port
        chosen on the Web / LAN tab. The password stays a placeholder: the
        clipboard must never carry the real access password.
        """
        # __dict__, not getattr: on a widget-less App (tests) Tk.__getattr__ recurses
        handle = self.__dict__.get("_server_handle")
        if handle is not None and handle.is_running():
            port = int(handle.port or 0)
            scheme = "https" if handle.https else "http"
        else:
            try:
                port = int(self.server_port_var.get())
            except (tk.TclError, ValueError):
                try:
                    port = int(self.app_config.get("server_port", 8765))
                except (TypeError, ValueError):
                    port = 8765  # junk in the config file: use the default port
            scheme = "https" if bool(self.server_https_enabled_var.get()) else "http"
        port = port if 1 <= port <= 65535 else 8765
        command = (
            f"claude mcp add --transport http whisper "
            f"{scheme}://127.0.0.1:{port}/mcp "
            '--header "Authorization: Bearer <access password>"')
        self.clipboard_clear()
        self.clipboard_append(command)
        self.log(_("MCP setup command copied."))

    def open_server_in_browser(self) -> None:
        """Open the loopback URL in the default browser."""
        handle = self._server_handle
        if handle is None or not handle.is_running():
            return
        import webbrowser
        urls = handle.urls()
        if urls:
            try:
                webbrowser.open(urls[0])
            except Exception:  # noqa: BLE001
                logger.exception("Could not open browser")

    def active_server_jobs(self) -> int:
        """Waiting or running jobs that came in through the built-in server (0 without one)."""
        handle = self.__dict__.get("_server_handle")
        if handle is None:
            return 0
        try:
            return int(handle.active_jobs())
        except Exception:  # noqa: BLE001 - a failed probe must not block the exit
            logger.exception("Could not count the active server jobs")
            return 0

    def _shutdown_server_on_exit(self) -> None:
        """Best-effort synchronous stop of the server during app exit."""
        handle = self._server_handle
        if handle is None:
            return
        try:
            handle.stop(timeout=3.0)
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping web / LAN server on exit")
        self._server_handle = None

    # Rendering ---------------------------------------------------------------
    def fmt_time(self, t: Any) -> str:
        if not getattr(t, "start_time", None):
            return ""
        # Freeze at end_time once the task is in a terminal state
        # (finished / cancelled / error). Before this, the Elapsed
        # column kept incrementing forever — the user never saw
        # "this file took 1m 22s", just a number that grew while
        # they were doing something else.
        end = getattr(t, "end_time", None)
        if end is not None:
            s = end - t.start_time
        else:
            s = time.time() - t.start_time
        s = max(0.0, s)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        return f"{h:02}:{m:02}:{sec:02}"

    def _download_row_progress(self, task: Any) -> float:
        # While an auto-transcribe runs, the download row mirrors the
        # linked transcription's live progress (else it sits at 100%).
        tr = getattr(task, "transcription_task", None)
        if getattr(task, "make_subbed_video", False):
            from app.services.subbed_video import rising_chain_progress
            stage = tr.progress if task.status == "transcribing" and tr is not None else (
                getattr(task, "burn_progress", 0.0) if task.status == "burning" else task.progress
            )
            return rising_chain_progress(task, stage)
        if task.status == "transcribing" and tr is not None:
            return tr.progress
        return task.progress

    def _row_progress_text(self, status: str, progress: float) -> str:
        """Progress text for a queue row: the real bar, or an indeterminate
        marquee while the row is working but has no percentage yet (e.g.
        during the model load before the first segment)."""
        from app.widgets.tabs import marquee_cell, progress_cell

        if status in ("running", "transcribing", "burning") and (progress or 0) <= 0:
            return marquee_cell(getattr(self, "_anim_frame", 0), progress)
        return progress_cell(progress)

    def _ensure_animation(self) -> None:
        """Start the marquee loop if any row is working without a real %."""
        if getattr(self, "_anim_running", False):
            return
        needs = any(
            t.status == "running" and (t.progress or 0) <= 0 for t in self.queue
        ) or any(
            d.status in ("running", "transcribing", "burning")
            and (self._download_row_progress(d) or 0) <= 0
            for d in self.download_queue
        )
        if needs:
            self._anim_running = True
            self._animate_tick()

    def _animate_tick(self) -> None:
        from app.widgets.tabs import marquee_cell

        self._anim_frame = getattr(self, "_anim_frame", 0) + 1
        bar = marquee_cell(self._anim_frame)
        active = False
        for item_id, t in list(getattr(self, "row_map", {}).items()):
            if t.status == "running" and (t.progress or 0) <= 0:
                active = True
                try:
                    self.tree.set(item_id, "progress", bar)
                except tk.TclError:
                    pass
        for item_id, d in list(getattr(self, "download_row_map", {}).items()):
            if d.status in ("running", "transcribing", "burning") and (self._download_row_progress(d) or 0) <= 0:
                active = True
                try:
                    self.download_tree.set(item_id, "progress", bar)
                except tk.TclError:
                    pass
        if active:
            self.after(250, self._animate_tick)
        else:
            self._anim_running = False

    def refresh(self) -> None:
        from app.widgets.tabs import fit_tree_cell, queue_language_cell, task_status_label

        # Snapshot the SELECTED tasks (by identity) before we tear the tree
        # down: refresh() runs every 500ms via loop(), and a plain
        # delete()+re-insert() assigns brand-new iids, wiping the Treeview
        # selection. With the selection gone _update_queue_action_bar() below
        # would see nothing selected and disable every Pause/Resume/Cancel/
        # Re-run/Remove button ~0.5s after the user clicks a row — making the
        # action bar unusable. We restore the selection onto the new iids so
        # it survives the rebuild.
        prev_selected = self._selected_tasks()
        # The keyboard-focus row is lost the same way: Up/Down would restart from the top.
        prev_focused = self.row_map.get(self.tree.focus())
        rows: list[tuple[Any, tuple[str, ...], tuple[str, ...]]] = []
        for t in self.queue:
            lang = getattr(t, "detected_language", "") or ""
            # No speech: the detection guessed from noise ("English (not sure)" for a horse);
            # the history row drops it the same way.
            lang_str = ("" if getattr(t, "no_speech", False)
                        else queue_language_cell(lang, getattr(t, "language_probability", None)))
            name = os.path.basename(t.file_path)
            tags = script_fonts.tree_row_tags(self.tree, name, language=t.language or lang)
            values = (
                ltr_base(fit_tree_cell(self.tree, "file", name, tuple(tags))),
                task_status_label(t),
                self._row_progress_text(t.status, t.progress),
                speed_cell_text(t),
                lang_str,
                self.fmt_time(t),
            )
            rows.append((t, values, tuple(tags)))
        # Rebuild only when a row, its text or its tags changed. delete()+insert() on a
        # visible Treeview repaints it, so doing it every 500 ms kept an idle Queue tab
        # busy (about 36% of a core on macOS, measured). ``_queue_rows_sig`` is what the
        # tree currently shows; the child count guards against the tree having been emptied.
        if (
            not _same_rows(getattr(self, "_queue_rows_sig", None), rows)
            or len(self.tree.get_children()) != len(rows)
        ):
            self.tree.delete(*self.tree.get_children())
            self.row_map = {}
            for t, values, tags in rows:
                item_id = self.tree.insert("", "end", values=values, tags=tags)
                self.row_map[item_id] = t
            self._queue_rows_sig = rows
            # Re-select the same task objects on their new iids (no-op when the
            # selection was empty or its tasks left the queue).
            restore = _iids_for_tasks(self.row_map, prev_selected)
            if restore:
                self.tree.selection_set(restore)
            if prev_focused is not None:
                focus_iids = _iids_for_tasks(self.row_map, [prev_focused])
                if focus_iids:
                    self.tree.focus(focus_iids[0])
        self._auto_select_running_row()
        # Empty-state hint visibility — show when the queue is empty,
        # hide once there is at least one task. Kept here (rather than
        # in tabs.py) because refresh is the choke point for queue
        # changes, so the placeholder can't drift out of sync.
        if hasattr(self, "queue_empty_label"):
            # Change the geometry only when the label's visibility changes: re-packing an
            # already packed widget every 500 ms made an idle Queue tab repaint all the
            # time (about 36% of a core on macOS, measured).
            shown = bool(self.queue_empty_label.winfo_manager())
            if self.queue:
                if shown:
                    self.queue_empty_label.pack_forget()
            elif not shown:
                self.queue_empty_label.pack(fill="x", pady=(2, 0))
        sync_transcribe_empty_state(self)
        sync_ready = _inst_attr(self, "sync_transcribe_ready")  # absent on test doubles
        if sync_ready is not None:
            sync_ready()
        # Reflect work-in-progress in the window title so users with
        # the app minimised see "Whisper — 34% transcribing foo.mp4"
        # in their taskbar / Alt-Tab.
        self._refresh_window_title()
        win_taskbar.sync(self)   # Windows taskbar progress/badge/flash (no-op elsewhere)
        self._ensure_animation()
        # Recompute the action-bar enabled state AFTER the selection is
        # restored: refresh rebuilds the tree every tick, so a row whose
        # status flipped (e.g. running->finished) must not leave the buttons
        # reflecting the old status, and a still-selected row must keep them
        # enabled.
        self._update_queue_action_bar()

    def _auto_select_running_row(self) -> None:
        """Select a job when it starts, so Pause and Cancel work without finding the row first.

        The action bar follows the selection only, and nothing selected a running job, so
        both buttons stayed grey while it ran (click-through test, 2026-10-21). Only when
        nothing is selected, or only ended rows (a finished row left selected kept Pause and
        Cancel grey for the next job: screenshot review, 2026-10-21), and exactly one job
        runs, once per job: a waiting/running/paused row the user picked, or a selection the
        user cleared, is left alone.
        """
        picked = _select_the_running_task(self.tree, self.row_map, self.queue,
                                          getattr(self, "_auto_selected_task", None))
        if picked is not None:
            self._auto_selected_task = picked

    def _auto_select_running_download(self) -> None:
        """The Download tab's copy of _auto_select_running_row: Pause, Cancel and Open stayed
        grey while a download ran until the user found its row (round-2 screenshot critics,
        2026-10-21). The row stays selected when it finishes, so Open works at once."""
        picked = _select_the_running_task(self.download_tree, self.download_row_map,
                                          self.download_queue,
                                          getattr(self, "_auto_selected_download", None))
        if picked is not None:
            self._auto_selected_download = picked

    def refresh_download_queue(self) -> None:
        from app.widgets.tabs import status_label

        # Snapshot the SELECTED tasks (by identity) before tearing the tree
        # down -- same rationale as refresh() above: a plain delete()+
        # re-insert() assigns brand-new iids, wiping the selection and
        # disabling the Pause/Resume/Cancel action bar mid-download, since
        # this runs on every drained download event (frequent while a
        # download is active), not just periodically.
        prev_selected = self._selected_downloads()
        self.download_tree.delete(*self.download_tree.get_children())
        self.download_row_map = {}
        for task in self.download_queue:
            # While auto-transcribe runs, mirror the linked transcription's
            # live progress on the download row (otherwise a finished
            # download would sit at 100% and look idle while it transcribes).
            prog = self._download_row_progress(task)
            item_id = self.download_tree.insert(
                "",
                "end",
                values=(
                    ltr_base(task.title),
                    task.url,
                    task.format_label,
                    status_label(task.status),
                    self._row_progress_text(task.status, prog),
                    self.fmt_time(task),
                ),
                tags=script_fonts.tree_row_tags(
                    self.download_tree, task.title,
                    language=task.subtitle_lang or task.detected_language,
                ),
            )
            self.download_row_map[item_id] = task
        # Re-select the same task objects on their new iids (no-op when the
        # selection was empty or its tasks left the queue).
        restore = _iids_for_tasks(self.download_row_map, prev_selected)
        if restore:
            self.download_tree.selection_set(restore)
        self._auto_select_running_download()
        self._refresh_window_title()
        self._ensure_animation()
        self._update_download_action_bar()

    # -- UX helpers (Phase v0.7.1 — user-friendly result surfacing) ----------

    def _refresh_window_title(self) -> None:
        """Update the Tk window title so the taskbar / Alt-Tab reflects state.

        Idle: "Whisper Transcriber Suite".
        One running task: "Whisper Transcriber Suite — 34% transcribing foo.mp4".
        Multiple running: "Whisper Transcriber Suite — 2 tasks (avg 41%)".
        While Work offline is on, the base ends in "— Work offline".
        """
        base = self._base_title
        if offline.is_offline():
            base = _("{title} — Work offline", title=base)
        running = [t for t in self.queue if t.status == "running"]
        running_dl = [
            d for d in self.download_queue if d.status == "running"
        ]
        # Sync the tray icon colour to current activity.
        if self.tray is not None:
            try:
                self.tray.set_active(bool(running or running_dl))
            except Exception:  # noqa: BLE001
                pass
        if not running and not running_dl:
            self.title(base)
            return
        if running and not running_dl and len(running) == 1:
            t = running[0]
            self.title(_("{title} — {percent}% transcribing {name}", title=base,
                         percent=t.progress, name=os.path.basename(t.file_path)))
            return
        if running_dl and not running and len(running_dl) == 1:
            d = running_dl[0]
            self.title(_("{title} — {percent}% downloading {name}", title=base,
                         percent=d.progress, name=d.title[:40] if d.title else d.url[:40]))
            return
        total = len(running) + len(running_dl)
        all_p = [t.progress for t in running] + [d.progress for d in running_dl]
        avg = sum(all_p) // len(all_p) if all_p else 0
        self.title(ngettext("{title} — {n} job running ({percent}%)",
                            "{title} — {n} jobs running ({percent}%)", total,
                            title=base, percent=avg))

    def show_last_result(self, task: "TranscriptionTask") -> None:
        """Populate the Transcribe-tab Last Result card.

        Called by TranscriptionService.finish_task when a job
        completes successfully. Lists every output file that
        actually exists on disk next to the input, with sizes and
        one-click "Open" buttons. Also offers a single "Open folder"
        button as a shortcut.
        """
        from app.widgets.tabs import _fmt_bytes, capped_rows

        if not hasattr(self, "last_result_frame"):
            return

        try:
            self.last_result_empty_label.pack_forget()
        except Exception:  # noqa: BLE001
            pass

        # Wipe any previous result card body and rebuild from scratch
        # — simpler than diff-updating a handful of widgets.
        for child in list(self.last_result_body.winfo_children()):
            child.destroy()
        try:
            self.last_result_body.pack_forget()
        except Exception:  # noqa: BLE001
            pass

        base, _unused = os.path.splitext(task.file_path)
        # The outputs' folder, not the source's: an output template can
        # write somewhere else, and "Open folder" must show the new files.
        folder = task_output_folder(task)
        # Prefer the exact files the worker reported writing — that
        # covers docx/pdf/md and the de-duped "name (1).srt" form the
        # hard-coded candidate list below would miss (a docx-only run
        # used to show "no output files found" despite a clean write).
        written = getattr(task, "output_paths", None)
        no_speech = bool(getattr(task, "no_speech", False))
        # No speech: the worker wrote nothing and says so with an empty list; the guess below
        # would list files an earlier run left next to the recording.
        if written or (written is not None and no_speech):
            existing = [p for p in written if os.path.isfile(p)]
        else:
            candidates = [
                f"{base}.{ext}"
                for ext in ("srt", "json", "vtt", "tsv", "txt", "lrc", "docx", "pdf", "md")
            ]
            existing = [p for p in candidates if os.path.isfile(p)]

        ttk.Label(
            self.last_result_body,
            # A tick read as success over empty files (round-2 screenshot critics, 2026-10-21).
            text=ltr_base(f"{'⚠' if no_speech else '✓'} {os.path.basename(task.file_path)}"),
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w")
        speed_line = task_summary_text(task)
        if speed_line:
            ttk.Label(
                self.last_result_body,
                text=speed_line,
                foreground=tokens.themed(tokens.TEXT_MUTED),
            ).pack(anchor="w", pady=(2, 0))
        if no_speech:
            ttk.Label(
                self.last_result_body,
                text=_("No speech was recognised in this file, so no transcript was saved."),
                foreground=tokens.themed(tokens.WARNING_TEXT),
            ).pack(anchor="w", pady=(2, 0))
            ttk.Label(
                self.last_result_body,
                text=_("Check that the recording has sound. If the speech is quiet or in "
                       "another language, choose that language and transcribe it again."),
                foreground=tokens.themed(tokens.WARNING_TEXT),
            ).pack(anchor="w")
        if existing:
            ttk.Label(
                self.last_result_body,
                text=ngettext("Saved {n} output file in {folder}",
                              "Saved {n} output files in {folder}", len(existing), folder=folder),
                foreground=tokens.themed(tokens.TEXT_MUTED),
            ).pack(anchor="w", pady=(2, 6))

            files_frame = ttk.Frame(self.last_result_body)
            files_frame.pack(fill="x")

            def _fill_rows(rows_parent: "ttk.Frame") -> None:
                from app.widgets.tabs import elide_middle

                for path in existing:
                    row = ttk.Frame(rows_parent)
                    row.pack(fill="x", pady=1)
                    size = _fmt_bytes(os.path.getsize(path))
                    # Open sits right after its file (it was at the far right edge, ~1700 px
                    # away), and a long name is cut in the middle so the button and the
                    # extension stay in sight (screenshot reviews, 2026-10-21).
                    ttk.Label(
                        row, text=ltr_base(f"• {elide_middle(os.path.basename(path), 64)}  ({size})")
                    ).pack(side="left")
                    ttk.Button(
                        row, text=pgettext("file", "Open"),
                        command=lambda p=path: self._open_file(p),
                    ).pack(side="left", padx=(10, 0))

            # A long list scrolls inside the card: it must never grow until the drop
            # zone and the log have no room left.
            capped_rows(files_frame, len(existing), _fill_rows)
        elif not no_speech:  # no speech: no files is the expected result, said above
            ttk.Label(
                self.last_result_body,
                text=_("(no output files were found on disk — re-run the task?)"),
                foreground=tokens.themed(tokens.DANGER_TEXT),
            ).pack(anchor="w")

        button_row = ttk.Frame(self.last_result_body)
        button_row.pack(anchor="w", pady=(8, 0))
        ttk.Button(
            button_row,
            text=folder_action_label(
                _("Open folder"), _("Open Folder in Finder"), existing[0] if existing else None),
            command=lambda: self._open_folder(
                folder, select=existing[0] if existing else None),
        ).pack(side="left")
        # "View transcript" launches the in-app viewer with the JSON
        # next to the source media (or the file picker if no JSON
        # found). Discoverable single click into the new viewer.
        # Nothing to view, share or time when no speech was found: the files are empty.
        json_output = None if no_speech else pick_transcript_json(existing, task.file_path)
        if json_output is not None:
            ttk.Button(
                button_row, text=_("View transcript"),
                command=lambda jp=json_output: self.open_transcript_viewer_for(
                    task.file_path, jp, task.language or task.detected_language
                ),
            ).pack(side="left", padx=(8, 0))
            ttk.Button(
                button_row, text=translate(share_page.BUTTON_TEXT),
                command=lambda jp=json_output: self._save_shareable_page_for(
                    task.file_path, jp, task.language or task.detected_language
                ),
            ).pack(side="left", padx=(8, 0))
        # Windows only: open the best subtitle file in Subtitle Edit
        # (waveform editor) for fine timing work.
        subtitle_output = None if no_speech else subtitle_edit.pick_subtitle_file(existing)
        if subtitle_output is not None and subtitle_edit.is_supported():
            ttk.Button(
                button_row, text=translate(subtitle_edit_ui.BUTTON_TEXT),
                command=lambda sp=subtitle_output: subtitle_edit_ui.open_in_subtitle_edit(
                    self, self.app_config, sp
                ),
            ).pack(side="left", padx=(8, 0))

        rtl_layout.mirror_tree(self.last_result_body)  # built fresh above, so exactly once
        self.last_result_body.pack(fill="both", expand=True)
        # Chime + log so the user notices even if they're on another
        # tab. The bell is one short cross-platform beep; suppressed
        # when the View > Chime on completion toggle is off.
        if getattr(self, "chime_on_complete_var", None) is not None:
            try:
                if self.chime_on_complete_var.get():
                    self.bell()
            except Exception:  # noqa: BLE001
                pass
        # Native toast via the tray controller — visible even when the
        # window is minimised. Falls through silently if pystray /
        # Pillow aren't installed (tray controller is None) or the
        # user disabled tray support.
        if self.tray is not None:
            if no_speech:  # not "Wrote 2 output files" over empty files
                body = _("No speech was found in {name}", name=os.path.basename(task.file_path))
            else:
                body = ngettext("Wrote {n} output file for {name}", "Wrote {n} output files for {name}",
                                len(existing), name=os.path.basename(task.file_path))
            try:
                self.tray.notify(_("Whisper Transcriber Suite — transcription done"), body)
            except Exception:  # noqa: BLE001
                pass
        # macOS has no tray: a desktop notification while the window is in the background.
        desktop_alert.job_done(self, task, len(existing))
        self.log(
            f"Done: {os.path.basename(task.file_path)} → "
            f"{len(existing)} file(s) in {folder}"
        )
        # No jump to the Transcribe tab: from the Queue it took the tab away from a user who had
        # just clicked a row (deep review, 2026-10-21). The notification above says it is done.

    def _open_file(self, path: str) -> None:
        """Open a single file with the OS default handler.

        The outcome is checked on every platform: with no app set for the file type the file is
        shown in its folder with a notice (see ``app.widgets.platform.open_file``); any other
        failure shows an error.
        """
        _open_file_helper(path, parent=self)

    def _install_tray(self) -> None:
        """Bring up the system-tray icon if pystray + Pillow are present.

        The icon's right-click menu offers Show/Hide/Exit; the icon
        colour mirrors active/idle state. Failing imports silently
        leave ``self.tray = None`` so the rest of the app still
        boots in environments without tray support.
        """
        try:
            tray = TrayController(self)
            if not tray.is_supported():
                logger.info("Tray icon unavailable: pystray or Pillow missing")
                self.tray = None
                return
            tray.start()
            self.tray = tray
            logger.info("Tray icon installed")
        except Exception as e:  # noqa: BLE001
            logger.warning("Tray icon failed to install: %s", e)
            self.tray = None

    def _restart_watched_folder(self) -> None:
        """(Re)start the watched-folder watcher from current config.

        The watcher class lives in ``core.watcher``; if the
        ``watchdog`` Python package isn't installed the call no-ops.
        Files dropped into the watched folder are auto-enqueued onto
        the transcription queue via a Tk-safe ``after()`` hop.
        """
        # Tear down any previous watcher so we don't leak observer
        # threads when the user picks a new folder in Advanced.
        if self._folder_watcher is not None:
            try:
                self._folder_watcher.stop()
            except Exception:  # noqa: BLE001
                pass
            self._folder_watcher = None

        if not bool(self.app_config.get("watched_folder_enabled", False)):
            return
        folder = str(self.app_config.get("watched_folder") or "").strip()
        if not folder or not os.path.isdir(folder):
            self.log(
                f"Watched folder ignored — not a directory: {folder!r}"
            )
            return

        def _on_new_file(path: str) -> None:
            # watchdog calls back from its own thread — DON'T touch Tk
            # from here. Calling self.after() off-thread raises
            # RuntimeError on Python 3.14 (and is undefined behaviour
            # on earlier 3.x). Instead push the path into a
            # thread-safe queue that the Tk main loop drains via
            # _drain_watched_paths.
            if self._closing:
                return
            try:
                self._watched_path_queue.put_nowait(path)
            except Exception:  # noqa: BLE001
                pass

        try:
            watcher = FolderWatcher(folder, _on_new_file)
            watcher.start()
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not start folder watcher: {e}")
            return
        self._folder_watcher = watcher
        self.log(f"Watching folder for new media: {folder}")

    def _drain_watched_paths(self) -> None:
        """Drain the cross-thread queue of watched-folder paths.

        Runs on the Tk main thread (scheduled via after()). watchdog
        callbacks push into ``_watched_path_queue`` from their worker
        thread; this method dequeues + hands each path to
        ``_enqueue_watched_file`` (which is now safe because we're
        on the Tk thread). Re-arms itself every 250 ms while the
        app is alive.

        ``_enqueue_watched_file`` is wrapped in its own try/except so
        one path that keeps raising (e.g. a file the OS holds locked)
        can't stall every other path queued behind it on every single
        250 ms tick -- it used to share one try/except with the
        ``get_nowait()`` loop, so any exception from the enqueue call
        was caught the same way as the intended ``Empty``-means-stop
        signal, ending that tick's drain early.
        """
        if self._closing:
            return
        while True:
            try:
                path = self._watched_path_queue.get_nowait()
            except Empty:
                break
            try:
                self._enqueue_watched_file(path)
            except Exception:  # noqa: BLE001
                logger.exception("Watched-folder enqueue failed for %r", path)
        if not self._closing:
            try:
                self.after(250, self._drain_watched_paths)
            except Exception:  # noqa: BLE001
                pass

    # Update check ------------------------------------------------------------
    def _maybe_quiet_update_check(self) -> None:
        """Fire the silent launch-time GitHub update check, if eligible.

        Runs on the Tk main thread (scheduled via ``after``). Gated by
        ``update_check_enabled`` (and the ``WTS_DISABLE_UPDATER`` variable)
        and a once-per-day throttle keyed on ``last_update_check`` (an ISO
        date). When eligible, the date is stamped immediately (so a second
        launch the same day won't re-check) and the network call runs on a
        daemon thread. A found update shows the quiet bar at most once per
        launch — NOTHING appears when up to date, offline, or on a private
        repo. Each call books the next one a day later, so an app left open
        for days still hears about a new version.
        """
        if self._closing:
            return
        if self._quick_start_open:
            # The quick start window promises no network traffic while it is
            # open; check again once it has closed.
            self.after(4000, self._maybe_quiet_update_check)
            return
        try:
            self.after(_UPDATE_RECHECK_MS, self._maybe_quiet_update_check)
        except Exception:  # noqa: BLE001
            logger.debug("Could not book the next update check", exc_info=True)
        try:
            from core import updates as _updates
            if not _updates.automatic_check_enabled(self.app_config):
                return
            if offline.is_offline():
                offline.skipped("the automatic update check")
                return  # not stamped: the next daily call (or a restart) checks
            today = _today().isoformat()
            if (self.app_config.get("last_update_check") or "") == today:
                return  # already checked today
            # Stamp the date up-front so we throttle even if the check
            # races / fails; persist via save_config so it survives a
            # restart.
            self.app_config["last_update_check"] = today
            try:
                save_config(self.app_config)
            except Exception:  # noqa: BLE001
                logger.debug("Could not persist last_update_check", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("Quiet update-check gate failed", exc_info=True)
            return
        self._run_update_check(manual=False)

    def _check_for_updates_manual(self) -> None:
        """Help-menu "Check for updates..." — always runs, reports all cases."""
        if not self.ensure_online("Checking for updates"):
            return
        self._run_update_check(manual=True)

    def _run_update_check(self, *, manual: bool) -> None:
        """Run core.updates.check_for_update on a daemon thread.

        The network call happens off the Tk thread (it can block for up
        to the urllib timeout); the result is marshalled back via
        :meth:`post_to_main` so all widget work stays on the main
        thread. ``manual`` controls whether the "up to date" /
        "couldn't reach the server" cases are surfaced (manual) or
        swallowed (the quiet launch check).
        """

        def _worker() -> None:
            from core import updates as _updates
            info = _updates.check_for_update()
            self.post_to_main(lambda: self._on_update_result(info, manual=manual))

        from core._threads import safe_thread
        safe_thread(_worker, name="update-check")

    def _on_update_result(self, info: object, *, manual: bool) -> None:
        """Act on an update-check result (main thread).

        ``info`` is a ``core.updates.UpdateInfo`` or ``None`` (typed as
        ``object`` here to keep this glue free of a hard import at the
        annotation site). A newer release shows the quiet bar (never a
        dialog) when ``core.updates.notice_level`` allows it, at most once
        per launch; otherwise only the passive signs change. A manual check
        always shows the bar for a newer release (asking first when the user
        skipped that version) and also reports up-to-date / unreachable; the
        quiet launch check stays silent in those cases.
        """
        if self._closing:
            return
        from core import updates as _updates

        if info is None:
            if manual:
                notify(
                    self,
                    _("Could not reach the update server. Please check your "
                      "internet connection and try again later."),
                    "warning",
                )
            return

        if not isinstance(info, _updates.UpdateInfo):  # defensive; never expected
            return

        if not info.is_newer:
            # A newer release seen earlier may have been withdrawn: remember
            # the release that really is the latest, so the Help-menu dot and
            # the bar stop pointing at the withdrawn one.
            seen = str(self.app_config.get("update_latest_seen") or "")
            if (
                seen
                and _updates.is_newer(seen, info.latest_tag)
                and _updates.note_latest(self.app_config, info.latest_tag)
            ):
                # Nothing to update to any more: drop the withdrawn release
                # and its bar, so no button acts on it.
                self._latest_update = None
                if self._update_bar is not None and self._update_bar.visible:
                    self._hide_update_bar()
                self._save_update_prefs()
                self._refresh_update_signs()
            if manual:
                notify(
                    self,
                    _("You're on the latest version ({version}).",
                      version=_updates.version_label(_APP_VERSION)),
                    "success",
                )
            return

        if not manual:
            kind = self._install_kind()
            if (
                _updates.kind_has_a_release_file(kind)
                and _updates.pick_asset(kind, info.assets) is None
            ):
                # The file for this kind of install is not uploaded yet (the
                # macOS files sometimes follow the Windows ones): stay silent
                # until a later check finds it.
                logger.info("Update %s found, but not its file for %s yet", info.latest_tag, kind)
                return

        self._latest_update = info
        changed = _updates.note_latest(self.app_config, info.latest_tag)
        version = _updates.version_label(info.latest_tag)
        if manual:
            if _updates.is_skipped(self.app_config, info.latest_tag):
                if messagebox.askyesno(
                    _("Check for updates"),
                    _("Version {version} is available. You chose to skip it.\n\n"
                      "Show it again?", version=version),
                    parent=self,
                ):
                    _updates.stop_skipping(self.app_config)
                    changed = True
                else:
                    if changed:
                        self._save_update_prefs()
                    return
            if changed:
                self._save_update_prefs()
            self._show_update_bar(info)
        else:
            if changed:
                self._save_update_prefs()
            level = _updates.notice_level(
                self.app_config, _APP_VERSION, _today(),
            )
            bar_visible = self._update_bar is not None and self._update_bar.visible
            # Once per launch; a bar still on screen is refreshed instead, so
            # its text names the version its buttons now act on.
            if level == _updates.NOTICE_BAR and (
                bar_visible or not self._update_bar_shown_this_launch
            ):
                if bar_visible or not self._jobs_active():
                    self._show_update_bar(info)
                else:
                    # Never while a transcription or download runs: the bar
                    # waits for an idle queue (the Help-menu dot shows now).
                    self._book_update_bar_retry()
        self._refresh_update_signs()

    # Update notice: bar, buttons and passive signs ----------------------------
    def _install_kind(self) -> str:
        from core import updates as _updates
        from core.hub import resolve_app_dir
        return _updates.detect_install_kind(resolve_app_dir())

    def _save_update_prefs(self) -> None:
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save the update-notice state")
            self.log(f"Could not save the update-notice choice: {e}")

    def _show_update_bar(self, info: Any) -> None:
        """Show (or refresh) the quiet bar above the tabs. Never moves the focus."""
        from core import updates as _updates
        bar = self._update_bar
        if bar is None:
            from app.widgets.update_bar import UpdateBar
            bar = UpdateBar(
                self,
                on_whats_new=self._update_whats_new,
                on_download=self._update_download,
                on_later=self._update_later,
                on_skip=self._update_skip,
            )
            rtl_layout.mirror_tree(bar)
            self._update_bar = bar
        bar.show(
            _updates.bar_text(info.latest_tag, _APP_VERSION, info.headline),
            before=self.nb,
        )
        self._update_bar_shown_this_launch = True

    def _hide_update_bar(self) -> None:
        if self._update_bar is not None:
            self._update_bar.hide()

    def _book_update_bar_retry(self) -> None:
        """Look again for an idle queue later (one timer at a time)."""
        if _inst_attr(self, "_update_bar_retry_id") is not None:
            return
        self._update_bar_retry_id = self.after(_UPDATE_BAR_RETRY_MS, self._retry_update_bar)

    def _retry_update_bar(self) -> None:
        """Show the bar a running job held back, once no job is queued or running.

        Every rule is checked again, because the user may have turned the check
        off, gone offline, skipped or snoozed the version (Help menu) or seen
        the bar through a manual check in the meantime.
        """
        self._update_bar_retry_id = None
        if self._closing or self._update_bar_shown_this_launch:
            return
        info = self._latest_update
        if info is None:
            return
        from core import updates as _updates
        if not _updates.automatic_check_enabled(self.app_config) or offline.is_offline():
            return
        if _updates.notice_level(self.app_config, _APP_VERSION, _today()) != _updates.NOTICE_BAR:
            return
        if self._jobs_active():
            self._book_update_bar_retry()
            return
        self._show_update_bar(info)

    # Gentle star invitation (core.star_invite) -------------------------------
    def _star_save(self) -> None:
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save the star-invitation state")
            self.log(f"Could not save the star-invitation choice: {e}")

    def _star_stamp_first_run(self) -> None:
        from core import star_invite
        if star_invite.ensure_first_run(self.app_config, _today()):
            self._star_save()

    def _jobs_active(self) -> bool:
        """True while a transcription or download is queued or running."""
        return any(
            t.status in ("running", "waiting") for t in self.queue
        ) or any(
            d.status in ("running", "transcribing", "burning", "waiting")
            for d in self.download_queue
        )

    def note_job_success(self) -> None:
        """One transcription finished well: count it, maybe show the star bar.

        Called from the task-done handler (main thread) after the queue rows
        are final, so the finished job itself is no longer "running".
        """
        from core import star_invite
        if self._closing:
            return
        today = _today()
        try:
            star_invite.record_success(self.app_config, today)
            if star_invite.should_invite(
                self.app_config, today,
                job_running=self._jobs_active(), offline=offline.is_offline(),
            ):
                star_invite.mark_shown(self.app_config, today)
                self._show_star_bar()
            self._star_save()
        except Exception:  # noqa: BLE001 - a counter must never break a finished job
            logger.exception("Star invitation check failed")

    def _show_star_bar(self) -> None:
        """Show the quiet bar above the tabs. Never moves the focus."""
        bar = self._star_bar
        if bar is None:
            from app.widgets.update_bar import StarBar
            bar = StarBar(
                self,
                on_open=self._star_open,
                on_not_now=self._hide_star_bar,
                on_never=self._star_never,
            )
            rtl_layout.mirror_tree(bar)
            self._star_bar = bar
        bar.show(translate(_STAR_BAR_TEXT), before=self.nb)

    def _hide_star_bar(self) -> None:
        bar = _inst_attr(self, "_star_bar")
        if bar is not None:
            bar.hide()

    def _star_open_page(self) -> None:
        import webbrowser

        from core import star_invite
        webbrowser.open(star_invite.REPO_URL)

    def _star_open(self) -> None:
        """"Open GitHub page": the repo page, then no more invitations."""
        from core import star_invite
        self._star_open_page()
        star_invite.decline(self.app_config)
        self._star_save()
        self._hide_star_bar()

    def _star_never(self) -> None:
        from core import star_invite
        star_invite.decline(self.app_config)
        self._star_save()
        self._hide_star_bar()

    # yt-dlp update bar (core.yt_dlp_update) ---------------------------------
    def _refresh_yt_dlp_versions(self) -> None:
        if self._closing:
            return

        def _work() -> None:
            try:
                from core import yt_dlp_update
                yt_dlp_update.refresh_state_if_stale()
            except Exception:  # noqa: BLE001
                logger.exception("Could not refresh the yt-dlp versions")

        from core._threads import safe_thread
        safe_thread(_work, name="yt-dlp-versions")

    def _ensure_yt_dlp_bar(self) -> Any:
        bar = self._yt_dlp_bar
        if bar is None:
            from app.widgets.update_bar import DownloaderUpdateBar
            bar = DownloaderUpdateBar(
                self, on_update=self._yt_dlp_update_now, on_dismiss=self._yt_dlp_bar_dismiss,
            )
            rtl_layout.mirror_tree(bar)
            self._yt_dlp_bar = bar
        return bar

    def offer_yt_dlp_update(self, reason: str = "") -> None:
        """Offer to update the video downloader (main thread).

        Called after a download or a format lookup failed in a way an
        outdated yt-dlp fails (core.yt_dlp_update.should_offer_update). Not
        in mode "never", not when this copy of the app cannot update yt-dlp
        (no single-file build to copy or download: a Mac older than 10.15, or
        a source run without a bundled yt-dlp), not again after "Not now" in
        this launch, and not while an update runs. The macOS app installs
        yt-dlp's folder build from the latest release on "Update it".
        """
        if self._closing or self._yt_dlp_bar_dismissed or self._yt_dlp_updating:
            return
        from core import yt_dlp_update
        if yt_dlp_update.update_mode(self.app_config) == yt_dlp_update.MODE_NEVER:
            return
        if not yt_dlp_update.can_self_update():
            # No bar to offer; say once per launch what does help (a failed
            # download's own message carries the same advice, with the app's
            # download page).
            if not _inst_attr(self, "_yt_dlp_outdated_hint_shown") and yt_dlp_update.looks_outdated(reason):
                self._yt_dlp_outdated_hint_shown = True
                self.log("Note: " + yt_dlp_update.OUTDATED_HINT)
            return
        logger.info("Offering a yt-dlp update after: %s", reason)
        self._yt_dlp_offer_open = True
        self._ensure_yt_dlp_bar().show_offer(
            _("The video downloader may be out of date. An update (about "
              "{size} MB) often fixes failing YouTube downloads.",
              size=yt_dlp_update.download_mb()),
            before=self.nb,
        )

    def hide_yt_dlp_offer(self) -> None:
        """Take the "may be out of date" offer down after a format lookup or a
        download worked (main thread). Only the plain offer: never an update's
        progress or result. Not "Not now", so a later failure can offer again."""
        if not _inst_attr(self, "_yt_dlp_offer_open", False):
            return
        self._yt_dlp_offer_open = False
        if self._yt_dlp_bar is not None and not self._yt_dlp_updating:
            self._yt_dlp_bar.hide()

    def _yt_dlp_bar_dismiss(self) -> None:
        self._yt_dlp_offer_open = False
        self._yt_dlp_bar_dismissed = True
        if self._yt_dlp_bar is not None:
            self._yt_dlp_bar.hide()

    def _yt_dlp_update_now(self) -> None:
        """"Update it": update the user-writable copy off the Tk thread."""
        if self._yt_dlp_updating or self._closing:
            return
        self._yt_dlp_offer_open = False
        if not self.ensure_online("Updating the video downloader"):
            return
        from core import yt_dlp_update
        bar = self._ensure_yt_dlp_bar()
        if yt_dlp_update.downloads_running():
            bar.show_result(
                _("A download is running. Click Update it again when it has finished."),
                before=self.nb, can_retry=True,
            )
            return
        self._yt_dlp_updating = True
        bar.show_progress(_("Updating the video downloader…"), before=self.nb)
        self.log("Updating the video downloader (yt-dlp)…")

        def _work() -> None:
            result = yt_dlp_update.update_cached_copy(
                log=lambda line: logger.info("yt-dlp update: %s", line),
            )
            self.post_to_main(lambda: self._yt_dlp_update_done(result))

        from core._threads import safe_thread
        safe_thread(_work, name="yt-dlp-update")

    def _yt_dlp_update_done(self, result: Any) -> None:
        self._yt_dlp_updating = False
        from core import yt_dlp_update
        text = yt_dlp_update.result_text(result)
        self.log(text)
        if self._closing or self._yt_dlp_bar is None:
            return
        self._yt_dlp_bar.show_result(
            text, before=self.nb, can_retry=result.status in ("failed", "busy"),
        )

    def _update_whats_new(self) -> None:
        """"What's new": a small non-modal window with the release highlights."""
        info = self._latest_update
        if info is None:
            return
        window = _inst_attr(self, "_whats_new_window")
        if window is not None and window.winfo_exists():
            window.destroy()  # one window, showing the latest release
        import webbrowser

        from app.widgets.update_bar import show_whats_new
        from core import updates as _updates
        self._whats_new_window = show_whats_new(
            self,
            version=_updates.version_label(info.latest_tag),
            headline=info.headline,
            highlights=info.highlights,
            on_full_notes=lambda: webbrowser.open(info.html_url or _updates.RELEASES_PAGE_URL),
        )

    def _update_download(self) -> None:
        """"Download": the file for this kind of install, in the browser.

        A source checkout gets the update command instead (Linux and
        developers); an unknown install, or a release without the matching
        file, gets the release page.
        """
        info = self._latest_update
        if info is None:
            return
        import webbrowser

        from core import updates as _updates
        version = _updates.version_label(info.latest_tag)
        kind = self._install_kind()
        if kind == _updates.INSTALL_SOURCE:
            from app.widgets.update_bar import show_update_command
            from core.hub import resolve_app_dir
            show_update_command(
                self, version=version, command=_updates.update_command(resolve_app_dir()),
            )
            return
        name = _updates.pick_asset(kind, info.assets)
        if name:
            url = _updates.asset_download_url(info.latest_tag, name)
            self.log(f"Downloading {name} in your browser. Close this app before you run it.")
        else:
            url = info.html_url or _updates.RELEASES_PAGE_URL
            self.log(f"Opening the page of version {version} in your browser.")
        webbrowser.open(url)
        self._hide_update_bar()

    def _update_later(self) -> None:
        """"Later": hide the bar for 3, 7, then 14 days, then 30 days each time."""
        info = self._latest_update
        from core import updates as _updates
        until = _updates.snooze(self.app_config, _today())
        self._save_update_prefs()
        self._hide_update_bar()
        self._refresh_update_signs()
        version = _updates.version_label(info.latest_tag) if info is not None else "the new version"
        message = f"Update reminder for version {version} again on {until.isoformat()}"
        if _updates.is_monthly_reminder(self.app_config):
            message += " (about once a month from now on; Skip this version stops it)"
        self.log(message + ".")

    def _update_skip(self) -> None:
        """"Skip this version": silent until a newer version appears."""
        info = self._latest_update
        if info is None:
            return
        from core import updates as _updates
        _updates.skip_version(self.app_config, info.latest_tag)
        self._save_update_prefs()
        self._hide_update_bar()
        self._refresh_update_signs()
        self.log(
            f"Version {_updates.version_label(info.latest_tag)} skipped; you will hear "
            "about the next one."
        )

    def _apply_update_setting(self) -> None:
        """After Advanced closes: "Don't check for updates" also hides the bar."""
        from core import updates as _updates
        if not _updates.automatic_check_enabled(self.app_config):
            self._hide_update_bar()
        self._refresh_update_signs()

    def _refresh_update_signs(self) -> None:
        """The passive signs: a dot in the Help menu, on "Check for updates...".

        Off macOS the "Help" title carries a dot too; on macOS the title stays exactly
        "Help" (macOS adds its search field only to that title).

        Shown while a newer, unskipped version is known (stored, no network)
        and automatic checks are on; cleared otherwise.
        """
        from core import updates as _updates
        menubar = _inst_attr(self, "_menubar")
        help_menu = _inst_attr(self, "_help_menu")
        if menubar is None or help_menu is None:
            return
        try:
            version = _updates.passive_sign_version(self.app_config, _APP_VERSION)
            if version:
                help_label = f"{translate(_HELP_MENU_LABEL)} ●"
                item_label = _("Check for updates...  ● {version} available", version=version)
            else:
                help_label = translate(_HELP_MENU_LABEL)
                item_label = translate(_CHECK_FOR_UPDATES_LABEL)
            if not mac_native.is_aqua(self):
                # On macOS the Help title must stay exactly "Help": macOS adds
                # its search field only to a menu with that title, so the dot
                # stays on the "Check for updates" item alone.
                menubar.entryconfigure(self._help_cascade_index, label=help_label)
            help_menu.entryconfigure(self._check_updates_index, label=item_label)
        except Exception:  # noqa: BLE001
            logger.debug("Could not refresh the update signs", exc_info=True)

    def _drain_main_calls(self) -> None:
        """Drain the cross-thread queue of main-thread callables.

        Runs on the Tk main thread (scheduled via after()). Any
        background thread that needs to touch widgets pushes a
        zero-arg callable into ``_main_thread_calls`` via
        :meth:`post_to_main`; this method dequeues and runs each on
        the Tk thread. Bounded to 64 calls per tick so a flood from
        a misbehaving thread can't stall the Tk loop.
        """
        if self._closing:
            return
        drained = 0
        while drained < 64:  # bound to keep the Tk loop responsive
            try:
                fn = self._main_thread_calls.get_nowait()
            except Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001
                logger.exception("Main-thread call raised")
            drained += 1
        if not self._closing:
            try:
                self.after(50, self._drain_main_calls)
            except Exception:  # noqa: BLE001
                pass

    def post_to_main(self, fn: Callable[[], None]) -> None:
        """Schedule ``fn`` on the Tk main thread from any thread.

        Safe to call from worker / background threads where
        ``self.after(0, fn)`` would either raise (Python 3.14) or
        silently no-op (older 3.x with off-thread Tk calls). The
        callable is drained by :meth:`_drain_main_calls` on the
        next Tk tick (≤ 50 ms).
        """
        try:
            self._main_thread_calls.put_nowait(fn)
        except Full:
            logger.warning("Main-thread call queue full; dropping callback")

    def _enqueue_watched_file(self, path: str) -> None:
        """Auto-enqueue a media file dropped into the watched folder.

        Mirrors the bookkeeping of App.add(): builds a
        TranscriptionTask, appends to the queue, refreshes the
        Treeview. Skips when the file is still being written (size
        keeps growing for a few seconds after the first detect on
        Windows).

        Deduplicated by path: Windows fires both ``on_created`` and
        ``on_modified`` for the same file (sometimes several of the
        latter as the writer flushes). Each invocation cancels any
        in-flight stability-check ladder for the same path before
        scheduling a fresh one, so we never enqueue the same file
        twice.
        """
        if self._closing:
            return
        if not os.path.isfile(path):
            return
        first = _file_signature(path)
        if first is None:
            return

        norm = os.path.normcase(os.path.abspath(path))
        if norm in self._watched_pending:
            # Already stable and waiting for the model to load.
            return
        # Cancel any prior stability-check ladder for this path so
        # we don't double-enqueue under rapid event bursts.
        prior = self._watched_after_ids.pop(norm, None)
        if prior is not None:
            try:
                self.after_cancel(prior)
            except Exception:  # noqa: BLE001
                pass

        def _schedule(prev: tuple[int, int], same_checks: int) -> None:
            # Track the id so a later event can cancel us cleanly.
            try:
                aid = self.after(
                    _WATCH_CHECK_MS, lambda: _check_stable_then_enqueue(prev, same_checks)
                )
                self._watched_after_ids[norm] = aid
            except Exception:  # noqa: BLE001
                pass

        def _check_stable_then_enqueue(prev: tuple[int, int], same_checks: int) -> None:
            self._watched_after_ids.pop(norm, None)
            if self._closing:
                return
            now = _file_signature(path)
            if now is None:
                return
            verdict, same_checks = _watch_stability_step(prev, now, same_checks)
            if verdict == "wait":
                _schedule(now, same_checks)
                return
            base = os.path.basename(path)
            if verdict == "empty":
                self.log(f"Watched: skipped {base} — the file stayed empty.")
                return
            # Don't re-enqueue a file that is already waiting or running;
            # a finished/cancelled/error row does not block a new copy.
            if self._active_dup_in_queue(path):
                return
            # Lazy model load without freezing the UI. The watched-folder
            # tick runs on the Tk main thread, so a synchronous wait for
            # the model would freeze the app; spawn + await the worker via
            # after()-polling instead and enqueue once it's ready.
            self._watched_pending.add(norm)
            stable = now

            def _do_enqueue() -> None:
                self._watched_pending.discard(norm)
                if self._closing or self._active_dup_in_queue(path):
                    return
                current = _file_signature(path)
                if current is None:
                    self.log(f"Watched: skipped {base} — it was moved or deleted.")
                    return
                if current != stable:
                    # Written to again while the model loaded: wait until it
                    # settles once more.
                    self._enqueue_watched_file(path)
                    return
                task = TranscriptionTask(path)
                self.queue.append(task)
                self.refresh()
                self.log(f"Watched: enqueued {base}")
                self._warn_english_only(task.language, base)
                App._note_mixed_not_applied(self, base)  # a class call: test stand-ins lack it

            def _on_timeout() -> None:
                self._watched_pending.discard(norm)
                self.log(
                    f"Watched: skipped {base} — model load timed out {HEADLESS_READY_TIMEOUT_S} s"
                )

            try:
                self._when_worker_ready(
                    _do_enqueue,
                    on_timeout=_on_timeout,
                    loading_label=f"will transcribe {base} when ready.",
                )
            except Exception:
                # The worker could not start: a later event must not find the
                # file still marked as waiting.
                self._watched_pending.discard(norm)
                raise

        _schedule(first, 0)

    def _maybe_offer_crash_resume(self) -> None:
        """If history.db flagged any rows interrupted on launch, offer
        to re-enqueue the still-existing files."""
        history = getattr(self, "history", None)
        if history is None or getattr(self, "_history_owner", True) is False:
            return
        try:
            rows = history.list_transcriptions(limit=200) or []
        except Exception:  # noqa: BLE001
            return
        interrupted = [
            r for r in rows
            if r.get("status") == "interrupted"
            and r.get("file_path")
            and os.path.isfile(r["file_path"])
        ]
        if not interrupted:
            return
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in interrupted:
            p = r["file_path"]
            if p not in seen:
                seen.add(p)
                unique.append(r)
        n = len(unique)
        if not messagebox.askyesno(
            _("Resume interrupted transcriptions?"),
            _resume_prompt_text(unique),
            parent=self,
        ):
            # User declined — clear the interrupted flag on the rows we
            # offered so this prompt doesn't reappear on every launch.
            try:
                history.dismiss_interrupted_transcriptions(
                    [r["id"] for r in interrupted]
                )
            except Exception:  # noqa: BLE001
                logger.debug("Failed to dismiss interrupted rows", exc_info=True)
            # Also drop the on-disk partial checkpoints for the declined
            # files: declining means "don't resume", so the JSON (which can
            # be MBs of captured segments) is now dead weight. Without this
            # it lingered until the age-based startup sweep.
            try:
                from core import _checkpoint
                for r in unique:
                    _checkpoint.delete_checkpoint(r["file_path"])
            except Exception:  # noqa: BLE001
                logger.debug("Failed to delete declined checkpoints", exc_info=True)
            return
        # Crash-resume: if a partial checkpoint exists for any of
        # these interrupted files, flag the new task as a resume so
        # the worker reuses the on-disk segments instead of starting
        # over. Worker validation will fall back to a fresh
        # transcribe if the checkpoint is stale (different model,
        # mtime drift, etc.) so this is always safe to set when the
        # partial is present.
        # See _task_has_checkpoint: go straight to the lightweight
        # core._checkpoint module rather than core.transcriber, which
        # would force the heavy faster_whisper/ctranslate2 backend
        # import onto the Tk main thread for a plain file-existence check.
        try:
            from core import _checkpoint
            has_resumable_checkpoint = _checkpoint.has_checkpoint
        except Exception:  # noqa: BLE001
            has_resumable_checkpoint = lambda _p: False  # type: ignore[assignment]
        # Lazy model load without freezing the UI. This fires from a
        # startup after(), i.e. on the Tk main thread, so we spawn and
        # await the worker via after()-polling instead of a synchronous
        # wait (which froze the app while the model loaded). On timeout
        # the rows stay flagged interrupted for a later attempt.
        def _do_resume() -> None:
            resumed = 0
            for r in unique:
                task = TranscriptionTask(r["file_path"])
                lang = r.get("language") or ""
                if lang and hasattr(task, "language"):
                    task.language = lang  # type: ignore[attr-defined]
                # Keep the Whisper task of the interrupted run (history row).
                if r.get("task") == "translate":
                    task.whisper_task = "translate"
                # ... and its time range and mixed languages, which no
                # setting restores (the checkpoint was made for them too).
                apply_run_options(task, r.get("run_options"))
                try:
                    if has_resumable_checkpoint(r["file_path"]):
                        task.resume = True
                        resumed += 1
                except Exception:  # noqa: BLE001
                    pass
                self.queue.append(task)
            # The re-run gets its own history row; retire the offered ones
            # (duplicates of the same file too) so the next launch does not
            # offer the same job again.
            try:
                history.dismiss_interrupted_transcriptions(
                    [r["id"] for r in interrupted]
                )
            except Exception:  # noqa: BLE001
                logger.warning("Failed to dismiss resumed interrupted rows", exc_info=True)
            self.refresh()
            if resumed:
                self.log(
                    f"Re-enqueued {n} interrupted transcription(s) "
                    f"({resumed} will resume from checkpoint)"
                )
            else:
                self.log(f"Re-enqueued {n} interrupted transcription(s)")

        self._when_worker_ready(
            _do_resume,
            on_timeout=lambda: self.log(
                f"Crash-resume skipped: model load timed out "
                f"({n} task(s) not re-enqueued) — {HEADLESS_READY_TIMEOUT_S} s"
            ),
            loading_label=f"resuming {n} interrupted transcription(s) when ready.",
        )

    _CLIPBOARD_VK = {86: "paste", 67: "copy", 88: "cut", 65: "selectall"}

    @staticmethod
    def _clipboard_action(keysym: str, keycode: int) -> str | None:
        """Map a Ctrl+key press to a clipboard action, layout-independently.

        Returns None when Tk's own Latin-keysym binding already handles
        the key (English layout) — so we don't act twice — or when it
        isn't a clipboard key. Otherwise it dispatches by the physical
        key's keycode, which is identical whatever the active keyboard
        layout. This fixes paste / copy / cut / select-all under a
        non-Latin layout (Persian, Arabic, Russian, …), where Tk's
        built-in ``<Control-v>`` keysym binding never fires because the
        layout doesn't produce the Latin 'v' keysym.
        """
        if (keysym or "").lower() in ("a", "c", "v", "x"):
            return None
        return App._CLIPBOARD_VK.get(keycode)

    def _install_clipboard_keys(self) -> None:
        if shortcuts.is_mac():
            # Tk/aqua maps Command-C/V/X/A natively, and its keycodes are not
            # the Windows virtual-key codes this handler dispatches on.
            return
        virt = {"paste": "<<Paste>>", "copy": "<<Copy>>", "cut": "<<Cut>>"}

        def _on_ctrl_key(event: tk.Event) -> str | None:
            action = self._clipboard_action(
                event.keysym or "", getattr(event, "keycode", -1)
            )
            if action is None:
                return None
            w = event.widget
            if action == "selectall":
                try:
                    w.select_range(0, "end")  # type: ignore[attr-defined]
                    w.icursor("end")  # type: ignore[attr-defined]
                    return "break"
                except (tk.TclError, AttributeError):
                    pass
                try:
                    w.tag_add("sel", "1.0", "end-1c")  # type: ignore[attr-defined]
                    return "break"
                except (tk.TclError, AttributeError):
                    pass
                return None
            try:
                w.event_generate(virt[action])
                return "break"
            except tk.TclError:
                return None

        self.bind_all("<Control-KeyPress>", _on_ctrl_key, add="+")

    def _install_text_context_menu(self) -> None:
        """Right-click Copy / Cut / Paste / Select all on every text field.

        A mouse-driven, keyboard-layout-independent way to use the
        clipboard. The keyboard shortcuts also work (see
        _install_clipboard_keys), but a right-click menu is what a
        non-technical user reaches for and it never depends on the active
        layout — e.g. selecting + copying the download-folder path. Bound
        on the Entry / Text widget classes so it covers every field; the
        Treeview queue menus use a different class and are unaffected.
        """
        def _popup(event: tk.Event) -> str:
            w = event.widget

            def _select_all() -> None:
                try:
                    w.select_range(0, "end")  # type: ignore[attr-defined]
                    w.icursor("end")  # type: ignore[attr-defined]
                except (tk.TclError, AttributeError):
                    try:
                        w.tag_add("sel", "1.0", "end-1c")  # type: ignore[attr-defined]
                    except (tk.TclError, AttributeError):
                        pass

            menu = tk.Menu(w, tearoff=0)
            menu.add_command(label=_("Cut"), command=lambda: w.event_generate("<<Cut>>"))
            menu.add_command(label=_("Copy"), command=lambda: w.event_generate("<<Copy>>"))
            menu.add_command(label=_("Paste"), command=lambda: w.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label=_("Select all"), command=_select_all)
            try:
                w.focus_set()
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        for cls in ("TEntry", "Entry", "Text"):
            self.bind_class(cls, "<Button-3>", _popup, add="+")
            if sys.platform == "darwin":
                # macOS Tk reports right-click as Button-2, not Button-3.
                self.bind_class(cls, "<Button-2>", _popup, add="+")

    def _install_icon(self) -> None:
        """Set the window-title-bar + taskbar icon from ``assets/whisper.ico``.

        Cosmetic — silently no-ops when the file is missing so a
        damaged install never blocks launch.
        """
        if getattr(sys, "frozen", False):
            ico = os.path.join(
                os.path.dirname(os.path.abspath(sys.executable)),
                "assets", "whisper.ico",
            )
        else:
            ico = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "whisper.ico",
            )
        if not os.path.isfile(ico):
            return
        if sys.platform == "darwin":
            # iconbitmap(default=...) is not supported on macOS/Tk and
            # throws "wrong # args: should be 'wm iconbitmap window ?bitmap?'"
            return
        try:
            self.iconbitmap(default=ico)
        except tk.TclError as exc:
            logger.warning("Could not set window icon (%s): %s", ico, exc)

    def _apply_hidpi_scaling(self) -> None:
        """Bump Tk's pt→px scaling on high-DPI displays.

        Tk default is 72 dpi (1.0). Most modern Windows machines
        report 96 dpi (1.33). Computing from ``self.winfo_fpixels``
        gives the right factor on 125 % / 150 % Windows scaling, so
        the app's fonts and widget paddings keep their physical
        size rather than shrinking to the size of a 1 cm icon.
        """
        try:
            dpi = float(self.winfo_fpixels("1i"))
            if dpi <= 0:
                return
            scale = max(1.0, dpi / 72.0)
            self.tk.call("tk", "scaling", scale)
            logger.info("Tk scaling set to %.2f (%.0f dpi)", scale, dpi)
        except Exception as e:  # noqa: BLE001
            logger.info("Could not apply HiDPI scaling: %s", e)

    def _install_drag_drop(self) -> None:
        """Wire tkinterdnd2 if available, no-op otherwise.

        ``TkinterDnD._require(self)`` loads the Tcl ``tkdnd`` package
        into the interpreter but DOES NOT add the
        ``drop_target_register`` / ``dnd_bind`` methods to a plain
        ``tk.Tk`` instance — those live on ``TkinterDnD.DnDWrapper``.
        Mix the wrapper into our App's class so the methods become
        bound. Without this graft, drag-and-drop silently never
        registered in v0.7.1.
        """
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-not-found]
        except ImportError:
            logger.info("tkinterdnd2 not present; drag-and-drop disabled")
            return
        try:
            TkinterDnD._require(self)
            # Graft DnDWrapper's methods onto our class so this
            # instance gains drop_target_register / dnd_bind.
            wrapper = getattr(TkinterDnD, "DnDWrapper", None)
            if wrapper is not None and wrapper not in self.__class__.__mro__:
                self.__class__ = type(
                    self.__class__.__name__,
                    (self.__class__, wrapper),
                    {},
                )
            if not hasattr(self, "drop_target_register"):
                logger.warning(
                    "tkinterdnd2 imported but drop_target_register "
                    "is still missing; drag-and-drop disabled"
                )
                return
            self.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            logger.info("Drag-and-drop enabled (tkinterdnd2)")
            self._dnd_ready = True
            sync_transcribe_empty_state(self)  # the headline may now promise a drop
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not initialise drag-and-drop: %s", e)

    def _on_drop(self, event: tk.Event) -> None:
        """Handle a drag-and-drop onto the window.

        tkinterdnd2 packs all dropped paths into a single string with
        space-or-brace separation. We split it with ``_split_dnd_paths``
        rather than ``self.tk.splitlist`` because Tcl's list parser
        collapses a UNC path's leading double-backslash down to a single
        one, which then fails the ``os.path.isfile`` gate and silently
        drops network-share files. ``self.tk.splitlist`` is kept as a
        fallback for any unexpected token shape, so behaviour is
        otherwise unchanged.
        Behaviour:
          - one file dropped → populate the Transcribe tab's file
            field
          - multiple files   → enqueue each as a Transcription task
            without further prompts
          - folder dropped   → its top-level media files are treated as
            a multi-file drop (empty folders are reported, not ignored)
          - URL dropped      → if it's a known download URL, paste
            into the Download tab's URL field
          - anything else    → reported in the log; a drop is never a
            silent no-op
        """
        raw = getattr(event, "data", "") or ""
        items = _split_dnd_paths(raw)
        if not items and raw.strip():
            # Helper found nothing in a non-empty payload — fall back to
            # Tcl's own splitter so we don't regress on an odd token shape.
            try:
                items = list(self.tk.splitlist(raw))
            except Exception:  # noqa: BLE001
                items = [raw]
        self.open_paths(items, empty_payload=not raw.strip())

    def open_paths(
        self, items: list[str], *, empty_payload: bool = False, require_media: bool = False,
    ) -> None:
        """Handle dropped items, or files passed on the command line.

        ``require_media``: files that are not audio or video (``core.watcher.is_transcribable``)
        are reported like any unusable item instead of being picked. Off for drops and the
        command line (Transcribe and the multi-file queue check them later); macOS turns it on
        for files Finder hands over ("Open With" lists the app for any file type).

        One file is picked in the Transcribe tab, several files (or a
        folder's media files) are queued, a URL goes to the Download tab,
        and anything unusable is reported in the log.
        """
        from core.watcher import is_transcribable

        paths: list[str] = []
        urls: list[str] = []
        folders: list[str] = []
        unsupported: list[str] = []
        for item in items:
            s = item.strip()
            if not s:
                continue
            if s.startswith(("http://", "https://")):
                urls.append(s)
            elif s.startswith("file://"):
                # A file:// URI (some apps / file managers hand these to a
                # drop target) points at a local file. Convert it to a real
                # path and treat it like any other local file rather than
                # silently swallowing it.
                local = _file_uri_to_path(s)
                if local and os.path.isfile(local):
                    paths.append(local)
                elif local and os.path.isdir(local):
                    folders.append(local)
                else:
                    unsupported.append(s)
            elif os.path.isfile(s):
                if require_media and not is_transcribable(s):
                    unsupported.append(s)
                else:
                    paths.append(s)
            elif os.path.isdir(s):
                folders.append(s)
            else:
                # An unsupported scheme (ftp:, magnet:, smb:, …), a path
                # that no longer exists, or plain text. Don't pretend it
                # worked — note it so the drop isn't a silent no-op.
                unsupported.append(s)

        for folder in folders:
            found = _media_files_in_folder(folder)
            display = os.path.basename(folder.rstrip("\\/")) or folder
            if found:
                paths.extend(found)
                self.log(
                    f"Dropped folder {display}: queueing its "
                    f"{len(found)} media file(s)."
                )
            else:
                self.log(
                    f"Dropped folder {display} has no media files at its "
                    f"top level; nothing to queue."
                )

        if urls and hasattr(self, "download_url_var"):
            self.download_url_var.set(urls[0])
            self.nb.select(self.t3)
            self.log(f"Pasted URL into Download tab: {urls[0]}")
            if len(urls) > 1:
                # The Download tab takes one URL at a time; the rest of a
                # multi-URL drop would otherwise vanish without a trace.
                self.log(
                    f"Only the first of {len(urls)} dropped URLs was used; "
                    f"drop the others one at a time."
                )
        if paths:
            if len(paths) == 1:
                self.nb.select(self.t1)  # first: the box scrolls best once its tab is shown
                _show_file_in_box(self, paths[0])
                self.log(f"Picked: {os.path.basename(paths[0])} (drag-and-drop)")
            else:
                count = self._bulk_enqueue(paths)
                if count:
                    self.log(f"Enqueued {count} files via drag-and-drop")
        if unsupported:
            self.log(
                f"Ignored {len(unsupported)} dropped item(s) that aren't "
                f"usable (e.g. {unsupported[0]}). Drop a media file, a "
                f"folder of media files, or an http(s) URL."
            )
        elif not paths and not urls and not folders and not empty_payload:
            # A non-empty payload that produced nothing actionable — e.g.
            # an empty selection. Without this the drop is a silent no-op
            # and the user can't tell what went wrong.
            self.log(
                "Nothing to do with that drop — drop a media file, a "
                "folder of media files, or an http(s) URL."
            )

    def _cancel_running(self) -> None:
        """Esc handler — cancel whichever single running task is most relevant.

        Confirms first: Esc is an easy accidental keystroke and the
        running task can be a long transcription, not something to
        drop with zero recovery on one stray tap.
        """
        for t in self.queue:
            if t.status == "running":
                if messagebox.askyesno(
                    _("Cancel transcription?"),
                    _("A transcription is running ({name}). Cancel it?",
                      name=os.path.basename(t.file_path)),
                    parent=self,
                    default="no",
                ):
                    self.cancel(t)
                return
        for d in self.download_queue:
            if d.status == "running":
                if messagebox.askyesno(
                    _("Cancel download?"),
                    _("A download is running. Cancel it?"),
                    parent=self,
                    default="no",
                ):
                    self.cancel_download(d)
                return

    def _apply_default_geometry(self) -> None:
        """First-run window size: as large as the layout wants (1320x900),
        shrunk to fit the usable screen area (the work area of the monitor
        on Windows, so the taskbar never covers the bottom), centred in it.
        On a small screen (1366x768 laptops) Windows also maximises it."""
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:  # noqa: BLE001
            sw, sh = 1366, 768
        w, h = scaled_size(self, 1320, 900)
        ax, ay, aw, ah, _exact = work_area(self)
        if aw <= 0 or ah <= 0:
            ax, ay, aw, ah = 0, 0, sw, sh
        # The title bar sits above the client area that geometry() places.
        title = dpi_scaled(self, 32)
        x = ax + max(0, (aw - w) // 2)
        y = ay + max(0, (ah - h - title) // 3)
        try:
            self.geometry(f"{w}x{h}+{x}+{y}")
            if sys.platform == "win32" and (sw < 1440 or sh < 900):
                self.state("zoomed")
        except Exception:  # noqa: BLE001
            self.geometry("960x640")

    def _save_window_geometry(self) -> None:
        """Persist the window's current size + position in config.json."""
        try:
            geom = self.geometry()
        except Exception:  # noqa: BLE001
            return
        if not geom:
            return
        try:
            self.app_config["window_geometry"] = geom
            save_config(self.app_config)
        except Exception:  # noqa: BLE001
            pass

    def queue_row_double_click(self, event: tk.Event) -> None:
        """Double-click on a finished Queue row opens its transcript in the viewer, as
        "View transcript" does; the folder made the user find and open the file (deep review,
        2026-10-21). Without a transcript .json (other formats only, or no speech) it opens
        the output folder, which an output-folder setting can put away from the source.

        For waiting/running/error/cancelled rows the action is a
        no-op (no useful destination yet).
        """
        item = self.tree.identify_row(event.y)
        if not item:
            return
        task = self.row_map.get(item)
        if not task or task.status != "finished":
            return
        if not getattr(task, "no_speech", False) and task_transcript_json(task, must_exist=True):
            self.open_transcript_viewer_for(
                task.file_path, self._task_json_output(task), task.language or task.detected_language,
            )
            return
        self._open_task_output_folder(task)

    def log(self, msg: str) -> None:
        # The log file gets the text without the right-to-left marks; the panel keeps them.
        self._ui_logger.info(plain(msg) if isinstance(msg, str) else msg)
        if hasattr(self, "txt") and self.txt is not None:
            insert_log_line(self.txt, msg)

    def log_threadsafe(self, msg: str) -> None:
        """Thread-safe wrapper around :meth:`log` for background threads.

        log() writes the console Text widget directly, and Tk is not
        thread-safe, so any background-thread caller (e.g. the Advanced
        dialog's install / model-download / cloud-key / gcloud-test workers)
        must marshal through here. Mirrors the post_to_main pattern already
        used by _offer_optional_install."""
        self.post_to_main(lambda: self.log(msg))

    # Driver loops ------------------------------------------------------------
    def update_overall_progress(self) -> None:
        running = [t for t in self.queue if t.status == "running"]
        value = sum(t.progress for t in running) / len(running) if running else 0
        self.pb["value"] = value
        row = _inst_attr(self, "overall_row")  # absent on bare test doubles
        if row is None:
            return
        # winfo_manager, not winfo_ismapped: a row on a tab that is not shown is packed but not
        # mapped, and packing it again every 500 ms kept the window busy (review, 2026-10-21).
        if len(running) < 2:
            # One job: its row bar and the window title already show it.
            if row.winfo_manager():
                row.pack_forget()
            return
        self.overall_var.set(_("{count} jobs running: {percent}% done in all",
                               count=len(running), percent=int(value)))
        if not row.winfo_manager():
            row.pack(fill="x", pady=(6, 4))

    def loop(self) -> None:
        # Once shutdown starts, don't begin new subprocess work (a nested
        # "exit with queued tasks?" modal pumps the event loop, so this
        # after()-chain keeps firing during teardown otherwise). Audit P2-5.
        if self._closing:
            return
        steps: tuple[tuple[str, Callable[[], None]], ...] = (
            ("refresh", self.refresh),
            ("dispatch", self.transcription_service.dispatch_waiting),
            ("downloads", self.download_service.process_queue),
        )
        if getattr(self, "_exit_waiting", False):
            # The app is finishing viewer exports before it closes: no job may start now.
            steps = steps[:1]
        try:
            # One failing step (e.g. Popen blocked by an antivirus inside
            # start_worker) must not skip the others or stop the pump.
            for name, step in steps:
                try:
                    step()
                except Exception as e:  # noqa: BLE001
                    self._log_loop_error(name, e)
                else:
                    self._loop_errors.pop(name, None)
        finally:
            if not self._closing:
                self.after(500, self.loop)

    def _log_loop_error(self, step: str, error: Exception) -> None:
        """Log a queue-pump failure once per distinct error, not every 500 ms."""
        text = f"{type(error).__name__}: {error}"
        if self._loop_errors.get(step) == text:
            logger.debug("Queue pump step %r still failing: %s", step, text)
            return
        self._loop_errors[step] = text
        logger.error("Queue pump step %r failed; retrying every 500 ms",
                     step, exc_info=error)

    def report_callback_exception(
        self, exc: type[BaseException], val: BaseException, tb: Any
    ) -> None:
        """Route an error raised inside any Tk callback to the app log.

        Tk's default prints the traceback to stderr, which is None under
        pythonw (the installed app), so such errors used to vanish. The
        same error raised again in a row (a failing after() loop re-arms
        every 100 ms) is logged once with its traceback, not on every tick.
        """
        text = f"{exc.__name__}: {val}"
        if getattr(self, "_last_callback_error", "") == text:
            logger.debug("Tk callback error repeated: %s", text)
            return
        self._last_callback_error = text
        logger.error("Unhandled error in a Tk callback", exc_info=(exc, val, tb))
        try:
            self.log(f"Unexpected error: {text} (details are in the log file)")
        except Exception:  # noqa: BLE001 - the error is already in the log
            logger.debug("Could not show the error in the console", exc_info=True)
