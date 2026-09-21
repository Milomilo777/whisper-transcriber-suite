"""Tests for the hallucination detector heuristics."""
from __future__ import annotations

import pytest

from core import hallucination as h


# ---------- BoH ----------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "Thanks for watching",
    "thanks for watching!",
    "Thank you for watching.",
    "subscribe to my channel",
    "[Music]",
    "♪",
    ".",
    "...",
    "Bye bye",
    "  Thank you   for   watching  ",  # whitespace tolerated
])
def test_detect_boh_matches_known_phrases(text):
    assert h.detect_boh(text) is True


@pytest.mark.parametrize("text", [
    "Thanks for watching the video tonight, see you tomorrow.",
    "Welcome back to the channel.",
    "Hello everyone, and goodbye for now.",
    "",
])
def test_detect_boh_does_not_match_legitimate_text(text):
    assert h.detect_boh(text) is False


# ---------- Repetition ---------------------------------------------------------


def test_detect_repetition_unigram_loop():
    assert h.detect_repetition("the the the the") is True


def test_detect_repetition_two_token_loop():
    assert h.detect_repetition("yes no yes no yes no") is True


def test_detect_repetition_three_token_loop():
    assert h.detect_repetition(
        "one two three one two three one two three"
    ) is True


def test_detect_repetition_normal_speech_not_flagged():
    assert h.detect_repetition(
        "Welcome back to the channel today we explore new ideas."
    ) is False


def test_detect_repetition_two_repeats_below_threshold():
    # Default min_repeats=3 — "the the" only repeats twice.
    assert h.detect_repetition("the the cat sat there") is False


def test_detect_repetition_case_insensitive():
    assert h.detect_repetition("The the THE") is True


def test_detect_repetition_empty_text():
    assert h.detect_repetition("") is False


def test_detect_repetition_custom_min_repeats():
    # Lower the bar: even 2 in a row counts.
    assert h.detect_repetition("hi hi", min_repeats=2) is True


# ---------- VAD disagreement ---------------------------------------------------


def test_vad_disagreement_segment_inside_silence_gap():
    seg = {"start": 5.0, "end": 6.0}
    vad = [(0.0, 4.0), (7.0, 10.0)]
    assert h.detect_vad_disagreement(seg, vad) is True


def test_vad_disagreement_segment_overlaps_speech():
    seg = {"start": 3.5, "end": 4.5}
    vad = [(0.0, 4.0), (7.0, 10.0)]
    assert h.detect_vad_disagreement(seg, vad) is False


def test_vad_disagreement_none_vad_returns_false():
    seg = {"start": 5.0, "end": 6.0}
    assert h.detect_vad_disagreement(seg, None) is False


def test_vad_disagreement_empty_vad_returns_false():
    seg = {"start": 5.0, "end": 6.0}
    assert h.detect_vad_disagreement(seg, []) is False


# ---------- annotate_segments --------------------------------------------------


def test_annotate_segments_flags_boh_and_repetition():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "Welcome back to the channel."},
        {"start": 2.0, "end": 4.0, "text": "Thanks for watching!"},
        {"start": 4.0, "end": 6.0, "text": "the the the the the"},
        {"start": 6.0, "end": 8.0, "text": "Today we cover three topics."},
    ]
    n = h.annotate_segments(segs)
    assert n == 2
    assert segs[0].get("suspect") is None
    assert segs[1]["suspect"] is True
    assert segs[1]["suspect_reason"] == "bag-of-hallucinations"
    assert segs[2]["suspect"] is True
    assert segs[2]["suspect_reason"] == "repetition"
    assert segs[3].get("suspect") is None


def test_annotate_segments_uses_vad_disagreement_when_provided():
    segs = [
        {"start": 0.5, "end": 1.5, "text": "Real speech here."},
        # "you" is in BoH so would flag anyway — use a non-BoH phrase
        # that lives in a silence gap so vad-disagreement is the
        # unique trigger.
        {"start": 4.5, "end": 5.5, "text": "Random hallucinated sentence here."},
    ]
    vad = [(0.0, 2.0), (8.0, 10.0)]
    n = h.annotate_segments(segs, vad_segments=vad)
    assert n == 1
    assert segs[0].get("suspect") is None
    assert segs[1]["suspect_reason"] == "vad-disagreement"


def test_annotate_segments_is_idempotent_on_pre_flagged():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "Thanks for watching!",
         "suspect": True, "suspect_reason": "manual"},
    ]
    n = h.annotate_segments(segs)
    assert n == 0
    assert segs[0]["suspect_reason"] == "manual"


def test_annotate_segments_skips_empty_text():
    segs = [{"start": 0.0, "end": 1.0, "text": ""}]
    n = h.annotate_segments(segs)
    assert n == 0
    assert segs[0].get("suspect") is None


def test_annotate_segments_skips_non_string_text():
    """Segments with non-string text (None, a number from a malformed
    backend payload) must be skipped, not crash on .strip()."""
    segs = [
        {"start": 0.0, "end": 1.0, "text": None},
        {"start": 1.0, "end": 2.0, "text": 123},
        {"start": 2.0, "end": 3.0},
    ]
    n = h.annotate_segments(segs)
    assert n == 0
    assert all(s.get("suspect") is None for s in segs)


def test_normalize_collapses_whitespace_and_case():
    assert h._normalize("  HELLO   WORLD  ") == "hello world"
