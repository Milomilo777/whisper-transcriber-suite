"""Controls for one worker reach its stdin in the order they were sent.

Each cancel/pause/resume (and the transcribe dispatch) is written from its
own daemon thread. The per-worker stdin lock keeps the JSON lines whole but
does not order the threads: a pause thread delayed before taking the lock
let a quick resume overtake it, so the worker ended paused while the window
said running. A write order taken on the calling thread fixes that.

Hermetic: a fake stdin records the lines; the delay stands in for the
scheduler.
"""
from __future__ import annotations

import io
import json
import threading
import time
import types

import pytest

from app.services.transcription_service import TranscriptionService
from core import worker as core_worker
from core.task import TranscriptionTask


def _service_with_fake_stdin() -> tuple[TranscriptionService, dict, io.StringIO, TranscriptionTask]:
    t = TranscriptionTask("clip.mp4")
    t.history_id = 7
    buf = io.StringIO()
    proc = types.SimpleNamespace(stdin=buf, pid=1234, poll=lambda: None)
    worker = {"id": 1, "task": t, "process": proc, "stdin_lock": threading.Lock()}
    service = TranscriptionService(types.SimpleNamespace(workers=[worker]))  # type: ignore[arg-type]
    return service, worker, buf, t


def _lines(buf: io.StringIO, n: int, timeout: float = 3.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        lines = [json.loads(s) for s in buf.getvalue().splitlines() if s.strip()]
        if len(lines) >= n:
            return lines
        time.sleep(0.01)
    raise AssertionError(f"expected {n} lines, got: {buf.getvalue()!r}")


def _delay_writes_containing(monkeypatch, word: str, seconds: float) -> None:
    real = TranscriptionService._locked_stdin_write

    def _slow(worker, msg):
        if word in msg:
            time.sleep(seconds)  # the pause thread loses its time slice before the lock
        real(worker, msg)

    monkeypatch.setattr(TranscriptionService, "_locked_stdin_write", staticmethod(_slow))


def test_pause_then_resume_reach_the_worker_in_that_order(monkeypatch):
    service, worker, buf, t = _service_with_fake_stdin()
    _delay_writes_containing(monkeypatch, '"pause"', 0.15)

    assert service.send_control(t, "pause") is True
    assert service.send_control(t, "resume") is True

    actions = [line["action"] for line in _lines(buf, 2)]
    assert actions == ["pause", "resume"]

    # Applied in that order, the user's last word (resume) wins.
    for action in actions:
        core_worker._apply_control_flag(t, action)
    assert t.paused is False


def test_a_transcribe_dispatch_precedes_a_control_sent_right_after(monkeypatch):
    service, worker, buf, t = _service_with_fake_stdin()
    _delay_writes_containing(monkeypatch, '"transcribe"', 0.15)
    service._dispatch_command_async(worker, t, {"action": "transcribe", "task_id": "h7"})
    assert service.send_control(t, "cancel") is True

    actions = [line["action"] for line in _lines(buf, 2)]
    assert actions == ["transcribe", "cancel"]


def test_a_failed_earlier_write_does_not_block_the_next_one(monkeypatch):
    service, worker, buf, t = _service_with_fake_stdin()
    real = TranscriptionService._locked_stdin_write

    def _first_fails(w, msg):
        if '"pause"' in msg:
            raise OSError("broken pipe")
        real(w, msg)

    monkeypatch.setattr(TranscriptionService, "_locked_stdin_write", staticmethod(_first_fails))
    service.send_control(t, "pause")
    service.send_control(t, "resume")
    assert [line["action"] for line in _lines(buf, 1)] == ["resume"]


def test_a_worker_dict_without_the_order_fields_still_writes():
    """Older worker dicts (tests, shadow dicts of retiring workers) carry
    only the stdin lock."""
    service, worker, buf, t = _service_with_fake_stdin()
    assert "send_cv" not in worker
    service.send_control(t, "cancel")
    assert [line["action"] for line in _lines(buf, 1)] == ["cancel"]


def test_a_writer_thread_that_never_starts_does_not_block_the_next_command(monkeypatch):
    service, worker, buf, t = _service_with_fake_stdin()
    real_start = threading.Thread.start
    calls = {"n": 0}

    def _start(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _start)
    with pytest.raises(RuntimeError):
        service._send_command_async(worker, {"action": "pause", "task_id": "h7"})
    service._send_command_async(worker, {"action": "cancel", "task_id": "h7"})
    assert [line["action"] for line in _lines(buf, 1)] == ["cancel"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
