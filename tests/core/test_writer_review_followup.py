"""Preserve bilingual language rows and reject unusable word clocks."""
import json
import re

import pytest

from core.writers import ass, bilingual_srt, json_writer
from core.writers.base import MAX_SECONDS


@pytest.mark.parametrize("originals,translations,speakers,expected", [
    (["Hello there", "Goodbye"], ["Salut", "Au revoir"], [None, None],
     ["Hello there Goodbye", "Salut Au revoir"]),
    (["Hello", "Bye"], ["T1", "T2"], ["A", "B"],
     ["A: Hello B: Bye", "T1 T2"]),
    (["Hello", "Bye"], ["", "T2"], [None, None], ["Hello Bye", "T2"]),
    (["", "Bye"], ["T1", "T2"], ["A", "B"], ["B: Bye", "A: T1 T2"]),
    (["اول", "دوم"], ["الأول", "الثاني"], [None, None],
     ["اول دوم", "الأول الثاني"]),
])
def test_merged_bilingual_cue_keeps_exact_language_rows(originals, translations, speakers, expected):
    segments = [dict(start=1, end=1, text=originals[0], speaker=speakers[0]),
                dict(start=1.05, end=3, text=originals[1], speaker=speakers[1])]
    lines = bilingual_srt.write(segments, translations).splitlines()
    assert lines[2:] == expected


@pytest.mark.parametrize("end", [None, "abc", float("nan"), float("inf")])
def test_unusable_word_end_uses_its_own_start(end):
    result = json.loads(json_writer.write([dict(start=10, end=20, text="a b", words=[
        dict(word="a", start=10, end=end), dict(word="b", start=15, end=16)])]))
    assert result[0]["words"][0]["end"] == 10
    assert result[0]["words"][1]["end"] == 16


def test_inferred_word_clock_is_bounded_and_roundtrips():
    body = json_writer.write([dict(start=10, text="a b", words=[
        dict(word="a", start=10, end=10.5), dict(word="b", start=9999, end=1e308)])])
    result = json.loads(body)
    assert 10 < result[0]["end"] <= MAX_SECONDS
    assert all(10 <= word["start"] <= word["end"] <= MAX_SECONDS for word in result[0]["words"])
    assert json_writer.write(result) == body


def test_ass_speaker_controls_do_not_corrupt_dialogue():
    body = ass.write([dict(start=0, end=1, text="Hello", speaker="Speaker\x001\x01")])
    assert "\x00" not in body and "\x01" not in body
    assert "Speaker1" in body


def test_valid_bilingual_cues_keep_original_bytes():
    assert bilingual_srt.write([dict(start=0, end=1, text="Hello", speaker="A"),
                                dict(start=2, end=3, text="Bye")], ["Salut", ""]) == (
        "1\n00:00:00,000 --> 00:00:01,000\nA: Hello\nSalut\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nBye\n")


def test_bilingual_merge_retains_order_with_arbitrary_clocks():
    hypothesis = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st

    @hypothesis.settings(max_examples=250, deadline=None)
    @hypothesis.given(st.lists(st.tuples(st.integers(0, 2000), st.booleans()),
                               min_size=1, max_size=12))
    def check(clocks):
        segments = [dict(start=start / 1000, end=(start + (100 if valid else 0)) / 1000,
                         text=f"O{i}") for i, (start, valid) in enumerate(clocks)]
        body = bilingual_srt.write(segments, [f"T{i}" for i in range(len(clocks))])
        assert re.findall(r"\bO\d+\b", body) == [f"O{i}" for i in range(len(clocks))]
        assert re.findall(r"\bT\d+\b", body) == [f"T{i}" for i in range(len(clocks))]
        for line in body.splitlines():
            assert not (re.search(r"\bO\d+\b", line) and re.search(r"\bT\d+\b", line))

    check()
