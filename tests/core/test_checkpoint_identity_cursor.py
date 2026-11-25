"""Checkpoint safety: media identity survives a stat failure, and a malformed
cursor never deletes saved segments.

Hermetic: real files under tmp_path, no model, no ffmpeg. Covers two review
findings on the checkpoint durability fix:

1. A source-stat failure used to store null size/mtime, so a source replaced
   afterwards could be resumed onto the old transcript prefix. Identity now
   survives the failure; an unverifiable checkpoint is kept aside, not
   resumed and not deleted.
2. A non-numeric ``last_end_time`` used to make the resume path delete the
   whole partial. The cursor is now recovered from the saved segments, or the
   checkpoint is quarantined.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

from core import _checkpoint as cp


@pytest.fixture
def transcriber(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.config as cfg
    import core.transcriber as t

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")
    monkeypatch.setattr(t, "MODEL", None, raising=False)
    monkeypatch.setattr(t, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(t, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(t, "_ensure_default_backend_loaded", lambda log_cb=None: None)
    getattr(cp, "_RUN_IDENTITY", {}).clear()
    yield t
    getattr(cp, "_RUN_IDENTITY", {}).clear()


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "media.wav"
    p.write_bytes(b"A" * 64)
    return p


SEGS = [
    {"start": 0.0, "end": 40.0, "text": "a"},
    {"start": 40.0, "end": 80.0, "text": "b"},
]


def _fingerprint_and_model(t, task):
    with t._runtime_overrides_scope(task):
        fp = cp.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) \
            or str(t.config.get("whisper_model", ""))
    return fp, model_name


def _write(t, task, audio, **over):
    fp, model_name = _fingerprint_and_model(t, task)
    kwargs = dict(
        backend="faster_whisper", model_name=model_name, language="en",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=80.0,
        segments=SEGS, checkpoint_time=time.time(),
    )
    kwargs.update(over)
    return cp.write_checkpoint(str(audio), **kwargs)


def _stat_blip_for(monkeypatch, path):
    real = os.stat
    target = os.path.abspath(str(path))

    def _stat(p, *a, **kw):
        if os.path.abspath(os.fspath(p)) == target:
            raise OSError(116, "share hiccup")
        return real(p, *a, **kw)

    monkeypatch.setattr(cp.os, "stat", _stat)
    return real


def _quarantined(audio):
    path = cp.checkpoint_path(str(audio))
    return sorted(path.parent.glob(path.name + ".unverified-*"))


# --- finding 1: identity ----------------------------------------------------


def test_run_start_identity_survives_a_stat_failure(transcriber, audio, monkeypatch):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    real_size = audio.stat().st_size
    cp.note_source_identity(str(audio))
    real_stat = _stat_blip_for(monkeypatch, audio)
    _write(transcriber, task, audio)
    monkeypatch.setattr(cp.os, "stat", real_stat)

    data = cp.load_checkpoint(str(audio))
    assert data["source_size"] == real_size
    assert data["source_mtime"] is not None


def test_previous_checkpoint_identity_survives_a_stat_failure(
        transcriber, audio, monkeypatch):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    _write(transcriber, task, audio)
    getattr(cp, "_RUN_IDENTITY", {}).clear()  # a new process: only the file on disk remains
    real_stat = _stat_blip_for(monkeypatch, audio)
    _write(transcriber, task, audio)
    monkeypatch.setattr(cp.os, "stat", real_stat)

    assert cp.load_checkpoint(str(audio))["source_size"] == 64


def test_replaced_source_after_stat_failure_is_not_resumed(
        transcriber, audio, monkeypatch):
    """No known identity at all (blip on the very first write), then the
    media at the path is replaced: no resume, checkpoint kept aside."""
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    real_stat = _stat_blip_for(monkeypatch, audio)
    _write(transcriber, task, audio)
    monkeypatch.setattr(cp.os, "stat", real_stat)
    assert cp.load_checkpoint(str(audio))["source_size"] is None

    audio.write_bytes(b"B" * 200)  # different media, same path
    monkeypatch.setattr(
        transcriber, "_slice_audio_from",
        lambda *a, **kw: pytest.fail("must not resume onto unverified media"),
    )
    logs: list[str] = []
    assert transcriber.resume_transcription(task, log_cb=logs.append) is False

    assert not cp.checkpoint_path(str(audio)).exists()  # fresh run is not blocked
    kept = _quarantined(audio)
    assert len(kept) == 1
    saved = json.loads(kept[0].read_text(encoding="utf-8"))
    assert [s["text"] for s in saved["segments"]] == ["a", "b"]  # text preserved
    assert any("kept aside" in line for line in logs)


def test_quarantine_never_overwrites_an_earlier_one(transcriber, audio):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    for _ in range(2):
        _write(transcriber, task, audio)
        assert cp.quarantine_checkpoint(str(audio)) is not None
    assert len(_quarantined(audio)) == 2


# --- finding 2: malformed cursor --------------------------------------------


@pytest.mark.parametrize("bad", ["abc", [1], {"x": 1}, float("nan"), -5.0, True])
def test_malformed_cursor_is_recovered_from_segments(
        transcriber, audio, monkeypatch, bad):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    _write(transcriber, task, audio)
    path = cp.checkpoint_path(str(audio))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["last_end_time"] = bad
    path.write_text(json.dumps(data), encoding="utf-8")

    seen: dict[str, float] = {}

    def _slice(src, start, out_dir):
        seen["start"] = start
        raise RuntimeError("fresh run would fail here")

    monkeypatch.setattr(transcriber, "_slice_audio_from", _slice)
    assert transcriber.resume_transcription(task) is False

    assert seen["start"] == 80.0  # recovered from the latest segment end
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert [s["text"] for s in kept["segments"]] == ["a", "b"]  # nothing deleted


def test_unrecoverable_cursor_quarantines_instead_of_deleting(
        transcriber, audio, monkeypatch):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    _write(transcriber, task, audio, segments=[{"start": 0.0, "text": "no end"}])
    path = cp.checkpoint_path(str(audio))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["last_end_time"] = "abc"
    path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        transcriber, "_slice_audio_from",
        lambda *a, **kw: pytest.fail("no cursor, nothing to slice"),
    )
    assert transcriber.resume_transcription(task) is False

    assert not path.exists()
    kept = _quarantined(audio)
    assert len(kept) == 1
    assert json.loads(kept[0].read_text(encoding="utf-8"))["segments"][0]["text"] == "no end"


def test_recover_cursor_rules(transcriber):
    f = transcriber._recover_resume_cursor
    assert f({"last_end_time": 12.5, "segments": []}) == 12.5
    assert f({"segments": []}) == 0.0
    assert f({"last_end_time": "x", "segments": []}) is None
    assert f({"last_end_time": "x", "segments": [{"end": 3}, {"end": 9.5}]}) == 9.5
    assert f({"last_end_time": "x", "segments": [{"end": 3}, {"end": "?"}]}) is None
    assert f({"last_end_time": "x", "segments": ["junk"]}) is None
