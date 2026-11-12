"""Silent loopback must stop without waiting for future speaker packets."""
import sys
import threading
import types
import wave

from core import recorder as rec


class Loopback:
    def __init__(self):
        self.ready = threading.Event()
        self.release = threading.Event()
        self.read_called = False
        self.stopped = self.closed = False
        self.available = []
        self.last_available = 0
        self.requested_frames = []

    def get_read_available(self):
        self.ready.set()
        value = self.available.pop(0) if self.available else 0
        if isinstance(value, BaseException):
            raise value
        self.last_available = value
        return value

    def read(self, frames, exception_on_overflow=False):
        self.ready.set()
        self.read_called = True
        self.requested_frames.append(frames)
        if frames > self.last_available:
            self.release.wait(3)
        return b"\x01\x00\x03\x00" * frames  # stereo

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


def install(monkeypatch, stream):
    class Audio:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_default_wasapi_loopback(self):
            return {"index": 4, "maxInputChannels": 2, "defaultSampleRate": 48000}

        def open(self, **kwargs):
            return stream

    fake = types.ModuleType("pyaudiowpatch")
    fake.PyAudio = Audio
    fake.paInt16 = 8
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", fake)
    monkeypatch.setattr(rec, "loopback_available", lambda: True)


def test_idle_loopback_stops_without_waiting_for_playback(tmp_path, monkeypatch):
    stream = Loopback()
    install(monkeypatch, stream)
    path = tmp_path / "idle.wav"
    recorder = rec.Recorder(str(path), mode="loopback")
    recorder.start()
    try:
        assert stream.ready.wait(2)
        recorder.stop(timeout=0.15)
        assert not recorder.is_running(), "Idle loopback must observe Stop before any audio arrives"
        assert not stream.read_called, "Never block on a read when zero frames are available"
        assert recorder.last_error is None
        assert stream.stopped and stream.closed
        with wave.open(str(path), "rb") as wav:
            assert wav.getnframes() == 0
            assert wav.getframerate() == 48000
    finally:
        stream.release.set()
        recorder.stop(timeout=2)


def test_availability_failure_keeps_completed_frames(tmp_path, monkeypatch):
    stream = Loopback()
    stream.available = [240, OSError("Loopback device removed")]
    install(monkeypatch, stream)
    path = tmp_path / "retained.wav"
    recorder = rec.Recorder(str(path), mode="loopback")
    recorder.start()
    recorder._thread.join(timeout=2)
    assert not recorder.is_running()
    recorder.stop()
    assert recorder.last_error == "Loopback device removed"
    assert stream.stopped and stream.closed
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 240
        assert len(wav.readframes(240)) == 480


def test_partial_available_packet_is_saved_and_delivered_without_full_block_wait(tmp_path, monkeypatch):
    stream = Loopback()
    stream.available = [240]
    install(monkeypatch, stream)
    path = tmp_path / "partial.wav"
    taps = []
    recorder = rec.Recorder(str(path), mode="loopback")

    def frames(pcm, rate):
        taps.append((pcm, rate))
        recorder._stop_event.set()

    recorder.on_frames = frames
    recorder.start()
    try:
        recorder._thread.join(timeout=1)
        assert not recorder.is_running()
        assert stream.requested_frames == [240]
        assert len(taps) == 1 and len(taps[0][0]) == 240 * 2 and taps[0][1] == 48000
        with wave.open(str(path), "rb") as wav:
            assert wav.getnframes() == 240
            assert wav.readframes(240) == taps[0][0]
    finally:
        stream.release.set()
        recorder.stop(timeout=2)
