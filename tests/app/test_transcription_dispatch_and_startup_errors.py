"""Dispatch of a waiting task and a worker's start-up failure, in ``TranscriptionService``.

* The history row is written before the task is marked running; if that
  write fails the task stays waiting (a locked database is common on Windows).
* A retried task gets a fresh correlation id from its fresh history row.
* A start-up error of the default engine opens the mandatory model download
  only when no model set-up is already running; a stale ``done`` event for an
  older attempt must not finish the current one.

Hermetic: a plain namespace stands in for the App, no worker is started.
"""
from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest

from app.services.transcription_service import TranscriptionService


def _app(**extra):
    base = dict(
        workers=[],
        queue=[],
        parallel_workers=1,
        worker_events=queue.Queue(),
        status_var=SimpleNamespace(set=lambda _text: None),
        update_overall_progress=lambda: None,
        log=lambda _msg: None,
        after=lambda *_a: None,
        app_config={"model": {"name": "test"}, "transcribe_backend": "faster_whisper"},
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _idle_worker():
    return {"id": 1, "process": SimpleNamespace(pid=111, poll=lambda: None),
            "ready": True, "task": None}


@pytest.fixture
def sent(monkeypatch):
    """Capture the command handed to the worker instead of writing to a pipe."""
    commands: list[dict] = []
    monkeypatch.setattr(
        TranscriptionService, "_dispatch_command_async",
        lambda self, worker, task, command: commands.append(command),
    )
    return commands


def test_a_failed_history_write_leaves_the_task_waiting(sent):
    class _LockedHistory:
        def insert_transcription(self, **_kw):
            raise RuntimeError("database is locked")

    app = _app(history=_LockedHistory())
    task = SimpleNamespace(status="waiting", file_path="clip.mp4")
    app.queue.append(task)
    worker = _idle_worker()
    app.workers.append(worker)

    TranscriptionService(app).dispatch_waiting()

    assert task.status == "waiting"
    assert worker["task"] is None
    assert sent == []


def test_a_dispatched_task_is_running_and_recorded(sent):
    class _History:
        def insert_transcription(self, **_kw):
            return 456

    app = _app(history=_History())
    task = SimpleNamespace(status="waiting", file_path="clip.mp4")
    app.queue.append(task)
    worker = _idle_worker()
    app.workers.append(worker)

    TranscriptionService(app).dispatch_waiting()

    assert worker["task"] is task
    assert task.status == "running"
    assert task.history_id == 456
    assert len(sent) == 1


def test_a_retried_task_gets_a_fresh_correlation_id(sent):
    class _History:
        def insert_transcription(self, **_kw):
            return 456

    app = _app(history=_History())
    task = SimpleNamespace(
        status="waiting", file_path="clip.mp4", task_id="h123", history_id=123
    )
    app.queue.append(task)
    app.workers.append(_idle_worker())

    TranscriptionService(app).dispatch_waiting()

    assert task.task_id == "h456"
    assert sent[0]["task_id"] == "h456"


def _start_up_error_poll(model_setup_running: bool):
    app = _app(model_setup_running=model_setup_running)
    app.after = lambda ms, func: func() if ms == 0 else None
    downloads: list[dict] = []
    app.ensure_model_with_modal = lambda **kw: downloads.append(kw)
    app.workers.append(
        {"id": 1, "process": SimpleNamespace(pid=111, poll=lambda: None,
                                             wait=lambda **_kw: 0)}
    )
    app.worker_events.put(
        {"event": "startup_error", "message": "model missing",
         "_worker_id": 1, "_pid": 111}
    )
    TranscriptionService(app).poll()
    return downloads


def test_a_start_up_error_opens_the_mandatory_download():
    assert _start_up_error_poll(model_setup_running=False) == [{"mandatory": True}]


def test_a_start_up_error_does_not_stack_a_second_download():
    assert _start_up_error_poll(model_setup_running=True) == []


def test_a_done_event_of_an_older_attempt_does_not_finish_the_task():
    app = _app()
    task = SimpleNamespace(status="running", task_id="h456")
    app.workers.append(
        {"id": 1, "process": SimpleNamespace(pid=111, poll=lambda: None),
         "task": task, "ready": True, "token": "tok-A"}
    )
    app.worker_events.put(
        {"event": "done", "task_id": "h123", "_worker_id": 1, "_pid": 111,
         "_token": "tok-A"}
    )

    TranscriptionService(app).poll()

    assert task.status == "running"
