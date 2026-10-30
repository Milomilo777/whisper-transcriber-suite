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


def test_a_sleep_gap_is_not_counted_as_worker_silence(monkeypatch):
    clock = [1000.5]
    svc, worker, restarted = _service(monkeypatch, clock)
    svc.poll()                      # last poll before the sleep (0.5 s of silence)
    clock[0] = 1000.5 + 600         # 10 minutes asleep, no events queued
    svc.poll()
    assert restarted == []
    woke = clock[0]
    assert worker["last_event_at"] == 1000.0 + 600  # the gap is excused, nothing more
    # A worker that really stays silent is still caught: 0.5 s before the
    # sleep + 120 s after it.
    for _ in range(140):
        clock[0] += 1               # polls keep running, worker silent
        svc.poll()
    assert [(i, t - woke) for i, t in restarted] == [(1, 120)]


def test_short_sleeps_are_excused_too(monkeypatch):
    clock = [1000.5]
    svc, worker, restarted = _service(monkeypatch, clock)
    worker["last_event_at"] = 1000.0
    svc.poll()
    clock[0] = 1000.5 + 25          # a 25 s sleep
    svc.poll()
    assert worker["last_event_at"] == 1000.0 + 25
    assert restarted == []


def test_a_worker_stamped_during_the_gap_is_left_alone(monkeypatch):
    clock = [1000.5]
    svc, worker, restarted = _service(monkeypatch, clock)
    svc.poll()                      # polling then stops (no busy worker) ...
    clock[0] = 2000.0
    worker["last_event_at"] = 1999.0  # ... a worker is spawned later
    svc.poll()
    assert worker["last_event_at"] == 1999.0  # not pushed into the future


def test_silence_without_a_gap_still_restarts_the_worker(monkeypatch):
    clock = [1000.5]
    svc, _worker, restarted = _service(monkeypatch, clock)
    while clock[0] < 1000 + svc.LIVENESS_TIMEOUT_S + 5:
        clock[0] += 1               # regular polls, worker silent
        svc.poll()
    assert [i for i, _t in restarted] == [1]
