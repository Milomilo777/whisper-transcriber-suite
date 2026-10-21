"""The Transcribe tab names the job it started while that job runs.

After Transcribe the tab kept saying "Ready: talk.mp3" while talk.mp3 was being transcribed,
so a user who came back saw no sign of the job (deep review of tabs 1-3, 2026-10-21). The
pure part needs no Tk; the last test builds the window.
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

import pytest

from app.widgets.tabs import running_job_line
from core.task import TranscriptionTask


def _task(path: str, status: str = "running", progress: int = 0, eta: float | None = None) -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.status = status
    t.progress = progress
    t.live_eta_s = eta
    return t


def test_nothing_runs_no_line(tmp_path) -> None:
    media = str(tmp_path / "talk.mp3")
    assert running_job_line(media, [_task(media, status="finished", progress=100)]) == (None, "")
    assert running_job_line("", []) == (None, "")


def test_the_box_file_running_with_time_left(tmp_path) -> None:
    media = str(tmp_path / "talk.mp3")
    job = _task(media, progress=34, eta=6 * 60)
    task, line = running_job_line(media, [job])
    assert task is job
    assert line == "Transcribing talk.mp3 — 34%, about 6 min left"


def test_no_time_left_yet_and_under_a_minute(tmp_path) -> None:
    media = str(tmp_path / "talk.mp3")
    assert running_job_line(media, [_task(media, progress=3)])[1] == "Transcribing talk.mp3 — 3%"
    assert running_job_line(media, [_task(media, progress=97, eta=20)])[1] == (
        "Transcribing talk.mp3 — 97%, under 1 min left")


def test_a_paused_job_says_paused(tmp_path) -> None:
    media = str(tmp_path / "talk.mp3")
    assert running_job_line(media, [_task(media, status="paused", progress=40)])[1] == (
        "Paused: talk.mp3 — 40%")


def test_the_box_path_matches_a_quoted_or_differently_cased_path(tmp_path) -> None:
    media = str(tmp_path / "talk.mp3")
    job = _task(media, progress=10)
    assert running_job_line(f'"{media}"', [job])[0] is job


def test_a_new_file_in_the_box_keeps_its_ready_line(tmp_path) -> None:
    """The user picked the next file: its Ready line matters more than the running job."""
    running = str(tmp_path / "talk.mp3")
    assert running_job_line(str(tmp_path / "next.mp3"), [_task(running, progress=10)]) == (None, "")


def test_an_empty_box_shows_a_job_started_by_browse(tmp_path) -> None:
    """Several files picked with Browse never enter the box; the first running one shows."""
    a, b = str(tmp_path / "a.mp3"), str(tmp_path / "b.mp3")
    waiting, job = _task(a, status="waiting"), _task(b, progress=50)
    assert running_job_line("", [waiting, job])[0] is job


def test_a_download_job_is_not_shown(tmp_path) -> None:
    """A job a finished download started belongs to the Download tab."""
    media = str(tmp_path / "video.mp4")
    job = _task(media, progress=10)
    job.source_download = object()
    assert running_job_line("", [job]) == (None, "")


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


def test_the_tab_swaps_the_ready_line_and_show_in_queue_opens_the_row(app, tmp_path, monkeypatch) -> None:
    from core import watcher

    monkeypatch.setattr(watcher, "cached_media_duration", lambda _p: None)
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x" * 1024)
    app.fv.set(str(media))
    assert app.transcribe_ready_var.get().startswith("Ready: talk.mp3")
    assert not app.transcribe_show_in_queue_btn.winfo_manager()

    job = _task(str(media), progress=34, eta=6 * 60)
    app.queue.append(job)
    app.refresh()
    assert app.transcribe_ready_var.get() == "Transcribing talk.mp3 — 34%, about 6 min left"
    assert app.transcribe_show_in_queue_btn.winfo_manager()

    app.transcribe_show_in_queue_btn.invoke()
    assert app.nb.select() == str(app.t2)
    assert [app.row_map[i] for i in app.tree.selection()] == [job]

    job.status, job.progress = "finished", 100
    app.refresh()
    assert app.transcribe_ready_var.get().startswith("Ready: talk.mp3")
    assert not app.transcribe_show_in_queue_btn.winfo_manager()


def test_the_idle_tick_does_not_touch_the_box_file(app, tmp_path, monkeypatch) -> None:
    """App.refresh runs every 500 ms: with no job running it must not stat the box file again
    (a path on a sleeping network share would stall the window each time). The box's own
    trace still redraws the line when the text changes."""
    from app.widgets import tabs

    calls: list[str] = []
    real = tabs.file_ready_state
    monkeypatch.setattr(tabs, "file_ready_state", lambda text, *a, **k: calls.append(text) or real(text, *a, **k))
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x" * 1024)
    app.fv.set(str(media))
    assert calls
    calls.clear()
    for _i in range(3):
        app.refresh()
    assert calls == []
    app.fv.set("")
    assert calls == [""]
