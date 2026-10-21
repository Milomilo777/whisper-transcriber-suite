"""The Transcribe tab says "(whole recording)" while the time range is unset."""
from __future__ import annotations


def test_time_range_hint_names_the_whole_recording():
    from app.widgets.tabs import time_range_hint

    assert time_range_hint("0:00:00", "0:00:00") == "(whole recording)"
    assert time_range_hint("", " ") == "(whole recording)"
    assert time_range_hint("0:00:00", "0:05:00") == ""
    assert time_range_hint("1:30", "0:00:00") == ""
    # Text that is not a time is read as unset when the job starts, so the hint is right.
    assert time_range_hint("abc", "0") == "(whole recording)"
