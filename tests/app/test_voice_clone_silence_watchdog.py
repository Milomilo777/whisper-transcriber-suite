"""A voice-clone worker that goes silent is given up on instead of loading forever."""
import io
import threading
import time

import pytest

from app.services import voice_clone_service as vcs


class _FakeProc:
    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = None

    def poll(self):
        return None


def _worker(monkeypatch, silence_s: float) -> vcs.VoiceCloneWorker:
    w = vcs.VoiceCloneWorker("gui.py")
    w._process = _FakeProc()  # type: ignore[assignment]
    monkeypatch.setattr(w, "SILENCE_TIMEOUT_S", silence_s)
    monkeypatch.setattr(w, "WAIT_POLL_S", 0.02)
    killed: list[object] = []
    monkeypatch.setattr(vcs.VoiceCloneWorker, "_kill_process_tree", staticmethod(killed.append))
    w._killed = killed  # type: ignore[attr-defined]
    return w


def test_a_silent_worker_is_stopped_with_a_clear_message(monkeypatch):
    w = _worker(monkeypatch, silence_s=0.2)
    w._last_seen = time.monotonic() - 1000  # nothing heard for a long time
    t0 = time.monotonic()
    with pytest.raises(vcs.VoiceCloneWorkerError, match="stopped responding"):
        w.generate("hi", [], "out.wav", consent_accepted=True)
    assert time.monotonic() - t0 < 5
    assert w._killed  # type: ignore[attr-defined]  # the stuck process tree is ended
    assert not w.is_running()  # the next Generate starts a fresh worker


def test_heartbeats_keep_a_slow_load_alive(monkeypatch):
    w = _worker(monkeypatch, silence_s=0.3)
    stop = threading.Event()

    def beat() -> None:  # what the reader does for every heartbeat line
        while not stop.wait(0.05):
            w._last_seen = time.monotonic()

    def finish() -> None:
        time.sleep(1.0)  # well past the silence limit, but never silent
        with w._lock:
            slot = next(iter(w._pending.values()))
        slot["result"] = {"ok": True}
        slot["event"].set()

    threading.Thread(target=beat, daemon=True).start()
    threading.Thread(target=finish, daemon=True).start()
    try:
        assert w.generate("hi", [], "out.wav", consent_accepted=True) == {"ok": True}
    finally:
        stop.set()
    assert not w._killed  # type: ignore[attr-defined]
