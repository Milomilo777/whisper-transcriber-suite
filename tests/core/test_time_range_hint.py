"""The note beside the Transcribe tab's time range.

"(whole recording)" while the range is unset; a red line when a side is not a time,
since App.add reads such text as unset and would transcribe the whole recording while
the user meant a part (code review, 2026-10-21).
"""
from __future__ import annotations

from app.widgets.tabs import time_range_hint


def test_an_unset_range_is_the_whole_recording():
    assert time_range_hint("0:00:00", "0:00:00") == ("(whole recording)", False)
    assert time_range_hint("", " ") == ("(whole recording)", False)
    assert time_range_hint("0", "") == ("(whole recording)", False)


def test_a_set_range_needs_no_note():
    assert time_range_hint("0:00:00", "0:05:00") == ("", False)
    assert time_range_hint("1:30", "0:00:00") == ("", False)


def test_text_that_is_not_a_time_is_flagged_not_called_whole():
    for start, end in (("abc", "0"), ("5 min", "0:00:00"), ("0:00:00", "5;00"), ("-1", ""),
                       ("1:00", "99:00:00")):
        text, wrong = time_range_hint(start, end)
        assert wrong and text == "Not a time: use H:MM:SS", (start, end)
