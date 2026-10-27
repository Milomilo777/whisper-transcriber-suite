"""format_views at the K/M rounding boundary.

``:.0f`` rounds 999,999/1000 up to "1000", so a video one view short of a
million showed "1000K views" -- a figure in a unit the function itself
replaces with the M branch one view later.
"""
from __future__ import annotations

from app.widgets.smtv_tab import format_views


def test_views_just_under_a_million_never_show_1000k() -> None:
    assert format_views(999_999) == "1.0M views"
    assert format_views(999_500) == "1.0M views"


def test_views_that_round_below_1000k_keep_the_k_form() -> None:
    assert format_views(999_499) == "999K views"
    assert format_views(52000) == "52K views"
    assert format_views(6362) == "6.4K views"
    assert format_views(999) == "999 views"
    assert format_views(1_400_000) == "1.4M views"
    assert format_views(None) == ""
