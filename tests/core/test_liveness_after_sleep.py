"""The liveness watchdog must not kill a worker because the computer slept.

On Windows ``time.monotonic`` counts through sleep, so the first poll after
waking saw minutes of worker silence (no event can arrive while the computer
sleeps) and replaced a healthy worker: the running job ended as an error.
"""
from __future__ import annotations

import time
from queue import Queue

from app.services.transcription_service import TranscriptionService


class _AliveProc:
    pid = 1

    def poll(self):
        return None


class _Task:
    status = "running"


class _FakeApp:
    def __init__(self, workers):
        self.workers = workers
        self.worker_events: Queue = Queue()
        self.after_calls: list = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))

    def log(self, msg):
        pass


def _service(monkeypatch, clock):
    worker = {"id": 1, "process": _AliveProc(), "task": _Task(), "last_event_at": 1000.0}
    svc = TranscriptionService(_FakeApp([worker]))  # type: ignore[arg-type]
    restarted: list = []
    def restart(w):  # a restarted worker starts unstamped, like a real respawn
        restarted.append((w["id"], clock[0]))
        w["last_event_at"] = 0.0

    monkeypatch.setattr(svc, "restart_worker", restart)
    monkeypatch.setattr(svc, "finish_task", lambda w, keep_status=False: None)
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    return svc, worker, restarted


def test_a_sleep_gap_restarts_the_window_instead_of_the_worker(monkeypatch):
    clock = [1000.5]
    svc, worker, restarted = _service(monkeypatch, clock)
    svc.poll()                      # last poll before the sleep
    clock[0] = 1000.5 + 600         # 10 minutes asleep, no events queued
    svc.poll()
    assert restarted == []
    woke = clock[0]
    assert worker["last_event_at"] == woke
    # A worker that really stays silent is still caught afterwards.
    for _ in range(14):
        clock[0] += 10              # polls keep running, 140 s of silence
        svc.poll()
    assert [(i, t - woke) for i, t in restarted] == [(1, 130)]


def test_silence_without_a_gap_still_restarts_the_worker(monkeypatch):
    clock = [1000.5]
    svc, _worker, restarted = _service(monkeypatch, clock)
    while clock[0] < 1000 + svc.LIVENESS_TIMEOUT_S + 5:
        clock[0] += 1               # regular polls, worker silent
        svc.poll()
    assert [i for i, _t in restarted] == [1]
