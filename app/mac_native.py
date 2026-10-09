"""macOS native integration: app menu, Window and Help menus, Finder, Dock icon.

Everything here is a no-op unless Tk reports the ``aqua`` windowing system, so
Windows and Linux behave exactly as before. Each hook was proved on Tk 8.6.16
(python.org Python 3.12, macOS 13) by ``tools/mac_native_probe.py``; see
``docs/MACOS_BUILD_NOTES.md`` "Native integration" for the probe result and the
two hooks that are NOT used (the ``.apple`` menu does not merge into the app
menu, and Tk has no Dock menu hook).

Tk 8.6 documentation used: the ``menu`` manual page ("SPECIAL MENUS IN
MENUBARS": the ``.window`` and ``.help`` menus), the ``tk_mac`` commands
``::tk::mac::ShowPreferences``, ``::tk::mac::ShowHelp``,
``::tk::mac::OpenDocument``, ``::tk::mac::ReopenApplication`` and the
``tkAboutDialog`` command that the app menu's About item runs, and the ``wm``
manual page (``wm attributes -modified`` and ``-titlepath``).

Files that macOS hands over (Finder "Open With", a drop on the Dock icon, a
double-click on an associated file) arrive as Apple events after the Tk loop
starts, never through ``argv`` (PyInstaller's ``argv_emulation`` conflicts with
Tk and is not used). They wait in a queue until the first-run windows and any
other modal window are done, then go through ``App.open_paths``: the same path
as a drop on the window.
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Tk treats a menu as the Window or Help menu by the last part of its path name.
WINDOW_MENU_NAME = "window"
HELP_MENU_NAME = "help"

# How often a queued Finder file checks whether the app can take it yet.
DRAIN_POLL_MS = 400

#: Wording on macOS for the actions that open a folder in the file manager.
REVEAL_LABEL = "Reveal in Finder"


def is_aqua(widget: Any) -> bool:
    """True when ``widget`` runs on Tk's macOS (Aqua) windowing system."""
    try:
        return str(widget.tk.call("tk", "windowingsystem")) == "aqua"
    except (tk.TclError, AttributeError):
        return False


def clean_paths(raw: Any) -> list[str]:
    """The non-empty path strings of an Apple ``odoc`` event, in order."""
    return [str(p) for p in raw if str(p).strip()]


# --------------------------------------------------------------------- menus

def window_menu_kwargs(widget: Any) -> dict[str, Any]:
    """``tk.Menu`` options that make the Window menu the native one on Aqua.

    Tk fills it with Minimize, Zoom, Bring All to Front and the window list.
    """
    return {"name": WINDOW_MENU_NAME} if is_aqua(widget) else {}


def help_menu_kwargs(widget: Any) -> dict[str, Any]:
    """``tk.Menu`` options that make the Help menu the native one on Aqua.

    macOS adds its search field to a Help menu titled exactly ``Help``, and Tk
    adds its own "<App> Help" item (which runs ``::tk::mac::ShowHelp``).
    """
    return {"name": HELP_MENU_NAME} if is_aqua(widget) else {}


# ----------------------------------------------------------------- app menu

def _guarded(name: str, action: Callable[[], None]) -> Callable[..., None]:
    """A Tcl command body that logs instead of raising into Tk's Apple event handler."""
    def run(*_args: str) -> None:
        try:
            action()
        except Exception:  # noqa: BLE001
            logger.exception("macOS %s handler failed", name)
    return run


def _modal_open(app: Any) -> bool:
    """True while a modal window holds the Tk grab (macOS menus still work then)."""
    try:
        return app.grab_current() is not None
    except (tk.TclError, KeyError):
        return False


def _cannot_open_dialog(app: Any) -> bool:
    """True before the window is ready, or while a modal window is open.

    Windows blocks the main window's buttons the same way; macOS menu items
    stay live, so the app menu's About and Settings check it themselves.
    """
    return not getattr(app, "_start_ran", False) or _modal_open(app)


def show_about(app: Any) -> None:
    """The app menu's About item: the app's own About dialog."""
    if _cannot_open_dialog(app):
        app.bell()
        return
    app._show_about()


def show_settings(app: Any) -> None:
    """The app menu's Settings item (Command-comma): the Advanced settings dialog."""
    if _cannot_open_dialog(app):
        app.bell()
        return
    app.open_advanced_dialog()


def show_help(app: Any) -> None:
    """The Help menu's "<App> Help" item: the user documentation page."""
    import webbrowser

    from core import star_invite

    webbrowser.open(f"{star_invite.REPO_URL}/blob/master/docs/README.md")


# ------------------------------------------------------------ Finder: open

def queue_documents(app: Any, paths: list[str]) -> None:
    """Remember files macOS asked to open and hand them over when the app is ready."""
    paths = clean_paths(paths)
    if not paths:
        return
    app._mac_pending_opens.extend(paths)
    schedule_drain(app)


def schedule_drain(app: Any, delay_ms: int = 0) -> None:
    """Arrange one drain of the queue (never two timers at once)."""
    if getattr(app, "_mac_drain_scheduled", False):
        return
    app._mac_drain_scheduled = True
    try:
        app.after(delay_ms, lambda: drain_pending(app))
    except tk.TclError:
        app._mac_drain_scheduled = False


def ready_for_documents(app: Any) -> bool:
    """True once the first-run windows and every modal window are done."""
    if getattr(app, "_closing", False):
        return False
    return (
        bool(getattr(app, "_start_ran", False))
        and not getattr(app, "_quick_start_open", False)
        and not _modal_open(app)
    )


def drain_pending(app: Any) -> None:
    """Open the queued files, or look again shortly while the app is busy."""
    app._mac_drain_scheduled = False
    if getattr(app, "_closing", False) or not app._mac_pending_opens:
        return
    if not ready_for_documents(app):
        schedule_drain(app, DRAIN_POLL_MS)
        return
    paths, app._mac_pending_opens = app._mac_pending_opens, []
    show_main_window(app)
    app.open_paths(paths)


# ------------------------------------------------------------- Dock: reopen

def show_main_window(app: Any) -> None:
    """Bring the main window back: from the Dock, minimised or hidden in the tray."""
    if getattr(app, "_closing", False):
        return
    try:
        if str(app.state()) in ("withdrawn", "iconic"):
            app.deiconify()
        app.lift()
    except tk.TclError:
        logger.debug("Could not show the main window", exc_info=True)


# ------------------------------------------------------------- Close Window

def close_front_window(app: Any) -> bool:
    """Command-W: close the window that has the keyboard focus, never the main one.

    Runs the window's own ``WM_DELETE_WINDOW`` handler, so a viewer with unsaved
    edits still asks first. A window without a handler is destroyed. Returns True
    when a secondary window was asked to close.
    """
    try:
        focus = app.focus_get()
    except (tk.TclError, KeyError):
        focus = None
    window = focus.winfo_toplevel() if focus is not None else None
    if window is None or window is app:
        return False
    try:
        handler = str(app.tk.call("wm", "protocol", window, "WM_DELETE_WINDOW"))
        if handler:
            app.tk.call(handler)
        else:
            window.destroy()
    except tk.TclError:
        logger.debug("Close Window failed", exc_info=True)
        return False
    return True


# -------------------------------------------------------------- window marks

def set_title_path(window: Any, path: str) -> None:
    """Show ``path`` as the window's proxy icon (drag it, Command-click the title)."""
    if not is_aqua(window):
        return
    try:
        window.wm_attributes("-titlepath", path)
    except tk.TclError:
        logger.debug("-titlepath not applied", exc_info=True)


def set_modified(window: Any, modified: bool) -> None:
    """Show or clear the dot in the window's close button (unsaved changes)."""
    if not is_aqua(window):
        return
    try:
        window.wm_attributes("-modified", bool(modified))
    except tk.TclError:
        logger.debug("-modified not applied", exc_info=True)


# ------------------------------------------------------------------- install

def install(app: Any) -> bool:
    """Register the native handlers on the main window; False when not on Aqua.

    Called while the window is being built, before the first event-loop turn, so
    a file that launched the app is queued and never lost.
    """
    if not is_aqua(app):
        return False
    app._mac_pending_opens = []
    app._mac_drain_scheduled = False
    app.createcommand("tkAboutDialog", _guarded("About", lambda: show_about(app)))
    app.createcommand(
        "::tk::mac::ShowPreferences", _guarded("Settings", lambda: show_settings(app)))
    app.createcommand("::tk::mac::ShowHelp", _guarded("Help", lambda: show_help(app)))
    app.createcommand(
        "::tk::mac::ReopenApplication",
        _guarded("Reopen", lambda: show_main_window(app)))

    def open_document(*paths: str) -> None:
        try:
            queue_documents(app, list(paths))
        except Exception:  # noqa: BLE001
            logger.exception("macOS OpenDocument handler failed")

    app.createcommand("::tk::mac::OpenDocument", open_document)
    return True
