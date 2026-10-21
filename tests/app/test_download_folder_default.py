"""A fresh install's Download tab offers a folder instead of an empty box.

With the Quick start skipped, the Folder box was empty and the first Download only said
"Select a download folder first" (click-through test, 2026-10-21). It now holds the
user's Downloads folder, the same default the Quick start offers. Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

import pytest

from app.app import App
from app.dialogs.quick_start import default_output_folder
from core.config import DEFAULT_CONFIG


def _app(tmp_path, config: dict) -> App:
    with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
         patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
         patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
         patch("core.stats.post_stats_async", return_value=False), \
         patch("app.app.load_config", return_value=config), \
         patch("app.app.save_config"):
        return App()


@pytest.fixture
def display():
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")


def test_no_saved_folder_offers_the_downloads_folder(display, tmp_path):
    app = _app(tmp_path, dict(DEFAULT_CONFIG, download_folder=""))
    try:
        assert app.download_folder_var.get() == default_output_folder({})
        assert app.download_folder_var.get().strip()
    finally:
        app.destroy()


def test_a_saved_folder_is_kept(display, tmp_path):
    app = _app(tmp_path, dict(DEFAULT_CONFIG, download_folder=str(tmp_path)))
    try:
        assert app.download_folder_var.get() == str(tmp_path)
    finally:
        app.destroy()
