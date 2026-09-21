"""InqScribe writer: inline ``[hh:mm:ss.ff]`` timestamps before each segment.

InqScribe (https://www.inqscribe.com) transcripts are plain text where a
timestamp in square brackets precedes the text it marks. ``.ff`` is
centiseconds (hundredths of a second), matching InqScribe's own display.
"""
from __future__ import annotations

import math

from .base import coerce_seconds, normalize_text, speaker_prefix


def fmt_inqscribe_time(seconds: float) -> str:
    """``[hh:mm:ss.ff]`` — centiseconds, clamped to a non-negative finite value."""
    try:
        f = float(seconds)
    except (TypeError, ValueError, OverflowError):
        f = 0.0
    # math.isfinite covers both NaN and Inf; Inf used to reach
    # ``int(round(inf * 100))`` and raise OverflowError, aborting the file.
    if not math.isfinite(f) or f < 0:
        f = 0.0
    total_cs = int(round(f * 100))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    sec, cs = divmod(rem, 100)
    return f"[{hours:02d}:{minutes:02d}:{sec:02d}.{cs:02d}]"


def write(segments: list[dict], audio_path: str = "") -> str:
    lines: list[str] = []
    for seg in segments:
        text = speaker_prefix(seg) + normalize_text(seg.get("text", ""))
        lines.append(f"{fmt_inqscribe_time(coerce_seconds(seg.get('start')))}{text}")
    return "\n".join(lines) + "\n"
