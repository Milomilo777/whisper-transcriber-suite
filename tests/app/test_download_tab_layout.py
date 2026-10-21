"""Download tab fixes from the second verification pass of the deep review (2026-10-21):
the time boxes after a download is queued, and the action bar above the table (needs Tk).
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

import pytest

from app.app import App
from core.config import DEFAULT_CONFIG


def test_the_time_boxes_go_back_to_the_whole_video():
    import inspect

    from app.services.download_service import DownloadService

    src = inspect.getsource(DownloadService.enqueue_from_form)
    assert 'start_var.set("0:00:00")' in src and 'end_var.set("0:00:00")' in src
    assert 'start_var.set("")' not in src


def test_the_download_action_bar_sits_above_the_table(tmp_path):
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")
    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False), \
         patch("app.app.load_config", return_value=dict(DEFAULT_CONFIG)), \
         patch("app.app.save_config"):
        app = App()
    try:
        bar = app.download_action_bar
        table_frame = app.download_tree.master
        order = list(bar.master.pack_slaves())
        assert order.index(bar) < order.index(table_frame)
        assert int(app.download_tree.cget("height")) <= 5
    finally:
        app.destroy()
