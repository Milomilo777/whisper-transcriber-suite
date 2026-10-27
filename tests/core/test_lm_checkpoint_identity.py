"""A web/LAN job on a transformers language model must stamp its resume
checkpoints with the language model it actually ran on.

``_current_backend_and_model`` reads ``_LM_RUNNER.slot`` exactly so "a web
job on a Whisper language model (ADR 0018): a checkpoint from it must not
pass as one of the general model". The transformers (nvidia_asr) engine
path of :func:`transcribe_with_language_model` never sets the slot, so its
checkpoints record the desktop's general model name — a later desktop
resume then validates that mismatched identity and splices general-model
segments onto language-model text.
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    if "core.transcriber" not in sys.modules:
        import types as _t
        fake_fw = _t.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


class _LangInfo:
    language = "fa"
    probability = 0.99


class _FakeBackend:
    def transcribe_to_segments(self, path, **kwargs):
        return ([{"start": 0.0, "end": 2.0, "text": "سلام"}], _LangInfo())


def test_transformers_lm_checkpoint_names_the_lm(transcriber, monkeypatch, tmp_path):
    import core.language_models as lm_mod
    from core.task import TranscriptionTask

    t = transcriber
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"\x00")  # presence only; duration is stubbed

    row = lm_mod.LANGUAGE_MODELS["fa"]  # engine == ENGINE_TRANSFORMERS
    assert row.engine == lm_mod.ENGINE_TRANSFORMERS
    monkeypatch.setattr(lm_mod, "by_model", lambda mid: row)
    monkeypatch.setattr(t, "_language_model_backend",
                        lambda mid, cb=None: _FakeBackend())
    monkeypatch.setattr(t, "release_default_model", lambda: False)
    monkeypatch.setattr(t, "get_duration", lambda p: 10.0)
    monkeypatch.setattr(t, "require_audio_stream", lambda p: None)
    monkeypatch.setattr(t, "_run_post_pipeline", lambda *a, **k: 0)
    monkeypatch.setattr(t, "_write_outputs", lambda *a, **k: [])
    monkeypatch.setattr(t._checkpoint, "delete_checkpoint", lambda *a, **k: None)
    writes: list[dict] = []
    monkeypatch.setattr(t._checkpoint, "write_checkpoint",
                        lambda *a, **kw: writes.append(kw))

    task = TranscriptionTask(str(audio))
    t.transcribe_with_language_model(row.model, task)

    assert writes, "the language-model run wrote no checkpoint"
    stamped = writes[-1]["model_name"]
    assert stamped == row.model, (
        f"checkpoint model_name must be the language model ({row.model!r}), "
        f"not the general model ({stamped!r})"
    )
    stamped_backend = writes[-1]["backend"]
    assert stamped_backend == "nvidia_asr", (
        f"checkpoint backend must be nvidia_asr (the LM engine), "
        f"not the desktop's ({stamped_backend!r})"
    )
