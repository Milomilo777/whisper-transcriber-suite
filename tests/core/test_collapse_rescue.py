"""Collapsed windows and silent-looking gaps are read again (ADR 0017).

The measured case: a 73-second Persian phone call, large-v3 on a CPU, came back as
"0:00 -> 0:30  two words" with the rest of that window's speech gone, in every setting tried;
reading it again in pieces of at most 15 seconds gave 47 words. Pure tests: no model, no audio.
"""
from __future__ import annotations

from typing import Any

import pytest

from core import collapse_rescue as cr


def seg(start: float, end: float, text: str) -> dict[str, Any]:
    return {"start": start, "end": end, "text": text}


CALL = [
    seg(0.0, 30.3, "آقای واسمی"),
    seg(30.4, 32.1, "ببخشید همش تو زنگ زنی ها"),
    seg(32.1, 33.0, "نه ببخشید"),
    seg(33.0, 35.4, "من هم باید زنگ بزنم خیلی بچه بودم"),
]


# --- detection --------------------------------------------------------------------------------

def test_the_phone_call_window_is_found():
    spans = cr.find_suspect_spans(CALL, 72.9)
    assert spans[0] == cr.Span(0.0, 30.3, 0, 1, "collapsed")


def test_a_normal_transcript_has_no_suspect_span():
    normal = [seg(i * 4.0, i * 4.0 + 3.5, "a normal sentence of eight short words here") for i in range(20)]
    assert cr.find_suspect_spans(normal, 80.0) == []


def test_a_long_chinese_segment_with_many_characters_is_not_collapsed():
    # Chinese counts characters (core.text_metrics): 30 characters in 25 s is real text.
    assert cr.find_suspect_spans([seg(0.0, 25.0, "我們今天討論的是一個非常重要的問題大家都應該認真地聽一下吧好")], 25.0) == []


def test_gaps_before_between_and_after_segments_are_found():
    spans = cr.find_suspect_spans([seg(20.0, 22.0, "hello there"), seg(40.0, 42.0, "and again")], 70.0)
    assert [(s.kind, s.start, s.end, s.first, s.last) for s in spans] == [
        ("gap", 0.0, 20.0, 0, 0), ("gap", 22.0, 40.0, 1, 1), ("gap", 42.0, 70.0, 2, 2)]


def test_unusable_times_are_skipped_not_fatal():
    spans = cr.find_suspect_spans([seg(None, 5, "x"), {"start": "a", "end": 3}, seg(5, 1, "y")], 0.0)  # type: ignore[arg-type]
    assert spans == []


# --- pieces, acceptance, splice --------------------------------------------------------------------

def test_pieces_are_at_most_fifteen_seconds_and_never_tiny():
    runs = [(0.0, 0.4), (0.4, 1.8), (1.8, 6.1), (6.1, 8.5), (8.5, 11.9), (11.9, 13.3), (13.6, 17.5),
            (17.5, 18.7), (18.7, 20.1), (20.1, 22.0), (22.0, 24.1), (24.1, 27.8), (27.8, 30.0)]
    pieces = cr.group_pieces(runs)
    assert pieces[0][0] == 0.0 and pieces[-1][1] == 30.0
    # The 15-s limit wins over the 3-s minimum: a short tail that cannot join stays on its own.
    assert pieces == [(0.0, 13.3), (13.6, 27.8), (27.8, 30.0)]
    assert all(cr.MIN_PIECE_KEEP_S <= b - a <= cr.PIECE_MAX_S for a, b in pieces)


def test_short_pieces_never_grow_past_the_piece_limit():
    # Review finding: a short piece joined across a long pause made a 31-s piece.
    pieces = cr.group_pieces([(0.0, 2.0), (2.5, 4.0), (30.0, 31.0)])
    assert all(b - a <= cr.PIECE_MAX_S for a, b in pieces)
    assert pieces == [(0.0, 4.0), (30.0, 31.0)]
    assert cr.group_pieces([(0.0, 0.4), (40.0, 52.0)]) == [(40.0, 52.0)]  # a lone blip is dropped


def test_a_repeating_second_reading_is_refused():
    loop = [seg(i, i + 1, "موسیقی") for i in range(6)]
    ok, why = cr.accept([seg(0, 30, "آقای واسمی")], loop)
    assert not ok and "repeats" in why


def test_a_gap_needs_real_density_of_words():
    few = [seg(0, 5, "thank you for watching this video")]  # 6 words over 60 s of sound
    assert cr.accept([], few, kind="gap", speech_s=60.0)[0] is False
    assert cr.accept([], few, kind="gap", speech_s=10.0)[0] is True


def test_a_long_gap_is_never_decoded():
    def speech_in(a, b):
        pytest.fail("a 20-minute gap must be skipped before decoding")

    out, report = cr.rescue([seg(0, 3, "hello there"), seg(1203, 1205, "and again")], 1205.0, speech_in,
                            lambda a, b: [])
    assert out[0]["text"] == "hello there" and not report.kept  # a gap is skipped quietly


def test_a_filled_gap_is_flagged_for_review_and_pause_is_honoured():
    paused: list[int] = []
    words = "one two three four five six seven eight nine ten eleven twelve"
    out, report = cr.rescue([seg(0, 3, "hello there"), seg(30, 33, "and again")], 33.0, _speech_everywhere,
                            lambda a, b: [seg(a, b, words)], before_piece=lambda: paused.append(1))
    assert report.rescued and paused
    filled = [s for s in out if s["text"] == words]
    assert filled and all(s["suspect"] for s in filled)


def test_a_second_reading_must_clearly_add_text():
    assert cr.accept([seg(0, 30, "two words")], [seg(0, 5, "three more words")])[0] is False
    assert cr.accept([seg(0, 30, "two words")], [seg(0, 5, "one two three four five six")])[0] is True


# --- the whole rescue with stand-ins --------------------------------------------------------------

RESCUED = [seg(0.0, 2.0, "آقای واسمی"), seg(2.0, 4.0, "خیلی جدید خوبی ردیفی"),
           seg(4.0, 6.0, "مختصم سلامتی تا خوبی"), seg(15.0, 20.2, "بجایی سرکاری"),
           seg(20.2, 22.2, "سرکار نه آمدن پیشی که بچه ها")]


def _speech_everywhere(start: float, end: float) -> list[tuple[float, float]]:
    return [(start, end)]


def test_the_collapsed_window_is_replaced_and_the_rest_is_untouched():
    pieces: list[tuple[float, float]] = []

    def read(start: float, end: float) -> list[dict[str, Any]]:
        pieces.append((start, end))
        return [s for s in RESCUED if start <= s["start"] < end]

    out, report = cr.rescue(CALL, 72.9, _speech_everywhere, read)
    assert out[: len(RESCUED)] == RESCUED
    assert out[len(RESCUED):] == CALL[1:]  # the very same dicts, in order
    assert all(out[len(RESCUED) + i] is CALL[1 + i] for i in range(3))
    assert report.rescued == [(0.0, 30.3, 2, sum(len(s["text"].split()) for s in RESCUED))]
    assert all(b - a <= cr.PIECE_MAX_S + cr.PIECE_MIN_S for a, b in pieces)
    assert any("again in shorter pieces" in line for line in report.lines())


def test_music_or_silence_is_left_alone():
    out, report = cr.rescue(CALL, 72.9, lambda a, b: [], lambda a, b: pytest.fail("no speech, no reading"))
    assert out == CALL and not report.rescued and not report.kept


def test_a_refused_reading_keeps_the_text_and_warns():
    out, report = cr.rescue(CALL, 72.9, _speech_everywhere, lambda a, b: [seg(a, a + 1, "um")])
    assert out == CALL
    assert report.kept and report.lines()[0].startswith("WARN:")


def test_the_rescue_budget_caps_a_noisy_file():
    many = [seg(i * 40.0, i * 40.0 + 30.0, "hm") for i in range(10)]  # ten collapsed windows
    calls: list[float] = []

    def read(start: float, end: float) -> list[dict[str, Any]]:
        calls.append(start)
        return [seg(start, start + 1, "one two three four five six seven")]

    _out, report = cr.rescue(many, 400.0, _speech_everywhere, read)
    rescued_s = sum(end - start for start, end, _o, _n in report.rescued)
    assert rescued_s <= cr.MAX_RESCUED_FRACTION * 400.0 + 1e-6
    assert any("too long" in why for _a, _b, why in report.kept)


def test_cancel_stops_the_rescue():
    out, _report = cr.rescue(CALL, 72.9, _speech_everywhere, lambda a, b: RESCUED, cancelled=lambda: True)
    assert out == CALL


# --- properties -----------------------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies


@st.composite
def transcripts(draw: Any) -> list[dict[str, Any]]:
    n = draw(st.integers(0, 25))
    t = 0.0
    out = []
    for _ in range(n):
        t += draw(st.floats(0.0, 25.0))
        length = draw(st.floats(0.1, 40.0))
        words = draw(st.integers(0, 12))
        out.append(seg(round(t, 2), round(t + length, 2), " ".join(["w"] * words)))
        t += length
    return out


@hypothesis.given(st.lists(st.tuples(st.floats(0.0, 200.0), st.floats(0.0, 40.0)), max_size=30))
@hypothesis.settings(max_examples=300, deadline=None)
def test_property_pieces_stay_within_the_limit_and_the_runs(runs):
    ordered = sorted((a, a + d) for a, d in runs)
    pieces = cr.group_pieces(ordered)
    assert all(b - a <= cr.PIECE_MAX_S + 1e-6 for a, b in pieces)
    if ordered:
        assert all(min(a for a, _ in ordered) - 1e-6 <= a <= b <= max(b for _, b in ordered) + 1e-6
                   for a, b in pieces)


@hypothesis.given(transcripts(), st.floats(0.0, 2000.0))
@hypothesis.settings(max_examples=300, deadline=None)
def test_property_nothing_changes_when_no_second_reading_is_kept(segments, duration):
    out, report = cr.rescue(segments, duration, _speech_everywhere, lambda a, b: [])
    assert out == segments and not report.rescued


@hypothesis.given(transcripts(), st.floats(0.0, 2000.0))
@hypothesis.settings(max_examples=300, deadline=None)
def test_property_text_outside_replaced_stretches_is_kept_in_order(segments, duration):
    def read(start: float, end: float) -> list[dict[str, Any]]:
        return [seg(start, min(end, start + 2.0), "new one two three four five six seven")]

    out, report = cr.rescue(segments, duration, _speech_everywhere, read)
    replaced = [(a, b) for a, b, _o, _n in report.rescued]
    kept = [s for s in segments
            if not any(a <= s["start"] and s["end"] <= b and s["text"] != "" for a, b in replaced)]
    survivors = [s for s in out if any(s is k for k in segments)]
    assert [id(s) for s in survivors] == [id(s) for s in kept if any(s is o for o in out)]
    assert all(any(s is o for o in out) for s in segments
               if not any(a <= s["start"] < b for a, b in replaced))
    starts = [float(s["start"]) for s in out]
    assert starts == sorted(starts) or [float(s["start"]) for s in segments] != sorted(
        float(s["start"]) for s in segments)
