"""An idle window must not be repainted: ``App.refresh()`` writes nothing that has not changed.

``App.loop()`` runs ``refresh()`` every 500 ms. The empty-state headline used to be written
into its ``StringVar`` on every round even when the text was the same. A variable write fires
the label's trace and redraws it, and on macOS (aqua) that kept the whole window busy: an
idle app used about 38% of a core (plain Tk idles near 0.2%).

The tests run the real ``App.refresh`` on a bare ``App`` (no ``__init__``: no services, config
or tray) with the real empty-state widgets, and count variable writes and widget
``configure`` calls over repeated rounds with an unchanged state.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from app.app import App
from app.widgets import tabs


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every Variable.set and widget configure call, as (kind, target)."""
    seen: list[tuple[str, str]] = []
    orig_set = tk.Variable.set
    orig_configure = tk.Misc._configure  # type: ignore[attr-defined]

    def counting_set(self: tk.Variable, value: Any) -> None:
        seen.append(("var.set", str(self)))
        orig_set(self, value)

    def counting_configure(self: tk.Misc, cmd: Any, cnf: Any, kw: Any) -> Any:
        seen.append(("configure", str(self)))
        return orig_configure(self, cmd, cnf, kw)

    monkeypatch.setattr(tk.Variable, "set", counting_set)
    monkeypatch.setattr(tk.Misc, "_configure", counting_configure)
    return seen


@pytest.fixture
def bare_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A real Tk root of class App, with the widgets refresh() touches and nothing else."""
    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    tree = ttk.Treeview(root, columns=("file", "status", "progress", "language", "time"))
    tree.pack()
    drop_zone = ttk.LabelFrame(root)
    drop_zone.pack()
    empty_state = ttk.Frame(drop_zone)
    browse_row = ttk.Frame(drop_zone)
    browse_row.pack()
    headline = tk.StringVar(master=root)
    ttk.Label(empty_state, textvariable=headline).pack()
    buttons = {key: ttk.Button(root, text=key) for key in tabs.QUEUE_ACTION_KEYS}
    root.tree = tree
    root.row_map = {}
    root.queue = []
    root.download_queue = []
    root._base_title = "Whisper Transcriber Suite"
    root.tray = None
    root._closing = False
    root.queue_action_buttons = buttons
    root.transcribe_empty_state = empty_state
    root.transcribe_browse_row = browse_row
    root.transcribe_empty_headline_var = headline
    root.transcribe_has_sample = True
    root._dnd_ready = False
    monkeypatch.setattr("app.app.win_taskbar.sync", lambda _root: None)
    try:
        yield root
    finally:
        root.destroy()


def test_refresh_with_an_empty_queue_writes_nothing_after_the_first_round(
    bare_app: Any, writes: list[tuple[str, str]]
) -> None:
    bare_app.refresh()
    assert bare_app.transcribe_empty_headline_var.get()  # the first round filled it in
    writes.clear()

    bare_app.refresh()
    bare_app.refresh()

    assert writes == []


def test_refresh_still_updates_the_headline_when_its_text_changes(
    bare_app: Any, writes: list[tuple[str, str]]
) -> None:
    bare_app.refresh()
    writes.clear()

    bare_app._dnd_ready = True  # drag and drop became ready: the headline must follow
    bare_app.refresh()

    assert [kind for kind, _ in writes] == ["var.set"]
    assert bare_app.transcribe_empty_headline_var.get().startswith("Drop a file here")


def test_sync_empty_state_writes_the_headline_once_while_nothing_changes() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        var = tk.StringVar(master=root)
        drop_zone = ttk.Frame(root)
        drop_zone.pack()
        host = SimpleNamespace(
            queue=[],
            _dnd_ready=False,
            transcribe_has_sample=True,
            transcribe_empty_state=ttk.Frame(drop_zone),
            transcribe_browse_row=ttk.Frame(drop_zone),
            transcribe_empty_headline_var=var,
        )
        host.transcribe_browse_row.pack()
        written: list[str] = []
        var.trace_add("write", lambda *_: written.append(var.get()))

        for _ in range(4):
            tabs.sync_transcribe_empty_state(host)  # type: ignore[arg-type]

        assert written == ["Pick a file, paste a link, or try the sample"]
    finally:
        root.destroy()
