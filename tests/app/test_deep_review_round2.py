"""Fixes from the second verification pass of the deep review of tabs 1-3 (2026-10-21).

- the same job queued twice by a second Transcribe click;
- the status line after Cancel.
Windowless. The Download-tab fixes are in test_download_tab_layout.py.
"""
from __future__ import annotations

import os
import types


import app.app as app_mod
from app.app import App


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _task(path: str, status: str, clip=(None, None)) -> types.SimpleNamespace:
    return types.SimpleNamespace(file_path=path, status=status, clip_start=clip[0], clip_end=clip[1])


def _dup_host(queue: list) -> types.SimpleNamespace:
    fake = types.SimpleNamespace(queue=queue)
    fake._same_job_active = App._same_job_active.__get__(fake)
    return fake


def test_the_same_file_and_range_counts_as_the_same_job(tmp_path):
    path = str(tmp_path / "class.flac")
    fake = _dup_host([_task(path, "running")])
    assert fake._same_job_active(_task(path, "waiting"))
    # another part of the same file is a new job
    assert not fake._same_job_active(_task(path, "waiting", clip=(60.0, 120.0)))
    # an ended job does not block a new one
    assert not _dup_host([_task(path, "finished")])._same_job_active(_task(path, "waiting"))
    # the same file named another way (case, relative) on Windows
    if os.name == "nt":
        assert fake._same_job_active(_task(path.upper(), "waiting"))


def test_a_second_transcribe_click_does_not_queue_it_again(tmp_path, monkeypatch):
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x")
    selected: list = []
    logs: list[str] = []
    running = _task(str(media), "running")
    fake = types.SimpleNamespace(
        fv=_Var(str(media)), queue=[running], log=logs.append, pb={},
        nb=types.SimpleNamespace(select=lambda tab: selected.append(tab)), t1="t1", t2="t2",
        _ensure_transcribe_ready=lambda: True, _confirm_english_only_model=lambda: True,
        _apply_task_options=lambda t: None, refresh=lambda: None,
    )
    fake._same_job_active = App._same_job_active.__get__(fake)
    App.add(fake)  # type: ignore[arg-type]
    assert fake.queue == [running]
    assert selected == ["t2"] and logs[-1].startswith("Already in the queue")


def test_cancel_says_so_on_the_status_line(monkeypatch):
    monkeypatch.setattr(app_mod.desktop_alert, "job_ended", lambda *_a: None)
    status = _Var("class.flac: 7% done — some words")
    task = types.SimpleNamespace(file_path="C:/rec/class.flac", status="running", progress=7.4,
                                 end_time=None, source_download=None)
    overall: list[bool] = []
    fake = types.SimpleNamespace(
        status_var=status, log=lambda _m: None, refresh=lambda: None,
        transcription_service=types.SimpleNamespace(send_control=lambda _t, _c: True),
        update_overall_progress=lambda: overall.append(True),
    )
    fake._release_waiting_download = App._release_waiting_download.__get__(fake)
    App.cancel(fake, task)  # type: ignore[arg-type]
    assert status.get() == "class.flac: cancelled at 7%"
    assert task.status == "cancelled" and overall == [True]
