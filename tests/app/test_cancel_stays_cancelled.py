"""A task the user cancelled ends as "cancelled", never "error".

A worker ``error`` event or the hung-worker watchdog that lands AFTER the user's
Cancel used to flip the task to "error" (queue row, history row and the usage
stats row). Genuine errors without a cancel stay "error"; a Cancel that arrives
after every output was written stays "finished".

Windowless: no Tk root is created.
"""
from __future__ import annotations

import time
from queue import Empty
from unittest.mock import MagicMock

from app.services.transcription_service import TranscriptionService
from core import stats as core_stats


class _Events:
    def __init__(self):
        self.items: list = []

    def get_nowait(self):
        if self.items:
            return self.items.pop(0)
        raise Empty

    def put(self, event):
        self.items.append(event)


class _App:
    def __init__(self):
        self.workers: list = []
        self.queue: list = []
        self.app_config = {
            "output_formats": ["srt", "json"],
            "telemetry_opt_in": True,
            "stats_url": "https://example/stats",
        }
        self.worker_events = _Events()
        self.model_ready = False
        self.model_loading = False
        self._closing = False
        self._exit_waiting = False
        self.history = MagicMock()
        self.history.finish_transcription.return_value = True
        self.parallel_workers = 1
        self.logged: list[str] = []

    def log(self, msg, *a, **k):
        self.logged.append(str(msg))

    def update_overall_progress(self, *a):
        pass

    def after(self, ms, func):
        pass

    def show_last_result(self, task):
        pass

    def note_job_success(self):
        pass


class _Task:
    def __init__(self, **kwargs):
        self.file_path = "/tmp/test.mp3"
        self.status = "running"
        self.progress = 0
        self.cancelled = False
        self.end_time = None
        self.word_count = 0
        self.audio_duration = 0.0
        self.start_time = time.time()
        self.history_id = 1
        self.error_reason = ""
        self.recovery_note = ""
        self.source_download = None
        self.__dict__.update(kwargs)


class _LiveProc:
    pid = 1234

    def poll(self):
        return None

    def kill(self):
        pass

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass


def _rig(monkeypatch, task):
    rows: list = []
    monkeypatch.setattr(
        core_stats, "post_stats_async", lambda config, payload, **kw: rows.append(payload) or True
    )
    app = _App()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    worker = {
        "id": 1, "token": "test-token", "task": task, "ready": True,
        "process": _LiveProc(), "last_event_at": time.monotonic(),
    }
    app.workers.append(worker)
    return app, svc, worker, rows


def _user_cancels(task):
    # Mirrors App.cancel(): flag + status, then the worker is told to stop.
    task.cancelled = True
    task.status = "cancelled"


def test_worker_error_after_cancel_stays_cancelled(monkeypatch):
    task = _Task()
    app, svc, worker, rows = _rig(monkeypatch, task)
    _user_cancels(task)
    app.worker_events.put({
        "event": "error", "message": "ffmpeg exited with code 1",
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "cancelled"
    assert not task.error_reason
    assert [r["status"] for r in rows] == ["cancelled"]
    assert app.history.finish_transcription.call_args.kwargs["status"] == "cancelled"
    assert worker["task"] is None
    assert any("ffmpeg exited" in m for m in app.logged), "the error text still reaches the log"


def test_watchdog_after_cancel_stays_cancelled(monkeypatch):
    task = _Task()
    app, svc, worker, rows = _rig(monkeypatch, task)
    _user_cancels(task)
    worker["last_event_at"] = time.monotonic() - 3000
    svc.restart_worker = MagicMock()

    svc._poll_once()

    assert task.status == "cancelled"
    assert not task.error_reason
    assert [r["status"] for r in rows] == ["cancelled"]
    assert app.history.finish_transcription.call_args.kwargs["status"] == "cancelled"
    svc.restart_worker.assert_called_once_with(worker)  # the wedged worker is still replaced


def test_genuine_error_without_cancel_is_still_error(monkeypatch):
    task = _Task()
    app, svc, worker, rows = _rig(monkeypatch, task)
    app.worker_events.put({
        "event": "error", "message": "model exploded",
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "error"
    assert task.error_reason
    assert [r["status"] for r in rows] == ["error"]


def test_genuine_hang_without_cancel_is_still_error(monkeypatch):
    task = _Task()
    app, svc, worker, rows = _rig(monkeypatch, task)
    worker["last_event_at"] = time.monotonic() - 3000
    svc.restart_worker = MagicMock()

    svc._poll_once()

    assert task.status == "error"
    assert [r["status"] for r in rows] == ["error"]


def test_cancel_after_all_outputs_written_stays_finished(monkeypatch, tmp_path):
    task = _Task(file_path=str(tmp_path / "test.mp3"), output_formats=["srt", "json"])
    app, svc, worker, rows = _rig(monkeypatch, task)
    srt, js = tmp_path / "test.srt", tmp_path / "test.json"
    srt.write_text("x", encoding="utf-8")
    js.write_text("{}", encoding="utf-8")
    task.output_paths = [str(srt), str(js)]
    _user_cancels(task)
    app.worker_events.put({
        "event": "done", "outputs": [str(srt), str(js)],
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "finished"
    assert [r["status"] for r in rows] == ["finished"]


def test_cancel_then_error_then_exit_posts_one_row(monkeypatch):
    task = _Task()
    app, svc, worker, rows = _rig(monkeypatch, task)
    _user_cancels(task)
    app.worker_events.put({
        "event": "error", "message": "boom", "_worker_id": 1, "_token": "test-token",
    })
    app.worker_events.put({
        "event": "worker_exit", "return_code": 1, "_pid": 1234,
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "cancelled"
    assert len(rows) == 1 and rows[0]["status"] == "cancelled"
