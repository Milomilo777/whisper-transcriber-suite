import pytest
import core.recorder as r
import time

def test_device_default_rate_handles_missing_device_index():
    class MockSD:
        def query_devices(self, idx=None, kind=None):
            return {"default_samplerate": "48000"}
    assert r._device_default_rate(MockSD(), None) == 48000

def test_device_default_rate_handles_specific_device_index():
    class MockSD:
        def query_devices(self, idx=None, kind=None):
            if idx == 2:
                return {"default_samplerate": "44100"}
            raise ValueError("Wrong index")
    assert r._device_default_rate(MockSD(), 2) == 44100

def test_device_default_rate_returns_zero_on_error():
    class MockSD:
        def query_devices(self, idx=None, kind=None):
            raise Exception("No devices found")
    assert r._device_default_rate(MockSD(), None) == 0

def test_downmix_to_mono_int16_leaves_mono_untouched():
    data = b"\x01\x00\x02\x00"
    assert r._downmix_to_mono_int16(data, 1) == data

def test_downmix_to_mono_int16_downmixes_stereo():
    data = b"\x10\x00\x30\x00"
    assert r._downmix_to_mono_int16(data, 2) == b"\x20\x00"

def test_downmix_to_mono_int16_fallback_without_numpy(monkeypatch):
    # The no-numpy fallback keeps channel 0 on purpose (core/recorder.py), unlike the numpy path that averages.
    import sys
    monkeypatch.setitem(sys.modules, "numpy", None)
    data = b"\x10\x00\x30\x00\x50\x00\x70\x00"
    assert r._downmix_to_mono_int16(data, 2) == b"\x10\x00\x50\x00"

def test_list_mic_devices_returns_empty_when_unavailable(monkeypatch):
    monkeypatch.setattr(r, "mic_available", lambda: False)
    assert r.list_mic_devices() == []

def test_recorder_duration_seconds():
    rec = r.Recorder("out.wav")
    rec._started_at = time.time() - 2.0
    rec._stopped_at = time.time()
    assert rec.duration_seconds() == pytest.approx(2.0, abs=0.1)

def test_recorder_is_running_initially_false():
    rec = r.Recorder("out.wav")
    assert rec.is_running() is False
