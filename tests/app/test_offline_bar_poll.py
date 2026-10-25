"""The Work-offline bar must not poll the connection table on the Tk thread.

``tick`` called ``offline.poll_connections`` synchronously: that walks
psutil's per-process socket tables for the app AND every worker child,
which stalls Tk event processing for as long as it takes — every poll
cycle, while the bar is showing. The module's own NetworkLogWindow.verify
already runs its work off-thread; the bar must too.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from typing import Callable

import pytest

from app.widgets import offline_status as osm
from core import offline


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


class _Bridge:
    """post_to_main that just queues callbacks for the test to drain."""

    def __init__(self) -> None:
        self.queue: list[Callable[[], None]] = []

    def __call__(self, fn: Callable[[], None]) -> None:
        self.queue.append(fn)

    def drain(self) -> None:
        while self.queue:
            self.queue.pop(0)()


def test_tick_returns_before_a_slow_poll_finishes(root):
    bridge = _Bridge()
    started = threading.Event()
    release = threading.Event()

    def slow_poll() -> offline.ConnectionCheck:
        started.set()
        release.wait(timeout=5.0)
        return offline.ConnectionCheck(time.time(), True)

    bar = osm.OfflineStatusBar(root, post_to_main=bridge, poll=slow_poll)
    bar.pack()
    try:
        start = time.monotonic()
        bar.tick()
        took = time.monotonic() - start
        assert started.wait(timeout=2.0), "the poll never started"
        # The whole point: the Tk thread does not wait for the poll.
        assert took < 0.4, f"tick blocked the Tk thread for {took:.2f}s"
        release.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and bar.check is None:
            root.update()
            bridge.drain()
            time.sleep(0.02)
        assert bar.check is not None and bar.check.ok
    finally:
        bar.destroy()


def test_poll_failure_is_a_reported_check_not_a_crash(root):
    bridge = _Bridge()

    def bad_poll() -> offline.ConnectionCheck:
        raise RuntimeError("psutil exploded")

    bar = osm.OfflineStatusBar(root, post_to_main=bridge, poll=bad_poll)
    bar.pack()
    try:
        bar.tick()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and bar.check is None:
            root.update()
            bridge.drain()
            time.sleep(0.02)
        assert bar.check is not None
        assert bar.check.ok is False
        assert "psutil exploded" in (bar.check.error or "")
    finally:
        bar.destroy()


def test_a_bar_hidden_during_a_poll_does_not_start_polling_again(root):
    bridge = _Bridge()
    started = threading.Event()
    release = threading.Event()

    def slow_poll() -> offline.ConnectionCheck:
        started.set()
        release.wait(timeout=5.0)
        return offline.ConnectionCheck(time.time(), True)

    bar = osm.OfflineStatusBar(root, post_to_main=bridge, poll=slow_poll)
    bar.pack()
    try:
        bar.tick()
        assert started.wait(timeout=2.0), "the poll never started"
        bar.hide()  # unpacks and cancels the timer while the poll is in the air
        release.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and bar.check is None:
            root.update()
            bridge.drain()
            time.sleep(0.02)
        assert bar.check is not None
        assert bar._after_id is None, "a hidden bar re-armed its poll timer"
    finally:
        bar.destroy()
