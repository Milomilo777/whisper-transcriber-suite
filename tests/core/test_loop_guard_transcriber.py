"""Loop guard + windowed VAD wired into core.transcriber (both decode paths).

The engine is faked: the first decode loops ("so good" over and over, as in
the field report); the restart decode returns normal lines. The tests check
what the transcriber asks the engine for on the restart (no previous-text
prompt, language pinned, the right slice) and what ends up in the output.
"""
from __future__ import annotations

import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from core import vad_window


@pytest.fixture
def t(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake)
    import core._checkpoint as cp
    import core.config as cfg
    import core.transcriber as tr

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    for key, value in (
        ("transcribe_backend", "faster_whisper"), ("demucs_enabled", False),
        ("denoise_enabled", False), ("word_timestamps", False),
        ("vad_enabled", True), ("vad_window_s", 30), ("loop_guard_repeats", 3),
    ):
        monkeypatch.setitem(tr.config, key, value)
    monkeypatch.setattr(tr, "PIPELINE", None, raising=False)
    monkeypatch.setattr(tr, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(tr, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(tr, "get_duration", lambda p: 600.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda p: None)
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(tr, "_write_chapter_sidecar", lambda *a, **k: None)
    return tr


@dataclass
class Word:
    start: float
    end: float
    word: str = "w"
    probability: float = 0.9


@dataclass
class Seg:
    start: float
    end: float
    text: str
    words: Any = field(default_factory=list)


@dataclass
class Info:
    language: str = "zh"
    language_probability: float = 0.8


def run_of(text: str, start: float, n: int) -> list[Seg]:
    return [Seg(start + i, start + i + 1, text) for i in range(n)]


class Engine:
    """Fake WhisperModel: one scripted segment list per transcribe() call."""

    def __init__(self, *scripts: list[Seg]) -> None:
        self.scripts = list(scripts)
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio_path, **kwargs):
        self.calls.append({
            "path": audio_path, "kwargs": dict(kwargs),
            "vad_window": vad_window._WINDOW_S.get(),
        })
        return iter(self.scripts.pop(0)), Info()


def _wire(t, monkeypatch, tmp_path, engine, *, batched=False):
    slices: list[tuple[str, float]] = []

    def fake_slice(src, start, out_dir, end_seconds=None):  # noqa: ARG001
        path = tmp_path / f"slice{len(slices)}.wav"
        path.write_bytes(b"\0")
        slices.append((src, float(start)))
        return str(path)

    monkeypatch.setattr(t, "_slice_audio_from", fake_slice)
    monkeypatch.setattr(t, "MODEL", engine)
    if batched:
        monkeypatch.setattr(t, "PIPELINE", engine)
    written: dict[str, Any] = {}
    monkeypatch.setattr(
        t, "_write_outputs",
        lambda base, segs, *a, **k: written.__setitem__("segs", list(segs)) or [],
    )
    return slices, written


def _longest_run(segs: list[dict[str, Any]]) -> int:
    best = run = 0
    prev = None
    for s in segs:
        run = run + 1 if s["text"] == prev else 1
        prev = s["text"]
        best = max(best, run)
    return best


def test_loop_restarts_without_conditioning_and_pinned_language(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine(
        [Seg(0, 5, "hello class"), *run_of("so good", 5, 30)],
        [Seg(0, 4, "now the harmony"), Seg(4, 9, "the end", [Word(4, 5)])],
    )
    slices, written = _wire(t, monkeypatch, tmp_path, engine)
    logs: list[str] = []

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, logs.append)

    assert len(engine.calls) == 2
    first, second = engine.calls
    assert "condition_on_previous_text" not in first["kwargs"]  # default kept
    assert second["kwargs"]["condition_on_previous_text"] is False
    assert second["kwargs"]["language"] == "zh"  # detected on the first pass
    assert slices == [(str(audio), 6.0)]  # from the second "so good"
    assert second["path"] == str(tmp_path / "slice0.wav")
    assert first["vad_window"] == 30.0 and second["vad_window"] == 30.0

    segs = written["segs"]
    assert [s["text"] for s in segs] == [
        "hello class", "so good", "now the harmony", "the end",
    ]
    assert [(s["start"], s["end"]) for s in segs] == [
        (0, 5), (5, 6), (6.0, 10.0), (10.0, 15.0),
    ]
    assert not (tmp_path / "slice0.wav").exists()  # restart slice cleaned up
    assert any("Loop guard: 8 identical lines" in m for m in logs)
    assert any("1 restart(s), 0 repeated line(s) dropped" in m for m in logs)


def test_clipped_run_restarts_on_the_clip_timeline(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    # times are relative to the clip slice (clip_start = 100)
    engine = Engine(
        [Seg(0, 2, "intro"), *run_of("这个是", 2, 9)],
        [Seg(0, 3, "后面的话")],
    )
    slices, written = _wire(t, monkeypatch, tmp_path, engine)
    task = TranscriptionTask(str(audio))
    task.clip_start = 100.0
    task.clip_end = 200.0

    t.transcribe(task, lambda p: None, lambda m: None)

    clip_slice = str(tmp_path / "slice0.wav")
    assert slices == [(str(audio), 100.0), (clip_slice, 3.0)]
    segs = written["segs"]
    assert [s["text"] for s in segs] == ["intro", "这个是", "后面的话"]
    assert segs[2]["start"] == 103.0 and segs[2]["end"] == 106.0


def test_batched_pipeline_drops_repeats_without_restart(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine([Seg(0, 1, "a"), *run_of("so good", 1, 10), Seg(11, 12, "b")])
    slices, written = _wire(t, monkeypatch, tmp_path, engine, batched=True)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    assert len(engine.calls) == 1 and slices == []
    assert [s["text"] for s in written["segs"]] == ["a", "so good", "b"]


def test_guard_and_window_can_be_switched_off(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    monkeypatch.setitem(t.config, "loop_guard_repeats", 0)
    monkeypatch.setitem(t.config, "vad_window_s", 0)
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine(run_of("so good", 0, 5))
    _slices, written = _wire(t, monkeypatch, tmp_path, engine)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    assert engine.calls[0]["vad_window"] == 0.0
    assert [s["text"] for s in written["segs"]] == ["so good"] * 5


def test_checkpoints_never_hold_the_loop(t, monkeypatch, tmp_path):
    """A checkpoint written mid-loop must not carry the repeats (W5)."""
    from core.task import TranscriptionTask

    monkeypatch.setattr(t, "_CHECKPOINT_EVERY_N_SEGMENTS", 1)
    saved: list[list[str]] = []
    monkeypatch.setattr(
        t, "_write_periodic_checkpoint",
        lambda task, segs, *a, **k: saved.append([s["text"] for s in segs]),
    )
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine(run_of("so good", 0, 12), [Seg(0, 1, "fine")])
    _wire(t, monkeypatch, tmp_path, engine)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    assert saved and all(_longest_run([{"text": x} for x in s]) < 3 for s in saved)


def test_resume_tail_is_guarded_across_the_seam(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    prior = [{"start": 0.0, "end": 90.0, "text": "a"},
             {"start": 90.0, "end": 100.0, "text": "so good"}]
    task = TranscriptionTask(str(audio))
    with t._runtime_overrides_scope(task):
        fp = _checkpoint.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) \
            or str(t.config.get("whisper_model", ""))
    _checkpoint.write_checkpoint(
        str(audio), backend="faster_whisper", model_name=model_name,
        language="zh", language_probability=0.9, cfg_fingerprint=fp,
        last_end_time=100.0, segments=prior, checkpoint_time=time.time(),
    )
    # The tail loops on the checkpointed line. Its first copy is never back
    # to back with the checkpointed one (other timeline), so the loop is
    # judged on the tail alone: 8 tight copies there restart the decode.
    engine = Engine(run_of("so good", 0, 9) + [Seg(9, 10, "x")], [Seg(0, 2, "real")])
    slices, written = _wire(t, monkeypatch, tmp_path, engine)

    assert t.resume_transcription(task) is True

    tail_slice = str(tmp_path / "slice0.wav")
    assert slices == [(str(audio), 100.0), (tail_slice, 1.0)]
    assert engine.calls[1]["kwargs"]["condition_on_previous_text"] is False
    assert engine.calls[1]["kwargs"]["language"] == "zh"
    assert engine.calls[0]["vad_window"] == 30.0
    segs = written["segs"]
    assert [s["text"] for s in segs] == ["a", "so good", "so good", "real"]
    assert segs[3]["start"] == 101.0 and segs[3]["end"] == 103.0


# ---- C2.53: cancel during a drop, marks, resume checkpoints, no speech --------

def test_cancel_during_a_long_drop_stops_the_decode(t, monkeypatch, tmp_path):
    """S01-2: the guard used to eat a whole loop inside one next() call."""
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    pulled: list[int] = []

    def looping():
        yield Seg(0, 1, "a")
        for i in range(1000):
            pulled.append(i)
            yield Seg(1 + i, 2 + i, "so good")

    class LoopEngine(Engine):
        def transcribe(self, audio_path, **kwargs):
            self.calls.append({"path": audio_path, "kwargs": dict(kwargs)})
            return looping(), Info()

    engine = LoopEngine()
    _slices, written = _wire(t, monkeypatch, tmp_path, engine, batched=True)
    task = TranscriptionTask(str(audio))
    calls: list[int] = []

    def progress(p: int) -> None:
        calls.append(p)
        if len(calls) == 20:
            task.cancelled = True

    t.transcribe(task, progress, lambda m: None)

    assert len(pulled) < 100  # the decode was closed long before its end
    assert written == {}  # a cancelled run writes no outputs
    data = _checkpoint.load_checkpoint(str(audio))
    assert data is not None
    assert data["segment_count"] == len(data["segments"]) == 2
    assert [s["text"] for s in data["segments"]] == ["a", "so good"]
    assert data["last_end_time"] == 2.0  # the last KEPT row, not a tick


def test_kept_tight_repeats_reach_the_output_marked(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "prayer.wav"
    audio.write_bytes(b"\0" * 16)
    amen = [Seg(round(2 + i * 0.35, 2), round(2.3 + i * 0.35, 2), "Amen.") for i in range(4)]
    engine = Engine([Seg(0, 2, "Let us pray."), *amen, Seg(10, 12, "Go in peace.")])
    _slices, written = _wire(t, monkeypatch, tmp_path, engine)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    segs = written["segs"]
    assert [s["text"] for s in segs] == ["Let us pray.", *["Amen."] * 4, "Go in peace."]
    assert [s.get("suspect_reason") for s in segs] == [
        None, None, "repeated-line", "repeated-line", "repeated-line", None]
    assert len(engine.calls) == 1  # no restart for a short streak


def test_spaced_repeats_reach_the_output_unchanged(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "prayer.wav"
    audio.write_bytes(b"\0" * 16)
    amen = [Seg(3.0 * i, 3.0 * i + 2.5, "Amen.") for i in range(10)]
    engine = Engine(amen)
    _slices, written = _wire(t, monkeypatch, tmp_path, engine)

    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    assert [s["text"] for s in written["segs"]] == ["Amen."] * 10
    assert not any(s.get("suspect") for s in written["segs"])
    assert len(engine.calls) == 1


def _write_prior_checkpoint(t, audio, prior, last_end):
    from core import _checkpoint
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    with t._runtime_overrides_scope(task):
        fp = _checkpoint.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) \
            or str(t.config.get("whisper_model", ""))
    _checkpoint.write_checkpoint(
        str(audio), backend="faster_whisper", model_name=model_name,
        language="zh", language_probability=0.9, cfg_fingerprint=fp,
        last_end_time=last_end, segments=prior, checkpoint_time=time.time(),
    )
    return task


def test_resumed_tail_writes_periodic_checkpoints(t, monkeypatch, tmp_path):
    """S01-6: a late crash in the tail used to repeat the whole tail."""
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    prior = [{"start": 0.0, "end": 100.0, "text": "first half"}]
    task = _write_prior_checkpoint(t, audio, prior, 100.0)
    engine = Engine([Seg(0, 5, "one"), Seg(5, 9, "two"), Seg(9, 12, "three")])
    _wire(t, monkeypatch, tmp_path, engine)
    monkeypatch.setattr(t, "_CHECKPOINT_EVERY_N_SEGMENTS", 2)
    saved: list[tuple[list[str], float]] = []
    real_write = t._write_periodic_checkpoint

    def spy(task_, segs, last_end, *a, **k):
        saved.append(([s["text"] for s in segs], last_end))
        return real_write(task_, segs, last_end, *a, **k)

    monkeypatch.setattr(t, "_write_periodic_checkpoint", spy)

    assert t.resume_transcription(task) is True

    assert saved == [(["first half", "one", "two"], 109.0)]


def test_resume_cancel_on_the_last_segment_skips_the_post_pipeline(t, monkeypatch, tmp_path):
    from core import _checkpoint

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)
    prior = [{"start": 0.0, "end": 100.0, "text": "first half"}]
    task = _write_prior_checkpoint(t, audio, prior, 100.0)
    engine = Engine([Seg(0, 5, "one"), Seg(5, 9, "two")])
    _slices, written = _wire(t, monkeypatch, tmp_path, engine)
    post: list[int] = []
    monkeypatch.setattr(t, "_run_post_pipeline", lambda *a, **k: post.append(1) or 0)
    seen: list[int] = []

    def progress(p: int) -> None:
        seen.append(p)
        if len(seen) == 2:
            task.cancelled = True

    assert t.resume_transcription(task, progress) is True

    assert post == [] and written == {}
    data = _checkpoint.load_checkpoint(str(audio))
    assert data is not None
    assert [s["text"] for s in data["segments"]] == ["first half", "one", "two"]
    assert data["last_end_time"] == 109.0


def test_decoder_error_mid_file_keeps_the_decoded_segments(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"\0" * 16)

    def broken():
        yield Seg(0, 4, "one")
        yield Seg(4, 8, "two")
        raise RuntimeError("CUDA out of memory")

    class BrokenEngine(Engine):
        def transcribe(self, audio_path, **kwargs):
            self.calls.append({"path": audio_path, "kwargs": dict(kwargs)})
            return broken(), Info()

    _wire(t, monkeypatch, tmp_path, BrokenEngine())

    with pytest.raises(RuntimeError, match="out of memory"):
        t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)

    data = _checkpoint.load_checkpoint(str(audio))
    assert data is not None
    assert [s["text"] for s in data["segments"]] == ["one", "two"]
    assert data["last_end_time"] == 8.0


@pytest.mark.parametrize("script", [[], [Seg(0, 3, ""), Seg(3, 5, "  ")]])
def test_no_speech_is_said_and_outputs_are_still_written(t, monkeypatch, tmp_path, script):
    """S01-5: an empty transcript used to finish like any other success."""
    from core.task import TranscriptionTask

    audio = tmp_path / "silence.wav"
    audio.write_bytes(b"\0" * 16)
    _slices, written = _wire(t, monkeypatch, tmp_path, Engine(script))
    logs: list[str] = []
    task = TranscriptionTask(str(audio))

    t.transcribe(task, lambda p: None, logs.append)

    assert "segs" in written  # the (empty) outputs are still written
    assert task.no_speech is True
    assert any("No speech recognised" in m for m in logs)


def test_speech_clears_the_no_speech_flag(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"\0" * 16)
    _wire(t, monkeypatch, tmp_path, Engine([Seg(0, 3, "hello")]))
    logs: list[str] = []
    task = TranscriptionTask(str(audio))

    t.transcribe(task, lambda p: None, logs.append)

    assert task.no_speech is False
    assert not any("No speech recognised" in m for m in logs)
