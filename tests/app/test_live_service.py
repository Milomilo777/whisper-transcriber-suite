"""Tests for the Live tab's worker plumbing (app/services/live_service.py).

The concurrency here is the risky part: a blocking request/response over
a pipe, answered on a reader thread, with a worker that can die at any
moment. No real subprocess is spawned — a fake stands in for the pipe.
"""
from __future__ import annotations

import io
import json
import queue
import threading
import time

import pytest

from app.services.live_service import LiveTranscriber, LiveWorkerError


class _FakeStdout:
    """A blocking line iterator the reader thread can consume."""

    def __init__(self) -> None:
        self._q: "queue.Queue[str | None]" = queue.Queue()

    def push(self, obj) -> None:
        self._q.put(json.dumps(obj) + "\n" if not isinstance(obj, str) else obj)

    def close_stream(self) -> None:
        self._q.put(None)

    def __iter__(self):
        return self

    def __next__(self) -> str:
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item


class _FakeProc:
    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = _FakeStdout()
        self._rc = None
        self.killed = False

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        self._rc = 0
        return 0

    def exit(self, code=0):
        self._rc = code


@pytest.fixture
def wired(monkeypatch):
    """A started LiveTranscriber backed by a fake process."""
    proc = _FakeProc()
    monkeypatch.setattr(
        "app.services.live_service.subprocess.Popen", lambda *a, **kw: proc
    )
    lt = LiveTranscriber("gui.py")
    lt.start(wait_ready=False)
    yield lt, proc
    _stop_and_join(lt, proc)


def _sent(proc: _FakeProc) -> list[dict]:
    out = []
    for line in proc.stdin.getvalue().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _wait(predicate, timeout=3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _stop_and_join(lt: LiveTranscriber, proc: _FakeProc) -> None:
    """Unblock the reader thread and confirm it actually exits.

    A real subprocess's stdout pipe closes on its own once the process
    exits, which is what makes ``_read_loop``'s ``for line in
    proc.stdout:`` return. ``_FakeProc``/``_FakeStdout`` do not simulate
    that, so without this, every test that starts a ``LiveTranscriber``
    leaves its "live-worker-reader" daemon thread permanently blocked in
    ``queue.get()`` for the rest of the test process's life — harmless on
    its own (daemon=True), but dozens of them accumulate across this
    file's tests and were still alive minutes later when an unrelated
    real-model test ran near the end of the full suite.
    """
    reader = getattr(lt, "_reader", None)
    proc.stdout.close_stream()  # idempotent even if already closed
    lt.stop()
    if reader is not None:
        reader.join(timeout=2.0)
        assert not reader.is_alive(), "live-worker-reader thread leaked"


# ------------------------------------------------------------- readiness


def test_wait_ready_returns_once_the_model_loads(wired):
    lt, proc = wired
    proc.stdout.push({"event": "ready"})
    lt.wait_ready(timeout=3.0)   # must not raise


def test_wait_ready_surfaces_a_startup_error(wired):
    lt, proc = wired
    proc.stdout.push({"event": "startup_error", "message": "model missing"})
    with pytest.raises(LiveWorkerError, match="model missing"):
        lt.wait_ready(timeout=3.0)


def test_wait_ready_times_out_rather_than_hanging(wired):
    lt, _proc = wired
    with pytest.raises(LiveWorkerError, match="Timed out"):
        lt.wait_ready(timeout=0.4)


# ------------------------------------------------------- request/response


def test_chunk_round_trip_returns_the_text(wired):
    lt, proc = wired
    result: dict = {}

    def call():
        result.update(lt.transcribe_chunk("chunk.wav"))

    t = threading.Thread(target=call, daemon=True)
    t.start()
    assert _wait(lambda: _sent(proc)), "nothing was written to the worker"
    request = _sent(proc)[0]
    assert request["action"] == "transcribe_live"
    assert request["file_path"] == "chunk.wav"
    proc.stdout.push({
        "event": "live_result", "id": request["id"],
        "text": "hello there", "language": "en", "segments": [],
    })
    t.join(timeout=3.0)
    assert result["text"] == "hello there"
    assert result["language"] == "en"


def test_language_is_forwarded(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(
        "app.services.live_service.subprocess.Popen", lambda *a, **kw: proc
    )
    lt = LiveTranscriber("gui.py", language="fa")
    lt.start(wait_ready=False)
    caller = threading.Thread(
        target=lambda: _swallow(lt.transcribe_chunk, "c.wav"), daemon=True
    )
    caller.start()
    assert _wait(lambda: _sent(proc))
    assert _sent(proc)[0]["language"] == "fa"
    # Answer the chunk so `caller` returns now instead of blocking for the
    # full CHUNK_TIMEOUT_S (180s) — it would otherwise still be alive,
    # waiting, for most of the rest of a full test-suite run.
    proc.stdout.push({
        "event": "live_result", "id": _sent(proc)[0]["id"], "text": "",
    })
    caller.join(timeout=3.0)
    assert not caller.is_alive(), "the chunk-caller thread leaked"
    _stop_and_join(lt, proc)


def _answer_next(lt, proc, n_before, **reply):
    """Send one chunk from a thread, answer it with ``reply``, return result."""
    out: dict = {}
    t = threading.Thread(
        target=lambda: out.update(lt.transcribe_chunk("c.wav")), daemon=True
    )
    t.start()
    assert _wait(lambda: len(_sent(proc)) > n_before)
    request = _sent(proc)[n_before]
    proc.stdout.push({"event": "live_result", "id": request["id"], **reply})
    t.join(timeout=3.0)
    return request, out


def test_auto_detect_locks_after_first_confident_chunk(wired):
    lt, proc = wired
    logged: list[str] = []
    lt._log = logged.append
    # Unsure (low probability) -> keep auto-detecting.
    req, _ = _answer_next(lt, proc, 0, text="hm", language="en",
                          language_probability=0.4)
    assert req["language"] is None and lt.language is None
    # Empty text never locks, however confident.
    req, _ = _answer_next(lt, proc, 1, text="", language="en",
                          language_probability=0.99)
    assert lt.language is None
    req, out = _answer_next(lt, proc, 2, text="salam", language="fa",
                            language_probability=0.93)
    assert req["language"] is None
    assert out["language_probability"] == pytest.approx(0.93)
    assert lt.language == "fa" and lt.locked_language == "fa"
    assert any("'fa'" in m for m in logged)
    req, _ = _answer_next(lt, proc, 3, text="khoobi", language="fa",
                          language_probability=0.9)
    assert req["language"] == "fa"  # later chunks skip detection


def test_explicit_language_is_never_overridden(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(
        "app.services.live_service.subprocess.Popen", lambda *a, **kw: proc
    )
    lt = LiveTranscriber("gui.py", language="en")
    lt.start(wait_ready=False)
    _answer_next(lt, proc, 0, text="bonjour", language="fr",
                 language_probability=0.99)
    assert lt.language == "en" and lt.locked_language == ""
    _stop_and_join(lt, proc)


def _swallow(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


def test_a_worker_side_error_raises_for_that_chunk_only(wired):
    lt, proc = wired
    box: dict = {}

    def call():
        try:
            lt.transcribe_chunk("chunk.wav")
        except LiveWorkerError as e:
            box["error"] = str(e)

    t = threading.Thread(target=call, daemon=True)
    t.start()
    assert _wait(lambda: _sent(proc))
    proc.stdout.push({
        "event": "live_error", "id": _sent(proc)[0]["id"],
        "message": "bad chunk",
    })
    t.join(timeout=3.0)
    assert "bad chunk" in box.get("error", "")


def test_responses_are_routed_by_id_not_arrival_order(wired):
    """Two chunks in flight must not swap their answers."""
    lt, proc = wired
    results: dict[str, str] = {}

    def call(tag):
        results[tag] = lt.transcribe_chunk(f"{tag}.wav")["text"]

    t1 = threading.Thread(target=call, args=("first",), daemon=True)
    t1.start()
    assert _wait(lambda: len(_sent(proc)) >= 1)
    t2 = threading.Thread(target=call, args=("second",), daemon=True)
    t2.start()
    assert _wait(lambda: len(_sent(proc)) >= 2)

    sent = _sent(proc)
    by_file = {r["file_path"]: r["id"] for r in sent}
    # Answer the SECOND request first.
    proc.stdout.push({"event": "live_result", "id": by_file["second.wav"],
                      "text": "second text"})
    proc.stdout.push({"event": "live_result", "id": by_file["first.wav"],
                      "text": "first text"})
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert results == {"first": "first text", "second": "second text"}


def test_an_unknown_response_id_is_ignored(wired):
    lt, proc = wired
    proc.stdout.push({"event": "live_result", "id": "nope", "text": "ghost"})
    time.sleep(0.2)
    assert lt.is_running()


# --------------------------------------------------------- failure modes


def test_worker_death_releases_a_waiting_chunk(wired):
    """A blocked consumer thread must not wait forever on a dead worker."""
    lt, proc = wired
    box: dict = {}

    def call():
        try:
            lt.transcribe_chunk("chunk.wav")
        except LiveWorkerError as e:
            box["error"] = str(e)

    t = threading.Thread(target=call, daemon=True)
    t.start()
    assert _wait(lambda: _sent(proc))
    proc.stdout.close_stream()   # worker exits
    t.join(timeout=5.0)
    assert not t.is_alive(), "the caller hung on a dead worker"
    assert "exited" in box.get("error", "").lower()


def test_transcribe_refuses_when_the_worker_already_exited(wired):
    lt, proc = wired
    proc.exit(1)
    with pytest.raises(LiveWorkerError, match="not running"):
        lt.transcribe_chunk("chunk.wav")


def test_stop_releases_pending_chunks(wired):
    lt, proc = wired
    box: dict = {}

    def call():
        try:
            lt.transcribe_chunk("chunk.wav")
        except LiveWorkerError as e:
            box["error"] = str(e)

    t = threading.Thread(target=call, daemon=True)
    t.start()
    assert _wait(lambda: _sent(proc))
    lt.stop()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert box.get("error")


def test_stop_sends_shutdown_then_is_idempotent(wired):
    lt, proc = wired
    lt.stop()
    assert any(r.get("action") == "shutdown" for r in _sent(proc))
    lt.stop()   # second call must not raise


def test_cannot_start_twice(wired):
    lt, _proc = wired
    with pytest.raises(RuntimeError):
        lt.start(wait_ready=False)


def test_non_json_worker_output_is_logged_not_fatal(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(
        "app.services.live_service.subprocess.Popen", lambda *a, **kw: proc
    )
    logged: list[str] = []
    lt = LiveTranscriber("gui.py", log=logged.append)
    lt.start(wait_ready=False)
    proc.stdout.push("Traceback (most recent call last):\n")
    proc.stdout.push({"event": "ready"})
    lt.wait_ready(timeout=3.0)
    assert any("Traceback" in line for line in logged)
    _stop_and_join(lt, proc)


def test_spawn_failure_is_reported_clearly(monkeypatch):
    def boom(*a, **kw):
        raise OSError("no such executable")

    monkeypatch.setattr("app.services.live_service.subprocess.Popen", boom)
    lt = LiveTranscriber("gui.py")
    with pytest.raises(LiveWorkerError, match="Could not start"):
        lt.start(wait_ready=False)
