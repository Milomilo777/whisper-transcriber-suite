"""Bound stderr parsing and keep exit clues local to the job that produced them."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core import failure_clue


def start_reader(monkeypatch, lines):
    from app.services import transcription_service as ts
    from core import _threads
    from tests.core.test_worker_lifecycle_c251b import _app

    app = _app()
    service = ts.TranscriptionService(app)
    process = SimpleNamespace(pid=4242, stdout=iter(lines), wait=lambda: 1)
    monkeypatch.setattr(ts.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kw: target())
    monkeypatch.setattr(service, "_engine_snapshot", lambda: {})
    service.start_worker()
    events = []
    while not app.worker_events.empty():
        events.append(app.worker_events.get_nowait())
    return app.workers[0], events


@pytest.mark.parametrize("terminal", ["done", "error", "live_result", "live_error"])
def test_terminal_event_clears_stderr_before_next_job_starts(monkeypatch, terminal):
    worker, events = start_reader(monkeypatch, [
        "MemoryError: old job\n", json.dumps({"event": terminal}) + "\n",
    ])
    # The next job can die before it has a chance to emit 'started'.
    exited = next(e for e in events if e["event"] == "worker_exit")
    assert "exception_family" not in exited
    assert not worker.get("stderr_clue")


def test_oversize_line_is_bounded_before_json_parse(monkeypatch):
    from app.services import transcription_service as ts

    loads = ts.json.loads
    sizes = []

    def load(line):
        sizes.append(len(line))
        assert len(line) <= 1 << 20
        return loads(line)

    monkeypatch.setattr(ts.json, "loads", load)
    _, events = start_reader(monkeypatch, ['{"event":"done","value":"' + "x" * (2 << 20) + '"}\n'])
    assert not sizes
    assert events[0]["event"] == "log" and len(events[0]["message"]) <= 1 << 20


def test_json_object_line_keeps_e27f18de_protocol_behavior(monkeypatch):
    record = {"event": "done", "file_path": "input.wav"}
    _, events = start_reader(monkeypatch, [json.dumps(record) + "\n"])
    assert events[0].items() >= record.items()


def test_stderr_library_evidence_must_be_a_traceback_frame():
    clue = failure_clue.stderr_clue([
        'Processing file "/private/numpy/foo.py"',
        "RuntimeError: CUDA failed with error out of memory",
    ])
    assert clue["observed_code"] == "none"


def test_stderr_library_evidence_does_not_cross_tracebacks():
    clue = failure_clue.stderr_clue([
        'File "C:/libs/faster_whisper/transcribe.py", line 15, in generate_segments',
        "RuntimeError: unrelated warning",
        "Traceback (most recent call last):",
        'File "C:/private/input.py", line 10, in process',
        "RuntimeError: CUDA failed with error out of memory",
    ])
    assert clue["observed_code"] == "none"


def test_stderr_accepts_nested_library_frame():
    clue = failure_clue.stderr_clue([
        'File "C:/libs/faster_whisper/transcribe/decode.py", line 15, in generate_segments',
        "RuntimeError: CUDA failed with error out of memory",
    ])
    assert clue["observed_code"] == "cuda_out_of_memory"


def test_later_python_exception_replaces_earlier_native_allocation_failure():
    clue = failure_clue.stderr_clue([
        "terminate called after throwing an instance of 'std::bad_alloc'",
        "  what():  std::bad_alloc",
        "PermissionError: later failure",
    ])
    assert clue["exception_family"] == "PermissionError" and clue["observed_code"] == "none"


def test_truncation_cannot_create_a_complete_stderr_exception():
    message = "Unable to allocate 2 GiB for an array with shape (" + "1," * 900
    prefix = message + "0) and data type float32"
    # Pad the array dimensions so the full, apparently valid prefix ends at the cap.
    prefix = prefix.replace("(1,", "(" + " " * max(0, 2048 - len("MemoryError: " + prefix)) + "1,", 1)
    assert len("MemoryError: " + prefix) == 2048
    clue = failure_clue.stderr_clue([
        'File "C:/libs/numpy/allocate.py", line 15, in allocate',
        "MemoryError: " + prefix + " private trailing text",
    ])
    assert clue["observed_code"] == "none"
