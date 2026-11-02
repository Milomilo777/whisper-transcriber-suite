"""Regression test: _run_post_pipeline wires progress_cb through diarisation.

Background: a long file (~14 min) hit the worker liveness watchdog
(LIVENESS_TIMEOUT_S) mid-diarisation because diarisation was called
without forwarding ``progress_cb``, so no events flowed during the
otherwise-silent long-running C call and the watchdog killed the worker.

The post-pipeline forwards fractions to the shared tracker, which maps
0.5 to 92 percent in the reserved 85..99 diarization slice.
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


def test_diar_progress_uses_shared_85_99_slice(transcriber, monkeypatch):
    """Native fractions use the same tracker as GUI, server and CLI jobs."""
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": True,
        "diarization_num_speakers": -1,
        "diarization_cluster_threshold": 0.5,
        "alignment": "none",
        "hallucination_detect_enabled": False,
        "auto_chapters_enabled": False,
    })

    # Stub core.diarization so we never touch sherpa-onnx. We capture
    # the progress_cb the transcriber hands us, then invoke it with
    # the canonical fraction=0.5 sentinel and pin the int it forwards.
    captured: dict = {}

    def _fake_diarize(_path, *, num_speakers, cluster_threshold, progress_cb, cancelled=None):
        captured["progress_cb"] = progress_cb
        if progress_cb:
            progress_cb(0.5)
        return []  # no diar segments — speaker_count will be 0

    import core as _core_pkg
    fake_diar = _t.ModuleType("core.diarization")
    fake_diar.is_available = lambda: True  # type: ignore[attr-defined]
    fake_diar.availability_reason = lambda: ""  # type: ignore[attr-defined]
    fake_diar.diarize = _fake_diarize  # type: ignore[attr-defined]
    fake_diar.assign_speakers_to_segments = lambda segs, diar: segs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.diarization", fake_diar)
    monkeypatch.setattr(_core_pkg, "diarization", fake_diar, raising=False)

    class _Task:
        file_path = "/dev/null"
        cancelled = False

    progress_calls: list[int] = []
    segs: list[dict] = [{"start": 0.0, "end": 1.0, "text": "hi"}]

    from core.job_progress import JobProgress
    progress = JobProgress(progress_calls.append, diarization=True)
    n = transcriber._run_post_pipeline(
        _Task(), segs, "en", None, progress.diarization,
    )

    # speaker_count = 0 because our fake returned no diar segments.
    assert n == 0
    # The wrapper must have been built + handed to diarize.
    assert captured.get("progress_cb") is not None
    assert progress_calls == [85, 92]


def test_diar_progress_wrapper_is_noop_when_progress_cb_is_none(
    transcriber, monkeypatch,
):
    """No progress_cb supplied = wrapper must not crash when sherpa ticks."""
    monkeypatch.setattr(transcriber, "config", {
        "diarization_enabled": True,
        "diarization_num_speakers": -1,
        "diarization_cluster_threshold": 0.5,
        "alignment": "none",
        "hallucination_detect_enabled": False,
        "auto_chapters_enabled": False,
    })

    def _fake_diarize(_path, *, num_speakers, cluster_threshold, progress_cb, cancelled=None):
        # Sherpa-onnx WILL invoke this even when our wrapper has no
        # user callback. Must not raise.
        if progress_cb:
            progress_cb(0.42)
        return []

    import core as _core_pkg
    fake_diar = _t.ModuleType("core.diarization")
    fake_diar.is_available = lambda: True  # type: ignore[attr-defined]
    fake_diar.availability_reason = lambda: ""  # type: ignore[attr-defined]
    fake_diar.diarize = _fake_diarize  # type: ignore[attr-defined]
    fake_diar.assign_speakers_to_segments = lambda segs, diar: segs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.diarization", fake_diar)
    monkeypatch.setattr(_core_pkg, "diarization", fake_diar, raising=False)

    class _Task:
        file_path = "/dev/null"
        cancelled = False

    # progress_cb defaults to None — must not raise.
    n = transcriber._run_post_pipeline(
        _Task(), [{"start": 0.0, "end": 1.0, "text": "hi"}], "en", None,
    )
    assert n == 0
