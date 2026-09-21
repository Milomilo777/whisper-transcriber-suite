"""LRC lyric writer: ``[mm:ss.xx]`` per segment with the audio file name."""
from __future__ import annotations

import os

from .base import coerce_seconds, fmt_lrc_time, normalize_text


def write(segments: list[dict], audio_path: str = "") -> str:
    lines: list[str] = []
    if audio_path:
        lines.append(f"[ti:{os.path.splitext(os.path.basename(audio_path))[0]}]")
    for seg in segments:
        # coerce_seconds: clamp a malformed start (None / non-numeric /
        # non-finite) instead of aborting the whole .lrc.
        start = coerce_seconds(seg.get("start"))
        lines.append(f"{fmt_lrc_time(start)}{normalize_text(seg.get('text', ''))}")
    return "\n".join(lines) + "\n"
