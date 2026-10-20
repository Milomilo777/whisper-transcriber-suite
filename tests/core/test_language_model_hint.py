"""The Transcribe tab's "a model trained for <language>" line and its button (ADR 0015).

Hermetic: bare App objects with stand-in widgets, no Tk root.
"""
from __future__ import annotations

import sys
import types

import pytest

from core import language_models as lm


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


class _Var:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class _Row:
    def __init__(self) -> None:
        self.shown = False

    def winfo_manager(self) -> str:
        return "pack" if self.shown else ""

    def pack(self, **_kw) -> None:
        self.shown = True

    def pack_forget(self) -> None:
        self.shown = False


class _Button:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, **kw) -> None:
        self.text = kw.get("text", self.text)


class _Service:
    def __init__(self) -> None:
        self.stops = 0

    def stop_all(self) -> None:
        self.stops += 1

    def active_workers(self):
        return []


def _bare_app(App, language: str = "Auto", **cfg):
    a = App.__new__(App)
    a.app_config = {"transcribe_backend": "faster_whisper", "whisper_model": "large-v3", **cfg}
    a.logs = []
    a.log = a.logs.append
    a.transcribe_lang_var = _Var(language)
    a.language_model_row = _Row()
    a.language_model_hint_var = _Var("")
    a.language_model_button = _Button()
    a.language_model_anchor = object()
    a.transcription_service = _Service()
    a.refreshed = []
    a._refresh_engine_selector = lambda: a.refreshed.append("engine")
    a._refresh_model_selector = lambda: a.refreshed.append("model")
    return a


def test_hidden_for_auto_and_languages_without_a_model(App):
    for language in ("Auto", "English", "French"):
        a = _bare_app(App, language)
        a._refresh_language_model_hint()
        assert a.language_model_row.shown is False, language


def test_offers_the_persian_model(App):
    a = _bare_app(App, "Persian")
    a._refresh_language_model_hint()
    assert a.language_model_row.shown is True
    assert "Nemotron ASR Persian" in a.language_model_hint_var.get()
    assert "2.5 GB" in a.language_model_hint_var.get()
    assert a.language_model_button.text == "Use it"


def test_use_it_switches_after_a_yes(App, monkeypatch):
    import app.app as app_mod

    asked = []
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda title, text, **k: asked.append(text) or True)
    saved = []
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: saved.append(dict(cfg)))
    a = _bare_app(App, "Persian")
    a._refresh_language_model_hint()
    a._on_language_model_button()
    assert "this app has not measured them" in asked[0] and "no word-level timestamps" in asked[0]
    assert "huggingface.co/mehdi-hf/nemotron-asr-streaming-farsi" in asked[0]
    assert a.app_config["transcribe_backend"] == "nvidia_asr"
    assert a.app_config["nvidia_asr_model_id"] == "mehdi-hf/nemotron-asr-streaming-farsi"
    assert saved and a.transcription_service.stops == 1
    assert a.refreshed == ["engine", "model"]
    assert a.language_model_row.shown is False  # the model is now in use: nothing more to offer


def test_no_switch_on_no(App, monkeypatch):
    import app.app as app_mod

    asked = []
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: asked.append(a) and False)
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: pytest.fail("saved after a No"))
    a = _bare_app(App, "Chinese (Simplified)")  # the picker's code is "zh-Hans,zh-CN"
    a._refresh_language_model_hint()
    assert a.language_model_row.shown is True
    assert "Belle" in a.language_model_hint_var.get() and "Chinese" in a.language_model_hint_var.get()
    a._on_language_model_button()
    assert len(asked) == 1
    assert a.app_config["whisper_model"] == "large-v3"
    assert a.transcription_service.stops == 0


def test_switch_back_when_the_language_changes(App, monkeypatch):
    import app.app as app_mod

    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: pytest.fail("Switch back needs no question"))
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: None)
    a = _bare_app(App, "English")
    lm.apply_language_model(a.app_config, lm.LANGUAGE_MODELS["fa"])
    a._refresh_language_model_hint()
    assert a.language_model_row.shown is True
    assert "writes Persian only" in a.language_model_hint_var.get()
    assert a.language_model_button.text == "Switch back"
    a._on_language_model_button()
    assert a.app_config["transcribe_backend"] == "faster_whisper"
    assert lm.active(a.app_config) is None


def test_every_language_model_dialog_says_it_writes_one_language(App, monkeypatch):
    import app.app as app_mod

    asked = []
    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda title, text, **k: asked.append(text) and False)
    a = _bare_app(App, "Japanese")
    a._refresh_language_model_hint()
    a._on_language_model_button()
    assert "writes Japanese only" in asked[0]
    assert "huggingface.co/kotoba-tech/kotoba-whisper-v2.0-faster" in asked[0]  # the repo it downloads
    assert "no word-level timestamps" not in asked[0]  # a Whisper model keeps them


@pytest.mark.parametrize("language,model", [("Persian", None), ("English", "fa")])
def test_running_job_refusal_changes_nothing(App, monkeypatch, language, model):
    import app.app as app_mod

    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(app_mod, "save_config", lambda cfg: pytest.fail("saved although the switch was refused"))
    a = _bare_app(App, language)
    if model:
        lm.apply_language_model(a.app_config, lm.LANGUAGE_MODELS[model])
    before = dict(a.app_config)
    a._confirm_backend_switch = lambda **k: False
    a._refresh_language_model_hint()
    a._on_language_model_button()
    assert a.app_config == before and a.transcription_service.stops == 0


def test_click_uses_the_config_as_it_is_now(App, monkeypatch):
    # the line was drawn for Persian, then Advanced settings switched to the Persian model already
    import app.app as app_mod

    monkeypatch.setattr(app_mod.messagebox, "askyesno", lambda *a, **k: pytest.fail("nothing left to ask"))
    a = _bare_app(App, "Persian")
    a._refresh_language_model_hint()
    lm.apply_language_model(a.app_config, lm.LANGUAGE_MODELS["fa"])
    a._on_language_model_button()
    assert a.language_model_row.shown is False
