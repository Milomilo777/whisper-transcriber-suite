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

from app.app import App

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
    App._show_file(box, LONG)  # type: ignore[arg-type]
    box.root.update()
    first, last = box.file_entry.xview()
    assert box.fv.get() == LONG
    assert last == 1.0 and first > 0.0
    assert box.file_entry.index("insert") == len(LONG)


def test_a_double_without_the_box_still_gets_the_path():
    fake = types.SimpleNamespace(fv=types.SimpleNamespace(value="", set=None))
    seen: list[str] = []
    fake.fv.set = seen.append
    App._show_file(fake, LONG)  # type: ignore[arg-type]
    assert seen == [LONG]
