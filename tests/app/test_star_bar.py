"""The star invitation in the app: when the bar shows, its three buttons, the
offline and running-job gates, and the hook in the task-done handler. The rules
themselves are tested without Tk in tests/core/test_star_invite.py.

Like tests/app/test_update_bar.py, the App methods run on a small Tk host.
"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from types import SimpleNamespace

import pytest

import app.app as app_mod
from app.app import App
from app.services.transcription_service import TranscriptionService
from core import offline
from core import star_invite as s

_FIRST = date(2026, 10, 1)
_TODAY = _FIRST + timedelta(days=s.MIN_DAYS)

_BORROWED = (
    "_star_save", "_star_stamp_first_run", "_jobs_active", "note_job_success",
    "_show_star_bar", "_hide_star_bar", "_star_open_page", "_star_open", "_star_never",
)


class _Host(tk.Tk):
    """A Tk root that runs the App's star-invitation methods."""


for _name in _BORROWED:
    setattr(_Host, _name, getattr(App, _name))


@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: urls.append(url) or True)
    return urls


@pytest.fixture
def set_today(monkeypatch):
    return lambda day: monkeypatch.setattr(app_mod, "_today", lambda: day)


@pytest.fixture
def host(monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(dict(c)))
    monkeypatch.setattr(app_mod, "_today", lambda: _TODAY)
    offline.set_offline(False)
    root = _Host()
    root.withdraw()
    root.app_config = {  # type: ignore[attr-defined]
        s.KEY_FIRST_RUN: _FIRST.isoformat(), s.KEY_JOBS: s.MIN_JOBS - 1,
        s.KEY_SHOWN: 0, s.KEY_LAST_SHOWN: "", s.KEY_DONT_ASK: False,
    }
    root._closing = False  # type: ignore[attr-defined]
    root._star_bar = None  # type: ignore[attr-defined]
    root.queue = []  # type: ignore[attr-defined]
    root.download_queue = []  # type: ignore[attr-defined]
    root.logs = []  # type: ignore[attr-defined]
    root.log = root.logs.append  # type: ignore[attr-defined]
    root.saved = saved  # type: ignore[attr-defined]
    root.nb = ttk.Notebook(root)  # type: ignore[attr-defined]
    root.nb.pack(fill="both", expand=True)  # type: ignore[attr-defined]
    try:
        yield root
    finally:
        offline.set_offline(None)
        try:
            root.destroy()
        except tk.TclError:
            pass


def _visible(host) -> bool:
    return host._star_bar is not None and host._star_bar.visible


def _task(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


# ------------------------------------------------------------------- when it shows

def test_the_fifth_success_after_a_week_shows_the_bar_above_the_tabs(host):
    host.note_job_success()
    assert _visible(host)
    assert host._star_bar.text_var.get() == s.BAR_TEXT
    slaves = host.pack_slaves()
    assert slaves.index(host._star_bar) < slaves.index(host.nb)
    assert [b.cget("text") for b in host._star_bar.buttons.values()] == [
        "Open GitHub page", "Not now", "Don't ask again",
    ]
    assert host.app_config[s.KEY_SHOWN] == 1
    assert host.saved[-1][s.KEY_SHOWN] == 1
    assert host.saved[-1][s.KEY_JOBS] == s.MIN_JOBS


def test_the_fourth_success_only_counts(host):
    host.app_config[s.KEY_JOBS] = s.MIN_JOBS - 2
    host.note_job_success()
    assert not _visible(host)
    assert host.saved[-1][s.KEY_JOBS] == s.MIN_JOBS - 1


def test_before_the_seventh_day_the_bar_stays_away(host, set_today):
    set_today(_FIRST + timedelta(days=s.MIN_DAYS - 1))
    host.note_job_success()
    assert not _visible(host)


def test_never_while_another_job_runs_or_waits(host):
    for rows in ("queue", "download_queue"):
        for status in ("running", "waiting"):
            setattr(host, rows, [_task(status)])
            host.app_config[s.KEY_JOBS] = s.MIN_JOBS - 1
            host.note_job_success()
            assert not _visible(host), (rows, status)
            assert host.app_config[s.KEY_SHOWN] == 0
        setattr(host, rows, [])
    host.queue = [_task("finished"), _task("error")]
    host.app_config[s.KEY_JOBS] = s.MIN_JOBS - 1
    host.note_job_success()
    assert _visible(host)


def test_a_running_download_that_transcribes_blocks_it(host):
    host.download_queue = [_task("transcribing")]
    host.note_job_success()
    assert not _visible(host)


def test_never_in_work_offline_mode(host):
    offline.set_offline(True)
    host.note_job_success()
    assert not _visible(host)
    assert host.app_config[s.KEY_SHOWN] == 0
    assert host.app_config[s.KEY_JOBS] == s.MIN_JOBS  # still counted


def test_switching_offline_on_hides_a_visible_bar(host):
    host.note_job_success()
    assert _visible(host)
    host._hide_star_bar()  # what _set_work_offline / _sync_offline_menu call
    assert not _visible(host)


def test_the_bar_never_takes_focus_or_grabs_input(host, monkeypatch):
    calls: list[str] = []
    for name in ("focus_set", "focus_force", "grab_set", "grab_set_global"):
        monkeypatch.setattr(tk.Misc, name, lambda self, *a, _n=name, **k: calls.append(_n))
    host.note_job_success()
    host.update_idletasks()
    assert _visible(host)
    assert calls == []
    assert [w for w in host.winfo_children() if isinstance(w, tk.Toplevel)] == []


# --------------------------------------------------------------------- the buttons

def test_not_now_hides_it_and_keeps_the_second_chance(host, opened, set_today):
    host.note_job_success()
    host._star_bar.buttons["not_now"].invoke()
    assert not _visible(host)
    assert opened == []
    assert host.app_config[s.KEY_DONT_ASK] is False
    assert host.app_config[s.KEY_SHOWN] == 1
    # a month later, after more jobs, the second invitation comes
    set_today(_TODAY + timedelta(days=s.MIN_GAP_DAYS))
    host.note_job_success()
    assert _visible(host)
    assert host.app_config[s.KEY_SHOWN] == 2


def test_never_more_than_two_invitations_ever(host, set_today):
    host.note_job_success()
    host._star_bar.buttons["not_now"].invoke()
    day = _TODAY
    for _ in range(3):
        day = day + timedelta(days=s.MIN_GAP_DAYS)
        set_today(day)
        host.note_job_success()
        if _visible(host):
            host._star_bar.buttons["not_now"].invoke()
    assert host.app_config[s.KEY_SHOWN] == 2


def test_dont_ask_again_is_saved_and_final(host, opened, set_today):
    host.note_job_success()
    host._star_bar.buttons["never"].invoke()
    assert not _visible(host)
    assert opened == []
    assert host.saved[-1][s.KEY_DONT_ASK] is True
    set_today(_TODAY + timedelta(days=3000))
    host.note_job_success()
    assert not _visible(host)
    assert host.app_config[s.KEY_SHOWN] == 1


def test_open_github_page_opens_the_repo_page_and_stops_asking(host, opened):
    host.note_job_success()
    host._star_bar.buttons["open"].invoke()
    assert opened == [s.REPO_URL]
    assert "stargazers" not in opened[0]
    assert not _visible(host)
    assert host.saved[-1][s.KEY_DONT_ASK] is True


def test_the_about_link_opens_the_repo_page(host, opened):
    host._star_open_page()
    assert opened == [s.REPO_URL]
    assert host.app_config[s.KEY_DONT_ASK] is False


def test_stamping_the_first_run_saves_once(host):
    host.app_config[s.KEY_FIRST_RUN] = ""
    host._star_stamp_first_run()
    assert host.app_config[s.KEY_FIRST_RUN] == _TODAY.isoformat()
    assert len(host.saved) == 1
    host._star_stamp_first_run()
    assert len(host.saved) == 1


def test_a_failing_save_is_logged_and_does_not_raise(host, monkeypatch):
    def boom(_config):
        raise OSError("disk full")

    monkeypatch.setattr(app_mod, "save_config", boom)
    host.note_job_success()
    assert _visible(host)
    assert any("Could not save the star-invitation choice" in line for line in host.logs)


# --------------------------------------------- the hook in the task-done handler

def _finish(task, *, keep_status=False):
    counted: list[int] = []
    app = SimpleNamespace(
        app_config={}, update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        note_job_success=lambda: counted.append(1),
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    svc.finish_task({"task": task, "temporary": False}, keep_status=keep_status)
    return counted


def _job(**over):
    base = dict(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=[], file_path="clip.mp4", history_id=0, source_download=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_a_finished_job_is_counted():
    assert _finish(_job()) == [1]


def test_an_errored_cancelled_or_sample_job_is_not_counted():
    assert _finish(_job(status="error"), keep_status=True) == []
    assert _finish(_job(cancelled=True)) == []
    assert _finish(_job(open_when_done=True)) == []


def test_a_counter_failure_cannot_break_the_finished_job():
    task = _job()
    app = SimpleNamespace(
        app_config={}, update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        note_job_success=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    worker = {"task": task, "temporary": False}
    svc.finish_task(worker)
    assert task.status == "finished"
    assert worker["task"] is None
