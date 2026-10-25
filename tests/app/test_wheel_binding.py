"""The wheel binding must survive the pointer crossing into child widgets.

``<Leave>`` fires on a widget with detail=Inferior when the pointer moves
onto one of its OWN children (and plainly fires between siblings inside
the subtree); a leave handler that unconditionally ``unbind_all`` kills
the wheel exactly over the content — the place the pointer usually is.
``app/widgets/notice.py`` solves the same crossing for hover with a
``winfo_containing`` guard; the scrollable panels need it too.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets import smtv_tab as st



@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def _wired(root, monkeypatch, under):
    """A canvas+inner pair with the wheel bound, pointer faked to *under*."""
    canvas = tk.Canvas(root, width=200, height=100)
    inner = ttk.Frame(canvas)
    lbl = ttk.Label(inner, text="card")
    inner.pack()
    lbl.pack()
    canvas.pack()
    root.update_idletasks()
    root.update()
    monkeypatch.setattr(
        tk.Misc, "winfo_pointerxy", lambda self, _c=canvas: (_c.winfo_rootx() + 5,
                                                             _c.winfo_rooty() + 5),
    )
    monkeypatch.setattr(tk.Misc, "winfo_containing", lambda self, x, y, _u=under: _u)
    st._bind_wheel(canvas, inner)
    canvas.event_generate("<Enter>")
    root.update()
    assert canvas.bind_all("<MouseWheel>")  # sanity: the wheel is bound on entry
    return canvas, inner, lbl


def test_leave_into_a_child_keeps_the_wheel(root, monkeypatch):
    canvas, inner, lbl = _wired(root, monkeypatch, under=None)
    # The pointer sits over the card label (a child of inner, child of
    # canvas): Tk fires <Leave> on both anchors, but the wheel must stay.
    monkeypatch.setattr(tk.Misc, "winfo_containing", lambda self, x, y, _u=lbl: _u)
    canvas.event_generate("<Leave>")
    root.update()
    inner.event_generate("<Leave>")
    root.update()
    assert canvas.bind_all("<MouseWheel>"), "wheel died while the pointer is inside the panel"
    assert canvas.bind_all("<Button-4>")


def test_leaving_the_panel_releases_the_wheel(root, monkeypatch):
    canvas, inner, lbl = _wired(root, monkeypatch, under=None)
    # Pointer over something outside the canvas subtree.
    other = tk.Label(root, text="elsewhere")
    other.pack()
    monkeypatch.setattr(tk.Misc, "winfo_containing", lambda self, x, y, _u=other: _u)
    canvas.event_generate("<Leave>")
    root.update()
    assert not canvas.bind_all("<MouseWheel>")
    assert not canvas.bind_all("<Button-5>")
    other.destroy()
