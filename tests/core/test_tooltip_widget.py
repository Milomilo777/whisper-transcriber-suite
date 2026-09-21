"""Regression tests for ``app/widgets/tooltip.py``'s popup lifecycle.

Pins the two edge cases the shared hover-help helper must survive:
a widget destroyed while its tooltip is showing (no dangling Toplevel),
and a tooltip near the bottom-right screen edge (flipped back on-screen).
"""
from __future__ import annotations

import re
import time

import pytest

tk = pytest.importorskip("tkinter")

from app.widgets.tooltip import bind_tooltip  # noqa: E402


def _pump_until(root: tk.Tk, predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _tips(widget: tk.Misc) -> list[tk.Toplevel]:
    return [w for w in widget.winfo_children() if isinstance(w, tk.Toplevel)]


def test_widget_destroyed_while_tooltip_showing_leaves_nothing_behind():
    root = tk.Tk()
    root.geometry("300x200+60+60")
    root.deiconify()
    try:
        root.update()
        lbl = tk.Label(root, text="hover")
        lbl.place(x=10, y=10)
        root.update()

        bind_tooltip(lbl, "help text", delay_ms=1)
        lbl.event_generate("<Enter>", x=1, y=1, when="now")
        assert _pump_until(root, lambda: bool(_tips(lbl)))
        tip = _tips(lbl)[0]

        # Destroy the widget while its popup is up: the <Destroy> binding
        # must take the Toplevel with it, not leave it floating.
        lbl.destroy()
        root.update()
        assert not tip.winfo_exists()
    finally:
        root.destroy()


def test_tooltip_is_flipped_on_screen_at_the_bottom_right_edge(monkeypatch):
    root = tk.Tk()
    root.geometry("300x200+10+10")
    root.deiconify()
    try:
        root.update()
        lbl = tk.Label(root, text="corner")
        lbl.place(relx=1.0, rely=1.0, anchor="se")
        root.update()

        # winfo_screenwidth/height describe the PRIMARY display; fake a
        # small one so a bottom-right widget needs both clamps.
        monkeypatch.setattr(tk.Misc, "winfo_screenwidth", lambda self: 320)
        monkeypatch.setattr(tk.Misc, "winfo_screenheight", lambda self: 240)

        bind_tooltip(lbl, "corner tip", delay_ms=1)
        lbl.event_generate("<Enter>", x=1, y=1, when="now")
        assert _pump_until(root, lambda: bool(_tips(lbl)))
        tip = _tips(lbl)[0]

        parsed = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", tip.wm_geometry())
        assert parsed is not None, f"unexpected geometry {tip.wm_geometry()!r}"
        width, height, x, y = (int(g) for g in parsed.groups())
        assert x >= 0 and y >= 0
        assert x + width <= 320 and y + height <= 240
    finally:
        root.destroy()
