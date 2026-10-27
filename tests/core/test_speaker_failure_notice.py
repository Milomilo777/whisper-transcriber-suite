"""B1: a diarisation failure must reach the UI, not only the console log.

_run_post_pipeline caught diarisation errors and only ``log()``-ed them, so
the job still ended "done" and the transcript was saved without speaker
labels with no user-visible notice. Like the existing ``no_speech`` flag
(core/task.py -> worker "done" event -> app result card), the post pipeline
now sets ``task.speaker_labels_failed`` and the app renders one short notice.
"""
from __future__ import annotations

import sys
import types as _t

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    """Import core.transcriber with faster_whisper stubbed (cheap to load)."""
    if "core.transcriber" not in sys.modules:
        fake_fw = _t.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


def _stub_config(monkeypatch, transcriber):
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": True,
        "diarization_num_speakers": -1,
        "diarization_cluster_threshold": 0.5,
        "alignment": "none",
        "hallucination_detect_enabled": False,
        "auto_chapters_enabled": False,
    })


def _stub_diarization(monkeypatch, diarize):
    fake_diar = _t.ModuleType("core.diarization")
    fake_diar.is_available = lambda: True  # type: ignore[attr-defined]
    fake_diar.availability_reason = lambda: ""  # type: ignore[attr-defined]
    fake_diar.diarize = diarize  # type: ignore[attr-defined]
    fake_diar.assign_speakers_to_segments = lambda segs, diar: segs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.diarization", fake_diar)
    import core as _core_pkg
    monkeypatch.setattr(_core_pkg, "diarization", fake_diar, raising=False)


def test_diarization_failure_sets_the_speaker_labels_failed_flag(
    transcriber, monkeypatch
):
    """A diarisation crash must set the task's UI-notice flag."""

    def _boom(*_a, **_k):
        raise RuntimeError("sherpa-onnx exploded")

    _stub_config(monkeypatch, transcriber)
    _stub_diarization(monkeypatch, _boom)
    task = transcriber.TranscriptionTask("talk.wav")

    speaker_count = transcriber._run_post_pipeline(task, [], "en", None)

    assert speaker_count == 0
    assert task.speaker_labels_failed is True


def test_diarization_success_keeps_the_flag_off(transcriber, monkeypatch):
    """A successful diarisation must not mark the run as label-less."""

    _stub_config(monkeypatch, transcriber)
    _stub_diarization(
        monkeypatch,
        lambda *a, **k: [],  # no diar segments, but no failure either
    )
    task = transcriber.TranscriptionTask("talk.wav")

    transcriber._run_post_pipeline(task, [], "en", None)

    assert task.speaker_labels_failed is False


def test_diarization_disabled_keeps_the_flag_off(transcriber, monkeypatch):
    """Diarisation being switched off is a choice, not a failure."""
    _stub_config(monkeypatch, transcriber)
    transcriber.config["diarization_enabled"] = False

    task = transcriber.TranscriptionTask("talk.wav")
    transcriber._run_post_pipeline(task, [], "en", None)

    assert task.speaker_labels_failed is False
