"""Terminal delivery stays single, attributable and usable after worker failures."""
from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import failure_clue, worker
from tests.core.test_worker_error_outputs import _run


@pytest.mark.parametrize("code", [None, 0])
@pytest.mark.parametrize("stage", ["top", "load", "task", "live", "reader"])
def test_clean_system_exit_remains_success(monkeypatch, capsys, stage, code):
    def exit_cleanly(*a, **kw):
        raise SystemExit(code)

    monkeypatch.setattr(worker, "load_existing_model", exit_cleanly if stage == "load" else lambda cb: True)
    if stage == "top":
        monkeypatch.setattr(worker, "_main", exit_cleanly)
    elif stage == "task":
        monkeypatch.setattr(worker, "transcribe", exit_cleanly)
    elif stage == "live":
        from core import transcriber
        monkeypatch.setattr(transcriber, "transcribe_chunk_to_text", exit_cleanly)
    action = "transcribe_live" if stage == "live" else "transcribe"
    if stage == "reader":
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(read=exit_cleanly))
    else:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": action, "file_path": "input.wav"}) + "\n"))
    assert worker.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not any(e["event"] in {"error", "startup_error", "live_error"} for e in events)
    assert worker._current_task is None


def test_idle_helper_failure_stops_worker(monkeypatch, capsys):
    def load(cb):
        # Invoke the installed hook while the worker is idle, deterministically.
        threading.excepthook(SimpleNamespace(exc_value=RuntimeError("helper failed")))
        return True

    monkeypatch.setattr(worker, "load_existing_model", load)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action":"shutdown"}\n'))
    assert worker.main() == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len([e for e in events if e["event"] == "error"]) == 1


def test_ending_session_clears_its_background_failure():
    from core.task import TranscriptionTask

    worker._begin_session()
    worker._note_background_failure(RuntimeError("ended session"))
    worker._end_session()
    task = TranscriptionTask("input.wav")
    try:
        worker._register_task(task)
        assert not task.cancelled
        assert worker._background_failure is None
    finally:
        worker._set_current_task(None)


@pytest.mark.parametrize("reader", [False, True])
@pytest.mark.parametrize("decode_raises", [False, True])
def test_helper_failure_waits_for_saved_outputs_and_sends_one_terminal(monkeypatch, capsys, tmp_path, reader, decode_raises):
    accepted = threading.Event()
    reader_failed = threading.Event()
    terminals = []
    output = tmp_path / "kept.srt"
    real_emit = worker.emit

    def emit(event, **payload):
        if event in {"done", "error"}:
            assert output.read_text(encoding="utf-8") == "saved transcript"
            terminals.append(payload)
        return real_emit(event, **payload)

    class Input:
        sent = False

        def read(self, n):
            if not self.sent:
                self.sent = True
                return '{"action":"transcribe","file_path":"input.wav","task_id":"job-1"}\n'
            assert accepted.wait(5)
            if reader:
                raise UnicodeError("reader failed")
            return ""

    original_report = worker._report_error

    def report(*a, **kw):
        # The original implementation reports from the reader before saving.
        if threading.current_thread().name == "worker-stdin":
            reader_failed.set()
        return original_report(*a, **kw)

    def transcribe(task, *a, **kw):
        accepted.set()
        if reader:
            # Wait for either implementation to mark the task cancelled.
            for _ in range(500):
                if task.cancelled:
                    break
                reader_failed.wait(0.01)
            assert task.cancelled
        else:
            threading.excepthook(SimpleNamespace(exc_value=RuntimeError("helper failed")))
        assert terminals == []
        output.write_text("saved transcript", encoding="utf-8")
        task.output_paths = [output]
        if decode_raises:
            raise RuntimeError("decode stopped")

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", transcribe)
    monkeypatch.setattr(worker, "emit", emit)
    monkeypatch.setattr(worker, "_report_error", report)
    monkeypatch.setattr(sys, "stdin", Input())
    assert worker.main() == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    terminal = [e for e in events if e["event"] in {"done", "error"}]
    assert len(terminal) == 1 and terminal[0]["event"] == "error"
    assert terminal[0]["outputs"] == [str(output)]
    assert terminal[0]["file_path"] == "input.wav" and terminal[0]["task_id"] == "job-1"
    assert worker._current_task is None


def test_user_cancel_sends_one_done_and_clears_current_task(monkeypatch, capsys):
    def transcribe(task, *a, **kw):
        task.cancelled = True
        raise RuntimeError("cancelled")

    events = _run(monkeypatch, capsys, transcribe)
    assert [e["event"] for e in events if e["event"] in {"done", "error"}] == ["done"]
    assert worker._current_task is None


@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_fatal_live_chunk_uses_live_terminal_protocol(monkeypatch, capsys, exc):
    from core import transcriber

    def fail(*a, **kw):
        raise exc

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(transcriber, "transcribe_chunk_to_text", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        '{"action":"transcribe_live","file_path":"input.wav","id":"chunk-1"}\n'))
    assert worker.main() == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    terminal = [e for e in events if e["event"] in {"error", "live_error"}]
    assert len(terminal) == 1 and terminal[0]["event"] == "live_error"
    assert terminal[0]["id"] == "chunk-1"
    assert terminal[0]["diag"]["cls"] == type(exc).__name__


@pytest.mark.parametrize("stderr", [False, True])
def test_report_serializes_path_outputs_and_keeps_task_identity(monkeypatch, capsys, stderr):
    if stderr:
        monkeypatch.setattr(worker, "emit", lambda *a, **kw: (_ for _ in ()).throw(OSError("write failed")))
    task = SimpleNamespace(file_path="input.wav", task_id="job-2", output_paths=[Path("kept.srt")])
    worker._report_error(RuntimeError("late failure"), task)
    captured = capsys.readouterr()
    event = json.loads(captured.err if stderr else captured.out)
    assert event["event"] == "error" and event["outputs"] == ["kept.srt"]
    assert event["file_path"] == "input.wav" and event["task_id"] == "job-2"


@pytest.mark.parametrize("failure", ["traceback", "task_getattr"])
def test_report_setup_failure_still_emits_error(monkeypatch, capsys, failure):
    class Task:
        @property
        def _failure_site(self):
            raise MemoryError()

    if failure == "traceback":
        monkeypatch.setattr(failure_clue, "site_from_traceback", lambda *a: (_ for _ in ()).throw(MemoryError()))
    worker._report_error(RuntimeError("original"), Task() if failure == "task_getattr" else None)
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "error" and event["exception_family"] == "RuntimeError"


def test_report_stderr_fallback_survives_partial_stdout_line(monkeypatch):
    merged_pipe = io.StringIO()
    monkeypatch.setattr(sys, "stdout", merged_pipe)
    monkeypatch.setattr(sys, "stderr", merged_pipe)

    def broken_emit(*a, **kw):
        merged_pipe.write('{"event":')
        raise OSError("partial write")

    monkeypatch.setattr(worker, "emit", broken_emit)
    worker._report_error(RuntimeError("failed"), file_path="input.wav", task_id="job-3")
    records = []
    for line in merged_pipe.getvalue().splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            pass
    assert len(records) == 1
    assert records[0]["file_path"] == "input.wav" and records[0]["task_id"] == "job-3"


def test_cancel_message_allocation_failure_still_sends_done(monkeypatch, capsys):
    class Message(str):
        def lower(self):
            raise MemoryError()

    class Error(RuntimeError):
        def __str__(self):
            return Message("stopped")

    def transcribe(task, *a, **kw):
        task.cancelled = True
        raise Error()

    events = _run(monkeypatch, capsys, transcribe)
    assert [e["event"] for e in events if e["event"] in {"done", "error"}] == ["done"]


@pytest.mark.parametrize("chained", [False, True])
def test_unprintable_origin_keeps_device_memory_and_family(monkeypatch, chained):
    class Unprintable(RuntimeError):
        def __str__(self):
            raise MemoryError()

    class UnprintablePermission(PermissionError):
        def __str__(self):
            raise MemoryError()

    exc = Unprintable()
    if chained:
        exc.__cause__ = UnprintablePermission(13, "unavailable")
    monkeypatch.setattr(failure_clue, "peak_memory_mb", lambda: 300)
    clue = failure_clue.worker_clue(exc, site="worker.prepare", device="cuda")
    assert clue["device"] == "cuda" and clue["peak_mem_mb"] == "512"
    assert clue["exception_family"] == ("PermissionError" if chained else "RuntimeError")
    assert clue["os_error"] == ("13" if chained else "0")
