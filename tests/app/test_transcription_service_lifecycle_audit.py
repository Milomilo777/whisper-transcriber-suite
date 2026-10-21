"""Lifecycle edge cases of TranscriptionService: a worker that crashes after
writing its files, a worker that hangs, an exit while a job runs, a cancel
during the export steps, an out-of-order event, and the rule that finishing a
job never starts the next one by itself (App.loop() does that).

Windowless: no Tk root is created.
"""
from __future__ import annotations

import threading
import time
from queue import Empty
from unittest.mock import MagicMock

from app.services.transcription_service import HUNG_WORKER_NOTE, TranscriptionService


class _Var:
    def set(self, value):
        pass


class _Events:
    def __init__(self):
        self.items: list = []

    def get_nowait(self):
        if self.items:
            return self.items.pop(0)
        raise Empty

    def put(self, event):
        self.items.append(event)


class MockApp:
    def __init__(self):
        self.workers: list = []
        self.queue: list = []
        self.app_config = {"output_formats": ["srt", "json"]}
        self.worker_events = _Events()
        self.status_var = _Var()
        self.model_ready = False
        self.model_loading = False
        self._closing = False
        self._exit_waiting = False
        self.history = MagicMock()
        self.parallel_workers = 1

    def log(self, *a, **k):
        pass

    def update_overall_progress(self, *a):
        pass

    def after(self, ms, func):
        pass

    def show_last_result(self, task):
        pass

    def note_job_success(self):
        pass


class MockTask:
    def __init__(self, **kwargs):
        self.file_path = "/tmp/test.mp3"
        self.status = "running"
        self.progress = 0
        self.cancelled = False
        self.end_time = None
        self.word_count = 0
        self.audio_duration = 0.0
        self.__dict__.update(kwargs)


class _DeadProc:
    pid = 1234

    def poll(self):
        return -9

    def kill(self):
        pass


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


def _worker(task, process, **extra):
    worker = {
        "id": 1, "token": "test-token", "task": task, "ready": True,
        "process": process, "last_event_at": time.monotonic(),
    }
    worker.update(extra)
    return worker


def test_worker_crashes_after_writing_outputs(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.history.finish_transcription.return_value = True
    task = MockTask(start_time=time.time() - 10, history_id=1,
                    file_path=str(tmp_path / "test.mp3"), output_formats=["srt", "json"])
    app.workers.append(_worker(task, _DeadProc()))
    srt_path = tmp_path / "test.srt"
    json_path = tmp_path / "test.json"
    srt_path.write_text("test", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")
    task.output_paths = [str(srt_path), str(json_path)]
    app.worker_events.put({
        "event": "worker_exit", "return_code": -9, "_pid": 1234,
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "finished", "complete outputs are salvaged as a success"
    assert app.history.finish_transcription.call_count == 1


def test_worker_hangs_without_events(tmp_path):
    """A hung job's history row says why it failed (it was blank before)."""
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time() - 3000, history_id=2,
                    file_path=str(tmp_path / "test2.mp3"))
    worker = _worker(task, _LiveProc())
    worker["last_event_at"] = time.monotonic() - 3000
    app.workers.append(worker)
    svc.restart_worker = MagicMock()

    svc._poll_once()

    assert task.status == "error"
    assert app.history.finish_transcription.call_count == 1
    kwargs = app.history.finish_transcription.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["error"] == HUNG_WORKER_NOTE
    svc.restart_worker.assert_called_once_with(worker)


def test_hung_worker_restart_does_not_hand_next_job_to_dying_worker(tmp_path):
    """Regression: finish_task used to call dispatch_waiting(), so the job
    queued behind a hung one went to the worker about to be restarted."""
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    hung = MockTask(start_time=time.time() - 3000, history_id=2,
                    file_path=str(tmp_path / "hung.mp3"))
    nxt = MockTask(status="waiting", file_path=str(tmp_path / "next.mp3"))
    app.queue.extend([hung, nxt])
    worker = _worker(hung, _LiveProc(), temporary=False)
    worker["last_event_at"] = time.monotonic() - 3000
    app.workers.append(worker)
    tasks_at_restart: list = []
    svc.restart_worker = MagicMock(side_effect=lambda w: tasks_at_restart.append(w["task"]))
    svc._dispatch_command_async = MagicMock()

    svc._poll_once()

    assert tasks_at_restart == [None], "the restarted worker must hold no job"
    assert nxt.status == "waiting", "the next job waits for a healthy worker"
    svc._dispatch_command_async.assert_not_called()


def test_dispatch_clears_the_previous_attempts_note(tmp_path):
    """A retried job must not carry the last attempt's failure note into
    its own history row."""
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.history.insert_transcription.return_value = 7
    task = MockTask(status="waiting", file_path=str(tmp_path / "retry.mp3"),
                    recovery_note=HUNG_WORKER_NOTE)
    app.queue.append(task)
    worker = _worker(None, _LiveProc(), temporary=False)
    app.workers.append(worker)
    svc._dispatch_command_async = MagicMock()

    svc.dispatch_waiting()

    assert worker["task"] is task and task.status == "running"
    assert task.recovery_note == ""


def test_finishing_a_job_does_not_start_the_next_one(tmp_path):
    """Regression: dispatch belongs to App.loop(), which first checks
    _exit_waiting (the app waiting on viewer exports before closing)."""
    app = MockApp()
    app._exit_waiting = True
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    first = MockTask(start_time=time.time(), history_id=1, file_path=str(tmp_path / "a.mp3"))
    second = MockTask(status="waiting", file_path=str(tmp_path / "b.mp3"))
    app.queue.extend([first, second])
    worker = _worker(first, _LiveProc(), temporary=False)
    app.workers.append(worker)
    svc._dispatch_command_async = MagicMock()
    app.worker_events.put({
        "event": "done", "outputs": [], "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert first.status == "finished"
    assert worker["task"] is None
    assert second.status == "waiting"
    svc._dispatch_command_async.assert_not_called()


def test_cancel_during_post_steps_with_some_files_is_cancelled(tmp_path):
    """Regression: a cancel during the export steps with only some files
    written must stay "cancelled", never be recorded as "finished"."""
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.history.finish_transcription.return_value = True
    task = MockTask(start_time=time.time(), history_id=1, status="cancelled",
                    cancelled=True, file_path=str(tmp_path / "test.mp3"))
    app.workers.append(_worker(task, None))
    srt_path = tmp_path / "test.srt"
    srt_path.write_text("partial", encoding="utf-8")
    app.worker_events.put({
        "event": "done", "outputs": [str(srt_path)],
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "cancelled"
    assert app.history.finish_transcription.call_args.kwargs["status"] == "cancelled"


def test_app_closes_while_worker_runs():
    app = MockApp()
    app._closing = True
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time(), history_id=1)
    app.workers.append(_worker(task, _LiveProc(), stdin_lock=threading.Lock()))
    svc._locked_stdin_write = MagicMock()

    svc.stop_all(cancel_running=True)

    calls = svc._locked_stdin_write.call_args_list
    assert len(calls) >= 2, f"expected cancel then shutdown, got {len(calls)}"
    assert "cancel" in calls[-2][0][1]
    assert "shutdown" in calls[-1][0][1]


def test_events_arrive_out_of_order():
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time(), history_id=1)
    app.workers.append(_worker(task, None))
    app.worker_events.put({
        "event": "progress", "percent": 50, "task_id": "u1234",
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.progress == 0, "an event for another task must not update this one"


# A failed job keeps its reason: the Queue shows it on the selected row (error_reason,
# in the UI language) and the history row stores it (recovery_note). Before, both were
# blank and the row said only "error" (click-through test, 2026-10-21).

def test_a_worker_error_keeps_its_reason(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time(), history_id=1,
                    file_path=str(tmp_path / "talk.mp3"))
    app.workers.append(_worker(task, _LiveProc()))
    app.worker_events.put({
        "event": "error", "message": "CUDA out of memory",
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "error"
    assert "CUDA out of memory" in task.error_reason
    assert app.history.finish_transcription.call_args.kwargs["error"] == "CUDA out of memory"


def test_a_file_that_is_not_media_is_named_as_such(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time(), history_id=1,
                    file_path=str(tmp_path / "README.md"))
    app.workers.append(_worker(task, _LiveProc()))
    app.worker_events.put({
        "event": "error", "message": "[Errno 1094995529] Invalid data found when processing input",
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.error_reason.startswith("README.md could not be read as audio or video")


def test_a_crashed_worker_says_so(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time(), history_id=1, output_formats=["srt"],
                    file_path=str(tmp_path / "talk.mp3"))
    app.workers.append(_worker(task, _DeadProc()))
    app.worker_events.put({
        "event": "worker_exit", "return_code": -9, "_pid": 1234,
        "_worker_id": 1, "_token": "test-token",
    })

    svc._poll_once()

    assert task.status == "error"
    assert "-9" in task.error_reason
    assert "-9" in app.history.finish_transcription.call_args.kwargs["error"]


def test_a_hung_worker_gives_a_reason(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    task = MockTask(start_time=time.time() - 3000, history_id=2,
                    file_path=str(tmp_path / "test2.mp3"))
    worker = _worker(task, _LiveProc())
    worker["last_event_at"] = time.monotonic() - 3000
    app.workers.append(worker)
    svc.restart_worker = MagicMock()

    svc._poll_once()

    assert "stopped responding" in task.error_reason


def test_dispatch_clears_the_previous_reason(tmp_path):
    app = MockApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.history.insert_transcription.return_value = 7
    task = MockTask(status="waiting", file_path=str(tmp_path / "retry.mp3"),
                    error_reason="old reason")
    app.queue.append(task)
    app.workers.append(_worker(None, _LiveProc(), temporary=False))
    svc._dispatch_command_async = MagicMock()

    svc.dispatch_waiting()

    assert task.error_reason == ""
