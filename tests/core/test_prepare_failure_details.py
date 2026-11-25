"""Prepare failures keep their concrete cause; terminal tasks are not retried."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from core import failure_clue, transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, endpoint_case, install_model, output_task,
)


def test_failed_probe_reports_called_process_family(monkeypatch, tmp_path):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"invalid media")
    monkeypatch.setattr(tr.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="", stderr="Invalid data found when processing input"))
    with pytest.raises(RuntimeError) as caught:
        tr.get_duration(str(audio))
    clue = failure_clue.worker_clue(caught.value)
    assert clue["failure_site"] == "worker.prepare"
    assert clue["exception_family"] == "subprocess.CalledProcessError"
    assert "invalid media" not in str(clue)


def test_transcription_continues_after_duration_probe_times_out(monkeypatch, endpoint_case):
    attempts = []

    def timeout(cmd, **kwargs):
        attempts.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(tr, "get_duration", _REAL_GET_DURATION)
    monkeypatch.setattr(tr, "subprocess", SimpleNamespace(
        DEVNULL=subprocess.DEVNULL, CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        run=timeout, TimeoutExpired=subprocess.TimeoutExpired,
    ))
    monkeypatch.setattr(tr, "require_audio_stream", lambda path: pytest.fail("repeated slow probe"))
    install_model(monkeypatch, [Segment(0.2, 1.0, "kept text")])
    task = output_task(endpoint_case)
    notes = []
    tr.transcribe(task, log_cb=notes.append)
    assert len(attempts) == 1
    assert any("timed out" in note and "Continuing" in note for note in notes)
    assert endpoint_case.writes[-1][0]["text"] == "kept text"


_REAL_GET_DURATION = tr.get_duration
def test_invalid_prepare_override_keeps_value_error_family(monkeypatch):
    monkeypatch.setattr(tr, "config", {"diarization_enabled": "unusable"})
    monkeypatch.setattr(tr, "load_config", lambda: {})
    from core import config
    monkeypatch.setattr(config, "load_project_overrides", lambda path: {})
    task = SimpleNamespace(file_path="fake.wav", _failure_site="worker.prepare")
    with pytest.raises(RuntimeError) as caught:
        tr._apply_runtime_overrides(task)
    clue = failure_clue.worker_clue(caught.value, task)
    assert clue["exception_family"] == "ValueError"
    assert clue["failure_site"] == "worker.prepare"


def test_prepare_error_is_terminal_across_dispatch_ticks(monkeypatch):
    from app.services import transcription_service as ts
    from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

    app = _app()
    service = _svc(app)
    task = SimpleNamespace(status="running", file_path="input.wav", cancelled=False,
                           recovery_note="", error_reason="")
    worker = {"id": 1, "token": "tok1", "ready": True, "task": task,
              "process": _Alive(), "device": "cpu", "last_event_at": 0}
    app.workers, app.queue = [worker], [task]
    finished = []

    def finish(w, **kwargs):
        finished.append(w["task"])
        w["task"] = None

    monkeypatch.setattr(service, "finish_task", finish)
    app.worker_events.put({"event": "error", "_pid": 4242, "_worker_id": 1, "_token": "tok1",
                           "message": "ffprobe failed", "failure_site": "worker.prepare",
                           "exception_family": "RuntimeError"})
    service.poll()
    for _ in range(4):
        service.dispatch_waiting()
    assert task.status == "error" and finished == [task]
    assert worker["task"] is None
