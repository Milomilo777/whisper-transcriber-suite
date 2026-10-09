"""A tab page built with ``fit_or_scroll`` repaints after its tab is shown again, on macOS only.

On aqua, a canvas whose content is an embedded window draws blank after the notebook hid and
re-showed its tab (all five scrolling tabs, found in the macOS 13 VM). Re-setting options,
``update()`` and re-gridding do not repaint it; moving the embedded window by one pixel and
back does. ``fit_or_scroll`` therefore does that once on the page's ``<Map>``, only on macOS:
Windows and Linux bind nothing and are unchanged. The repaint runs per tab switch, never on a
timer, so an idle window stays idle (see ``test_idle_redraw``).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from app.widgets import tabs


@pytest.fixture
def root() -> Any:
    r = tk.Tk()
    r.withdraw()
    try:
        yield r
    finally:
        r.destroy()


def _build(root: tk.Tk, platform: str, monkeypatch: pytest.MonkeyPatch) -> tuple[ttk.Frame, tk.Canvas]:
    monkeypatch.setattr(tabs, "sys", SimpleNamespace(platform=platform))
    page = ttk.Frame(root)
    page.pack(fill="both", expand=True)
    inner = tabs.fit_or_scroll(page)
    ttk.Label(inner, text="content").pack()
    canvas = inner.master
    assert isinstance(canvas, tk.Canvas)
    return page, canvas


def _record_coords(canvas: tk.Canvas, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    seen: list[tuple[Any, ...]] = []
    orig = canvas.coords

    def coords(*args: Any) -> Any:
        if len(args) > 1:
            seen.append(args[1:])
        return orig(*args)

    monkeypatch.setattr(canvas, "coords", coords)
    return seen


def test_redraw_moves_the_embedded_window_one_pixel_and_puts_it_back(
    root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    canvas = tk.Canvas(root)
    window = canvas.create_window((0, 0), window=ttk.Frame(canvas), anchor="nw")
    seen = _record_coords(canvas, monkeypatch)

    tabs._redraw_embedded_window(canvas, window)

    assert seen == [(0.0, 1.0), (0.0, 0.0)]
    assert [float(v) for v in canvas.coords(window)] == [0.0, 0.0]


def test_redraw_survives_a_destroyed_canvas(root: tk.Tk) -> None:
    canvas = tk.Canvas(root)
    window = canvas.create_window((0, 0), window=ttk.Frame(canvas))
    canvas.destroy()

    tabs._redraw_embedded_window(canvas, window)  # must not raise


def test_page_map_repaints_once_on_macos(root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    page, canvas = _build(root, "darwin", monkeypatch)
    assert page.bind("<Map>")
    seen = _record_coords(canvas, monkeypatch)

    page.event_generate("<Map>")
    root.update()

    assert seen == [(0.0, 1.0), (0.0, 0.0)]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_windows_and_linux_bind_nothing_and_never_move_the_window(
    root: tk.Tk, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    page, canvas = _build(root, platform, monkeypatch)
    assert page.bind("<Map>") == ""
    seen = _record_coords(canvas, monkeypatch)

    page.event_generate("<Map>")
    root.update()

    assert seen == []


def test_the_repaint_is_not_repeated_without_another_map(
    root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, canvas = _build(root, "darwin", monkeypatch)
    page.event_generate("<Map>")
    root.update()
    seen = _record_coords(canvas, monkeypatch)

    root.update()
    root.after(600, root.quit)
    root.mainloop()  # long enough for the 400 ms layout poll to run once or twice

    assert seen == []
