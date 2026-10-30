"""A step that raises because the user cancelled ends with ``done``, not ``error``."""
from __future__ import annotations

import io
import json
import sys

from core import worker


def _run(monkeypatch, capsys, fake_transcribe):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    inputs = (
        json.dumps({"action": "transcribe", "file_path": "/tmp/x.wav"}) + "\n"
        + json.dumps({"action": "shutdown"}) + "\n"
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_exception_after_cancel_is_reported_as_done(monkeypatch, capsys):
    def fake(task, progress_cb, log_cb, language_cb=None):
        task.cancelled = True
        raise RuntimeError("ffmpeg was stopped")

    events = _run(monkeypatch, capsys, fake)
    kinds = [e["event"] for e in events]
    assert "error" not in kinds
    done = [e for e in events if e["event"] == "done"]
    assert len(done) == 1 and done[0]["outputs"] == []


def test_exception_after_cancel_keeps_written_outputs(monkeypatch, capsys):
    def fake(task, progress_cb, log_cb, language_cb=None):
        task.output_paths = ["/tmp/x.srt"]
        task.cancelled = True
        raise RuntimeError("late step stopped")

    done = [e for e in _run(monkeypatch, capsys, fake) if e["event"] == "done"]
    assert len(done) == 1 and done[0]["outputs"] == ["/tmp/x.srt"]


def test_exception_without_cancel_is_still_an_error(monkeypatch, capsys):
    def fake(task, progress_cb, log_cb, language_cb=None):
        raise RuntimeError("model exploded")

    kinds = [e["event"] for e in _run(monkeypatch, capsys, fake)]
    assert "error" in kinds and "done" not in kinds
