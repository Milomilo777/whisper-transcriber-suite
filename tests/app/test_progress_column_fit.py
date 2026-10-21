"""A Treeview progress column shows a full "100%" cell, also after the row font changes.

A fixed 150 px column cut "100%" to "10(" on Windows 10, where the block glyphs come
from a wider fallback font (screenshot review, 2026-10-21). Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import pytest

from app.widgets.tabs import fit_progress_column, progress_cell


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # no display
        pytest.skip(f"Tk unavailable: {exc}")
    r.withdraw()
    yield r
    r.destroy()


def _needed(root: tk.Misc, font: str) -> int:
    return tkfont.Font(root=root, font=font).measure(progress_cell(100))


def test_the_column_fits_the_widest_cell(root):
    style = ttk.Style(root)
    style.configure("Fit.Treeview", font=("Segoe UI", 11))
    tree = ttk.Treeview(root, columns=("file", "progress"), show="headings", style="Fit.Treeview")
    fit_progress_column(tree)
    needed = _needed(root, "{Segoe UI} 11")
    assert int(tree.column("progress", "width")) > needed
    # ttk's default width (200) can be wide enough on its own; the minimum width (20) is not.
    assert int(tree.column("progress", "minwidth")) > needed


def test_the_column_grows_when_the_row_font_grows(root):
    style = ttk.Style(root)
    style.configure("Grow.Treeview", font=("Segoe UI", 9))
    tree = ttk.Treeview(root, columns=("file", "progress"), show="headings", style="Grow.Treeview")
    tree.pack()
    fit_progress_column(tree)
    style.configure("Grow.Treeview", font=("Segoe UI", 30))  # sends <<ThemeChanged>>
    for _ in range(5):
        root.update()
    assert int(tree.column("progress", "width")) > _needed(root, "{Segoe UI} 30")
