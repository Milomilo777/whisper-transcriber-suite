"""Actionable Windows microphone permission errors, without changing settings."""
from __future__ import annotations

import os
import re
import sys
import types

import pytest

from core import recorder as rec


_HOST_NAMES = ["Windows WDM-KS", "Windows WASAPI", "Windows DirectSound", "MME"]


class PortAudioError(Exception):
    # Adapted from python-sounddevice 0.5.6 (https://python-sounddevice.readthedocs.io/en/0.5.6/_modules/sounddevice.html#PortAudioError) — native-free exception tuple and diagnostic formatting.
    def __str__(self):
        message = self.args[0] if self.args else ""
        if len(self.args) > 1:
            message = f"{message} [PaErrorCode {self.args[1]}]"
        if len(self.args) > 2:
            host_index, code, text = self.args[2]
            name = _HOST_NAMES[host_index]
            message = f"{message}: '{text}' [{name} error {code}]"
        return message


def _native_error(host_index, code, text):
    # sounddevice._check translates the native host API type ID into an
    # index before constructing this tuple. WASAPI type 13 is index 1 here.
    return PortAudioError("Error opening RawInputStream: Unanticipated host error", -9999, (host_index, code, text))


def _capture_failure(monkeypatch, tmp_path, error, *, platform_name="nt", native_retry=False, host_index=3):
    fake = types.ModuleType("sounddevice")
    attempts = []
    devices = [
        {"name": "Output", "max_input_channels": 0, "default_samplerate": 16_000, "hostapi": host_index}
        for _ in range(4)
    ] + [{"name": "Input", "max_input_channels": 2, "default_samplerate": 44_100 if native_retry else 16_000, "hostapi": host_index}]

    def cannot_open(**kwargs):
        attempts.append(kwargs["samplerate"])
        assert kwargs.get("device", 4) == 4
        if native_retry and kwargs["samplerate"] == 16_000:
            raise OSError("Unsupported sampling rate")
        raise error

    def query_devices(device=None, kind=None):
        if device is None and kind is None:
            return [dict(info) for info in devices]
        return dict(devices[4 if device is None else device])

    fake.RawInputStream = cannot_open  # type: ignore[attr-defined]
    fake.PortAudioError = PortAudioError  # type: ignore[attr-defined]
    fake.default = types.SimpleNamespace(device=(4, 0))  # type: ignore[attr-defined]
    fake.query_devices = query_devices  # type: ignore[attr-defined]
    hosts = [{"name": name} for name in _HOST_NAMES]
    fake.query_hostapis = lambda index=None: hosts if index is None else hosts[index]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    fake_os = types.ModuleType("os")
    fake_os.__dict__.update(vars(os))
    fake_os.name = platform_name
    monkeypatch.setattr(rec, "os", fake_os)
    recorder = rec.Recorder(str(tmp_path / "denied.wav"), device_index=4)
    raised = None
    try:
        recorder.start()
    except Exception as exc:
        raised = exc
    if recorder._thread is not None:
        recorder._thread.join(timeout=2)
    assert not recorder.is_running()
    return str(raised) if raised is not None else recorder.last_error or "", attempts


def _assert_desktop_permission_guidance(message, error):
    assert str(error) in message
    lowered = message.lower()
    assert all(word in lowered for word in ("settings", "privacy", "microphone", "desktop", "access"))
    # The original diagnostic may already contain "microphone" before the
    # later Settings path. Match that ordered path, not first occurrences.
    assert re.search(r"settings.*privacy.*microphone", lowered, re.DOTALL)
    assert any(action in lowered for action in ("check", "allow", "enable"))


@pytest.mark.parametrize("error", [PermissionError(5, "Access is denied"), PermissionError(13, "Operating-system microphone access denied")])
def test_windows_permission_denied_names_settings_and_desktop_access(monkeypatch, tmp_path, error):
    message, _ = _capture_failure(monkeypatch, tmp_path, error)
    _assert_desktop_permission_guidance(message, error)


def test_native_rate_retry_keeps_the_permission_diagnostic(monkeypatch, tmp_path):
    error = PermissionError(13, "Native-rate microphone permission denied")
    message, attempts = _capture_failure(monkeypatch, tmp_path, error, native_retry=True)
    assert attempts == [16_000, 44_100]
    _assert_desktop_permission_guidance(message, error)


@pytest.mark.parametrize("error", [OSError("Microphone disconnected"), OSError(-9997, "Invalid sample rate"), RuntimeError("Unanticipated host error [PaErrorCode -9999]"), RuntimeError("Access is denied by the host API")], ids=["disconnected", "sample-format", "host-api", "denied-text-is-not-permission-type"])
def test_other_failures_are_not_mislabeled_as_permission_denial(monkeypatch, tmp_path, error):
    message, _ = _capture_failure(monkeypatch, tmp_path, error)
    assert message == str(error)


def test_non_windows_permission_error_keeps_its_own_diagnostic(monkeypatch, tmp_path):
    error = PermissionError(13, "Input permission denied")
    message, _ = _capture_failure(monkeypatch, tmp_path, error, platform_name="posix")
    assert message == str(error)


@pytest.mark.parametrize("code", [-2147024891, 0x80070005], ids=["signed-native-long", "unsigned-hresult-representation"])
def test_wasapi_access_denied_hresult_keeps_native_diagnostic_and_adds_guidance(monkeypatch, tmp_path, code):
    # Microsoft defines E_ACCESSDENIED as HRESULT 0x80070005. The signed
    # Windows LONG form is the actual PortAudio host error representation.
    # PortAudio's inspected WASAPI logger has no E_ACCESSDENIED text case;
    # its numeric HRESULT survives even when the text is UNKNOWN ERROR.
    error = _native_error(1, code, "UNKNOWN ERROR")
    message, _ = _capture_failure(monkeypatch, tmp_path, error, host_index=1)
    _assert_desktop_permission_guidance(message, error)


def test_native_retry_preserves_structured_wasapi_access_denied(monkeypatch, tmp_path):
    error = _native_error(1, -2147024891, "UNKNOWN ERROR")
    message, attempts = _capture_failure(monkeypatch, tmp_path, error, host_index=1, native_retry=True)
    assert attempts == [16_000, 44_100]
    _assert_desktop_permission_guidance(message, error)


@pytest.mark.parametrize("host_index,code,text", [
    (3, 5, "The specified device handle is invalid"),
    (1, 5, "Unspecified native host failure"),
    (1, -2004287484, "AUDCLNT_E_DEVICE_INVALIDATED"),
    (3, 1, "Access is denied by the driver"),
    (3, -2147024891, "A different host's error code"),
], ids=["mme-invalid-handle-five", "wasapi-small-five-is-not-hresult", "wasapi-device-invalidated", "host-denied-text-is-not-permission-code", "wrong-host-hresult"])
def test_structured_non_permission_host_failures_keep_their_diagnostic(monkeypatch, tmp_path, host_index, code, text):
    error = _native_error(host_index, code, text)
    message, _ = _capture_failure(monkeypatch, tmp_path, error, host_index=host_index)
    assert message == str(error)


def test_non_windows_structured_error_gets_no_windows_settings_guidance(monkeypatch, tmp_path):
    error = _native_error(1, -2147024891, "UNKNOWN ERROR")
    message, _ = _capture_failure(monkeypatch, tmp_path, error, platform_name="posix", host_index=1)
    assert message == str(error)


def test_destination_permission_error_is_not_microphone_privacy(monkeypatch, tmp_path):
    error = PermissionError(13, "Destination write denied")

    class OpenInput:
        samplerate = 16_000

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake = types.ModuleType("sounddevice")
    fake.RawInputStream = lambda **kwargs: OpenInput()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    def denied_output(self, rate):
        raise error

    monkeypatch.setattr(rec.Recorder, "_open_wave", denied_output)
    recorder = rec.Recorder(str(tmp_path / "output.wav"))
    recorder.start()
    recorder._thread.join(timeout=2)
    assert not recorder.is_running()
    assert recorder.last_error == str(error)


def test_input_read_permission_error_keeps_microphone_guidance(monkeypatch, tmp_path):
    error = PermissionError(13, "Microphone access revoked")

    class OpenInput:
        samplerate = 16_000

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, frames):
            raise error

    fake = types.ModuleType("sounddevice")
    fake.RawInputStream = lambda **kwargs: OpenInput()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    fake_os = types.ModuleType("os")
    fake_os.__dict__.update(vars(os))
    fake_os.name = "nt"
    monkeypatch.setattr(rec, "os", fake_os)
    recorder = rec.Recorder(str(tmp_path / "output.wav"))
    recorder.start()
    recorder._thread.join(timeout=2)
    assert not recorder.is_running()
    _assert_desktop_permission_guidance(recorder.last_error or "", error)


def test_unprintable_input_error_retains_a_useful_error_name():
    class Unprintable(Exception):
        def __str__(self):
            raise OSError("Host disappeared")

    assert rec._mic_error_message(Unprintable()) == "Unprintable"
