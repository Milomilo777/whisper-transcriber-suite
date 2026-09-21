"""Fixpack regression tests for core.worker — CONCURRENCY cluster.

Covers two defects:

1. emit() wrote JSON lines to stdout from the main, stdin-reader and
   heartbeat threads with NO lock, so concurrent write+flush pairs could
   interleave and corrupt a line — breaking the FROZEN one-JSON-object-
   per-line worker protocol. Fixed with a module-level _emit_lock.

2. The stdin reader buffered a whole line (``for raw in sys.stdin``)
   BEFORE the 1 MB length check, so a runaway/malicious parent could OOM
   the worker with one enormous newline-less line. Fixed with
   read_capped_lines(), which enforces the cap WHILE reading in chunks.

All tests are hermetic: no subprocess, no network, no real model, no Tk.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time

import pytest

from core import worker


# --------------------------------------------------------------------------
# read_capped_lines — bounded reader (OOM guard enforced while reading)
# --------------------------------------------------------------------------

def test_read_capped_lines_splits_normal_lines():
    stream = io.StringIO("a\nbb\nccc\n")
    out = list(worker.read_capped_lines(stream, 1000))
    assert out == [("a\n", False), ("bb\n", False), ("ccc\n", False)]


def test_read_capped_lines_yields_trailing_line_without_newline():
    stream = io.StringIO("a\nlast")
    out = list(worker.read_capped_lines(stream, 1000))
    assert out == [("a\n", False), ("last", False)]


def test_read_capped_lines_flags_oversize_terminated_record():
    big = "x" * 50 + "\n"
    stream = io.StringIO(big)
    out = list(worker.read_capped_lines(stream, 10))
    assert out and out[0][1] is True
    assert all(oversize is True for _, oversize in out)


def test_read_capped_lines_flags_oversize_unterminated_then_recovers():
    """An overlong newline-less record is flagged oversize; a following
    well-formed line still parses (the reader drains the bad tail)."""
    payload = "y" * 100 + "\n" + "ok\n"
    stream = io.StringIO(payload)
    out = list(worker.read_capped_lines(stream, 10))
    flags = [o for _, o in out]
    assert flags[0] is True            # oversized record flagged
    assert ("ok\n", False) in out      # good line recovered after the tail


def test_read_capped_lines_does_not_buffer_full_oversized_payload():
    """Core OOM guard: a giant newline-less line must NOT be held in memory
    in full. We track the largest single string the reader ever yields and
    assert it stays bounded near the cap (+ one read chunk), not the whole
    multi-megabyte payload."""
    cap = 1000
    total = cap * 5000  # ~5M chars, dwarfs cap and the chunk size
    stream = io.StringIO("z" * total + "\n")
    max_yielded = 0
    saw_oversize = False
    for text, oversize in worker.read_capped_lines(stream, cap):
        max_yielded = max(max_yielded, len(text))
        saw_oversize = saw_oversize or oversize
    assert saw_oversize is True
    # Never accumulated the full payload: bounded by cap + one chunk.
    assert max_yielded <= cap + worker._READ_CHUNK_CHARS
    assert max_yielded < total


def test_read_capped_lines_empty_stream():
    assert list(worker.read_capped_lines(io.StringIO(""), 10)) == []


class _ReadOnlyStream:
    """A read(n)-only stream, forcing read_capped_lines' chunked fallback."""

    def __init__(self, data: str) -> None:
        self._buf = io.StringIO(data)

    def read(self, n: int = -1) -> str:
        return self._buf.read(n)


class _IterOnlyStream:
    """A pure-iterator stream (no readline, no read), forcing
    read_capped_lines' iterate-only fallback."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


def test_read_capped_lines_reports_each_oversized_record_once():
    """One oversized record must produce exactly ONE oversize yield.

    The drained tail used to be yielded again as ("", True), so the stdin
    reader emitted "command exceeds max length" twice for a single bad
    command.
    """
    out = list(worker.read_capped_lines(io.StringIO("x" * 50 + "\n" + "ok\n"), 10))
    assert [t for t, o in out if o] == ["x" * 11]
    assert ("ok\n", False) in out


def test_read_capped_lines_reports_each_oversized_record_once_chunked(monkeypatch):
    """Same one-report contract on the read() fallback path, with the
    oversized record split across several bounded reads."""
    monkeypatch.setattr(worker, "_READ_CHUNK_CHARS", 8)
    stream = _ReadOnlyStream("x" * 50 + "\n" + "ok\n")
    out = list(worker.read_capped_lines(stream, 10))
    over = [t for t, o in out if o]
    assert len(over) == 1
    assert ("ok\n", False) in out


@pytest.mark.parametrize("chunked", [False, True])
def test_read_capped_lines_accepts_record_exactly_at_cap(chunked):
    """A record of exactly the cap (plus its framing newline) is NOT
    oversized — the newline is framing, not payload."""
    cap = 10
    line = "x" * cap + "\n"
    stream = _ReadOnlyStream(line) if chunked else io.StringIO(line)
    assert list(worker.read_capped_lines(stream, cap)) == [(line, False)]


def test_read_capped_lines_iterate_only_accepts_record_exactly_at_cap():
    """Same at-cap contract on the iterate-only fallback path: it kept the
    old len() check (newline counted), so an at-cap record was wrongly
    flagged oversized there while both other paths accepted it."""
    cap = 10
    line = "x" * cap + "\n"
    assert list(worker.read_capped_lines(_IterOnlyStream([line]), cap)) == [
        (line, False)
    ]


# --------------------------------------------------------------------------
# main() OOM guard — oversize command never starts a task (end-to-end)
# --------------------------------------------------------------------------

def test_main_rejects_oversize_command_without_buffering(monkeypatch, capsys):
    """A line far past MAX_COMMAND_BYTES is rejected with an error and never
    starts a task, and the parent's reads are observably bounded."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(
        worker, "transcribe",
        lambda *a, **k: pytest.fail("oversize command must not run a task"),
    )

    class _BoundedReadStream:
        """Wraps a StringIO and records the largest single read() result."""
        def __init__(self, data: str) -> None:
            self._buf = io.StringIO(data)
            self.max_read = 0

        def read(self, n: int = -1) -> str:
            chunk = self._buf.read(n)
            self.max_read = max(self.max_read, len(chunk))
            return chunk

        def __iter__(self):  # pragma: no cover - must NOT be used now
            raise AssertionError("worker must not line-iterate stdin")

    huge = "x" * ((1 << 20) * 8) + "\n"  # 8 MB, no newline until the end
    stream = _BoundedReadStream(huge + json.dumps({"action": "shutdown"}) + "\n")
    monkeypatch.setattr(sys, "stdin", stream)
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    errs = [e for e in events if e["event"] == "error"]
    assert errs and "exceeds max length" in errs[0]["message"]
    assert not any(e["event"] == "started" for e in events)
    # Reads were chunk-bounded — the 8 MB line was never read in one gulp.
    assert stream.max_read <= worker._READ_CHUNK_CHARS


def test_main_oversize_command_reports_exactly_one_error(monkeypatch, capsys):
    """One over-cap stdin command yields exactly ONE error event.

    The drained tail of the oversized record used to be yielded as a second
    oversize record, so the parent got a duplicate "exceeds max length"
    error for a single bad command.
    """
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    huge = "x" * ((1 << 20) + 1) + "\n"
    inputs = huge + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    assert worker.main() == 0
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    errs = [e for e in events if e["event"] == "error"]
    assert len(errs) == 1
    assert "exceeds max length" in errs[0]["message"]


def test_main_normal_command_still_works_after_reader_change(monkeypatch, capsys):
    """The bounded reader does not regress the happy path."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", lambda task, p, l, language_cb=None: None)
    inputs = (
        json.dumps({"action": "transcribe", "file_path": "/tmp/x.wav"}) + "\n"
        + json.dumps({"action": "shutdown"}) + "\n"
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()
    events = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines() if l.strip()]
    assert any(e["event"] == "started" for e in events)
    assert any(e["event"] == "done" for e in events)


# --------------------------------------------------------------------------
# emit() concurrency — _emit_lock prevents interleaved/corrupt lines
# --------------------------------------------------------------------------

def test_emit_uses_a_lock():
    """The lock exists and emit() acquires it (regression anchor)."""
    assert isinstance(worker._emit_lock, type(threading.Lock()))


def test_concurrent_emit_lines_are_never_interleaved(monkeypatch):
    """Many threads emitting at once must produce only intact JSON lines.

    We force a context switch between the write and the flush by wrapping
    print so the write half yields the GIL; without the lock this would let
    another thread's print interleave inside a partial line. With the lock,
    every stdout line is a complete, parseable JSON object.
    """
    captured: list[str] = []
    cap_lock = threading.Lock()

    real_print = print

    def slow_print(line, flush=False):  # noqa: A002 - mirror builtin
        # Simulate non-atomic write+flush: hand the line off in two steps
        # with a thread yield between them. The _emit_lock must hold across
        # both so no other thread's line can splice in.
        import time as _t
        _t.sleep(0)  # yield the GIL mid-emit
        with cap_lock:
            captured.append(line)

    monkeypatch.setattr("builtins.print", slow_print)

    n_threads = 24
    per_thread = 40

    def worker_fn(idx: int) -> None:
        for j in range(per_thread):
            worker.emit("log", message=f"t{idx}-{j}", thread=idx, seq=j)

    threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    monkeypatch.setattr("builtins.print", real_print)

    assert len(captured) == n_threads * per_thread
    seen = set()
    for line in captured:
        parsed = json.loads(line)  # must be intact JSON — raises if corrupt
        assert parsed["event"] == "log"
        seen.add((parsed["thread"], parsed["seq"]))
    # Every emit is accounted for exactly once.
    assert len(seen) == n_threads * per_thread


# --------------------------------------------------------------------------
# Task isolation across rapid re-dispatch (no leftover cancel/pause flag)
# --------------------------------------------------------------------------

def test_rapid_redispatch_does_not_leak_cancel_flag(monkeypatch, capsys):
    """A cancel applied to task A must not bleed into a freshly dispatched
    task B: each transcribe builds a new task and _set_current_task(None)
    clears the slot when the task ends."""
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)

    seen_tasks: list[object] = []

    def fake_transcribe(task, p, l, language_cb=None):
        seen_tasks.append(task)
        # Each freshly dispatched task starts un-cancelled / un-paused.
        assert task.cancelled is False
        assert task.paused is False

    monkeypatch.setattr(worker, "transcribe", fake_transcribe)

    inputs = (
        json.dumps({"action": "transcribe", "file_path": "/a.wav"}) + "\n"
        + json.dumps({"action": "transcribe", "file_path": "/b.wav"}) + "\n"
        + json.dumps({"action": "shutdown"}) + "\n"
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))
    worker.main()

    assert len(seen_tasks) == 2
    assert seen_tasks[0] is not seen_tasks[1]
    # Current-task slot is cleared after the run loop drains.
    assert worker._current_task is None


def test_read_capped_lines_reads_from_real_pipe_promptly():
    """A real pipe carrying one short JSON line must be consumed promptly.

    This is the regression we actually hit in the GUI: a Windows text pipe
    was being read with a chunked ``read(n)`` path that never handed a short
    command to the worker. A pipe-based test catches that class of bug while
    staying hermetic.
    """
    rfd, wfd = os.pipe()
    out: list[tuple[str, bool]] = []
    err: list[BaseException] = []

    def _reader() -> None:
        try:
            with os.fdopen(rfd, "r", encoding="utf-8", newline="") as stream:
                out.extend(worker.read_capped_lines(stream, 1000))
        except BaseException as exc:  # pragma: no cover - failure path
            err.append(exc)

    t = threading.Thread(target=_reader)
    t.start()
    try:
        time.sleep(0.2)
        with os.fdopen(wfd, "w", encoding="utf-8", newline="") as writer:
            writer.write(json.dumps({"action": "transcribe"}) + "\n")
            writer.flush()
            deadline = time.time() + 5
            expected = (json.dumps({"action": "transcribe"}) + "\n", False)
            while time.time() < deadline and expected not in out:
                time.sleep(0.05)
            assert expected in out
    finally:
        if t.is_alive():
            try:
                os.close(wfd)
            except OSError:
                pass
            t.join(timeout=5)
    assert not err
    assert out == [(json.dumps({"action": "transcribe"}) + "\n", False)]
