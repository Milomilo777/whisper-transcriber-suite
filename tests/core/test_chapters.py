"""Tests for the auto-chapter detector."""
from __future__ import annotations

import pytest

from core import chapters as ch


# ---------- detect_chapter_boundaries ------------------------------------------


def test_empty_segments_returns_empty():
    assert ch.detect_chapter_boundaries([]) == []


def test_single_chapter_when_no_long_gaps():
    segs = [
        {"start": 0.0, "end": 30.0, "text": "a"},
        {"start": 30.5, "end": 60.0, "text": "b"},
        {"start": 60.3, "end": 90.0, "text": "c"},
    ]
    b = ch.detect_chapter_boundaries(segs, min_chapter_seconds=60.0)
    assert len(b) == 1
    assert b[0].segment_start == 0
    assert b[0].segment_end == 2
    assert b[0].start == 0.0
    assert b[0].end == 90.0


def test_chapter_break_at_long_gap_after_min_duration():
    segs = [
        {"start": 0.0,  "end": 60.0,  "text": "intro"},     # 60s
        {"start": 70.0, "end": 130.0, "text": "next"},      # 10s gap, qualifies
        {"start": 131.0, "end": 200.0, "text": "more"},
    ]
    b = ch.detect_chapter_boundaries(segs, min_chapter_seconds=30.0,
                                      gap_seconds=5.0)
    assert len(b) == 2
    assert b[0].segment_start == 0 and b[0].segment_end == 0
    assert b[1].segment_start == 1 and b[1].segment_end == 2


def test_short_gap_does_not_break_chapter():
    segs = [
        {"start": 0.0,  "end": 60.0,  "text": "a"},
        {"start": 61.0, "end": 120.0, "text": "b"},   # gap of 1s only
    ]
    b = ch.detect_chapter_boundaries(segs, min_chapter_seconds=30.0,
                                      gap_seconds=5.0)
    assert len(b) == 1


def test_long_gap_before_min_duration_does_not_break():
    segs = [
        {"start": 0.0,  "end": 30.0,  "text": "a"},
        {"start": 50.0, "end": 70.0,  "text": "b"},   # 20s gap, chapter only 30s
        {"start": 200.0, "end": 260.0, "text": "c"},  # 130s gap, chapter now 70s
    ]
    b = ch.detect_chapter_boundaries(segs, min_chapter_seconds=60.0,
                                      gap_seconds=5.0)
    # First gap doesn't trigger (running chapter only 30s).
    # Second gap triggers (running chapter 70s ≥ 60s).
    assert len(b) == 2
    assert b[0].segment_end == 1
    assert b[1].segment_start == 2


# ---------- heuristic_title ----------------------------------------------------


def test_heuristic_title_pulls_first_sentence():
    segs = [
        {"start": 0.0, "end": 5.0, "text": "Welcome to the show. Today we explore."},
        {"start": 5.0, "end": 10.0, "text": "Second segment."},
    ]
    b = ch.ChapterBoundary(start=0.0, end=10.0, segment_start=0, segment_end=1)
    title = ch.heuristic_title(segs, b)
    assert title == "Welcome to the show"


def test_heuristic_title_truncates_long_first_sentence():
    segs = [
        {"start": 0.0, "end": 5.0,
         "text": "This is a very long opening sentence that goes on without ending"},
    ]
    b = ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)
    title = ch.heuristic_title(segs, b, max_words=6)
    assert title.endswith("…")
    assert len(title.split()) <= 7


def test_heuristic_title_fallback_for_empty():
    b = ch.ChapterBoundary(start=0.0, end=1.0, segment_start=0, segment_end=0)
    assert ch.heuristic_title([{"text": ""}], b) == "Chapter"


def test_heuristic_title_out_of_range_returns_chapter():
    b = ch.ChapterBoundary(start=0.0, end=1.0, segment_start=99, segment_end=99)
    assert ch.heuristic_title([], b) == "Chapter"


# ---------- title_chapters_with_llm -------------------------------------------


def test_title_chapters_falls_back_to_heuristic_when_runner_none():
    segs = [{"start": 0.0, "end": 5.0, "text": "Hello there friend."}]
    b = [ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)]
    titles = ch.title_chapters_with_llm(segs, b, runner=None)
    assert len(titles) == 1
    assert titles[0] == "Hello there friend"


def test_title_chapters_uses_runner_when_provided():
    segs = [{"start": 0.0, "end": 5.0, "text": "long text here"}]
    b = [ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)]

    class _Runner:
        def ask(self, transcript, question):
            return "LLM Generated Title"

    titles = ch.title_chapters_with_llm(segs, b, runner=_Runner())
    assert titles == ["LLM Generated Title"]


def test_title_chapters_falls_back_when_runner_raises():
    segs = [{"start": 0.0, "end": 5.0, "text": "fallback content here"}]
    b = [ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)]

    class _BrokenRunner:
        def ask(self, transcript, question):
            raise RuntimeError("LLM crashed")

    titles = ch.title_chapters_with_llm(segs, b, runner=_BrokenRunner())
    assert titles == ["fallback content here"]


def test_title_chapters_rejects_oversize_llm_response():
    """An LLM that returns a wall of text instead of a headline must
    fall back to the heuristic rather than embed the wall of text
    as the title."""
    segs = [{"start": 0.0, "end": 5.0, "text": "short fallback"}]
    b = [ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)]

    class _ChattyRunner:
        def ask(self, transcript, question):
            return "x" * 500

    titles = ch.title_chapters_with_llm(segs, b, runner=_ChattyRunner())
    assert titles == ["short fallback"]


# ---------- build_chapters end-to-end ------------------------------------------


def test_build_chapters_produces_dict_shape():
    segs = [
        {"start": 0.0, "end": 60.0, "text": "Intro segment."},
        {"start": 70.0, "end": 130.0, "text": "Second segment."},
    ]
    out = ch.build_chapters(segs, min_chapter_seconds=30.0, gap_seconds=5.0)
    assert len(out) == 2
    for i, chap in enumerate(out):
        assert chap["index"] == i
        assert "title" in chap
        assert "start" in chap
        assert "end" in chap
        assert "segment_start" in chap
        assert "segment_end" in chap


def test_build_chapters_assigns_sequential_indices():
    segs = [{"start": float(i*60), "end": float(i*60 + 50), "text": f"s{i}"}
            for i in range(5)]
    out = ch.build_chapters(segs, min_chapter_seconds=30.0, gap_seconds=5.0)
    assert [c["index"] for c in out] == list(range(len(out)))


def test_heuristic_title_caps_a_long_unspaced_script_sentence():
    """Chinese/Japanese/Thai text has no spaces, so the word limit never
    applies: one long clause used to become the whole chapter title."""
    long_zh = "今天我们来讨论一下人工智能在医疗领域的应用以及未来的发展趋势和挑战还有很多很多内容"
    segs = [{"start": 0.0, "end": 5.0, "text": long_zh}]
    b = ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)
    title = ch.heuristic_title(segs, b)
    assert title.endswith("…")
    assert len(title) <= 31
    assert title.startswith("今天我们来讨论")


def test_heuristic_title_keeps_a_short_unspaced_script_sentence():
    segs = [{"start": 0.0, "end": 5.0, "text": "今天我们来讨论。第二句。"}]
    b = ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)
    assert ch.heuristic_title(segs, b) == "今天我们来讨论"
