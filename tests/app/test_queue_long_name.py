"""The Queue's File cell: a long name is cut in the middle to the column width, with an ellipsis.

ttk cuts a cell at its right edge with no ellipsis; the round-2 real-click test (2026-10-21)
showed "Interview with the head of the re" with the end and the extension gone. Needs Tk.
"""
from __future__ import annotations

import os
import tkinter as tk
import types
from tkinter import font as tkfont
from tkinter import ttk

import pytest

import app.app as appmod
from app.domain.tasks import TranscriptionTask
from app.widgets.tabs import fit_tree_cell

LONG = ("Interview with the head of the regional teachers association about the new "
        "school year (full recording, part 1 of 3).mp4")


@pytest.fixture
def tree():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    t = ttk.Treeview(root, columns=("file", "status"), show="headings")
    t.column("file", width=220)
    yield t
    root.destroy()


def _width(t: ttk.Treeview, text: str) -> int:
    spec = str(ttk.Style(t).lookup("Treeview", "font")) or "TkDefaultFont"
    return tkfont.Font(root=t, font=spec).measure(text)


def test_a_long_name_fits_the_column_and_keeps_its_extension(tree):
    shown = fit_tree_cell(tree, "file", LONG)
    assert "…" in shown and shown.endswith(").mp4") and shown.startswith("Interview")
    assert _width(tree, shown) <= 220


def test_a_short_name_is_unchanged(tree):
    assert fit_tree_cell(tree, "file", "talk.mp3") == "talk.mp3"


def test_a_wider_column_shows_more_of_the_name(tree):
    narrow = fit_tree_cell(tree, "file", LONG)
    tree.column("file", width=420)
    assert len(fit_tree_cell(tree, "file", LONG)) > len(narrow)


def test_a_tree_without_columns_gets_the_name_back():
    assert fit_tree_cell(types.SimpleNamespace(), "file", LONG) == LONG


def test_the_queue_row_shows_the_cut_name_and_the_task_keeps_its_path(tree):
    path = os.path.join("media", LONG)
    task = TranscriptionTask(path)
    app = types.SimpleNamespace(
        tree=tree, row_map={}, queue=[task],
        _row_progress_text=lambda *_a: "", fmt_time=lambda _t: "",
        _refresh_window_title=lambda: None, _ensure_animation=lambda: None,
        _selected_tasks=lambda: [], _update_queue_action_bar=lambda: None,
        _auto_select_running_row=lambda: None,
    )
    appmod.App.refresh(app)  # type: ignore[arg-type]
    (iid,) = tree.get_children()
    shown = tree.item(iid, "values")[0]
    assert "…" in shown and shown.endswith(").mp4")
    assert app.row_map[iid] is task and task.file_path == path
