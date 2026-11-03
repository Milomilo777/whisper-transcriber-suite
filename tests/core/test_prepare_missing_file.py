"""A vanished source gets the existing file-not-found notice."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import failure_clue, transcriber as tr


def test_missing_source_is_file_not_found_before_probe(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("A missing source must be reported before launching ffprobe")

    monkeypatch.setattr(tr.subprocess, "run", forbidden)
    with pytest.raises(FileNotFoundError) as caught:
        tr.get_duration(str(tmp_path / "gone.wav"))
    clue = failure_clue.worker_clue(caught.value)
    assert clue["observed_code"] == "file_not_found"
    assert clue["failure_site"] == "worker.prepare"


def test_missing_prepare_file_uses_existing_plain_notice(monkeypatch):
    from tests.core.test_worker_lifecycle_c251b import _Alive, _app, _svc

    app = _app()
    service = _svc(app)
    task = SimpleNamespace(status="running", file_path="gone.wav", cancelled=False,
                           recovery_note="", error_reason="")
    worker = {"id": 1, "token": "tok1", "ready": True, "task": task,
              "process": _Alive(), "device": "cpu", "last_event_at": 0}
    app.workers = [worker]
    monkeypatch.setattr(service, "finish_task", lambda *a, **k: None)
    app.worker_events.put({"event": "error", "_pid": 4242, "_worker_id": 1, "_token": "tok1",
                           "message": "[Errno 2] No such file: secret.wav", "failure_site": "worker.prepare",
                           "exception_family": "FileNotFoundError", "observed_code": "file_not_found"})
    service.poll()
    assert "File not found: check the path, or click Browse files..." in task.error_reason
    assert "Errno" not in task.error_reason and "secret" not in task.error_reason
