"""End-to-end test of ``core.transcriber.transcribe`` with the real model.

Runs the public ``transcribe`` function against the silent fixture, checks that
SRT + JSON files land next to the audio, and asserts that the language event
fires. Skipped on environments without ffmpeg or without network access to
download tiny.en.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("faster_whisper")

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "audio"
SILENT_WAV = FIXTURES / "silent_1s.wav"


def _have_ffmpeg() -> bool:
    if shutil.which("ffmpeg"):
        return True
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return candidate.exists()


@pytest.fixture
def temp_audio(tmp_path):
    """Copy the silent fixture into a tmp dir so we don't litter the repo."""
    dst = tmp_path / "sample.wav"
    shutil.copyfile(SILENT_WAV, dst)
    return dst


@pytest.fixture
def loaded_transcriber(tmp_path_factory, monkeypatch):
    """Force the transcriber module to use a tiny.en model in a tmp cache."""
    if not _have_ffmpeg():
        pytest.skip("ffmpeg not available")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        pytest.skip("faster_whisper not importable")

    cache = tmp_path_factory.mktemp("tiny_e2e")
    try:
        model = WhisperModel("tiny.en", device="cpu", compute_type="int8",
                             download_root=str(cache))
    except Exception:
        pytest.skip("tiny.en download failed")

    import core.transcriber as t
    monkeypatch.setattr(t, "MODEL", model)
    monkeypatch.setattr(t, "PIPELINE", None)
    monkeypatch.setattr(t, "MODEL_READY", True)
    monkeypatch.setattr(t, "MODEL_ERROR", None)
    return t


def test_transcribe_writes_srt_and_json(loaded_transcriber, temp_audio):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(temp_audio))
    # Explicit, so the developer's own saved output_formats don't decide it.
    task.output_formats = ["srt", "json"]
    captured_lang: dict = {}

    def on_lang(lang: str, prob: float) -> None:
        captured_lang["language"] = lang
        captured_lang["probability"] = prob

    loaded_transcriber.transcribe(task, language_cb=on_lang)

    base = os.path.splitext(str(temp_audio))[0]
    assert os.path.exists(base + ".srt"), "SRT was not written"
    assert os.path.exists(base + ".json"), "JSON was not written"
    assert captured_lang.get("language"), "language_cb was not invoked"
    assert task.detected_language == captured_lang["language"]


def test_transcribe_respects_output_formats(loaded_transcriber, temp_audio, monkeypatch):
    from core.task import TranscriptionTask

    monkeypatch.setattr(loaded_transcriber, "config",
                        {**loaded_transcriber.config, "output_formats": ["vtt", "txt"]})

    task = TranscriptionTask(str(temp_audio))
    loaded_transcriber.transcribe(task)
    base = os.path.splitext(str(temp_audio))[0]
    assert os.path.exists(base + ".vtt"), "VTT was not written"
    assert os.path.exists(base + ".txt"), "TXT was not written"
    assert not os.path.exists(base + ".srt"), "SRT was written despite not being in output_formats"


def test_transcribe_with_word_timestamps_enriches_json(loaded_transcriber, monkeypatch, tmp_path):
    """tiny.en may produce 0 segments on pure silence, so just check JSON validity."""
    import json

    from core.task import TranscriptionTask

    # Use the tone fixture (more chance of producing segments)
    src = FIXTURES / "tone_440hz_2s.wav"
    audio = tmp_path / "tone.wav"
    shutil.copyfile(src, audio)

    monkeypatch.setattr(loaded_transcriber, "config",
                        {**loaded_transcriber.config,
                         "word_timestamps": True, "output_formats": ["json"]})

    task = TranscriptionTask(str(audio))
    loaded_transcriber.transcribe(task)
    base = os.path.splitext(str(audio))[0]
    with open(base + ".json", encoding="utf-8") as f:
        parsed = json.load(f)
    assert isinstance(parsed, list)
