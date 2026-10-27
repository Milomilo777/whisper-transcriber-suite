"""VoiceCloneWorker.generate must fail fast when the session dies mid-call."""
from __future__ import annotations

import io
import time
from types import SimpleNamespace

from app.services import voice_clone_service as vcs
from app.services.voice_clone_service import VoiceCloneWorker, VoiceCloneWorkerError


class _ParkedStdout:
    """A stdout that never reaches EOF, so the reader thread stays parked and
    cannot answer (or re-fail) the request asynchronously during the test."""

    def __iter__(self) -> "_ParkedStdout":
        while True:
            time.sleep(60.0)


class _ParkedProc(SimpleNamespace):
    """A live-looking process whose reader stays parked (stdout never EOFs),
    so nothing asynchronous answers (or re-fails) the request mid-test."""

    def __init__(self) -> None:
        super().__init__(stdin=io.StringIO(), stdout=_ParkedStdout(), pid=77)

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_generate_fails_fast_when_session_dies_mid_call(monkeypatch):
    worker = VoiceCloneWorker("gui.py")
    proc = _ParkedProc()
    monkeypatch.setattr(vcs.subprocess, "Popen", lambda cmd, **kw: proc)
    worker.start()
    # The session dies between generate()'s liveness check and the slot
    # registration: uuid.uuid4() (which builds the request id) is the hook.
    def _die_mid_call():
        worker._dead.set()
        worker._fail_all_pending("Voice-clone session stopped.")
        worker._process = None
        return type("U", (), {"hex": "deadbeef"})()

    monkeypatch.setattr(vcs.uuid, "uuid4", _die_mid_call)
    # Shrink the wait constants so the test distinguishes "fails fast" from
    # "waits out the whole silence window" (300 s at real values).
    worker.WAIT_POLL_S = 0.05
    worker.SILENCE_TIMEOUT_S = 6.0
    monkeypatch.setattr(vcs, "GENERATE_TIMEOUT_S", 60.0)
    began = time.monotonic()
    try:
        worker.generate(
            "hello", [], "out.wav", consent_accepted=True, timeout_s=60.0,
        )
    except VoiceCloneWorkerError as e:
        elapsed = time.monotonic() - began
        assert "not running" in str(e), str(e)
        # Must fail on the first poll ticks, not after the silence window.
        assert elapsed < 3.0, f"generate() hung {elapsed:.1f}s after the session died"
    else:
        raise AssertionError("generate() should have raised")
