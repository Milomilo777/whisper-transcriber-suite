"""Tests for the audio recorder module."""
from __future__ import annotations

import os
import sys
import types
import wave
from pathlib import Path

import pytest

from core import recorder as rec


# ---------- availability -------------------------------------------------------


def test_mic_available_false_when_module_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    assert rec.mic_available() is False
    assert "sounddevice" in rec.mic_availability_reason()


def test_loopback_available_false_on_non_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert rec.loopback_available() is False
    assert "Windows" in rec.loopback_availability_reason()


def test_loopback_available_false_when_pyaudio_missing(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
    assert rec.loopback_available() is False


def test_mic_available_false_when_portaudio_fails_to_load(monkeypatch):
    """sounddevice can raise a non-ImportError at import time — its
    documented "PortAudio library not found" OSError (a missing/broken
    native lib, common on Linux without libportaudio2). That must degrade to
    False instead of escaping into a UI callback.
    """
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert rec.mic_available() is False
    reason = rec.mic_availability_reason()
    assert "sounddevice" in reason
    assert "PortAudio" in reason


def test_loopback_available_false_when_pyaudio_fails_to_load(monkeypatch):
    """Same native-load guard for pyaudiowpatch (e.g. a DLL-load OSError)."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyaudiowpatch":
            raise OSError("DLL load failed while importing _portaudio")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert rec.loopback_available() is False
    assert "could not be loaded" in rec.loopback_availability_reason()


# ---------- device enumeration -------------------------------------------------


def test_list_mic_devices_returns_empty_when_unavailable(monkeypatch):
    monkeypatch.setattr(rec, "mic_available", lambda: False)
    assert rec.list_mic_devices() == []


def test_list_mic_devices_filters_zero_input_channels(monkeypatch):
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [  # type: ignore[attr-defined]
        {"name": "Microphone", "max_input_channels": 2,
         "default_samplerate": 48000.0},
        {"name": "Speakers", "max_input_channels": 0,
         "default_samplerate": 48000.0},
        {"name": "USB Mic", "max_input_channels": 1,
         "default_samplerate": 44100.0},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    devices = rec.list_mic_devices()
    assert len(devices) == 2
    assert all(d.max_input_channels > 0 for d in devices)
    names = {d.name for d in devices}
    assert "Microphone" in names
    assert "USB Mic" in names
    assert "Speakers" not in names


def test_list_mic_devices_skips_one_malformed_entry_not_the_whole_list(monkeypatch):
    """Found by an adversarial review (2026-09-22): a driver reporting
    None for a numeric field (seen on hot-unplug/virtual-cable devices)
    used to raise inside the loop and wipe out every working device via
    the whole-function except -> []."""
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [  # type: ignore[attr-defined]
        {"name": "Microphone", "max_input_channels": 2,
         "default_samplerate": 48000.0},
        {"name": "Virtual Cable", "max_input_channels": 2,
         "default_samplerate": None},  # malformed: float(None) raises
        {"name": "USB Mic", "max_input_channels": 1,
         "default_samplerate": 44100.0},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    devices = rec.list_mic_devices()
    names = {d.name for d in devices}
    assert names == {"Microphone", "USB Mic"}


# ---------- Recorder dataclass -------------------------------------------------


def test_recorder_start_raises_when_mic_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "mic_available", lambda: False)
    r = rec.Recorder(output_path=str(tmp_path / "out.wav"), mode="mic")
    with pytest.raises(rec.RecorderUnavailable):
        r.start()


def test_recorder_unknown_mode_raises(tmp_path):
    r = rec.Recorder(output_path=str(tmp_path / "out.wav"), mode="nonsense")
    with pytest.raises(ValueError):
        r.start()


def test_recorder_stop_writes_wav_even_with_no_frames(tmp_path):
    out = tmp_path / "empty.wav"
    r = rec.Recorder(output_path=str(out), mode="mic")
    # Don't actually start the recorder — just call stop().
    # _finalize_wav must still write a valid (zero-frame) WAV.
    r.stop()
    assert out.exists()
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == rec.SAMPLE_RATE
        assert wf.getsampwidth() == rec.SAMPLE_WIDTH_BYTES
        assert wf.getnchannels() == rec.CHANNELS
        assert wf.getnframes() == 0


def test_recorder_finalize_writes_captured_frames(tmp_path):
    out = tmp_path / "captured.wav"
    r = rec.Recorder(output_path=str(out), mode="mic")
    # Inject some fake frames as if the mic loop captured them.
    r._frames.append(b"\x00\x01" * 1024)
    r._frames.append(b"\x00\x01" * 1024)
    r._finalize_wav()
    with wave.open(str(out), "rb") as wf:
        # 2 * 1024 frames of 2 bytes each — 2048 frames total.
        assert wf.getnframes() == 2048


def test_recorder_streams_to_wav_without_buffering(tmp_path, monkeypatch):
    """Regression (P2-6): real capture must stream straight to disk, not
    accumulate every block in an in-memory list (which OOMs on a
    multi-hour recording)."""
    out = tmp_path / "stream.wav"
    r = rec.Recorder(output_path=str(out), mode="mic")
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    block = b"\x01\x02" * 512  # 1024 bytes = 512 int16 mono frames

    calls = {"n": 0}

    class _FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            calls["n"] += 1
            if calls["n"] >= 4:
                r._stop_event.set()  # end the loop after a few blocks
            return (block, False)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.RawInputStream = lambda **kw: _FakeStream()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    r._mic_loop()  # run synchronously for determinism

    assert r._wrote_wave is True
    assert r._frames == [], "frames must NOT be buffered in memory during capture"
    with wave.open(str(out), "rb") as wf:
        assert wf.getnframes() > 0
        assert wf.getnchannels() == rec.CHANNELS
        assert wf.getsampwidth() == rec.SAMPLE_WIDTH_BYTES


def test_mic_loop_uses_the_stream_negotiated_rate_not_the_request(tmp_path, monkeypatch):
    """Found by an adversarial review (2026-09-22): the requested rate is
    a hint, not a guarantee -- a fixed-rate device can silently open at
    a different rate. The WAV header and the live tap must reflect what
    was actually negotiated, not the request."""
    out = tmp_path / "rate.wav"
    r = rec.Recorder(output_path=str(out), mode="mic", sample_rate=16_000)
    monkeypatch.setattr(rec, "mic_available", lambda: True)
    seen_rates: list[int] = []
    r.on_frames = lambda pcm, rate: seen_rates.append(rate)
    block = b"\x01\x02" * 512

    class _FakeStream:
        samplerate = 48_000  # negotiated a different rate than requested

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            r._stop_event.set()
            return (block, False)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.RawInputStream = lambda **kw: _FakeStream()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    r._mic_loop()

    assert seen_rates == [48_000], "on_meter got the requested rate, not the real one"
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 48_000, "WAV header still claims the requested rate"
    assert r.sample_rate == 16_000, "the capture thread must not mutate the requested rate"


def test_stop_survives_a_finalize_failure(tmp_path, monkeypatch):
    """Found by the same review: stop()'s own docstring promises it
    always returns a path; an unwritable output location used to make
    the unguarded _finalize_wav() call raise out of stop() instead."""
    out = tmp_path / "readonly" / "out.wav"
    r = rec.Recorder(output_path=str(out), mode="mic")

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(r, "_finalize_wav", boom)
    path = r.stop()
    assert path == str(out)
    assert r.last_error and "disk full" in r.last_error


def test_recorder_duration_seconds_after_stop():
    r = rec.Recorder(output_path="/tmp/x.wav", mode="mic")
    r._started_at = 100.0
    r._stopped_at = 105.5
    assert r.duration_seconds() == pytest.approx(5.5, abs=1e-3)


# ---------- mono downmix -------------------------------------------------------


def test_downmix_to_mono_passthrough_for_single_channel():
    data = b"\x00\x01\x02\x03"
    assert rec._downmix_to_mono_int16(data, 1) == data


def test_downmix_to_mono_averages_stereo_with_numpy():
    pytest.importorskip("numpy")
    import numpy as np
    stereo = np.array([[100, 200], [300, 400], [-100, 100]], dtype=np.int16)
    data = stereo.tobytes()
    mono = rec._downmix_to_mono_int16(data, 2)
    expected = np.array([150, 350, 0], dtype=np.int16).tobytes()
    assert mono == expected


def test_downmix_without_numpy_drops_a_trailing_partial_frame(monkeypatch):
    """Found by an adversarial review (2026-09-22): the pure-Python
    fallback's guard was `len(f) >= SAMPLE_WIDTH_BYTES` (one channel's
    worth) instead of a full frame across all channels -- a short read
    ending mid-frame fabricated a phantom sample from a stub instead of
    dropping it, the same way the numpy path already does."""
    monkeypatch.setitem(sys.modules, "numpy", None)  # force the no-numpy path
    channels = 6
    # 2 full 6-channel frames (12 bytes each) + a 2-byte stub of a 3rd.
    frame1 = bytes(range(0, 12))
    frame2 = bytes(range(12, 24))
    stub = bytes([99, 99])
    data = frame1 + frame2 + stub
    mono = rec._downmix_to_mono_int16(data, channels)
    # Only the two complete frames may contribute a sample; the stub
    # must be dropped, not turned into a fabricated third sample.
    assert len(mono) == 2 * rec.SAMPLE_WIDTH_BYTES
    assert mono == frame1[:2] + frame2[:2]


def test_downmix_handles_partial_trailing_frame(monkeypatch):
    pytest.importorskip("numpy")
    import numpy as np
    # 5 samples can't reshape to (?, 2). Function must trim instead of crashing.
    data = np.array([10, 20, 30, 40, 50], dtype=np.int16).tobytes()
    mono = rec._downmix_to_mono_int16(data, 2)
    # First two frames are (10,20)->15 and (30,40)->35; the lone 50 is dropped.
    expected = np.array([15, 35], dtype=np.int16).tobytes()
    assert mono == expected
