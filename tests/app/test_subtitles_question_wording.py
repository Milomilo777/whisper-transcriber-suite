"""The subtitles question says what each answer downloads; the inline shortcut follows the tick.

The question's buttons were "Transcribe" and "Use the subtitles", which did not say whether the
video is downloaded (deep review of tabs 1-3, 2026-10-21): they are now "Download and
transcribe" and "Subtitles only (no video)". The inline "Use the subtitles" offer under the link
asked "instead of transcribing?" even when "Transcribe after download" was off; it now shows only
while that box is ticked. Windowless: stand-ins replace the Tk variables and widgets.
"""
from __future__ import annotations

import inspect
import types

from app.app import App
from app.dialogs import caption_choice


def test_the_question_buttons_name_what_is_downloaded() -> None:
    src = inspect.getsource(caption_choice.ask_caption_choice)
    assert '_("Download and transcribe")' in src
    assert '_("Subtitles only (no video)")' in src
    assert '_("Transcribe")' not in src and '_("Use the subtitles")' not in src


class _Var:
    def __init__(self, value: object = "") -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class _Button:
    def __init__(self) -> None:
        self.packed = False

    def pack(self, **_kw: object) -> None:
        self.packed = True

    def pack_forget(self) -> None:
        self.packed = False


def _app(tick: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        update_caption_bar=lambda: None, caption_shortcut_status_var=_Var(),
        caption_shortcut_button=_Button(), _smtv_episode=None, subtitle_lang_var=_Var("German"),
        current_video_language="de", current_video_caption_langs={"de": "manual"},
        auto_transcribe_var=_Var(tick),
    )


def test_the_inline_offer_shows_only_while_transcribe_after_download_is_on(monkeypatch) -> None:
    from app.domain import languages

    monkeypatch.setattr(languages, "resolve_caption_kind", lambda *_a, **_k: "manual")
    on, off = _app(True), _app(False)
    App.update_caption_shortcut_state(on)  # type: ignore[arg-type]
    App.update_caption_shortcut_state(off)  # type: ignore[arg-type]
    assert on.caption_shortcut_button.packed and on.caption_shortcut_status_var.get()
    assert not off.caption_shortcut_button.packed and off.caption_shortcut_status_var.get() == ""


def test_ticking_the_box_updates_the_offer(monkeypatch) -> None:
    calls: list[str] = []
    fake = types.SimpleNamespace(
        app_config={}, auto_transcribe_var=_Var(True), log=lambda _m: None,
        update_caption_shortcut_state=lambda: calls.append("update"),
    )
    monkeypatch.setattr("app.app.save_config", lambda _c: None)
    App._save_auto_transcribe_pref(fake)  # type: ignore[arg-type]
    assert calls == ["update"]
