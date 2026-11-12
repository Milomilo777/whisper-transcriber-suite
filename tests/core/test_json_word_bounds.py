"""JSON word clocks remain inside the cue used by downstream players."""
from copy import deepcopy
import json
import math

import pytest

from core.writers import json_writer


def test_native_alignment_overrun_is_clamped_to_segment_end():
    segments = [{"start": 23.84, "end": 31.84, "text": "Final word.",
                 "words": [{"start": 31.58, "end": 31.92,
                            "word": "word.", "probability": 0.87}]}]
    word = json.loads(json_writer.write(segments))[0]["words"][0]
    assert word == {"start": 31.58, "end": 31.84,
                    "word": "word.", "probability": 0.87}


@pytest.mark.parametrize("start,end,expected", [
    (1.0, 2.5, (2.0, 2.5)),
    (0.0, 1.0, (2.0, 2.0)),
    (5.0, 6.0, (4.0, 4.0)),
    (3.5, 2.5, (3.5, 3.5)),
    (float("nan"), float("inf"), (2.0, 4.0)),
    (None, "bad", (2.0, 4.0)),
    (3.0, 10**1000, (3.0, 4.0)),
])
def test_word_clock_repair_preserves_payload(start, end, expected):
    segment = {"start": 2.0, "end": 4.0, "text": "word",
               "words": [{"start": start, "end": end,
                          "word": "word", "probability": 0.75}]}
    word = json.loads(json_writer.write([segment]))[0]["words"][0]
    assert (word["start"], word["end"]) == expected
    assert word["word"] == "word"
    assert word["probability"] == 0.75


@pytest.mark.parametrize("start,end", [(-2.0, -1.0), (4.0, 2.0),
                                        (float("inf"), float("nan"))])
def test_malformed_parent_still_provides_valid_word_bounds(start, end):
    segment = {"start": start, "end": end, "text": "word",
               "words": [{"start": -3.0, "end": 8.0, "word": "word"}]}
    saved = json.loads(json_writer.write([segment]))[0]
    word = saved["words"][0]
    assert math.isfinite(saved["start"]) and math.isfinite(saved["end"])
    assert 0 <= saved["start"] <= word["start"] <= word["end"] <= saved["end"]


def test_valid_alignment_metadata_and_input_are_preserved():
    segments = [{"start": 2.0, "end": 4.0, "text": "word", "speaker": "Speaker 1",
                 "suspect": True, "suspect_reason": "review",
                 "words": [{"start": 2.5, "end": 3.5, "word": "word", "probability": 0.9}]}]
    before = deepcopy(segments)
    assert json.loads(json_writer.write(segments)) == before
    assert segments == before


def test_repair_does_not_mutate_shared_segments_or_words():
    segments = [{"start": 2.0, "end": 4.0, "text": "word",
                 "words": [{"start": 1.0, "end": 8.0, "word": "word"}]}]
    before = deepcopy(segments)
    json_writer.write(segments)
    assert segments == before