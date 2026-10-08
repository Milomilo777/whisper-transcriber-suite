"""Review fixes for voice cloning and the speed store (core/voice_clone.py,
core/tts_plan.py): empty OmniVoice output is an error, the sample rate comes
from the model, ffmpeg errors on a non-ASCII path stay readable, two runs in
the same second get their own folders, and the speed store survives a reader
holding it open on Windows."""
from __future__ import annotations

import os
import subprocess
import sys
import types
import wave

import pytest

from core import tts_plan, voice_clone


def _fake_soundfile(monkeypatch) -> list:
    written: list = []

    def fake_write(path, data, sr):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(b"\x00\x00" * len(data))
        written.append((path, sr, len(data)))

    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(write=fake_write))
    return written


def test_empty_omnivoice_output_is_an_error_not_a_zero_second_file(monkeypatch, tmp_path):
    class EmptyModel:
        def generate(self, **_kw):
            return [[]]

    written = _fake_soundfile(monkeypatch)
    out = tmp_path / "o.wav"
    with pytest.raises(RuntimeError, match="no audio"):
        voice_clone.generate(EmptyModel(), "hi", [], str(out), consent_accepted=False)
    assert written == [] and not out.exists()


def test_the_sample_rate_comes_from_the_model(monkeypatch, tmp_path):
    class Model44k:
        sampling_rate = 44100

        def generate(self, **_kw):
            return [[0.0] * 44100]

    written = _fake_soundfile(monkeypatch)
    result = voice_clone.generate(Model44k(), "hi", [], str(tmp_path / "o.wav"),
                                  consent_accepted=False)
    assert written[0][1] == 44100
    assert result.audio_seconds == pytest.approx(1.0)


def test_a_model_without_a_rate_is_taken_as_24_khz(monkeypatch, tmp_path):
    class Model:
        def generate(self, **_kw):
            return [[0.0] * 2400]

    written = _fake_soundfile(monkeypatch)
    result = voice_clone.generate(Model(), "hi", [], str(tmp_path / "o.wav"),
                                  consent_accepted=False)
    assert written[0][1] == 24000 and result.audio_seconds == pytest.approx(0.1)


@pytest.mark.parametrize("call", ["trim", "concat"])
def test_ffmpeg_output_is_decoded_as_utf8(monkeypatch, tmp_path, call):
    """A cp1252 decode of ffmpeg's UTF-8 error about a Persian path raises in
    subprocess's reader thread and the error text is lost."""
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ref = tmp_path / "a.wav"
    ref.write_bytes(b"\x00")
    with pytest.raises(RuntimeError):
        if call == "trim":
            voice_clone.trim_reference_sample(str(ref), str(tmp_path / "t.wav"))
        else:
            voice_clone._concat_references([str(ref), str(ref)])
    assert seen.get("encoding") == "utf-8" and seen.get("errors") == "replace"


def test_two_runs_in_the_same_second_get_their_own_folders(monkeypatch, tmp_path):
    from core import config as _cfg

    monkeypatch.setattr(_cfg, "user_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(voice_clone.time, "strftime", lambda *_a: "20261008-120000")
    first, second = voice_clone.session_work_dir(), voice_clone.session_work_dir()
    assert first != second
    assert os.path.isdir(first) and os.path.isdir(second)
    assert os.path.dirname(first) == os.path.dirname(second) == str(tmp_path / "voice_clone")


def test_the_speed_store_is_written_while_a_reader_briefly_holds_it(monkeypatch, tmp_path):
    real = os.replace
    failures = {"left": 2}

    def locked_then_free(src, dst):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(5, "Access is denied")
        real(src, dst)

    monkeypatch.setattr(os, "replace", locked_then_free)
    target = tmp_path / "speed.json"
    cal = tts_plan.record_measurement(
        "kokoro", "cpu", "kokoro 1.0", "hw", units=500.0, audio_seconds=30.0,
        compute_seconds=10.0, path=target)
    assert cal is not None and target.is_file()
    assert failures["left"] == 0
