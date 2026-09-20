"""Correlation-id tests for ``app.services.transcription_service``.

The parent side of the race fix: the transcribe command and the later
cancel/pause/resume must carry the SAME correlation id for a task, and the
app must handle the worker's new ack events. The final test here rebuilds the
exact bad ordering from the original bug report — a control line written
BEFORE its transcribe line, using the real parent-built command payloads —
and proves the worker now honours the control instead of dropping it.

Hermetic: no Tk, no subprocess, no model (the worker is driven with a fake
stdin and a stub transcribe).
"""
from __future__ import annotations

import io
import json
import queue
import sys
import threading
import time
import types

from app.services.transcription_service import (
    TranscriptionService,
    task_correlation_id,
    transcribe_command,
)
from core import worker as core_worker
from core.task import TranscriptionTask


def _task(history_id: int = 0) -> TranscriptionTask:
    t = TranscriptionTask("clip.mp4")
    t.history_id = history_id
    return t


def _wait_for_line(buf: io.StringIO, timeout: float = 3.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = buf.getvalue().strip()
        if text:
            return text
        time.sleep(0.01)
    raise AssertionError("control command was never written to the fake stdin")


# ---------------------------------------------------------------- id derivation


def test_correlation_id_uses_the_existing_history_id_and_caches_it():
    t = _task(history_id=9)
    assert task_correlation_id(t) == "h9"
    assert task_correlation_id(t) == "h9"
    assert t.task_id == "h9"


def test_correlation_id_falls_back_to_a_uuid_without_a_history_row():
    t = _task(history_id=0)
    cid = task_correlation_id(t)
    assert cid.startswith("u")
    assert task_correlation_id(t) == cid


def test_correlation_id_survives_a_hostile_history_id():
    t = _task(history_id=0)
    t.history_id = "not-a-number"  # type: ignore[assignment]
    assert task_correlation_id(t).startswith("u")


# ------------------------------------------------------- command id agreement


def test_transcribe_command_and_control_use_the_same_id():
    t = _task(history_id=4)
    command = transcribe_command(t)
    buf = io.StringIO()
    proc = types.SimpleNamespace(stdin=buf, pid=1234, poll=lambda: None)
    worker = {"id": 1, "task": t, "process": proc,
              "stdin_lock": threading.Lock()}
    service = TranscriptionService(
        types.SimpleNamespace(workers=[worker])  # type: ignore[arg-type]
    )

    assert service.send_control(t, "pause") is True
    control = json.loads(_wait_for_line(buf))

    assert command["task_id"] == "h4"
    assert control == {"action": "pause", "task_id": "h4"}
    # Both payloads must round-trip as JSON lines (they are written to stdin).
    json.dumps(command)


def test_send_control_returns_false_when_the_task_is_not_on_a_worker():
    t = _task(history_id=4)
    service = TranscriptionService(
        types.SimpleNamespace(workers=[])  # type: ignore[arg-type]
    )
    assert service.send_control(t, "cancel") is False
    assert t.task_id == ""  # not even an id was generated — no command was sent


# --------------------------------------------------------------- ack handling


def _poll_service(logs: list[str]):
    q: "queue.Queue[dict]" = queue.Queue()
    proc = types.SimpleNamespace(pid=4321, poll=lambda: None)
    worker = {"id": 1, "process": proc, "task": None, "ready": True,
              "last_event_at": time.time(), "token": "", "temporary": False}
    app = types.SimpleNamespace(
        worker_events=q,
        workers=[worker],
        app_config={},
        after=lambda *a, **k: None,
        log=logs.append,
    )
    service = TranscriptionService(app)  # type: ignore[arg-type]
    return service, q, worker


def test_poll_logs_an_unmatched_control_instead_of_swallowing_it():
    logs: list[str] = []
    service, q, _worker = _poll_service(logs)
    q.put({
        "event": "control_unmatched", "action": "cancel", "task_id": "h9",
        "reason": "timeout", "_worker_id": 1, "_pid": 4321,
    })

    service.poll()

    assert any("h9" in line and "cancel" in line for line in logs)


def test_poll_accepts_a_delayed_control_applied_ack():
    logs: list[str] = []
    service, q, _worker = _poll_service(logs)
    q.put({
        "event": "control_applied", "action": "pause", "task_id": "h9",
        "delayed": True, "_worker_id": 1, "_pid": 4321,
    })

    service.poll()  # must not raise

    assert logs == []  # delayed acks are debug-level only


# ------------------------------------- end-to-end bad ordering (parent payloads)


def test_control_written_before_its_transcribe_still_pauses_the_task(monkeypatch):
    """Rebuilds the reported race with the REAL parent commands: the control
    line lands on the wire first, then the transcribe line. The worker must
    park the control by id and apply it when the transcribe registers, so the
    stub transcriber sees task.paused=True on entry."""
    monkeypatch.setattr(core_worker, "load_existing_model", lambda cb: True)
    core_worker._clear_parked_controls()
    core_worker._set_current_task(None)
    seen: list[tuple[str, bool, bool]] = []

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        seen.append((task.task_id, task.paused, task.cancelled))

    monkeypatch.setattr(core_worker, "transcribe", fake_transcribe)

    t = _task(history_id=4)
    transcribe = transcribe_command(t)

    buf = io.StringIO()
    proc = types.SimpleNamespace(stdin=buf, pid=1234, poll=lambda: None)
    worker = {"id": 1, "task": t, "process": proc,
              "stdin_lock": threading.Lock()}
    service = TranscriptionService(
        types.SimpleNamespace(workers=[worker])  # type: ignore[arg-type]
    )
    assert service.send_control(t, "pause") is True
    control_line = _wait_for_line(buf)

    stdin_text = (
        control_line + "\n"
        + json.dumps(transcribe) + "\n"
        + json.dumps({"action": "shutdown"}) + "\n"
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    try:
        assert core_worker.main() == 0
    finally:
        core_worker._clear_parked_controls()
        core_worker._set_current_task(None)

    assert seen == [("h4", True, False)]
