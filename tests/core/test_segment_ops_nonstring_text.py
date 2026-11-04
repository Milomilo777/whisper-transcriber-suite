"""Hermetic tests for non-string segment text in core.segment_ops."""
from __future__ import annotations

import pytest

from core import segment_ops


def test_merge_with_next_coerces_non_string_text() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "text": 123},
        {"start": 1.0, "end": 2.0, "text": 456},
    ]
    merged = segment_ops.merge_with_next(segments, 0)
    assert len(merged) == 1
    assert merged[0]["text"] == "123 456"
    assert merged[0]["start"] == 0.0
    assert merged[0]["end"] == 2.0
    assert segments[0]["text"] == 123


def test_merge_with_next_handles_zero_none_and_cjk_text() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "text": 0},
        {"start": 1.0, "end": 2.0, "text": None},
        {"start": 2.0, "end": 3.0, "text": ""},
    ]
    merged_once = segment_ops.merge_with_next(segments, 0)
    assert merged_once[0]["text"] == "0", f"Expected '0' to be preserved, got {merged_once[0]['text']!r}"
    merged_twice = segment_ops.merge_with_next(merged_once, 0)
    assert merged_twice[0]["text"] == "0"

    cjk_segments = [
        {"start": 0.0, "end": 1.0, "text": "你好 "},
        {"start": 1.0, "end": 2.0, "text": " 世界"},
    ]
    assert segment_ops.merge_with_next(cjk_segments, 0)[0]["text"] == "你好世界"


def test_split_at_coerces_non_string_text() -> None:
    segments = [
        {"start": 0.0, "end": 4.0, "text": 1234},
    ]
    split = segment_ops.split_at(segments, 0, 2)
    assert len(split) == 2
    assert split[0]["text"] == "12"
    assert split[1]["text"] == "34"
    assert split[0]["start"] == 0.0
    assert split[0]["end"] == 2.0
    assert split[1]["start"] == 2.0
    assert split[1]["end"] == 4.0
    assert segments[0]["text"] == 1234


def test_split_at_rejects_empty_combining_or_out_of_bounds_on_coerced_text() -> None:
    for bad_text in (None, "", 0):
        segments = [{"start": 0.0, "end": 2.0, "text": bad_text}]
        with pytest.raises(segment_ops.SegmentOpError):
            segment_ops.split_at(segments, 0, 1)

    combining = [{"start": 0.0, "end": 2.0, "text": "e\u0301x"}]
    with pytest.raises(segment_ops.SegmentOpError):
        segment_ops.split_at(combining, 0, 1)
