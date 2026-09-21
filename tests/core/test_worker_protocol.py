"""Tests for the worker JSON protocol — without spawning a subprocess.

We exercise ``core.worker.emit`` for serialization, then drive ``main()`` with
patched stdin/stdout and a stub transcriber to verify the event sequence.
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from core import worker


def test_emit_serializes_event_and_payload(capsys):
    worker.emit("ready")
    line = capsys.readouterr().out.strip()
    parsed = json.loads(line)
    assert parsed == {"event": "ready"}


def test_emit_includes_extra_fields(capsys):
    worker.emit("progress", percent=42, message="hi")
    parsed = json.loads(capsys.readouterr().out.strip())
    assert parsed == {"event": "progress", "percent": 42, "message": "hi"}


def test_emit_progress_payload_keys(capsys):
    worker.emit("done", file_path="/tmp/x.wav")
    parsed = json.loads(capsys.readouterr().out.strip())
    assert parsed["event"] == "done"
    assert parsed["file_path"] == "/tmp/x.wav"


def test_main_emits_startup_error_when_model_missing(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = worker.main()
    assert rc == 1
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert any(e["event"] == "startup_error" for e in events)


def test_main_emits_ready_then_handles_shutdown(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "shutdown"}) + "\n"))
    rc = worker.main()
    assert rc == 0
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert events[0]["event"] == "ready"


def test_main_survives_logging_setup_failure(monkeypatch, capsys):
    """A locked / unwritable log directory must not kill the worker before
    it emits a single protocol event: logging is best-effort, stdout is the
    contract."""
    def boom(*args, **kwargs):
        raise PermissionError("log dir locked by antivirus")

    monkeypatch.setattr(worker, "setup_logging", boom)
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "shutdown"}) + "\n"))
    assert worker.main() == 0
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert events and events[0]["event"] == "ready"


def test_main_emits_startup_error_when_model_load_raises(monkeypatch, capsys):
    """A raise from load_existing_model must surface as startup_error, not
    as a bare crash the parent can only observe as a silent worker_exit."""
    def boom(cb):
        raise RuntimeError("model dir vanished")

    monkeypatch.setattr(worker, "load_existing_model", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = worker.main()
    assert rc == 1
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    errs = [e for e in events if e["event"] == "startup_error"]
    assert len(errs) == 1
    assert "model dir vanished" in errs[0]["message"]
    assert not any(e["event"] == "ready" for e in events)


def test_ready_event_carries_effective_device_fields(monkeypatch, capsys):
    """R3: the ready event additively reports the effective device."""
    from core import transcriber as _t

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(
        worker, "get_effective_device",
        lambda: _t.EffectiveDevice(
            device="cpu", compute_type="int8",
            requested_device="cuda", downgraded=True,
        ),
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "shutdown"}) + "\n"))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    ready = next(e for e in events if e["event"] == "ready")
    assert ready["device"] == "cpu"
    assert ready["compute_type"] == "int8"
    assert ready["requested_device"] == "cuda"
    assert ready["downgraded"] is True


def test_ready_event_backward_compatible_parser_ignores_new_fields(monkeypatch, capsys):
    """An OLD parser that only checks event type still works (additive proof)."""
    from core import transcriber as _t

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(
        worker, "get_effective_device",
        lambda: _t.EffectiveDevice(
            device="cuda", compute_type="float16",
            requested_device="cuda", downgraded=False,
        ),
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "shutdown"}) + "\n"))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    # A naive parser that only switches on event type sees a valid "ready".
    assert any(e.get("event") == "ready" for e in events)


def test_ready_falls_back_to_bare_ready_if_probe_raises(monkeypatch, capsys):
    """If get_effective_device blows up, the essential bare ready still fires."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)

    def _boom():
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(worker, "get_effective_device", _boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "shutdown"}) + "\n"))
    rc = worker.main()
    assert rc == 0
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert any(e.get("event") == "ready" for e in events)


def test_main_rejects_invalid_json_command(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    inputs = "not-json\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    rc = worker.main()
    assert rc == 0
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    error_events = [e for e in events if e["event"] == "error"]
    assert error_events and "Invalid worker command" in error_events[0]["message"]


def test_main_rejects_missing_file_path(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    inputs = json.dumps({"action": "transcribe"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    error_events = [e for e in events if e["event"] == "error"]
    assert error_events and "Missing input file" in error_events[0]["message"]


def test_main_emits_started_then_done_on_transcribe(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", lambda task, p, l, language_cb=None: None)
    inputs = json.dumps({"action": "transcribe", "file_path": "/tmp/x.wav"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    started = [e for e in events if e["event"] == "started"]
    done = [e for e in events if e["event"] == "done"]
    assert started and done
    assert started[0]["file_path"] == "/tmp/x.wav"


def test_main_done_event_includes_written_outputs(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)

    def fake_transcribe(task, p, l, language_cb=None):
        task.output_paths = ["/tmp/x.srt", "/tmp/x.docx"]

    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    inputs = json.dumps({"action": "transcribe", "file_path": "/tmp/x.wav"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    done = [e for e in events if e["event"] == "done"]
    assert done and done[0].get("outputs") == ["/tmp/x.srt", "/tmp/x.docx"]


def test_main_unknown_action_emits_error(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    inputs = json.dumps({"action": "fly-to-the-moon"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    error_events = [e for e in events if e["event"] == "error"]
    assert error_events and "Unknown worker command" in error_events[0]["message"]


def test_main_catches_transcribe_exception(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    def boom(*a, **k):
        raise RuntimeError("decode failed")
    monkeypatch.setattr(worker, "transcribe", boom)
    inputs = json.dumps({"action": "transcribe", "file_path": "/tmp/x.wav"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    error_events = [e for e in events if e["event"] == "error"]
    assert error_events and "decode failed" in error_events[0]["message"]


def test_main_rejects_oversize_command(monkeypatch, capsys):
    """Audit P2-20: a stdin line past MAX_COMMAND_BYTES is dropped with an
    error and never starts a task (OOM / runaway-parent guard)."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(
        worker, "transcribe",
        lambda *a, **k: pytest.fail("oversize command must not run a task"),
    )
    # MAX_COMMAND_BYTES is a 1 MB local in worker.main(); exceed it.
    huge = "x" * ((1 << 20) + 10) + "\n"
    inputs = huge + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    errs = [e for e in events if e["event"] == "error"]
    assert errs and "exceeds max length" in errs[0]["message"]
    assert not any(e["event"] == "started" for e in events)


def test_main_clip_disables_resume(monkeypatch, capsys):
    """Audit P2-20: a clipped request must NOT resume a whole-file
    checkpoint (resuming would transcribe past clip_end)."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(
        worker, "resume_transcription",
        lambda *a, **k: pytest.fail("a clipped run must not call resume_transcription"),
    )
    ran = {"transcribe": False}

    def fake_transcribe(task, p, l, language_cb=None):
        ran["transcribe"] = True

    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    cmd = {
        "action": "transcribe", "file_path": "/tmp/x.wav",
        "clip_start": 10, "clip_end": 20, "resume": True,
    }
    inputs = json.dumps(cmd) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    assert ran["transcribe"] is True  # full path ran, resume did not
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert any(e["event"] == "done" for e in events)
