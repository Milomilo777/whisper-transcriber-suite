"""Tab-separated values writer (used by Audacity Labels and many editors)."""
from __future__ import annotations

import math

from .base import normalize_text


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
        text = normalize_text(seg.get("text", "")).replace("\t", " ")
        start_ms = _ms(seg.get("start", 0.0))
        end_ms = _ms(seg.get("end", 0.0))
        rows.append(f"{start_ms}\t{end_ms}\t{text}")
    return "\n".join(rows) + "\n"
