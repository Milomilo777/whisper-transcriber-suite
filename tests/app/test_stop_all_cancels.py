"""Quitting with a job running: the worker is asked to cancel before it is asked to shut down.

The worker handles ``shutdown`` only after the running ``transcribe`` returns, so a
shutdown alone made it run on until the 5 s grace ended and then killed it, without the
cancel that writes the resume checkpoint (up to ~20 s of work lost). ``stop_all(cancel_running=True)``
(the exit path) now sends ``cancel`` first for a worker with a live task; the worker saves the
checkpoint, ends the task, reads the queued ``shutdown`` and exits inside the same grace.
"""
from __future__ import annotations

import json
import threading
from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import transcription_service as ts_mod
from app.services.transcription_service import TranscriptionService, task_correlation_id


class _Task:
    status = "running"
    cancelled = False
    history_id = 7
    file_path = "clip.mp4"


class _Proc:
    """Exits as soon as it has been sent 'shutdown' (a cooperative worker)."""

    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.pid = 99

    def poll(self) -> int | None:
        return None if self.alive else 0

    def wait(self, timeout: float | None = None) -> int:
        self.alive = False
        return 0


def _service() -> tuple[TranscriptionService, SimpleNamespace]:
    app = SimpleNamespace(
        after=lambda _ms, _fn: None, workers=[], worker_events=Queue(), queue=[],
        next_worker_id=1, model_loading=False, status_var=SimpleNamespace(set=lambda _v: None),
        entry_file=__file__, app_config={}, update_overall_progress=lambda: None,
        log=lambda _m: None,
    )
    return TranscriptionService(app), app  # type: ignore[arg-type]


def _worker(task: Any, wid: int = 1) -> dict[str, Any]:
    return {"id": wid, "process": _Proc(), "ready": True, "task": task, "token": f"t{wid}",
            "last_event_at": 0.0, "temporary": False, "stdin_lock": threading.Lock()}


def _capture(svc: TranscriptionService, monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, dict]]:
    sent: list[tuple[int, dict]] = []
    lock = threading.Lock()

    def _write(worker: dict[str, Any], msg: str) -> None:
        with lock:
            sent.append((worker["id"], json.loads(msg)))

    monkeypatch.setattr(svc, "_locked_stdin_write", _write)
    return sent


def test_stop_all_cancels_a_running_task_before_the_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, app = _service()
    task = _Task()
    app.workers.append(_worker(task))
    sent = _capture(svc, monkeypatch)

    svc.stop_all(cancel_running=True)

    assert sent == [
        (1, {"action": "cancel", "task_id": task_correlation_id(task)}),
        (1, {"action": "shutdown"}),
    ]


def test_stop_all_sends_only_the_shutdown_to_an_idle_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, app = _service()
    app.workers.append(_worker(None))
    sent = _capture(svc, monkeypatch)

    svc.stop_all(cancel_running=True)

    assert sent == [(1, {"action": "shutdown"})]


@pytest.mark.parametrize("status", ["finished", "cancelled", "error"])
def test_stop_all_does_not_cancel_a_task_that_already_ended(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    svc, app = _service()
    task = _Task()
    task.status = status
    app.workers.append(_worker(task))
    sent = _capture(svc, monkeypatch)

    svc.stop_all(cancel_running=True)

    assert [m["action"] for _w, m in sent] == ["shutdown"]


def test_each_busy_worker_gets_its_own_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, app = _service()
    first, second = _Task(), _Task()
    second.history_id = 8
    app.workers.extend([_worker(first, 1), _worker(second, 2)])
    sent = _capture(svc, monkeypatch)

    svc.stop_all(cancel_running=True)

    for wid, task in ((1, first), (2, second)):
        mine = [m for w, m in sent if w == wid]
        assert mine == [
            {"action": "cancel", "task_id": task_correlation_id(task)},
            {"action": "shutdown"},
        ]


def test_a_failing_cancel_write_still_lets_the_shutdown_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, app = _service()
    app.workers.append(_worker(_Task()))
    seen: list[str] = []

    def _write(_worker: dict[str, Any], msg: str) -> None:
        action = json.loads(msg)["action"]
        seen.append(action)
        if action == "cancel":
            raise RuntimeError("worker stdin is None")

    monkeypatch.setattr(svc, "_locked_stdin_write", _write)

    svc.stop_all(cancel_running=True)

    assert seen == ["cancel", "shutdown"]


def test_stopping_one_worker_for_a_restart_keeps_the_plain_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the exit path adds the cancel; restart/retire callers are unchanged."""
    svc, app = _service()
    worker = _worker(_Task())
    app.workers.append(worker)
    sent = _capture(svc, monkeypatch)

    svc.stop_worker(worker)

    assert [m["action"] for _w, m in sent] == ["shutdown"]


def test_a_plain_stop_all_keeps_sending_only_the_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine switches and model changes stop workers with the app still running: the
    cancelled task's ``done`` event would be read there as a finished run."""
    svc, app = _service()
    app.workers.append(_worker(_Task()))
    sent = _capture(svc, monkeypatch)

    svc.stop_all()

    assert [m["action"] for _w, m in sent] == ["shutdown"]


# ------------------------------------------------------------- the longer exit grace


class _LateProc:
    """A worker that needs ``exit_after`` seconds to finish its task and exit."""

    def __init__(self, exit_after: float) -> None:
        import time

        self.pid = 5
        self._end = time.monotonic() + exit_after
        self.terminated = False

    def poll(self) -> int | None:
        import time

        return 0 if (self.terminated or time.monotonic() >= self._end) else None

    def wait(self, timeout: float | None = None) -> int:
        import subprocess
        import time

        left = self._end - time.monotonic()
        if self.terminated or left <= 0:
            return 0
        if timeout is not None and timeout < left:
            time.sleep(timeout)
            raise subprocess.TimeoutExpired("worker", timeout)
        time.sleep(left)
        return 0


def _late_worker(task: Any, exit_after: float) -> tuple[dict[str, Any], _LateProc]:
    proc = _LateProc(exit_after)
    worker = _worker(task)
    worker["process"] = proc
    return worker, proc


def _watch_terminate(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    killed: list[Any] = []

    def _kill(proc: _LateProc, force: bool = False) -> None:
        killed.append(proc)
        proc.terminated = True

    monkeypatch.setattr(ts_mod, "kill_process_tree", _kill)
    return killed


def test_a_busy_worker_gets_the_longer_grace_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job in its last diarisation / alignment step can still finish or checkpoint."""
    svc, app = _service()
    worker, proc = _late_worker(_Task(), exit_after=0.8)
    app.workers.append(worker)
    _capture(svc, monkeypatch)
    killed = _watch_terminate(monkeypatch)
    monkeypatch.setattr(TranscriptionService, "STOP_GRACE_S", 0.2)
    monkeypatch.setattr(TranscriptionService, "EXIT_CANCEL_GRACE_S", 3.0)

    svc.stop_all(cancel_running=True)

    assert killed == []  # it left on its own inside the longer grace


def test_the_longer_grace_is_still_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    svc, app = _service()
    worker, proc = _late_worker(_Task(), exit_after=60.0)
    app.workers.append(worker)
    _capture(svc, monkeypatch)
    killed = _watch_terminate(monkeypatch)
    monkeypatch.setattr(TranscriptionService, "STOP_GRACE_S", 0.2)
    monkeypatch.setattr(TranscriptionService, "EXIT_CANCEL_GRACE_S", 0.6)
    monkeypatch.setattr(TranscriptionService, "STOP_TERMINATE_S", 0.2)

    started = time.monotonic()
    svc.stop_all(cancel_running=True)

    assert killed == [proc]  # terminated once the longer grace ran out
    assert time.monotonic() - started < 3.0


def test_other_stop_all_callers_and_idle_workers_keep_the_short_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, app = _service()
    busy, proc = _late_worker(_Task(), exit_after=0.8)
    app.workers.append(busy)
    _capture(svc, monkeypatch)
    killed = _watch_terminate(monkeypatch)
    monkeypatch.setattr(TranscriptionService, "STOP_GRACE_S", 0.2)
    monkeypatch.setattr(TranscriptionService, "EXIT_CANCEL_GRACE_S", 3.0)
    monkeypatch.setattr(TranscriptionService, "STOP_TERMINATE_S", 0.2)

    svc.stop_all()  # the engine-switch caller: no cancel, so no longer grace

    assert killed == [proc]

    # An idle worker that ignores the shutdown is not waited for 15 s either.
    app.workers.clear()
    idle, idle_proc = _late_worker(None, exit_after=0.8)
    app.workers.append(idle)
    killed.clear()
    svc.stop_all(cancel_running=True)
    assert killed == [idle_proc]
