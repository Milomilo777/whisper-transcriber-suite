"""A path the app puts in the File or video link box shows its end (name and extension).

An Entry shows the start of its text, so a long path showed "C:/Users/.../Interview with the
head of the regional teachers association about the new school year and the chang" with the
name's end and extension out of sight (round-2 screenshot critics, 2026-10-21). Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
import types
from tkinter import ttk

import pytest

from app.app import _show_file_in_box

LONG = ("C:/Users/Owner/media/Interview with the head of the regional teachers association "
        "about the new school year and the changes (part 1 of 3).mp4")


@pytest.fixture
def box():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    root.geometry("400x60")
    var = tk.StringVar(master=root)
    entry = ttk.Entry(root, textvariable=var)
    entry.pack(fill="x")
    root.update()
    yield types.SimpleNamespace(fv=var, file_entry=entry, root=root)
    root.destroy()


def test_a_long_path_shows_its_end(box):
    _show_file_in_box(box, LONG)
    box.root.update()
    first, last = box.file_entry.xview()
    assert box.fv.get() == LONG
    assert last == 1.0 and first > 0.0
    assert box.file_entry.index("insert") == len(LONG)


def test_a_double_without_the_box_still_gets_the_path():
    fake = types.SimpleNamespace(fv=types.SimpleNamespace(value="", set=None))
    seen: list[str] = []
    fake.fv.set = seen.append
    _show_file_in_box(fake, LONG)
    assert seen == [LONG]


def test_a_path_set_while_its_tab_is_hidden_shows_its_end_once_shown():
    # A drop or a Recent file from another tab (code review of 284745d9, 2026-10-21).
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    try:
        root.geometry("500x150")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        tab1, tab2 = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(tab1, text="1")
        nb.add(tab2, text="2")
        var = tk.StringVar(master=root)
        entry = ttk.Entry(tab1, textvariable=var)
        entry.pack(fill="x", padx=10, pady=10)
        root.update()
        nb.select(tab2)
        root.update()
        box = types.SimpleNamespace(fv=var, file_entry=entry)
        nb.select(tab1)
        _show_file_in_box(box, LONG)
        root.update()
        first, last = entry.xview()
        assert last == 1.0 and first > 0.0
    finally:
        root.destroy()
