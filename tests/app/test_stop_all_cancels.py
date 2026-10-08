"""Quitting with a job running: the worker is asked to cancel before it is asked to shut down.

The worker handles ``shutdown`` only after the running ``transcribe`` returns, so a
shutdown alone made it run on until the 5 s grace ended and then killed it, without the
cancel that writes the resume checkpoint (up to ~20 s of work lost). ``stop_all()`` (the
exit path) now sends ``cancel`` first for a worker with a live task; the worker saves the
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

    svc.stop_all()

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

    svc.stop_all()

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

    svc.stop_all()

    assert [m["action"] for _w, m in sent] == ["shutdown"]


def test_each_busy_worker_gets_its_own_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, app = _service()
    first, second = _Task(), _Task()
    second.history_id = 8
    app.workers.extend([_worker(first, 1), _worker(second, 2)])
    sent = _capture(svc, monkeypatch)

    svc.stop_all()

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

    svc.stop_all()

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
