"""Retain late-window decode text without publishing timestamps after EOF."""
from types import SimpleNamespace

import pytest

from core.backends import faster_whisper_be as be


@pytest.mark.parametrize("frames", [104, [104]])
@pytest.mark.parametrize("failure", ["index_error", "collapsed"])
def test_raw_fallback_tail_uses_the_actual_decode_window(monkeypatch, frames, failure):
    model = object.__new__(be.WhisperModel)
    model.frames_per_second = 100
    tokenizer = SimpleNamespace(decode=lambda tokens: "".join({1: " first", 2: " second"}[i] for i in tokens))
    group = [
        dict(seek=59896, start=598.96, end=604.96, tokens=[1], text=" first"),
        dict(seek=59896, start=604.96, end=606.96, tokens=[2], text=" second"),
    ]

    def unusable_alignment(self, groups, *args):
        if failure == "index_error":
            raise IndexError("truncated optional alignment")
        for rows in groups:
            for row in rows:
                row.update(end=row["start"], words=[])
        return 598.96

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", unusable_alignment)
    model.add_word_timestamps([group], tokenizer, None, frames, "", "", 598.96)

    assert [(row["start"], row["end"]) for row in group] == [(598.96, 600.0)]
    assert group[0]["tokens"] == [1, 2]
    assert group[0]["text"] == " first second"
    assert group[0]["words"] == []


def test_valid_alignment_keeps_its_word_times(monkeypatch):
    model = object.__new__(be.WhisperModel)
    model.frames_per_second = 100
    group = [dict(seek=59896, start=598.96, end=600.0, tokens=[1])]
    words = [dict(start=599.0, end=599.8, word=" first")]

    def valid_alignment(self, groups, *args):
        groups[0][0].update(start=599.0, end=599.8, words=words)
        return 599.8

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", valid_alignment)
    result = model.add_word_timestamps([group], None, None, [104], "", "", 598.96)
    assert result == 599.8
    assert group[0]["words"] == words
    assert (group[0]["start"], group[0]["end"]) == (599.0, 599.8)


def test_unknown_frame_extent_does_not_invent_a_new_boundary(monkeypatch):
    model = object.__new__(be.WhisperModel)
    model.frames_per_second = 100
    group = [dict(start=2.0, end=4.0, tokens=[1])]

    def unusable_alignment(self, groups, *args):
        groups[0][0].update(end=2.0, words=[])
        return 2.0

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", unusable_alignment)
    model.add_word_timestamps([group], None, None, None, "", "", 2.0)
    assert (group[0]["start"], group[0]["end"]) == (2.0, 4.0)
    assert group[0]["tokens"] == [1]


def test_all_late_predictions_keep_text_in_the_encoded_window(monkeypatch):
    model = object.__new__(be.WhisperModel)
    model.frames_per_second = 100
    group = [dict(seek=59896, start=604.0, end=606.0, tokens=[1], text=" kept")]
    tokenizer = SimpleNamespace(decode=lambda tokens: " kept")

    def failed_alignment(*args):
        raise IndexError("no alignment")

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", failed_alignment)
    model.add_word_timestamps([group], tokenizer, None, [104], "", "", 598.96)
    assert (group[0]["start"], group[0]["end"]) == (598.96, 600.0)
    assert group[0]["tokens"] == [1] and group[0]["text"] == " kept"
    assert group[0]["words"] == []


def test_fallback_does_not_skip_a_second_decode_window(monkeypatch):
    import numpy as np
    from tests.core.test_word_timing_safety import model_for_loop

    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch, windows=2)
    seeks = []

    def split(**kwargs):
        seek = kwargs["seek"]
        seeks.append(seek)
        start = kwargs["time_offset"]
        return ([dict(start=start, end=start + 1.5, tokens=[1], seek=seek)],
                seek + 100, False)

    monkeypatch.setattr(model, "_split_segments_by_timestamps", split)
    result = list(model.generate_segments(np.zeros((80, 201)), tokenizer, options, False))
    assert seeks == [0, 100]
    assert [(row.start, row.end) for row in result] == [(0.0, 1.0), (1.0, 2.0)]
    assert all(row.text == " Yes." and not row.words for row in result)
