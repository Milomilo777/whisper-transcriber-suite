"""Regression tests for zero-length and inverted subtitle cues."""
from __future__ import annotations

import re

import pytest

from core.writers import srt, vtt

try:
    from hypothesis import given, settings, strategies as st
except ImportError:  # pragma: no cover - exercised only without hypothesis
    given = None


_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_WORD_RE = re.compile(r"w\d+")


def _ms(groups: tuple[str, ...]) -> int:
    h, m, s, ms = (int(part) for part in groups)
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _cues(body: str) -> list[tuple[int, int, str]]:
    if body.startswith("WEBVTT"):
        body = body[len("WEBVTT"):].lstrip("\n")
    segments = body.split("\n\n")
    out = []
    for block in segments:
        lines = block.splitlines()
        if not lines:
            continue
        time_idx = 1 if lines[0].strip().isdigit() else 0
        match = _TIME_RE.fullmatch(lines[time_idx])
        assert match, block
        start = _ms(tuple(match.groups()[:4]))
        end = _ms(tuple(match.groups()[4:]))
        out.append((start, end, "\n".join(lines[time_idx + 1 :])))
    return out


def _write(fmt: str, segments: list[dict]) -> str:
    return (srt if fmt == "srt" else vtt).write(segments)


def test_zero_and_inverted_cues_get_positive_durations():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "zero duration"},
        {"start": 5.0, "end": 4.0, "text": "end before start"},
    ]
    expected_srt = (
        "1\n"
        "00:00:02,000 --> 00:00:03,000\n"
        "zero duration\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:06,000\n"
        "end before start\n"
    )
    expected_vtt = (
        "WEBVTT\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "zero duration\n\n"
        "00:00:05.000 --> 00:00:06.000\n"
        "end before start\n"
    )
    assert srt.write(segments) == expected_srt
    assert vtt.write(segments) == expected_vtt


def test_six_identical_zero_length_cues_become_one():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "same words"} for _ in range(6)
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 1
        assert cues[0][0] == 2000
        assert cues[0][1] == 3000
        assert cues[0][2].count("same words") == 1


def test_two_different_texts_at_same_instant_keep_both():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "first words"},
        {"start": 2.0, "end": 2.0, "text": "second words"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 1
        assert cues[0][0] == 2000
        assert cues[0][1] == 3000
        assert cues[0][2] == "first words second words"


def test_last_cue_is_extended():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "valid"},
        {"start": 5.0, "end": 5.0, "text": "last cue"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues[-1][0] == 5000
        assert cues[-1][1] == 6000
        assert "last cue" in cues[-1][2]


def test_bad_cue_stops_at_next_start_when_there_is_room():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "short"},
        {"start": 2.4, "end": 3.0, "text": "next"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 2
        assert cues[0][0:2] == (2000, 2400)
        assert cues[1][0:2] == (2400, 3000)


def test_merge_chain_dedupes_identical_text():
    segments = [
        {"start": 2.0, "end": 2.0, "text": text}
        for text in ("y", "z", "z")
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 1
        assert cues[0][2] == "y z"


def test_merge_chain_dedupes_non_adjacent_duplicate():
    segments = [
        {"start": 2.0, "end": 2.0, "text": text}
        for text in ("a", "b", "a")
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 1
        assert cues[0][2] == "a b"


def test_srt_arrow_escape_does_not_merge_distinct_texts():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "a --> b"},
        {"start": 2.0, "end": 2.0, "text": "a \u2192 b"},
    ]
    cues = _cues(srt.write(segments))
    assert len(cues) == 1
    assert cues[0][2] == "a \u2192 b a \u2192 b"


def test_vtt_karaoke_duplicate_text_written_once():
    segments = [
        {
            "start": 2.0,
            "end": 2.0,
            "text": "hi there",
            "words": [
                {"start": 2.0, "end": 2.4, "word": "hi"},
                {"start": 2.4, "end": 2.0, "word": "there"},
            ],
        },
        {
            "start": 2.0,
            "end": 2.0,
            "text": "hi there",
            "words": [
                {"start": 2.1, "end": 2.5, "word": "hi"},
                {"start": 2.5, "end": 2.0, "word": "there"},
            ],
        },
    ]
    body = vtt.write(segments)
    assert body.count("<c>hi</c>") == 1
    assert body.count("<c>there</c>") == 1


def test_duplicate_text_with_different_speakers_is_kept():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "hello", "speaker": "A"},
        {"start": 2.0, "end": 2.0, "text": "hello", "speaker": "B"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert len(cues) == 1
        assert cues[0][2] == "A: hello B: hello"


def test_valid_srt_output_is_byte_identical():
    segments = [
        {"start": 0.0, "end": 1.5, "text": "Hello world"},
        {"start": 1.5, "end": 3.25, "text": "Second line", "speaker": "Speaker 1"},
    ]
    expected = (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "Hello world\n\n"
        "2\n"
        "00:00:01,500 --> 00:00:03,250\n"
        "Speaker 1: Second line\n"
    )
    assert srt.write(segments) == expected


def test_valid_vtt_output_is_byte_identical():
    segments = [
        {"start": 0.0, "end": 1.5, "text": "Hello world"},
        {
            "start": 1.5,
            "end": 3.25,
            "text": "Second line",
            "words": [
                {"start": 1.5, "end": 2.0, "word": "Second"},
                {"start": 2.0, "end": 3.25, "word": "line"},
            ],
        },
    ]
    expected = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.500\n"
        "Hello world\n\n"
        "00:00:01.500 --> 00:00:03.250\n"
        "<00:00:01.500><c>Second</c> <00:00:02.000><c>line</c>\n"
    )
    assert vtt.write(segments) == expected


def _random_segments(rng) -> list[dict]:
    segments = []
    for i in range(rng.randint(0, 12)):
        start = rng.randint(0, 12_000)
        end = start + rng.randint(-2_000, 2_000)
        segments.append(
            {
                "start": start / 1000,
                "end": end / 1000,
                "text": f"w{i}",
            }
        )
    return segments


def _check_property(segments: list[dict]) -> None:
    words = [segment["text"] for segment in segments]
    for fmt in ("srt", "vtt"):
        body = _write(fmt, segments)
        assert _WORD_RE.findall(body) == words
        for start, end, _text in _cues(body):
            assert end > start


if given is not None:
    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=12_000),
                st.integers(min_value=-2_000, max_value=2_000),
            ),
            max_size=12,
        )
    )
    def test_random_cues_keep_words_and_have_positive_duration(raw):
        segments = [
            {
                "start": start / 1000,
                "end": (start + delta) / 1000,
                "text": f"w{i}",
            }
            for i, (start, delta) in enumerate(raw)
        ]
        _check_property(segments)
else:  # pragma: no cover
    def test_random_cues_keep_words_and_have_positive_duration():
        import random

        rng = random.Random(20261103)
        for _ in range(300):
            _check_property(_random_segments(rng))


def _check_words_and_duration(segments: list[dict]) -> None:
    input_words = [
        word
        for segment in segments
        for word in re.findall(r"\S+", segment["text"])
    ]
    for fmt in ("srt", "vtt"):
        body = _write(fmt, segments)
        cues = _cues(body)
        output_words = [
            word
            for _start, _end, text in cues
            for word in re.findall(r"w\d+", text)
        ]
        # Rule 3 may drop an exact duplicate occurrence, never a word type
        # and never reorder: output is an ordered subsequence of input.
        position = 0
        for word in output_words:
            while position < len(input_words) and input_words[position] != word:
                position += 1
            assert position < len(input_words), (fmt, word, input_words, body)
            position += 1
        assert set(output_words) == set(input_words), (fmt, input_words, body)
        assert all(end > start for start, end, _text in cues), body


if given is not None:
    _vocab = st.sampled_from(["w0", "w1", "w2", "w3"])
    _text = st.lists(_vocab, min_size=1, max_size=3).map(" ".join)
    _seg = st.tuples(
        st.integers(min_value=0, max_value=20_000),
        st.integers(min_value=-3_000, max_value=3_000),
        _text,
        st.sampled_from(["", "A", "B"]),
    )

    @settings(max_examples=400, deadline=None)
    @given(st.lists(_seg, max_size=10))
    def test_property_words_appear_in_order_and_durations_are_positive(raw):
        segments = [
            {
                "start": start / 1000,
                "end": (start + delta) / 1000,
                "text": text,
                **({"speaker": speaker} if speaker else {}),
            }
            for start, delta, text, speaker in raw
        ]
        _check_words_and_duration(segments)
else:  # pragma: no cover
    def test_property_words_appear_in_order_and_durations_are_positive():
        import random

        rng = random.Random(20261103)
        vocab = ["w0", "w1", "w2", "w3"]
        for _ in range(2_000):
            segments = []
            for _ in range(rng.randint(0, 10)):
                start = rng.randint(0, 20_000)
                segments.append(
                    {
                        "start": start / 1000,
                        "end": (start + rng.randint(-3_000, 3_000)) / 1000,
                        "text": " ".join(
                            rng.choice(vocab) for _ in range(rng.randint(1, 3))
                        ),
                    }
                )
            _check_words_and_duration(segments)



def test_merge_into_zero_length_next_gets_full_short_display_time():
    # Two 100 ms-close bad cues merge. The merged cue used to keep the next
    # cue's zero and the loop only healed "end <= start", so a merge into a
    # zero-length next cue got whatever short end it had (1 ms, 50 ms).
    # It is now healed exactly like any bad cue: start + 1000 ms.
    segments = [
        {"start": 2.0, "end": 2.0, "text": "b"},
        {"start": 2.001, "end": 2.0, "text": "v"},
        {"start": 8.0, "end": 9.0, "text": "far"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues == [(2000, 3000, "b v"), (8000, 9000, "far")]


def test_merge_into_zero_length_next_clipped_to_following_start():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "b"},
        {"start": 2.05, "end": 2.05, "text": "v"},
        {"start": 2.4, "end": 3.0, "text": "next"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues == [(2000, 2400, "b v"), (2400, 3000, "next")]


def test_merge_into_inverted_next_keeps_full_short_display_time():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "b"},
        {"start": 2.0, "end": 1.9, "text": "v"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues == [(2000, 3000, "b v")]


def test_merge_chain_into_bad_cues_respects_next_start():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "b"},
        {"start": 2.0, "end": 1.9, "text": "v"},
        {"start": 2.05, "end": 2.04, "text": "w"},
        {"start": 3.0, "end": 4.0, "text": "far"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues == [(2000, 3000, "b v w"), (3000, 4000, "far")]


def test_bad_cue_followed_by_valid_keeps_valid_end():
    segments = [
        {"start": 2.0, "end": 2.0, "text": "bad"},
        {"start": 2.15, "end": 9.0, "text": "valid long"},
    ]
    for fmt in ("srt", "vtt"):
        cues = _cues(_write(fmt, segments))
        assert cues == [(2000, 2150, "bad"), (2150, 9000, "valid long")]
