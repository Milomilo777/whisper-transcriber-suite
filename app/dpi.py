"""Windows display-scaling helpers.

Without a DPI-awareness declaration Windows renders the whole app at 96 dpi and
stretches the bitmap to the display's scale (125 %, 150 %, ...), which makes
every window blurry. ``enable_dpi_awareness`` declares the process DPI aware
before the Tk root exists, so Tk draws at the real resolution. Pixel values
written in code (window sizes, canvas heights) were chosen at 96 dpi; once the
process is aware they must be multiplied by ``scale_factor``.

macOS and Linux are untouched: the awareness call is Windows-only and
``scale_factor`` is 1.0 elsewhere.
"""
from __future__ import annotations

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
    import ctypes

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
            import ctypes

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


def scaled_size(
    widget: Any, width: int, height: int, margin_w: int = 40, margin_h: int = 90
) -> tuple[int, int]:
    """Window size designed at 96 dpi, scaled and kept inside the screen.

    The margins leave room for the title bar and the taskbar, so a size that
    fitted a small screen at 100 % cannot grow past it at 150 %.
    """
    factor = scale_factor(widget)
    if factor <= 1.0:
        return width, height
    w, h = int(round(width * factor)), int(round(height * factor))
    try:
        sw, sh = widget.winfo_screenwidth(), widget.winfo_screenheight()
    except Exception:  # noqa: BLE001
        return w, h
    return min(w, max(sw - margin_w, 1)), min(h, max(sh - margin_h, 1))
