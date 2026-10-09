"""The Work-offline status bar leaves no pending timer when its window is destroyed."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets import offline_status as status
from core import offline


def _pending(root: tk.Tk) -> list[str]:
    ids = root.tk.splitlist(root.tk.call("after", "info"))
    return [str(root.tk.call("after", "info", i)) for i in ids]


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display")
    r.withdraw()
    try:
        yield r
    finally:
        try:
            r.destroy()
        except tk.TclError:
            pass


def _ok() -> offline.ConnectionCheck:
    return offline.ConnectionCheck(0.0, True)


def test_destroying_the_bar_cancels_its_tick(root: tk.Tk) -> None:
    holder = ttk.Frame(root)
    holder.pack()
    bar = status.OfflineStatusBar(holder, post_to_main=lambda fn: fn(), poll=_ok)
    sibling = ttk.Frame(holder)
    sibling.pack()
    bar.show(before=sibling)
    assert any("tick" in s for s in _pending(root)), "control: a tick is pending"
    holder.destroy()
    assert not any("tick" in s for s in _pending(root))


def test_a_destroyed_bar_does_not_start_polling_again(root: tk.Tk) -> None:
    bar = status.OfflineStatusBar(root, post_to_main=lambda fn: fn(), poll=_ok)
    bar.destroy()
    bar.tick()
    assert not any("tick" in s for s in _pending(root))
