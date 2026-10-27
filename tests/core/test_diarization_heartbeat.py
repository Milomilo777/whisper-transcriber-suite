"""B2: a heartbeat while the diarisation worker is still segmenting.

sherpa-onnx prints nothing during its segmentation pass (~100 s for 12 min
of audio), so before the first "progress" event no progress_cb fires: the
UI bar freezes and the parent's liveness watchdog sees no events. While no
real progress has arrived, diarize() must now emit a periodic 0.0-fraction
heartbeat through the same progress_cb (the transcriber maps it to the 90
percent slot, so the bar keeps moving and events keep flowing).
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from typing import Any

import pytest

from core import diarization


@pytest.fixture
def fake_worker(monkeypatch, tmp_path):
    """Make diarize() start a stand-in worker that runs ``body`` (Python code)."""
    started: list[Any] = []
    real_popen = diarization.subprocess.Popen

    def spy_popen(*a, **k):
        p = real_popen(*a, **k)
        started.append(p)
        return p

    monkeypatch.setattr(diarization, "availability_reason", lambda: "")
    monkeypatch.setattr("core.transcriber.get_duration", lambda p: 10.0)
    monkeypatch.setattr(diarization.subprocess, "Popen", spy_popen)

    def use(body: str) -> list[Any]:
        script = tmp_path / "worker_stub.py"
        script.write_text(
            "import json, os, sys, time\n"
            "def emit(ev):\n"
            "    sys.stdout.write(json.dumps(ev) + '\\n'); sys.stdout.flush()\n"
            "request = json.loads(sys.stdin.readline())\n"
            + textwrap.dedent(body),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            diarization, "_worker_command", lambda: [sys.executable, "-u", str(script)]
        )
        return started

    return use


def test_heartbeat_while_waiting_for_the_first_progress(fake_worker, monkeypatch):
    """A silent worker still produces periodic progress_cb calls."""
    fake_worker("""
        time.sleep(2.0)
        emit({"event": "done", "segments": []})
    """)
    monkeypatch.setattr(diarization, "SEGMENTATION_HEARTBEAT_S", 0.5)

    seen: list[float] = []
    t0 = time.monotonic()
    assert diarization.diarize("talk.wav", progress_cb=seen.append) == []
    assert time.monotonic() - t0 >= 1.5

    # The worker emitted nothing, so every call was a heartbeat.
    assert seen and all(f == 0.0 for f in seen)
    assert len(seen) >= 2


def test_heartbeat_stops_once_real_progress_arrives(fake_worker, monkeypatch):
    """After the worker's own progress events no 0.0 heartbeats interleave."""
    fake_worker("""
        time.sleep(1.2)
        emit({"event": "progress", "fraction": 0.5})
        emit({"event": "progress", "fraction": 1.0})
        time.sleep(0.3)
        emit({"event": "done", "segments": []})
    """)
    monkeypatch.setattr(diarization, "SEGMENTATION_HEARTBEAT_S", 0.3)

    seen: list[float] = []
    assert diarization.diarize("talk.wav", progress_cb=seen.append) == []

    assert seen[-2:] == [0.5, 1.0]
    assert 0.0 in seen  # heartbeats ran before the first real progress
    assert 0.0 not in seen[seen.index(0.5):]  # ...and stopped after it
