"""SubRip ``.srt`` writer.

If a segment carries a ``speaker`` field (set by the diarisation
pipeline), the SRT line is prefixed with ``Speaker N: ``. This is
the convention SubRip and most media players accept; downstream
viewers like VLC render it cleanly.
"""
from __future__ import annotations

from .base import (
    coerce_seconds,
    escape_cue_separator,
    fmt_srt_time,
    normalize_text,
    speaker_prefix,
)


def write(segments: list[dict], audio_path: str = "") -> str:
    out: list[str] = []
    for i, seg in enumerate(segments, 1):
        # escape_cue_separator: literal "-->" in the payload would
        # collide with SRT's own time-code separator and confuse
        # downstream parsers.
        text = escape_cue_separator(normalize_text(seg.get("text", "")))
        text = speaker_prefix(seg) + text
        # coerce_seconds: a hand-edited / externally produced segment can
        # carry None / a non-numeric string / a non-finite time; the cue
        # must survive with a clamped timestamp rather than aborting the
        # whole file. Missing "end" falls back to the start.
        start = coerce_seconds(seg.get("start"))
        end = coerce_seconds(seg.get("end"), start)
        out.append(f"{i}")
        out.append(f"{fmt_srt_time(start)} --> {fmt_srt_time(end)}")
        out.append(text)
        out.append("")
    return "\n".join(out)
