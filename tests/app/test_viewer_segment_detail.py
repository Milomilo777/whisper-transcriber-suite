"""Transcript viewer: a segment longer than its list column stays readable.

A Treeview row is one line and cannot wrap, so the full text of the selected
segment is also shown, wrapped, in a read-only box under the list.
"""
from __future__ import annotations

import json

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402

LONG = " ".join(f"word{i}" for i in range(80))  # far wider than the column
RTL = "این یک جمله\u200cی بسیار طولانی فارسی است " * 6


@pytest.fixture
def viewer(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    segs = [
        {"start": 0.0, "end": 2.0, "text": "Short"},
        {"start": 2.0, "end": 9.0, "text": LONG},
        {"start": 9.0, "end": 12.0, "text": RTL.strip()},
    ]
    p = tmp_path / "t.json"
    p.write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
    v = tv.TranscriptViewer(root, str(p))
    v.withdraw()
    yield v
    v._dirty = False
    v._on_close()
    root.destroy()


def _select(v, iid: str) -> None:
    v.tree.selection_set(iid)
    v.tree.focus(iid)
    v._on_segment_select(None)  # type: ignore[arg-type]


def _shown(v) -> str:
    return v._segment_detail.get("1.0", "end-1c")


def test_detail_box_wraps_and_is_read_only(viewer) -> None:
    assert str(viewer._segment_detail.cget("wrap")) == "word"
    assert str(viewer._segment_detail.cget("state")) == "disabled"
    assert _shown(viewer) == ""


def test_selecting_a_long_segment_shows_all_of_it(viewer) -> None:
    _select(viewer, "1")
    assert _shown(viewer) == LONG
    _select(viewer, "2")
    assert _shown(viewer) == RTL.strip()
    _select(viewer, "0")
    assert _shown(viewer) == "Short"


def test_detail_box_empties_when_the_selected_row_is_filtered_out(viewer) -> None:
    _select(viewer, "1")
    viewer.search_var.set("Short")
    viewer._refilter()
    assert _shown(viewer) == ""
