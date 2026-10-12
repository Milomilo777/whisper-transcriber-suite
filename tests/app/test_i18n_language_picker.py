"""The interface-language picker in Advanced settings > "App behaviour" (app/dialogs/advanced.py).

* Windowless (any machine): the entries and their order (``_ui_language_choices``), the labels
  of machine-translated catalogs, the label <-> stored value map, and the fonts the picker gives
  each language's own name on Windows (every one of the 42 names gets a font with glyphs for all
  its letters).
* Real Tk (tests named ``*_tk_*``; they need a display): the dialog built with the hermetic
  harness of ``test_i18n_wave_2.py`` lists the catalogs of a temporary locales folder, saves
  "auto" or the code, keeps a setting it does not offer, says when a change needs a restart, and
  stores the same value in the pseudo-locale as in English.
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from app import i18n

# The order the picker must show when every catalog ships (right-to-left ones included): Latin
# names alphabetically with accents ignored, then Cyrillic, Greek, Hebrew/Arabic, Indic, Thai and
# CJK names, each group alphabetically (by code point where there is no case or accent).
ALL_IN_PICKER_ORDER = [
    "id", "ms", "ca", "cs", "da", "de", "en", "es", "fil", "fr", "hr", "it", "lv", "lt", "hu",
    "nl", "nb", "pl", "pt-BR", "pt-PT", "ro", "sk", "sl", "fi", "sv", "vi", "tr",
    "bg", "ru", "sr", "uk",
    "el",
    "he", "ar", "fa",
    "hi", "bn",
    "th",
    "ja", "zh-Hans", "zh-Hant", "ko",
]
AUTO_LABEL = "Automatic (system language)"


@pytest.fixture(autouse=True)
def _fresh_i18n(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(i18n, "_WARNED", set())
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    monkeypatch.setattr(i18n, "_OS_LANGUAGE", [])
    monkeypatch.delenv(i18n.ENV_LANGUAGE, raising=False)
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def locales(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "locales"
    folder.mkdir()
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    return folder


def write_catalog(folder: Path, code: str, status: str) -> None:
    lang = i18n.LANGUAGES_BY_CODE[code]
    doc = {"_meta": {"code": code, "name": lang.endonym, "direction": lang.direction,
                     "status": status, "plural": lang.plural},
           "messages": {}}
    (folder / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _adv() -> Any:
    from app.dialogs import advanced
    return advanced


# --- windowless: entries, order, labels, values ---------------------------------------------------

def test_every_catalog_is_listed_in_script_groups_alphabetically(
        locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    for lang in i18n.SUPPORTED_LANGUAGES[1:]:
        write_catalog(locales, lang.code, "reviewed")
    choices = _adv()._ui_language_choices()
    assert choices[0] == (AUTO_LABEL, "auto")
    assert [value for _label, value in choices[1:]] == ALL_IN_PICKER_ORDER
    by_code = {lang.code: lang.endonym for lang in i18n.SUPPORTED_LANGUAGES}
    # Each language only by its own name, exactly as the table spells it.
    assert [label for label, _value in choices[1:]] == [by_code[c] for c in ALL_IN_PICKER_ORDER]
    assert len(choices) == 43


def test_machine_catalogs_are_marked_and_rtl_ones_wait_for_the_mirrored_layout(locales: Path) -> None:
    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    write_catalog(locales, "ja", "machine")
    write_catalog(locales, "ar", "reviewed")
    write_catalog(locales, "he", "machine")
    assert i18n.RTL_LAYOUT_READY is False
    assert _adv()._ui_language_choices() == [
        (AUTO_LABEL, "auto"),
        ("Deutsch", "de"),
        ("English", "en"),
        ("Français (machine translation)", "fr"),
        ("日本語 (machine translation)", "ja"),
    ]


def test_only_english_ships(locales: Path) -> None:
    assert _adv()._ui_language_choices() == [(AUTO_LABEL, "auto"), ("English", "en")]


def test_pseudo_locale_marks_the_texts_but_never_a_language_name(locales: Path) -> None:
    from tests.app.i18n_walk import is_pseudo_marked, unmarked_rest

    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    i18n.set_language(i18n.PSEUDO_LOCALE)
    choices = _adv()._ui_language_choices()
    assert [value for _label, value in choices] == ["auto", "de", "en", "fr"]
    assert is_pseudo_marked(choices[0][0])
    assert choices[1][0] == "Deutsch" and choices[2][0] == "English"
    machine = choices[3][0]
    assert "Français" in machine and unmarked_rest(machine).strip() == ""


@pytest.mark.parametrize("setting,index", [
    ("auto", 0), ("", 0), ("  ", 0), (None, 0), ("AUTO", 0), ("de", 1), ("DE", 1), ("pt_br", 3),
    ("pt-BR", 3), ("fr", None), ("qps-ploc", None), ("de_DE", 4), ("de-de", 4),
])
def test_setting_to_entry(setting: object, index: int | None) -> None:
    choices = [(AUTO_LABEL, "auto"), ("Deutsch", "de"), ("English", "en"),
               ("Português (Brasil)", "pt-BR"), ("de_DE", "de_DE")]
    assert _adv()._ui_language_index(choices, setting) == index


@pytest.mark.parametrize("setting", ["de_DE", "pt_br", " de-AT ", "qps-ploc", "xx"])
def test_an_appended_setting_is_the_entry_shown(locales: Path, setting: str) -> None:
    adv = _adv()
    choices = adv._ui_language_choices(setting)
    assert adv._ui_language_index(choices, setting) == len(choices) - 1


def test_a_setting_the_list_does_not_offer_is_shown_as_it_is(locales: Path) -> None:
    adv = _adv()
    # A known language without a catalog (or an rtl one, not offered yet): its own name.
    assert adv._ui_language_choices("de")[-1] == ("Deutsch", "de")
    assert adv._ui_language_choices("he")[-1] == ("עברית", "he")
    # The pseudo-locale or anything else: the stored text itself.
    assert adv._ui_language_choices("qps-ploc")[-1] == ("qps-ploc", "qps-ploc")
    assert adv._ui_language_choices("auto") == [(AUTO_LABEL, "auto"), ("English", "en")]


def test_macos_keeps_a_right_to_left_name_in_a_left_to_right_line(
        locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.theme import bidi_display

    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    write_catalog(locales, "he", "machine")
    write_catalog(locales, "de", "reviewed")
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: True)
    labels = dict((v, lbl) for lbl, v in _adv()._ui_language_choices())
    assert labels["he"] == bidi_display.LRM + "עברית (machine translation)"
    assert labels["de"] == "Deutsch"  # left to right already: unchanged
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: False)
    labels = dict((v, lbl) for lbl, v in _adv()._ui_language_choices())
    assert labels["he"] == "עברית (machine translation)"


# --- windowless: fonts with glyphs for every language name (R1b) ---------------------------------

# What each Windows font has glyphs for (Microsoft's font documentation, "Windows 10 font list"),
# by the first word of the Unicode character name. Only the scripts the 42 names use are listed.
GLYPHS = {
    "Segoe UI": {"LATIN", "GREEK", "CYRILLIC", "ARABIC", "HEBREW"},
    "Nirmala UI": {"LATIN", "DEVANAGARI", "BENGALI", "SINHALA"},
    "Leelawadee UI": {"LATIN", "THAI"},
    "Malgun Gothic": {"LATIN", "HANGUL"},
    "Microsoft YaHei UI": {"LATIN", "CJK"},
    "Microsoft JhengHei UI": {"LATIN", "CJK"},
    "Yu Gothic UI": {"LATIN", "CJK", "HIRAGANA", "KATAKANA"},
    "Myanmar Text": {"LATIN", "MYANMAR"},
}
# Scripts Tk on Windows borrows from another font under Segoe UI at the right line height
# (measured for app.theme.script_fonts with every caption language on Windows 10).
SEGOE_FALLBACK_OK = {"DEVANAGARI", "BENGALI", "THAI", "HANGUL", "CJK", "HIRAGANA", "KATAKANA"}


def _scripts(text: str) -> set[str]:
    """The scripts of the letters and marks of ``text`` (spaces and brackets are in every font)."""
    return {unicodedata.name(ch).split(" ")[0] for ch in text
            if unicodedata.category(ch)[0] in ("L", "M")}


@pytest.mark.parametrize("lang", i18n.SUPPORTED_LANGUAGES, ids=lambda lang: lang.code)
def test_windows_gives_every_name_a_font_with_all_its_glyphs(
        lang: i18n.SupportedLanguage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    family = _adv()._ui_language_family(lang.code, lang.endonym, installed=set(GLYPHS))
    assert family is not None
    missing = _scripts(lang.endonym) - GLYPHS[family]
    assert not missing, (lang.endonym, family, missing)
    # The drop-down list shows every name in Segoe UI: each script is in it or drawn by Tk's
    # fallback at the right height. A new language in another script fails here on purpose.
    assert _scripts(lang.endonym) <= GLYPHS["Segoe UI"] | SEGOE_FALLBACK_OK, lang.endonym


def test_han_names_get_the_font_of_their_own_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    family = _adv()._ui_language_family
    installed = set(GLYPHS)
    assert family("ja", "日本語", installed) == "Yu Gothic UI"
    assert family("zh-Hans", "简体中文", installed) == "Microsoft YaHei UI"
    assert family("zh-Hant", "繁體中文", installed) == "Microsoft JhengHei UI"
    assert family("ko", "한국어", installed) == "Malgun Gothic"
    assert family("de", "Deutsch", installed) == "Segoe UI"
    assert family("auto", AUTO_LABEL, installed) == "Segoe UI"


def test_a_missing_font_falls_back_to_segoe_ui_then_to_the_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    family = _adv()._ui_language_family
    assert family("th", "ไทย", {"Segoe UI"}) == "Segoe UI"
    assert family("th", "ไทย", set()) is None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_macos_and_linux_keep_the_platform_fonts(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    for lang in i18n.SUPPORTED_LANGUAGES:
        assert _adv()._ui_language_family(lang.code, lang.endonym, installed=set(GLYPHS)) is None


# --- real Tk: the dialog ------------------------------------------------------------------------

@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from tests.app.test_i18n_wave_2 import _Harness

    h = _Harness(monkeypatch, tmp_path)
    h.notices = []  # type: ignore[attr-defined]
    monkeypatch.setattr(h.adv, "notify", lambda _w, text, kind="info": h.notices.append(text))  # type: ignore[attr-defined]
    try:
        yield h
    finally:
        h.close()


def _values(dlg: Any) -> list[str]:
    return list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))


def _pick(dlg: Any, label: str) -> None:
    combo = dlg._ui_language_combo
    combo.current(_values(dlg).index(label))
    combo.event_generate("<<ComboboxSelected>>")
    dlg.update_idletasks()


def _save(h: Any, dlg: Any) -> dict[str, Any]:
    h.saved.clear()
    dlg._save_and_close()
    assert len(h.saved) == 1
    return h.saved[0]


def test_tk_picker_sits_in_app_behaviour_and_lists_the_catalogs(harness: Any, locales: Path) -> None:
    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    write_catalog(locales, "ar", "reviewed")  # right to left: not offered yet
    dlg = harness.make()
    assert _values(dlg) == [AUTO_LABEL, "Deutsch", "English", "Français (machine translation)"]
    assert dlg._ui_language_display.get() == AUTO_LABEL
    assert str(dlg._ui_language_combo.cget("state")) == "readonly"
    # Inside "App behaviour", right before the "New versions:" choice.
    row = dlg._ui_language_combo.master
    misc = row.master
    assert dict(dlg._nav_targets)["App behaviour"] is misc
    slaves = misc.pack_slaves()
    texts = [str(w.cget("text")) if "text" in w.keys() else "" for w in slaves]
    at = slaves.index(row)
    assert texts[at + 1] == "New versions:"
    label = [w for w in row.winfo_children() if w.winfo_class() == "TLabel"][0]
    assert label.cget("text") == "Interface language:"


def test_tk_saving_writes_auto_or_the_code(harness: Any, locales: Path) -> None:
    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    dlg = harness.make(ui_language="auto")
    _pick(dlg, "Français (machine translation)")
    assert _save(harness, dlg)["ui_language"] == "fr"
    dlg = harness.make(ui_language="fr")
    assert dlg._ui_language_display.get() == "Français (machine translation)"
    _pick(dlg, "Deutsch")
    assert _save(harness, dlg)["ui_language"] == "de"
    dlg = harness.make(ui_language="de")
    _pick(dlg, AUTO_LABEL)
    assert _save(harness, dlg)["ui_language"] == "auto"


def test_tk_an_unchanged_picker_keeps_what_config_holds(harness: Any, locales: Path) -> None:
    write_catalog(locales, "de", "reviewed")
    for setting, shown in (("qps-ploc", "qps-ploc"), ("pt-BR", "Português (Brasil)"),
                           ("de_DE", "de_DE"), ("DE", "Deutsch")):
        dlg = harness.make(ui_language=setting)
        assert dlg._ui_language_display.get() == shown
        assert _values(dlg)[-1] == shown or shown == "Deutsch"
        assert _save(harness, dlg)["ui_language"] == setting
    assert harness.notices == []


def test_tk_restart_notice_only_when_the_language_would_change(
        harness: Any, locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: "fr-FR")
    restart = "The interface language changes the next time you start the app."
    dlg = harness.make(ui_language="auto")  # running English: auto with a French OS is English
    _pick(dlg, "English")
    _save(harness, dlg)
    assert harness.notices == []  # "en" is what runs now
    dlg = harness.make(ui_language="en")
    _pick(dlg, AUTO_LABEL)
    _save(harness, dlg)
    assert harness.notices == []  # French is machine translated: auto stays English
    dlg = harness.make(ui_language="auto")
    _pick(dlg, "Deutsch")
    _save(harness, dlg)
    assert harness.notices == [restart]
    harness.notices.clear()
    monkeypatch.setenv(i18n.ENV_LANGUAGE, "qps-ploc")
    dlg = harness.make(ui_language="de")
    _pick(dlg, "English")
    _save(harness, dlg)
    assert harness.notices == [
        "The WTS_UI_LANGUAGE environment variable sets the interface language of this run. "
        "Your choice applies when the app starts without it."]


def test_tk_a_failed_save_shows_no_notice(harness: Any, locales: Path) -> None:
    write_catalog(locales, "de", "reviewed")
    dlg = harness.make(ui_language="auto")
    _pick(dlg, "Deutsch")
    harness.save_error = OSError("disk full")
    dlg._save_and_close()
    harness.save_error = None
    assert harness.notices == [] and harness.messageboxes
    assert dlg.app.app_config["ui_language"] == "auto"  # the unsaved pick is rolled back


def test_tk_the_real_notice_reaches_the_main_window(harness: Any, locales: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from app.widgets import notice

    monkeypatch.setattr(harness.adv, "notify", notice.notify)
    write_catalog(locales, "de", "reviewed")
    dlg = harness.make(ui_language="auto")
    _pick(dlg, "Deutsch")
    _save(harness, dlg)
    host = notice.host_for(harness.root)
    assert host.current == ("The interface language changes the next time you start the app.",
                            "info")


@pytest.mark.parametrize("os_language,expected", [
    ("de-DE", {"auto": "de", "de": "de", "en": "en", "fr": "fr"}),
    ("fr-FR", {"auto": "en", "de": "de", "en": "en", "fr": "fr"}),  # machine: never automatic
    (None, {"auto": "en", "de": "de", "en": "en", "fr": "fr"}),
])
def test_tk_every_picker_value_resolves_like_start_up(
        harness: Any, locales: Path, monkeypatch: pytest.MonkeyPatch, os_language: str | None,
        expected: dict[str, str]) -> None:
    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: os_language)
    dlg = harness.make()
    values = [dlg._ui_language_value(label) for label in _values(dlg)]
    assert values == ["auto", "de", "en", "fr"]
    resolved = {value: i18n.setting_language(value) for value in values if value}
    assert resolved == expected
    for value, code in resolved.items():  # what the next start really does with it
        assert i18n.init_language(lambda v=value: {"ui_language": v}, environ={}) == code
    i18n.set_language("en")


def test_tk_pseudo_locale_saves_the_same_value_as_english(harness: Any, locales: Path) -> None:
    from tests.app.i18n_walk import is_pseudo_marked, untranslated

    write_catalog(locales, "de", "reviewed")
    write_catalog(locales, "fr", "machine")
    saved = {}
    for language in ("en", i18n.PSEUDO_LOCALE):
        i18n.set_language(language)
        try:
            dlg = harness.make(ui_language="auto")
            if language == i18n.PSEUDO_LOCALE:
                row = dlg._ui_language_combo.master
                names = {"Deutsch", "English"}
                left = [t for _p, t in untranslated(row) if t not in names]
                assert left == [], left
                assert is_pseudo_marked(_values(dlg)[0])
            dlg._ui_language_combo.current(3)
            dlg._ui_language_combo.event_generate("<<ComboboxSelected>>")
            saved[language] = _save(harness, dlg)["ui_language"]
        finally:
            i18n.set_language("en")
    assert saved == {"en": "fr", i18n.PSEUDO_LOCALE: "fr"}


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows fonts")
def test_tk_windows_fonts_follow_the_shown_name(harness: Any, locales: Path) -> None:
    from tkinter import font as tkfont

    from app.theme import script_fonts

    write_catalog(locales, "ja", "machine")
    write_catalog(locales, "ko", "machine")
    dlg = harness.make(ui_language="ja")
    combo = dlg._ui_language_combo
    installed = script_fonts.installed_families(combo)

    def family() -> str:
        return str(tkfont.Font(root=combo, font=combo.cget("font")).actual("family"))

    if "Yu Gothic UI" in installed:
        assert family() == "Yu Gothic UI"
    _pick(dlg, "한국어 (machine translation)")
    if "Malgun Gothic" in installed:
        assert family() == "Malgun Gothic"
    _pick(dlg, AUTO_LABEL)
    if "Segoe UI" in installed:
        assert family() == "Segoe UI"
        popdown = str(combo.tk.call("ttk::combobox::PopdownWindow", str(combo)))
        list_font = combo.tk.call(f"{popdown}.f.l", "cget", "-font")
        assert tkfont.Font(root=combo, font=list_font).actual("family") == "Segoe UI"
