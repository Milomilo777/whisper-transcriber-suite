"""Transcript viewer defect from an external review pass (branch fix/gemini-b1).

The bilingual subtitle's file name keeps only ASCII letters of the target
language, so two different non-Latin languages (typed in the free-text box)
both became ``<name>.bilingual.translated.srt`` and the second run silently
replaced the first one's file.

No Tk window is created: the method under test runs on a small stand-in.
"""
from __future__ import annotations

import os
import types

import pytest

pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402

# Persian and Arabic names of the languages (escaped: tracked files stay ASCII)
_PERSIAN = "\u0641\u0627\u0631\u0633\u06cc"
_ARABIC = "\u0627\u0644\u0639\u0631\u0628\u064a\u0629"


class _Widget:
    def pack_forget(self) -> None:
        pass


class _Var:
    def set(self, _value) -> None:
        pass


def _viewer_standin(json_path: str):
    return types.SimpleNamespace(
        _closing=False, _bilingual_cancel=None, json_path=json_path, media_path="",
        _ai_cancel_btn=_Widget(), _ai_progress_var=_Var(),
        _set_ai_buttons_busy=lambda _busy: None,
    )


def _run(standin, lang: str, text: str) -> None:
    segments = [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    tv.TranscriptViewer._finish_bilingual_translate(  # type: ignore[arg-type]
        standin, segments, [text], lang, None)


@pytest.fixture
def dialogs(monkeypatch):
    shown: list[str] = []
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(tv.messagebox, name,
                            lambda title, msg, **_k: shown.append(msg))
    return shown


def test_two_non_latin_languages_write_two_different_files(tmp_path, dialogs):
    json_path = str(tmp_path / "talk.json")
    viewer = _viewer_standin(json_path)
    _run(viewer, _PERSIAN, "persian-text")
    _run(viewer, _ARABIC, "arabic-text")
    files = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".srt"))
    assert len(files) == 2, files
    texts = {(tmp_path / n).read_text(encoding="utf-8") for n in files}
    assert any("persian-text" in t for t in texts)
    assert any("arabic-text" in t for t in texts)


def test_latin_language_names_keep_their_old_file_names(tmp_path, dialogs):
    viewer = _viewer_standin(str(tmp_path / "talk.json"))
    _run(viewer, "Brazilian Portuguese", "x")
    assert os.path.isfile(tmp_path / "talk.bilingual.brazilian-portuguese.srt")


@pytest.mark.parametrize("lang", ["", "  ", "///", "..", "?*<>|"])
def test_a_name_without_any_letter_falls_back_to_translated(lang):
    assert tv._bilingual_lang_slug(lang) == "translated"


@pytest.mark.parametrize("lang", ["a/b", "a\\b", "CON:", "x*y?z", "..\\..\\evil"])
def test_the_slug_never_holds_a_path_or_reserved_character(lang):
    slug = tv._bilingual_lang_slug(lang)
    assert not set(slug) & set('\\/:*?"<>|')
    assert ".." not in slug


@pytest.mark.parametrize("lang, slug", [
    ("English", "english"),
    ("pt_BR", "pt-br"),
    ("Brazilian Portuguese", "brazilian-portuguese"),
    (_PERSIAN, _PERSIAN),
])
def test_slug_keeps_the_old_names_for_latin_input(lang, slug):
    assert tv._bilingual_lang_slug(lang) == slug
