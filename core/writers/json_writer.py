"""JSON writer: list of segment dicts, indented for readability.

Preserves ``words`` (with their probabilities) when present so downstream
karaoke tools can re-render without re-running Whisper. Also preserves
``speaker`` when the diarisation pipeline tagged the segment.
"""
from __future__ import annotations

import json
import math

from .base import MAX_SECONDS, replace_lone_surrogates


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
        start = max(0.0, _safe_float(seg.get("start", 0.0)))
        # A missing (or unusable) end falls back to the start, as in every
        # other writer; 0 made a negative-length segment.
        item: dict = {
            "start": start,
            "end": max(start, _safe_float(seg.get("end", start), start)),
            "text": ("" if raw_text is None else str(raw_text)).strip(),
        }
        language = seg.get("language")
        if language not in (None, ""):
            item["language"] = str(language)
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
            # A missing/collapsed segment end carries no usable upper bound.
            # Preserve valid word clocks instead of clamping them all to start.
            if item["end"] <= start:
                item["end"] = max(start, min(MAX_SECONDS, max([start] + [
                    max(start, _safe_float(w.get("start"), start),
                        _safe_float(w.get("end"), start))
                    for w in words if isinstance(w, dict)
                ])))
            coerced_words = []
            valid_words = [w for w in words if isinstance(w, dict)]
            for index, w in enumerate(valid_words):
                # Alignment may extend a word past its containing cue.
                # Keep its label and confidence while bounding the clock.
                word_start = min(item["end"], max(
                    item["start"], _safe_float(w.get("start"), item["start"])
                ))
                # An unusable earlier end must not consume a later word. The
                # final word can use the cue's remaining coverage; a missing
                # end retains its separate legacy fallback to its own start.
                fallback_end = word_start if index + 1 < len(valid_words) else item["end"]
                word_end = min(item["end"], max(
                    word_start, _safe_float(w.get("end", word_start), fallback_end)
                ))
                coerced_words.append({
                    "start": word_start,
                    "end": word_end,
                    # str-coerce like text / speaker / suspect_reason: a
                    # hand-edited JSON can put a number or null in the
                    # label, and downstream karaoke tools expect a string.
                    "word": ("" if w.get("word") is None
                             else str(w["word"])),
                    "probability": _safe_float(w.get("probability", 0.0)),
                })
            if coerced_words:
                item["words"] = coerced_words
        out.append(item)
    # allow_nan=False — every consumer of this JSON expects strict
    # output; we've already _safe_float-ed every numeric field above
    # so this can no longer raise in practice but guards against
    # future regressions.
    # A lone surrogate half (hand-edited JSON, a damaged name) cannot be
    # written as UTF-8 and ensure_ascii=False passes it through. Replacing it
    # in the finished text covers every field (text, speaker, flags, words).
    body = json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False)
    return replace_lone_surrogates(body) + "\n"
