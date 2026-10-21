"""The Queue's "Speed and time left" cell and the result card's speed line, translated.

``core.speed_meter`` builds the same texts in English for the log, the HTTP server and the
CLI; core never imports the interface's ``_()``, and the message extractor reads ``app/``
only, so the interface builds its own copy here. In English both give the same words
(tests/core/test_speed_text.py checks that), except that while the speed is still being
measured the cell here also says how much audio is done: the meter needs two of
faster-whisper's 30-s windows before it has a rate, about a minute on a CPU, and a bare
"measuring speed..." for that long looked stuck (deep review, 2026-10-21). Each line is one
whole message, so a translation can order it freely (right-to-left languages too).
"""
from __future__ import annotations

import math

from app.i18n import _
from core.speed_meter import device_label


def _finite(value: object) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def duration_text(seconds: float) -> str:
    """``3 min 40 s`` / ``40 s`` / ``1 h 5 min`` (core.speed_meter.format_duration)."""
    s = max(0, int(round(_finite(seconds))))
    if s < 1:
        return _("under 1 s")
    if s < 60:
        return _("{seconds} s", seconds=s)
    if s < 3600:
        m, sec = divmod(s, 60)
        return _("{minutes} min {seconds} s", minutes=m, seconds=sec) if sec else _("{minutes} min", minutes=m)
    h, rem = divmod(s, 3600)
    m = rem // 60
    return _("{hours} h {minutes} min", hours=h, minutes=m) if m else _("{hours} h", hours=h)


def speed_text(x: float | None) -> str:
    """``11.5x`` (core.speed_meter.format_speed); "" when there is no speed."""
    if x is None or not math.isfinite(x) or x <= 0:
        return ""
    if x < 0.1:
        return _("under 0.1x")
    if round(x, 1) >= 100:
        return f"{x:.0f}x"
    return f"{x:.1f}x"


def time_left_text(eta_s: float | None) -> str:
    """Whole minutes, rounded up (core.speed_meter.format_time_left)."""
    if eta_s is None or not math.isfinite(eta_s):
        return ""
    if eta_s <= 0:
        return _("audio done")
    if eta_s < 60:
        return _("under 1 min left")
    minutes = math.ceil(eta_s / 60.0)
    if minutes < 60:
        return _("{minutes} min left", minutes=minutes)
    h, m = divmod(minutes, 60)
    return _("{hours} h {minutes} min left", hours=h, minutes=m) if m else _("{hours} h left", hours=h)


def live_text(speed_x: float | None, eta_s: float | None, audio_s: float | None = None) -> str:
    """While a job runs: ``about 4.8x, 6 min left``; before the first rate, how much audio
    is done (core.speed_meter.live_cell, plus the audio)."""
    if speed_x is None or speed_x <= 0:
        if audio_s is not None and audio_s >= 1:
            return _("measuring speed... ({done} of audio done)", done=duration_text(audio_s))
        return _("measuring speed...")
    if speed_x < 0.1:
        speed = _("very slow")
    else:
        speed = _("about {speed}", speed=speed_text(speed_x))
    left = time_left_text(eta_s)
    return _("{speed}, {time_left}", speed=speed, time_left=left) if left else speed


def speed_cell_text(task: object) -> str:
    """The Queue row's "Speed and time left" cell (core.speed_meter.speed_cell)."""
    status = str(getattr(task, "status", "") or "")
    if status == "paused" or (status == "running" and getattr(task, "paused", False)):
        return _("paused")
    if status == "running":
        if not getattr(task, "speed_live", True):
            return _("shown when done")
        return live_text(
            getattr(task, "live_speed_x", None), getattr(task, "live_eta_s", None),
            getattr(task, "live_audio_s", None),
        )
    if status == "finished":
        return speed_text(getattr(task, "speed_x", 0.0) or None)
    return ""


_DEVICES = {"GPU": lambda: _("GPU"), "CPU": lambda: _("CPU"), "Apple GPU": lambda: _("Apple GPU")}


def summary_text(audio_s: float, seconds: float, model: str = "", device: str = "",
                 resumed: bool = False) -> str:
    """``42 min of audio transcribed in 3 min 40 s (11.5x) with small on CPU``
    (core.speed_meter.summary_line); "" under a second of work."""
    if audio_s <= 0 or seconds < 1.0:
        return ""
    x = audio_s / seconds
    speed = speed_text(x)
    if x < 1.0:
        speed = _("{speed}, slower than the recording plays", speed=speed)
    audio, took = duration_text(audio_s), duration_text(seconds)
    model = (model or "").removeprefix("faster-whisper-")
    where = device_label(device)
    where = _DEVICES[where]() if where in _DEVICES else where
    if model and where:
        text = _("{audio} of audio transcribed in {time} ({speed}) with {model} on {device}",
                 audio=audio, time=took, speed=speed, model=model, device=where)
    elif model:
        text = _("{audio} of audio transcribed in {time} ({speed}) with {model}",
                 audio=audio, time=took, speed=speed, model=model)
    elif where:
        text = _("{audio} of audio transcribed in {time} ({speed}) on {device}",
                 audio=audio, time=took, speed=speed, device=where)
    else:
        text = _("{audio} of audio transcribed in {time} ({speed})", audio=audio, time=took, speed=speed)
    if resumed:
        text = _("{line}, counting only the part done after resuming", line=text)
    return text


def task_summary_text(task: object) -> str:
    """The result card's line, from a finished task's fields (core.speed_meter.task_summary_line)."""
    return summary_text(
        _finite(getattr(task, "speed_audio_s", 0.0) or 0.0),
        _finite(getattr(task, "speed_seconds", 0.0) or 0.0),
        str(getattr(task, "speed_model", "") or ""),
        str(getattr(task, "speed_device", "") or ""),
        resumed=bool(getattr(task, "speed_resumed", False)),
    )
