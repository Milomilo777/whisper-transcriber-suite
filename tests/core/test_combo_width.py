"""The Engine and Model lists are as wide as their longest entry, within limits.

A fixed width of 44 cut "Google Cloud Speech-to-Text ... ⚠ unavailable" to "⚠ u"
(click-through test, 2026-10-21). Windowless.
"""
from __future__ import annotations

import inspect

from app.widgets import tabs
from app.widgets.tabs import combo_width


def test_short_lists_keep_the_old_width():
    assert combo_width(["Small", "Large v3"]) == 44
    assert combo_width([]) == 44


def test_a_long_entry_widens_the_box_up_to_the_cap():
    assert combo_width(["x" * 60]) == 62
    assert combo_width(["x" * 200]) == 72


def test_the_engine_and_model_lists_use_it():
    src = inspect.getsource(tabs.build_transcribe_tab)
    assert "width=combo_width([opt.display_label for opt in _engine_options])" in src
    assert "width=combo_width([lbl for _slug, lbl in _model_labeled])" in src


def test_once_per_drops_a_held_or_double_enter():
    """Keyboard auto-repeat must not queue the same file twice (review, 2026-10-21)."""
    from app.widgets.tabs import once_per

    t = [0.0]
    runs: list[float] = []
    handler = once_per(1.5, lambda: runs.append(t[0]), clock=lambda: t[0])
    for t[0] in (10.0, 10.03, 10.06, 11.0):  # a held key, then a second tap inside 1.5 s
        handler(object())
    t[0] = 12.0
    handler(object())
    assert runs == [10.0, 12.0]
