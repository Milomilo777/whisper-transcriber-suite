"""Express Scribe writer: ``[hh:mm:ss] text`` per segment.

Express Scribe (NCH Software) timestamps are whole seconds, so this
format is lossy by design and is therefore EXPORT-ONLY: it is registered
in ``core.writers.WRITERS`` but deliberately NOT added to
``core.convert.PARSE_FORMATS`` (re-parsing ``[hh:mm:ss]`` cues back into
sub-second-accurate segments is ambiguous).
"""
from __future__ import annotations

import math

from .base import coerce_seconds, normalize_text, speaker_prefix


def fmt_express_scribe_time(seconds: float) -> str:
    """``[hh:mm:ss]`` — whole seconds, clamped to a non-negative finite value."""
    try:
        f = float(seconds)
    except (TypeError, ValueError, OverflowError):
        f = 0.0
    # math.isfinite covers both NaN and Inf; Inf used to reach
    # ``int(round(inf))`` and raise OverflowError, aborting the file.
    if not math.isfinite(f) or f < 0:
        f = 0.0
    total = int(round(f))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    return f"[{hours:02d}:{minutes:02d}:{sec:02d}]"


def write(segments: list[dict], audio_path: str = "") -> str:
    lines: list[str] = []
    for seg in segments:
        text = speaker_prefix(seg) + normalize_text(seg.get("text", ""))
        lines.append(f"{fmt_express_scribe_time(coerce_seconds(seg.get('start')))} {text}")
    return "\n".join(lines) + "\n"
