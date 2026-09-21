"""Unit tests for core.diarization — the speaker-assignment matcher.

The actual sherpa-onnx model load + ONNX inference is exercised by a
live smoke test under tests/smoke/test_diarization_smoke.py; this
file pins the deterministic matcher logic and the availability
gates without touching the network or the 35 MB ONNX models.
"""
from __future__ import annotations

import os

import pytest

from core.diarization import (
    DiarSegment,
    DiarizationUnavailable,
    assign_speakers_to_segments,
    availability_reason,
    is_available,
)


# --- matcher --------------------------------------------------------------


def test_assign_speakers_no_diar_segments_is_noop():
    transcript = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    out = assign_speakers_to_segments(transcript, [])
    assert out is transcript  # mutated-in-place / returned for chaining
    assert "speaker" not in transcript[0]


def test_assign_speakers_picks_highest_overlap():
    # Diar windows: 0.0-1.5 = Speaker 00, 1.5-3.0 = Speaker 01
    diar = [
        DiarSegment(0.0, 1.5, "Speaker 00"),
        DiarSegment(1.5, 3.0, "Speaker 01"),
    ]
    transcript = [
        # Segment 0.0-1.0 fully inside Speaker 00.
        {"start": 0.0, "end": 1.0, "text": "alpha"},
        # Segment 1.4-2.4 overlaps 0.1s with Speaker 00, 0.9s with
        # Speaker 01 -> 01 wins.
        {"start": 1.4, "end": 2.4, "text": "beta"},
        # Segment 2.5-2.9 fully inside Speaker 01.
        {"start": 2.5, "end": 2.9, "text": "gamma"},
    ]
    assign_speakers_to_segments(transcript, diar)
    assert transcript[0]["speaker"] == "Speaker 00"
    assert transcript[1]["speaker"] == "Speaker 01"
    assert transcript[2]["speaker"] == "Speaker 01"


def test_assign_speakers_skips_no_overlap_segments():
    diar = [DiarSegment(0.0, 1.0, "Speaker 00")]
    transcript = [
        # Outside any diar window -> no speaker label set.
        {"start": 5.0, "end": 6.0, "text": "silence"},
    ]
    assign_speakers_to_segments(transcript, diar)
    assert "speaker" not in transcript[0]


def test_assign_speakers_handles_zero_duration_segment():
    diar = [DiarSegment(0.0, 2.0, "Speaker 00")]
    transcript = [{"start": 1.0, "end": 1.0, "text": ""}]  # e == s
    assign_speakers_to_segments(transcript, diar)
    # Defensive: the matcher refuses to assign zero-duration segments.
    assert "speaker" not in transcript[0]


def test_assign_speakers_preserves_other_fields():
    diar = [DiarSegment(0.0, 2.0, "Speaker 00")]
    transcript = [{
        "start": 0.5, "end": 1.5, "text": "hi",
        "words": [{"word": "hi", "start": 0.5, "end": 1.5, "probability": 0.9}],
    }]
    assign_speakers_to_segments(transcript, diar)
    assert transcript[0]["speaker"] == "Speaker 00"
    assert transcript[0]["words"][0]["word"] == "hi"
    assert transcript[0]["text"] == "hi"


# --- availability ---------------------------------------------------------


def test_is_available_returns_bool():
    # On the developer machine where models are downloaded, this
    # should be True; in CI / clean-machine environments it returns
    # False. Either way the call must not raise.
    result = is_available()
    assert isinstance(result, bool)


def test_availability_reason_returns_str():
    reason = availability_reason()
    assert isinstance(reason, str)
    # If diarization is available, reason is empty; otherwise the
    # reason names either the missing dep or the missing file.
    if not is_available():
        assert "sherpa-onnx" in reason or "missing" in reason


def test_is_available_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); sherpa-onnx is native, same risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            is_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_availability_reason_also_restores_gc_state():
    """availability_reason() does its own guarded import via the shared
    _sherpa_onnx_importable() helper — must not leave GC disabled either."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            availability_reason()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_diarize_raises_on_missing_models(tmp_path, monkeypatch):
    """When availability_reason() reports something is missing,
    diarize() must raise DiarizationUnavailable rather than crashing
    later inside sherpa_onnx with a less useful error.
    """
    import core.diarization as diar_mod

    monkeypatch.setattr(diar_mod, "availability_reason", lambda: "sherpa-onnx Python package not installed")
    with pytest.raises(DiarizationUnavailable):
        diar_mod.diarize(str(tmp_path / "missing.wav"))


def test_prepare_audio_raises_on_empty_decode(tmp_path, monkeypatch):
    """A valid container with zero audio frames decodes to an empty
    sample array; that must raise DiarizationUnavailable, not reach
    sherpa-onnx's native process() with nothing to chew on."""
    import subprocess as _sp

    import core.diarization as diar_mod

    monkeypatch.setattr(diar_mod, "bundled_binary", lambda _name: "ffmpeg")
    monkeypatch.setattr(
        diar_mod.subprocess,
        "run",
        lambda *a, **kw: _sp.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        ),
    )
    with pytest.raises(DiarizationUnavailable):
        diar_mod._prepare_audio_16k_mono(str(tmp_path / "empty.wav"))
