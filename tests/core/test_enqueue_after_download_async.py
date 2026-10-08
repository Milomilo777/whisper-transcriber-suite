"""Hardest edge cases for the async transcribe-after-download enqueue.

``App.enqueue_transcription_from_download`` runs on the Tk main thread
(the download-complete handler) and must NOT block while the Whisper
model loads — a synchronous wait there froze the whole UI. It spawns a
worker if none is alive and polls ``ready_workers()`` with ``after()``.

These tests drive the *real* method with a duck-typed ``self`` so no Tk
root or worker subprocess is created: a fake ``after`` records pending
callbacks the test pumps by hand, and a fake service flips readiness on
demand.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("tkinter")

from app.app import App


class _FakeAfter:
    """Stand-in for tk.Misc.after — records callbacks, runs on demand."""

    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, _ms, cb):
        self.pending.append(cb)
        return f"after#{len(self.pending)}"

    def pump(self) -> None:
        """Run every currently-pending callback once (they may reschedule)."""
        batch, self.pending = self.pending, []
        for cb in batch:
            cb()


class _FakeService:
    def __init__(self, *, ready: bool = False, active: bool = False) -> None:
        self._ready = ready
        self._active = active
        self.spawns = 0

    def ready_workers(self):
        return [object()] if self._ready else []

    def active_workers(self):
        return [object()] if self._active else []

    def start_worker(self, temporary: bool = False) -> None:
        self.spawns += 1
        self._active = True


class _FakeApp:
    def __init__(self, svc: _FakeService, after: _FakeAfter) -> None:
        self.transcription_service = svc
        self.after = after
        self.queue: list = []
        self.logs: list[str] = []
        self.refreshed = 0

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def refresh(self) -> None:
        self.refreshed += 1

    def _warn_english_only(self, language, name) -> None:
        pass

    # Bind the real helper so these tests exercise the actual scheduling
    # logic that enqueue_transcription_from_download now delegates to.
    _when_worker_ready = App._when_worker_ready


def _call(app: _FakeApp) -> None:
    App.enqueue_transcription_from_download(app, "/tmp/clip.mp4", "en")  # type: ignore[arg-type]


def test_enqueue_immediate_when_worker_ready():
    svc = _FakeService(ready=True)
    after = _FakeAfter()
    app = _FakeApp(svc, after)
    _call(app)
    assert len(app.queue) == 1       # enqueued synchronously
    assert svc.spawns == 0           # reused the ready worker
    assert after.pending == []       # no polling scheduled


def test_enqueue_spawns_worker_then_enqueues_when_ready():
    svc = _FakeService(ready=False, active=False)
    after = _FakeAfter()
    app = _FakeApp(svc, after)
    _call(app)
    assert svc.spawns == 1           # spawned exactly one worker
    assert app.queue == []           # not enqueued yet — model loading
    assert len(after.pending) == 1   # polling scheduled (no blocking)
    svc._ready = True                # model finished loading
    after.pump()
    assert len(app.queue) == 1
    assert app.refreshed == 1


def test_enqueue_reuses_in_flight_worker_without_second_spawn():
    svc = _FakeService(ready=False, active=True)  # a worker is already loading
    after = _FakeAfter()
    app = _FakeApp(svc, after)
    _call(app)
    assert svc.spawns == 0           # don't spawn a duplicate
    assert len(after.pending) == 1


def test_enqueue_keeps_polling_until_ready():
    svc = _FakeService(ready=False, active=False)
    after = _FakeAfter()
    app = _FakeApp(svc, after)
    _call(app)
    for _ in range(3):               # several poll cycles, still loading
        assert app.queue == []
        assert len(after.pending) == 1
        after.pump()
    svc._ready = True
    after.pump()
    assert len(app.queue) == 1


def test_enqueue_drops_task_on_load_timeout(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    svc = _FakeService(ready=False, active=False)
    after = _FakeAfter()
    app = _FakeApp(svc, after)
    _call(app)                       # deadline = 1000 + HEADLESS_READY_TIMEOUT_S
    clock["t"] = 1000.0 + 10_000.0   # jump well past the timeout
    after.pump()
    assert app.queue == []           # task dropped, not queued forever
    assert any("timed out" in m for m in app.logs)
    assert after.pending == []       # gave up — no reschedule
