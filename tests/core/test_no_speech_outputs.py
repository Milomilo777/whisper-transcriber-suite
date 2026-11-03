"""Windowless empty-transcript regressions; no model or network required."""
import json
import wave
from types import SimpleNamespace

import pytest

from app.services.transcription_service import TranscriptionService
from core.task import TranscriptionTask
from tests.core.test_loop_guard_transcriber import Engine, _wire, t  # noqa: F401


@pytest.mark.parametrize("batched", [False, True])
def test_silent_wav_saves_empty_outputs_and_measured_duration(t, monkeypatch, tmp_path, batched):
    audio = tmp_path / "silence.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 16000)
    writer = t._write_outputs
    _wire(t, monkeypatch, tmp_path, Engine([]), batched=batched)
    monkeypatch.setattr(t, "_write_outputs", writer)
    monkeypatch.setattr(t, "get_duration", lambda p: 1.0)
    task = TranscriptionTask(str(audio))
    task.output_formats = ["srt", "json"]
    logs = []
    t.transcribe(task, log_cb=logs.append)
    assert task.no_speech is True
    assert task.word_count == 0
    assert task.audio_duration == 1.0
    assert set(task.output_paths) == {str(audio.with_suffix(".srt")), str(audio.with_suffix(".json"))}
    assert audio.with_suffix(".srt").read_text(encoding="utf-8-sig").strip() == ""
    assert json.loads(audio.with_suffix(".json").read_text(encoding="utf-8-sig")) == []
    assert any("No speech recognised" in line for line in logs)


def test_empty_resume_saves_outputs_before_dropping_checkpoint(t, monkeypatch, tmp_path):
    task = TranscriptionTask(str(tmp_path / "silence.wav"))
    task.output_formats = ["srt", "json"]
    dropped = []

    def delete_checkpoint(path):
        assert task.output_paths
        assert (tmp_path / "silence.srt").exists()
        dropped.append(path)

    monkeypatch.setattr(t._checkpoint, "delete_checkpoint", delete_checkpoint)
    t._write_resumed_outputs(task, [], "en", 0, None, None)
    assert task.no_speech is True
    assert dropped == [task.file_path]


@pytest.mark.parametrize("end, expected", [(None, 7.0), (8.0, 5.0), (20.0, 7.0)])
def test_silent_clip_counts_only_its_audio_span(t, monkeypatch, tmp_path, end, expected):
    _wire(t, monkeypatch, tmp_path, Engine([]))
    monkeypatch.setattr(t, "get_duration", lambda p: 10.0)
    task = TranscriptionTask(str(tmp_path / "silence.wav"))
    task.clip_start, task.clip_end = 3.0, end
    t.transcribe(task)
    assert task.no_speech is True
    assert task.audio_duration == expected


def test_alt_backend_saves_empty_outputs(t, monkeypatch, tmp_path):
    from core.backends.base import LanguageInfo

    backend = SimpleNamespace(transcribe_to_segments=lambda *a, **k: ([], LanguageInfo("en", 0.1)))
    monkeypatch.setattr(t, "_get_alt_backend", lambda *a: backend)
    task = TranscriptionTask(str(tmp_path / "silence.wav"))
    task.output_formats = ["srt", "json"]
    t._transcribe_via_alt_backend("whisper_cpp", task, None, None, None)
    assert task.no_speech is True
    assert task.audio_duration == 600.0
    assert (tmp_path / "silence.srt").exists()
    assert json.loads((tmp_path / "silence.json").read_text(encoding="utf-8-sig")) == []


def test_empty_output_failure_keeps_checkpoint(t, monkeypatch, tmp_path):
    task = TranscriptionTask(str(tmp_path / "silence.wav"))

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(t, "_write_outputs", fail_write)
    monkeypatch.setattr(t._checkpoint, "delete_checkpoint", lambda p: pytest.fail("lost checkpoint"))
    with pytest.raises(OSError, match="disk full"):
        t._write_resumed_outputs(task, [], "en", 0, None, None)
    assert task.output_paths is None


def test_bad_json_does_not_hide_valid_srt_stats(tmp_path):
    audio = tmp_path / "speech.wav"
    sidecar = audio.with_suffix(".json")
    sidecar.write_text("{broken", encoding="utf-8")
    srt = audio.with_suffix(".srt")
    srt.write_text("1\n00:00:00,000 --> 00:00:02,500\nHello world\n\n", encoding="utf-8")
    task = SimpleNamespace(file_path=str(audio), output_paths=[str(sidecar), str(srt)])
    assert TranscriptionService(None)._derive_transcript_stats(task) == (2, 2.5)
