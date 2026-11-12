"""Reject host APIs whose PortAudio blocking capture is unimplemented."""
from __future__ import annotations

import sys
import types
import wave

import pytest

from core import recorder as rec


class DeviceBackend:
    """Device indices deliberately differ from reordered host indices."""

    def __init__(self, monkeypatch, default_input=5):
        self.hosts = ["Windows WDM-KS", "Windows WASAPI", "Windows DirectSound", "MME"]
        self.devices = [
            self.info("Output only", 3, channels=0),
            self.info("MME input A", 3),
            self.info("DirectSound input A", 2),
            self.info("WASAPI output only", 1, channels=0),
            self.info("WDM input A", 0),
            self.info("WASAPI input A", 1),
            self.info("MME input B", 3),
            self.info("DirectSound input B", 2),
            self.info("WASAPI input B", 1),
            self.info("WDM input B", 0),
        ]
        self.default_input = default_input
        self.device_errors = {}
        self.host_errors = {}
        self.enumeration_error = None
        self.opened = []
        self.queried = []
        self.allow_stream = False
        self.native_fallback = False
        self.actual_rate = 48_000
        self.recorder = None
        self.block = b"\x12\x00" * 1024
        fake = types.ModuleType("sounddevice")
        fake.default = types.SimpleNamespace(device=(default_input, 0))  # type: ignore[attr-defined]
        fake.query_devices = self.query_devices  # type: ignore[attr-defined]
        fake.query_hostapis = self.query_hostapis  # type: ignore[attr-defined]
        fake.RawInputStream = self.open_stream  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sounddevice", fake)

    @staticmethod
    def info(name, hostapi, channels=2):
        return {"name": name, "hostapi": hostapi, "max_input_channels": channels, "default_samplerate": 48_000.0}

    def query_devices(self, device=None, kind=None):
        self.queried.append((device, kind))
        if device is None and kind is None:
            if self.enumeration_error:
                raise self.enumeration_error
            return [dict(info) for info in self.devices]
        index = self.default_input if device is None and kind == "input" else device
        if index in self.device_errors:
            raise self.device_errors[index]
        return {**self.devices[index], "index": index}

    def query_hostapis(self, index=None):
        if index is None:
            return [{"name": name} for name in self.hosts]
        if index in self.host_errors:
            raise self.host_errors[index]
        return {"name": self.hosts[index]}

    def open_stream(self, **kwargs):
        self.opened.append(dict(kwargs))
        if not self.allow_stream:
            raise RuntimeError("Guard must reject this selection before stream open")
        selected = kwargs.get("device")
        if selected is None:
            selected = self.default_input
        assert selected in (5, 6)
        if self.native_fallback and kwargs["samplerate"] != 48_000:
            raise OSError("Invalid sample rate")
        backend = self

        class Stream:
            samplerate = backend.actual_rate

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, frames):
                assert backend.recorder is not None
                backend.recorder._stop_event.set()
                return backend.block, False

        return Stream()


def _assert_refused_without_mutation(tmp_path, backend, index):
    output = tmp_path / "existing.wav"
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x01\x02" * 512)
    original = output.read_bytes()
    recorder = rec.Recorder(str(output), device_index=index)
    backend.recorder = recorder
    error = None
    try:
        recorder.start()
    except Exception as exc:
        error = exc
    finally:
        if recorder._thread is not None:
            recorder._thread.join(timeout=2)
        before_stop = output.read_bytes()
        recorder.stop()
        first_stop = output.read_bytes()
        recorder.stop()
        second_stop = output.read_bytes()
    assert isinstance(error, rec.RecorderUnavailable), "Reject before creating a capture thread"
    assert str(error).strip()
    assert not backend.opened, "Never choose another microphone or open the refused one"
    assert not recorder.is_running()
    assert (before_stop, first_stop, second_stop) == (original, original, original)
    return str(error)


def test_picker_omits_unimplemented_blocking_capture_hosts(monkeypatch):
    DeviceBackend(monkeypatch)
    assert [device.index for device in rec.list_mic_devices()] == [1, 5, 6, 8]


@pytest.mark.parametrize("index", [2, 4, 7, 9])
def test_unsupported_selection_fails_before_open_or_output_write(tmp_path, monkeypatch, index):
    backend = DeviceBackend(monkeypatch)
    message = _assert_refused_without_mutation(tmp_path, backend, index)
    assert "WASAPI" in message or "MME" in message


@pytest.mark.parametrize("default_input", [4, 7])
def test_unsupported_actual_input_default_is_refused(tmp_path, monkeypatch, default_input):
    backend = DeviceBackend(monkeypatch, default_input=default_input)
    _assert_refused_without_mutation(tmp_path, backend, None)


@pytest.mark.parametrize("index", [0, 3])
def test_output_only_entry_is_not_an_input_selection(tmp_path, monkeypatch, index):
    backend = DeviceBackend(monkeypatch)
    _assert_refused_without_mutation(tmp_path, backend, index)


def test_hotplug_requeries_a_previously_supported_selection(tmp_path, monkeypatch):
    backend = DeviceBackend(monkeypatch)
    assert any(device.index == 5 for device in rec.list_mic_devices())
    backend.devices[5]["hostapi"] = 2
    _assert_refused_without_mutation(tmp_path, backend, 5)


@pytest.mark.parametrize("failure", ["device-query", "missing-host", "invalid-host", "host-index-type", "host-query", "empty-host-name", "missing-host-name"])
def test_unverifiable_selection_is_refused_without_another_microphone(tmp_path, monkeypatch, failure):
    backend = DeviceBackend(monkeypatch)
    if failure == "device-query":
        backend.device_errors[5] = OSError("Input query failed after unplug")
    elif failure == "missing-host":
        backend.devices[5].pop("hostapi")
    elif failure == "invalid-host":
        backend.devices[5]["hostapi"] = 99
    elif failure == "host-index-type":
        backend.devices[5]["hostapi"] = "not-an-index"
    elif failure == "host-query":
        backend.host_errors[1] = OSError("Host API query failed")
    elif failure == "missing-host-name":
        backend.hosts[1] = None
    else:
        backend.hosts[1] = ""
    _assert_refused_without_mutation(tmp_path, backend, 5)


def test_one_malformed_entry_does_not_hide_other_valid_inputs(monkeypatch):
    backend = DeviceBackend(monkeypatch)
    backend.devices[5].pop("hostapi")
    backend.devices.append({"name": "Malformed", "max_input_channels": None, "default_samplerate": None, "hostapi": 3})
    backend.devices.append(backend.info("Later valid MME input", 3))
    assert [device.index for device in rec.list_mic_devices()] == [1, 6, 8, 11]


def test_failed_host_query_does_not_hide_other_hosts(monkeypatch):
    backend = DeviceBackend(monkeypatch)
    backend.host_errors[1] = OSError("WASAPI metadata unavailable")
    assert [device.index for device in rec.list_mic_devices()] == [1, 6]


def test_failed_enumeration_is_empty_without_opening_a_stream(monkeypatch):
    backend = DeviceBackend(monkeypatch)
    backend.enumeration_error = OSError("Device list unavailable")
    assert rec.list_mic_devices() == []
    assert not backend.opened


@pytest.mark.parametrize("index,native_fallback,actual_rate", [(6, False, 44_100), (5, True, 48_000), (None, True, 48_000)], ids=["mme-negotiated", "wasapi-native", "actual-input-default"])
def test_supported_capture_preserves_negotiated_rate_and_live_tap(tmp_path, monkeypatch, index, native_fallback, actual_rate):
    backend = DeviceBackend(monkeypatch)
    backend.allow_stream = True
    backend.native_fallback = native_fallback
    backend.actual_rate = actual_rate
    output = tmp_path / "new.wav"
    taps = []
    recorder = rec.Recorder(str(output), device_index=index, sample_rate=16_000, on_frames=lambda pcm, rate: taps.append((pcm, rate)))
    backend.recorder = recorder
    recorder.start()
    assert recorder._thread is not None
    recorder._thread.join(timeout=2)
    recorder.stop()
    assert not recorder.is_running()
    assert recorder.last_error is None
    assert recorder.sample_rate == 16_000
    assert taps == [(backend.block, actual_rate)]
    expected_rates = [16_000, 48_000] if native_fallback else [16_000]
    assert [call["samplerate"] for call in backend.opened] == expected_rates
    assert all((backend.default_input if call.get("device") is None else call["device"]) == (5 if index is None else index) for call in backend.opened)
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == actual_rate
        assert wav.getnchannels() == 1
        assert wav.readframes(wav.getnframes()) == backend.block


def test_changed_system_default_cannot_switch_capture_or_native_rate_retry(tmp_path, monkeypatch):
    backend = DeviceBackend(monkeypatch)
    backend.allow_stream = True
    backend.native_fallback = True
    query = backend.query_devices

    def query_then_change_default(device=None, kind=None):
        info = query(device, kind)
        if device is None and kind == "input":
            backend.default_input = 7  # now an unsupported DirectSound input
        return info

    sys.modules["sounddevice"].query_devices = query_then_change_default
    recorder = rec.Recorder(str(tmp_path / "pinned.wav"))
    backend.recorder = recorder
    recorder.start()
    recorder._thread.join(timeout=2)
    recorder.stop()
    assert recorder.last_error is None
    assert [call["device"] for call in backend.opened] == [5, 5]
    assert backend.queried[0] == (None, "input")
    assert any(device == 5 for device, kind in backend.queried[1:])
    assert recorder.device_index is None  # user preference remains the default


@pytest.mark.parametrize("host", ["Core Audio", "ALSA", "PulseAudio"])
def test_other_platform_hosts_are_not_excluded(monkeypatch, host):
    backend = DeviceBackend(monkeypatch)
    backend.hosts[1] = host
    assert [device.index for device in rec.list_mic_devices()] == [1, 5, 6, 8]


@pytest.mark.parametrize("index", [None, True, -1, "5"])
def test_unverifiable_resolved_input_index_is_refused(tmp_path, monkeypatch, index):
    backend = DeviceBackend(monkeypatch)
    query = backend.query_devices

    def invalid_index(device=None, kind=None):
        return {**query(device, kind), "index": index}

    sys.modules["sounddevice"].query_devices = invalid_index
    _assert_refused_without_mutation(tmp_path, backend, 5)
