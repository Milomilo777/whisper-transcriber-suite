"""Planning a Text to Voice job (core/tts_plan.py): estimate maths, the
confirm threshold, the free-disk check and the stored speed figure."""
from __future__ import annotations

import json

import pytest

from core import tts_plan as p

KOKORO_V = "kokoro-multi-lang-v1_0; sherpa-onnx 1.0"
HW = "Windows / AMD64 / test CPU / 8 threads"


# ------------------------------------------------------------------ text


@pytest.mark.parametrize("text, units", [
    ("", 0.0),
    ("abc", 3.0),
    ("  a  \n\t b  ", 3.0),        # outer space stripped, a run counts once
    ("你好", 6.0),                  # Han: 3 each
    ("こんにちは", 10.0),            # kana: 2 each
    ("안녕", 5.0),                  # Hangul: 2.5 each
    ("Hi 你", 6.0),
])
def test_speech_units(text, units):
    assert p.speech_units(text) == pytest.approx(units)


# ------------------------------------------------------------------ estimate


def _cal(engine="kokoro", device="cpu", *, units=200.0, audio=10.0, compute=5.0,
         speed=1.0, version=KOKORO_V, hardware=HW):
    return p.Calibration(engine=engine, device=device, engine_version=version,
                         hardware=hardware, units=units, audio_seconds=audio,
                         compute_seconds=compute, speed=speed, source="check",
                         measured_at="2026-10-06T00:00:00Z")


def test_estimate_without_a_measurement_uses_the_reference_figure():
    est = p.estimate("a" * 160, "kokoro", "cpu")
    # 160 units / 16 per second = 10 s of speech, spread 0.8 .. 1.25.
    assert (est.audio_low, est.audio_high) == pytest.approx((8.0, 12.5))
    # Kokoro reference 0.7 s per second of speech, spread 0.5 .. 2.5.
    assert est.time_low == pytest.approx(8.0 * 0.7 * 0.5)
    assert est.time_high == pytest.approx(12.5 * 0.7 * 2.5)
    assert est.measured is False
    # 24 kHz 16-bit mono = 48,000 bytes a second, plus the header and tag.
    assert est.size_low == 8 * 48000 + 4096
    assert est.size_high == 600000 + 4096


def test_estimate_with_a_measurement_uses_its_rate_and_speed():
    est = p.estimate("a" * 160, "kokoro", "cpu", _cal(units=200, audio=10, compute=5))
    # 20 units per second measured -> 8 s of speech; 0.5 s compute per second.
    assert (est.audio_low, est.audio_high) == pytest.approx((6.4, 10.0))
    assert est.time_low == pytest.approx(6.4 * 0.5 * 0.85)
    assert est.time_high == pytest.approx(10.0 * 0.5 * 1.25)
    assert est.measured is True


def test_speed_shortens_the_speech_and_the_time():
    slow = p.estimate("a" * 160, "kokoro", "cpu", speed=1.0)
    fast = p.estimate("a" * 160, "kokoro", "cpu", speed=2.0)
    assert fast.audio_high == pytest.approx(slow.audio_high / 2)
    assert fast.time_high == pytest.approx(slow.time_high / 2)
    assert p.estimate("a" * 160, "kokoro", "cpu", speed=0).audio_high == slow.audio_high


def test_omnivoice_short_pass_costs_a_whole_minimum_pass():
    est = p.estimate("Hi.", "omnivoice", "cpu")
    assert est.audio_high < 1.0
    # A pass under 4 s costs as much as a 4 s one: 4 * 21, spread 0.5 .. 2.5.
    assert est.time_low == pytest.approx(4 * 21.0 * 0.5)
    assert est.time_high == pytest.approx(4 * 21.0 * 2.5)


def test_device_without_a_figure_has_no_time():
    est = p.estimate("a" * 400, "omnivoice", "cuda")
    assert est.time_low is None and est.time_high is None
    assert est.size_high > 0
    assert p.needs_confirm(est) is True  # long: still shows size and disk
    measured = p.estimate("a" * 400, "omnivoice", "cuda",
                          _cal("omnivoice", "cuda", audio=20, compute=10))
    assert measured.time_high is not None and measured.measured


def test_calibration_ratio_and_rate():
    assert _cal("omnivoice", audio=2.0, compute=84.0).ratio == pytest.approx(21.0)
    assert _cal(audio=10.0, compute=5.0).ratio == pytest.approx(0.5)
    assert _cal(units=100, audio=5, speed=2.0).units_per_second == pytest.approx(10.0)


def test_confirm_only_for_long_slow_jobs():
    # Short text never asks, even on the slowest engine.
    assert p.needs_confirm(p.estimate("Hi.", "omnivoice", "cpu")) is False
    assert p.needs_confirm(p.estimate("a" * 300, "omnivoice", "cpu")) is False
    # Long and slow asks.
    assert p.needs_confirm(p.estimate("a" * 400, "omnivoice", "cpu")) is True
    # Long but measured fast (high estimate 15.6 s) does not.
    fast = p.estimate("a" * 400, "kokoro", "cpu", _cal(units=200, audio=10, compute=5))
    assert fast.time_high < p.CONFIRM_ABOVE_SECONDS
    assert p.needs_confirm(fast) is False


# ------------------------------------------------------------------ disk


def test_disk_check_refuses_below_need_plus_margin(monkeypatch, tmp_path):
    est = p.estimate("a" * 160, "kokoro", "cpu")
    need = est.size_high + p.DISK_MARGIN_BYTES
    asked = []

    def free(path):
        asked.append(path)
        return free_value

    monkeypatch.setattr(p, "free_bytes", free)
    free_value = need
    check = p.check_disk(est, tmp_path / "not" / "there")
    assert check.ok is True
    assert asked == [tmp_path]  # nearest existing parent
    assert (check.need_bytes, check.margin_bytes) == (est.size_high, p.DISK_MARGIN_BYTES)
    free_value = need - 1
    assert p.check_disk(est, tmp_path).ok is False


def test_disk_check_defaults_to_the_output_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(p, "output_root", lambda: tmp_path / "voice_clone")
    monkeypatch.setattr(p, "free_bytes", lambda _path: 10**12)
    check = p.check_disk(p.estimate("abc", "kokoro", "cpu"))
    assert check.folder == str(tmp_path / "voice_clone") and check.ok


# ------------------------------------------------------------------ store


def _record(path, **kw):
    args = dict(units=200.0, audio_seconds=10.0, compute_seconds=5.0, path=path)
    args.update(kw)
    return p.record_measurement("kokoro", "cpu", KOKORO_V, HW, **args)


def test_measurement_is_stored_and_read_back(tmp_path):
    path = tmp_path / "tts" / "speed.json"
    cal = _record(path, source="check")
    assert cal is not None and cal.source == "check"
    loaded = p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path)
    assert loaded == cal
    assert not list(path.parent.glob("*.tmp"))


def test_other_version_or_hardware_measures_again(tmp_path):
    path = tmp_path / "speed.json"
    _record(path)
    assert p.load_calibration("kokoro", "cpu", KOKORO_V + "x", HW, path=path) is None
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW + " / new CPU", path=path) is None
    assert p.load_calibration("kokoro", "cuda", KOKORO_V, HW, path=path) is None
    assert p.load_calibration("omnivoice", "cpu", KOKORO_V, HW, path=path) is None


def test_runs_too_short_to_measure_are_not_stored(tmp_path):
    path = tmp_path / "speed.json"
    assert _record(path, audio_seconds=4.9) is None
    assert not path.exists()
    # OmniVoice needs 8 s: shorter passes are mostly its fixed cost.
    assert p.record_measurement("omnivoice", "cpu", "v", HW, units=100, audio_seconds=7.9,
                                compute_seconds=160, path=path) is None
    assert p.record_measurement("omnivoice", "cpu", "v", HW, units=100, audio_seconds=8.0,
                                compute_seconds=160, path=path) is not None


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_unusable_numbers_are_not_stored(tmp_path, bad):
    path = tmp_path / "speed.json"
    assert _record(path, compute_seconds=bad) is None
    assert _record(path, units=bad) is None
    assert not path.exists()


def test_a_new_measurement_keeps_the_other_engines(tmp_path):
    path = tmp_path / "speed.json"
    _record(path)
    p.record_measurement("omnivoice", "cpu", "omni 1", HW, units=300, audio_seconds=20,
                         compute_seconds=400, path=path)
    _record(path, compute_seconds=7.0, source="run")
    assert p.load_calibration("omnivoice", "cpu", "omni 1", HW, path=path) is not None
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path).compute_seconds == 7.0


@pytest.mark.parametrize("content", [
    "not json",
    json.dumps([1, 2]),
    json.dumps({"version": 99, "entries": {}}),
    json.dumps({"version": 1, "entries": {"kokoro/cpu": {"engine": "kokoro"}}}),
    json.dumps({"version": 1, "entries": {"kokoro/cpu": {
        "engine": "kokoro", "device": "cpu", "engine_version": KOKORO_V, "hardware": HW,
        "units": "200", "audio_seconds": 10, "compute_seconds": 5, "speed": 1,
        "source": "check", "measured_at": "x"}}}),
])
def test_damaged_store_is_ignored_and_then_replaced(tmp_path, content):
    path = tmp_path / "speed.json"
    path.write_text(content, encoding="utf-8")
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path) is None
    assert _record(path) is not None
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path) is not None


@pytest.mark.parametrize("units, audio, compute, speed", [
    (1e200, 1e200, 5.0, 1e200),   # rate underflows to 0
    (1e-200, 1e200, 1e-200, 1.0),  # rate and ratio underflow
    (1e300, 1e-300, 5.0, 1e-300),  # rate overflows to inf
])
def test_absurd_stored_numbers_are_measured_again(tmp_path, units, audio, compute, speed):
    path = tmp_path / "speed.json"
    entry = {"engine": "kokoro", "device": "cpu", "engine_version": KOKORO_V, "hardware": HW,
             "units": units, "audio_seconds": audio, "compute_seconds": compute,
             "speed": speed, "source": "run", "measured_at": "x"}
    path.write_text(json.dumps({"version": 1, "entries": {"kokoro/cpu": entry}}),
                    encoding="utf-8")
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path) is None


def test_store_writes_leave_no_temp_files_behind(tmp_path):
    path = tmp_path / "speed.json"
    for i in range(3):
        _record(path, compute_seconds=5.0 + i)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["speed.json"]
    assert p.load_calibration("kokoro", "cpu", KOKORO_V, HW, path=path).compute_seconds == 7.0


def test_cuda_fingerprint_names_the_card(monkeypatch):
    import sys
    import types

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(get_device_name=lambda _i: "Test GPU 4000"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert p.hardware_fingerprint("cuda").endswith("Test GPU 4000")
    assert "Test GPU" not in p.hardware_fingerprint("cpu")


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError):
        p.engine_version("nope")
    assert p.load_calibration("nope", "cpu", "v", HW) is None


# ------------------------------------------------------------------ wording


@pytest.mark.parametrize("low, high, text", [
    (10, 50, "under a minute"),
    (60, 120, "1–2 minutes"),
    (100, 110, "about 2 minutes"),
    (30, 70, "about 1 minute"),
    (5400, 10800, "1.5–3 hours"),
    (3600, 3650, "about 1 hour"),
    (2400, 7200, "40 minutes to 2 hours"),
    (2400, 3700, "40 minutes to 1 hour"),
    (3590, 3610, "about 1 hour"),
    (3600 * 12, 3600 * 20, "12–20 hours"),
])
def test_format_duration_range(low, high, text):
    assert p.format_duration_range(low, high) == text


def test_format_sizes():
    mb = 1024 * 1024
    assert p.format_size(500_000) == "less than 1 MB"
    assert p.format_size(25 * mb) == "25 MB"
    assert p.format_size(2048 * mb) == "2.0 GB"
    assert p.format_size_range(17 * mb, 26 * mb) == "17–26 MB"
    assert p.format_size_range(5 * mb, 5 * mb) == "about 5 MB"
    assert p.format_size_range(mb // 2, 2 * mb) == "up to 2 MB"
    assert p.format_size_range(0, 100) == "less than 1 MB"
    assert p.format_size_range(mb - 1, mb + 1) == "up to 1 MB"
    assert p.format_size_range(900 * mb, 1100 * mb) == "900 MB to 1.1 GB"
