"""LRC lyric writer: ``[mm:ss.xx]`` per segment with the audio file name."""
from __future__ import annotations

import os

from .base import coerce_seconds, fmt_lrc_time, labelled_text, replace_lone_surrogates


def write(segments: list[dict], audio_path: str = "") -> str:
    lines: list[str] = []
    if audio_path:
        title = os.path.splitext(os.path.basename(audio_path))[0]
        lines.append(f"[ti:{replace_lone_surrogates(title)}]")
    for seg in segments:
        # coerce_seconds: clamp a malformed start (None / non-numeric /
        # non-finite) instead of aborting the whole .lrc.
        start = coerce_seconds(seg.get("start"))
        lines.append(f"{fmt_lrc_time(start)}{labelled_text(seg)}")
    return "\n".join(lines) + "\n"
