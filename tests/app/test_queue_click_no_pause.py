"""A click on a Queue row only selects it.

A single click on a running row's Status or Progress cell used to pause the job, and a second
click resumed it: a user picking the row to read it paused the work without noticing (deep
review of tabs 1-3, 2026-10-21). Pause and Resume stay on the buttons and the right-click menu.
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

import pytest

from app.app import App


def test_the_app_has_no_click_to_pause_handler() -> None:
    assert not hasattr(App, "queue_status_cell_click")


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
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


def test_no_click_binding_pauses_a_job(app) -> None:
    script = app.tree.bind("<Button-1>")
    assert "pause" not in script and "status_cell" not in script
