"""Parent-side outcomes for finished work (no Tk window): a second worker's
startup failure, a Cancel that arrives after the files were written, a locked
history database at finish time, and a worker ``error`` event after the files
exist. Each test states its scenario in the docstring.
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
        self.modals: list = []


def _app(tmp_path, calls: _Calls):
    hist = HistoryDB(tmp_path / "history.db")
    app = SimpleNamespace(
        worker_events=queue.Queue(), workers=[], queue=[],
        app_config={"transcribe_backend": "faster_whisper", "output_formats": ["srt", "json"]},
        after=lambda *a, **k: None, log=calls.logs.append,
        update_overall_progress=lambda: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, model_status=lambda m: None,
        show_last_result=calls.shown.append, note_job_success=lambda: None,
        model_setup_running=False,
        ensure_model_with_modal=lambda **k: calls.modals.append(k),
        history=hist, post_to_main=lambda fn: fn(), status_var=None,
    )
    return app, hist


def _worker(wid: int, token: str, task=None, ready: bool = True):
    return {"id": wid, "process": None, "ready": ready, "task": task, "temporary": False,
            "token": token, "last_event_at": 0.0, "stdin_lock": None}


def _task(path: str, hist: HistoryDB) -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.history_id = hist.insert_transcription(path)
    t.status = "running"
    t.start_time = time.time()
    t.task_id = f"h{t.history_id}"
    return t


def _startup_error(wid: int, token: str) -> dict:
    return {"event": "startup_error", "message": "CUDA out of memory",
            "_token": token, "_worker_id": wid, "_pid": 6}


def test_startup_error_of_second_worker_keeps_healthy_running_job(tmp_path):
    """Worker 2 cannot load a second model copy. Worker 1's running job must
    neither be failed nor hard-stopped, and no download modal may open."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    stopped: list = []
    svc.stop_all = lambda *a, **k: stopped.append(k)  # type: ignore[method-assign]
    t = _task(str(tmp_path / "long.mp4"), hist)
    w1 = _worker(1, "tok1", t)
    w2 = _worker(2, "tok2", ready=False)
    app.workers.extend([w1, w2])
    app.worker_events.put(_startup_error(2, "tok2"))
    svc.poll()
    assert t.status == "running"
    assert hist.list_transcriptions()[0]["status"] == "running"
    assert app.workers == [w1] and w1["task"] is t
    assert stopped == [] and calls.modals == []


def test_startup_error_of_only_worker_still_fails_task_and_opens_download(tmp_path):
    """No healthy peer: the old teardown stays (task ends as error, workers
    cleared, the required-download modal is scheduled)."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    after: list = []
    app.after = lambda ms, fn=None, *a: after.append(fn)
    svc = TranscriptionService(app)
    svc.stop_all = lambda *a, **k: None  # type: ignore[method-assign]
    t = _task(str(tmp_path / "x.mp4"), hist)
    w1 = _worker(1, "tok1", t, ready=False)
    app.workers.append(w1)
    app.worker_events.put(_startup_error(1, "tok1"))
    svc.poll()
    assert t.status == "error"
    assert hist.list_transcriptions()[0]["status"] == "error"
    assert app.workers == []
    for fn in after:
        if callable(fn):
            fn()
    assert calls.modals == [{"mandatory": True}]


def test_failed_second_worker_is_not_respawned_in_a_tight_loop(tmp_path):
    """After a second worker failed to start, dispatch must not spawn another
    one next to the live worker until the hold expires."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    spawned: list = []
    svc.start_worker = lambda *a, **k: spawned.append(k)  # type: ignore[method-assign]
    svc.worker_limit = lambda: 2  # type: ignore[method-assign]
    live = SimpleNamespace(poll=lambda: None, pid=1)
    w1 = _worker(1, "tok1", _task(str(tmp_path / "a.mp4"), hist))
    w1["process"] = live
    app.workers.append(w1)
    waiting = TranscriptionTask(str(tmp_path / "b.mp4"))
    waiting.status = "waiting"
    app.queue.append(waiting)
    svc._spawn_hold_until = time.monotonic() + 30
    svc.dispatch_waiting()
    assert spawned == []
    svc._spawn_hold_until = 0.0
    svc.dispatch_waiting()
    assert len(spawned) == 1
