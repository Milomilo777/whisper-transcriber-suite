"""Transcription speed (x real time) and an honest time-remaining estimate.

Pure and clock-injectable, so the maths is tested without a model. The
engine feeds it the audio position it has reached (segment end times on the
source timeline), never the progress percent: diarisation reuses the top of
the percent band, so a percent-based rate would be wrong exactly when the
job is nearly done.

Rules:

* The clock is ``time.monotonic()`` with pauses taken out. The engine stops
  it while the job waits in its pause loop, so a paused job never looks slow.
  Pre-processing (slicing, denoise, vocal separation) runs before ``start()``
  and diarisation / alignment / writing run after ``finish()``, so neither
  counts. The engine's own voice detection and language detection run
  inside the decode call and do count: that is time the engine spends on
  the audio.
* The live speed is the average since the first segment: audio done after
  it divided by decode time after it (the start-up work before it, voice and
  language detection, would make every early estimate too slow). It is
  labelled "about" in the UI. A sliding window was tried first and dropped:
  decode speed depends on the audio content, and on real runs the window's
  swings predicted the time left worse (mean error 56 % vs 35 %, worst
  293 % vs 147 % over five recorded runs of tiny, small and turbo).
* The time left starts at ``remaining audio / smoothed speed`` once there
  are ``min_audio_s`` of audio and ``min_elapsed_s`` of decode time. Each
  update then counts the previous estimate down by the decode time passed
  and moves it toward the new ``remaining / speed`` by the fraction
  ``1 - exp(-dt / eta_tau_s)``: a burst of segments arriving together
  (dt = 0) cannot move it at all, a long gap lets it follow the new rate.
  It never goes below 0 and snaps to 0 when the decode ends.
* The final speed is the overall average: the whole span's audio length
  (the probed media duration, not the last segment end, so a silent tail
  counts) divided by the decode time.
* A resumed job measures only the part decoded after the resume (the
  checkpoint holds no timing from the first run).

Never feed this from the hardware wizard's benchmark (a silent clip with
voice detection off): it would report a speed no real file reaches.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable

# Live-number tuning. Kept as module constants so tests can name them.
MIN_AUDIO_S = 30.0
MIN_ELAPSED_S = 3.0
ETA_TAU_S = 20.0
# A speed computed over less decode time than this is noise.
_MIN_SPEED_DT = 0.5


def eta_weight(dt: float) -> float:
    """How far one update moves the time left toward the new estimate."""
    return 1.0 - math.exp(-max(0.0, dt) / ETA_TAU_S)


def _finite(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


class SpeedMeter:
    """Track decode speed and time left for one span of audio.

    ``start_pos_s`` / ``end_pos_s`` bound the span on the source timeline
    (a time range or a resumed tail does not start at 0). ``end_pos_s <=
    start_pos_s`` means the length is unknown: no time left is shown, and
    the final average falls back to the last position reached.
    """

    def __init__(
        self,
        end_pos_s: float,
        start_pos_s: float = 0.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        min_audio_s: float = MIN_AUDIO_S,
        min_elapsed_s: float = MIN_ELAPSED_S,
    ) -> None:
        self.start_pos = max(0.0, _finite(start_pos_s))
        self.end_pos = _finite(end_pos_s)
        self._clock = clock
        self._min_audio = min_audio_s
        self._min_elapsed = min_elapsed_s
        self._t0: float | None = None
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._finished_elapsed: float | None = None
        self.pos = self.start_pos
        # (decode seconds, position) at the first segment: the live speed's
        # baseline. None until the first update.
        self._base: tuple[float, float] | None = None
        self._speed: float | None = None
        self._eta: float | None = None
        self._eta_t = 0.0

    # -- clock ---------------------------------------------------------

    @property
    def known_length(self) -> bool:
        return self.end_pos > self.start_pos

    def start(self) -> None:
        if self._t0 is None:
            self._t0 = self._clock()

    def pause(self) -> None:
        if self._t0 is not None and self._paused_at is None:
            self._paused_at = self._clock()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += max(0.0, self._clock() - self._paused_at)
            self._paused_at = None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def elapsed(self) -> float:
        """Decode seconds so far, pauses excluded."""
        if self._finished_elapsed is not None:
            return self._finished_elapsed
        if self._t0 is None:
            return 0.0
        now = self._paused_at if self._paused_at is not None else self._clock()
        return max(0.0, now - self._t0 - self._paused_total)

    # -- samples -------------------------------------------------------

    def update(self, pos_s: float) -> None:
        """Record that the engine reached ``pos_s`` on the source timeline.

        A position behind the furthest one (a loop-guard restart decodes
        part of the audio again) never moves the meter backwards.
        """
        if self._finished_elapsed is not None:
            return
        self.start()
        self.pos = max(self.pos, _finite(pos_s))
        t = self.elapsed()
        if self._base is None:
            # The first segment is the live speed's baseline (see the module
            # docstring). The final average still counts the time before it.
            self._base = (t, self.pos)
            self._update_eta(t)
            return
        t_old, p_old = self._base
        dt = t - t_old
        dp = self.pos - p_old
        self._speed = dp / dt if (dt >= _MIN_SPEED_DT and dp > 0) else None
        self._update_eta(t)

    def _ready(self, t: float) -> bool:
        return (
            self.known_length
            and (self.pos - self.start_pos) >= self._min_audio
            and t >= self._min_elapsed
        )

    def _update_eta(self, t: float) -> None:
        remaining = max(0.0, self.end_pos - self.pos)
        if not self.known_length:
            self._eta = None
            return
        if remaining <= 0.0 and self._eta is not None:
            self._eta = 0.0
            self._eta_t = t
            return
        if self._eta is None:
            if not self._ready(t) or not self._speed:
                return
            self._eta = remaining / self._speed
            self._eta_t = t
            return
        dt = t - self._eta_t
        expected = max(0.0, self._eta - dt)
        # No usable rate right now (no new audio inside the window): aim at
        # the last estimate instead of counting it down to a false zero.
        raw = remaining / self._speed if self._speed else self._eta
        self._eta = max(0.0, expected + eta_weight(dt) * (raw - expected))
        self._eta_t = t

    def finish(self) -> None:
        """The decode ended: stop the clock and snap the time left to 0."""
        if self._finished_elapsed is not None:
            return
        self.start()
        self.resume()
        self._finished_elapsed = self.elapsed()
        if self.known_length:
            self.pos = max(self.pos, self.end_pos)
        self._eta = 0.0

    # -- results -------------------------------------------------------

    @property
    def speed_x(self) -> float | None:
        """Smoothed live speed, or None until there is enough data."""
        if self._finished_elapsed is not None:
            return self.average_x
        t = self.elapsed()
        if self.known_length:
            return self._speed if (self._eta is not None or self._ready(t)) else None
        # Unknown length: still show the speed once enough audio is in.
        enough = (self.pos - self.start_pos) >= self._min_audio and t >= self._min_elapsed
        return self._speed if enough else None

    @property
    def eta_s(self) -> float | None:
        return self._eta

    @property
    def audio_s(self) -> float:
        """Audio covered: the whole span once finished (``finish()`` moves
        the position to the probed end), else the position reached."""
        return max(0.0, self.pos - self.start_pos)

    @property
    def average_x(self) -> float | None:
        seconds = self.elapsed()
        audio = self.audio_s
        if seconds <= 0.0 or audio <= 0.0:
            return None
        return audio / seconds


# -- plain-words formatting --------------------------------------------


def format_duration(seconds: float) -> str:
    """``3 min 40 s`` / ``40 s`` / ``1 h 5 min``: no false precision."""
    s = max(0, int(round(_finite(seconds))))
    if s < 1:
        return "under 1 s"
    if s < 60:
        return f"{s} s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m} min {sec} s" if sec else f"{m} min"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h} h {m} min" if m else f"{h} h"


def format_speed(x: float | None) -> str:
    """``11.5x`` (one decimal under 100, whole number above)."""
    if x is None or not math.isfinite(x) or x <= 0:
        return ""
    if x < 0.1:
        return "under 0.1x"
    if round(x, 1) >= 100:
        return f"{x:.0f}x"
    return f"{x:.1f}x"


def format_time_left(eta_s: float | None) -> str:
    """Whole minutes, rounded up; never seconds (the estimate is rough)."""
    if eta_s is None or not math.isfinite(eta_s):
        return ""
    if eta_s <= 0:
        # The audio is through; speaker labels or writing may still run.
        return "audio done"
    if eta_s < 60:
        return "under 1 min left"
    minutes = math.ceil(eta_s / 60.0)
    if minutes < 60:
        return f"{minutes} min left"
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min left" if m else f"{h} h left"


def live_cell(speed_x: float | None, eta_s: float | None) -> str:
    """Queue-row text while a job runs: ``about 4.8x, 6 min left``."""
    if speed_x is None or speed_x <= 0:
        return "measuring speed..."
    speed = "very slow" if speed_x < 0.1 else f"about {format_speed(speed_x)}"
    left = format_time_left(eta_s)
    return f"{speed}, {left}" if left else speed


def device_label(device: str) -> str:
    d = (device or "").strip().lower()
    if d.startswith("cuda") or d == "gpu":
        return "GPU"
    if d == "cpu":
        return "CPU"
    if d in ("mps", "metal"):
        return "Apple GPU"
    return ""


def summary_line(
    audio_s: float,
    seconds: float,
    model: str = "",
    device: str = "",
    resumed: bool = False,
) -> str:
    """``42 min of audio transcribed in 3 min 40 s (11.5x) with small on CPU``.

    The time is decode time only (no model load, speaker labels or writing),
    so it can be shorter than the queue's Elapsed column. Under a second of
    work gives no line: a speed from a blink of a clock is noise.
    """
    if audio_s <= 0 or seconds < 1.0:
        return ""
    x = audio_s / seconds
    speed = format_speed(x)
    if x < 1.0:
        speed += ", slower than the recording plays"
    text = (
        f"{format_duration(audio_s)} of audio transcribed in "
        f"{format_duration(seconds)} ({speed})"
    )
    # "faster-whisper-small" is the engine's folder name; people know "small".
    model = (model or "").removeprefix("faster-whisper-")
    if model:
        text += f" with {model}"
    where = device_label(device)
    if where:
        text += f" on {where}"
    if resumed:
        text += ", counting only the part done after resuming"
    return text


# -- task fields (both sides of the worker protocol) ---------------------


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def reset_speed(task: object) -> None:
    """Forget a previous run's numbers (a re-run starts a fresh meter)."""
    for name, value in (
        ("live_speed_x", None), ("live_eta_s", None), ("speed_x", 0.0),
        ("speed_audio_s", 0.0), ("speed_seconds", 0.0),
        ("speed_resumed", False), ("speed_model", ""), ("speed_device", ""),
        ("speed_live", True),
    ):
        setattr(task, name, value)


def apply_live_speed(task: object, event: dict[str, object]) -> None:
    """Copy a "progress" event's ``speed_x`` / ``eta_s`` onto the task."""
    setattr(task, "speed_live", event.get("speed_live") is not False)
    setattr(task, "live_speed_x", _opt_float(event.get("speed_x")))
    setattr(task, "live_eta_s", _opt_float(event.get("eta_s")))


def apply_final_speed(task: object, event: dict[str, object]) -> None:
    """Copy a "done" event's overall speed fields onto the task."""
    speed = _opt_float(event.get("speed_x")) or 0.0
    setattr(task, "speed_x", speed)
    setattr(task, "speed_audio_s", _opt_float(event.get("speed_audio_s")) or 0.0)
    setattr(task, "speed_seconds", _opt_float(event.get("speed_seconds")) or 0.0)
    setattr(task, "speed_resumed", bool(event.get("speed_resumed")))
    setattr(task, "speed_model", str(event.get("model") or ""))
    setattr(task, "speed_device", str(event.get("device") or ""))
    setattr(task, "live_eta_s", None)


def speed_cell(task: object) -> str:
    """Text for the queue row's "Speed and time left" cell."""
    status = str(getattr(task, "status", "") or "")
    if status == "paused" or (status == "running" and getattr(task, "paused", False)):
        return "paused"
    if status == "running":
        if not getattr(task, "speed_live", True):
            # Engines that return everything at once: the speed comes at the end.
            return "shown when done"
        return live_cell(
            getattr(task, "live_speed_x", None), getattr(task, "live_eta_s", None)
        )
    if status == "finished":
        return format_speed(getattr(task, "speed_x", 0.0) or None)
    return ""


def task_summary_line(task: object) -> str:
    """The result card's line, from a finished task's fields."""
    return summary_line(
        float(getattr(task, "speed_audio_s", 0.0) or 0.0),
        float(getattr(task, "speed_seconds", 0.0) or 0.0),
        str(getattr(task, "speed_model", "") or ""),
        str(getattr(task, "speed_device", "") or ""),
        resumed=bool(getattr(task, "speed_resumed", False)),
    )
