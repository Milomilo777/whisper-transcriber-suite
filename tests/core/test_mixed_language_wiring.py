"""Mixed-language audio through core.transcriber's real code paths (the engine is faked).

transcribe(), the loop-guard restart and resume_transcription() must run a per-job copy of the
model whose language detection is limited to the pair, never pin one language, and leave the
shared MODEL alone; a crash-resumed task (rebuilt from history without the pair) gets the pair
back from its checkpoint.
"""
from __future__ import annotations

import json
import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


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
class Seg:
    start: float
    end: float
    text: str
    words: Any = field(default_factory=list)


@dataclass
class Info:
    language: str = "zh"
    language_probability: float = 0.8


class Ct2:
    def detect_language(self, *_a, **_k):
        return [[("<|ja|>", 0.6), ("<|en|>", 0.3), ("<|zh|>", 0.1)]]


class Engine:
    """Fake WhisperModel: one scripted segment list per transcribe() call; records the call."""

    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.model = Ct2()
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio_path, **kwargs):
        # what the job's copy would answer if faster-whisper asked for the language now
        self.calls.append({"kwargs": dict(kwargs), "detects": self.model.detect_language()[0],
                           "is_shared": self is ENGINE[0]})
        return iter(self.scripts.pop(0)), Info()


ENGINE: list[Any] = [None]


def _wire(t, monkeypatch, tmp_path, engine):
    ENGINE[0] = engine
    count = [0]

    def fake_slice(src, start, out_dir, end_seconds=None):  # noqa: ARG001
        path = tmp_path / f"slice{count[0]}.wav"
        count[0] += 1
        path.write_bytes(b"\0")
        return str(path)

    monkeypatch.setattr(t, "_slice_audio_from", fake_slice)
    monkeypatch.setattr(t, "MODEL", engine)
    written: dict[str, Any] = {}
    monkeypatch.setattr(t, "_write_outputs",
                        lambda base, segs, *a, **k: written.__setitem__("segs", list(segs)) or [])
    return written


def _mixed_call(call):
    assert call["kwargs"].get("multilingual") is True
    assert "language" not in call["kwargs"], "one language was pinned"
    assert not call["is_shared"], "the shared model ran the job"
    assert [p[0] for p in call["detects"]] == ["<|en|>", "<|zh|>"]


def test_transcribe_runs_a_restricted_copy_and_restarts_without_pinning(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "class.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine([Seg(0, 5, "hello"), *[Seg(5 + i, 6 + i, "so good") for i in range(30)]],
                    [Seg(0, 4, "back to normal")])
    shared_ct2 = engine.model
    written = _wire(t, monkeypatch, tmp_path, engine)
    task = TranscriptionTask(str(audio))
    task.languages = ("zh", "en")
    logs: list[str] = []
    t.transcribe(task, lambda p: None, logs.append)

    assert len(engine.calls) == 2  # first pass + the loop-guard restart
    for call in engine.calls:
        _mixed_call(call)
    assert engine.model is shared_ct2  # shared model untouched
    assert any("Mixed-language audio" in m for m in logs)
    assert written["segs"][-1]["text"] == "back to normal"


def test_one_language_still_pins_on_restart(t, monkeypatch, tmp_path):
    from core.task import TranscriptionTask

    audio = tmp_path / "class.wav"
    audio.write_bytes(b"\0" * 16)
    engine = Engine([Seg(0, 5, "hello"), *[Seg(5 + i, 6 + i, "so good") for i in range(30)]],
                    [Seg(0, 4, "back to normal")])
    _wire(t, monkeypatch, tmp_path, engine)
    t.transcribe(TranscriptionTask(str(audio)), lambda p: None, lambda m: None)
    assert engine.calls[0]["is_shared"] and "multilingual" not in engine.calls[0]["kwargs"]
    assert engine.calls[1]["kwargs"]["language"] == "zh"


def test_crash_resume_gets_the_pair_back_from_the_checkpoint(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "class.wav"
    audio.write_bytes(b"\0" * 16)
    first = TranscriptionTask(str(audio))
    first.languages = ("zh", "en")
    with t._runtime_overrides_scope(first):
        fp = _checkpoint.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) or str(t.config.get("whisper_model", ""))
    _checkpoint.write_checkpoint(
        str(audio), backend="faster_whisper", model_name=model_name, language="zh",
        language_probability=0.9, cfg_fingerprint=fp, last_end_time=100.0,
        segments=[{"start": 0.0, "end": 100.0, "text": "earlier"}], checkpoint_time=time.time(),
        languages=["zh", "en"],
    )
    engine = Engine([Seg(0, 3, "the rest")])
    written = _wire(t, monkeypatch, tmp_path, engine)
    rebuilt = TranscriptionTask(str(audio))  # as from a history row: no pair
    rebuilt.language = "zh"
    assert t.resume_transcription(rebuilt) is True

    _mixed_call(engine.calls[0])
    assert rebuilt.languages == ("zh", "en")
    assert [s["text"] for s in written["segs"]] == ["earlier", "the rest"]


def test_checkpoint_records_the_pair(t, monkeypatch, tmp_path):
    from core import _checkpoint
    from core.task import TranscriptionTask

    audio = tmp_path / "class.wav"
    audio.write_bytes(b"\0" * 16)
    task = TranscriptionTask(str(audio))
    task.languages = ("zh-Hans,zh-CN", "en")
    t._write_periodic_checkpoint(task, [{"start": 0.0, "end": 1.0, "text": "x"}], 1.0, "zh", 0.9, None)
    data = json.loads(_checkpoint.checkpoint_path(str(audio)).read_text(encoding="utf-8"))
    assert data["languages"] == ["zh", "en"]
    plain = TranscriptionTask(str(audio))
    t._write_periodic_checkpoint(plain, [{"start": 0.0, "end": 1.0, "text": "x"}], 1.0, "zh", 0.9, None)
    data = json.loads(_checkpoint.checkpoint_path(str(audio)).read_text(encoding="utf-8"))
    assert data["languages"] is None
