"""Tests for the live transcription engine (core/live.py).

The segmenter is the part that decides transcript quality, so it is
tested against synthetic audio rather than mocked: cutting mid-word, or
sending silence to the model, is what makes a live transcript junk.

Nothing here needs a sound card, a model, or a UI.
"""
from __future__ import annotations

import array
import math
import os
import queue
import threading
import time
import wave

import pytest

from core import live


RATE = 16_000


def _pcm(seconds: float, *, amplitude: float, freq: float = 220.0,
         rate: int = RATE) -> bytes:
    """Mono int16 tone at a given amplitude (0..1). amplitude=0 -> silence."""
    n = int(seconds * rate)
    peak = int(amplitude * 32767)
    samples = array.array(
        "h",
        (int(peak * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)),
    )
    return samples.tobytes()


def _speech(seconds: float, **kw) -> bytes:
    return _pcm(seconds, amplitude=0.5, **kw)


def _silence(seconds: float, **kw) -> bytes:
    return _pcm(seconds, amplitude=0.0, **kw)


def _feed_in_blocks(seg: live.Segmenter, pcm: bytes,
                    block_s: float = 0.064) -> list[bytes]:
    """Feed audio the way a capture backend does: small fixed blocks."""
    block = int(block_s * seg.config.sample_rate) * 2
    out: list[bytes] = []
    for i in range(0, len(pcm), block):
        out.extend(seg.feed(pcm[i:i + block]))
    return out


def _seconds(pcm: bytes, rate: int = RATE) -> float:
    return len(pcm) / float(rate * 2)


# ------------------------------------------------------------------- RMS


def test_rms_separates_speech_from_silence():
    assert live.block_rms(_silence(0.1)) == pytest.approx(0.0, abs=1e-6)
    assert live.block_rms(_speech(0.1)) > 0.2


def test_rms_of_empty_and_odd_length_input():
    assert live.block_rms(b"") == 0.0
    assert live.block_rms(b"\x01") == 0.0  # half a sample, not a crash


def test_rms_scales_with_amplitude():
    quiet = live.block_rms(_pcm(0.1, amplitude=0.01))
    loud = live.block_rms(_pcm(0.1, amplitude=0.9))
    assert quiet < loud


# ------------------------------------------------------------- segmenting


def test_no_chunk_before_the_minimum_length():
    seg = live.Segmenter()
    assert _feed_in_blocks(seg, _speech(1.0)) == []
    assert seg.buffered_seconds == pytest.approx(1.0, abs=0.05)


def test_speech_then_pause_produces_one_chunk():
    seg = live.Segmenter()
    chunks = _feed_in_blocks(seg, _speech(3.0) + _silence(0.8))
    assert len(chunks) == 1
    # The chunk covers the speech plus the pause that closed it.
    assert 3.0 <= _seconds(chunks[0]) <= 4.2


def test_a_pause_too_short_does_not_cut():
    """Natural gaps between words must not each become a chunk."""
    seg = live.Segmenter()
    chunks = _feed_in_blocks(seg, _speech(3.0) + _silence(0.2) + _speech(1.0))
    assert chunks == []


def test_two_utterances_produce_two_chunks():
    seg = live.Segmenter()
    audio = (_speech(2.5) + _silence(0.8)
             + _speech(2.5) + _silence(0.8))
    chunks = _feed_in_blocks(seg, audio)
    assert len(chunks) == 2


def test_continuous_speech_is_force_cut_at_the_maximum():
    """A monologue with no pause must still produce output."""
    cfg = live.SegmenterConfig(max_chunk_s=5.0)
    seg = live.Segmenter(config=cfg)
    chunks = _feed_in_blocks(seg, _speech(12.0))
    assert len(chunks) >= 2
    for c in chunks:
        assert _seconds(c) <= cfg.max_chunk_s + 0.2


def test_forced_cut_prefers_a_recent_quiet_moment():
    """Cutting mid-word transcribes as nothing or the wrong word.

    With a short quiet patch just before the deadline, the split should
    land there rather than exactly on the deadline.
    """
    cfg = live.SegmenterConfig(max_chunk_s=5.0, backtrack_s=1.0,
                               silence_hold_s=10.0)  # disable pause cuts
    seg = live.Segmenter(config=cfg)
    audio = _speech(4.2) + _silence(0.3) + _speech(1.5)
    chunks = _feed_in_blocks(seg, audio)
    assert chunks, "expected a forced cut"
    # Split at the quiet patch (~4.2-4.5s), not at the 5.0s deadline.
    assert _seconds(chunks[0]) < 4.9


def test_pure_silence_is_never_emitted():
    """Whisper invents text on silence — the main source of junk lines."""
    seg = live.Segmenter()
    chunks = _feed_in_blocks(seg, _silence(30.0))
    assert chunks == []


def test_silence_does_not_grow_the_buffer_without_bound():
    seg = live.Segmenter()
    _feed_in_blocks(seg, _silence(60.0))
    assert seg.buffered_seconds <= seg.config.max_chunk_s + 0.5


def test_speech_after_long_silence_still_transcribes():
    seg = live.Segmenter()
    chunks = _feed_in_blocks(seg, _silence(20.0) + _speech(3.0) + _silence(0.8))
    assert len(chunks) == 1
    assert live.block_rms(chunks[0]) > 0.05


# ------------------------------------------------------------------ flush


def test_flush_returns_the_trailing_utterance():
    seg = live.Segmenter()
    _feed_in_blocks(seg, _speech(1.2))
    tail = seg.flush()
    assert tail is not None
    assert _seconds(tail) == pytest.approx(1.2, abs=0.1)


def test_flush_discards_trailing_silence():
    seg = live.Segmenter()
    _feed_in_blocks(seg, _silence(1.2))
    assert seg.flush() is None


def test_flush_discards_a_too_short_tail():
    seg = live.Segmenter()
    _feed_in_blocks(seg, _speech(0.15))
    assert seg.flush() is None


def test_flush_resets_state():
    seg = live.Segmenter()
    _feed_in_blocks(seg, _speech(1.0))
    seg.flush()
    assert seg.buffered_seconds == 0.0
    assert seg.flush() is None


# -------------------------------------------------------------- wav output


def test_write_wav_roundtrip(tmp_path):
    pcm = _speech(0.5)
    path = live.write_wav(str(tmp_path / "a" / "chunk.wav"), pcm, RATE)
    assert os.path.isfile(path)
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == RATE
        assert wf.readframes(wf.getnframes()) == pcm


# ------------------------------------------------------- result normalising


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ("", "")),
        ("  hello  ", ("hello", "")),
        ({"text": " hi ", "language": "en"}, ("hi", "en")),
        ({"text": ""}, ("", "")),
        ({}, ("", "")),
    ],
)
def test_result_text_normalisation(value, expected):
    assert live._result_text(value) == expected


# ------------------------------------------------------------- the session


class _FakeRecorder:
    """Stands in for core.recorder.Recorder: no sound card involved."""

    instances: list["_FakeRecorder"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.on_frames = kwargs.get("on_frames")
        self.output_path = kwargs.get("output_path", "")
        self.last_error = None
        self._running = False
        _FakeRecorder.instances.append(self)

    def start(self):
        self._running = True

    def stop(self, **kwargs):
        self._running = False
        return self.output_path

    def is_running(self):
        return self._running

    def push(self, pcm: bytes, rate: int = RATE, block_s: float = 0.064):
        """Deliver audio the way a real backend does — in small blocks.

        Handing over one giant block would let a mixed speech+silence
        buffer average out above the silence threshold, so no pause is
        ever detected and nothing is ever cut. The real recorder reads
        1024 frames at a time; the fake must too, or it tests a pipeline
        that does not exist.
        """
        assert self.on_frames is not None
        step = int(block_s * rate) * 2
        for i in range(0, len(pcm), step):
            self.on_frames(pcm[i:i + step], rate)


@pytest.fixture
def fake_recorder(monkeypatch):
    _FakeRecorder.instances = []
    monkeypatch.setattr(live._rec, "Recorder", _FakeRecorder)
    return _FakeRecorder


def _drain_until(session, kind, timeout=5.0):
    """Collect events until one of ``kind`` arrives (or time runs out)."""
    got = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in session.drain_events():
            got.append(ev)
            if ev.kind == kind:
                return got
        time.sleep(0.02)
    return got


def test_session_transcribes_a_chunk_and_emits_text(fake_recorder, tmp_path):
    seen: list[str] = []

    def fake_transcribe(path):
        seen.append(path)
        return {"text": "hello world", "language": "en"}

    session = live.LiveSession(
        transcribe_chunk=fake_transcribe, work_dir=str(tmp_path / "work")
    )
    session.start()
    fake_recorder.instances[0].push(_speech(3.0) + _silence(0.8))
    events = _drain_until(session, "text")
    session.stop()

    texts = [e for e in events if e.kind == "text"]
    assert texts, f"no text event; got {[e.kind for e in events]}"
    assert texts[0].text == "hello world"
    assert texts[0].language == "en"
    assert seen, "the chunk was never handed to the transcriber"


def test_session_removes_chunk_files_after_transcribing(fake_recorder, tmp_path):
    work = tmp_path / "work"
    kept: list[str] = []

    def fake_transcribe(path):
        kept.append(path)
        assert os.path.isfile(path), "chunk should exist while transcribing"
        return "text"

    session = live.LiveSession(
        transcribe_chunk=fake_transcribe, work_dir=str(work)
    )
    session.start()
    fake_recorder.instances[0].push(_speech(3.0) + _silence(0.8))
    _drain_until(session, "text")
    session.stop()

    assert kept
    for p in kept:
        assert not os.path.exists(p), "chunk WAV leaked"


def test_session_never_transcribes_silence(fake_recorder, tmp_path):
    def fake_transcribe(path):
        pytest.fail("silence was sent to the model")

    session = live.LiveSession(
        transcribe_chunk=fake_transcribe, work_dir=str(tmp_path / "work")
    )
    session.start()
    fake_recorder.instances[0].push(_silence(30.0))
    time.sleep(0.3)
    session.stop()


def test_session_survives_a_failing_chunk(fake_recorder, tmp_path):
    """One bad chunk must not end the session."""
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("engine hiccup")
        return "second chunk"

    session = live.LiveSession(
        transcribe_chunk=flaky, work_dir=str(tmp_path / "work")
    )
    session.start()
    rec = fake_recorder.instances[0]
    rec.push(_speech(3.0) + _silence(0.8))
    _drain_until(session, "error")
    rec.push(_speech(3.0) + _silence(0.8))
    events = _drain_until(session, "text")
    session.stop()

    kinds = [e.kind for e in events]
    assert "text" in kinds, f"session died after one failure; got {kinds}"


def test_session_reports_falling_behind_instead_of_hiding_it(fake_recorder,
                                                            tmp_path):
    """A live transcript that silently skips audio is worse than one that
    admits it."""
    release = threading.Event()

    def slow(path):
        release.wait(timeout=10.0)
        return "late"

    session = live.LiveSession(
        transcribe_chunk=slow,
        work_dir=str(tmp_path / "work"),
        max_pending_chunks=1,
    )
    session.start()
    rec = fake_recorder.instances[0]
    for _ in range(6):
        rec.push(_speech(3.0) + _silence(0.8))
    warnings = _drain_until(session, "warning", timeout=3.0)
    release.set()
    session.stop()

    assert session.dropped_chunks > 0
    assert any(e.kind == "warning" for e in warnings)


def test_session_transcribes_the_tail_on_stop(fake_recorder, tmp_path):
    seen: list[str] = []

    def fake_transcribe(path):
        seen.append(path)
        return "tail text"

    session = live.LiveSession(
        transcribe_chunk=fake_transcribe, work_dir=str(tmp_path / "work")
    )
    session.start()
    # Speech with no trailing pause: only flush() on stop can emit it.
    fake_recorder.instances[0].push(_speech(1.5))
    assert not seen
    session.stop()
    assert seen, "the trailing utterance was dropped at stop"


def _three_utterances():
    return (_speech(2.5) + _silence(0.8)) * 3


def test_stop_capture_keeps_transcribing_the_whole_backlog(fake_recorder, tmp_path):
    """Owner report (2026-09-23): with a model slower than real time,
    pressing Stop threw away every chunk still queued (a fixed 10 s join,
    then the worker was killed under them). Stop now only ends capture;
    the backlog is transcribed however long it takes.
    """
    release = threading.Event()
    done: list[str] = []

    def slow_transcribe(path):
        release.wait(5.0)
        done.append(path)
        return f"part {len(done)}"

    session = live.LiveSession(
        transcribe_chunk=slow_transcribe, work_dir=str(tmp_path / "work")
    )
    session.start()
    fake_recorder.instances[0].push(_three_utterances())
    session.stop_capture()                    # returns at once
    assert session.pending_chunks() == 3
    assert session.wait_drained(timeout=0.05) is False   # still working
    release.set()
    assert session.wait_drained(timeout=5.0) is True
    texts = [e.text for e in session.drain_events(limit=100) if e.kind == "text"]
    assert texts == ["part 1", "part 2", "part 3"]
    assert session.pending_chunks() == 0


def test_discard_pending_drops_the_backlog_quietly(fake_recorder, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def blocking_transcribe(path):
        started.set()
        release.wait(5.0)
        raise RuntimeError("worker stopped under this chunk")

    session = live.LiveSession(
        transcribe_chunk=blocking_transcribe, work_dir=str(tmp_path / "work")
    )
    session.start()
    fake_recorder.instances[0].push(_three_utterances())
    session.stop_capture()
    assert started.wait(5.0)
    assert session.discard_pending() == 2     # the in-flight one is not queued
    release.set()                             # simulate the killed worker
    assert session.wait_drained(timeout=5.0) is True
    events = session.drain_events(limit=100)
    assert not [e for e in events if e.kind in ("error", "text")]
    assert [e.detail for e in events if e.kind == "state"][-1] == "stopped"


def test_stop_called_twice_emits_stopped_only_once(fake_recorder, tmp_path):
    """Found by an adversarial review (2026-09-22): a second stop() call
    (e.g. the Stop button's worker racing app-exit teardown) used to
    re-run the whole teardown -- a stranded extra sentinel and duplicate
    "stopped"/error events a UI counting them would double-report.
    """
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    session.start()
    session.stop()
    session.stop()  # must be a harmless no-op, not a second teardown

    stopped_events = [
        e for e in session.drain_events(limit=1000)
        if e.kind == "state" and e.detail == "stopped"
    ]
    assert len(stopped_events) == 1


def test_feed_and_flush_do_not_race_over_the_segmenter(fake_recorder, tmp_path):
    """Found by the same review: _on_frames' feed() and stop()'s flush()
    both touch the lock-free Segmenter and could, in principle, run on
    different threads at once. Both now take the session's own lock;
    hammering the capture path concurrently with stop() must not raise
    or corrupt state.
    """
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    session.start()
    block = _speech(0.064)  # one recorder-sized block

    errors: list[BaseException] = []

    def hammer() -> None:
        try:
            for _ in range(200):
                session._on_frames(block, RATE)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=hammer, daemon=True)
    t.start()
    time.sleep(0.01)  # let the hammering thread get into feed()
    session.stop()
    t.join(timeout=5.0)

    assert not t.is_alive(), "the hammering thread never finished"
    assert not errors, f"concurrent feed/flush raised: {errors}"


def test_session_start_failure_does_not_leak_the_consumer_thread(
    fake_recorder, tmp_path, monkeypatch
):
    def boom(self):
        raise live._rec.RecorderUnavailable("no microphone")

    monkeypatch.setattr(_FakeRecorder, "start", boom)
    before = threading.active_count()
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    with pytest.raises(live._rec.RecorderUnavailable):
        session.start()
    deadline = time.time() + 3.0
    while threading.active_count() > before and time.time() < deadline:
        time.sleep(0.02)
    assert threading.active_count() <= before, "consumer thread leaked"


def test_session_cannot_be_started_twice(fake_recorder, tmp_path):
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    session.start()
    with pytest.raises(RuntimeError):
        session.start()
    session.stop()


def test_event_timeline_advances_across_chunks(fake_recorder, tmp_path):
    """Each chunk must be stamped where it happened, not at 0."""
    session = live.LiveSession(
        transcribe_chunk=lambda p: "x", work_dir=str(tmp_path / "work")
    )
    session.start()
    rec = fake_recorder.instances[0]
    rec.push(_speech(3.0) + _silence(0.8))
    _drain_until(session, "text")
    rec.push(_speech(3.0) + _silence(0.8))
    events = _drain_until(session, "text")
    session.stop()
    texts = [e for e in events if e.kind == "text"]
    assert texts
    assert texts[-1].start > 0.0


def test_drain_events_respects_its_limit(tmp_path):
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    for i in range(10):
        session._emit(live.LiveEvent(kind="text", text=str(i)))
    assert len(session.drain_events(limit=4)) == 4
    assert len(session.drain_events(limit=100)) == 6


def test_emit_never_blocks_when_the_ui_stops_draining(tmp_path):
    """A stalled UI must not wedge the capture or transcribe thread."""
    session = live.LiveSession(
        transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "work")
    )
    session.events = queue.Queue(maxsize=2)
    for i in range(50):
        session._emit(live.LiveEvent(kind="text", text=str(i)))
    assert session.events.qsize() == 2


# ------------------------------------------------------------ availability


def test_availability_reports_a_reason_when_unavailable(monkeypatch):
    monkeypatch.setattr(live._rec, "mic_available", lambda: False)
    assert live.is_available("mic") is False
    assert "sounddevice" in live.availability_reason("mic")


def test_loopback_availability_is_windows_only(monkeypatch):
    monkeypatch.setattr(live._rec.os, "name", "posix")
    assert live.is_available("loopback") is False
    assert "Windows" in live.availability_reason("loopback")
