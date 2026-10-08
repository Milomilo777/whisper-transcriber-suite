"""Live engine: capture failures, native-rate devices, stop and cleanup.

Fake sound devices only (no sound card, no model): a stream that cannot
be opened, one that dies mid-session, one that only accepts its native
rate, and loopback-style 48 kHz blocks fed straight into the session.
"""
from __future__ import annotations

import array
import math
import os
import queue
import sys
import threading
import time
import types
import wave

import pytest

from core import live
from core import recorder as rec


def _tone(rate: int, seconds: float, amp: int, freq: float = 220.0) -> bytes:
    n = int(rate * seconds)
    return array.array(
        "h", (int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n))
    ).tobytes()


def _blocks(pcm: bytes, size: int = 2048):
    for i in range(0, len(pcm), size):
        yield pcm[i:i + size]


class _PortAudioError(Exception):
    pass


def _fake_sd(monkeypatch, factory, default_rate: float = 48_000.0):
    fake = types.ModuleType("sounddevice")
    fake.RawInputStream = factory  # type: ignore[attr-defined]
    fake.PortAudioError = _PortAudioError  # type: ignore[attr-defined]
    fake.query_devices = (  # type: ignore[attr-defined]
        lambda device=None, kind=None: {"default_samplerate": default_rate}
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    return fake


def _wait(cond, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ------------------------------------------------- S07-2: dead capture


def test_mic_that_cannot_be_opened_is_reported_while_running(tmp_path, monkeypatch):
    def factory(**kw):
        raise _PortAudioError("Error querying device -1")

    _fake_sd(monkeypatch, factory, default_rate=16_000.0)
    s = live.LiveSession(transcribe_chunk=lambda p: "x", work_dir=str(tmp_path))
    s.start()
    try:
        assert _wait(lambda: not s.is_running())
        assert "Error querying device -1" in s.capture_error()
        assert s.last_error == "Error querying device -1"
    finally:
        s.stop(timeout=2.0)


def test_device_unplugged_mid_session_is_reported(tmp_path, monkeypatch):
    reads = {"n": 0}

    class _Stream:
        samplerate = 16_000

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            reads["n"] += 1
            if reads["n"] > 3:
                raise _PortAudioError("Unanticipated host error")
            time.sleep(0.01)
            return (b"\x10\x00" * n, False)

    _fake_sd(monkeypatch, lambda **kw: _Stream(), default_rate=16_000.0)
    s = live.LiveSession(transcribe_chunk=lambda p: "x", work_dir=str(tmp_path))
    s.start()
    try:
        assert _wait(lambda: s.capture_error() != "")
        assert "Unanticipated host error" in s.capture_error()
    finally:
        s.stop(timeout=2.0)


def test_capture_error_is_empty_after_a_normal_stop(tmp_path, monkeypatch):
    class _Stream:
        samplerate = 16_000

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            time.sleep(0.01)
            return (b"\x10\x00" * n, False)

    _fake_sd(monkeypatch, lambda **kw: _Stream(), default_rate=16_000.0)
    s = live.LiveSession(transcribe_chunk=lambda p: "x", work_dir=str(tmp_path))
    s.start()
    assert _wait(lambda: s.is_running())
    assert s.capture_error() == ""
    s.stop(timeout=2.0)
    assert s.capture_error() == "", "a user's Stop is not a capture failure"


def test_input_signal_state_reports_no_audio_and_digital_silence(tmp_path):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path))
    s._recorder = types.SimpleNamespace(is_running=lambda: True, last_error=None)  # type: ignore[assignment]
    s._started_at = 100.0
    assert s.input_signal_state(now=102.0) == "ok", "grace period first"
    assert s.input_signal_state(now=106.0) == "no_audio"
    s._on_frames(b"\x00\x00" * 1600, 16_000)
    assert s.input_signal_state(now=106.0) == "silent"
    s._on_frames(b"\x05\x00" * 1600, 16_000)
    assert s.input_signal_state(now=time.monotonic()) == "ok"
    s.mode = "loopback"
    s._last_signal_at = 0.0
    assert s.input_signal_state(now=time.monotonic() + 60) == "ok", (
        "silence on system audio is normal, never a hint"
    )


# ------------------------------------- S07-3: native-rate (loopback) audio


@pytest.mark.parametrize("rate", [44_100, 48_000])
def test_native_rate_audio_is_cut_like_16k_audio(tmp_path, rate):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path))
    # 1.0 s speech, 0.2 s pause (inside a sentence), 1.0 s speech, 1 s quiet
    pcm = (_tone(rate, 1.0, 8000) + _tone(rate, 0.2, 0)
           + _tone(rate, 1.0, 8000) + _tone(rate, 1.0, 0))
    for blk in _blocks(pcm):
        s._on_frames(blk, rate)
    items = []
    while True:
        try:
            items.append(s._chunks.get_nowait())
        except queue.Empty:
            break
    assert len(items) == 1, f"the 0.2 s pause must not cut the sentence: {len(items)} chunks"
    assert items[0] is not None
    _seq, chunk, start_s, chunk_rate = items[0]
    assert chunk_rate == 16_000
    seconds = len(chunk) / (16_000 * 2)
    assert 2.6 <= seconds <= 3.0, seconds
    assert start_s == 0.0


def test_event_times_follow_real_seconds_at_48k(tmp_path):
    texts: list[str] = []
    s = live.LiveSession(transcribe_chunk=lambda p: texts.append(p) or "hello",
                         work_dir=str(tmp_path))
    pcm = _tone(48_000, 3.0, 8000) + _tone(48_000, 1.0, 0)
    for blk in _blocks(pcm):
        s._on_frames(blk, 48_000)
    item = s._chunks.get_nowait()
    assert item is not None
    s._consume_one(item)
    ev = [e for e in s.drain_events() if e.kind == "text"][0]
    assert ev.start == 0.0
    assert 3.0 <= ev.end <= 3.6, ev.end


def test_rate_converter_keeps_duration_and_pitch():
    rate_in, rate_out = 48_000, 16_000
    conv = live.RateConverter(rate_in, rate_out)
    src = _tone(rate_in, 2.0, 10_000, freq=440.0)
    out = b"".join(conv.convert(b) for b in _blocks(src, 1000))
    samples = array.array("h")
    samples.frombytes(out)
    assert abs(len(samples) - 2 * rate_out) <= 2
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
    assert 875 <= crossings <= 885, crossings  # 440 Hz for 2 s


@pytest.mark.parametrize("size", [1, 2, 333, 1000, 4096])
def test_rate_converter_output_does_not_depend_on_block_size(size):
    """Same length, and no sample off by more than float rounding (1 LSB)."""
    src = _tone(44_100, 1.0, 9000, freq=300.0) + b"\x01"  # odd byte too
    one = array.array("h")
    one.frombytes(live.RateConverter(44_100, 16_000).convert(src))
    conv = live.RateConverter(44_100, 16_000)
    parts = array.array("h")
    parts.frombytes(b"".join(conv.convert(b) for b in _blocks(src, size)))
    assert len(parts) == len(one)
    assert max(abs(a - b) for a, b in zip(parts, one)) <= 1


def test_rate_converter_numpy_and_pure_paths_agree(monkeypatch):
    src = _tone(48_000, 0.5, 12_000, freq=1000.0)
    with_np = live.RateConverter(48_000, 16_000).convert(src)
    monkeypatch.setitem(sys.modules, "numpy", None)
    pure = live.RateConverter(48_000, 16_000).convert(src)
    assert with_np == pure


def test_rate_converter_damps_content_above_the_new_band():
    """A 20 kHz tone at 48 kHz would fold to 4 kHz at full strength."""
    src = _tone(48_000, 0.5, 10_000, freq=20_000.0)
    out = live.RateConverter(48_000, 16_000).convert(src)
    assert live.block_rms(out) < 0.4 * live.block_rms(src)


def test_rate_converter_same_rate_is_identity():
    src = _tone(16_000, 0.3, 5000)
    assert live.RateConverter(16_000, 16_000).convert(src) == src


# ------------------------------------------- S07-7: native-rate mic


def test_mic_falls_back_to_the_device_native_rate(tmp_path, monkeypatch):
    opened: list[int] = []

    class _Stream:
        def __init__(self, rate):
            self.samplerate = rate

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            r._stop_event.set()
            return (b"\x01\x00" * n, False)

    def factory(**kw):
        opened.append(kw["samplerate"])
        if kw["samplerate"] != 48_000:
            raise _PortAudioError("Invalid sample rate [PaErrorCode -9997]")
        return _Stream(kw["samplerate"])

    _fake_sd(monkeypatch, factory, default_rate=48_000.0)
    out = tmp_path / "native.wav"
    r = rec.Recorder(output_path=str(out), mode="mic", device_index=7)
    seen: list[int] = []
    r.on_frames = lambda pcm, rate: seen.append(rate)
    r._mic_loop()
    assert r.last_error is None, r.last_error
    assert opened == [16_000, 48_000]
    assert seen == [48_000]
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 48_000


def test_mic_open_failure_at_native_rate_keeps_the_error(tmp_path, monkeypatch):
    def factory(**kw):
        raise _PortAudioError(f"cannot open at {kw['samplerate']}")

    _fake_sd(monkeypatch, factory, default_rate=44_100.0)
    r = rec.Recorder(output_path=str(tmp_path / "x.wav"), mode="mic")
    r._mic_loop()
    assert r.last_error and "cannot open" in r.last_error


# --------------------------------------- L5: a dead or stuck worker


def test_repeated_chunk_failures_end_in_one_fatal_event(tmp_path):
    def boom(path):
        raise RuntimeError("The live worker is not running.")

    s = live.LiveSession(transcribe_chunk=boom, work_dir=str(tmp_path))
    for seq in range(1, 6):
        s._consume_one((seq, b"\x10\x00" * 16_000, 0.0, 16_000))
    kinds = [e.kind for e in s.drain_events()]
    assert kinds.count("fatal") == 1
    assert kinds.index("fatal") == s.max_consecutive_errors


def test_a_success_resets_the_failure_count(tmp_path):
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] % 2:
            raise RuntimeError("one bad chunk")
        return "ok"

    s = live.LiveSession(transcribe_chunk=flaky, work_dir=str(tmp_path))
    for seq in range(1, 9):
        s._consume_one((seq, b"\x10\x00" * 16_000, 0.0, 16_000))
    assert "fatal" not in [e.kind for e in s.drain_events()]


# ------------------------------------------ _put_sentinel / L7


def test_stop_capture_never_blocks_on_a_full_queue(tmp_path):
    release = threading.Event()

    def stuck(path):
        release.wait(10)
        return ""

    s = live.LiveSession(transcribe_chunk=stuck, work_dir=str(tmp_path),
                         max_pending_chunks=1)
    s._consumer = threading.Thread(target=s._consume, daemon=True)
    s._consumer.start()
    s._chunks.put((1, b"\x10\x00" * 100, 0.0, 16_000))
    assert _wait(lambda: s.pending_chunks() == 1 and s._chunks.empty())
    s._chunks.put((2, b"\x10\x00" * 100, 0.0, 16_000))  # queue now full
    done = threading.Event()
    threading.Thread(target=lambda: (s.stop_capture(), done.set()), daemon=True).start()
    try:
        assert done.wait(2.0), "stop_capture blocked on a full chunk queue (Tk freezes at exit)"
    finally:
        release.set()
    assert s.wait_drained(timeout=5.0), "the consumer must still end after the backlog"


def test_consumer_ends_even_when_drop_oldest_ate_the_sentinel(tmp_path):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path),
                         max_pending_chunks=1)
    s._consumer = threading.Thread(target=s._consume, daemon=True)
    s.stop_capture()          # sets the stop flags and queues the sentinel
    s._submit(b"\x10\x00" * 100)  # a late chunk drops the oldest item: the sentinel
    s._consumer.start()
    assert s.wait_drained(timeout=3.0)


# ----------------------------------------- S07-6 / L8: the recording


def _session_with_files(tmp_path, keep):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "w"),
                         keep_recording=keep)
    os.makedirs(s.work_dir)
    s.recording_path = os.path.join(s.work_dir, "live-session.wav")
    with open(s.recording_path, "wb") as fh:
        fh.write(b"RIFF")
    with open(os.path.join(s.work_dir, "chunk-000001.wav"), "wb") as fh:
        fh.write(b"RIFF")
    return s


def test_recording_is_removed_unless_kept(tmp_path):
    s = _session_with_files(tmp_path, keep=False)
    assert s.finish_recording() == ""
    assert not os.path.exists(s.work_dir)


def test_kept_recording_survives_and_is_returned(tmp_path):
    s = _session_with_files(tmp_path, keep=True)
    kept = s.finish_recording()
    assert kept == s.recording_path and os.path.isfile(kept)
    assert not os.path.exists(os.path.join(s.work_dir, "chunk-000001.wav"))


def test_recording_is_not_touched_while_capture_still_runs(tmp_path):
    s = _session_with_files(tmp_path, keep=False)
    s.defer_s = 0.3
    s._recorder = types.SimpleNamespace(is_running=lambda: True, last_error=None)  # type: ignore[assignment]
    assert s.finish_recording() == ""
    time.sleep(0.8)  # past the deferral: the thread never ended, so keep
    assert os.path.isfile(s.recording_path), "deleted under a live capture thread"


def test_cleanup_waits_for_a_slow_capture_thread_then_runs(tmp_path):
    """A loopback read can block ~49 s past Stop: clean up once it ends."""
    s = _session_with_files(tmp_path, keep=False)
    running = {"value": True}
    s._recorder = types.SimpleNamespace(  # type: ignore[assignment]
        is_running=lambda: running["value"], last_error=None)
    assert s.finish_recording() == ""
    assert os.path.isfile(s.recording_path)
    running["value"] = False
    assert _wait(lambda: not os.path.exists(s.work_dir))


def test_chunks_are_not_deleted_under_a_running_consumer(tmp_path):
    s = _session_with_files(tmp_path, keep=True)
    busy = threading.Event()
    s._consumer = threading.Thread(target=busy.wait, args=(5,), daemon=True)
    s._consumer.start()
    try:
        assert s.finish_recording() == s.recording_path, "the kept path is still named"
        assert os.path.isfile(os.path.join(s.work_dir, "chunk-000001.wav"))
    finally:
        busy.set()
    assert _wait(lambda: not os.path.exists(os.path.join(s.work_dir, "chunk-000001.wav")))
    assert os.path.isfile(s.recording_path)


def test_finish_recording_leaves_foreign_files_alone(tmp_path):
    s = _session_with_files(tmp_path, keep=False)
    other = os.path.join(s.work_dir, "notes.txt")
    with open(other, "w", encoding="utf-8") as fh:
        fh.write("not ours")
    s.finish_recording()
    assert os.path.isfile(other)
    assert not os.path.exists(s.recording_path)


def test_session_work_dirs_never_collide(monkeypatch, tmp_path):
    import core.config as cfg

    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path)
    dirs = {live.session_work_dir() for _ in range(20)}
    assert len(dirs) == 20, "two sessions in one second shared a folder"
