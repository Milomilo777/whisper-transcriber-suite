"""tests/app/i18n_walk.is_pseudo_marked: the check every pseudo-locale test relies on.

Windowless: it only reads strings (no Tk root is created).
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from app import i18n
from app.shortcuts import accel_text
from tests.app.i18n_walk import is_pseudo_marked, unmarked_rest

P = i18n.pseudo_translate
CMD = chr(0x2318)


@pytest.fixture(autouse=True)
def _english() -> Iterator[None]:
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def _in_pseudo(msgid: str, **kwargs: str) -> str:
    i18n.set_language(i18n.PSEUDO_LOCALE)
    try:
        return i18n._(msgid, **kwargs)
    finally:
        i18n.set_language("en")


def test_flat_segments() -> None:
    assert is_pseudo_marked(P("Save all"))
    assert is_pseudo_marked(P("A") + " — " + P("B"))
    assert is_pseudo_marked("0 / 2000")  # no letters at all
    assert is_pseudo_marked(P("Line one\nline two"))  # a segment spans lines


def test_plain_text_is_reported() -> None:
    assert not is_pseudo_marked("Save all")
    assert not is_pseudo_marked("Sent with: " + P("x"))
    assert not is_pseudo_marked("[Save]")  # brackets alone are not the marker
    assert not is_pseudo_marked("Save ~]")  # an end with no start
    assert not is_pseudo_marked("[Save ~")  # a start with no end
    assert not is_pseudo_marked("[Save~]")  # the marker has a space before the tildes
    assert not is_pseudo_marked("[Plain " + P("B"))  # an unclosed bracket before a segment


def test_nested_segments_are_marked() -> None:
    inner = _in_pseudo("the CPU")
    outer = _in_pseudo("Runs on {cpu}. It is fine.", cpu=inner)
    # The inner segment ends before the outer sentence does: letters follow it.
    assert outer.index(inner) + len(inner) < len(outer) - 5
    assert is_pseudo_marked(outer)
    two_deep = _in_pseudo("Recommended: {entry}", entry=_in_pseudo(
        "{language} (automatic)", language=_in_pseudo("German")))
    assert is_pseudo_marked(two_deep)


def test_plain_word_next_to_a_marked_segment_is_reported() -> None:
    # Negative controls: the nested rule must not swallow English beside a segment.
    assert not is_pseudo_marked("Runs on " + P("the CPU"))
    assert not is_pseudo_marked(P("Runs on") + " the CPU")
    assert not is_pseudo_marked(P("A") + " and " + P("B"))
    nested = _in_pseudo("Runs on {cpu}.", cpu=P("the CPU"))
    assert not is_pseudo_marked(nested + " Plain")
    assert not is_pseudo_marked("Plain " + nested)
    assert unmarked_rest("Runs on " + P("the CPU")) == "Runs on "


def test_placeholder_values_with_brackets_stay_inside_their_segment() -> None:
    assert is_pseudo_marked(_in_pseudo("Saved {name}", name="clip [1080p] final.mp4"))
    assert is_pseudo_marked(_in_pseudo("Saved {name}", name="[a] [b]"))
    # An unbalanced bracket in a value is reported (a false alarm is safer than a miss).
    assert not is_pseudo_marked(_in_pseudo("Saved {name}", name="a] b"))


def test_trailing_menu_shortcut_is_not_interface_text() -> None:
    for shortcut in ("Ctrl+O", "Ctrl+Enter", "Cmd+O", CMD + "O", accel_text("q")):
        assert is_pseudo_marked(P("Open...") + "    " + shortcut), shortcut
        assert is_pseudo_marked(P("Open...") + shortcut), shortcut  # no gap
        assert not is_pseudo_marked("Open...    " + shortcut), shortcut
    # Only one shortcut, only at the end.
    assert not is_pseudo_marked("Ctrl+O " + P("Open..."))
    assert not is_pseudo_marked(P("Open...") + " Ctrl+O Ctrl+P")
    assert not is_pseudo_marked(P("Open...") + " Control+O")
