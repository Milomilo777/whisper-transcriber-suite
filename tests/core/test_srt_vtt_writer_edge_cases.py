"""Edge cases for the SRT, bilingual SRT and WebVTT writers.

The cue-time separator ``-->`` must appear once per cue, on the timing
line only: a speaker label that contains it is escaped like the cue text
is. Also covers Persian/emoji text, blank cues, karaoke word timing and
clamping of nonsensical times. Hermetic: pure string functions.
"""
from __future__ import annotations

import pytest

from core.writers import bilingual_srt, srt, vtt

_SEGMENT = {"start": 0.0, "end": 1.0, "text": "text", "speaker": "A --> B"}
_PERSIAN_EMOJI = "مرحبا world \U0001f600"


def _arrow_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if "-->" in line]


def test_srt_speaker_label_cannot_add_a_second_separator():
    out = srt.write([_SEGMENT])
    assert len(_arrow_lines(out)) == 1
    assert "A → B: text" in out


def test_bilingual_srt_speaker_label_cannot_add_a_second_separator():
    out = bilingual_srt.write([_SEGMENT], ["translated"])
    assert len(_arrow_lines(out)) == 1
    assert "A → B: text" in out


def test_vtt_speaker_label_keeps_one_separator():
    out = vtt.write([_SEGMENT])
    assert len(_arrow_lines(out)) == 1


def test_srt_keeps_the_label_of_an_ordinary_speaker():
    out = srt.write([{**_SEGMENT, "speaker": "Speaker 1"}])
    assert "Speaker 1: text" in out


@pytest.mark.parametrize("writer", [srt, vtt])
def test_persian_and_emoji_text_is_kept(writer):
    out = writer.write([{"start": 0.0, "end": 1.0, "text": _PERSIAN_EMOJI}])
    assert _PERSIAN_EMOJI in out


@pytest.mark.parametrize(
    ("writer", "empty"), [(srt, ""), (vtt, "WEBVTT\n")]
)
def test_no_segments_and_blank_segments_give_no_cues(writer, empty):
    assert writer.write([]) == empty
    assert writer.write([{"start": 0.0, "end": 1.0, "text": "   "}]) == empty


def test_vtt_blank_text_drops_the_cue_even_with_word_timing():
    seg = {
        "start": 0.0, "end": 1.0, "text": "",
        "words": [{"word": "ignored", "start": 0.0, "end": 1.0}],
    }
    assert vtt.write([seg]) == "WEBVTT\n"


def test_vtt_karaoke_marks_each_word_boundary():
    seg = {
        "start": 0.0, "end": 1.0, "text": "a b",
        "words": [
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 0.5, "end": 1.0},
        ],
    }
    assert "<c>a</c> <00:00:00.500><c>b</c>" in vtt.write([seg])


def test_srt_negative_start_is_clamped_to_zero():
    out = srt.write([{"start": -5.0, "end": 2.0, "text": "time"}])
    assert "00:00:00,000 --> 00:00:02,000" in out
