"""Live-audio visualizer for the Live tab: iOS 9 Siri waves + a level meter.

Two parts, drawn into one image per frame:

* The wave: SiriWave's "ios9" style -- three coloured (blue, red, green)
  blobs of randomly spawned sine curves, blended additively ("lighter")
  so where they overlap they glow towards white, over a faint white
  support line. Curve maths, spawn/despawn behaviour, colours and
  defaults are ported from:

      SiriWave — https://github.com/kopiro/siriwave
      src/ios9-curve.ts + src/index.ts
      MIT License, Copyright (c) 2020 Flavio Maria De Stefano
      (full notice in THIRD_PARTY_NOTICES.md)

* The meter: a slim horizontal peak meter along the bottom edge,
  green / yellow / red zones with a short peak-hold marker and a dBFS
  readout -- the standard look of a DAW or OBS input meter, so clipping
  or a dead input is obvious at a glance.

Tk's ``Canvas`` has neither alpha nor additive blending, so frames are
composed with numpy + Pillow (2x supersampled for smooth edges) and shown
through one reused ``ImageTk.PhotoImage``.

Threading: the recorder calls :meth:`AudioVisualizer.push_frames` on its
own capture thread. That method only stores bytes under a lock and never
touches a widget. All drawing happens in :meth:`_tick`, which runs on
the Tk main thread via ``after()`` and is gated by :meth:`set_active` so
an idle tab paints nothing per frame.
"""
from __future__ import annotations

import array
import logging
import math
import random
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: ~30 fps while listening.
UPDATE_MS = 33

# Adapted from SiriWave (https://github.com/kopiro/siriwave) — iOS9Curve
# constants, default ranges and SiriWave's default options
# (MIT, Copyright (c) 2020 Flavio Maria De Stefano).
GRAPH_X = 25.0
AMPLITUDE_FACTOR = 0.8
SPEED_FACTOR = 1.0
DEAD_PX = 2.0
ATT_FACTOR = 4.0
DESPAWN_FACTOR = 0.02
NOOFCURVES_RANGE = (2.0, 5.0)
AMPLITUDE_RANGE = (0.3, 1.0)
OFFSET_RANGE = (-3.0, 3.0)
WIDTH_RANGE = (1.0, 3.0)
SPEED_RANGE = (0.5, 1.0)
DESPAWN_TIMEOUT_RANGE_MS = (500.0, 2000.0)
GLOBAL_ALPHA = 0.7
LERP_SPEED = 0.1
#: SiriWave samples every 0.02 units across 2 * GRAPH_X; 0.05 gives the
#: same shape at a width this strip actually has, for 2.5x fewer points.
PIXEL_DEPTH = 0.05

#: Not in SiriWave: its blobs peak around a quarter of the half-height,
#: which in a short, wide strip like this one reads as a thin line. This
#: scales them up (clamped to the strip) so speech visibly fills it.
DISPLAY_GAIN = 3.5

#: SiriWave iOS9Curve.getDefinition() colours: blue, red, green.
WAVE_COLORS: tuple[tuple[int, int, int], ...] = (
    (15, 82, 169),
    (173, 57, 76),
    (48, 220, 155),
)

#: Resting amplitude while listening but silent: the support line alone
#: says "the mic is live"; a small shimmer confirms the loop is running.
IDLE_AMPLITUDE = 0.03
MIN_SPEED = 0.12
MAX_SPEED = 0.3

#: dBFS range mapped onto amplitude 0..1. Measured on a real mic: room
#: silence sits near -64 dBFS, normal speech around -26 dBFS.
_FLOOR_DB = -60.0
_RANGE_DB = 45.0
#: Meter scale: -60 dBFS .. 0 dBFS; zones like a DAW input meter.
METER_FLOOR_DB = -60.0
METER_YELLOW_DB = -18.0
METER_RED_DB = -6.0
PEAK_HOLD_S = 1.2
PEAK_FALL_DB_PER_S = 20.0

_FULL_SCALE = 32768.0
_SUPERSAMPLE = 2
_METER_H = 6  # px, final (not supersampled) height of the meter band
_BG_RGB = (6, 9, 20)
_BG = "#%02x%02x%02x" % _BG_RGB
_METER_TRACK_RGB = (30, 36, 52)
_METER_GREEN = (46, 204, 113)
_METER_YELLOW = (241, 196, 15)
_METER_RED = (231, 76, 60)


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


def pcm_to_peak(pcm: bytes) -> float:
    """Normalised absolute peak (0..1) of mono int16 PCM."""
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[:usable])
    if not samples:
        return 0.0
    return min(1.0, max(abs(max(samples)), abs(min(samples))) / _FULL_SCALE)


def to_dbfs(value: float) -> float:
    """Linear 0..1 -> dBFS, floored at :data:`METER_FLOOR_DB`."""
    if value <= 0.0:
        return METER_FLOOR_DB
    return max(METER_FLOOR_DB, 20.0 * math.log10(value))


def level_from_rms(rms: float) -> float:
    """Map linear RMS onto a perceptual 0..1 level (log / dB scale)."""
    if rms <= 0.0:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(1.0, (db - _FLOOR_DB) / _RANGE_DB))


def meter_fraction(db: float) -> float:
    """dBFS -> 0..1 position along the meter."""
    return max(0.0, min(1.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))


def lerp(v0: float, v1: float, t: float = LERP_SPEED) -> float:
    return v0 * (1.0 - t) + v1 * t


# Adapted from SiriWave (https://github.com/kopiro/siriwave) — iOS9Curve
# globalAttFn (MIT, Copyright (c) 2020 Flavio Maria De Stefano).
def global_att(x: Any) -> Any:
    """Bell-shaped attenuation; works on floats and numpy arrays."""
    return (ATT_FACTOR / (ATT_FACTOR + x ** 2)) ** ATT_FACTOR


class IOS9Curve:
    """One coloured blob of SiriWave's iOS 9 style.

    Adapted from SiriWave (https://github.com/kopiro/siriwave) —
    src/ios9-curve.ts (MIT, Copyright (c) 2020 Flavio Maria De Stefano):
    spawns 2-4 sub-curves with random offset/width/speed/amplitude, grows
    them in, lets them die out after a random timeout, and respawns once
    the whole blob has collapsed below DEAD_PX.
    """

    def __init__(self, color: tuple[int, int, int],
                 rng: "random.Random | None" = None,
                 clock: "Callable[[], float] | None" = None) -> None:
        self.color = color
        self._rng = rng or random.Random()
        self._clock = clock or (lambda: time.monotonic() * 1000.0)
        self.spawn_at = 0.0
        # SiriWave uses spawnAt === 0 as "respawn next frame"; a separate
        # flag keeps that working with a clock that can legitimately read 0.
        self.needs_spawn = True
        self.no_of_curves = 0
        self.prev_max_y = 0.0
        self.phases: list[float] = []
        self.amplitudes: list[float] = []
        self.despawn_timeouts: list[float] = []
        self.offsets: list[float] = []
        self.speeds: list[float] = []
        self.final_amplitudes: list[float] = []
        self.widths: list[float] = []
        self.verses: list[float] = []

    def _rand(self, r: tuple[float, float]) -> float:
        return r[0] + self._rng.random() * (r[1] - r[0])

    def spawn(self) -> None:
        self.needs_spawn = False
        self.spawn_at = self._clock()
        n = int(math.floor(self._rand(NOOFCURVES_RANGE)))
        self.no_of_curves = n
        self.phases = [0.0] * n
        self.amplitudes = [0.0] * n
        self.despawn_timeouts = [self._rand(DESPAWN_TIMEOUT_RANGE_MS) for _ in range(n)]
        self.offsets = [self._rand(OFFSET_RANGE) for _ in range(n)]
        self.speeds = [self._rand(SPEED_RANGE) for _ in range(n)]
        self.final_amplitudes = [self._rand(AMPLITUDE_RANGE) for _ in range(n)]
        self.widths = [self._rand(WIDTH_RANGE) for _ in range(n)]
        self.verses = [self._rand((-1.0, 1.0)) for _ in range(n)]

    def advance(self, speed: float, frames: float = 1.0) -> None:
        """Grow/decay each sub-curve and advance its phase.

        SiriWave steps once per ``requestAnimationFrame`` (~60 fps); this
        runs on a slower ``after()`` loop, so ``frames`` says how many
        60 fps frames the tick stands for and scales every step to match.
        """
        if self.needs_spawn:
            self.spawn()
        now = self._clock()
        for ci in range(self.no_of_curves):
            if self.spawn_at + self.despawn_timeouts[ci] <= now:
                self.amplitudes[ci] -= DESPAWN_FACTOR * frames
            else:
                self.amplitudes[ci] += DESPAWN_FACTOR * frames
            self.amplitudes[ci] = min(max(self.amplitudes[ci], 0.0), self.final_amplitudes[ci])
            self.phases[ci] = (
                self.phases[ci] + speed * self.speeds[ci] * SPEED_FACTOR * frames
            ) % (2 * math.pi)

    def y_values(self, i: Any, height_max: float, amplitude: float) -> Any:
        """Vectorised yPos over the numpy array ``i`` (-GRAPH_X..GRAPH_X)."""
        import numpy as np  # type: ignore[import-not-found]

        y = np.zeros_like(i)
        n = self.no_of_curves
        for ci in range(n):
            # Static spread so the sub-curves sit apart, plus a random offset.
            t = 4 * (-1 + (ci / (n - 1)) * 2) if n > 1 else 0.0
            t += self.offsets[ci]
            x = i * (1 / self.widths[ci]) - t
            y += np.abs(self.amplitudes[ci] * np.sin(self.verses[ci] * x - self.phases[ci])
                        * global_att(x))
        if n:
            y /= n
        y = AMPLITUDE_FACTOR * height_max * amplitude * y * global_att((i / GRAPH_X) * 2)
        return np.minimum(y * DISPLAY_GAIN, height_max - 2 * _SUPERSAMPLE)

    def note_max_y(self, max_y: float) -> None:
        """Respawn once the blob has faded out (SiriWave's DEAD_PX rule)."""
        if max_y < DEAD_PX and self.prev_max_y > max_y:
            self.needs_spawn = True
        self.prev_max_y = max_y


_background_cache: dict[tuple[int, int], Any] = {}


def _wave_background(w: int, h: int, row: int) -> Any:
    """Cached float32 background + faded support line for one strip size."""
    import numpy as np  # type: ignore[import-not-found]

    key = (w, h)
    bg = _background_cache.get(key)
    if bg is None:
        bg = np.empty((h, w, 3), dtype=np.float32)
        bg[:] = _BG_RGB
        # Support line: white, faded at both ends (SiriWave ios9 gradient
        # stops 0 / 0.1 / 0.8 / 1 at 50% white, drawn at globalAlpha).
        xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
        ramp = np.clip(np.minimum(xs / 0.1, (1.0 - xs) / 0.2), 0.0, 1.0) * 0.5
        bg[row:row + _SUPERSAMPLE, :, :] += (GLOBAL_ALPHA * 255.0 * ramp)[None, :, None]
        _background_cache.clear()
        _background_cache[key] = bg
    return bg


def render_frame(width: int, height: int, curves: "list[IOS9Curve]", amplitude: float,
                 meter_db: "float | None" = None, peak_db: "float | None" = None) -> Any:
    """Compose one RGB ``PIL.Image`` of the waves (+ meter when given)."""
    import numpy as np  # type: ignore[import-not-found]
    from PIL import Image, ImageDraw

    width, height = max(32, int(width)), max(48, int(height))
    ss = _SUPERSAMPLE
    wave_h = height - (_METER_H + 4 if meter_db is not None else 0)
    w, h = width * ss, wave_h * ss
    height_max = h / 2 - 6 * ss
    acc = _wave_background(w, h, int(height_max)).copy()

    i = np.arange(-GRAPH_X, GRAPH_X + PIXEL_DEPTH / 2, PIXEL_DEPTH, dtype=np.float64)
    px = w * ((i + GRAPH_X) / (GRAPH_X * 2))
    for curve in curves:
        y = curve.y_values(i, height_max, amplitude)
        max_y = float(y.max()) if y.size else 0.0
        curve.note_max_y(max_y / ss)
        if max_y < 0.5:
            continue
        # Only the blob's bounding box is rasterised and blended -- the
        # blobs cover a small part of the strip, so this is most of the
        # per-frame saving.
        visible = np.nonzero(y >= 0.25)[0]
        c0 = max(0, int(px[visible[0]]) - 1)
        c1 = min(w, int(px[visible[-1]]) + 2)
        r0 = max(0, int(height_max - max_y) - 1)
        r1 = min(h, int(height_max + max_y) + 2)
        if c1 <= c0 or r1 <= r0:
            continue
        mask = Image.new("L", (c1 - c0, r1 - r0), 0)
        draw = ImageDraw.Draw(mask)
        xs_local = (px - c0).tolist()
        for sign in (1, -1):
            draw.polygon(list(zip(xs_local, (height_max - sign * y - r0).tolist())), fill=255)
        m = np.asarray(mask, dtype=np.float32) * (GLOBAL_ALPHA / 255.0)
        acc[r0:r1, c0:c1] += m[:, :, None] * np.asarray(curve.color, dtype=np.float32)

    img = Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8), "RGB")
    img = img.reduce(ss) if ss > 1 else img
    if meter_db is None:
        return img

    out = Image.new("RGB", (width, height), _BG_RGB)
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    x0, x1 = 8, width - 8
    y0 = height - _METER_H - 3
    y1 = y0 + _METER_H - 1
    draw.rectangle((x0, y0, x1, y1), fill=_METER_TRACK_RGB)
    span = x1 - x0

    def xat(db: float) -> int:
        return x0 + int(round(span * meter_fraction(db)))

    level_x = xat(meter_db)
    for lo, hi, col in ((METER_FLOOR_DB, METER_YELLOW_DB, _METER_GREEN),
                        (METER_YELLOW_DB, METER_RED_DB, _METER_YELLOW),
                        (METER_RED_DB, 0.0, _METER_RED)):
        a, b = xat(lo), min(xat(hi), level_x)
        if b > a:
            draw.rectangle((a, y0, b, y1), fill=col)
    # Faint scale ticks every 12 dB.
    for db in range(int(METER_FLOOR_DB) + 12, 0, 12):
        tx = xat(float(db))
        draw.line((tx, y0, tx, y1), fill=_BG_RGB)
    if peak_db is not None and peak_db > METER_FLOOR_DB:
        px_ = xat(peak_db)
        col = _METER_RED if peak_db >= METER_RED_DB else (
            _METER_YELLOW if peak_db >= METER_YELLOW_DB else (230, 230, 230))
        draw.rectangle((max(x0, px_ - 1), y0 - 1, px_ + 1, y1 + 1), fill=col)
    return out


# -------------------------------------------------------------- widget


class AudioVisualizer:
    """iOS 9 Siri-wave display + input level meter for the Live tab.

    A small controller object owning a ``tk.Canvas`` (rather than a
    ``ttk.Frame`` subclass) so tests can drive the pure parts without Tk
    and the tab can embed just ``.frame``.
    """

    def __init__(self, parent: Any, height: int = 130) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.height = max(48, int(height))
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
        self._target_amplitude = 0.0
        self._target_speed = MIN_SPEED
        self.curves = [IOS9Curve(c) for c in WAVE_COLORS]
        self.meter_db = METER_FLOOR_DB
        self.peak_db = METER_FLOOR_DB
        self._peak_at = 0.0
        self._last_tick = time.monotonic()
        self._photo: Any = None
        self._photo_size: tuple[int, int] = (0, 0)
        self._image_id: int | None = None
        self._text_id: int | None = None
        self.frame.bind("<Destroy>", lambda _e: self._on_destroy())
        self.canvas.bind("<Configure>", lambda _e: self._on_resize())
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
        """Start/stop the redraw loop. Idle paints a still, flat strip."""
        self._active = bool(active)
        if self._active:
            self._target_amplitude = IDLE_AMPLITUDE
            self._last_tick = time.monotonic()
            self._schedule()
        else:
            self._cancel()
            self._take_pending()  # drop any stale block so it can't leak into the next session
            self.amplitude = 0.0
            self._target_amplitude = 0.0
            self.speed = self._target_speed = MIN_SPEED
            self.meter_db = self.peak_db = METER_FLOOR_DB
            self.curves = [IOS9Curve(c) for c in WAVE_COLORS]
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

    def _on_resize(self) -> None:
        if not self._active:
            try:
                self._draw_idle()
            except Exception:  # noqa: BLE001
                logger.debug("Visualizer resize redraw failed", exc_info=True)

    def _take_pending(self) -> bytes | None:
        with self._lock:
            pcm = self._pending
            self._pending = None
            return pcm

    def _update_levels(self, pcm: "bytes | None", dt: float) -> None:
        if pcm:
            level = level_from_rms(pcm_to_rms(pcm))
            self._target_amplitude = IDLE_AMPLITUDE + (1.0 - IDLE_AMPLITUDE) * level
            self._target_speed = MIN_SPEED + (MAX_SPEED - MIN_SPEED) * level
            peak = to_dbfs(pcm_to_peak(pcm))
            # Fast attack, smooth release -- a VU-style needle, not a jitter.
            self.meter_db = peak if peak > self.meter_db else lerp(self.meter_db, peak, 0.25)
        else:
            # No fresh audio this frame: ease back toward the resting wave.
            self._target_amplitude = lerp(self._target_amplitude, IDLE_AMPLITUDE, 0.15)
            self._target_speed = lerp(self._target_speed, MIN_SPEED, 0.15)
            self.meter_db = max(METER_FLOOR_DB, self.meter_db - PEAK_FALL_DB_PER_S * dt)
        now = time.monotonic()
        if self.meter_db >= self.peak_db:
            self.peak_db, self._peak_at = self.meter_db, now
        elif now - self._peak_at > PEAK_HOLD_S:
            self.peak_db = max(self.meter_db, self.peak_db - PEAK_FALL_DB_PER_S * dt)
        # Adapted from SiriWave (https://github.com/kopiro/siriwave) —
        # lerp'd amplitude/speed per frame (MIT).
        self.amplitude = lerp(self.amplitude, self._target_amplitude, 0.3)
        self.speed = lerp(self.speed, self._target_speed)

    def _tick(self) -> None:
        self._after_id = None
        if not self._active:
            return
        try:
            now = time.monotonic()
            dt = min(0.25, max(0.0, now - self._last_tick))
            self._last_tick = now
            self._update_levels(self._take_pending(), dt)
            for curve in self.curves:
                curve.advance(self.speed, frames=dt * 60.0)
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

    def _show(self, img: Any) -> None:
        from PIL import ImageTk

        c = self.canvas
        if self._photo is None or self._photo_size != img.size:
            self._photo = ImageTk.PhotoImage(img, master=c)
            self._photo_size = img.size
            c.delete("all")
            self._image_id = c.create_image(0, 0, image=self._photo, anchor="nw")
            self._text_id = c.create_text(
                img.size[0] - 10, 8, anchor="ne", fill="#94a3b8",
                font=("Segoe UI", 8), text="",
            )
        else:
            self._photo.paste(img)
        if self._text_id is not None:
            text = ("" if not self._active else
                    "-∞ dB" if self.meter_db <= METER_FLOOR_DB else
                    f"{self.meter_db:.0f} dB")
            c.itemconfigure(self._text_id, text=text)

    def _draw(self) -> None:
        img = render_frame(self._width(), self.height, self.curves, self.amplitude,
                           meter_db=self.meter_db, peak_db=self.peak_db)
        self._show(img)

    def _draw_idle(self) -> None:
        try:
            img = render_frame(self._width(), self.height, [], 0.0,
                               meter_db=METER_FLOOR_DB, peak_db=None)
            self._show(img)
        except Exception:  # noqa: BLE001
            logger.debug("Visualizer idle draw failed", exc_info=True)
