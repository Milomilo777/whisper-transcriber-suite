"""Auto-chapter markers from a finished transcript (v0.8 Phase 3).

The simplest robust heuristic: cut a new chapter whenever there is
a **long inter-segment silence** AND the cumulative chapter
duration crossed a minimum threshold. Modelled after PODTILE-lite
(arXiv 2410.16148) without the heavy LLM dep.

Two-step pipeline:

  1. :func:`detect_chapter_boundaries` walks the segment list and
     returns a list of `(start_seconds, end_seconds, segment_index_range)`.
     Pure Python, no model dependencies. Always available.
  2. (Optional) :func:`title_chapters_with_llm` runs each chapter
     through the local LLM (when installed) to label it with a
     6-word headline. Falls back to "Chapter N" when LLM isn't
     ready.

Output shape (what :func:`build_chapters` returns):

    [
      {"index": 0, "title": "Intro & guest welcome",
       "start": 0.0, "end": 215.4, "segment_start": 0, "segment_end": 27},
      ...
    ]

The viewer (future work) can use the start times for navigation
and the writer can append them to JSON. The chapters list is
self-contained — it doesn't mutate the underlying segments.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_MIN_CHAPTER_SECONDS = 60.0
DEFAULT_GAP_SECONDS = 2.5
DEFAULT_SENTENCE_TERMINATORS = ("?", "!", ".")


@dataclass(frozen=True)
class ChapterBoundary:
    start: float
    end: float
    segment_start: int
    segment_end: int  # inclusive


def detect_chapter_boundaries(
    segments: list[dict[str, Any]],
    *,
    min_chapter_seconds: float = DEFAULT_MIN_CHAPTER_SECONDS,
    gap_seconds: float = DEFAULT_GAP_SECONDS,
) -> list[ChapterBoundary]:
    """Cut chapters at long silences once the running chapter is long enough.

    A boundary forms when:
      * gap between segment ``i`` end and segment ``i+1`` start
        exceeds ``gap_seconds``, AND
      * the cumulative duration of the in-progress chapter has
        passed ``min_chapter_seconds``.

    Always returns at least one chapter covering the whole input
    when ``segments`` is non-empty; empty input → empty list.
    """
    if not segments:
        return []
    boundaries: list[ChapterBoundary] = []
    chapter_start_idx = 0
    chapter_start = _seconds(segments[0].get("start"), 0.0)
    for i in range(len(segments) - 1):
        cur_end = _seg_end(segments[i])
        next_start = _seconds(segments[i + 1].get("start"), cur_end)
        gap = next_start - cur_end
        duration = cur_end - chapter_start
        if gap >= gap_seconds and duration >= min_chapter_seconds:
            boundaries.append(ChapterBoundary(
                start=chapter_start,
                end=cur_end,
                segment_start=chapter_start_idx,
                segment_end=i,
            ))
            chapter_start_idx = i + 1
            chapter_start = next_start
    # Close the trailing chapter on the final segment.
    last_end = _seg_end(segments[-1])
    boundaries.append(ChapterBoundary(
        start=chapter_start,
        end=last_end,
        segment_start=chapter_start_idx,
        segment_end=len(segments) - 1,
    ))
    return boundaries


# ---------------------------------------------------------------- titles


# A sentence ends at ".", "!", "?" or the Arabic-script question mark
# followed by whitespace or the end of the text, so "Version 2.0" and
# "3.14" do not end it; the CJK full-width marks need no space after them.
_SENTENCE_END_RE = re.compile(r"[.!?\u061f](?=\s|$)|[\u3002\uff01\uff1f]")
_TERMINATORS = ".!?\u061f\u3002\uff01\uff1f\u2026"
# Scripts written without spaces between words (kana, Han ideographs, Thai,
# Lao, Khmer, Myanmar): a title cut by "words" never shortens them.
_UNSPACED_SCRIPT_RE = re.compile(
    "[\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff\u3400-\u9fff]"
)
_MAX_UNSPACED_TITLE_CHARS = 30
# Words ending in "." that are abbreviations, not a sentence end. Words
# with an inner dot ("e.g", "U.S") count as abbreviations too.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "vs", "etc",
    "mt", "ft", "inc", "ltd", "approx", "dept",
})


def _seconds(value: object, default: float) -> float:
    """A finite float from a segment field; ``default`` for None / junk."""
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _seg_end(seg: dict[str, Any]) -> float:
    start = _seconds(seg.get("start"), 0.0)
    return _seconds(seg.get("end"), start)


def _seg_text(seg: dict[str, Any]) -> str:
    raw = seg.get("text")
    return ("" if raw is None else str(raw)).strip()


def _first_sentence(text: str) -> str:
    for m in _SENTENCE_END_RE.finditer(text):
        before = text[:m.start()]
        if not before.strip().strip(_TERMINATORS).strip():
            continue  # a leading "..." / "!!!" ends nothing yet
        if m.group(0) == ".":
            words = before.split()
            last = words[-1].lower() if words else ""
            # "Dr." / "e.g." / "U.S." / an initial ("J. Smith") go on;
            # "I." is a word, not an initial.
            if (last in _ABBREVIATIONS or "." in last
                    or (len(last) == 1 and last.isalpha() and last != "i")):
                continue
        return text[:m.end()]
    return text


def heuristic_title(segments: list[dict[str, Any]], boundary: ChapterBoundary,
                     *, max_words: int = 6) -> str:
    """Pull the first sentence of the chapter as a fallback title."""
    if boundary.segment_start >= len(segments):
        return "Chapter"
    text_parts: list[str] = []
    for idx in range(boundary.segment_start, boundary.segment_end + 1):
        if idx >= len(segments):
            break
        t = _seg_text(segments[idx])
        if t:
            text_parts.append(t)
            if len(" ".join(text_parts).split()) >= max_words * 2:
                break
    combined = " ".join(text_parts).strip()
    if not combined:
        return "Chapter"
    words = _first_sentence(combined).strip(_TERMINATORS + " \t\n").split()
    first = " ".join(words)
    if len(words) > max_words:
        first = " ".join(words[:max_words]) + "…"
    elif len(first) > _MAX_UNSPACED_TITLE_CHARS and _UNSPACED_SCRIPT_RE.search(first):
        first = first[:_MAX_UNSPACED_TITLE_CHARS].rstrip() + "…"
    return first or "Chapter"


def title_chapters_with_llm(
    segments: list[dict[str, Any]],
    boundaries: list[ChapterBoundary],
    *,
    runner: "Any | None" = None,
) -> list[str]:
    """Use the local LLM to label each chapter; fall back to heuristic.

    ``runner`` is a :class:`core.llm.LLMRunner` (or any object with
    a compatible ``ask`` method). When ``None`` or unavailable, this
    returns the heuristic titles so the chapter list is always
    usable.
    """
    titles: list[str] = []
    for boundary in boundaries:
        if runner is None:
            titles.append(heuristic_title(segments, boundary))
            continue
        text = _slice_text(segments, boundary)
        try:
            raw = runner.ask(
                text,
                "Write a 4-7 word headline that summarises this "
                "chapter. Respond with only the headline, no quotes.",
            )
            raw = (raw or "").strip().strip('"').strip("'")
            if raw and len(raw) <= 120:
                titles.append(raw)
                continue
        except Exception as e:  # noqa: BLE001
            logger.debug("LLM titling failed: %s", e)
        titles.append(heuristic_title(segments, boundary))
    return titles


def _slice_text(segments: list[dict[str, Any]], boundary: ChapterBoundary) -> str:
    parts: list[str] = []
    for idx in range(boundary.segment_start, boundary.segment_end + 1):
        if idx >= len(segments):
            break
        t = _seg_text(segments[idx])
        if t:
            parts.append(t)
    return " ".join(parts)


# ---------------------------------------------------------------- entry point


def build_chapters(
    segments: list[dict[str, Any]],
    *,
    runner: "Any | None" = None,
    min_chapter_seconds: float = DEFAULT_MIN_CHAPTER_SECONDS,
    gap_seconds: float = DEFAULT_GAP_SECONDS,
) -> list[dict[str, Any]]:
    """High-level entry point: detect + title in one call.

    Returns a list of chapter dicts ready to write into the JSON
    output sidecar.
    """
    boundaries = detect_chapter_boundaries(
        segments,
        min_chapter_seconds=min_chapter_seconds,
        gap_seconds=gap_seconds,
    )
    titles = title_chapters_with_llm(segments, boundaries, runner=runner)
    out: list[dict[str, Any]] = []
    for i, (b, title) in enumerate(zip(boundaries, titles)):
        out.append({
            "index": i,
            "title": title,
            "start": b.start,
            "end": b.end,
            "segment_start": b.segment_start,
            "segment_end": b.segment_end,
        })
    return out
