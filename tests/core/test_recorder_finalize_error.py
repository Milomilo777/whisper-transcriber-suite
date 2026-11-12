"""Native WAV files plus fake capture devices expose finalization failures."""
import errno
import sys
import types
import wave
from contextlib import nullcontext

import pytest

from core import recorder as capture


@pytest.mark.parametrize("mode", ["mic", "loopback"])
@pytest.mark.parametrize("read_error", [False, True])
def test_wav_close_error_is_reported_without_truncating_captured_audio(
    tmp_path, monkeypatch, mode, read_error,
):
    path = tmp_path / "captured.wav"
    recorder = capture.Recorder(str(path), mode=mode)

    class Stream:
        samplerate = 16000
        reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size, **kwargs):
            self.reads += 1
            if self.reads > 1:
                raise RuntimeError("synthetic capture failure")
            if not read_error:
                recorder._stop_event.set()
            data = b"\x01\x02" * size
            return (data, False) if mode == "mic" else data

        def stop_stream(self):
            pass

        def get_read_available(self):
            return 1024

        def close(self):
            pass

    stream = Stream()
    if mode == "mic":
        device = types.ModuleType("sounddevice")
        device.RawInputStream = lambda **kwargs: stream
        monkeypatch.setitem(sys.modules, "sounddevice", device)
    else:
        class Audio:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get_default_wasapi_loopback(self):
                return {"index": 1, "defaultSampleRate": 16000, "maxInputChannels": 1}

            def open(self, **kwargs):
                return stream

        device = types.ModuleType("pyaudiowpatch")
        device.PyAudio = Audio
        device.paInt16 = 8
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", device)
    open_wave = recorder._open_wave

    def broken_close(rate):
        actual = open_wave(rate)

        def close():
            actual.close()
            raise OSError(errno.ENOSPC, "synthetic WAV finalization failure")

        return types.SimpleNamespace(writeframes=actual.writeframes, close=close)

    monkeypatch.setattr(recorder, "_open_wave", broken_close)
    getattr(recorder, "_mic_loop" if mode == "mic" else "_loopback_loop")()
    expected = "synthetic capture failure" if read_error else "synthetic WAV finalization failure"
    assert recorder.last_error and expected in recorder.last_error
    before_stop = path.read_bytes()
    monkeypatch.setattr(recorder, "_finalize_wav", lambda: pytest.fail("captured audio was truncated"))
    assert recorder.stop() == str(path)
    assert path.read_bytes() == before_stop
    with wave.open(str(path), "rb") as audio:
        assert audio.getnframes() == 1024


@pytest.mark.parametrize("state,exists", [
    ("healthy", True), ("raised", True), ("worker_error", True), ("worker_error", False),
])
def test_voice_reference_recording_reports_stop_errors_and_keeps_file(
    tmp_path, monkeypatch, state, exists,
):
    from app.widgets import voice_clone_tab as tab

    path = tmp_path / "reference.wav"
    if exists:
        path.write_bytes(b"synthetic retained recording")
    original = path.read_bytes() if exists else None
    stopped, added, errors, statuses = [], [], [], []

    def stop():
        stopped.append(True)
        if state == "raised":
            raise OSError("synthetic stop failure")
        return str(path)

    recorder = types.SimpleNamespace(
        stop=stop, last_error="synthetic finalization failure" if state == "worker_error" else None,
    )
    app = types.SimpleNamespace(vc_recorder=recorder,
                                vc_status_var=types.SimpleNamespace(set=statuses.append))
    monkeypatch.setattr(tab, "_sync_lock", lambda app: None)
    monkeypatch.setattr(tab, "_validate_and_add_sample", lambda app, path: added.append(path))
    monkeypatch.setattr(tab, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))
    tab._finish_recording(app)
    assert stopped == [True] and app.vc_recorder is None
    if state == "healthy":
        assert added == [str(path)] and errors == []
    else:
        assert added == [] and len(errors) == 1 and statuses
        if state == "worker_error":
            assert "synthetic finalization failure" in str(errors[0][0])
            detail = errors[0][1].get("detail", "")
            assert (str(path) in detail) == exists
    assert path.read_bytes() == original if exists else not path.exists()


@pytest.mark.parametrize("mode", ["mic", "loopback"])
def test_partial_first_write_and_close_failure_never_trigger_empty_fallback(tmp_path, monkeypatch, mode):
    path = tmp_path / "partial.wav"
    recorder = capture.Recorder(str(path), mode=mode)
    if mode == "mic":
        stream = types.SimpleNamespace(samplerate=16000, read=lambda size: (b"\x01\x02" * size, False))
        device = types.ModuleType("sounddevice")
        device.RawInputStream = lambda **kwargs: nullcontext(stream)
        monkeypatch.setitem(sys.modules, "sounddevice", device)
    else:
        stream = types.SimpleNamespace(
            read=lambda size, **kwargs: b"\x01\x02" * size,
            get_read_available=lambda: 1024,
            stop_stream=lambda: None, close=lambda: None,
        )
        audio = types.SimpleNamespace(
            get_default_wasapi_loopback=lambda: {"index": 1, "defaultSampleRate": 16000, "maxInputChannels": 1},
            open=lambda **kwargs: stream,
        )
        device = types.ModuleType("pyaudiowpatch")
        device.PyAudio = lambda: nullcontext(audio)
        device.paInt16 = 8
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", device)
    open_wave = recorder._open_wave

    def interrupted_wave(rate):
        actual = open_wave(rate)

        def writeframes(block):
            actual.writeframes(block[:len(block) // 2])
            raise OSError(errno.ENOSPC, "synthetic partial frame write")

        def close():
            actual.close()
            raise OSError(errno.ENOSPC, "synthetic finalization failure")

        return types.SimpleNamespace(writeframes=writeframes, close=close)

    monkeypatch.setattr(recorder, "_open_wave", interrupted_wave)
    getattr(recorder, "_mic_loop" if mode == "mic" else "_loopback_loop")()
    before_stop = path.read_bytes()
    assert recorder.last_error and "synthetic partial frame write" in recorder.last_error
    assert recorder.stop() == str(path)
    assert path.read_bytes() == before_stop
    with wave.open(str(path), "rb") as audio:
        assert audio.getnframes() == 512


def test_unreadable_file_metadata_never_authorizes_empty_fallback(tmp_path, monkeypatch):
    path = tmp_path / "partial.wav"
    original = b"synthetic retained partial audio"
    path.write_bytes(original)
    recorder = capture.Recorder(str(path))
    stat = capture.os.stat

    def unavailable(file, *args, **kwargs):
        if capture.os.fspath(file) == str(path):
            raise OSError(errno.EIO, "synthetic metadata failure")
        return stat(file, *args, **kwargs)

    monkeypatch.setattr(capture.os, "stat", unavailable)
    assert recorder.stop() == str(path)
    assert recorder.last_error and "synthetic metadata failure" in recorder.last_error
    assert path.read_bytes() == original


def test_stop_during_mic_read_does_not_hide_a_later_disk_error(tmp_path, monkeypatch):
    path = tmp_path / "stopping.wav"
    recorder = capture.Recorder(str(path))

    def read(size):
        recorder._stop_event.set()  # Stop arrived while the device read was in progress.
        return b"\x01\x02" * size, False

    stream = types.SimpleNamespace(samplerate=16000, read=read)
    device = types.ModuleType("sounddevice")
    device.RawInputStream = lambda **kwargs: nullcontext(stream)
    monkeypatch.setitem(sys.modules, "sounddevice", device)
    open_wave = recorder._open_wave

    def interrupted_wave(rate):
        actual = open_wave(rate)

        def writeframes(block):
            actual.writeframes(block[:len(block) // 2])
            raise OSError(errno.ENOSPC, "synthetic frame write failure after Stop")

        return types.SimpleNamespace(writeframes=writeframes, close=actual.close)

    monkeypatch.setattr(recorder, "_open_wave", interrupted_wave)
    recorder._mic_loop()
    assert recorder.last_error and "synthetic frame write failure after Stop" in recorder.last_error
    before_stop = path.read_bytes()
    recorder.stop()
    assert path.read_bytes() == before_stop
