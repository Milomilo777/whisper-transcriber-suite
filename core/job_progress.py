"""One emission point for monotonic progress shared by every job frontend."""
from __future__ import annotations

import math
import threading
from typing import Callable


class JobProgress:
    """Reserve post-processing space; repeated values still deliver heartbeats."""

    def __init__(self, callback: Callable[[int], None] | None, *, diarization: bool):
        self._callback = callback
        self._transcription_end = 85 if diarization else 99
        self._value = 0
        self._lock = threading.RLock()

    def update(self, phase: str, fraction: float) -> int:
        slices = {"transcription": (0, self._transcription_end),
                  "diarization": (85, 14), "finish": (99, 1)}
        start, width = slices[phase]
        with self._lock:
            if not math.isfinite(fraction):
                return self._value
            candidate = start + int(min(1.0, max(0.0, fraction)) * width)
            self._value = max(self._value, candidate)
            if self._callback is not None:
                self._callback(self._value)
            return self._value

    def transcription(self, percent: int) -> None:
        self.update("transcription", percent / 100)

    def diarization(self, fraction: float) -> None:
        self.update("diarization", fraction)

    def finish(self, _percent: int = 100) -> None:
        self.update("finish", 1.0)
