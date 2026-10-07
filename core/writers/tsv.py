"""Tab-separated values writer: ``start<TAB>end<TAB>text`` with a header row.

Times are integer MILLISECONDS (the layout OpenAI Whisper's ``.tsv``
output uses), which spreadsheets and scripts read directly. This is not
an Audacity label track: Audacity labels have no header and use seconds.
A diarised segment's ``Speaker: `` label goes at the start of the text
column, so the three-column layout stays what Whisper readers expect.
"""
from __future__ import annotations

import math

from .base import coerce_seconds, labelled_text


def _ms(value: object) -> int:
    """Coerce to a finite, non-negative millisecond integer.

    Whisper segments occasionally carry NaN / Inf timestamps from a
    buggy backend; ``int(round(float(...) * 1000))`` raises ValueError
    (NaN) or OverflowError (Inf) on those. Every peer timestamp path
    (fmt_srt_time / fmt_lrc_time / json_writer._safe_float) clamps to a
    safe default instead of crashing, so this writer must too — otherwise
    a single bad segment silently drops the whole .tsv output while the
    other formats write fine.
    """
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        # OverflowError: an integer too large for a float (a hand-edited
        # JSON can carry one) raises here exactly like NaN/Inf do.
        return 0
    if not math.isfinite(f) or f < 0:
        return 0
    return int(round(f * 1000))


def write(segments: list[dict], audio_path: str = "") -> str:
    rows: list[str] = ["start\tend\ttext"]
    for seg in segments:
        text = labelled_text(seg).replace("\t", " ")
        start_ms = _ms(seg.get("start", 0.0))
        # A missing or unusable end falls back to the start and an earlier
        # end is clamped to it, as in the subtitle writers (0 here made a
        # negative-length row).
        end_s = coerce_seconds(seg.get("end"), -1.0)
        end_ms = max(_ms(end_s), start_ms) if end_s >= 0 else start_ms
        rows.append(f"{start_ms}\t{end_ms}\t{text}")
    return "\n".join(rows) + "\n"
