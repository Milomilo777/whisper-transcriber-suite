"""Edge cases of the oTranscribe and SMTV integrations.

* An SRT timecode too long to convert must skip that cue, not abort the import.
* A file name whose reserved Windows device stem is followed by spaces
  (``LPT1 .txt``) is still the device on Windows, so it gets the same
  protective prefix as ``LPT1.txt``. The name comes from a CDN URL.

Hermetic: pure functions.
"""
from __future__ import annotations

import pytest

from core.integrations import otranscribe, smtv


def _srt(*cues: tuple[str, str]) -> str:
    return "\n\n".join(
        f"{i}\n{timing}\n{body}" for i, (timing, body) in enumerate(cues, 1)
    ) + "\n"


def test_srt_cues_parse_to_seconds_and_text():
    text = _srt(("00:00:01,500 --> 00:01:02,000", "hello"), ("01:00:00,000 --> 01:00:01,000", "later"))
    assert list(otranscribe._parse_srt(text)) == [
        (1.5, 62.0, "hello"),
        (3600.0, 3601.0, "later"),
    ]


def test_a_cue_with_an_absurdly_long_timecode_is_skipped_not_fatal():
    huge = "9" * 5000  # past Python's int-from-text digit limit
    text = _srt(
        ("00:00:01,000 --> 00:00:02,000", "before"),
        (f"{huge}:00:00,000 --> 00:00:03,000", "broken"),
        (f"00:00:00,{huge} --> 00:00:03,000", "broken too"),
        ("00:00:04,000 --> 00:00:05,000", "after"),
    )
    cues = list(otranscribe._parse_srt(text))
    assert [body for _s, _e, body in cues] == ["before", "after"]


@pytest.mark.parametrize(
    "name",
    ["LPT1 .txt", "con .mp4", "COM1  .x", "aux  .wav"],
)
def test_a_reserved_device_stem_followed_by_spaces_is_prefixed(name):
    cleaned = smtv._sanitise_filename(name)
    assert cleaned.startswith("_")
    assert cleaned.lstrip("_").split(".", 1)[0].strip().upper() in {
        "LPT1", "CON", "COM1", "NUL", "AUX",
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("LPT1.txt", "_LPT1.txt"),
        ("episode.txt", "episode.txt"),
        ("console.txt", "console.txt"),  # only the exact device names
        ("lpt10 notes.txt", "lpt10 notes.txt"),
    ],
)
def test_ordinary_and_plain_device_names(name, expected):
    assert smtv._sanitise_filename(name) == expected
