"""SubRip ``.srt`` writer.

If a segment carries a ``speaker`` field (set by the diarisation
pipeline), the SRT line is prefixed with ``Speaker N: ``. This is
the convention SubRip and most media players accept; downstream
viewers like VLC render it cleanly.
"""
from __future__ import annotations

from .base import (
    escape_cue_separator,
    fmt_srt_time,
    normalize_text,
    prepare_cues,
    speaker_prefix,
)


def write(segments: list[dict], audio_path: str = "") -> str:
    def render_text(seg: dict) -> str:
        # escape_cue_separator: literal "-->" in the payload would
        # collide with SRT's own time-code separator and confuse
        # downstream parsers.
        text = escape_cue_separator(normalize_text(seg.get("text", "")))
        if not text:
            # An empty payload line ends the cue early in strict parsers
            # and shows nothing; ASS and ELAN skip blank segments too.
            return ""
        # The label is hand-editable too: escape it like the payload, or a
        # "-->" in it adds a second separator to the cue.
        return escape_cue_separator(speaker_prefix(seg)) + text

    out: list[str] = []
    for i, (start_ms, end_ms, text) in enumerate(
        prepare_cues(segments, render_text), start=1
    ):
        out.append(f"{i}")
        out.append(
            f"{fmt_srt_time(start_ms / 1000)} --> {fmt_srt_time(end_ms / 1000)}"
        )
        out.append(text)
        out.append("")
    return "\n".join(out)
