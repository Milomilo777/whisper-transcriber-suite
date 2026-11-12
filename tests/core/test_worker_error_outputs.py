"""The worker's ``error`` event carries the files already written, so the
parent can keep a finished transcript when a late step fails."""
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


def test_error_after_outputs_written_reports_them(monkeypatch, capsys):
    def fake(task, progress_cb, log_cb, language_cb=None):
        task.output_paths = ["/tmp/x.srt", "/tmp/x.json"]
        raise RuntimeError("late step failed")

    errs = [e for e in _run(monkeypatch, capsys, fake) if e["event"] == "error"]
    assert len(errs) == 1
    assert errs[0]["outputs"] == ["/tmp/x.srt", "/tmp/x.json"]
    assert "late step failed" in errs[0]["message"]


def test_error_before_any_output_carries_no_outputs_field(monkeypatch, capsys):
    def fake(task, progress_cb, log_cb, language_cb=None):
        raise RuntimeError("model exploded")

    errs = [e for e in _run(monkeypatch, capsys, fake) if e["event"] == "error"]
    assert len(errs) == 1 and "outputs" not in errs[0]


def test_failed_export_recovery_is_reported_as_error_not_successful_output(monkeypatch, capsys, tmp_path):
    from pathlib import Path
    from core import _checkpoint, transcriber
    blocked = tmp_path / "exports"
    blocked.write_bytes(b"unrelated file blocks export directory")
    segments = [{"start": 30.0, "end": 32.0, "text": "completed clip"}]
    def fake(task, progress_cb, log_cb, language_cb=None):
        task.output_paths = transcriber._write_outputs(
            str(blocked / "clip"), segments, task.file_path, ["json"])
    events = _run(monkeypatch, capsys, fake)
    errors = [event for event in events if event["event"] == "error"]
    assert len(errors) == 1 and "outputs" not in errors[0]
    assert not any(event["event"] == "done" for event in events)
    saved, = (_checkpoint.user_data_dir() / "transcript-recovery").glob("output-*.json")
    assert str(saved) in errors[0]["message"]
    assert json.loads(Path(saved).read_text(encoding="utf-8"))["segments"] == segments
    assert blocked.read_bytes() == b"unrelated file blocks export directory"
