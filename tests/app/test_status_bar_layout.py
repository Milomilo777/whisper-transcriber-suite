"""The Work offline status line keeps its Network log button fully visible at a narrow width."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets.offline_status import OfflineStatusBar
from core import offline


def _poll() -> offline.ConnectionCheck:
    return offline.ConnectionCheck(0.0, True)


@pytest.fixture
def root():
    try:
        win = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless box
        pytest.skip("no display")
    win.geometry("400x120+40+40")
    yield win
    win.destroy()


def test_long_text_is_cut_not_the_button(root: tk.Tk) -> None:
    bar = OfflineStatusBar(root, post_to_main=lambda fn: fn(), poll=_poll)
    bar.pack(side="bottom", fill="x")
    bar.text_var.set("Work offline: " + "very long status text " * 20)
    root.update()
    button = next(w for w in bar.winfo_children()[1].winfo_children() if isinstance(w, ttk.Button))
    assert button.winfo_width() >= button.winfo_reqwidth() > 1
    assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    bar.hide()
