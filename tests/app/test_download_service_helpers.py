"""Small pure helpers of ``app.services.download_service`` without their own tests.

File-name tag for a time-range download, the SMTV ``?file=`` name, the
loose name key used to match yt-dlp's announced name to the file on disk,
and the rejection of a negative-zero timecode.
"""
from __future__ import annotations

import pytest

from app.services.download_service import (
    _name_key,
    _parse_timecode,
    _section_name_suffix,
    _smtv_basename_from_url,
)


@pytest.mark.parametrize(
    ("sections", "suffix"),
    [
        (None, ""),
        ("", ""),
        ("*0:00:01-0:00:02", " (clip 0.00.01-0.00.02)"),
        ("*0:00:01-", " (clip 0.00.01-end)"),
        ("*-0:00:02", " (clip 0-0.00.02)"),
    ],
)
def test_section_name_suffix_has_no_colons(sections, suffix):
    assert _section_name_suffix(sections) == suffix
    assert ":" not in _section_name_suffix(sections)  # not allowed in Windows names


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://example.invalid/v?file=some/path/video.mp4", "video.mp4"),
        ("https://example.invalid/v?file=../../escape.mp4", "escape.mp4"),
        ("https://example.invalid/v?x=1&file=clip.mp4", "clip.mp4"),
        ("https://example.invalid/v", None),
        ("https://example.invalid/v?file=", None),
    ],
)
def test_smtv_basename_comes_from_the_file_parameter(url, name):
    assert _smtv_basename_from_url(url) == name


def test_name_key_keeps_only_folded_letters_and_digits():
    assert _name_key("Test 123!") == "test123"
    assert _name_key("O'Neill") == "oneill"
    # An apostrophe replaced by U+FFFD, or curly quotes, must not matter.
    assert _name_key("O\ufffdNeill") == _name_key("O\u2019Neill") == "oneill"


def test_name_key_works_on_persian_names():
    assert _name_key("\u0641\u0627\u06cc\u0644 \u06f1 - \u0635\u0648\u062a\u06cc") == (
        "\u0641\u0627\u06cc\u0644\u06f1\u0635\u0648\u062a\u06cc"
    )


@pytest.mark.parametrize("text", ["-0:00:01", "-0", "0:-0:05", "-0.0"])
def test_a_negative_zero_part_is_rejected(text):
    assert _parse_timecode(text) is None


@pytest.mark.parametrize(
    ("text", "seconds"), [("0:00", 0.0), ("0", 0.0), ("1:30", 90.0), ("24:00:00", 86400.0)]
)
def test_ordinary_timecodes_still_parse(text, seconds):
    assert _parse_timecode(text) == seconds
