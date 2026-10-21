"""The Queue's action buttons sit above the list, as on the Download tab.

Below the table they fell under the visible part of the tab in a small window, and the two
tabs put the same kind of bar in different places (deep review of tabs 1-3, 2026-10-21). The
line that says why the selected job failed follows the bar. Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

import pytest

from core.task import TranscriptionTask


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    from app.app import App
    from core.config import DEFAULT_CONFIG

    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False), \
         patch("app.app.load_config", return_value=dict(DEFAULT_CONFIG)), \
         patch("app.app.save_config"):
        app_inst = App()
        try:
            yield app_inst
        finally:
            try:
                app_inst.destroy()
            except tk.TclError:
                pass


def _packed(app) -> list:
    return app.queue_action_bar.master.pack_slaves()


def test_the_buttons_come_before_the_list(app) -> None:
    order = _packed(app)
    assert order.index(app.queue_action_bar) < order.index(app.tree.master)


def test_the_failure_line_sits_under_the_buttons(app) -> None:
    job = TranscriptionTask("talk.mp3")
    job.status, job.error_reason = "error", "The file could not be read."
    app.queue.append(job)
    app.refresh()
    app.tree.selection_set(app.tree.get_children()[0])
    app._update_queue_action_bar()
    order = _packed(app)
    assert app.queue_failure_label in order
    assert order.index(app.queue_failure_label) == order.index(app.queue_action_bar) + 1
