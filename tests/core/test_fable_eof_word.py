"""Preserve an untimed trailing token on the exact audio boundary."""
import pytest
from core import transcriber as tr


def test_zero_length_word_at_eof_retains_text_in_bounded_writers():
    segment = {"start": 9.2, "end": 10., "text": "ok bye", "words": [
        {"start": 9.2, "end": 9.6, "word": "ok"},
        {"start": 10., "end": 10., "word": " bye"},
    ]}
    from copy import deepcopy
    original = deepcopy(segment)
    bounded = tr._cap_segment(segment, 10.)
    assert segment == original
    assert bounded["words"][-1] == segment["words"][-1]
    for fmt in ("srt", "vtt", "ass", "json"):
        rows = tr._segments_for_writer([segment], 10., fmt)
        assert "bye" in tr.get_writer(fmt)(rows, "source.wav")


def test_segment_starting_at_eof_still_rejected():
    with pytest.raises(tr._TimingBoundsError):
        tr._cap_segment({"start": 10., "end": 10., "text": "outside"}, 10.)


@pytest.mark.parametrize("start,end", [(10.001, 10.001), (-.1, 1.), (float("nan"), 1.), (1., float("inf")), (2., 1.)])
def test_invalid_word_bounds_still_rejected(start, end):
    segment = {"start": 0., "end": 10., "text": "keep", "words": [{"start": start, "end": end, "word": "keep"}]}
    with pytest.raises(tr._TimingBoundsError):
        tr._cap_segment(segment, 10.)
