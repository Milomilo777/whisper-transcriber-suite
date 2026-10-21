"""elide_to_width: a long name cut in the middle until it fits a width.

ttk cuts a Treeview cell at its right edge with no ellipsis; the round-2 real-click test
(2026-10-21) showed "Interview with the head of the re" in the Queue, end and extension gone.
Windowless: the width test is a plain predicate here (tests/app/test_queue_long_name.py measures
with a real font).
"""
from __future__ import annotations

import pytest

from app.widgets.tabs import elide_middle, elide_to_width

LONG = ("Interview with the head of the regional teachers association about the new "
        "school year (full recording, part 1 of 3).mp4")


def _fits(limit: int):
    return lambda text: len(text) <= limit


def test_a_name_that_fits_is_unchanged():
    assert elide_to_width("talk.mp3", _fits(40)) == "talk.mp3"


def test_a_long_name_keeps_its_start_and_its_end():
    shown = elide_to_width(LONG, _fits(34))
    assert len(shown) == 34
    assert shown.startswith("Interview with") and shown.endswith(").mp4") and "…" in shown


def test_the_longest_cut_that_fits_is_chosen():
    shown = elide_to_width(LONG, _fits(50))
    assert shown == elide_middle(LONG, 50)


def test_a_width_too_small_for_any_cut_gives_the_shortest_cut():
    assert elide_to_width(LONG, lambda _t: False) == elide_middle(LONG, 12)


def test_the_result_fits_and_keeps_the_end():
    pytest.importorskip("hypothesis")  # the property tests skip themselves without it (AGENTS.md)
    from hypothesis import given, strategies as st

    @given(st.text(st.characters(blacklist_characters="…"), min_size=1, max_size=200),
           st.integers(min_value=12, max_value=220))
    def check(name, limit):
        shown = elide_to_width(name, _fits(limit))
        if len(name) <= limit:
            assert shown == name
        else:
            assert len(shown) <= limit and "…" in shown
            head, _, tail = shown.partition("…")
            assert name.startswith(head) and name.endswith(tail)

    check()


def test_the_end_of_a_name_gets_half_of_the_room():
    # "part 1 of 3" told the parts of a recording apart; a third of the room cut it to "of 3).mp4"
    # in the Queue (round-3 screenshot critique, Gemini Argon, 2026-10-21).
    shown = elide_middle(LONG, 30)
    head, _, tail = shown.partition("…")
    assert len(tail) == 15 and tail == LONG[-15:] and len(head) == 14
    assert elide_to_width(LONG, _fits(30)).endswith("t 1 of 3).mp4")
