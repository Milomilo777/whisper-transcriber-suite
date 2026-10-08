"""Windows display-scaling helpers.

Without a DPI-awareness declaration Windows renders the whole app at 96 dpi and
stretches the bitmap to the display's scale (125 %, 150 %, ...), which makes
every window blurry. ``enable_dpi_awareness`` declares the process DPI aware
before the Tk root exists, so Tk draws at the real resolution. Pixel values
written in code (window sizes, canvas heights) were chosen at 96 dpi; once the
process is aware they must be multiplied by ``scale_factor``.

macOS and Linux are untouched: the awareness call is Windows-only and
``scale_factor`` is 1.0 elsewhere. Window sizes are kept inside the usable area of the
monitor at every scale (``scaled_size``); on Windows that is the work area, which leaves out
the taskbar.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+).
_CONTEXT_PER_MONITOR_V2 = -4
# PROCESS_PER_MONITOR_DPI_AWARE (shcore, Windows 8.1+).
_PROCESS_PER_MONITOR = 2
# HRESULT E_ACCESSDENIED: the awareness was already fixed (manifest or an
# earlier call); it cannot be changed again and is not an error for us.
_E_ACCESSDENIED = -2147024891

_BASE_DPI = 96.0

_awareness_result: str | None = None


def _declare(windll: Any) -> str:
    """Try the awareness APIs from newest to oldest; return which one worked."""
    user32 = windll.user32
    try:
        set_context = user32.SetProcessDpiAwarenessContext
        # The argument is a HANDLE: without argtypes ctypes would pass a
        # 32-bit int and the call would fail on 64-bit Windows.
        set_context.argtypes = [ctypes.c_void_p]
        if set_context(ctypes.c_void_p(_CONTEXT_PER_MONITOR_V2)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass  # Windows older than 10 1703

    try:
        hresult = windll.shcore.SetProcessDpiAwareness(_PROCESS_PER_MONITOR)
        if hresult == 0:
            return "per-monitor"
        if hresult == _E_ACCESSDENIED:
            return "already-set"
    except (AttributeError, OSError):
        pass  # Windows older than 8.1

    try:
        if user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return "unavailable"


def enable_dpi_awareness(
    platform: str | None = None, windll: Any = None
) -> str:
    """Declare the process DPI aware (Windows only); call before creating Tk.

    Runs the Windows call at most once per process; later calls return the
    first result. Returns ``"skipped"`` off Windows, otherwise the API that
    succeeded (``per-monitor-v2``, ``per-monitor``, ``system``,
    ``already-set``) or ``"unavailable"``. ``platform`` and ``windll`` exist
    for tests.
    """
    global _awareness_result
    if _awareness_result is not None:
        return _awareness_result
    if (platform or sys.platform) != "win32":
        return "skipped"
    try:
        if windll is None:
            windll = ctypes.windll  # type: ignore[attr-defined]
        _awareness_result = _declare(windll)
    except Exception as exc:  # noqa: BLE001 - never block start-up on this
        logger.info("Could not set DPI awareness: %s", exc)
        _awareness_result = "unavailable"
    logger.info("DPI awareness: %s", _awareness_result)
    return _awareness_result


def scale_factor(widget: Any) -> float:
    """Display scale relative to 96 dpi (1.0, 1.25, 1.5, ...); 1.0 off Windows."""
    if sys.platform != "win32":
        return 1.0
    try:
        factor = float(widget.winfo_fpixels("1i")) / _BASE_DPI
    except Exception:  # noqa: BLE001
        return 1.0
    return min(max(round(factor, 2), 1.0), 4.0)


def scaled(widget: Any, pixels: int) -> int:
    """``pixels`` (designed at 96 dpi) converted to the current display scale."""
    return int(round(pixels * scale_factor(widget)))


_process_factor = 1.0


def remember_scale(widget: Any) -> float:
    """Store the display scale for ``px``; call once when the main window exists.

    The process keeps the scale it started with (Tk does not follow a move to a monitor with
    another scale, WM_DPICHANGED), so one factor serves every widget built later.
    """
    global _process_factor
    _process_factor = scale_factor(widget)
    return _process_factor


def px(pixels: int) -> int:
    """``pixels`` (designed at 96 dpi) at the scale ``remember_scale`` stored (1.0 before)."""
    return int(round(pixels * _process_factor))


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]


_MONITOR_DEFAULTTONEAREST = 2


def _windows_work_area(widget: Any) -> tuple[int, int, int, int] | None:
    """Work area (without the taskbar) of the monitor that holds ``widget``'s window."""
    try:
        hwnd = int(widget.winfo_id())
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
        monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), _MONITOR_DEFAULTTONEAREST)
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
    except Exception:  # noqa: BLE001 - no window yet, a test stand-in, no user32
        return None
    work = info.rcWork
    width, height = work.right - work.left, work.bottom - work.top
    if width <= 0 or height <= 0:
        return None
    return work.left, work.top, width, height


def work_area(widget: Any) -> tuple[int, int, int, int, bool]:
    """``(x, y, width, height, exact)`` of the screen area a window of ``widget`` may use.

    On Windows this is the work area of the widget's monitor (the taskbar excluded) and
    ``exact`` is True; elsewhere, or when Windows cannot say, the whole screen at (0, 0)
    with ``exact`` False (macOS menu bar and Dock, Linux panels are not known).
    """
    if sys.platform == "win32":
        area = _windows_work_area(widget)
        if area is not None:
            return (*area, True)
    try:
        width, height = int(widget.winfo_screenwidth()), int(widget.winfo_screenheight())
    except Exception:  # noqa: BLE001
        width, height = 0, 0
    return 0, 0, width, height, False


# Room around a window inside the usable area, in pixels at 96 dpi: the title bar and the
# frame when the work area is known, plus the taskbar / menu bar / Dock when only the screen is.
_MARGIN_EXACT = (16, 48)
_MARGIN_SCREEN = (40, 90)
_MIN_SIZE = (320, 240)   # a fitted window never shrinks below this (if the request was larger)


def fit_size(widget: Any, width: int, height: int) -> tuple[int, int]:
    """Pixel size ``width`` x ``height`` (already scaled) kept inside the usable area."""
    _x, _y, area_w, area_h, exact = work_area(widget)
    if area_w <= 0 or area_h <= 0:
        return width, height
    factor = scale_factor(widget)
    margin_w, margin_h = _MARGIN_EXACT if exact else _MARGIN_SCREEN
    room_w = max(area_w - int(round(margin_w * factor)), 1)
    room_h = max(area_h - int(round(margin_h * factor)), 1)
    floor_w = min(width, int(round(_MIN_SIZE[0] * factor)))
    floor_h = min(height, int(round(_MIN_SIZE[1] * factor)))
    return max(min(width, room_w), floor_w), max(min(height, room_h), floor_h)


def scaled_size(widget: Any, width: int, height: int) -> tuple[int, int]:
    """Window size designed at 96 dpi, scaled and kept inside the usable screen area.

    Clamped at every scale, 100 % included: a 1180x720 window does not fit a 1366x768 laptop
    once the taskbar and the title bar take their share. The margins scale with the display.
    """
    factor = scale_factor(widget)
    return fit_size(widget, int(round(width * factor)), int(round(height * factor)))
