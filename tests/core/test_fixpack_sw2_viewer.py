"""Regression: the transcript viewer must not crash when a loaded
list-of-dicts JSON carries NON-NUMERIC ``start`` / ``end`` values.

After the round-1 fix, ``_load_segments`` accepts a list of dicts. But
the synchronous init path (``_populate_listbox``) then read each
segment's ``start`` with a bare ``float(seg.get("start", 0.0))``. A
hand-edited / locale-formatted transcript whose ``start`` is a European
decimal string (``"1,5"``) or a stray ``"abc"`` makes that ``float()``
raise ``ValueError`` *during construction*, taking down the whole viewer
window and bypassing the friendly "pick the .json" guard.

These tests exercise the pure parse seam without a Tk root, a media
file, VLC, or a network: ``_seg_float`` directly, and ``_populate_listbox``
driven against a class instance built with ``TranscriptViewer.__new__``
plus stubbed Tk attributes (the tree + the search var). On the pre-fix
code the ``_populate_listbox`` test raises ``ValueError`` and fails.
"""
from __future__ import annotations

import pytest


def test_seg_float_coerces_non_numeric_and_none_to_default():
    from app.dialogs.transcript_viewer import _seg_float

    # European decimal string — a common hand-edit / locale artefact.
    assert _seg_float({"start": "1,5"}, "start") == 0.0
    # Pure garbage string.
    assert _seg_float({"start": "abc"}, "start") == 0.0
    # None value.
    assert _seg_float({"end": None}, "end") == 0.0
    # Missing key falls back to the default.
    assert _seg_float({}, "start") == 0.0
    assert _seg_float({}, "start", 4.0) == 4.0
    # Legitimate numeric values still pass through unchanged.
    assert _seg_float({"start": 2.5}, "start") == 2.5
    assert _seg_float({"start": "3.0"}, "start") == 3.0
    assert _seg_float({"start": 7}, "start") == 7.0


def test_seg_float_rejects_non_finite_values():
    """``float("nan")`` / ``float("inf")`` parse successfully, so they
    used to pass through — then ``_fmt_hms`` raised ValueError
    (``int(nan)``) / OverflowError (``int(inf)``) during construction.
    They must coerce to the default like any other junk value."""
    from app.dialogs.transcript_viewer import _seg_float

    for bad in (float("nan"), float("inf"), float("-inf"), "nan", "inf", "-inf", "1e400"):
        assert _seg_float({"start": bad}, "start") == 0.0, bad
        assert _seg_float({"start": bad}, "start", 9.0) == 9.0, bad


class _StubTree:
    """Minimal stand-in for the ttk.Treeview the init path touches."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def get_children(self):
        return tuple(r["iid"] for r in self.rows)

    def delete(self, *_iids) -> None:
        self.rows = []

    def insert(self, _parent, _index, iid, values, tags) -> None:
        self.rows.append({"iid": iid, "values": values, "tags": tags})


class _StubVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _make_viewer(segments):
    """Build a TranscriptViewer instance WITHOUT running __init__ (no Tk
    root / no VLC), wired with just the attributes ``_populate_listbox``
    reads. This is the pure parse seam for an app/dialogs Tk class."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    v = TranscriptViewer.__new__(TranscriptViewer)
    v.segments = segments  # type: ignore[attr-defined]
    v.filtered_indices = []  # type: ignore[attr-defined]
    v._active_segment_idx = None  # type: ignore[attr-defined]
    v.search_var = _StubVar("")  # type: ignore[attr-defined]
    v.tree = _StubTree()  # type: ignore[attr-defined]
    return v


def test_populate_listbox_survives_non_numeric_timestamps():
    """A list-of-dicts whose start/end are non-numeric strings must
    populate without raising; the offending timestamps coerce to
    00:00:00 rather than crashing the viewer."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segments = [
        {"start": "1,5", "end": "3,0", "text": "european decimal", "speaker": "A"},
        {"start": "abc", "end": "xyz", "text": "pure garbage", "speaker": "B"},
        {"start": None, "end": None, "text": "null timestamps"},
        {"start": 4.0, "end": 5.0, "text": "legit numeric"},
    ]
    viewer = _make_viewer(segments)

    # On the pre-fix code this raises ValueError: could not convert
    # string to float: '1,5'.
    TranscriptViewer._populate_listbox(viewer)

    rows = viewer.tree.rows  # type: ignore[attr-defined]
    assert len(rows) == 4
    # Non-numeric start coerces to 0.0 -> "00:00:00".
    assert rows[0]["values"][0] == "00:00:00"
    assert rows[1]["values"][0] == "00:00:00"
    assert rows[2]["values"][0] == "00:00:00"
    # The legitimate numeric start is preserved.
    assert rows[3]["values"][0] == "00:00:04"
    # The text/speaker columns are untouched by the timestamp coercion.
    assert rows[0]["values"][2] == "european decimal"
    assert rows[0]["values"][1] == "A"


def test_populate_listbox_survives_non_finite_timestamps():
    """A segment whose start is NaN / end is Infinity (bare literals
    Python's ``json`` accepts) must render as 00:00:00 instead of
    raising ValueError / OverflowError out of the synchronous init
    path. Pre-fix this raised during construction."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segments = [
        {"start": float("nan"), "end": 1.0, "text": "nan start"},
        {"start": 0.0, "end": float("inf"), "text": "inf end"},
        {"start": 2.0, "end": 3.0, "text": "legit"},
    ]
    viewer = _make_viewer(segments)

    TranscriptViewer._populate_listbox(viewer)

    rows = viewer.tree.rows  # type: ignore[attr-defined]
    assert len(rows) == 3
    assert rows[0]["values"][0] == "00:00:00"
    assert rows[1]["values"][0] == "00:00:00"
    assert rows[2]["values"][0] == "00:00:02"
    assert rows[0]["values"][2] == "nan start"
    assert rows[1]["values"][2] == "inf end"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
