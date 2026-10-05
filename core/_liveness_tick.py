"""Periodic-log helper to keep silent C calls visible to the
worker-liveness watchdog.

The parent's :data:`TranscriptionService.LIVENESS_TIMEOUT_S`
watchdog assumes "no events from worker for X seconds" implies a
wedged worker and SIGTERMs it. Single long-running C-level calls
(sherpa-onnx, ctranslate2, demucs subprocess, llama-cpp, stable-ts
align) routinely run longer than that window with the GIL held and
emit nothing to stdout while they run, so the parent kills the
worker mid-pass on slow hardware. The just-fixed diarisation case
is the prototype; the same shape recurred in four more stalls
(P0-1 to P0-4) found by the 2026-05-23 stability audit.

This module provides one tiny context manager,
:func:`liveness_tick`, that spawns a daemon thread emitting one
log line every ``interval_seconds`` for the duration of the
``with`` body. The log line travels through the worker's existing
event channel (any event on the worker's stdout resets
``last_event_at`` on the parent side), so wrapping a silent C call
in ``with liveness_tick(log_cb, "label"): ...`` is sufficient to
keep the watchdog quiet.

Behaviour notes:

  * If ``log_cb`` is ``None`` the helper is a no-op; the body runs
    unwrapped with zero overhead.
  * The first tick fires after one full interval, not immediately,
    because the caller normally emits its own kickoff log line just
    before the ``with`` block.
  * The ticker thread is a daemon and is not joined on exit — on
    process shutdown we never want the parent caller to block
    waiting for the next interval tick.
  * Exceptions raised inside ``log_cb`` (e.g. broken pipe to a
    dead worker) silently stop the ticker; they are deliberately
    not propagated because the body's own outcome is what callers
    care about.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator


@contextmanager
def liveness_tick(
    log_cb: Callable[[str], None] | None,
    label: str,
    interval_seconds: float = 10.0,
) -> Iterator[None]:
    """Emit a periodic log line so a long-running C call still
    looks "alive" to the worker-liveness watchdog.

    Any event on the worker's stdout resets the parent's
    ``LIVENESS_TIMEOUT_S``, so calling
    ``log_cb(f"{label} - still working...")`` every
    ``interval_seconds`` keeps the watchdog quiet during
    GIL-holding C calls (sherpa-onnx, ctranslate2, demucs subprocess
    ``.wait()``, llama-cpp inference, ...).
    """
    if log_cb is None:
        yield
        return

    stop_event = threading.Event()

    def _ticker() -> None:
        # First tick after one interval, not immediately - the
        # call itself usually emits its own kickoff log line.
        while not stop_event.wait(interval_seconds):
            try:
                log_cb(f"{label} - still working...")
            except Exception:  # noqa: BLE001
                # log_cb landing on a closed pipe / dead worker is
                # not our problem; just stop ticking.
                break

    t = threading.Thread(target=_ticker, name=f"liveness-{label}", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop_event.set()
        # Don't join - daemon thread; on shutdown we don't want to
        # block the parent caller waiting for the next interval tick.
