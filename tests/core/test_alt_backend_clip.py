"""Regression for audit finding [12]: alternate backends must honour the
Transcribe-tab time range.

Before the fix, ``_transcribe_via_alt_backend`` ignored ``task.clip_start`` /
``task.clip_end`` entirely — the backend interface has no clip parameter — so
a clipped request on a non-default engine (whisper_cpp / nvidia_asr) silently
transcribed AND wrote the WHOLE file. The fix slices ``[start, end]`` into a
temp WAV, transcribes that, and offsets the returned segments back onto the
original timeline (mirroring the resume path), writing no whole-file-keyed
checkpoint for a clipped run.
"""
from __future__ import annotations

import pytest

from core import transcriber
from core.backends.base import LanguageInfo
from core.task import TranscriptionTask


class _FakeAltBackend:
    def __init__(self) -> None:
        self.seen_path: str | None = None

    def transcribe_to_segments(self, audio_path, **kwargs):
        self.seen_path = audio_path
        # Slice-relative timestamps: the temp WAV starts at 0 s.
        segs = [
            {"start": 0.0, "end": 2.0, "text": "first",
             "words": [{"start": 0.0, "end": 2.0, "word": "first",
                        "probability": 0.9}]},
            {"start": 2.0, "end": 5.0, "text": "second"},
        ]
        return segs, LanguageInfo(language="en", probability=0.99)


def test_alt_backend_clip_slices_and_offsets(monkeypatch, tmp_path):
    backend = _FakeAltBackend()
    slice_calls: list[dict] = []
    written: dict = {}

    def fake_slice(source_path, start_seconds, out_dir, end_seconds=None):
        slice_calls.append(
            {"start": start_seconds, "end": end_seconds, "src": source_path}
        )
        return str(tmp_path / "fake.slice.wav")  # never created → unlink no-ops

    def fail_checkpoint(*a, **k):  # a clipped run must NOT checkpoint
        raise AssertionError("clipped alt-backend run must not write a checkpoint")

    def fake_write_outputs(base, segments_data, *a, **k):
        written["segments"] = [dict(s) for s in segments_data]
        return []

    monkeypatch.setattr(
        transcriber, "_get_alt_backend", lambda name, status_cb=None: backend
    )
    monkeypatch.setattr(transcriber, "get_duration", lambda p: 600.0)
    monkeypatch.setattr(transcriber, "_slice_audio_from", fake_slice)
    monkeypatch.setattr(transcriber, "_write_periodic_checkpoint", fail_checkpoint)
    monkeypatch.setattr(transcriber, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(transcriber, "_write_outputs", fake_write_outputs)
    monkeypatch.setattr(transcriber, "_write_chapter_sidecar", lambda *a, **k: None)

    task = TranscriptionTask(str(tmp_path / "movie.mp4"))
    task.clip_start = 120.0
    task.clip_end = 180.0

    transcriber._transcribe_via_alt_backend("whisper_cpp", task, None, None, None)

    # The backend transcribed the SLICE, not the original file.
    assert backend.seen_path == str(tmp_path / "fake.slice.wav")
    # The slice was cut from [120, 180].
    assert len(slice_calls) == 1
    assert slice_calls[0]["start"] == pytest.approx(120.0)
    assert slice_calls[0]["end"] == pytest.approx(180.0)
    # Returned segments were shifted back onto the original timeline (+120).
    segs = written["segments"]
    assert segs[0]["start"] == pytest.approx(120.0)
    assert segs[0]["end"] == pytest.approx(122.0)
    assert segs[1]["start"] == pytest.approx(122.0)
    assert segs[1]["end"] == pytest.approx(125.0)
    # Word timestamps shifted too.
    assert segs[0]["words"][0]["start"] == pytest.approx(120.0)
    assert segs[0]["words"][0]["end"] == pytest.approx(122.0)


def test_alt_backend_no_clip_transcribes_whole_file(monkeypatch, tmp_path):
    backend = _FakeAltBackend()
    sliced = {"called": False}

    monkeypatch.setattr(
        transcriber, "_get_alt_backend", lambda name, status_cb=None: backend
    )
    monkeypatch.setattr(transcriber, "get_duration", lambda p: 600.0)
    monkeypatch.setattr(
        transcriber, "_slice_audio_from",
        lambda *a, **k: sliced.__setitem__("called", True),
    )
    monkeypatch.setattr(transcriber, "_write_periodic_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(transcriber, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(transcriber, "_write_outputs", lambda *a, **k: [])
    monkeypatch.setattr(transcriber, "_write_chapter_sidecar", lambda *a, **k: None)

    task = TranscriptionTask(str(tmp_path / "movie.mp4"))
    # No clip set.
    transcriber._transcribe_via_alt_backend("whisper_cpp", task, None, None, None)

    assert sliced["called"] is False
    assert backend.seen_path == str(tmp_path / "movie.mp4")


def test_alt_backend_clip_start_beyond_eof_raises(monkeypatch, tmp_path):
    """A start at/after the media length must fail loudly instead of
    slicing an empty WAV and writing empty output files. Mirrors the
    faster-whisper path's own guard."""
    backend = _FakeAltBackend()

    monkeypatch.setattr(
        transcriber, "_get_alt_backend", lambda name, status_cb=None: backend
    )
    monkeypatch.setattr(transcriber, "get_duration", lambda p: 60.0)
    monkeypatch.setattr(
        transcriber, "_slice_audio_from",
        lambda *a, **k: pytest.fail("must not slice past the media end"),
    )

    task = TranscriptionTask(str(tmp_path / "movie.mp4"))
    task.clip_start = 120.0
    task.clip_end = 180.0

    with pytest.raises(RuntimeError, match="beyond the media length"):
        transcriber._transcribe_via_alt_backend("whisper_cpp", task, None, None, None)


def test_offset_segments_shifts_in_place():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "a",
         "words": [{"start": 0.0, "end": 1.0, "word": "a"}]},
        {"start": 1.0, "end": 2.5, "text": "b"},
    ]
    transcriber._offset_segments(segs, 10.0)
    assert segs[0]["start"] == 10.0
    assert segs[0]["end"] == 11.0
    assert segs[0]["words"][0]["start"] == 10.0
    assert segs[1]["end"] == 12.5
    # Zero offset is a no-op.
    transcriber._offset_segments(segs, 0.0)
    assert segs[0]["start"] == 10.0
