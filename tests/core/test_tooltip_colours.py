"""Hover texts follow the theme: the pale yellow box glared on the dark panels
(click-through test, 2026-10-21). Windowless."""
from __future__ import annotations

import inspect

from app.theme import tokens
from app.widgets import tooltip


def _luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_each_theme_has_its_own_readable_pair():
    light, dark = tokens.tooltip_colours("light"), tokens.tooltip_colours("dark")
    assert light == (tokens.TOOLTIP_BG, tokens.TOOLTIP_FG)
    assert dark != light
    for bg, fg in (light, dark):
        assert _contrast(bg, fg) >= 7.0
    # the dark box sits on a dark panel instead of glaring on it
    assert _luminance(dark[0]) < 0.1


def test_the_tooltip_reads_the_pair_when_it_opens():
    assert "tokens.tooltip_colours()" in inspect.getsource(tooltip)  # read when a tip opens
