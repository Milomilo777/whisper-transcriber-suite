"""Audit [17]: worker_for_event token routing (the PID-recycle fix).

Prefers a per-worker token; falls back to PID + worker_id for the
synthetic worker_exit event that can't carry a token. A regression here
silently delivers a dead worker's events onto a freshly-spawned worker.
"""
from __future__ import annotations

from app.services.transcription_service import TranscriptionService


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class _FakeApp:
    def __init__(self, workers):
        self.workers = workers


def _svc(workers):
    return TranscriptionService(_FakeApp(workers))  # type: ignore[arg-type]


def _workers():
    return [
        {"id": 1, "token": "tok-A", "process": _FakeProc(100)},
        {"id": 2, "token": "tok-B", "process": _FakeProc(200)},
    ]


def test_token_match_wins_over_pid():
    ws = _workers()
    svc = _svc(ws)
    # Token B with A's (recycled) pid must still route to B.
    got = svc.worker_for_event({"_token": "tok-B", "_pid": 100, "_worker_id": 1})
    assert got is ws[1]


def test_token_routes_despite_recycled_pid():
    ws = _workers()
    svc = _svc(ws)
    got = svc.worker_for_event({"_token": "tok-A", "_pid": 200, "_worker_id": 2})
    assert got is ws[0]


def test_tokenless_worker_exit_falls_back_to_pid_and_id():
    ws = _workers()
    svc = _svc(ws)
    got = svc.worker_for_event(
        {"event": "worker_exit", "_token": "", "_pid": 100, "_worker_id": 1}
    )
    assert got is ws[0]


def test_no_match_returns_none():
    ws = _workers()
    svc = _svc(ws)
    assert svc.worker_for_event({"_token": "x", "_pid": 999, "_worker_id": 9}) is None


def test_stale_token_does_not_fall_back_to_pid_match():
    """Found by an adversarial review (2026-09-22): a PRESENT but
    non-matching token used to fall through to the PID+worker_id match
    below -- exactly defeating the protection the token exists for.
    restart_worker() assigns worker["id"]=1 a FRESH token while a
    lingering event from the dead instance (still carrying the OLD
    token) sits queued; if the OS also recycled the PID, the stale
    event's _pid/_worker_id now match the freshly-restarted worker too,
    and the old fallback silently routed it there -- crediting the live
    task with a dead task's progress/done."""
    ws = _workers()
    # Simulate restart_worker() having already assigned worker 1 a new
    # token by the time this event (still carrying the OLD token) is
    # processed.
    ws[0]["token"] = "tok-A-after-restart"
    svc = _svc(ws)
    stale_event = {"_token": "tok-A", "_pid": 100, "_worker_id": 1}
    assert svc.worker_for_event(stale_event) is None
