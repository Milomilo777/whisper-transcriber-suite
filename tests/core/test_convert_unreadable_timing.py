"""A cue with an unreadable timing line must not swallow the cues after it.

``core.convert._parse_cue_format`` skips a ``-->`` line it cannot read and
its payload, but in a compact SRT (cue number / text lines with no blank
separator between cues) the payload runs to the NEXT TIMING LINE, not to
the next blank line. Stopping only at a blank line dropped every following
valid cue in the file.
"""
from core import convert


COMPACT_SRT_BAD_TIMING = (
    "garbage --> here\n"
    "00:00:01,000 --> 00:00:02,000\n"
    "hello\n"
    "00:00:03,000 --> 00:00:04,000\n"
    "world\n"
)


def test_unreadable_timing_line_does_not_swallow_following_cues():
    segments = convert._parse_cue_format(COMPACT_SRT_BAD_TIMING, "compact.srt")
    assert [s["text"] for s in segments] == ["hello", "world"]


def test_unreadable_timing_line_still_skips_its_own_payload():
    # The malformed cue's payload ("stray text") belongs to the unreadable
    # cue and stays skipped; only the readable cues survive.
    text = (
        "garbage --> here\n"
        "stray text\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "hello\n"
    )
    segments = convert._parse_cue_format(text, "compact.srt")
    assert [s["text"] for s in segments] == ["hello"]


def test_unreadable_timing_line_with_blank_lines_unchanged():
    # The blank-separated shape keeps working exactly as before.
    text = "garbage --> here\n\n00:00:01,000 --> 00:00:02,000\nhello\n"
    segments = convert._parse_cue_format(text, "compact.srt")
    assert [s["text"] for s in segments] == ["hello"]
