"""The Transcribe tab's Accuracy row (App._refresh_accuracy_row / _on_accuracy_selected).

Hermetic, the tests/core/test_model_selector.py way: bare App objects with stand-in widgets,
no Tk root, no network, no model download. The pure level table is tests/core/test_accuracy.py.
"""
from __future__ import annotations

import sys
import types

import pytest

from core.model_manager import MODEL_REGISTRY, catalog_models

CUSTOM = "Custom (current setting)"


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


class _Combo:
    def __init__(self, values: list[str]) -> None:
        self.options: dict = {"values": tuple(values)}

    def configure(self, **kw) -> None:
        if "values" in kw:
            kw["values"] = tuple(kw["values"])
        self.options.update(kw)

    def cget(self, name: str):
        return self.options.get(name, "")


class _Packed:
    def __init__(self, shown: bool = True) -> None:
        self.shown = shown

    def winfo_manager(self) -> str:
        return "pack" if self.shown else ""

    def pack(self, **_kw) -> None:
        self.shown = True

    def pack_forget(self) -> None:
        self.shown = False


class _Service:
    def __init__(self) -> None:
        self.stops = 0

    def stop_all(self) -> None:
        self.stops += 1

    def active_workers(self):
        return []


LABELS = {"Fast": "fast", "Balanced": "balanced", "Best": "best"}


def _bare_app(App, monkeypatch, *, whisper_model: str, language: str = "Auto", ram_gb: float = 0.0,
              backend: str = "faster_whisper"):
    a = App.__new__(App)
    a.app_config = {"transcribe_backend": backend, "whisper_model": whisper_model}
    a.logs = []
    a.log = a.logs.append
    a.transcription_service = _Service()
    a.transcribe_lang_var = _Var(language)
    labeled = catalog_models(a.app_config)
    a._transcribe_model_label_to_slug = {lbl: slug for slug, lbl in labeled}
    a.transcribe_model_var = _Var(dict(labeled)[whisper_model])
    a.model_status_var = _Var("")
    a._transcribe_accuracy_label_to_level = dict(LABELS)
    a._accuracy_ram_gb = ram_gb
    a._accuracy_choice = None
    a.transcribe_accuracy_var = _Var("")
    a.transcribe_accuracy_combo = _Combo(list(LABELS))
    a.transcribe_accuracy_note_var = _Var("")
    a.transcribe_accuracy_pick = _Packed()
    a.transcribe_accuracy_check_link = _Packed()
    monkeypatch.setattr("app.app.save_config", lambda _cfg: None)
    return a


# ------------------------------------------------------------- what it shows

@pytest.mark.parametrize("slug,language,expected", [
    ("large-v3-turbo", "Auto", "Balanced"),
    ("large-v3", "Auto", "Best"),
    ("small", "Auto", "Fast"),
    ("large-v3-turbo", "Arabic", "Balanced"),  # Best is the same model there
])
def test_shows_the_level_of_the_saved_model(App, monkeypatch, slug, language, expected):
    a = _bare_app(App, monkeypatch, whisper_model=slug, language=language)
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == expected
    assert a._accuracy_choice == LABELS[expected]
    assert list(a.transcribe_accuracy_combo.cget("values")) == list(LABELS)
    assert a.transcribe_accuracy_pick.shown and a.transcribe_accuracy_check_link.shown


@pytest.mark.parametrize("slug", ["medium", "small.en", "ivrit-large-v3-turbo-he", "tiny"])
def test_a_model_of_no_level_shows_as_custom(App, monkeypatch, slug):
    a = _bare_app(App, monkeypatch, whisper_model=slug)
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == CUSTOM
    assert a._accuracy_choice is None
    assert list(a.transcribe_accuracy_combo.cget("values")) == [*LABELS, CUSTOM]


def test_the_note_names_the_model_and_its_download(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3-turbo")
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_note_var.get() == "Large v3 Turbo model: about 1.6 GB download on first use"


def test_the_note_says_when_the_model_is_already_there(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3")
    monkeypatch.setattr("core.model_manager.model_downloaded", lambda _cfg, _slug: True)
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_note_var.get() == "Large v3 model: already downloaded"


def test_another_engine_names_itself_instead_of_a_level(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3-turbo", backend="whisper_cpp")
    a._accuracy_choice = "balanced"
    App._refresh_accuracy_row(a)
    note = a.transcribe_accuracy_note_var.get()
    assert note.startswith("Engine: ") and note.endswith(" (change in Advanced settings)")
    assert "whisper.cpp" in note
    assert not a.transcribe_accuracy_pick.shown and not a.transcribe_accuracy_check_link.shown
    assert a._accuracy_choice is None


def test_a_bare_app_without_the_row_is_left_alone(App):
    a = App.__new__(App)
    a.app_config = {}
    App._refresh_accuracy_row(a)  # no widgets: nothing to do, nothing raised


# ------------------------------------------------------------- picking a level

def test_picking_a_level_switches_the_model_like_the_model_picker(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3")
    App._refresh_accuracy_row(a)
    a.transcribe_accuracy_var.set("Balanced")
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "large-v3-turbo"
    assert a.app_config["model"]["name"] == MODEL_REGISTRY["large-v3-turbo"]["name"]
    assert a.app_config["model_path"] == ""
    assert a.transcription_service.stops == 1
    assert a.transcribe_accuracy_var.get() == "Balanced"
    assert a.transcribe_model_var.get() == dict(catalog_models({}))["large-v3-turbo"]


def test_picking_the_level_already_in_use_changes_nothing(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3-turbo")
    App._refresh_accuracy_row(a)
    a.transcribe_accuracy_var.set("Balanced")
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "large-v3-turbo"
    assert a.transcription_service.stops == 0


def test_picking_best_for_arabic_takes_turbo(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="small", language="Arabic")
    App._refresh_accuracy_row(a)
    a.transcribe_accuracy_var.set("Best")
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "large-v3-turbo"
    assert a.transcribe_accuracy_var.get() == "Best"


def test_a_small_computer_keeps_the_level_a_person_picked(App, monkeypatch):
    # 4 GB: every level is Small, so the pick changes no model but the combo keeps the word.
    a = _bare_app(App, monkeypatch, whisper_model="small", ram_gb=4.0)
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == "Fast"
    a.transcribe_accuracy_var.set("Best")
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "small"
    assert a.transcribe_accuracy_var.get() == "Best"


def test_a_declined_switch_puts_the_row_back(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3")
    monkeypatch.setattr(App, "_confirm_backend_switch", lambda self, **_kw: False)
    App._refresh_accuracy_row(a)
    a.transcribe_accuracy_var.set("Fast")
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "large-v3"
    assert a.transcribe_accuracy_var.get() == "Best"
    assert a.transcription_service.stops == 0


def test_re_picking_custom_changes_nothing(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="medium")
    App._refresh_accuracy_row(a)
    a.transcribe_accuracy_var.set(CUSTOM)
    App._on_accuracy_selected(a)
    assert a.app_config["whisper_model"] == "medium"
    assert a.transcribe_accuracy_var.get() == CUSTOM


# ------------------------------------------------------- a language change

def test_a_language_change_resolves_the_level_again(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3-turbo")
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == "Balanced"
    a.transcribe_lang_var.set("Arabic")  # Balanced is Turbo there too: nothing changes
    App._refresh_accuracy_row(a, language_changed=True)
    assert a.app_config["whisper_model"] == "large-v3-turbo"
    assert a.transcribe_accuracy_var.get() == "Balanced"
    assert a.transcription_service.stops == 0
    a.transcribe_accuracy_var.set("Fast")
    App._on_accuracy_selected(a)
    a.transcribe_lang_var.set("Auto")  # a level that does change: Fast stays Small
    App._refresh_accuracy_row(a, language_changed=True)
    assert a.app_config["whisper_model"] == "small"
    assert a.transcribe_accuracy_var.get() == "Fast"


def test_a_language_change_resolves_best_to_that_languages_model(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3")
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == "Best"
    a.transcribe_lang_var.set("Arabic")  # Best measured there is Turbo
    App._refresh_accuracy_row(a, language_changed=True)
    assert a.app_config["whisper_model"] == "large-v3-turbo"
    assert a.transcribe_accuracy_var.get() == "Best"
    assert a.transcription_service.stops == 1


def test_a_language_change_never_touches_a_custom_model(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="ivrit-large-v3-turbo-he", language="Hebrew")
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == CUSTOM
    a.transcribe_lang_var.set("Arabic")
    App._refresh_accuracy_row(a, language_changed=True)
    assert a.app_config["whisper_model"] == "ivrit-large-v3-turbo-he"
    assert a.transcription_service.stops == 0


def test_a_language_change_that_keeps_the_model_leaves_the_worker_alone(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3")
    App._refresh_accuracy_row(a)
    assert a.transcribe_accuracy_var.get() == "Best"
    a.transcribe_lang_var.set("Persian")  # Best measured there is Large v3 too
    App._refresh_accuracy_row(a, language_changed=True)
    assert a.app_config["whisper_model"] == "large-v3"
    assert a.transcribe_accuracy_var.get() == "Best"
    assert a.transcription_service.stops == 0


def test_the_language_picker_saves_then_resolves(App, monkeypatch):
    a = _bare_app(App, monkeypatch, whisper_model="large-v3-turbo")
    calls: list[str] = []
    monkeypatch.setattr(App, "_save_transcribe_prefs", lambda self: calls.append("save"))
    monkeypatch.setattr(App, "_refresh_accuracy_row",
                        lambda self, *, language_changed=False: calls.append(f"row:{language_changed}"))
    App._on_transcribe_language_changed(a)
    assert calls == ["save", "row:True"]
