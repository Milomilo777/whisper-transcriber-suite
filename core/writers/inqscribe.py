"""InqScribe writer: inline ``[hh:mm:ss.ff]`` timestamps before each segment.

InqScribe (https://www.inqscribe.com) transcripts are plain text where a
timestamp in square brackets precedes the text it marks. ``.ff`` is
centiseconds (hundredths of a second), matching InqScribe's own display.

InqScribe has no escape syntax, so text that itself looks like a
timestamp (``see [00:01] here``) would start a new segment when read back.
Such a text timestamp is written with a backslash in front
(``see \\[00:01] here``), and backslashes already in front of it are
doubled; ``core.convert`` reverses this. Text without a bracketed
timestamp is written unchanged.
"""
from __future__ import annotations

import math
import re

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


# Same pattern as core.convert's InqScribe parser: ``[hh:]mm:ss[.ff]`` in
# square brackets.
_TEXT_TIMESTAMP = re.compile(r"\[(?:\d+:)?\d{1,2}:\d{1,2}(?:[.,]\d{1,3})?\]")


def escape_inqscribe_text(text: str) -> str:
    """Mark every timestamp-like run in *text* as literal (see module doc).

    ``n`` backslashes before the bracket become ``2n + 1``: odd means
    "literal text" to the parser, which halves the run back to ``n``. The
    run is counted by hand; a ``\\\\*`` regex group is quadratic on long
    runs of backslashes.
    """
    out: list[str] = []
    last = 0
    for m in _TEXT_TIMESTAMP.finditer(text):
        run = 0
        while m.start() - run - 1 >= last and text[m.start() - run - 1] == "\\":
            run += 1
        out.append(text[last:m.start() - run])
        out.append("\\" * (2 * run + 1))
        last = m.start()
    out.append(text[last:])
    return "".join(out)


def write(segments: list[dict], audio_path: str = "") -> str:
    lines: list[str] = []
    for seg in segments:
        text = escape_inqscribe_text(
            speaker_prefix(seg) + normalize_text(seg.get("text", ""))
        )
        lines.append(f"{fmt_inqscribe_time(coerce_seconds(seg.get('start')))}{text}")
    return "\n".join(lines) + "\n"
