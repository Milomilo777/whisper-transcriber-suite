"""WebVTT ``.vtt`` writer.

If a segment has a ``words`` list that still spells its ``text``, emit a
karaoke-style cue with each word wrapped in a ``<c>word</c>`` span and
valid in-cue ``<HH:MM:SS.ms>`` activation markers, recognised by browsers via
``<track>``. A segment whose text was edited after transcription (the
words no longer match) is written from ``text``.

``&``, ``<`` and ``>`` in the text, the word tokens and the speaker label
are written as character references, so the cue reads back exactly.
"""
from __future__ import annotations

import re

from .base import (
    coerce_seconds,
    escape_vtt_text,
    fmt_vtt_time,
    karaoke_tokens,
    normalize_text,
    prepare_cues,
    speaker_prefix,
)


def _plain_payload(seg: dict) -> str:
    return escape_vtt_text(normalize_text(seg.get("text", "")))


def _karaoke_payload(seg: dict) -> str:
    # Only a word list that still spells the (possibly edited) text is
    # usable; karaoke_tokens skips non-dict entries and blank tokens (from
    # hand-edited or externally produced JSON) and returns None otherwise.
    tokens = karaoke_tokens(seg)
    if tokens is None:
        return _plain_payload(seg)
    parts: list[str] = []
    for w, word_text, space_before in tokens:
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
        ts_seconds = coerce_seconds(ts_val, coerce_seconds(seg.get("start")))
        ts = fmt_vtt_time(ts_seconds)
        # A space only where the text has one: CJK words carry none, and a
        # spacing-only edit ("to day" -> "today") must show in the cue.
        if parts and space_before:
            parts.append(" ")
        parts.append(f"<{ts}><c>{escape_vtt_text(word_text)}</c>")
    return "".join(parts)


def _valid_cue_timestamps(text: str, start_ms: int, end_ms: int) -> str:
    # WebVTT 4.2.2: internal timestamps are strictly increasing and strictly
    # inside the final cue, including after prepare_cues merges bad cues.
    # https://www.w3.org/TR/webvtt1/#webvtt-cue-timestamp
    # Keep every word and class span; omit an unusable activation marker.
    previous = start_ms

    def marker(match: re.Match[str]) -> str:
        nonlocal previous
        hours, minutes, seconds, milliseconds = map(int, match.groups())
        stamp = ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds
        if previous < stamp < end_ms:
            previous = stamp
            return match.group(0)
        return ""

    return re.sub(r"<(\d{2,}):([0-5]\d):([0-5]\d)\.(\d{3})>", marker, text)


def write(segments: list[dict], audio_path: str = "") -> str:
    def render_text(seg: dict) -> str:
        payload = _karaoke_payload(seg)
        if not payload:
            # A blank cue shows nothing and some players reject an empty
            # payload; ASS and ELAN skip these too.
            return ""
        return escape_vtt_text(speaker_prefix(seg)) + payload

    out: list[str] = ["WEBVTT", ""]
    for start_ms, end_ms, text in prepare_cues(segments, render_text):
        out.append(
            f"{fmt_vtt_time(start_ms / 1000)} --> {fmt_vtt_time(end_ms / 1000)}"
        )
        out.append(_valid_cue_timestamps(text, start_ms, end_ms))
        out.append("")
    return "\n".join(out)
