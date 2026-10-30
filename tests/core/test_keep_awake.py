"""core/keep_awake.py: no idle sleep while a transcription runs, never a crash."""
from __future__ import annotations

import sys

import pytest

from core import keep_awake as ka


def test_windows_sets_and_resets_the_request(monkeypatch):
    calls = []
    monkeypatch.setattr(ka, "_windows_set", lambda flags: calls.append(flags) or True)
    with ka.keep_awake("win32") as active:
        assert active is True
        assert calls == [ka.ES_CONTINUOUS | ka.ES_SYSTEM_REQUIRED]
    assert calls[-1] == ka.ES_CONTINUOUS


def test_windows_reset_runs_when_the_job_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(ka, "_windows_set", lambda flags: calls.append(flags) or True)
    with pytest.raises(RuntimeError):
        with ka.keep_awake("win32"):
            raise RuntimeError("job failed")
    assert calls[-1] == ka.ES_CONTINUOUS


def test_a_failing_request_never_stops_the_job(monkeypatch):
    def boom(flags):
        raise OSError("no kernel32")

    monkeypatch.setattr(ka, "_windows_set", boom)
    ran = []
    with ka.keep_awake("win32") as active:
        ran.append(1)
    assert active is False and ran == [1]


def test_macos_runs_caffeinate_for_this_process_and_stops_it(monkeypatch):
    started = []

    class FakeProc:
        terminated = False

        def __init__(self, args, **kw):
            started.append(args)

        def terminate(self):
            FakeProc.terminated = True

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(ka.os.path, "exists", lambda p: p == ka.CAFFEINATE)
    monkeypatch.setattr(ka.subprocess, "Popen", FakeProc)
    with ka.keep_awake("darwin") as active:
        assert active is True
        assert FakeProc.terminated is False
    assert started == [[ka.CAFFEINATE, "-i", "-w", str(ka.os.getpid())]]
    assert FakeProc.terminated is True


def test_other_systems_do_nothing(monkeypatch):
    monkeypatch.setattr(ka.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("must not start anything"))
    with ka.keep_awake("linux") as active:
        assert active is False


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows API")
def test_real_windows_call_succeeds():
    with ka.keep_awake() as active:
        assert active is True
