"""Worker failures remain observable even when ordinary error reporting breaks."""
from __future__ import annotations

import io
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from core import worker, failure_clue
from tests.core.test_worker_error_outputs import _run


@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_task_baseexception_reports_class_and_phase(monkeypatch, capsys, exc):
    def fail(task, *args, **kwargs):
        task._failure_site = "worker.segments"
        task.output_paths = ["kept.srt"]
        raise exc

    errors = [e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["failure_site"] == "worker.segments"
    assert errors[0]["diag"]["cls"] == type(exc).__name__
    assert errors[0]["outputs"] == ["kept.srt"]


def test_unprintable_exception_still_reports_original_family(monkeypatch, capsys):
    class Unprintable(RuntimeError):
        def __str__(self):
            raise MemoryError()

    def fail(task, *args, **kwargs):
        task._failure_site = "worker.prepare"
        raise Unprintable()

    errors = [e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["exception_family"] == "RuntimeError"
    assert errors[0]["failure_site"] == "worker.prepare"


def test_top_level_failure_is_reported(monkeypatch, capsys):
    def fail():
        raise MemoryError("UserUniqueName.wav")

    monkeypatch.setattr(worker, "_main", fail)
    assert worker.main() == 1
    errors = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert errors[-1]["event"] == "error"
    assert errors[-1]["exception_family"] == "MemoryError"
    assert "useruniquename" not in str(errors[-1]["diag"])


def test_stdin_thread_failure_is_reported_and_returns_nonzero(monkeypatch, capsys):
    class BrokenInput:
        def read(self, count):
            raise UnicodeError("private input")

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(sys, "stdin", BrokenInput())
    assert worker.main() == 1
    errors = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if json.loads(line)["event"] == "error"]
    assert errors and errors[0]["exception_family"] == "UnicodeError"


def test_broken_stdout_reports_closed_fields_on_stderr(monkeypatch, capsys):
    def fail(task, *args, **kwargs):
        task._failure_site = "worker.features"
        raise MemoryError("private-secret.wav")

    real_emit = worker.emit

    def emit(event, **payload):
        if event == "error":
            raise OSError("stdout write failed")
        return real_emit(event, **payload)

    monkeypatch.setattr(worker, "emit", emit)
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action":"transcribe","file_path":"private.wav"}\n'))
    worker.main()
    stderr = capsys.readouterr().err
    records = [json.loads(line) for line in stderr.splitlines() if line.startswith('{"event":')]
    assert records and records[0]["exception_family"] == "MemoryError"
    assert records[0]["failure_site"] == "worker.features"
    assert records[0]["file_path"] == "private.wav"
    assert "private" not in str({k: v for k, v in records[0].items() if k != "file_path"})


def test_background_thread_baseexception_uses_worker_protocol(monkeypatch, capsys):
    def fail():
        raise SystemExit(1)

    def main():
        thread = threading.Thread(target=fail)
        thread.start()
        thread.join()
        return 0

    monkeypatch.setattr(worker, "_main", main)
    worker.main()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(e["event"] == "error" and e["diag"]["cls"] == "SystemExit" for e in events)


@pytest.mark.parametrize("lines,family,code", [
    (["MemoryError: private input.wav"], "MemoryError", "none"),
    (['  File "C:/private/faster_whisper/transcribe.py", line 15, in generate_segments',
      "RuntimeError: CUDA failed with error out of memory"], "RuntimeError", "cuda_out_of_memory"),
    (["terminate called after throwing an instance of 'std::bad_alloc'",
      "  what():  std::bad_alloc"], "RuntimeError", "ct2_bad_alloc"),
    (["RuntimeError: C:/private/CUDA failed with error out of memory.wav"], "RuntimeError", "none"),
    (["C:/private/MemoryError.wav", "private code 1"], "other", "none"),
])
def test_stderr_classifier_keeps_only_registered_values(lines, family, code):
    result = failure_clue.stderr_clue(lines)
    assert result["exception_family"] == family
    assert result["observed_code"] == code
    assert "private" not in str(result)


def test_parent_attaches_stderr_clue_to_exit_row(monkeypatch):
    from app.services import transcription_service as ts
    from core import _threads
    from tests.core.test_worker_lifecycle_c251b import _app

    app = _app()
    service = ts.TranscriptionService(app)
    process = SimpleNamespace(pid=4242, stdout=iter(["MemoryError: private.wav\n"]), wait=lambda: 1)
    monkeypatch.setattr(ts.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    monkeypatch.setattr(service, "_engine_snapshot", lambda: {})
    service.start_worker()
    events = []
    while not app.worker_events.empty():
        events.append(app.worker_events.get_nowait())
    exited = next(e for e in events if e["event"] == "worker_exit")
    task = SimpleNamespace()
    ts._remember_failure_clue(task, app.workers[0], event=exited,
                              site="parent.worker_exit", exit_code=1)
    assert task.failure_clue["exception_family"] == "MemoryError"
    assert task.failure_clue["failure_site"] == "parent.worker_exit"
    assert task.failure_clue["exit_code"] == "1"
    assert "private" not in str(task.failure_clue)


def test_broken_command_queue_reports_instead_of_hanging(monkeypatch, capsys):
    class BrokenQueue:
        def put(self, command):
            raise MemoryError()

        def get(self, **kwargs):
            raise worker.queue.Empty()

    monkeypatch.setattr(worker.queue, "Queue", BrokenQueue)
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action":"shutdown"}\n'))
    assert worker.main() == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(e.get("exception_family") == "MemoryError" for e in events)


def test_diagnostic_allocation_failure_keeps_minimal_error(monkeypatch, capsys):
    from core import diagnostic

    def unavailable(*a, **k):
        raise MemoryError()

    monkeypatch.setattr(diagnostic, "build", unavailable)

    def fail(task, *a, **k):
        task._failure_site = "worker.output"
        raise RuntimeError("failed")

    errors = [e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error"]
    assert errors[0]["failure_site"] == "worker.output"
    assert errors[0]["exception_family"] == "RuntimeError"


def test_stderr_fallback_keeps_written_outputs_for_parent_salvage(monkeypatch, capsys):
    def broken_emit(*args, **kwargs):
        raise OSError("stdout write failed")

    monkeypatch.setattr(worker, "emit", broken_emit)
    task = SimpleNamespace(output_paths=["result.srt"], _failure_site="worker.output")
    worker._report_error(RuntimeError("late failure"), task, task_id="task-1")
    event = json.loads(capsys.readouterr().err)
    assert event["outputs"] == ["result.srt"] and event["task_id"] == "task-1"
    assert "result.srt" not in str(event["diag"])


def test_cancel_done_delivery_error_keeps_outputs(monkeypatch, capsys):
    def broken_done(*a, **k):
        raise OSError("delivery failed")

    monkeypatch.setattr(worker, "_emit_done", broken_done)

    def fail(task, *args, **kwargs):
        task.cancelled = True
        task.output_paths = ["result.srt"]
        raise RuntimeError("stopped after writing")

    errors = [e for e in _run(monkeypatch, capsys, fail) if e["event"] == "error"]
    assert errors[0]["outputs"] == ["result.srt"]
