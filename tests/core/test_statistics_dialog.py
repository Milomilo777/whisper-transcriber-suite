"""Regression: the Statistics dialog must not let a history.db read
failure escape into the Tk menu callback.

``show_statistics`` is invoked straight from a File-menu command, so an
exception from ``history.stats()`` (e.g. ``database is locked`` / an I/O
error) is reported by Tk only to stderr — on a windowed build the user
sees the menu item do nothing at all. It must surface the failure via
the app-wide friendly error dialog instead.
"""
from __future__ import annotations

import sqlite3
import types

import pytest

tk = pytest.importorskip("tkinter")


def test_show_statistics_survives_stats_error(monkeypatch):
    from app.dialogs import statistics

    captured: dict = {}

    def _fake_show_error(parent, title, message, detail=None):
        captured["parent"] = parent
        captured["title"] = title
        captured["message"] = message
        captured["detail"] = detail

    monkeypatch.setattr(statistics, "show_error", _fake_show_error)

    class _BoomHistory:
        def stats(self):
            raise sqlite3.OperationalError("database is locked")

    app = types.SimpleNamespace(history=_BoomHistory())

    statistics.show_statistics(app)  # must not raise

    assert captured["title"] == "Statistics"
    assert captured["message"] == "Could not read the transcription history."
    assert "database is locked" in captured["detail"]


def test_show_statistics_renders_empty_history_without_crashing(tmp_path):
    """Happy path guard: an empty DB still produces the dialog with
    zeros (and my try/except must not disturb it)."""
    from app.dialogs import statistics
    from core.history import HistoryDB

    root = tk.Tk()
    root.withdraw()
    root.history = HistoryDB(tmp_path / "history.db")  # type: ignore[attr-defined]
    try:
        statistics.show_statistics(root)
        dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert len(dialogs) == 1
        dialogs[0].destroy()
    finally:
        root.history.close()  # type: ignore[attr-defined]
        root.destroy()
