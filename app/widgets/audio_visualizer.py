"""Live-audio visualizer for the Live tab (Tkinter/ttk): Siri-style sine waves.

Five overlapping sine curves whose amplitude follows the microphone level,
drawn on a fixed dark strip. The curve math, curve set and animation
defaults are ported from SiriWave's "classic" (iOS 7) style:

    SiriWave — https://github.com/kopiro/siriwave
    src/classic-curve.ts + src/index.ts
    MIT License, Copyright (c) 2020 Flavio Maria De Stefano
    (full notice in THIRD_PARTY_NOTICES.md)

Differences forced by Tk: a Tk ``Canvas`` has no alpha channel, so each
curve's opacity is pre-blended into its colour against the background, and
the animation runs on ``after()`` ticks instead of ``requestAnimationFrame``.
The amplitude/speed targets come from the captured PCM level rather than
from a caller's ``setAmplitude``.

Threading: the recorder calls :meth:`AudioVisualizer.push_frames` on its
own capture thread. That method only stores bytes under a lock and never
touches a widget. All canvas work happens in :meth:`_tick`, which runs on
the Tk main thread via ``after()`` and is gated by :meth:`set_active` so
an idle tab paints nothing per-frame.
"""
from __future__ import annotations

import array
import logging
import math
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: ~30 fps while listening: smooth motion, and only five ``coords`` updates
#: per frame (canvas items are created once and reused).
UPDATE_MS = 33

# Adapted from SiriWave (https://github.com/kopiro/siriwave) — classic-curve
# constants and default options (MIT, Copyright (c) 2020 Flavio Maria De Stefano).
ATT_FACTOR = 4
GRAPH_X = 2
AMPLITUDE_FACTOR = 0.6
FREQUENCY = 6
PIXEL_DEPTH = 0.02
LERP_SPEED = 0.1


@dataclass(frozen=True)
class Curve:
    attenuation: float
    line_width: float
    opacity: float


# SiriWave ClassicCurve.getDefinition(), drawn back to front.
CURVES: tuple[Curve, ...] = (
    Curve(-2, 1, 0.1),
    Curve(-6, 1, 0.2),
    Curve(4, 1, 0.4),
    Curve(2, 1, 0.6),
    Curve(1, 1.5, 1.0),
)

#: Resting amplitude while listening but silent: a faint, slowly moving
#: line says "the mic is live" without implying sound is coming in.
IDLE_AMPLITUDE = 0.04
MIN_SPEED = 0.08
MAX_SPEED = 0.22
#: dBFS range mapped onto amplitude 0..1. Measured on a real mic: room
#: silence sits near -64 dBFS, normal speech around -26 dBFS.
_FLOOR_DB = -60.0
_RANGE_DB = 45.0

_FULL_SCALE = 32768.0
# Fixed dark strip so the waves read the same under sv_ttk light/dark themes.
_BG = "#0f172a"
_BG_RGB = (15, 23, 42)
_WAVE_RGB = (56, 189, 248)  # sky blue, this app's tray/accent colour
_BASELINE = "#334155"


# ---------------------------------------------------------- pure helpers


def pcm_to_rms(pcm: bytes) -> float:
    """Normalised RMS (0..1) of mono int16 PCM. Empty input -> 0.0."""
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return 0.0
    try:
        import numpy as np  # type: ignore[import-not-found]

        arr = np.frombuffer(pcm[:usable], dtype=np.int16).astype("float32")
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(arr * arr)) / _FULL_SCALE)
    except ImportError:
        samples = array.array("h")
        samples.frombytes(pcm[:usable])
        if not samples:
            return 0.0
        total = 0
        for s in samples:
            total += s * s
        return math.sqrt(total / len(samples)) / _FULL_SCALE


def level_from_rms(rms: float) -> float:
    """Map linear RMS onto a perceptual 0..1 level (log / dB scale)."""
    if rms <= 0.0:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(1.0, (db - _FLOOR_DB) / _RANGE_DB))


def blend(opacity: float, fg: tuple[int, int, int] = _WAVE_RGB,
          bg: tuple[int, int, int] = _BG_RGB) -> str:
    """Hex colour of ``fg`` drawn at ``opacity`` over ``bg`` (Tk has no alpha)."""
    a = max(0.0, min(1.0, opacity))
    r, g, b = (int(round(f * a + k * (1.0 - a))) for f, k in zip(fg, bg))
    return f"#{r:02x}{g:02x}{b:02x}"


# Adapted from SiriWave (https://github.com/kopiro/siriwave) — ClassicCurve
# globalAttFn / xPos / yPos (MIT, Copyright (c) 2020 Flavio Maria De Stefano).
def _global_att(x: float) -> float:
    return (ATT_FACTOR / (ATT_FACTOR + x ** ATT_FACTOR)) ** ATT_FACTOR


_STEPS = int(round(2 * GRAPH_X / PIXEL_DEPTH))
_XS = tuple(-GRAPH_X + k * PIXEL_DEPTH for k in range(_STEPS + 1))
_ATTS = tuple(_global_att(x) for x in _XS)


def curve_points(
    curve: Curve, width: float, height_max: float, amplitude: float, phase: float
) -> list[float]:
    """Flat ``[x0, y0, x1, y1, ...]`` for one curve across ``width`` px.

    ``height_max`` is the vertical centre line (and the maximum excursion);
    ``amplitude`` is 0..1.
    """
    out: list[float] = []
    scale = AMPLITUDE_FACTOR * height_max * amplitude / curve.attenuation
    for x, att in zip(_XS, _ATTS):
        out.append(width * ((x + GRAPH_X) / (GRAPH_X * 2)))
        out.append(height_max + att * scale * math.sin(FREQUENCY * x - phase))
    return out


def lerp(v0: float, v1: float, t: float = LERP_SPEED) -> float:
    return v0 * (1.0 - t) + v1 * t


# -------------------------------------------------------------- widget


class AudioVisualizer:
    """Siri-style sine-wave level display for the Live tab.

    Implemented as a small controller object owning a ``tk.Canvas``
    (rather than subclassing ``ttk.Frame``) so tests can drive the pure
    parts without Tk and the tab can embed just ``.frame``.
    """

    def __init__(self, parent: Any, height: int = 110) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.height = max(40, int(height))
        self.frame = ttk.Frame(parent)
        self.canvas = tk.Canvas(
            self.frame, height=self.height, bg=_BG, highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self._lock = threading.Lock()
        self._pending: bytes | None = None
        self._active = False
        self._after_id: str | None = None
        self.amplitude = 0.0
        self.speed = MIN_SPEED
        self.phase = 0.0
        self._target_amplitude = 0.0
        self._target_speed = MIN_SPEED
        self._line_ids: list[int] = []
        self.frame.bind("<Destroy>", lambda _e: self._on_destroy())
        self._draw_idle()

    # -- thread-safe input ------------------------------------------

    def push_frames(self, pcm: bytes, _rate: int = 0) -> None:
        """Store the latest block. Safe to call from any thread.

        Never touches a widget — the ``after()`` tick on the Tk thread
        picks the block up and does the level maths + drawing.
        """
        if not pcm:
            return
        with self._lock:
            # Keep only the newest block; an older one is stale meter data.
            self._pending = bytes(pcm[-8192:]) if len(pcm) > 8192 else bytes(pcm)

    def set_active(self, active: bool) -> None:
        """Start/stop the redraw loop. Idle paints one flat baseline."""
        self._active = bool(active)
        if self._active:
            self._target_amplitude = IDLE_AMPLITUDE
            self._schedule()
        else:
            self._cancel()
            self._take_pending()  # drop any stale block so it can't leak into the next session
            self.amplitude = 0.0
            self._target_amplitude = 0.0
            self.speed = self._target_speed = MIN_SPEED
            self.phase = 0.0
            try:
                self._draw_idle()
            except Exception:  # noqa: BLE001
                logger.debug("Visualizer idle draw failed", exc_info=True)

    # -- main-thread drawing -----------------------------------------

    def _schedule(self) -> None:
        try:
            if self._after_id is None and self._active:
                self._after_id = self.frame.after(UPDATE_MS, self._tick)
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer schedule failed", exc_info=True)

    def _cancel(self) -> None:
        try:
            if self._after_id is not None:
                self.frame.after_cancel(self._after_id)
        except Exception:  # noqa: BLE001
            pass
        self._after_id = None

    def _on_destroy(self) -> None:
        self._active = False
        self._cancel()

    def _take_pending(self) -> bytes | None:
        with self._lock:
            pcm = self._pending
            self._pending = None
            return pcm

    def _tick(self) -> None:
        self._after_id = None
        if not self._active:
            return
        try:
            pcm = self._take_pending()
            if pcm:
                level = level_from_rms(pcm_to_rms(pcm))
                self._target_amplitude = IDLE_AMPLITUDE + (1.0 - IDLE_AMPLITUDE) * level
                self._target_speed = MIN_SPEED + (MAX_SPEED - MIN_SPEED) * level
            else:
                # No fresh audio this frame: ease back toward the resting wave.
                self._target_amplitude = lerp(self._target_amplitude, IDLE_AMPLITUDE, 0.15)
                self._target_speed = lerp(self._target_speed, MIN_SPEED, 0.15)
            # Adapted from SiriWave (https://github.com/kopiro/siriwave) —
            # lerp'd amplitude/speed and phase advance per frame (MIT).
            self.amplitude = lerp(self.amplitude, self._target_amplitude, 0.3)
            self.speed = lerp(self.speed, self._target_speed)
            self.phase = (self.phase + (math.pi / 2) * self.speed) % (2 * math.pi)
            self._draw()
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer tick failed", exc_info=True)
        finally:
            self._schedule()

    # -- canvas -------------------------------------------------------

    def _width(self) -> int:
        try:
            return max(1, int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth() or 320))
        except Exception:  # noqa: BLE001
            return 320

    def _draw(self) -> None:
        c = self.canvas
        if not self._line_ids:
            c.delete("all")
            self._line_ids = [
                c.create_line(0, 0, 1, 1, fill=blend(cv.opacity),
                              width=cv.line_width, smooth=True, capstyle="round")
                for cv in CURVES
            ]
        width = self._width()
        height_max = self.height / 2 - 6
        for line_id, cv in zip(self._line_ids, CURVES):
            c.coords(line_id, *curve_points(cv, width, height_max, self.amplitude, self.phase))

    def _draw_idle(self) -> None:
        c = self.canvas
        try:
            c.delete("all")
            self._line_ids = []
            mid = self.height // 2
            c.create_line(0, mid, self._width(), mid, fill=_BASELINE, width=1)
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer idle clear failed", exc_info=True)
