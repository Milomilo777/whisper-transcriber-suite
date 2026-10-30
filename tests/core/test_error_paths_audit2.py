from __future__ import annotations
import time
from app.services.transcription_service import TranscriptionService
from tests.core.test_liveness_watchdog import _FakeApp, _AliveProc


def test_transcription_service_ignores_system_clock_jumps(monkeypatch):
    proc = _AliveProc()
    worker = {
        "id": 1,
        "token": "tok1",
        "process": proc,
        "last_event_at": 0.0,
    }

    app = _FakeApp([worker])
    service = TranscriptionService(app)

    # Push a heartbeat event
    app.worker_events.put({
        "event": "heartbeat",
        "_worker_id": 1,
        "token": "tok1",
        "_pid": proc.pid
    })

    # Process the heartbeat to stamp last_event_at
    service._poll_once()

    assert worker["last_event_at"] > 0.0

    # Now simulate a system clock jump by 10,000s forward on time.time(),
    # while time.monotonic() only advances by 1s.
    restarted_workers = []
    monkeypatch.setattr(service, "_restart_wedged_worker", lambda w, dt: restarted_workers.append(w))
    monkeypatch.setattr(service, "_expire_dead_workers", lambda now: None)

    real_time = time.time()
    real_monotonic = time.monotonic()

    monkeypatch.setattr(time, "time", lambda: real_time + 10000.0)
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic + 1.0)

    # This should NOT trigger a restart because monotonic only advanced by 1s
    service._poll_once()
    assert len(restarted_workers) == 0


def test_transcription_service_restarts_on_real_monotonic_timeout(monkeypatch):
    proc = _AliveProc()
    worker = {
        "id": 2,
        "token": "tok2",
        "process": proc,
        "last_event_at": 0.0,
    }

    app = _FakeApp([worker])
    service = TranscriptionService(app)

    app.worker_events.put({
        "event": "heartbeat",
        "_worker_id": 2,
        "token": "tok2",
        "_pid": proc.pid
    })

    service._poll_once()

    restarted_workers = []
    monkeypatch.setattr(service, "_restart_wedged_worker", lambda w, dt: restarted_workers.append(w))
    monkeypatch.setattr(service, "_expire_dead_workers", lambda now: None)

    # Simulate real elapsed time exceeding timeout. Polls keep running through
    # the silence (every 100 ms in the app; 1 s steps here): one jump with no
    # poll in between is a system sleep, which the watchdog must not count
    # (tests/core/test_liveness_after_sleep.py).
    real_monotonic = time.monotonic()
    clock = [real_monotonic]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    while not restarted_workers and clock[0] < real_monotonic + service.LIVENESS_TIMEOUT_S + 10.0:
        clock[0] += 1.0
        service._poll_once()

    assert len(restarted_workers) == 1
    assert restarted_workers[0]["id"] == 2
