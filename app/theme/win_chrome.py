"""Windows window frame that matches the app theme: dark title bar, Windows 11 caption colours.

The Light/Dark theme only restyles what Tk draws inside the window. The title bar and border are
drawn by Windows (DWM), so they stayed light next to a dark window. This module asks DWM to draw
them for the app theme with ``DwmSetWindowAttribute``, through ``ctypes`` only:

* every Windows 10 1809+ / 11 window: ``DWMWA_USE_IMMERSIVE_DARK_MODE`` (20; 19 on Windows 10
  builds before 18985 that only know the old number);
* Windows 11 (build 22000+) only: ``DWMWA_CAPTION_COLOR`` (35), ``DWMWA_BORDER_COLOR`` (34) and
  ``DWMWA_TEXT_COLOR`` (36) take the theme's panel and text colours. On Windows 10 these three
  calls are not made;
* Windows 10 only: ``SetWindowPos(SWP_FRAMECHANGED)`` so the title bar repaints at once instead of
  at the next click.

Every native call is wrapped: a failure (an older Windows, a window that is gone) is logged once
and ignored. Off Windows nothing here does anything. Native message boxes and file dialogs are
drawn by Windows with its own title bar: the app cannot theme them.

Kill switch: the config key ``native_window_theme`` set to false (``set_enabled``), or the
environment variable ``WTS_NO_NATIVE_CHROME`` set to anything but ``0``/``false``, turns every
call here off.

Prior art: the attribute numbers and the colour byte order (COLORREF is ``0x00BBGGRR``) follow
Microsoft's ``DWMWINDOWATTRIBUTE`` documentation
(https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute) and the
pywinstyles package (https://github.com/Akascape/py-window-styles), which sets 19 and 20 together
and 34/35/36 for border, caption and text, with no Windows build check. Taken from pywinstyles:
the attribute numbers and the RGB-to-BGR conversion only. This app tries 20 and falls back to 19
only when 20 is refused, calls the colour attributes on Windows 11 only, redraws the Windows 10
frame, finds the frame window from Tk, themes later dialogs and ignores every failure.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import tkinter as tk
from typing import Any

from app.theme import tokens

logger = logging.getLogger(__name__)

ENV_KILL_SWITCH = "WTS_NO_NATIVE_CHROME"

# Adapted from pywinstyles (https://github.com/Akascape/py-window-styles) — the DWM attribute numbers.
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20

WINDOWS_11_BUILD = 22000

# SetWindowPos flags for a frame-only redraw: no move, no size, no z-order, no activation.
_SWP_REDRAW_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE NOMOVE NOZORDER NOACTIVATE FRAMECHANGED

# Frame colours = sv_ttk's panel and text colours of each theme: (caption/border, text).
_FRAME_COLOURS = {
    "dark": (tokens.DARK_PANELS[0], tokens.LIGHT_PANEL),
    "light": (tokens.LIGHT_PANEL, tokens.DARK_PANELS[0]),
}

_MARK = "_wts_chrome_theme"   # attribute on a themed Toplevel: the theme its frame has

# Process-wide state (reset by tests/conftest.py).
_config_enabled = True
_failed: set[str] = set()
_theme = "light"
_native_cache: Any = None


def set_enabled(enabled: bool) -> None:
    """The config switch (``native_window_theme``); the environment variable is read live."""
    global _config_enabled
    _config_enabled = bool(enabled)


def env_disabled() -> bool:
    value = os.environ.get(ENV_KILL_SWITCH, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def _platform() -> str:
    return sys.platform


def enabled(platform: str | None = None) -> bool:
    """True when DWM calls are allowed: Windows, config on, environment switch off."""
    if (platform or _platform()) != "win32":
        return False
    return _config_enabled and not env_disabled()


def windows_build() -> int:
    """The Windows build number (19045 = Windows 10 22H2, 22000+ = Windows 11); 0 off Windows."""
    getter = getattr(sys, "getwindowsversion", None)
    if getter is None:
        return 0
    try:
        return int(getter().build)
    except Exception:  # noqa: BLE001
        return 0


def colorref(rgb: str) -> int:
    """``"#rrggbb"`` as the Windows COLORREF integer ``0x00BBGGRR``."""
    # Adapted from pywinstyles (https://github.com/Akascape/py-window-styles) — RGB to BGR order.
    text = rgb.lstrip("#")
    r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    return (b << 16) | (g << 8) | r


# ------------------------------------------------------------------------- native layer

class _Native:
    """The few Win32 functions used, with explicit types (64-bit handles are not ints)."""

    def __init__(self) -> None:
        from ctypes import wintypes
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)  # type: ignore[attr-defined]
        user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        self._set = dwm.DwmSetWindowAttribute
        self._set.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self._set.restype = ctypes.c_long
        self._get = dwm.DwmGetWindowAttribute
        self._get.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self._get.restype = ctypes.c_long
        self._parent = user32.GetParent
        self._parent.argtypes = [wintypes.HWND]
        self._parent.restype = wintypes.HWND
        self._pos = user32.SetWindowPos
        self._pos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self._pos.restype = wintypes.BOOL

    def parent(self, hwnd: int) -> int:
        return int(self._parent(hwnd) or 0)

    def set_attribute(self, hwnd: int, attribute: int, value: int) -> int:
        """DwmSetWindowAttribute with a 4-byte value; returns the HRESULT (0 = success)."""
        data = ctypes.c_int(value)
        return int(self._set(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)))

    def get_attribute(self, hwnd: int, attribute: int) -> tuple[int, int]:
        """``(hresult, value)`` of DwmGetWindowAttribute for a 4-byte attribute."""
        data = ctypes.c_int(-1)
        hresult = int(self._get(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)))
        return hresult, data.value

    def redraw_frame(self, hwnd: int) -> bool:
        return bool(self._pos(hwnd, None, 0, 0, 0, 0, _SWP_REDRAW_FLAGS))


def _native() -> Any:
    global _native_cache
    if _native_cache is None:
        _native_cache = _Native()
    return _native_cache


def _note_failure(key: str, message: str, *args: object) -> None:
    if key in _failed:
        return
    _failed.add(key)
    logger.info(message, *args)


def window_handle(widget: tk.Misc, native: Any = None) -> int:
    """The HWND of the frame Windows draws around a Tk top-level (0 = not found).

    Tk's ``winfo_id`` is the inner client window; its parent is the frame with the title bar.
    A window Tk has not shown yet (a transient dialog, for one) has no frame window: the answer
    is 0, never the inner window, because DWM accepts the call there and it would do nothing. The
    window is themed when it is shown (``<Map>``).
    """
    native = native or _native()
    widget.update_idletasks()
    return int(native.parent(int(widget.winfo_id())) or 0)


# ------------------------------------------------------------------------------- apply

def _set(native: Any, hwnd: int, attribute: int, value: int, results: dict[int, int]) -> bool:
    try:
        hresult = native.set_attribute(hwnd, attribute, value)
    except Exception as exc:  # noqa: BLE001 - any native failure is harmless
        results[attribute] = -1
        _note_failure(f"call-{attribute}", "DWM attribute %d call failed: %s", attribute, exc)
        return False
    results[attribute] = hresult
    if hresult != 0:
        _note_failure(f"hr-{attribute}", "DWM attribute %d refused (HRESULT %#x)",
                      attribute, hresult & 0xFFFFFFFF)
        return False
    return True


def apply(widget: tk.Misc, theme: str, *, native: Any = None, build: int | None = None,
          platform: str | None = None) -> dict[int, int]:
    """Give the top-level ``widget``'s frame the look of ``theme`` ("light" or anything = dark).

    Returns the HRESULT of each attribute tried (``{}`` when nothing was tried: not Windows,
    kill switch on, or no window handle). Never raises.
    """
    results: dict[int, int] = {}
    if not enabled(platform):
        return results
    resolved = "light" if theme == "light" else "dark"
    try:
        if native is None:
            native = _native()
        hwnd = window_handle(widget, native)
        if not hwnd:
            return results
        build = windows_build() if build is None else build
        dark = 1 if resolved == "dark" else 0
        ok = _set(native, hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, dark, results)
        if not ok:
            # Windows 10 before 18985 knows the dark flag only under the old number.
            ok = _set(native, hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, dark, results)
        if build >= WINDOWS_11_BUILD:
            panel, text = _FRAME_COLOURS[resolved]
            _set(native, hwnd, DWMWA_CAPTION_COLOR, colorref(panel), results)
            _set(native, hwnd, DWMWA_BORDER_COLOR, colorref(panel), results)
            _set(native, hwnd, DWMWA_TEXT_COLOR, colorref(text), results)
        elif ok:
            # Windows 10 repaints the title bar only when its frame is told to.
            try:
                native.redraw_frame(hwnd)
            except Exception as exc:  # noqa: BLE001
                _note_failure("redraw", "Frame redraw failed: %s", exc)
        if ok:
            setattr(widget, _MARK, resolved)
    except Exception as exc:  # noqa: BLE001 - never let the frame break a window
        _note_failure("apply", "Could not apply the window frame theme: %s", exc)
    return results


def _is_top_level(widget: object) -> bool:
    """A real window with a frame of its own: the root or a ``Toplevel`` (not a Menu, which Tk
    also reports as its own top-level)."""
    return isinstance(widget, (tk.Tk, tk.Toplevel))


def _top_levels(root: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack: list[tk.Misc] = [root]
    while stack:
        widget = stack.pop()
        if _is_top_level(widget):
            found.append(widget)
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue
    return found


def _has_frame(widget: tk.Misc) -> bool:
    """False for override-redirect windows (tooltips, menus): they have no title bar."""
    try:
        return not bool(widget.wm_overrideredirect())  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):
        return False


def apply_all(root: tk.Misc, theme: str) -> int:
    """Theme ``root`` and every open Toplevel under it; returns how many windows were themed.

    Also records ``theme`` as the one windows opened later get.
    """
    global _theme
    _theme = "light" if theme == "light" else "dark"
    if not enabled():
        return 0
    count = 0
    try:
        windows = _top_levels(root)
    except Exception as exc:  # noqa: BLE001 - a theme switch must never fail on the frame
        _note_failure("walk", "Could not list the windows to theme: %s", exc)
        return 0
    for widget in windows:
        if _has_frame(widget) and apply(widget, _theme):
            count += 1
    return count


def _on_map(event: Any) -> None:
    widget = event.widget
    if not _is_top_level(widget) or not _has_frame(widget):
        return
    if getattr(widget, _MARK, None) == _theme:
        return  # already themed: a minimise/restore must not redraw the frame again
    apply(widget, _theme)


def install(root: tk.Misc, theme: str) -> None:
    """Theme ``root`` in ``theme`` now, and every Toplevel when it is first shown (dialogs made later).

    Call once after the first theme is chosen; ``apply_all`` follows each theme switch.
    Does nothing off Windows or with the kill switch on.
    """
    if not enabled():
        return
    try:
        # One binding per Tcl interpreter (bind_class is interpreter-wide); the marker lives on
        # the root object, so a second root (tests) gets its own.
        if not getattr(root, "_wts_chrome_bound", False):
            root.bind_class("Toplevel", "<Map>", _on_map, add="+")
            setattr(root, "_wts_chrome_bound", True)
        apply_all(root, theme)
    except Exception as exc:  # noqa: BLE001
        _note_failure("install", "Could not install the window frame theme: %s", exc)


def reset_for_tests() -> None:
    """Forget process-wide state (used by the autouse fixture in tests/conftest.py)."""
    global _config_enabled, _theme, _native_cache
    _config_enabled = True
    _theme = "light"
    _native_cache = None
    _failed.clear()
