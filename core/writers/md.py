"""Markdown ``.md`` writer.

Layout:

  # <audio basename>

  **HH:MM:SS** Speaker name :  segment text...
  **HH:MM:SS** Speaker name :  next segment...

Speaker prefixes appear only when the segment carries a ``speaker``
field (set by the diarisation pipeline). Without speakers, the
heading is the audio basename and each segment is a single line:

  **HH:MM:SS**  segment text...

Stdlib only.
"""
from __future__ import annotations

import os

from .base import coerce_seconds, fmt_srt_time, normalize_text


def _fmt_md_time(seconds: float) -> str:
    """``HH:MM:SS`` — drops the millisecond fraction the SRT helper carries."""
    return fmt_srt_time(seconds).split(",")[0]


def _escape_md_heading(title: str) -> str:
    """Strip markdown control characters from a title.

    Without this, a basename like ``[foo](bar)`` renders as a link in
    Markdown and ``# evil-script`` could inject HTML once rendered.
    """
    return (title or "").translate(str.maketrans({
        "[": "", "]": "", "(": "", ")": "",
        "<": "", ">": "", "#": "", "`": "",
    }))


def write(segments: list[dict], audio_path: str = "") -> str:
    title = _escape_md_heading(
        os.path.basename(audio_path) if audio_path else "Transcript"
    )
    lines: list[str] = [f"# {title}", ""]
    for seg in segments:
        text = normalize_text(seg.get("text", ""))
        if not text:
            continue
        ts = _fmt_md_time(coerce_seconds(seg.get("start")))
        # Defensive str-cast: a hand-edited JSON could carry a
        # numeric speaker label which (seg.get("speaker") or "")
        # used to .strip() on, raising AttributeError on int.
        raw_speaker = seg.get("speaker")
        speaker = (str(raw_speaker).strip()
                   if raw_speaker not in (None, "") else "")
        if speaker:
            lines.append(f"**{ts}** _{speaker}:_ {text}")
        else:
            lines.append(f"**{ts}** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
