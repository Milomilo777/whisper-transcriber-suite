"""WebVTT ``.vtt`` writer.

If a segment has a ``words`` list, emit a karaoke-style cue with each word
wrapped in ``<HH:MM:SS.ms><c>word</c>`` markers — the convention recognised
by browsers when shown via ``<track>``.
"""
from __future__ import annotations

from .base import (
    coerce_seconds,
    escape_cue_separator,
    fmt_vtt_time,
    normalize_text,
    speaker_prefix,
)


def _karaoke_payload(seg: dict) -> str:
    # A hand-edited / externally produced segment can carry a non-list in
    # "words" (e.g. a string or number); iterating it raised TypeError and
    # aborted the whole file. Only a non-empty list is usable.
    words = seg.get("words")
    if not isinstance(words, list) or not words:
        return escape_cue_separator(normalize_text(seg.get("text", "")))
    parts: list[str] = []
    for w in words:
        # w.get("start", default) only returns the default when the key
        # is ABSENT; an explicit start=None (hand-edited / externally
        # produced JSON re-fed for re-export) would make float(None)
        # raise and abort the whole VTT write. A non-numeric string such
        # as "abc" (also from a converted / hand-edited JSON) would make
        # float("abc") raise ValueError and abort just the same. Coerce
        # defensively: fall back to the segment start, then to 0.0.
        ts_val = w.get("start")
        if ts_val is None:
            ts_val = seg.get("start", 0.0)
        try:
            ts_seconds = float(ts_val)
        except (TypeError, ValueError):
            try:
                ts_seconds = float(seg.get("start", 0.0))
            except (TypeError, ValueError):
                ts_seconds = 0.0
        ts = fmt_vtt_time(ts_seconds)
        # The word text can be a non-string (e.g. a number) in a
        # hand-edited / externally produced JSON re-fed for re-export.
        # ``(w.get("word") or "")`` keeps that non-string truthy value,
        # so the bare ``.strip()`` would AttributeError and abort the
        # whole VTT write. Coerce to str defensively (mirroring
        # speaker_prefix) before the string ops.
        word_val = w.get("word")
        word_text = "" if word_val is None else str(word_val)
        token = escape_cue_separator(word_text.strip())
        if not token:
            continue
        if parts:
            parts.append(" ")
        parts.append(f"<{ts}><c>{token}</c>")
    if not parts:
        # Every word was unusable (non-dict entry / blank token). Fall back
        # to the segment text, matching ASS's writer, so the cue is not
        # silently emptied.
        return escape_cue_separator(normalize_text(seg.get("text", "")))
    return "".join(parts).strip()


def write(segments: list[dict], audio_path: str = "") -> str:
    out: list[str] = ["WEBVTT", ""]
    for seg in segments:
        # coerce_seconds: a malformed segment timestamp (None / non-numeric
        # / NaN / Inf) must clamp rather than abort the whole file; a
        # missing "end" falls back to the start.
        start = coerce_seconds(seg.get("start"))
        end = coerce_seconds(seg.get("end"), start)
        out.append(f"{fmt_vtt_time(start)} --> {fmt_vtt_time(end)}")
        payload = _karaoke_payload(seg)
        out.append(speaker_prefix(seg) + payload)
        out.append("")
    return "\n".join(out)
