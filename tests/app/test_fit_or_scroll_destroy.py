"""A page built with ``fit_or_scroll`` leaves no timer behind when it is destroyed.

Its 400 ms layout poll and (macOS) its repaint-on-show idle call are registered on the canvas.
Destroying the page deletes the Tcl commands they point at, so a still-pending call later fails
with ``invalid command name "..._poll"``; on Tk 8.6.16 / macOS the next root's ``update()`` then
hung. The calls must be cancelled when the canvas is destroyed.
"""
from __future__ import annotations

import time
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


def _pending_scripts(root: tk.Tk) -> list[str]:
    ids = root.tk.splitlist(root.tk.call("after", "info"))
    return [str(root.tk.call("after", "info", i)) for i in ids]


def _pump(root: tk.Tk, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def _build(root: tk.Tk) -> ttk.Frame:
    page = ttk.Frame(root)
    page.pack(fill="both", expand=True)
    ttk.Label(tabs.fit_or_scroll(page), text="content").pack()
    return page


def test_destroying_the_page_cancels_the_pending_poll(root: tk.Tk) -> None:
    page = _build(root)
    _pump(root, 0.15)  # the poll has run and re-armed itself
    assert any("_fit_or_scroll_timer" in s for s in _pending_scripts(root)), "control: a poll is pending"
    page.destroy()
    assert not any("_fit_or_scroll_timer" in s for s in _pending_scripts(root))


def test_destroying_the_toplevel_cancels_the_pending_poll(root: tk.Tk) -> None:
    # A Toplevel under a root that stays alive: destroying a Tk ROOT would pass on its own,
    # because the conftest net cancels every pending after() of a destroyed root. Here only
    # the canvas's own <Destroy> binding can cancel the poll.
    top = tk.Toplevel(root)
    _build(top)  # type: ignore[arg-type]
    _pump(root, 0.15)
    assert any("_fit_or_scroll_timer" in s for s in _pending_scripts(root)), "control: a poll is pending"
    top.destroy()
    # The root outlives the window: no script may still call a deleted command.
    assert not any("_fit_or_scroll_timer" in s for s in _pending_scripts(root))


def test_destroying_the_page_cancels_the_macos_repaint_on_show(
    root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tabs, "sys", SimpleNamespace(platform="darwin"))
    page = _build(root)
    page.event_generate("<Map>")
    # event_generate delivers at once; the idle repaint is queued and has not run yet.
    assert any("_fit_or_scroll_timer" in s for s in _pending_scripts(root)), "control: the idle repaint is pending"
    page.destroy()
    assert not any("_fit_or_scroll_timer" in s for s in _pending_scripts(root))

