"""Tall tabs scroll on small screens instead of being cut off; on a big
window they still fill it (app.widgets.tabs.fit_or_scroll)."""
from __future__ import annotations

import time

import pytest


def _pump(root, sec=0.6):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.02)


@pytest.fixture
def root():
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk unavailable: {e}")
    yield r
    r.destroy()


def _page(root, height):
    from tkinter import ttk

    from app.widgets.tabs import fit_or_scroll

    root.geometry(f"400x{height}")
    page = ttk.Frame(root)
    page.pack(fill="both", expand=True)
    inner = fit_or_scroll(page)
    for i in range(12):
        ttk.Label(inner, text=f"row {i}").pack(anchor="w", pady=8)
    _pump(root)
    canvas = next(c for c in page.winfo_children() if c.winfo_class() == "Canvas")
    return page, inner, canvas


def test_short_window_gets_a_scrollbar_and_the_wheel_scrolls(root):
    _page_, inner, canvas = _page(root, 200)
    assert canvas.yview()[1] < 1.0  # content overflows -> scrollable
    label = inner.winfo_children()[3]
    label.event_generate("<Button-5>")
    _pump(root, 0.2)
    assert canvas.yview()[0] > 0.0


def test_tall_window_is_filled_and_does_not_scroll(root):
    _page_, inner, canvas = _page(root, 900)
    assert canvas.yview() == (0.0, 1.0)
    assert inner.winfo_height() >= canvas.winfo_height() - 1  # fills the page


@pytest.mark.parametrize("screen, expected", [
    ((1366, 768), "1320x678+23+30"),    # laptop: fits with a margin
    ((1920, 1080), "1320x900+300+60"),  # desktop: the layout's full size
    ((1024, 700), "984x640+20+20"),     # tiny: never below the 960x640 floor
])
def test_first_run_window_fits_the_screen(monkeypatch, screen, expected):
    import types

    from app.app import App

    monkeypatch.setattr("app.app.sys.platform", "linux")  # no Windows maximise here
    calls: list = []
    fake = types.SimpleNamespace(
        winfo_screenwidth=lambda: screen[0],
        winfo_screenheight=lambda: screen[1],
        geometry=lambda g=None: calls.append(g),
        state=lambda s: calls.append(("state", s)),
    )
    App._apply_default_geometry(fake)  # type: ignore[arg-type]
    assert calls == [expected]


def test_small_windows_screen_is_maximised(monkeypatch):
    import types

    from app.app import App

    monkeypatch.setattr("app.app.sys.platform", "win32")
    calls: list = []
    fake = types.SimpleNamespace(
        winfo_screenwidth=lambda: 1366, winfo_screenheight=lambda: 768,
        geometry=lambda g=None: calls.append(g),
        state=lambda s: calls.append(("state", s)),
    )
    App._apply_default_geometry(fake)  # type: ignore[arg-type]
    assert calls[-1] == ("state", "zoomed")
