"""A worker's start-up failure while a model setup already runs.

The first ``startup_error`` opens the mandatory model download. A SECOND
worker that fails to start while that modal is up (the queue's dispatch
tick keeps running under ``wait_window``) must not wedge its task: with
``model_setup_running`` set, the handler used to do nothing at all — the
task stayed "running" forever, its history row never closed, and the
still-active worker blocked the queue until the app was restarted.
"""
from __future__ import annotations

import queue
import time
from types import SimpleNamespace

from app.services.transcription_service import TranscriptionService
from core.history import HistoryDB
from core.task import TranscriptionTask


class _Calls:
    def __init__(self) -> None:
        self.shown: list = []
        self.logs: list[str] = []
        self.modals: list[dict] = []


def _app(tmp_path, calls: _Calls, model_setup_running: bool):
    hist = HistoryDB(tmp_path / "history.db")
    app = SimpleNamespace(
        worker_events=queue.Queue(), workers=[], queue=[],
        app_config={"transcribe_backend": "faster_whisper",
                    "output_formats": ["srt", "json"]},
        after=lambda ms, fn=None, *a: (fn() if ms == 0 else None),
        log=calls.logs.append,
        update_overall_progress=lambda: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, model_status=lambda m: None,
        show_last_result=calls.shown.append, note_job_success=lambda: None,
        model_setup_running=model_setup_running,
        ensure_model_with_modal=lambda **k: calls.modals.append(k),
        history=hist, post_to_main=lambda fn: fn(), status_var=None,
    )
    return app, hist


def _worker(wid: int, token: str, task=None):
    return {"id": wid,
            "process": SimpleNamespace(pid=111, poll=lambda: None,
                                       wait=lambda **_kw: 0),
            "ready": False, "task": task, "temporary": False,
            "token": token, "last_event_at": 0.0, "stdin_lock": None}


def _task(path: str, hist: HistoryDB) -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.history_id = hist.insert_transcription(path)
    t.status = "running"
    t.start_time = time.time()
    t.task_id = f"h{t.history_id}"
    return t


def test_second_startup_error_while_a_model_setup_runs_fails_the_task(tmp_path):
    """The task dispatched to the worker that failed to start must end as an
    error with its history row closed — not stay 'running' forever."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls, model_setup_running=True)
    svc = TranscriptionService(app)
    t = _task(str(tmp_path / "wedge.mp4"), hist)
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put({
        "event": "startup_error", "message": "model missing",
        "_token": "tok1", "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert t.status == "error", "the task must not be wedged at 'running'"
    assert hist.list_transcriptions()[0]["status"] == "error"
    assert app.workers == [], "the dead-start worker must not be kept"
    # And no second download modal may stack on the running one.
    assert calls.modals == []


def test_first_startup_error_without_a_running_setup_still_opens_the_modal(tmp_path):
    """The existing behaviour for the first failure is unchanged: teardown
    plus the mandatory download modal."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls, model_setup_running=False)
    svc = TranscriptionService(app)
    t = _task(str(tmp_path / "first.mp4"), hist)
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put({
        "event": "startup_error", "message": "model missing",
        "_token": "tok1", "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert t.status == "error"
    assert calls.modals == [{"mandatory": True}]
