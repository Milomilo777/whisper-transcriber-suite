"""Transcribe tab: an English-only model with another language asks first (C2.59b).

The Transcribe tab's model picker and language menu allow the same pair the
Live tab did; add() and the multi-file enqueue check it before queueing.
"""
from __future__ import annotations

import types

import pytest

from app import app as app_module
from app.dialogs import english_only_model as dlg

App = app_module.App


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


@pytest.fixture
def fake(monkeypatch):
    """The parts of App the check touches, with the real methods bound."""
    ns = types.SimpleNamespace()
    ns.app_config = {"whisper_model": "tiny.en"}
    ns.logged = []
    ns.log = ns.logged.append
    ns.transcribe_lang_var = _Var("Persian")
    ns._transcribe_model_label_to_slug = {"Tiny EN": "tiny.en", "Tiny": "tiny", "Small": "small"}
    ns.transcribe_model_var = _Var("Tiny EN")
    ns.engine_uses_model = True
    ns._engine_uses_whisper_model = lambda: ns.engine_uses_model
    ns.declined_switch = False

    def on_model_selected():
        if not ns.declined_switch:
            ns.app_config["whisper_model"] = ns._transcribe_model_label_to_slug[
                ns.transcribe_model_var.get()]

    ns._on_model_selected = on_model_selected
    for name in ("_selected_transcribe_language", "_confirm_english_only_model",
                 "_switch_transcribe_model"):
        setattr(ns, name, getattr(App, name).__get__(ns))
    prompts: list = []
    ns.prompts = prompts
    ns.answer = dlg.CHOICE_CANCEL

    def ask(master, prompt):
        prompts.append(prompt)
        return ns.answer

    monkeypatch.setattr(dlg, "ask_english_only", ask)
    return ns


def test_language_codes(fake):
    assert fake._selected_transcribe_language() == "fa"
    fake.transcribe_lang_var.set("Auto")
    assert fake._selected_transcribe_language() is None
    fake.transcribe_lang_var.set("No such language")
    assert fake._selected_transcribe_language() is None


@pytest.mark.parametrize("model,language,asks", [
    ("tiny.en", "Persian", True),
    ("tiny.en", "Auto", True),
    ("tiny.en", "English", False),
    ("tiny", "Persian", False),
    ("distil-large-v3", "German", True),
])
def test_when_it_asks(fake, model, language, asks):
    fake.app_config["whisper_model"] = model
    fake.transcribe_lang_var.set(language)
    fake._confirm_english_only_model()
    assert bool(fake.prompts) is asks


def test_other_engines_are_not_checked(fake):
    fake.engine_uses_model = False
    assert fake._confirm_english_only_model() is True
    assert fake.prompts == []


def test_switch_picks_the_same_size_multilingual_model(fake):
    fake.answer = dlg.CHOICE_SWITCH
    assert fake._confirm_english_only_model() is True
    assert fake.prompts[0].alternative == "tiny"
    assert fake.app_config["whisper_model"] == "tiny"
    assert fake.transcribe_model_var.get() == "Tiny"


def test_switch_declined_by_the_model_change_guard_does_not_queue(fake):
    fake.answer = dlg.CHOICE_SWITCH
    fake.declined_switch = True  # e.g. "a transcription is running; change anyway?" -> No
    assert fake._confirm_english_only_model() is False
    assert fake.app_config["whisper_model"] == "tiny.en"


def test_keep_queues_and_is_remembered(fake):
    fake.answer = dlg.CHOICE_KEEP
    assert fake._confirm_english_only_model() is True
    assert fake._confirm_english_only_model() is True
    assert len(fake.prompts) == 1
    assert fake.app_config["whisper_model"] == "tiny.en"


def test_cancel_does_not_queue(fake):
    assert fake._confirm_english_only_model() is False
    assert any("English only" in line for line in fake.logged)


def test_add_and_bulk_enqueue_check_before_queueing():
    import inspect

    for method in (App.add, App._bulk_enqueue):
        src = inspect.getsource(method)
        assert src.index("_confirm_english_only_model") < src.index("_ensure_transcribe_ready")


def test_declined_switch_is_logged(fake):
    fake.answer = dlg.CHOICE_SWITCH
    fake.declined_switch = True
    fake._confirm_english_only_model()
    assert any("not changed" in line for line in fake.logged)


def test_no_second_dialog_while_one_is_open(fake):
    fake.__dict__["_english_only_asking"] = True
    assert fake._confirm_english_only_model() is False
    assert fake.prompts == []


@pytest.mark.parametrize("model,language,warns", [
    ("tiny.en", None, True),
    ("tiny.en", "fa", True),
    ("tiny.en", "en", False),
    ("small", "fa", False),
])
def test_unattended_queueing_warns_in_the_log(fake, model, language, warns):
    fake._warn_english_only = App._warn_english_only.__get__(fake)
    fake.app_config["whisper_model"] = model
    fake._warn_english_only(language, "clip.mp4")
    assert any("understands English only" in line for line in fake.logged) is warns
    assert fake.prompts == []  # never a dialog nobody is there to answer
