"""Keep the computer from going to sleep by itself while a transcription runs.

A long CPU transcription on a laptop used to be suspended by the system's
idle-sleep timer (CPU work does not count as activity on Windows). On
Windows the parent's liveness clock (``time.monotonic``) keeps counting
through sleep, so the first check after waking saw minutes of silence and
replaced the "hung" worker: the job ended as an error.

:func:`keep_awake` asks the system not to idle-sleep while the block runs.
Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`` on
the calling thread, reset afterwards. macOS: ``caffeinate -i -w <pid>`` for
the duration (``-w`` also ends it if this process dies). The display may
still turn off, and the user can still put the computer to sleep or close
the lid. Elsewhere, or when the request fails, nothing changes and the run
goes on.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
CAFFEINATE = "/usr/bin/caffeinate"


def _windows_set(flags: int) -> bool:
    import ctypes

    kernel32 = getattr(ctypes, "windll").kernel32
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
    # Returns the previous state (ES_CONTINUOUS at least), or 0 on failure.
    return bool(kernel32.SetThreadExecutionState(ctypes.c_uint32(flags)))


@contextmanager
def keep_awake(platform: str | None = None) -> Generator[bool, None, None]:
    """Block idle sleep for the duration; yields True when the request took effect."""
    platform = platform or sys.platform
    active = False
    proc: Any = None
    try:
        if platform == "win32":
            active = _windows_set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif platform == "darwin" and os.path.exists(CAFFEINATE):
            proc = subprocess.Popen(
                [CAFFEINATE, "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            active = True
    except Exception as e:  # noqa: BLE001 - sleep prevention is best effort
        logger.info("Could not keep the computer awake (%s: %s)", type(e).__name__, e)
    if not active:
        logger.debug("keep_awake: not active on %s", platform)
    try:
        yield active
    finally:
        if platform == "win32" and active:
            try:
                _windows_set(ES_CONTINUOUS)
            except Exception as e:  # noqa: BLE001
                logger.info("Could not reset the sleep request (%s: %s)", type(e).__name__, e)
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception as e:  # noqa: BLE001
                logger.info("caffeinate did not stop cleanly (%s: %s)", type(e).__name__, e)
