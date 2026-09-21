"""Regression: a Transcribe-tab TIME RANGE on the offline path must PRE-SLICE
the [clip_start, clip_end] span (fast ffmpeg seek) and transcribe only the
slice, then shift results back onto the original timeline — instead of passing
faster_whisper clip_timestamps, which decodes the WHOLE file and hung on a
multi-hour input. Proven live (a [5,15] range on a 30s clip emitted an SRT
starting at 00:00:05); these tests lock the behaviour in hermetically.
"""
from __future__ import annotations

import sys
import types
from typing import Any, NamedTuple

import pytest


@pytest.fixture
def transcriber(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake)
    import core._checkpoint as cp
    import core.config as cfg
    import core.transcriber as t

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")
    monkeypatch.setattr(t, "PIPELINE", None, raising=False)
    monkeypatch.setattr(t, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(t, "MODEL_ERROR", None, raising=False)
    return t


class FWord(NamedTuple):
    start: float
    end: float
    word: str = "w"
    probability: float = 0.9


class FSeg(NamedTuple):
    start: float
    end: float
    text: str = "x"
    words: Any = None
    id: int = 0
    seek: int = 0
    tokens: Any = ()
    avg_logprob: float = -0.1
    compression_ratio: float = 1.0
    no_speech_prob: float = 0.0
    temperature: float = 0.0


class _Info(NamedTuple):
    language: str = "en"
    language_probability: float = 0.9


# ---- _shift_segments (pure offset logic) -----------------------------------

def test_shift_segments_offsets_start_end(transcriber):
    out = list(transcriber._shift_segments([FSeg(0.0, 5.0, "a"), FSeg(5.0, 12.0, "b")], 100.0))
    assert (out[0].start, out[0].end) == (100.0, 105.0)
    assert (out[1].start, out[1].end) == (105.0, 112.0)
    assert out[0].text == "a"  # other fields preserved


def test_shift_segments_shifts_word_times(transcriber):
    s = FSeg(0.0, 5.0, "a", [FWord(1.0, 2.0), FWord(3.0, 4.0)])
    out = list(transcriber._shift_segments([s], 50.0))
    assert [(w.start, w.end) for w in out[0].words] == [(51.0, 52.0), (53.0, 54.0)]


# ---- the time-range branch in transcribe() ---------------------------------

def _stub_engine(t, monkeypatch, slice_path, segs):
    rec: dict[str, Any] = {}

    def fake_slice(src, start, out_dir, end_seconds=None):
        rec["slice_args"] = (src, start, end_seconds)
        return str(slice_path)

    class _Model:
        def transcribe(self, audio_path, **kw):  # noqa: ARG002
            rec["audio_path"] = audio_path
            rec["kwargs"] = kw
            return (iter(segs), _Info())

    monkeypatch.setattr(t, "_slice_audio_from", fake_slice)
    monkeypatch.setattr(t, "MODEL", _Model())
    monkeypatch.setattr(t, "get_duration", lambda p: 3600.0)
    monkeypatch.setattr(t, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(t, "_write_chapter_sidecar", lambda *a, **k: None)
    written: dict[str, Any] = {}
    monkeypatch.setattr(
        t, "_write_outputs",
        lambda base, segs_, *a, **k: written.__setitem__("segs", list(segs_)) or [],
    )
    return rec, written


def test_timerange_preslices_offsets_and_cleans_up(transcriber, monkeypatch, tmp_path):
    t = transcriber
    from core.task import TranscriptionTask

    audio = tmp_path / "src.wav"; audio.write_bytes(b"\0" * 16)
    slice_path = tmp_path / "slice.wav"; slice_path.write_bytes(b"\0" * 16)
    rec, written = _stub_engine(
        t, monkeypatch, slice_path, [FSeg(0.0, 5.0, "d"), FSeg(5.0, 12.0, "e")]
    )

    task = TranscriptionTask(str(audio))
    task.clip_start = 100.0
    task.clip_end = 160.0
    t.transcribe(task, lambda p: None, lambda m: None, language_cb=None)

    # pre-sliced with the exact clip bounds
    assert rec["slice_args"][1] == 100.0 and rec["slice_args"][2] == 160.0
    # transcribed the SLICE, not the whole original
    assert rec["audio_path"] == str(slice_path)
    # the whole-file-decode clip_timestamps arg is NOT used anymore
    assert "clip_timestamps" not in rec["kwargs"]
    # output segments shifted back to the ORIGINAL timeline
    assert written["segs"][0]["start"] == 100.0
    assert written["segs"][0]["end"] == 105.0
    assert written["segs"][1]["end"] == 112.0
    # temp slice deleted
    assert not slice_path.exists()


def test_timerange_start_beyond_eof_raises(transcriber, monkeypatch, tmp_path):
    """A clip start at/after the media length must fail loudly rather
    than slice nothing and write an empty transcript."""
    t = transcriber
    from core.task import TranscriptionTask

    audio = tmp_path / "src.wav"; audio.write_bytes(b"\0" * 16)
    _stub_engine(t, monkeypatch, tmp_path / "slice.wav", [])
    monkeypatch.setattr(
        t, "_slice_audio_from",
        lambda *a, **k: pytest.fail("must not slice at/after EOF"),
    )

    task = TranscriptionTask(str(audio))
    task.clip_start = 5000.0
    task.clip_end = 5010.0
    with pytest.raises(RuntimeError, match="beyond the media length"):
        t.transcribe(task, lambda p: None, lambda m: None, language_cb=None)


def test_no_timerange_uses_whole_file_unchanged(transcriber, monkeypatch, tmp_path):
    t = transcriber
    from core.task import TranscriptionTask

    audio = tmp_path / "src.wav"; audio.write_bytes(b"\0" * 16)
    flags = {"sliced": False}
    monkeypatch.setattr(
        t, "_slice_audio_from",
        lambda *a, **k: (flags.__setitem__("sliced", True), "x")[1],
    )
    rec, _ = _stub_engine(t, monkeypatch, audio, [FSeg(0.0, 5.0, "a")])
    # _stub_engine set _slice_audio_from; re-pin the flagging one after it:
    monkeypatch.setattr(
        t, "_slice_audio_from",
        lambda *a, **k: (flags.__setitem__("sliced", True), "x")[1],
    )

    task = TranscriptionTask(str(audio))  # no clip range
    t.transcribe(task, lambda p: None, lambda m: None, language_cb=None)

    assert flags["sliced"] is False
    assert rec["audio_path"] == str(audio)
    assert "clip_timestamps" not in rec["kwargs"]
