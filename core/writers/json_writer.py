"""JSON writer: list of segment dicts, indented for readability.

Preserves ``words`` (with their probabilities) when present so downstream
karaoke tools can re-render without re-running Whisper. Also preserves
``speaker`` when the diarisation pipeline tagged the segment.
"""
from __future__ import annotations

import json


import math


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce to a finite float — NaN/Inf become ``default``.

    Strict JSON parsers (browsers, Go encoding/json, Rust serde)
    reject ``NaN`` / ``Infinity``. A buggy backend that produces
    non-finite timestamps would silently corrupt every downstream
    consumer of our JSON output if we serialised them as-is.
    """
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        # OverflowError: an integer too large for a float (a hand-edited
        # JSON can carry one) raises here exactly like NaN/Inf do.
        return default
    if not math.isfinite(f):
        return default
    return f


def write(segments: list[dict], audio_path: str = "") -> str:
    out: list[dict] = []
    for seg in segments:
        # A hand-edited / externally produced JSON can put a non-string
        # (e.g. a number) in "text"; ``(value or "").strip()`` raised
        # AttributeError on it and dropped the whole sidecar.
        raw_text = seg.get("text")
        item: dict = {
            "start": _safe_float(seg.get("start", 0.0)),
            "end": _safe_float(seg.get("end", 0.0)),
            "text": ("" if raw_text is None else str(raw_text)).strip(),
        }
        speaker = seg.get("speaker")
        if speaker not in (None, ""):
            item["speaker"] = str(speaker)
        # Carry through hallucination-detector flags so the on-disk JSON
        # actually contains them — the transcript viewer renders flagged
        # segments as red rows via seg.get("suspect"), and this is also
        # the round-trip path for the viewer's "Save Changes". Without
        # this passthrough the flags were computed in memory and dropped.
        if seg.get("suspect"):
            item["suspect"] = True
        reason = seg.get("suspect_reason")
        if reason not in (None, ""):
            item["suspect_reason"] = str(reason)
        words = seg.get("words")
        if isinstance(words, list):
            # Carry through only dict word entries, mirroring convert's
            # _parse_json: a non-dict element or a non-list "words" value
            # from a hand-edited JSON raised and aborted the whole write.
            coerced_words = [
                {
                    "start": _safe_float(w.get("start", item["start"]),
                                         item["start"]),
                    "end": _safe_float(w.get("end", item["end"]),
                                       item["end"]),
                    "word": w.get("word", ""),
                    "probability": _safe_float(w.get("probability", 0.0)),
                }
                for w in words
                if isinstance(w, dict)
            ]
            if coerced_words:
                item["words"] = coerced_words
        out.append(item)
    # allow_nan=False — every consumer of this JSON expects strict
    # output; we've already _safe_float-ed every numeric field above
    # so this can no longer raise in practice but guards against
    # future regressions.
    return json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
