"""macOS window appearance that matches the app theme: light or dark title bar on any system setting.

The Light/Dark/System theme only restyles what Tk draws inside the window. The title bar of an
Aqua window is drawn by macOS in the system appearance, so an explicit Dark theme on a Light Mac
(or Light on a Dark Mac) kept the system title bar next to a window of the other colour. Tk
8.6.10+ can pin the appearance of one window:

    ::tk::unsupported::MacWindowStyle appearance <window> aqua | darkaqua | auto

``aqua`` = light, ``darkaqua`` = dark, ``auto`` = follow the system. This module sets it on the main
window and every Toplevel from the theme *mode* ("light", "dark", "system"): "system" is ``auto``.
Windows opened later are set when they are first shown (``<Map>``), like ``win_chrome`` does for
the Windows frame. Off macOS nothing here does anything; a Tk that does not know the option
(before 8.6.10) is logged once and ignored.

The mode is applied BEFORE the theme is resolved: with the root pinned to ``darkaqua`` Tk's
``isdark`` answers "dark" whatever the system says, so "System" must be set back to ``auto`` first
or it would read its own earlier pin (``system_appearance.MacBackend`` asks that same window).

Kill switch: the config key ``native_window_theme`` (shared with the Windows frame) set to false,
or the environment variable ``WTS_NO_NATIVE_CHROME``. Native alerts and file dialogs follow the
system appearance: they are not Tk windows and are not touched here.

Tk 8.6 documentation used: the ``wm`` manual page and Tk's ``tkMacOSXWm.c``
(``::tk::unsupported::MacWindowStyle appearance``, added in 8.6.10).
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

from app import mac_native
from app.theme import win_chrome

logger = logging.getLogger(__name__)

_MARK = "_wts_mac_appearance"   # attribute on a themed window: the appearance it was given

_APPEARANCE = {"light": "aqua", "dark": "darkaqua", "system": "auto"}

# Process-wide state (reset by tests/conftest.py).
_config_enabled = True
_mode = "system"
_failed: set[str] = set()


def set_enabled(enabled: object) -> None:
    """The config switch (``native_window_theme``); the environment variable is read live."""
    global _config_enabled
    _config_enabled = win_chrome._as_switch(enabled)


def enabled() -> bool:
    return _config_enabled and not win_chrome.env_disabled()


def appearance_for(mode: str) -> str:
    """Tk's appearance word for a theme mode; an unknown mode is dark, as the theme itself does."""
    return _APPEARANCE.get(mode, "darkaqua")


def _note_failure(key: str, message: str, *args: object) -> None:
    if key in _failed:
        return
    _failed.add(key)
    logger.info(message, *args)


def apply(widget: tk.Misc, mode: str) -> bool:
    """Give the window ``widget`` the appearance of theme ``mode``; True when Tk took it.

    Never raises: a window that is gone or a Tk without the option is logged once and ignored.
    """
    if not enabled() or not mac_native.is_aqua(widget):
        return False
    word = appearance_for(mode)
    try:
        widget.tk.call("::tk::unsupported::MacWindowStyle", "appearance", str(widget), word)
    except tk.TclError as exc:
        _note_failure("apply", "Could not set the window appearance: %s", exc)
        return False
    setattr(widget, _MARK, word)
    return True


def _top_levels(root: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack: list[tk.Misc] = [root]
    while stack:
        widget = stack.pop()
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            found.append(widget)
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue
    return found


def _has_frame(widget: tk.Misc) -> bool:
    """False for override-redirect windows (tooltips, popup menus): they have no title bar."""
    try:
        return not bool(widget.wm_overrideredirect())  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):
        return False


def apply_all(root: tk.Misc, mode: str) -> int:
    """Set ``root`` and every open Toplevel under it; returns how many windows took it.

    Also records ``mode`` as the one windows opened later get.
    """
    global _mode
    _mode = mode if mode in _APPEARANCE else "dark"
    if not enabled() or not mac_native.is_aqua(root):
        return 0
    return sum(1 for w in _top_levels(root) if _has_frame(w) and apply(w, _mode))


def _on_map(event: Any) -> None:
    widget = event.widget
    if not isinstance(widget, (tk.Tk, tk.Toplevel)) or not _has_frame(widget):
        return
    if getattr(widget, _MARK, None) == appearance_for(_mode):
        return  # already set: a minimise/restore must not touch the window again
    apply(widget, _mode)


def install(root: tk.Misc, mode: str) -> None:
    """Set ``root`` for ``mode`` now, and every Toplevel when it is first shown.

    Call once at start, before the theme is resolved; ``apply_all`` follows each theme switch.
    Does nothing off macOS or with the kill switch on.
    """
    if not enabled() or not mac_native.is_aqua(root):
        return
    try:
        # One binding per Tcl interpreter (bind_class is interpreter-wide); the marker lives on
        # the root object, so a second root (tests) gets its own.
        if not getattr(root, "_wts_mac_appearance_bound", False):
            root.bind_class("Toplevel", "<Map>", _on_map, add="+")
            setattr(root, "_wts_mac_appearance_bound", True)
        apply_all(root, mode)
    except Exception as exc:  # noqa: BLE001 - a window frame must never stop start-up
        _note_failure("install", "Could not install the window appearance: %s", exc)


def reset_for_tests() -> None:
    """Forget process-wide state (used by the autouse fixture in tests/conftest.py)."""
    global _config_enabled, _mode
    _config_enabled = True
    _mode = "system"
    _failed.clear()
