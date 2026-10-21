"""The Transcribe tab's ready line gains the recording's length once ffprobe answers.

The length is read on a background thread and the line redrawn on the Tk thread; a
failed read must not start another read (an endless probe loop). Needs Tk.
"""
from __future__ import annotations

import subprocess
import time
import tkinter as tk
from unittest.mock import patch

import pytest

from app.app import App
from core import watcher
from core.config import DEFAULT_CONFIG


@pytest.fixture
def app(tmp_path):
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
        app_inst = App()
        try:
            yield app_inst
        finally:
            try:
                app_inst.destroy()
            except tk.TclError:
                pass


def _pump(app: App, until, seconds: float = 5.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        app.update()
        time.sleep(0.02)


def _fake_ffprobe(monkeypatch, out: bytes | None) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(args, **_kw):
        calls.append(args)
        if out is None:
            raise FileNotFoundError("no ffprobe")
        return subprocess.CompletedProcess(args, 0, out, b"")

    monkeypatch.setattr(watcher.subprocess, "run", fake_run)
    watcher._duration_cache.clear()
    return calls


def test_the_length_appears_after_the_probe(app, tmp_path, monkeypatch):
    calls = _fake_ffprobe(monkeypatch, b"65.2\n")
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x" * 1024)
    app.fv.set(str(media))
    assert app.transcribe_ready_var.get() == "Ready: talk.mp3 (1.0 KB)"
    _pump(app, lambda: "1:05" in app.transcribe_ready_var.get())
    assert app.transcribe_ready_var.get() == "Ready: talk.mp3 (1:05, 1.0 KB)"
    assert len(calls) == 1


def test_a_failed_probe_is_not_repeated(app, tmp_path, monkeypatch):
    calls = _fake_ffprobe(monkeypatch, None)
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x" * 1024)
    app.fv.set(str(media))
    _pump(app, lambda: False, seconds=1.5)
    assert len(calls) == 1
    assert app.transcribe_ready_var.get() == "Ready: talk.mp3 (1.0 KB)"
