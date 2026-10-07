"""Plain-text transcript: one segment per line, no timestamps.

A diarised segment keeps its ``Speaker: `` label, as in the SRT writer.
"""
from __future__ import annotations

from .base import labelled_text


def write(segments: list[dict], audio_path: str = "") -> str:
    lines = [labelled_text(seg) for seg in segments]
    return "\n".join(lines) + "\n"
