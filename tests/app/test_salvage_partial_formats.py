"""Parent-side salvage rules for a worker ``error`` after writing files.

A worker that fails DURING the export steps (an error after the first
format was written) reports only the files it wrote. That partial set is
not a delivered result: the run must end as an error, like the Cancel
path already rules for a partial set (see test_finish_task_paths.py).
"""
from __future__ import annotations

import queue
import time
from types import SimpleNamespace

import pytest

from app.services.transcription_service import TranscriptionService
from core.history import HistoryDB
from core.task import TranscriptionTask


class _Calls:
    def __init__(self) -> None:
        self.shown: list = []
        self.logs: list[str] = []


def _app(tmp_path, calls: _Calls):
    hist = HistoryDB(tmp_path / "history.db")
    app = SimpleNamespace(
        worker_events=queue.Queue(), workers=[], queue=[],
        app_config={"transcribe_backend": "faster_whisper",
                    "output_formats": ["srt", "json"]},
        after=lambda *a, **k: None, log=calls.logs.append,
        update_overall_progress=lambda: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, model_status=lambda m: None,
        show_last_result=calls.shown.append, note_job_success=lambda: None,
        history=hist, post_to_main=lambda fn: fn(), status_var=None,
    )
    return app, hist


def _worker(wid: int, token: str, task=None, ready: bool = True):
    return {"id": wid, "process": None, "ready": ready, "task": task,
            "temporary": False, "token": token, "last_event_at": 0.0,
            "stdin_lock": None}


def _task(path: str, hist: HistoryDB, formats=None) -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.history_id = hist.insert_transcription(path)
    t.status = "running"
    t.start_time = time.time()
    t.task_id = f"h{t.history_id}"
    if formats is not None:
        t.output_formats = formats
    return t


def _error_event(t, outputs, message="post step failed"):
    return {"event": "error", "task_id": t.task_id, "message": message,
            "outputs": outputs, "_token": "tok1", "_worker_id": 1, "_pid": 5}


def test_error_after_only_some_requested_formats_is_not_a_success(tmp_path):
    """The worker wrote the .srt and failed before the .json: the run's
    requested format set is partial, so it must stay an error (the written
    file itself is untouched on disk) instead of being reported finished."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    out = tmp_path / "p.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    t = _task(str(tmp_path / "p.mp4"), hist, formats=["srt", "json"])
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put(_error_event(t, [str(out)]))
    svc.poll()
    row = hist.list_transcriptions()[0]
    assert t.status == "error" and calls.shown == []
    assert row["status"] == "error"


def test_error_after_every_requested_format_is_still_a_success(tmp_path):
    """A late failure after the complete set (srt + json) keeps the salvage."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    out = tmp_path / "p.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    js = tmp_path / "p.json"
    js.write_text("[]", encoding="utf-8")
    t = _task(str(tmp_path / "p.mp4"), hist, formats=["srt", "json"])
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put(_error_event(t, [str(out), str(js)]))
    svc.poll()
    row = hist.list_transcriptions()[0]
    assert t.status == "finished" and calls.shown == [t]
    assert row["status"] == "finished"


def test_error_after_a_single_requested_format_is_salvaged(tmp_path):
    """One format requested, one written: complete, so salvaged."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls)
    svc = TranscriptionService(app)
    out = tmp_path / "p.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n", encoding="utf-8")
    t = _task(str(tmp_path / "p.mp4"), hist, formats=["srt"])
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put(_error_event(t, [str(out)]))
    svc.poll()
    assert t.status == "finished"
    assert hist.list_transcriptions()[0]["status"] == "finished"
