"""Plain-text transcript: one segment per line, no timestamps.

A diarised segment keeps its ``Speaker: `` label, as in the SRT writer.
"""
from __future__ import annotations

from .base import normalize_text, speaker_prefix


def write(segments: list[dict], audio_path: str = "") -> str:
    lines = [
        speaker_prefix(seg) + normalize_text(seg.get("text", ""))
        for seg in segments
    ]
    return "\n".join(lines) + "\n"
