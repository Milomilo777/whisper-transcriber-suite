"""The first-run language suggestion window: answers are remembered, nothing switches silently."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import i18n, ui_language_hint
from app.dialogs import language_suggestion as sug


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    folder = tmp_path / "locales"
    folder.mkdir()
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    monkeypatch.setattr(i18n, "_WARNED", set())
    lang = i18n.LANGUAGES_BY_CODE["de"]
    doc = {"_meta": {"code": "de", "name": lang.endonym, "direction": "ltr", "status": "reviewed",
                     "plural": lang.plural},
           "messages": {"Use {language} for this app?": "{language} für diese App verwenden?"}}
    (folder / "de.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def test_text_in_speaks_another_language_without_switching() -> None:
    assert i18n.text_in("de", "Use {language} for this app?", language="Deutsch") == "Deutsch für diese App verwenden?"
    assert i18n.text_in("de", "Keep English") == "Keep English"       # no entry: English
    assert i18n.text_in("fr", "Keep English") == "Keep English"       # no catalog: English
    assert i18n.text_in("en", "Use {language}", language="X") == "Use X"
    assert i18n.current_language() == "en"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    root.app_config = {"ui_language": "auto"}  # type: ignore[attr-defined]
    root.calls = []  # type: ignore[attr-defined]
    root.open_ui_language_chooser = lambda: root.calls.append("chooser")  # type: ignore[attr-defined]
    saved: list[dict[str, Any]] = []
    root.saved = saved  # type: ignore[attr-defined]
    monkeypatch.setattr(sug, "save_config", lambda cfg: saved.append(dict(cfg)))
    monkeypatch.setattr(sug, "apply_choice", lambda _app, code: root.calls.append(("apply", code)))
    monkeypatch.setattr(sug, "place_over", lambda *_a, **_k: None)
    try:
        yield root
    finally:
        root.destroy()


def _button(dlg: Any, start: str) -> Any:
    def walk(w: Any):
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    return next(w for w in walk(dlg) if w.winfo_class() == "TButton" and str(w.cget("text")).startswith(start))


def _labels(dlg: Any) -> list[str]:
    def walk(w: Any):
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    return [str(w.cget("text")) for w in walk(dlg) if w.winfo_class() == "TLabel"]


def test_tk_asks_in_the_suggested_language_and_in_english(app: Any) -> None:
    dlg = sug.show_suggestion(app, "de")
    assert _labels(dlg) == ["Deutsch für diese App verwenden?", "Use Deutsch for this app?"]
    assert {str(_button(dlg, s).cget("text")) for s in ("Use", "Keep", "Other")} == {
        "Use Deutsch", "Keep English", "Other…"}
    assert app.app_config["ui_language"] == "auto" and not app.calls  # nothing switched by itself


def test_tk_without_a_translation_the_question_is_shown_once(app: Any) -> None:
    assert _labels(sug.show_suggestion(app, "ja")) == ["Use 日本語 for this app?"]


def test_tk_use_applies_the_language_and_remembers(app: Any) -> None:
    dlg = sug.show_suggestion(app, "de")
    _button(dlg, "Use").invoke()
    assert app.calls == [("apply", "de")]
    assert app.app_config[ui_language_hint.HINT_KEY] is True and app.saved
    assert not dlg.winfo_exists()


def test_tk_keep_english_remembers_and_changes_nothing(app: Any) -> None:
    _button(sug.show_suggestion(app, "de"), "Keep").invoke()
    assert app.calls == [] and app.app_config[ui_language_hint.HINT_KEY] is True
    assert app.app_config["ui_language"] == "auto"


def test_tk_other_opens_the_chooser_and_remembers(app: Any) -> None:
    _button(sug.show_suggestion(app, "de"), "Other").invoke()
    assert app.calls == ["chooser"] and app.app_config[ui_language_hint.HINT_KEY] is True


def test_tk_closing_the_window_counts_as_an_answer(app: Any) -> None:
    dlg = sug.show_suggestion(app, "de")
    dlg.event_generate("<Escape>")  # may need focus; the close protocol is the real path
    dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
    assert app.app_config[ui_language_hint.HINT_KEY] is True and app.calls == []


def test_tk_maybe_suggest_shows_only_for_a_clear_hint(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(sug, "show_suggestion", lambda _a, code: shown.append(code))
    monkeypatch.setattr(ui_language_hint, "suggestion_for_this_machine", lambda _c: None)
    sug.maybe_suggest(app)
    monkeypatch.setattr(ui_language_hint, "suggestion_for_this_machine", lambda _c: "de")
    sug.maybe_suggest(app)
    app._closing = True
    sug.maybe_suggest(app)  # a closing app asks nothing
    assert shown == ["de"]


@pytest.mark.parametrize("flag", ["_quick_start_open", "_hub_setup_open", "_model_question_open"])
def test_suggestion_waits_while_a_modal_setup_window_is_open(flag: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    shown: list[str] = []
    rearmed: list[int] = []
    monkeypatch.setattr(sug, "show_suggestion", lambda _app, code: shown.append(code))
    monkeypatch.setattr(ui_language_hint, "suggestion_for_this_machine", lambda _cfg: "de")
    fake = types.SimpleNamespace(app_config={}, _closing=False, _quick_start_open=False,
                                 _hub_setup_open=False, _model_question_open=False,
                                 after=lambda ms, fn: rearmed.append(ms))
    setattr(fake, flag, True)
    sug.maybe_suggest(fake)
    assert shown == [] and rearmed == [sug.RETRY_MS]
    setattr(fake, flag, False)
    sug.maybe_suggest(fake)
    assert shown == ["de"] and rearmed == [sug.RETRY_MS]


def test_model_question_raises_the_flag_while_it_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suggestion waits on this flag, so it must be up exactly while the question is shown."""
    import types
    from unittest.mock import MagicMock

    from app import app as app_module

    seen: list[bool] = []
    fake = types.SimpleNamespace(
        _model_question_open=False, model_setup_running=False, log=MagicMock(),
        _model_bytes_present=lambda: False, _model_download_question=lambda: "q",
    )

    def _ask(*_a: Any, **_k: Any) -> bool:
        seen.append(fake._model_question_open)
        return False

    fake._ask_model_download = lambda: app_module.App._ask_model_download(fake)  # type: ignore[arg-type]
    monkeypatch.setattr(app_module.messagebox, "askyesno", _ask)
    assert app_module.App._ensure_transcribe_ready(fake) is False  # type: ignore[arg-type]
    assert seen == [True] and fake._model_question_open is False
