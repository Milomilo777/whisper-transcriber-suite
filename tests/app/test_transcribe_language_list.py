"""The Transcribe tab's Language list offers "Auto" once, not also "Automatic".

The subtitle language table starts with an "Automatic" row (empty code) that meant the
same as "Auto"; both stood one above the other (click-through test, 2026-10-21). Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

import pytest

from app.app import App
from core.config import DEFAULT_CONFIG


def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)


def test_auto_is_offered_once(tmp_path):
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
        lists = [list(w.cget("values")) for w in _widgets(app)
                 if isinstance(w, ttk.Combobox) and "English" in list(w.cget("values"))]
        first = next(values for values in lists if values and values[0] == "Auto")
        assert "Automatic" not in first
        assert first.count("Auto") == 1 and "Persian" in first
    finally:
        app.destroy()


def test_enter_in_the_file_and_link_boxes_starts_them(tmp_path):
    """Enter after pasting did nothing (code review, 2026-10-21)."""
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
        bound = {str(w.cget("textvariable")): w.bind("<Return>") for w in _widgets(app)
                 if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)}
        assert bound.get(str(app.fv))
        assert bound.get(str(app.download_url_var))
    finally:
        app.destroy()
