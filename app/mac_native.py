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

import ctypes
import ctypes.util
import logging
import sys
import tkinter as tk
import unicodedata
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
    """True while a modal window is open (macOS menus still work then).

    Two signals, because three dialogs swallow a failed ``grab_set`` and a
    native alert holds no grab at all: the Tk grab, and any window of the app
    that is on screen and transient (what every modal dialog here is). Windows
    that set ``_non_modal`` (the transcript viewer) are transient too but stay
    usable beside the main window.
    """
    try:
        if app.grab_current() is not None:
            return True
    except (tk.TclError, KeyError):
        pass
    try:
        children = app.winfo_children()
    except (tk.TclError, AttributeError):
        return False
    for child in children:
        if not isinstance(child, tk.Toplevel) or getattr(child, "_non_modal", False):
            continue
        try:
            if child.winfo_viewable() and str(child.wm_transient()):
                return True
        except tk.TclError:
            continue
    return False


def _question_open(app: Any) -> bool:
    """True while a question without a Tk grab is open: the quit question (a native
    alert) or the first-run model folder dialog."""
    return bool(getattr(app, "_exit_prompt_open", False) or getattr(app, "_hub_setup_open", False))


def _cannot_open_dialog(app: Any) -> bool:
    """True before the window is ready, or while a modal window or question is open.

    Windows blocks the main window's buttons the same way; macOS menu items
    stay live, so the app menu's About and Settings check it themselves.
    """
    return not getattr(app, "_start_ran", False) or _question_open(app) or _modal_open(app)


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
        and not _question_open(app)
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
    # Finder lists the app for any file type under "Open With": only audio and
    # video is taken, the rest is reported like an unusable drop.
    app.open_paths(paths, require_media=True)


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

def key_window_title() -> str | None:
    """Title of the app's AppKit key window, the one macOS gives Command-W; None if unknown.

    Asked through the Objective-C runtime with ``ctypes`` (no pyobjc), as
    ``desktop_alert`` asks ``[NSApp isActive]``. None off macOS, when the runtime cannot be
    reached, or when the app has no key window.
    """
    if sys.platform != "darwin":
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

        def send(restype: Any, receiver: Any, selector: bytes) -> Any:
            call = ctypes.PYFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", lib))
            return call(receiver, lib.sel_registerName(selector))

        ns_app_class = lib.objc_getClass(b"NSApplication")
        shared = send(ctypes.c_void_p, ns_app_class, b"sharedApplication") if ns_app_class else None
        window = send(ctypes.c_void_p, shared, b"keyWindow") if shared else None
        title = send(ctypes.c_void_p, window, b"title") if window else None
        raw = send(ctypes.c_char_p, title, b"UTF8String") if title else None
        return raw.decode("utf-8") if raw is not None else None
    except (OSError, AttributeError, ctypes.ArgumentError, UnicodeDecodeError):
        return None


def _stack_front_first(app: Any) -> list[str]:
    """Path names of the app's windows that are on screen, front window first.

    ``wm stackorder`` lists them bottom to top; on Aqua Tk builds it from AppKit's own ordered
    window list.
    """
    try:
        return list(reversed([str(p) for p in app.tk.splitlist(app.tk.call("wm", "stackorder", "."))]))
    except tk.TclError:
        return []


def _window_title(app: Any, path: str) -> str | None:
    try:
        return str(app.tk.call("wm", "title", path))
    except tk.TclError:
        return None


def _normal_title(title: str) -> str:
    """A window title as one comparable string: composed (NFC) and without blank edges.

    AppKit and Tk can hand back the same title with its characters composed differently
    (a Persian alef-madda as one code point or as alef + madda).
    """
    return unicodedata.normalize("NFC", title).strip()


def _focused_toplevel(app: Any) -> str | None:
    """Path name of the window that holds Tk's keyboard focus; None when Tk reports none."""
    try:
        focus = app.focus_get()
    except (tk.TclError, KeyError):
        return None
    if focus is None:
        return None
    try:
        return str(focus.winfo_toplevel())
    except tk.TclError:
        return None


def _front_window_path(app: Any) -> str | None:
    """Path name of the window Command-W acts on; ``.`` or None when there is none to close.

    The front window is the one macOS keeps as its key window. Tk's own focus is not a reliable
    stand-in: after a dialog or an alert of the window was closed Tk can report no focus at all
    while that window is still the key one (the same gap ``desktop_alert`` found for an inactive
    app). So AppKit is asked first, and its key window is matched to a Tk window by title (compared
    composed and trimmed), the front-most one when several share it. A title that still matches
    no window is a native panel, or a title Tk and AppKit disagree on: then only a secondary window
    that Tk itself reports as focused is closed, so the original silent no-op cannot come back.
    When AppKit cannot be asked, Tk's focus decides, and with no focus the front window in the
    stacking order.
    """
    stack = _stack_front_first(app)
    title = key_window_title()
    if title is not None:
        wanted = _normal_title(title)
        for path in stack:
            candidate = _window_title(app, path)
            if candidate is not None and _normal_title(candidate) == wanted:
                return path
        logger.debug("No Tk window has the key window's title %r", title)
        return _focused_toplevel(app)
    focused = _focused_toplevel(app)
    if focused is not None:
        return focused
    return stack[0] if stack else None


def _grab_forbids(app: Any, path: str) -> bool:
    """True while a modal dialog holds the Tk grab and ``path`` is not that dialog or a window
    opened from it (Windows keeps the other windows blocked the same way)."""
    try:
        holder = app.grab_current()
        grab = str(holder.winfo_toplevel()) if holder is not None else None
    except (tk.TclError, KeyError):
        return False
    if grab is None or grab == str(app):
        return False
    return not (path == grab or path.startswith(grab + "."))


def close_front_window(app: Any) -> bool:
    """Command-W: close the front window, never the main one.

    Runs the window's own ``WM_DELETE_WINDOW`` handler, so a viewer with unsaved
    edits still asks first. A window without a handler is destroyed. While a modal
    dialog holds the grab only that dialog (or a window opened from it) closes; any
    other window gets a beep. Returns True when a secondary window was asked to close.
    """
    path = _front_window_path(app)
    if path is None or path == str(app):
        return False
    if _grab_forbids(app, path):
        try:
            app.bell()
        except tk.TclError:
            pass
        return False
    try:
        handler = str(app.tk.call("wm", "protocol", path, "WM_DELETE_WINDOW"))
        if handler:
            app.tk.call(handler)
        else:
            app.nametowidget(path).destroy()
    except (tk.TclError, KeyError):
        logger.debug("Close Window failed", exc_info=True)
        return False
    return True


# ---------------------------------------------------------------- placement

# The menu bar and title bar: a window is never placed above this (Tk's y is the top of the frame).
_MENU_BAR_PX = 28


def centre_over(window: Any, master: Any, width: int, height: int) -> None:
    """Aqua: put ``window`` (about to be ``width`` x ``height``) in the middle of ``master``.

    macOS opens a new Tk window wherever it likes, which left the About dialog off to one side
    of the main window. On the main screen it is kept on screen; over a main window on another
    monitor it is simply centred there. Does nothing off Aqua or while ``master`` is not shown.
    """
    if not is_aqua(window):
        return
    try:
        top = master.winfo_toplevel()
        if not top.winfo_viewable():
            return
        left, up = top.winfo_rootx(), top.winfo_rooty()
        across, down = top.winfo_width(), top.winfo_height()
        x = left + (across - width) // 2
        y = up + (down - height) // 2
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
        # Tk's screen size is the main screen's. Keep the window on it only when the main window
        # is on it too; on a monitor left of, above or right of the main screen the coordinates
        # lie outside it (negative is valid: "+-800+40") and a clamp would send the window away.
        if left >= 0 and up >= 0 and left + across <= screen_w and up + down <= screen_h:
            x = max(0, min(x, screen_w - width))
            y = max(_MENU_BAR_PX, min(y, screen_h - height))
        window.geometry(f"+{x}+{y}")
    except tk.TclError:
        logger.debug("Window not centred", exc_info=True)


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
