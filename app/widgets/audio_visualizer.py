"""Live-audio visualizer for the Live tab (Tkinter/ttk).

Inspiration (not a copy): ``homelab-00/TranscriptionSuite``'s
``dashboard/components/AudioVisualizer.tsx`` — a React/Electron canvas that
paints frequency bars from a Web Audio ``AnalyserNode`` (plus a time-domain
waveform overlay), with a 3-layer sine idle animation gated by ``isActive``.

That source is GPL-3.0-licensed, while this repo is BSD-3-Clause, so this
module is an independent implementation in the same spirit — no code was
ported line-for-line, and the toolkit differs anyway (Tk ``Canvas`` here
versus HTML canvas there).

Deliberate visible differences from the original:

* 16 log-spaced FFT bands instead of ~width/6 linear bins (theirs renders
  a hundred-plus thin bars on a wide window).
* Per-bar peak-hold caps that fall slowly — theirs has none.
* A bottom RMS level strip instead of their time-domain waveform overlay.
* Idle state is a single flat baseline with no animation loop, not their
  3-layer cyan/magenta/orange sine waves.
* Teal-to-amber bar gradient on a fixed dark slate strip, matching this
  app's tray-blue/teal accents rather than their cyan-to-magenta wash.

Threading: the recorder calls :meth:`AudioVisualizer.push_frames` on its
own capture thread. That method only stores bytes under a lock and never
touches a widget. All canvas work happens in :meth:`_tick`, which runs on
the Tk main thread via ``after()`` and is gated by :meth:`set_active` so
an idle tab paints nothing per-frame (same gating idea as their
``isActive`` prop, reimplemented for Tk).
"""
from __future__ import annotations

import array
import logging
import math
import threading
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

#: Bands shown. Theirs is ~width/6 linear bins (100+ on desktop); 16
#: log-spaced bands is chunkier, cheaper, and reads better at tab width.
NUM_BANDS = 16
#: UI refresh while listening. ~10 fps is plenty for a meter and keeps
#: per-frame FFT + canvas work trivial.
UPDATE_MS = 100
#: Smoothing: fast attack so onsets pop, slow release so bars fall gently.
ATTACK = 0.7
RELEASE = 0.25
#: Peak caps fall one step per tick by this amount (0..1 units).
PEAK_FALL = 0.04

_FULL_SCALE = 32768.0
# Fixed dark strip so bars read the same under sv_ttk light/dark themes.
_BG = "#0f172a"
_GRID = "#1e293b"
_BASELINE = "#334155"
_LOW_RGB = (34, 211, 238)  # teal
_HIGH_RGB = (251, 146, 60)  # amber


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


def _log_band_edges(n_fft_bins: int, num_bands: int = NUM_BANDS) -> list[tuple[int, int]]:
    """Split ``n_fft_bins`` FFT bins into ``num_bands`` log-spaced ranges."""
    if n_fft_bins <= 0 or num_bands <= 0:
        return []
    # Log-spaced boundaries from bin 1 to n_fft_bins (skip DC).
    edges: list[tuple[int, int]] = []
    lo_log = math.log10(1.0)
    hi_log = math.log10(float(n_fft_bins))
    for i in range(num_bands):
        lo = int(10.0 ** (lo_log + (hi_log - lo_log) * i / num_bands))
        hi = int(10.0 ** (lo_log + (hi_log - lo_log) * (i + 1) / num_bands))
        lo = max(1, min(lo, n_fft_bins - 1))
        hi = max(lo + 1, min(hi, n_fft_bins))
        edges.append((lo, hi))
    return edges


def compute_spectrum(pcm: bytes, num_bands: int = NUM_BANDS) -> list[float]:
    """Map mono int16 PCM to ``num_bands`` levels in 0..1.

    Uses a real FFT with log-spaced band grouping when numpy is present;
    otherwise falls back to an RMS-derived pseudo-spectrum (equal energy
    with a gentle high-frequency roll-off) so the widget still moves on
    minimal installs. Pure and synchronous — unit-testable with synth.
    """
    if num_bands <= 0:
        return []
    if len(pcm) < 2:
        return [0.0] * num_bands
    usable = len(pcm) - (len(pcm) % 2)
    try:
        import numpy as np  # type: ignore[import-not-found]

        arr = np.frombuffer(pcm[:usable], dtype=np.int16).astype("float32")
        arr = arr / _FULL_SCALE
        if arr.size == 0:
            return [0.0] * num_bands
        # Hann window to tame leakage, then magnitude spectrum.
        windowed = arr * np.hanning(arr.size)
        mags = np.abs(np.fft.rfft(windowed))
        # Drop DC; normalise by length so levels are comparable across
        # block sizes.
        mags = mags[1:] / max(1, arr.size)
        if mags.size == 0:
            return [0.0] * num_bands
        ref = float(np.max(mags))
        if ref <= 0.0:
            return [0.0] * num_bands
        out: list[float] = []
        for lo, hi in _log_band_edges(int(mags.size), num_bands):
            band = mags[lo:hi]
            peak = float(np.max(band)) if band.size else 0.0
            out.append(max(0.0, min(1.0, (peak / ref) ** 0.6)))
        # Scale by overall loudness so silence reads as silence even if
        # the relative peak normalisation above found a tiny maximum.
        loud = pcm_to_rms(pcm)
        if loud < 0.01:
            return [0.0] * num_bands
        gain = max(0.0, min(1.0, (loud - 0.01) / 0.2))
        return [v * gain for v in out]
    except ImportError:
        rms = pcm_to_rms(pcm)
        if rms <= 0.0:
            return [0.0] * num_bands
        # Pseudo-spectrum: same energy everywhere, tilted down at the top
        # so it still looks like a spectrum rather than a flat wall.
        return [
            max(0.0, min(1.0, rms * 3.0 * (1.0 - 0.5 * i / max(1, num_bands - 1))))
            for i in range(num_bands)
        ]


def heights_for_levels(levels: Sequence[float], height_px: int) -> list[int]:
    """Map 0..1 levels to integer pixel heights clamped to ``height_px``."""
    out: list[int] = []
    for v in levels:
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        if not math.isfinite(f):
            f = 0.0
        out.append(max(0, min(int(height_px), int(round(max(0.0, min(1.0, f)) * height_px)))))
    return out


def band_color(ratio: float) -> str:
    """Teal-to-amber gradient across the band index (0..1)."""
    r = max(0.0, min(1.0, ratio))
    red = int(_LOW_RGB[0] + r * (_HIGH_RGB[0] - _LOW_RGB[0]))
    green = int(_LOW_RGB[1] + r * (_HIGH_RGB[1] - _LOW_RGB[1]))
    blue = int(_LOW_RGB[2] + r * (_HIGH_RGB[2] - _LOW_RGB[2]))
    return f"#{red:02x}{green:02x}{blue:02x}"


# -------------------------------------------------------------- widget


class AudioVisualizer:
    """16-band spectrum meter + RMS level strip for the Live tab.

    Implemented as a small controller object owning a ``tk.Canvas``
    (rather than subclassing ``ttk.Frame``) so tests can drive the pure
    parts without Tk and the tab can embed just ``.frame``.
    """

    def __init__(self, parent: Any, num_bands: int = NUM_BANDS, height: int = 110) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.num_bands = max(1, int(num_bands))
        self.height = max(60, int(height))
        self.frame = ttk.Frame(parent)
        self.canvas = tk.Canvas(
            self.frame, height=self.height, bg=_BG, highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self._lock = threading.Lock()
        self._pending: bytes | None = None
        self._active = False
        self._after_id: str | None = None
        self._levels = [0.0] * self.num_bands
        self._peaks = [0.0] * self.num_bands
        self._rms = 0.0
        self._bar_ids: list[int] = []
        self._peak_ids: list[int] = []
        self._level_id: int | None = None
        self._baseline_id: int | None = None
        self.frame.bind("<Destroy>", lambda _e: self._on_destroy())
        self._draw_idle()

    # -- thread-safe input ------------------------------------------

    def push_frames(self, pcm: bytes, _rate: int = 0) -> None:
        """Store the latest block. Safe to call from any thread.

        Never touches a widget — the ``after()`` tick on the Tk thread
        picks the block up and does the FFT + drawing.
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
            self._schedule()
        else:
            self._cancel()
            self._take_pending()  # drop any stale block so it can't leak into the next session
            try:
                self._levels = [0.0] * self.num_bands
                self._peaks = [0.0] * self.num_bands
                self._rms = 0.0
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
                spectrum = compute_spectrum(pcm, self.num_bands)
                rms = pcm_to_rms(pcm)
                for i in range(self.num_bands):
                    target = spectrum[i] if i < len(spectrum) else 0.0
                    prev = self._levels[i]
                    rate = ATTACK if target > prev else RELEASE
                    self._levels[i] = prev + (target - prev) * rate
                    if self._levels[i] >= self._peaks[i]:
                        self._peaks[i] = self._levels[i]
                    else:
                        self._peaks[i] = max(0.0, self._peaks[i] - PEAK_FALL)
                self._rms = self._rms + (rms - self._rms) * 0.5
            else:
                # No fresh audio: let bars decay so a pause visibly settles.
                for i in range(self.num_bands):
                    self._levels[i] *= 1.0 - RELEASE
                    self._peaks[i] = max(self._levels[i], self._peaks[i] - PEAK_FALL)
                self._rms *= 0.9
            self._draw()
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer tick failed", exc_info=True)
        finally:
            self._schedule()

    # -- canvas -------------------------------------------------------

    def _draw(self) -> None:
        c = self.canvas
        try:
            width = max(1, int(c.winfo_width() or c.winfo_reqwidth() or 320))
        except Exception:  # noqa: BLE001
            width = 320
        meter_h = 10
        plot_h = max(20, self.height - meter_h - 6)
        c.delete("all")
        # Faint vertical grid.
        step = max(20, width // 16)
        for x in range(0, width, step):
            c.create_line(x, 0, x, plot_h, fill=_GRID, width=1)
        n = self.num_bands
        gap = 3
        slot = width / max(1, n)
        bar_w = max(2.0, slot - gap)
        heights = heights_for_levels(self._levels, plot_h)
        peak_h = heights_for_levels(self._peaks, plot_h)
        for i in range(n):
            x0 = i * slot + gap / 2.0
            x1 = x0 + bar_w
            h = heights[i] if i < len(heights) else 0
            y0 = plot_h - h
            c.create_rectangle(x0, y0, x1, plot_h, fill=band_color(i / max(1, n - 1)), outline="")
            ph = peak_h[i] if i < len(peak_h) else 0
            py = plot_h - ph
            c.create_line(x0, py, x1, py, fill="#e2e8f0", width=2)
        # Baseline when silent.
        c.create_line(0, plot_h, width, plot_h, fill=_BASELINE, width=1)
        # Bottom RMS strip.
        strip_y = plot_h + 3
        c.create_rectangle(0, strip_y, width, strip_y + 4, fill=_GRID, outline="")
        fill_w = max(0.0, min(1.0, self._rms * 3.0)) * width
        c.create_rectangle(0, strip_y, fill_w, strip_y + 4, fill="#38bdf8", outline="")

    def _draw_idle(self) -> None:
        c = self.canvas
        try:
            width = max(1, int(c.winfo_width() or c.winfo_reqwidth() or 320))
        except Exception:  # noqa: BLE001
            width = 320
        meter_h = 10
        plot_h = max(20, self.height - meter_h - 6)
        try:
            c.delete("all")
            mid = plot_h // 2
            c.create_line(0, mid, width, mid, fill=_BASELINE, width=2)
            c.create_line(0, plot_h, width, plot_h, fill=_BASELINE, width=1)
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer idle clear failed", exc_info=True)
