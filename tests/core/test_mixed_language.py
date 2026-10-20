"""Mixed-language audio (experimental): two languages, detected per stretch, never forced into one.

The restriction works on a per-job copy of the model (core.transcriber._two_language_runner), so
the shared MODEL / PIPELINE that other jobs use is never changed.
"""
from __future__ import annotations

import inspect
import sys
import types

import pytest

import core.transcriber as t
from core.task import TranscriptionTask


def _task(**kw):
    task = TranscriptionTask("a.wav")
    for k, v in kw.items():
        setattr(task, k, v)
    return task


@pytest.mark.parametrize("pair,want", [
    (("zh", "en"), ("zh", "en")),
    (("zh-CN", "EN"), ("zh", "en")),
    (("en", "en"), None),
    (("xx", "en"), None),
    (("zh",), None),
    (None, None),
])
def test_pair_rules(pair, want):
    assert t.mixed_language_pair(_task(languages=pair)) == want


def test_no_pair_with_english_translation():
    assert t.mixed_language_pair(_task(languages=("zh", "en"), whisper_task="translate")) is None


def test_kwargs_detect_per_stretch_and_force_no_language():
    kwargs = t._build_transcribe_kwargs(_task(languages=("zh", "en"), language="zh"))
    assert kwargs.get("multilingual") is True
    assert "language" not in kwargs
    single = t._build_transcribe_kwargs(_task(language="zh"))
    assert single.get("language") == "zh" and "multilingual" not in single


class _FakeCt2:
    def __init__(self, rows):
        self.rows = rows
        self.is_multilingual = True

    def detect_language(self, *_a, **_k):
        return self.rows


def test_detection_keeps_only_the_pair_in_model_order():
    rows = [[("<|ja|>", 0.5), ("<|en|>", 0.3), ("<|zh|>", 0.2)], [("<|ko|>", 0.9), ("<|fr|>", 0.1)]]
    view = t._TwoLanguageDetection(_FakeCt2(rows), ("zh", "en"))
    out = view.detect_language("features")
    assert out[0] == [("<|en|>", 0.3), ("<|zh|>", 0.2)]
    assert out[1] == rows[1]  # neither language listed: the model's own answer, not an empty list
    assert view.is_multilingual is True  # everything else reaches the real model


class _FakeWhisperModel:
    def __init__(self):
        self.model = _FakeCt2([[("<|en|>", 1.0)]])
        self.feature_extractor = object()


def test_runner_copy_leaves_the_shared_model_alone():
    shared = _FakeWhisperModel()
    original_ct2 = shared.model
    job = t._two_language_runner(shared, ("zh", "en"))
    assert job is not shared and isinstance(job.model, t._TwoLanguageDetection)
    assert shared.model is original_ct2  # other jobs still see the plain model


def test_batched_pipeline_copy_leaves_the_shared_pipeline_alone():
    shared_model = _FakeWhisperModel()
    pipe = types.SimpleNamespace(model=shared_model)
    job = t._two_language_runner(pipe, ("zh", "en"))
    assert job is not pipe and job.model is not shared_model
    assert isinstance(job.model.model, t._TwoLanguageDetection)
    assert pipe.model is shared_model and not isinstance(shared_model.model, t._TwoLanguageDetection)


def test_faster_whisper_still_detects_through_the_wrapped_call():
    """Fails loudly if a faster-whisper upgrade stops calling detect_language where we wrap it."""
    fw = pytest.importorskip("faster_whisper.transcribe")
    if not hasattr(fw, "BatchedInferencePipeline") or not inspect.isclass(fw.WhisperModel):
        pytest.skip("faster_whisper is a stub in this run")
    seq = inspect.getsource(fw.WhisperModel.generate_segments)
    assert "options.multilingual" in seq and "self.model.detect_language(" in seq
    batched = inspect.getsource(fw.BatchedInferencePipeline)
    assert "self.model.model.detect_language(" in batched
    assert "self.model.detect_language(" in inspect.getsource(fw.WhisperModel.detect_language)


def test_restart_after_a_loop_keeps_per_stretch_detection(monkeypatch):
    seen = {}

    class _Runner:
        def transcribe(self, _path, **kwargs):
            seen.update(kwargs)
            return iter([]), None

    monkeypatch.setattr(t, "_slice_audio_from", lambda *_a: "slice.wav")
    restart = t._loop_guard_restart(_Runner(), "a.wav", {"multilingual": True}, 0.0, "zh", [])
    list(restart(12.0))
    assert "language" not in seen and seen["multilingual"] is True
    seen.clear()
    restart = t._loop_guard_restart(_Runner(), "a.wav", {}, 0.0, "zh", [])
    list(restart(12.0))
    assert seen["language"] == "zh"  # one-language files keep the pinned language


def test_command_carries_the_pair_to_the_worker():
    from app.services.transcription_service import transcribe_command
    assert transcribe_command(_task(languages=("zh", "en")))["languages"] == ["zh", "en"]
    assert transcribe_command(_task())["languages"] is None


# --- App: which pair a queued file gets ------------------------------------------------------

class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


def _app(App, on=True, first="Chinese (Simplified)", second="English", **config):
    a = App.__new__(App)
    a.app_config = dict(config)
    a.mixed_lang_var = _Var(on)
    a.transcribe_lang_var = _Var(first)
    a.transcribe_lang2_var = _Var(second)
    return a


def test_app_pair_when_ticked(App):
    assert App._selected_language_pair(_app(App)) == (("zh-Hans,zh-CN", "en"), "")
    # the engine reduces the picker codes to Whisper codes
    assert t.mixed_language_pair(_task(languages=("zh-Hans,zh-CN", "en"))) == ("zh", "en")


@pytest.mark.parametrize("kw,reason", [
    ({"first": "Auto"}, "not Auto"),
    ({"second": "Chinese (Simplified)"}, "two different"),
    ({"second": "Chinese (Traditional)"}, "two different"),
    ({"transcribe_backend": "whisper_cpp"}, "faster-whisper"),
    ({"translate_to_english": True}, "English translation"),
])
def test_app_falls_back_to_one_language_and_says_why(App, kw, reason):
    pair, why = App._selected_language_pair(_app(App, **kw))
    assert pair is None and reason in why


def test_app_off_means_no_pair_and_no_message(App):
    assert App._selected_language_pair(_app(App, on=False)) == (None, "")
