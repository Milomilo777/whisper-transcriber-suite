"""Download tab: the "Subtitles available" bar and the subtitles-or-transcribe question.

Covers:
  * ``caption_availability_text`` -- manual / automatic / none wording, the YouTube
    "-orig" rule, the cap on named languages.
  * ``App.update_caption_bar`` -- shown for a lookup with subtitles, hidden for none
    and never for an SMTV episode.
  * ``DownloadService.enqueue_from_form`` -- the question appears only when
    "Transcribe after download" is on and the subtitles match the chosen language;
    "Don't ask again" is saved and survives a config reload.
"""
from __future__ import annotations

import types
import tkinter.messagebox  # noqa: F401  -- ensures tkinter.messagebox is a bound attribute to monkeypatch

import pytest

from app.app import App
from app.dialogs import caption_choice as cc
from app.domain.languages import (
    CAPTION_BAR_MAX_LANGUAGES, caption_availability_text, real_caption_langs, resolve_caption_kind,
)
from app.services.download_service import DownloadService
from core import config as cfg

# --- caption_availability_text -------------------------------------------


def test_manual_and_automatic_are_told_apart():
    text = caption_availability_text({"en": "manual", "es": "auto"})
    assert text == "Subtitles available: English (made by the uploader), Spanish (automatic)"


def test_none_gives_an_empty_text():
    assert caption_availability_text({}) == ""


def test_manual_only_and_auto_only():
    assert caption_availability_text({"de": "manual"}) == (
        "Subtitles available: German (made by the uploader)"
    )
    assert caption_availability_text({"fr": "auto"}) == "Subtitles available: French (automatic)"


def test_manual_comes_before_automatic_whatever_the_dict_order():
    text = caption_availability_text({"es": "auto", "en": "manual"})
    assert text.index("English") < text.index("Spanish")


def test_youtube_translations_do_not_flood_the_line():
    # YouTube lists one real speech-recognition track (xx-orig) plus an automatic
    # translation into every language; only the real track is named.
    langs = {"en-orig": "auto", "en": "auto", "de": "auto", "ja": "auto", "fr": "auto"}
    assert caption_availability_text(langs) == "Subtitles available: English (automatic)"


def test_a_language_with_both_kinds_is_named_once_as_manual():
    langs = {"en": "manual", "en-orig": "auto", "de": "auto"}
    assert caption_availability_text(langs) == (
        "Subtitles available: English (made by the uploader)"
    )


def test_the_line_names_at_most_the_cap_and_counts_the_rest():
    codes = ["en", "es", "de", "fr", "it", "pt", "ru", "ja"]
    text = caption_availability_text({c: "manual" for c in codes})
    assert text.endswith(f" and {len(codes) - CAPTION_BAR_MAX_LANGUAGES} more")
    assert text.count("(made by the uploader)") == CAPTION_BAR_MAX_LANGUAGES


def test_an_unknown_code_is_shown_as_it_is_and_a_regional_one_by_its_language():
    text = caption_availability_text({"xx-unknown": "manual", "pt-BR": "manual"})
    assert "xx-unknown (made by the uploader)" in text
    assert "Portuguese (made by the uploader)" in text


# --- App.update_caption_bar -------------------------------------------------


class _Var:
    def __init__(self, value: object = "") -> None:
        self._v = value

    def get(self):  # noqa: ANN201
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


class _Label:
    def __init__(self) -> None:
        self.visible = False

    def pack(self, **_kw) -> None:  # noqa: ANN003
        self.visible = True

    def pack_forget(self) -> None:
        self.visible = False


def _bar_app(caption_langs, smtv_episode=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        caption_bar_var=_Var(),
        caption_bar_label=_Label(),
        current_video_caption_langs=caption_langs,
        _smtv_episode=smtv_episode,
    )


def test_bar_is_shown_with_the_text_for_a_video_with_subtitles():
    app = _bar_app({"en": "manual", "es": "auto"})
    App.update_caption_bar(app)  # type: ignore[arg-type]
    assert app.caption_bar_label.visible
    assert app.caption_bar_var.get() == (
        "Subtitles available: English (made by the uploader), Spanish (automatic)"
    )


def test_bar_is_hidden_when_there_are_no_subtitles():
    app = _bar_app({})
    app.caption_bar_label.visible = True  # left over from a previous video
    App.update_caption_bar(app)  # type: ignore[arg-type]
    assert not app.caption_bar_label.visible
    assert app.caption_bar_var.get() == ""


def test_bar_is_never_shown_for_an_smtv_episode():
    app = _bar_app({"en": "manual"}, smtv_episode=object())
    App.update_caption_bar(app)  # type: ignore[arg-type]
    assert not app.caption_bar_label.visible
    assert app.caption_bar_var.get() == ""


def test_preferred_languages_are_named_first():
    langs = {"ar": "manual", "bg": "manual", "en": "manual", "es": "auto"}
    text = caption_availability_text(langs, prefer=["es", "en"])
    assert text.startswith("Subtitles available: Spanish (automatic), English (made by the uploader)")


def test_the_bar_puts_the_video_language_first():
    app = _bar_app({"ar": "manual", "bg": "manual", "en": "manual"})
    app.current_video_language = "en"
    app.subtitle_lang_var = _Var("Automatic")
    App.update_caption_bar(app)  # type: ignore[arg-type]
    assert app.caption_bar_var.get().startswith("Subtitles available: English")


def test_the_bar_puts_the_chosen_subtitle_language_first():
    app = _bar_app({"ar": "manual", "de": "manual", "en": "manual"})
    app.current_video_language = "en"
    app.subtitle_lang_var = _Var("German")
    App.update_caption_bar(app)  # type: ignore[arg-type]
    assert app.caption_bar_var.get().startswith("Subtitles available: German")


# --- the question before a download that will be transcribed -----------------


def _svc(app) -> DownloadService:
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc


def _form_app(
    tmp_path, *, auto_transcribe=True, subtitle_lang="Automatic",
    caption_langs=None, current_language="en", smtv_episode=None, config=None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        download_url_var=_Var("https://www.youtube.com/watch?v=abc123"),
        download_folder_var=_Var(str(tmp_path)),
        download_mode_var=_Var("Audio and video"),
        audio_format_var=_Var(""),
        video_format_var=_Var(""),
        output_format_var=_Var("mp4"),
        subtitle_lang_var=_Var(subtitle_lang),
        auto_transcribe_var=_Var(auto_transcribe),
        current_video_caption_langs={"en": "manual"} if caption_langs is None else caption_langs,
        current_video_language=current_language,
        current_video_title="Sample video",
        _smtv_episode=smtv_episode,
        app_config=config if config is not None else {},
        download_queue=[],
        refresh_download_queue=lambda: None,
    )


@pytest.fixture
def asked(monkeypatch):
    """Replace the dialog; ``asked.answer`` is what the user "clicks"."""
    calls: list[dict] = []
    state = types.SimpleNamespace(calls=calls, answer=(cc.CHOICE_TRANSCRIBE, False))

    def _ask(_master, *, kind, language):
        calls.append({"kind": kind, "language": language})
        return state.answer

    monkeypatch.setattr("app.dialogs.caption_choice.ask_caption_choice", _ask)
    return state


@pytest.fixture
def svc_factory(monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr(
        "app.services.download_service.save_config", lambda c, *a, **k: saved.append(dict(c))
    )
    handled: list[str] = []

    def make(app) -> DownloadService:
        svc = _svc(app)
        svc.enqueue_caption_only_from_form = lambda: handled.append("captions")  # type: ignore[method-assign]
        svc.process_queue = lambda: handled.append("process")  # type: ignore[method-assign]
        return svc

    make.saved = saved  # type: ignore[attr-defined]
    make.handled = handled  # type: ignore[attr-defined]
    return make


def test_question_appears_when_subtitles_match_and_transcribe_is_on(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path)
    asked.answer = (cc.CHOICE_CAPTIONS, False)
    svc = svc_factory(app)

    svc.enqueue_from_form()

    assert asked.calls == [{"kind": "manual", "language": "English"}]
    assert svc_factory.handled == ["captions"]
    assert app.download_queue == []


def test_choosing_transcribe_carries_on_with_the_normal_download(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path)
    asked.answer = (cc.CHOICE_TRANSCRIBE, False)
    svc = svc_factory(app)

    assert svc._caption_choice() == "transcribe"
    # The normal path then goes on to its own format checks (none loaded here).
    assert svc_factory.handled == []


def test_closing_the_question_cancels_the_download(tmp_path, asked, svc_factory, monkeypatch):
    app = _form_app(tmp_path)
    asked.answer = (cc.CHOICE_CANCEL, True)  # "don't ask" is ignored for a cancel
    svc = svc_factory(app)

    svc.enqueue_from_form()

    assert svc_factory.handled == []
    assert app.download_queue == []
    assert "download_caption_choice" not in app.app_config
    assert svc_factory.saved == []


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"auto_transcribe": False}, "transcribe after download is off"),
        ({"caption_langs": {}}, "the video has no subtitles"),
        ({"caption_langs": {"de": "manual"}}, "subtitles exist only in another language"),
        ({"subtitle_lang": "German", "caption_langs": {"en": "manual"}}, "chosen language differs"),
        ({"smtv_episode": object()}, "an SMTV episode"),
    ],
)
def test_no_question_when_the_subtitles_do_not_apply(tmp_path, asked, svc_factory, overrides, why):
    app = _form_app(tmp_path, **overrides)
    svc = svc_factory(app)

    assert svc._caption_choice() == "", why
    assert asked.calls == [], why


def test_question_follows_the_chosen_language(tmp_path, asked, svc_factory):
    app = _form_app(
        tmp_path, subtitle_lang="German",
        caption_langs={"de": "auto", "en": "manual"},
    )
    svc = svc_factory(app)

    svc._caption_choice()

    assert asked.calls == [{"kind": "auto", "language": "German"}]


def test_dont_ask_again_is_saved_and_asked_no_more(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path)
    asked.answer = (cc.CHOICE_CAPTIONS, True)
    svc = svc_factory(app)

    assert svc._caption_choice() == "captions"
    assert app.app_config["download_caption_choice"] == "captions"
    assert svc_factory.saved and svc_factory.saved[-1]["download_caption_choice"] == "captions"

    asked.calls.clear()
    assert svc._caption_choice() == "captions"  # remembered: no dialog
    assert asked.calls == []


def test_a_remembered_transcribe_skips_the_dialog(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path, config={"download_caption_choice": "transcribe"})

    assert svc_factory(app)._caption_choice() == "transcribe"
    assert asked.calls == []


def test_an_unknown_saved_value_means_ask(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path, config={"download_caption_choice": "banana"})

    svc_factory(app)._caption_choice()

    assert len(asked.calls) == 1


def test_dont_ask_again_persists_across_a_config_reload(tmp_path, monkeypatch, asked):
    for kind in ("config", "cache", "log", "data"):
        folder = tmp_path / kind
        folder.mkdir()
        monkeypatch.setattr(cfg, f"user_{kind}_dir", lambda folder=folder: folder)
    path = tmp_path / "config" / "config.json"
    monkeypatch.setattr(cfg, "config_path", lambda: str(path))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))

    config = cfg.load_config(fetch_online=False)
    assert config["download_caption_choice"] == "ask"  # the shipped default

    app = _form_app(tmp_path, config=config)
    asked.answer = (cc.CHOICE_TRANSCRIBE, True)
    assert _svc(app)._caption_choice() == "transcribe"  # real save_config, isolated folder

    reloaded = cfg.load_config(fetch_online=False)
    assert reloaded["download_caption_choice"] == "transcribe"
    assert cc.remembered_choice(reloaded) == "transcribe"


# --- review fixes: translations, time range, pending lookup -----------------


def test_machine_translations_are_not_real_subtitles_when_the_original_track_exists():
    langs = {"es-orig": "auto", "es": "auto", "en": "auto", "fr": "auto", "de": "manual"}
    assert real_caption_langs(langs) == {"es-orig": "auto", "es": "auto", "de": "manual"}
    assert resolve_caption_kind(langs, "en") == ""  # only a translation of Spanish
    assert resolve_caption_kind(langs, "es") == "auto"
    assert resolve_caption_kind(langs, "de") == "manual"


def test_without_an_original_track_every_automatic_language_counts():
    langs = {"en": "auto", "fr": "auto"}
    assert real_caption_langs(langs) == langs
    assert resolve_caption_kind(langs, "fr") == "auto"


def test_no_question_for_a_translation_of_the_spoken_language(tmp_path, asked, svc_factory):
    app = _form_app(
        tmp_path, subtitle_lang="English", current_language="es",
        caption_langs={"es-orig": "auto", "es": "auto", "en": "auto"},
    )
    assert svc_factory(app)._caption_choice() == ""
    assert asked.calls == []


def test_no_question_while_a_time_range_is_set(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path)
    app.download_start_time_var = _Var("0:01:00")
    app.download_end_time_var = _Var("0:00:00")
    assert svc_factory(app)._caption_choice() == ""
    assert asked.calls == []
    app.download_start_time_var = _Var("0:00:00")  # the untouched default: whole video
    assert svc_factory(app)._caption_choice() == "transcribe"


def test_no_question_while_a_lookup_is_pending(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path, config={"download_caption_choice": "captions"})
    app.format_lookup_after = "after#1"  # the link changed; its lookup has not run yet
    assert svc_factory(app)._caption_choice() == ""
    assert asked.calls == []


def test_the_question_names_an_automatic_language_not_its_code(tmp_path, asked, svc_factory):
    app = _form_app(tmp_path, current_language="es", caption_langs={"es": "manual"})
    svc_factory(app)._caption_choice()
    assert asked.calls == [{"kind": "manual", "language": "Spanish"}]
