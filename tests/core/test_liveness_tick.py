"""Tests for core._liveness_tick.liveness_tick.

The helper is wrapped around every long, silent, GIL-holding C call
(demucs, stable-ts, sherpa-onnx, whisper.cpp, llama-cpp) so the parent's
worker-liveness watchdog doesn't SIGTERM a worker that is busy rather
than wedged. These tests pin the two properties the watchdog relies on:
ticks keep coming while the body runs, and the ticker ALWAYS stops when
the body exits — normally or by raising — because a leaked ticker would
keep emitting log lines (and holding a reference to ``log_cb``) for the
rest of the process's life.
"""
from __future__ import annotations

import threading
import time

from core._liveness_tick import liveness_tick

_TICKER_PREFIX = "liveness-"


def _wait_for_tickers_to_stop(timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(t.name.startswith(_TICKER_PREFIX) for t in threading.enumerate()):
            return True
        time.sleep(0.005)
    return False


def test_liveness_tick_emits_periodic_lines():
    lines: list[str] = []
    with liveness_tick(lines.append, "alignment", interval_seconds=0.02):
        time.sleep(0.2)
    assert any("alignment - still working..." in s for s in lines)


def test_liveness_tick_stops_after_the_body_exits():
    lines: list[str] = []
    with liveness_tick(lines.append, "job", interval_seconds=0.01):
        time.sleep(0.03)
    assert _wait_for_tickers_to_stop(), "ticker thread outlived the with block"
    count = len(lines)
    time.sleep(0.05)
    assert len(lines) == count, "ticker emitted after the guard exited"


def test_liveness_tick_stops_when_the_body_raises():
    lines: list[str] = []
    try:
        with liveness_tick(lines.append, "job", interval_seconds=0.01):
            time.sleep(0.03)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert _wait_for_tickers_to_stop(), "ticker thread outlived the raise"
    count = len(lines)
    time.sleep(0.05)
    assert len(lines) == count, "ticker emitted after the body raised"


def test_liveness_tick_stops_when_log_cb_raises():
    """A dead worker / closed pipe must stop ticking, not crash the thread."""
    calls: list[str] = []

    def _broken_log(_msg: str) -> None:
        calls.append("x")
        raise RuntimeError("pipe closed")

    with liveness_tick(_broken_log, "job", interval_seconds=0.01):
        time.sleep(0.05)
    assert _wait_for_tickers_to_stop(), "broken log_cb must not wedge the ticker"
    count = len(calls)
    time.sleep(0.05)
    assert len(calls) == count


def test_liveness_tick_with_none_callback_spawns_no_thread():
    with liveness_tick(None, "job", interval_seconds=0.01):
        assert not any(
            t.name.startswith(_TICKER_PREFIX) for t in threading.enumerate()
        )
