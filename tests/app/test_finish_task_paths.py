"""Parent-side outcomes for finished work (no Tk window): a second worker's
startup failure, a Cancel that arrives after the files were written, a locked
history database at finish time, and a worker ``error`` event after the files
exist. Each test states its scenario in the docstring.
"""
from __future__ import annotations

import queue
import sqlite3
import time
from types import SimpleNamespace

import app.services.transcription_service as ts
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


def _cancelled_task_with_done(tmp_path, outputs, no_speech=False):
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    t = _task(str(tmp_path / "a.mp4"), hist)
    t.cancelled = True
    t.status = "cancelled"  # app.cancel() did this at click time
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put({"event": "done", "task_id": t.task_id, "outputs": outputs,
                           "no_speech": no_speech, "word_count": 1, "audio_duration": 1.0,
                           "_token": "tok1", "_worker_id": 1, "_pid": 5})
    svc.poll()
    return t, hist, calls


def test_cancel_after_outputs_written_ends_finished_with_result_card(tmp_path):
    """Cancel clicked while the worker was writing: the done event carries the
    files, so the run is finished (row, status and result card), not cancelled."""
    out = tmp_path / "a.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    js = tmp_path / "a.json"
    js.write_text("{}", encoding="utf-8")
    t, hist, calls = _cancelled_task_with_done(tmp_path, [str(out), str(js)])
    row = hist.list_transcriptions()[0]
    assert row["status"] == "finished" and row["output_paths"] == [str(out), str(js)]
    assert t.status == "finished" and calls.shown == [t]


def test_cancel_with_only_some_formats_written_stays_cancelled(tmp_path):
    """A partial file set (a cancel during the export steps) is not a result."""
    out = tmp_path / "a.srt"
    out.write_text("partial", encoding="utf-8")
    t, hist, calls = _cancelled_task_with_done(tmp_path, [str(out)])
    assert hist.list_transcriptions()[0]["status"] == "cancelled"
    assert t.status == "cancelled" and calls.shown == []


def test_cancel_without_outputs_stays_cancelled(tmp_path):
    """A normal cancel (checkpoint only, empty outputs) is unchanged."""
    t, hist, calls = _cancelled_task_with_done(tmp_path, [])
    assert hist.list_transcriptions()[0]["status"] == "cancelled"
    assert t.status == "cancelled" and calls.shown == []


def test_cancel_after_no_speech_result_ends_finished(tmp_path):
    """A complete no-speech result (empty outputs, no_speech set) is finished too."""
    t, hist, calls = _cancelled_task_with_done(tmp_path, [], no_speech=True)
    assert hist.list_transcriptions()[0]["status"] == "finished"
    assert t.status == "finished"


def _locked_once(hist, failures: int):
    real = hist.finish_transcription
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] <= failures:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)

    hist.finish_transcription = flaky  # type: ignore[method-assign]
    return state


def _done_event(t, out):
    return {"event": "done", "task_id": t.task_id, "outputs": [str(out)],
            "word_count": 1, "audio_duration": 1.0,
            "_token": "tok1", "_worker_id": 1, "_pid": 5}


def test_locked_history_write_is_retried_and_row_is_finished(tmp_path, monkeypatch):
    """A transient lock at finish time must not leave the row 'running'."""
    monkeypatch.setattr(ts, "_HISTORY_LOCK_RETRY_DELAYS", (0.0, 0.0, 0.0))
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    out = tmp_path / "b.srt"
    out.write_text("x", encoding="utf-8")
    t = _task(str(tmp_path / "b.mp4"), hist)
    app.workers.append(_worker(1, "tok1", t))
    state = _locked_once(hist, failures=2)
    app.worker_events.put(_done_event(t, out))
    svc.poll()
    assert state["n"] == 3
    assert t.status == "finished" and calls.shown == [t]
    assert hist.list_transcriptions()[0]["status"] == "finished"


def test_persistent_lock_still_reports_finished_and_logs_loudly(tmp_path, monkeypatch, caplog):
    """When the lock outlasts the retries the files are still reported as
    done and the failure is logged at error level."""
    monkeypatch.setattr(ts, "_HISTORY_LOCK_RETRY_DELAYS", (0.0, 0.0, 0.0))
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    out = tmp_path / "b.srt"
    out.write_text("x", encoding="utf-8")
    t = _task(str(tmp_path / "b.mp4"), hist)
    app.workers.append(_worker(1, "tok1", t))
    state = _locked_once(hist, failures=99)
    app.worker_events.put(_done_event(t, out))
    with caplog.at_level("ERROR"):
        svc.poll()
    assert state["n"] == 4  # first try + 3 retries
    assert t.status == "finished" and calls.shown == [t]
    assert any("History record update failed" in r.getMessage() for r in caplog.records)
