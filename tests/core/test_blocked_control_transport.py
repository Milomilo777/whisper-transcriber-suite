"""A full command pipe cannot keep cancellation queued indefinitely."""
import threading
import time
from queue import Queue
from types import SimpleNamespace
from app.services.transcription_service import TranscriptionService
from core.task import TranscriptionTask


def test_blocked_body_cancel_has_bounded_recovery_without_waiting_on_ui(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class Pipe:
        def write(self, message):
            entered.set()
            assert release.wait(3)
            raise BrokenPipeError("retired transport")
        def flush(self):
            pass
    task = TranscriptionTask("fixture.wav")
    task.status = "cancelled"
    checkpoint = tmp_path / "checkpoint"
    checkpoint.write_text("saved prefix", encoding="utf-8")
    process = SimpleNamespace(stdin=Pipe(), pid=1234, poll=lambda: None)
    worker = {"id": 1, "task": task, "process": process, "stdin_lock": threading.Lock(), "last_event_at": time.monotonic()}
    app = SimpleNamespace(workers=[worker], worker_events=Queue(), log=lambda msg: None, after=lambda *a: None)
    service = TranscriptionService(app)
    service.CANCEL_SEND_TIMEOUT_S = .05
    retired = []
    def retire(w):
        retired.append(w)
        app.workers.remove(w)
        w["process"] = None
        release.set()
    monkeypatch.setattr(service, "retire_worker", retire)
    service._dispatch_command_async(worker, task, {"action": "transcribe", "task_id": "blocked", "body": "x" * 70000})
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert service.send_control(task, "cancel")
        assert time.monotonic() - started < .1
        time.sleep(.08)
        started = time.monotonic()
        service.poll()
        assert time.monotonic() - started < .1
        assert retired == [worker], "Cancel remains queued behind a blocked body"
        assert task.status == "cancelled"
        assert checkpoint.read_text(encoding="utf-8") == "saved prefix"
    finally:
        release.set()
        cv = worker.get("send_cv")
        if cv is not None:
            with cv:
                assert cv.wait_for(lambda: worker.get("send_next") == 2, timeout=2)


def test_stale_or_completed_cancel_cannot_retire_a_reused_worker(monkeypatch):
    for state in ("new-process", "new-task", "sent", "within-deadline"):
        task = TranscriptionTask("fixture.wav")
        process = SimpleNamespace(pid=1234)
        sent = threading.Event()
        pending = {"process": process, "task": task, "sent": sent, "started": 10.}
        worker = {"id": 1, "task": task, "process": process, "pending_cancel_send": pending}
        app = SimpleNamespace(workers=[worker], log=lambda msg: None)
        service = TranscriptionService(app)
        retired = []
        monkeypatch.setattr(service, "retire_worker", lambda w: retired.append(w))
        if state == "new-process":
            worker["process"] = SimpleNamespace(pid=1234)  # PID reuse is not ownership.
        elif state == "new-task":
            worker["task"] = TranscriptionTask("next.wav")
        elif state == "sent":
            sent.set()
        service._expire_blocked_cancels(11. if state == "within-deadline" else 100.)
        assert retired == []
        if state == "within-deadline":
            assert worker["pending_cancel_send"] is pending
        else:
            assert "pending_cancel_send" not in worker


def test_repeated_cancel_retains_first_transport_deadline(monkeypatch):
    pending_threads = []
    class Deferred:
        def __init__(self, target, **kwargs):
            pending_threads.append(target)
        def start(self):
            pass
    monkeypatch.setattr(threading, "Thread", Deferred)
    task = TranscriptionTask("fixture.wav")
    worker = {"id": 1, "task": task, "process": SimpleNamespace(pid=1234)}
    service = TranscriptionService(SimpleNamespace(workers=[worker]))
    assert service.send_control(task, "cancel")
    original = worker["pending_cancel_send"]
    original["started"] = 1.
    assert service.send_control(task, "cancel")
    assert worker["pending_cancel_send"] is original
    assert original["started"] == 1.
    assert len(pending_threads) == 2


def test_failed_cancel_write_retains_bounded_retirement(monkeypatch):
    class Broken:
        def write(self, message):
            raise BrokenPipeError("synthetic failed control")
        def flush(self):
            pass
    task = TranscriptionTask("fixture.wav")
    task.status = "cancelled"
    worker = {"id": 1, "task": task, "process": SimpleNamespace(pid=1234, stdin=Broken()), "stdin_lock": threading.Lock()}
    app = SimpleNamespace(workers=[worker], log=lambda msg: None)
    service = TranscriptionService(app)
    retired = []
    monkeypatch.setattr(service, "retire_worker", lambda w: retired.append(w))
    assert service.send_control(task, "cancel")
    cv = worker["send_cv"]
    with cv:
        assert cv.wait_for(lambda: worker.get("send_next") == 1, timeout=1)
    pending = worker["pending_cancel_send"]
    assert not pending["sent"].is_set()
    service._expire_blocked_cancels(pending["started"] + service.CANCEL_SEND_TIMEOUT_S + 1)
    assert retired == [worker]
