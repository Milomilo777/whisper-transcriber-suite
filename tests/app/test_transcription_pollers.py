"""The transcription service's poll loop and worker readers never die silently.

* ``poll()`` re-armed itself only while a worker process was alive. A worker that died
  before its reader thread queued ``worker_exit`` (a grandchild still holding the stdout
  pipe) stopped the loop: the task stayed "running" and an ``ensure_worker_ready`` wait
  was never released. An exception outside the per-event guard stopped it too.
* A worker stdout line that is valid JSON but not an object (``42``, ``[1]``, ``"x"``)
  raised in the reader thread, so ``worker_exit`` was never queued.
* ``stop_all()`` waited 5 + 2 s per busy worker one after the other.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from queue import Empty, Queue
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import transcription_service as ts_mod
from app.services.transcription_service import TranscriptionService


class _Task:
    status = "running"
    progress = 0
    cancelled = False
    history_id = 0
    start_time = 1.0
    end_time = None
    file_path = "clip.mp4"


class _DeadProc:
    """A worker process that already exited."""

    pid = 4242

    def poll(self) -> int:
        return 3


def _fake_app() -> SimpleNamespace:
    after_calls: list[tuple[int, Any]] = []
    return SimpleNamespace(
        after_calls=after_calls,
        after=lambda ms, fn: after_calls.append((ms, fn)),
        workers=[],
        worker_events=Queue(),
        queue=[],
        next_worker_id=1,
        model_loading=False,
        status_var=SimpleNamespace(set=lambda _v: None),
        entry_file=__file__,
        app_config={},
        update_overall_progress=lambda: None,
        log=lambda _m: None,
        post_to_main=lambda _f: None,
        refresh=lambda: None,
        refresh_download_queue=lambda: None,
    )


def _dead_worker_with_task() -> dict[str, Any]:
    return {"id": 1, "process": _DeadProc(), "ready": True, "task": _Task(),
            "token": "tok", "last_event_at": time.time(), "temporary": False}


def test_poll_keeps_polling_until_a_dead_workers_exit_event_arrives() -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.workers.append(_dead_worker_with_task())

    svc.poll()  # the process is gone but worker_exit is still on its way

    assert len(app.after_calls) == 1, "poll() stopped before worker_exit was handled"


def test_poll_stops_once_nothing_is_left_to_watch() -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.workers.append({"id": 1, "process": None, "ready": False, "task": None,
                        "token": "tok", "last_event_at": 0.0, "temporary": False})

    svc.poll()

    assert app.after_calls == []


def test_poll_rearms_even_when_routing_an_event_raises(monkeypatch: Any) -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    app.workers.append(_dead_worker_with_task())
    app.worker_events.put({"event": "progress", "_worker_id": 1})

    def _boom(_event: dict[str, Any]) -> None:
        raise RuntimeError("routing failed")

    monkeypatch.setattr(svc, "worker_for_event", _boom)
    with pytest.raises(RuntimeError):
        svc.poll()  # Tk reports the error; the loop must survive it

    assert len(app.after_calls) == 1


class _ScriptedProc:
    """Popen stand-in whose stdout yields the given lines, then EOF."""

    def __init__(self, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.stdin = None
        self.pid = 777
        self.returncode = 0

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _events_until_exit(app: SimpleNamespace, timeout: float = 5.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = app.worker_events.get(timeout=0.05)
        except Empty:
            continue
        events.append(event)
        if event.get("event") == "worker_exit":
            return events
    raise AssertionError(f"no worker_exit within {timeout} s; got {events!r}")


@pytest.mark.parametrize("line", ["42", "[1, 2]", '"just a string"', "null", "true"])
def test_reader_survives_json_that_is_not_an_object(monkeypatch: Any, line: str) -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    proc = _ScriptedProc([line + "\n", '{"event": "ready"}\n'])
    monkeypatch.setattr(ts_mod.subprocess, "Popen", lambda *_a, **_k: proc)

    svc.start_worker()
    events = _events_until_exit(app)

    kinds = [e.get("event") for e in events]
    assert kinds == ["log", "ready", "worker_exit"]
    assert events[0]["message"] == line


def test_reader_logs_a_line_it_cannot_route_and_keeps_reading(monkeypatch: Any,
                                                             caplog: Any) -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    proc = _ScriptedProc(['{"event": "ready"}\n', '{"event": "heartbeat"}\n'])
    monkeypatch.setattr(ts_mod.subprocess, "Popen", lambda *_a, **_k: proc)
    real_queue = app.worker_events

    class _FlakyQueue:
        calls = 0

        def put(self, event: dict[str, Any]) -> None:
            _FlakyQueue.calls += 1
            if _FlakyQueue.calls == 1:
                raise RuntimeError("queue rejected the event")
            real_queue.put(event)

    app.worker_events = _FlakyQueue()
    with caplog.at_level(logging.ERROR):
        svc.start_worker()
        app.worker_events = real_queue  # the reader keeps a reference to app only
        events = _events_until_exit(app)

    assert [e.get("event") for e in events][-1] == "worker_exit"
    assert "queue rejected the event" in caplog.text


# ------------------------------------------------------------------ stop_all


class _SlowProc:
    """Ignores the shutdown request; wait() always times out until killed."""

    def __init__(self) -> None:
        self.alive = True
        self.waited: list[float] = []

    def poll(self) -> int | None:
        return None if self.alive else -9

    def wait(self, timeout: float | None = None) -> int:
        if not self.alive:
            return -9
        if timeout:
            time.sleep(timeout)
        self.waited.append(timeout or 0.0)
        raise subprocess.TimeoutExpired("worker", timeout or 0.0)


def test_stop_all_waits_once_for_all_workers_not_once_per_worker(monkeypatch: Any) -> None:
    app = _fake_app()
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    procs = [_SlowProc() for _ in range(3)]
    for i, proc in enumerate(procs, start=1):
        app.workers.append({"id": i, "process": proc, "ready": True, "task": None,
                            "token": f"t{i}", "last_event_at": 0.0, "temporary": False,
                            "stdin_lock": threading.Lock()})
    monkeypatch.setattr(svc, "_locked_stdin_write", lambda *_a, **_k: None)
    killed: list[tuple[int, bool]] = []

    def _kill(proc: _SlowProc, force: bool = False) -> None:
        killed.append((procs.index(proc), force))
        if force:
            proc.alive = False

    monkeypatch.setattr(ts_mod, "kill_process_tree", _kill)
    monkeypatch.setattr(ts_mod.TranscriptionService, "STOP_GRACE_S", 0.3)
    monkeypatch.setattr(ts_mod.TranscriptionService, "STOP_TERMINATE_S", 0.2)

    started = time.monotonic()
    svc.stop_all()
    elapsed = time.monotonic() - started

    # Sequential stopping took 3 x (0.3 + 0.2) = 1.5 s; one shared deadline about 0.5 s.
    assert elapsed < 1.2, f"stop_all took {elapsed:.2f} s"
    assert sorted(killed) == [(0, False), (0, True), (1, False), (1, True), (2, False), (2, True)]
