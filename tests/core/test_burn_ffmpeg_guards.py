"""Two more defect-hunt findings in _run_ffmpeg:

1. A cancel flag that flips after ffmpeg exits 0 on its own (during the
   0.1 s poll sleep or the reader joins) must NOT discard the completed
   encode — burn()'s documented contract keeps the finished file.
2. A raising caller callback (on_process / cancel_check) must not leak
   a live ffmpeg: the process is killed before the error propagates.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from core import burn_subs as burn


class _FakeProc:
    """An ffmpeg stand-in: one empty poll, then exits 0; records kills."""

    def __init__(self):
        self._polls = 0
        self.returncode = None
        self.killed = False
        self.waited = 0
        self.stdout = open(os.devnull, "rb")
        self.stderr = open(os.devnull, "rb")

    def poll(self):
        self._polls += 1
        if self._polls > 1:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):  # noqa: ARG002
        self.waited += 1
        self.returncode = 0
        return 0

    def kill(self):
        self.killed = True


def test_cancel_after_a_completed_encode_keeps_the_file(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(burn.subprocess, "Popen", lambda *a, **k: proc)
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        # False during the whole poll loop; True by the post-loop re-check
        # (the user clicked cancel in the 0.1 s sleep / reader-join window).
        return calls["n"] > 1

    burn._run_ffmpeg(
        ["ffmpeg", "-i", "in.mp4", "out.mp4"],
        timeout=60, duration_s=10.0, cancel_check=cancel_check,
    )
    assert proc.returncode == 0
    assert not proc.killed


def test_raising_on_process_callback_kills_the_encode(monkeypatch):
    # A REAL sleeper process: kill_process_tree shells out to taskkill on
    # Windows, so only a live child can prove the leak is closed.
    procs: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def _popen(*a, **k):
        p = real_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        procs.append(p)
        return p

    monkeypatch.setattr(burn.subprocess, "Popen", _popen)

    def _boom(p):  # noqa: ARG001
        raise RuntimeError("callback is buggy")

    with pytest.raises(RuntimeError):
        burn._run_ffmpeg(
            ["ffmpeg", "-i", "in.mp4", "out.mp4"],
            timeout=60, on_process=_boom,
        )
    proc = procs[0]
    deadline = time.monotonic() + 10.0
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert proc.poll() is not None  # killed, not left running for 60 s
