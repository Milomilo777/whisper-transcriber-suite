"""Regression test for the multi-monitor _start() consumer-thread leak.

Hermetic: no real ffplay / yt-dlp / network / Tk. The multi-monitor branch of
``TilingController._start`` is driven with a stubbed ``subprocess.Popen`` whose
SECOND player (a later monitor) fails to launch. The bug: that ``except``
handler re-raised WITHOUT signalling the fan-out ``stop_event`` or waking the
consumer-writer thread already started for the FIRST monitor — so that daemon
thread (blocked on an empty queue) leaked, unbounded across reconnect attempts.

The fix mirrors the not-published / _terminate teardown: set the stop_event and
enqueue a None sentinel per started consumer (then best-effort join) before the
re-raise, so no consumer thread is left running.
"""
from __future__ import annotations

import threading

import pytest

from core import tiling


class _FakeStdin:
    """Stands in for a player's stdin; records writes, never blocks."""

    def __init__(self) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, chunk: bytes) -> int:
        self.writes.append(chunk)
        return len(chunk)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakeProc:
    """Minimal subprocess.Popen stand-in for a spawned helper process."""

    def __init__(self, with_stdin: bool = False) -> None:
        self.stdin = _FakeStdin() if with_stdin else None
        self.stdout = None
        self.stderr = None
        self.waited = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        # Records that the controller reaped this killed child.
        self.waited = True
        return 0


class _LaunchFailure(RuntimeError):
    """Raised by the stub when a later monitor's player 'fails to launch'."""


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make _start reach the multi-monitor consumer loop with no real I/O."""
    monkeypatch.setattr(tiling, "bundled_binary", lambda _name: "yt-dlp")
    monkeypatch.setattr(tiling, "ffplay_path", lambda: "ffplay")
    monkeypatch.setattr(tiling.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(tiling, "kill_process_tree", lambda *_a, **_k: None)
    monkeypatch.setattr(tiling, "new_session_kwargs", lambda: {})


def test_start_launch_failure_does_not_leak_consumer_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common(monkeypatch)

    ctl = tiling.TilingController()
    # No clean-slate teardown noise; we drive _start directly on this gen.
    monkeypatch.setattr(ctl, "_terminate", lambda join=True: None)
    monkeypatch.setattr(ctl, "_drain_stderr", lambda *_a, **_k: None)
    monkeypatch.setattr(ctl, "_fanout", lambda *_a, **_k: None)
    ctl._play_flag = True
    ctl._generation = 7
    ctl._multi_monitor = True

    # Two monitors -> multi-window wall (single is False).
    mons = [
        {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
         "primary": True},
        {"index": 1, "x": 1920, "y": 0, "width": 1920, "height": 1080,
         "primary": False},
    ]
    monkeypatch.setattr(ctl, "_targets", lambda: (mons, True))

    # Popen sequence: [0] yt-dlp, [1] first monitor's ffplay (OK, real consumer
    # thread starts on it), [2] second monitor's ffplay -> RAISES mid-setup.
    spawned = {"n": 0}
    spawned_procs: list[_FakeProc] = []

    def fake_popen(*_a, **_k):
        i = spawned["n"]
        spawned["n"] += 1
        if i == 0:
            proc = _FakeProc(with_stdin=False)   # yt-dlp
        elif i == 1:
            proc = _FakeProc(with_stdin=True)    # first ffplay -> consumer
        else:
            raise _LaunchFailure("later monitor's player failed to launch")
        spawned_procs.append(proc)
        return proc

    monkeypatch.setattr(tiling.subprocess, "Popen", fake_popen)

    # Capture the fan-out stop_event _start creates (it is a LOCAL in the
    # except path, never published to self), so we can assert it was signalled.
    # threading.Thread.__init__ also makes Events, so keep ONLY the one created
    # directly in _start's own frame (not from inside Thread.__init__).
    import sys as _sys

    fanout_events: list[threading.Event] = []
    real_event = threading.Event

    def recording_event() -> threading.Event:
        ev = real_event()
        caller = _sys._getframe(1)
        if caller.f_code.co_name == "_start":
            fanout_events.append(ev)
        return ev

    monkeypatch.setattr(tiling.threading, "Event", recording_event)

    # Snapshot the live (non-daemon-noise) thread set so we can prove the
    # consumer thread started by _start is gone after the failure.
    before = set(threading.enumerate())

    with pytest.raises(_LaunchFailure):
        ctl._start(my_gen=7)

    # The fan-out stop_event must have been signalled by the except handler.
    assert len(fanout_events) == 1 and fanout_events[0].is_set(), (
        "launch failure must signal the fan-out stop_event"
    )

    # No NEW consumer thread may still be running. The writer for monitor #1
    # was started and (pre-fix) would block forever on its empty queue; the
    # fix enqueues a None sentinel and joins it.
    new_threads = [
        t for t in threading.enumerate()
        if t not in before and t.is_alive()
    ]
    assert new_threads == [], (
        "launch failure mid-setup leaked consumer thread(s): "
        + repr([t.name for t in new_threads])
    )

    # Both already-spawned children were killed by the except handler and
    # must also be reaped (wait()-ed), or a flapping outage that keeps
    # failing here accumulates POSIX zombies.
    assert [p.waited for p in spawned_procs] == [True, True]


def test_start_superseded_launch_reaps_killed_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launch that a later Stop/new-run supersedes tears its fresh pipeline
    down (the not-published path) and must reap those children too."""
    _patch_common(monkeypatch)

    ctl = tiling.TilingController()
    monkeypatch.setattr(ctl, "_terminate", lambda join=True: None)
    monkeypatch.setattr(ctl, "_drain_stderr", lambda *_a, **_k: None)
    ctl._play_flag = True
    ctl._generation = 3
    ctl._multi_monitor = False

    mon = {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
           "primary": True}
    monkeypatch.setattr(ctl, "_targets", lambda: ([mon], False))

    # Active at the top of _start (so it launches); superseded by the time
    # it publishes (so the not-published teardown runs).
    states = iter([True, False])
    monkeypatch.setattr(ctl, "_is_active", lambda _gen: next(states))

    procs: list[_FakeProc] = []

    def fake_popen(*_a, **_k):
        proc = _FakeProc(with_stdin=(len(procs) == 1))
        procs.append(proc)
        return proc

    monkeypatch.setattr(tiling.subprocess, "Popen", fake_popen)

    ctl._start(my_gen=3)

    assert len(procs) == 2  # yt-dlp + the single fullscreen ffplay
    assert all(p.waited for p in procs)
    assert ctl._ytdlp is None
    assert ctl._ffplay == []
