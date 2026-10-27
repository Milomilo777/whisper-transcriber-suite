"""A task cancelled during diarisation must not run the word-alignment pass.

``_run_post_pipeline`` guards the diarisation and chapter branches with
``not task.cancelled`` (a cancelled task's outputs are discarded by the
caller right after), but the stable-ts alignment branch had no such
guard: cancelling during the speaker-detection worker still paid a full
whole-file alignment pass whose result could never be written.
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


def _fake_diarization(monkeypatch, on_diarize):
    import core as _core_pkg

    fake_diar = _t.ModuleType("core.diarization")
    fake_diar.is_available = lambda: True  # type: ignore[attr-defined]
    fake_diar.availability_reason = lambda: ""  # type: ignore[attr-defined]
    fake_diar.diarize = on_diarize  # type: ignore[attr-defined]
    fake_diar.assign_speakers_to_segments = lambda segs, diar: segs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.diarization", fake_diar)
    monkeypatch.setattr(_core_pkg, "diarization", fake_diar, raising=False)


def _fake_alignment(monkeypatch, calls):
    import core as _core_pkg

    fake_align = _t.ModuleType("core.alignment")
    fake_align.is_available = lambda: True  # type: ignore[attr-defined]
    fake_align.availability_reason = lambda: ""  # type: ignore[attr-defined]

    def _refine(_path, segments, **_kw):
        calls.append([s["text"] for s in segments])
        return True  # type: ignore[attr-defined]

    fake_align.refine_word_timestamps_in_place = _refine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.alignment", fake_align)
    monkeypatch.setattr(_core_pkg, "alignment", fake_align, raising=False)


class _Task:
    file_path = "talk.wav"
    cancelled = False
    whisper_task = "transcribe"


def test_cancelled_during_diarisation_skips_alignment(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": True,
        "diarization_num_speakers": -1,
        "diarization_cluster_threshold": 0.5,
        "alignment": "stable_ts",
        "hallucination_detect_enabled": False,
        "auto_chapters_enabled": False,
    })

    task = _Task()

    def _diarize(_path, **_kw):
        # The user presses Cancel while the speaker-detection worker runs.
        task.cancelled = True
        return []

    _fake_diarization(monkeypatch, _diarize)
    refine_calls: list[list[str]] = []
    _fake_alignment(monkeypatch, refine_calls)

    logs: list[str] = []
    speakers = transcriber._run_post_pipeline(
        task, [{"start": 0.0, "end": 1.0, "text": "hi"}], "en", logs.append,
    )

    assert speakers == 0
    assert refine_calls == [], "alignment must not run for a cancelled task"
    assert any("cancel" in m.lower() for m in logs)


def test_uncancelled_task_still_aligns(transcriber, monkeypatch):
    """The guard must not swallow alignment for a live task."""
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": True,
        "diarization_num_speakers": -1,
        "diarization_cluster_threshold": 0.5,
        "alignment": "stable_ts",
        "hallucination_detect_enabled": False,
        "auto_chapters_enabled": False,
    })

    task = _Task()
    _fake_diarization(monkeypatch, lambda _path, **_kw: [])
    refine_calls: list[list[str]] = []
    _fake_alignment(monkeypatch, refine_calls)

    transcriber._run_post_pipeline(
        task, [{"start": 0.0, "end": 1.0, "text": "hi"}], "en", None,
    )

    assert refine_calls == [["hi"]]
