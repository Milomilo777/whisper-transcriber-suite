"""A checkpoint that could only be copied (not renamed) stops the task: the
worker must not fall back to a fresh run over it.

Drives ``core.worker.main()`` with a fake stdin, like test_worker_correlation_id.
"""
from __future__ import annotations

import io
import json
import sys
import time

import pytest

from core import _checkpoint as cp
from core import worker


@pytest.fixture(autouse=True)
def _isolate_worker_state():
    worker._clear_parked_controls()
    worker._set_current_task(None)
    yield
    worker._clear_parked_controls()
    worker._set_current_task(None)


def _run(monkeypatch, resume_impl, transcribe_impl, path="x.wav"):
    events: list[dict] = []
    monkeypatch.setattr(worker, "emit", lambda event, **p: events.append({"event": event, **p}))
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "resume_transcription", resume_impl)
    monkeypatch.setattr(worker, "transcribe", transcribe_impl)
    cmd = {"action": "transcribe", "file_path": path, "resume": True, "task_id": "w1"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(cmd) + "\n"))
    assert worker.main() == 0
    deadline = time.time() + 5
    while time.time() < deadline and not any(e["event"] in ("done", "error") for e in events):
        time.sleep(0.01)
    return events


def test_in_use_checkpoint_prevents_the_fresh_fallback(monkeypatch):
    called = []

    def _resume(*_a, **_k):
        raise cp.CheckpointInUseError(
            "the checkpoint is in use or locked; the task was stopped so the saved text is not overwritten"
        )

    events = _run(monkeypatch, _resume, lambda *a, **k: called.append(1))
    assert called == []
    errors = [e for e in events if e["event"] == "error"]
    assert errors and "saved text is not overwritten" in errors[0]["message"]
    assert not any(e["event"] == "done" for e in events)


def test_a_declined_resume_still_falls_back_to_a_fresh_run(monkeypatch):
    called = []
    events = _run(monkeypatch, lambda *a, **k: False, lambda *a, **k: called.append(1))
    assert called == [1]
    assert any(e["event"] == "done" for e in events)
