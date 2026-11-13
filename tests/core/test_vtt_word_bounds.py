"""Karaoke timestamps remain strictly inside their final WebVTT cue."""
from copy import deepcopy
import html
import re

import pytest

from core.writers import vtt


def _milliseconds(clock):
    hours, minutes, seconds = clock.split(":")
    return round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def _assert_valid_markers(body):
    count = 0
    for block in body.split("\n\n"):
        if " --> " not in block:
            continue
        timing, payload = block.split("\n", 1)
        start, end = map(_milliseconds, timing.split(" --> "))
        markers = [_milliseconds(value) for value in re.findall(r"<(\d{2,}:\d{2}:\d{2}\.\d{3})>", payload)]
        assert all(start < value < end for value in markers)
        assert all(a < b for a, b in zip(markers, markers[1:]))
        count += len(markers)
    return count


@pytest.mark.parametrize("start,end,word_starts", [
    (92.12, 96.12, [91.7, 92.4, 93.48, 96.12]),
    (308.78, 311.62, [308.6, 308.96, 309.32, 310.46]),
    (2, 4, [2, 2.5, 3, 4]),
    (2, 4, [1, 2.5, 3, 5]),
    (2, 4, [2.5, 3.5, 3, 3.8]),
    (2, 4, [2.5, 2.5, 3, 3.5]),
    (2, 4, [2.0001, 2.0002, 2.0003, 2.0004]),
])
def test_alignment_drift_never_emits_invalid_or_duplicate_markers(start, end, word_starts):
    segment = {"start": start, "end": end, "text": "one two three four",
               "words": [{"start": stamp, "word": word} for stamp, word in zip(word_starts, ("one", "two", "three", "four"))]}
    before = deepcopy(segment)
    body = vtt.write([segment])
    _assert_valid_markers(body)
    assert "one two three four" in re.sub(r"<[^>]*>", "", body)
    assert segment == before


def test_valid_internal_word_markers_are_byte_identical():
    segment = {"start": 2, "end": 4, "text": "one two",
               "words": [{"start": 2.5, "word": "one"}, {"start": 3.5, "word": "two"}]}
    assert vtt.write([segment]) == (
        "WEBVTT\n\n00:00:02.000 --> 00:00:04.000\n"
        "<00:00:02.500><c>one</c> <00:00:03.500><c>two</c>\n")


@pytest.mark.parametrize("start", [None, "bad", -3, float("nan"), float("inf"), 10**400])
def test_unusable_word_time_preserves_word_without_invalid_marker(start):
    body = vtt.write([{"start": 2, "end": 4, "text": "word", "words": [{"start": start, "word": "word"}]}])
    _assert_valid_markers(body)
    assert "<c>word</c>" in body


def test_merged_repaired_cue_uses_its_final_bounds_and_marker_order():
    segments = [{"start": 2, "end": 2, "text": "one", "words": [{"start": 3.5, "word": "one"}]},
                {"start": 2.05, "end": 4, "text": "two", "words": [{"start": 2.5, "word": "two"}]}]
    body = vtt.write(segments)
    assert body.count(" --> ") == 1
    _assert_valid_markers(body)
    assert "one two" in re.sub(r"<[^>]*>", "", body)


def test_timestamp_shaped_literal_text_and_speaker_are_preserved():
    body = vtt.write([{"start": 2, "end": 4, "speaker": "<00:00:03.000>",
                       "text": "<00:00:03.000> & text"}])
    assert _assert_valid_markers(body) == 0
    assert "<00:00:03.000> & text" in html.unescape(body)
