"""LiveEvent.start/end are documented as "seconds since session start".

Dropped pure-silence spans used to vanish from the session's byte clock,
so every event after a long pause was stamped as if the pause never
happened — the times drifted further from the real session (and from the
timestamps in live-session.wav) with every silent gap.
"""
from __future__ import annotations

import array
import math

from core import live

RATE = 16_000


def _tone(seconds: float, amp: int = 8000, freq: float = 220.0) -> bytes:
    out = array.array("h")
    for i in range(int(RATE * seconds)):
        out.append(int(amp * math.sin(2 * math.pi * freq * i / RATE)))
    return out.tobytes()


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def _feed(session: "live.LiveSession", pcm: bytes, block: int = 2048) -> None:
    for i in range(0, len(pcm), block):
        session._on_frames(pcm[i:i + block], RATE)


def test_event_times_count_the_silence_between_utterances(tmp_path):
    session = live.LiveSession(
        transcribe_chunk=lambda p: "x", work_dir=str(tmp_path / "work")
    )
    # 3 s speech, a 10 s pause, then 3 s speech closed by a short pause.
    _feed(session, _tone(3.0))
    _feed(session, _silence(10.0))
    _feed(session, _tone(3.0) + _silence(0.8))

    events: list = []
    while True:
        try:
            session._consume_one(session._chunks.get_nowait())
        except Exception:
            break
        events += [e for e in session.drain_events() if e.kind == "text"]
    assert len(events) == 2
    # The second utterance really starts after 3 + 10 = 13 s of session
    # audio (its chunk may open slightly earlier, when the leftover pause
    # audio was still buffered) — never right after the first chunk.
    assert events[1].start >= 11.0, events[1].start
    assert events[1].start < 14.0, events[1].start
    assert events[0].start == 0.0
