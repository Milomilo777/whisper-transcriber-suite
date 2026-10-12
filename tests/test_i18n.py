"""app/i18n.py: lookups, plural rules, pseudo-locale, catalog loading and the start-up choice."""
from __future__ import annotations

import json
import logging
import string
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from app import i18n


@pytest.fixture(autouse=True)
def _english_and_fresh_warnings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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


def write_catalog(folder: Path, code: str, messages: dict[str, Any], *, status: str = "reviewed",
                  plural: str | None = None) -> Path:
    lang = i18n.LANGUAGES_BY_CODE[code]
    doc = {"_meta": {"code": code, "name": lang.endonym, "direction": lang.direction,
                     "status": status, "plural": plural or lang.plural},
           "messages": messages}
    path = folder / f"{code}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return path


# --- R2 the language table -----------------------------------------------------------------

SPEC_TABLE = """
en|English|ltr|one_other de|Deutsch|ltr|one_other fr|Français|ltr|zero_one_other
es|Español|ltr|one_other it|Italiano|ltr|one_other pt-BR|Português (Brasil)|ltr|zero_one_other
pt-PT|Português (Portugal)|ltr|one_other nl|Nederlands|ltr|one_other pl|Polski|ltr|pl
ru|Русский|ltr|east_slavic uk|Українська|ltr|east_slavic tr|Türkçe|ltr|one_other
cs|Čeština|ltr|cs_sk sk|Slovenčina|ltr|cs_sk hu|Magyar|ltr|one_other ro|Română|ltr|ro
bg|Български|ltr|one_other el|Ελληνικά|ltr|one_other sv|Svenska|ltr|one_other
da|Dansk|ltr|one_other nb|Norsk bokmål|ltr|one_other fi|Suomi|ltr|one_other
hr|Hrvatski|ltr|east_slavic sr|Српски|ltr|east_slavic sl|Slovenščina|ltr|sl lt|Lietuvių|ltr|lt
zh-Hans|简体中文|ltr|none zh-Hant|繁體中文|ltr|none ja|日本語|ltr|none ko|한국어|ltr|none
vi|Tiếng Việt|ltr|none th|ไทย|ltr|none id|Bahasa Indonesia|ltr|none ms|Bahasa Melayu|ltr|none
hi|हिन्दी|ltr|zero_one_other ar|العربية|rtl|ar fa|فارسی|rtl|zero_one_other he|עברית|rtl|he
lv|Latviešu|ltr|lv ca|Català|ltr|one_other bn|বাংলা|ltr|zero_one_other fil|Filipino|ltr|fil
"""


def _spec_rows() -> list[tuple[str, ...]]:
    # Rows are separated by a space that is followed by a code and "|"; endonyms contain spaces.
    import re
    flat = " ".join(SPEC_TABLE.split("\n")).strip()
    rows = re.split(r" (?=[a-z]{2,3}(?:-[A-Za-z]+)?\|)", flat)
    return [tuple(r.split("|")) for r in rows]


def test_the_table_is_exactly_the_42_languages_of_the_spec() -> None:
    rows = _spec_rows()
    assert len(rows) == 42
    assert [tuple(lang) for lang in i18n.SUPPORTED_LANGUAGES] == rows


def test_every_table_rule_exists_and_rtl_is_ar_fa_he() -> None:
    assert {lang.plural for lang in i18n.SUPPORTED_LANGUAGES} <= set(i18n.PLURAL_RULES)
    assert {lang.code for lang in i18n.SUPPORTED_LANGUAGES if lang.direction == "rtl"} == {"ar", "fa", "he"}


# --- R4 plural rules, CLDR integer samples -------------------------------------------------

def _expand(samples: str) -> list[int]:
    out: list[int] = []
    for part in samples.replace(" ", "").split(","):
        if "~" in part:
            lo, hi = part.split("~")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


# From unicode-org CLDR common/supplemental/plurals.xml (@integer samples), one list per form
# in category order.
CLDR_SAMPLES: dict[str, list[str]] = {
    "one_other": ["1", "0, 2~16, 100, 1000, 10000, 100000, 1000000"],
    "zero_one_other": ["0, 1", "2~17, 100, 1000, 10000, 100000, 1000000"],
    "east_slavic": ["1, 21, 31, 41, 51, 61, 71, 81, 101, 1001",
                    "2~4, 22~24, 32~34, 42~44, 52~54, 62, 102, 1002",
                    "0, 5~19, 100, 1000, 10000, 100000, 1000000"],
    "pl": ["1", "2~4, 22~24, 32~34, 42~44, 52~54, 62, 102, 1002",
           "0, 5~19, 100, 1000, 10000, 100000, 1000000"],
    "cs_sk": ["1", "2~4", "0, 5~19, 100, 1000, 10000, 100000, 1000000"],
    "ro": ["1", "0, 2~16, 102, 1002", "20~35, 100, 1000, 10000, 100000, 1000000"],
    "lt": ["1, 21, 31, 41, 51, 61, 71, 81, 101, 1001", "2~9, 22~29, 102, 1002",
           "0, 10~20, 30, 40, 50, 60, 100, 1000, 10000, 100000, 1000000"],
    "sl": ["1, 101, 201, 301, 401, 501, 601, 701, 1001",
           "2, 102, 202, 302, 402, 502, 602, 702, 1002",
           "3, 4, 103, 104, 203, 204, 303, 304, 403, 404, 503, 504, 603, 604, 703, 704, 1003",
           "0, 5~19, 100, 1000, 10000, 100000, 1000000"],
    "ar": ["0", "1", "2", "3~10, 103~110, 1003", "11~26, 111, 1011",
           "100~102, 200~202, 300~302, 400~402, 500~502, 600, 1000, 10000, 100000, 1000000"],
    "he": ["1", "2", "0, 3~17, 100, 1000, 10000, 100000, 1000000"],
    "lv": ["0, 10~20, 30, 40, 50, 60, 100, 1000, 10000, 100000, 1000000",
           "1, 21, 31, 41, 51, 61, 71, 81, 101, 1001", "2~9, 22~29, 102, 1002"],
    "fil": ["0~3, 5, 7, 8, 10~13, 15, 17, 18, 20, 21, 100, 1000, 10000, 100000, 1000000",
            "4, 6, 9, 14, 16, 19, 24, 26, 104, 1004"],
    "none": ["0~15, 100, 1000, 10000, 100000, 1000000"],
}


def test_every_rule_has_cldr_samples() -> None:
    assert set(CLDR_SAMPLES) == set(i18n.PLURAL_RULES)


@pytest.mark.parametrize("rule", sorted(CLDR_SAMPLES))
def test_plural_rule_matches_the_cldr_integer_samples(rule: str) -> None:
    nforms, _fn = i18n.PLURAL_RULES[rule]
    assert nforms == len(CLDR_SAMPLES[rule])
    wrong = [(n, form, i18n.plural_index(rule, n))
             for form, samples in enumerate(CLDR_SAMPLES[rule]) for n in _expand(samples)
             if i18n.plural_index(rule, n) != form]
    assert wrong == []


@pytest.mark.parametrize("rule", sorted(i18n.PLURAL_RULES))
def test_plural_index_is_in_range_for_every_count_up_to_a_thousand(rule: str) -> None:
    nforms, _fn = i18n.PLURAL_RULES[rule]
    assert all(0 <= i18n.plural_index(rule, n) < nforms for n in range(0, 1001))
    # Every form is reachable (a rule that never picks a form is a wrong rule).
    assert {i18n.plural_index(rule, n) for n in range(0, 1001)} == set(range(nforms))


# --- R1 lookups ----------------------------------------------------------------------------

def test_english_returns_msgid_unformatted_without_kwargs() -> None:
    assert i18n._("Use {title} in names") == "Use {title} in names"
    assert i18n._("Saved {name}", name="a.txt") == "Saved a.txt"


def test_a_wrong_call_raises_in_english_and_in_a_translation(locales: Path) -> None:
    with pytest.raises(KeyError):
        i18n._("Saved {name}", other="x")
    write_catalog(locales, "de", {"Saved {name}": "Gespeichert: {name}"})
    assert i18n.set_language("de") == "de"
    with pytest.raises(KeyError):
        i18n._("Saved {name}", other="x")


def test_translation_is_used_and_formatted(locales: Path) -> None:
    write_catalog(locales, "de", {"Save": "Speichern", "Saved {name}": "{name} gespeichert",
                                  "Open" + i18n.CONTEXT_SEPARATOR: "x",
                                  "menu" + i18n.CONTEXT_SEPARATOR + "Open": "Öffnen",
                                  "Empty": ""})
    assert i18n.set_language("de") == "de"
    assert i18n.current_language() == "de"
    assert i18n._("Save") == "Speichern"
    assert i18n._("Saved {name}", name="a") == "a gespeichert"
    assert i18n.pgettext("menu", "Open") == "Öffnen"
    assert i18n.pgettext("state", "Open") == "Open"
    assert i18n._("Empty") == "Empty"  # an empty translation means "not translated yet"
    assert i18n._("Missing") == "Missing"
    assert i18n.lazy("Save")() == "Speichern"
    assert i18n.translate(i18n.N_("Save")) == "Speichern"


def test_lazy_reads_the_language_when_called(locales: Path) -> None:
    write_catalog(locales, "de", {"Save": "Speichern"})
    tip = i18n.lazy("Save")
    assert tip() == "Save"
    i18n.set_language("de")
    assert tip() == "Speichern"


def test_placeholder_mismatch_gives_english_and_one_warning(locales: Path,
                                                            caplog: pytest.LogCaptureFixture) -> None:
    write_catalog(locales, "de", {"Saved {name}": "{nom} gespeichert", "Bad {x}": "{x",
                                  "Pos {x}": "{0} {x}"})
    i18n.set_language("de")
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        for _round in range(3):
            assert i18n._("Saved {name}", name="a") == "Saved a"
            assert i18n._("Bad {x}", x=1) == "Bad 1"
            assert i18n._("Pos {x}", x=1) == "Pos 1"
    warnings = [r for r in caplog.records if "placeholders" in r.getMessage()]
    assert len(warnings) == 3  # one per msgid, not one per call


def test_wrong_value_type_in_catalog_gives_english(locales: Path) -> None:
    write_catalog(locales, "de", {"Save": ["a", "b"], "{n} file": "Datei"})
    i18n.set_language("de")
    assert i18n._("Save") == "Save"
    assert i18n.ngettext("{n} file", "{n} files", 2) == "2 files"


@pytest.mark.parametrize("content", [
    b"{not json", b"[]", b'{"messages": {}}', b'{"_meta": {"code": "fr"}, "messages": {}}',
    b'{"_meta": {"code": "de", "status": "draft"}, "messages": {}}',
    b'{"_meta": {"code": "de", "status": "reviewed"}, "messages": []}', b"\xff\xfe",
])
def test_broken_catalog_gives_english_and_one_warning(locales: Path, content: bytes,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    (locales / "de.json").write_bytes(content)
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        assert i18n.set_language("de") == "en"
        assert i18n.set_language("de") == "en"
        assert i18n._("Save") == "Save"
    assert len([r for r in caplog.records if "not usable" in r.getMessage()]) == 1


def test_deeply_nested_catalog_gives_english(locales: Path) -> None:
    (locales / "de.json").write_bytes(b"[" * 100000 + b"]" * 100000)
    assert i18n.set_language("de") == "en"
    assert i18n.catalog_status("de") is None


def test_missing_catalog_and_unknown_code_give_english(locales: Path,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        assert i18n.set_language("de") == "en"
        assert i18n.set_language("de") == "en"
        assert i18n.set_language("xx-YY") == "en"
    assert len(caplog.records) == 2


def test_ngettext_english_and_translated_forms(locales: Path) -> None:
    assert i18n.ngettext("{n} file", "{n} files", 1) == "1 file"
    assert i18n.ngettext("{n} file", "{n} files", 0) == "0 files"
    assert i18n.ngettext("{n} file in {d}", "{n} files in {d}", 5, d="x") == "5 files in x"
    write_catalog(locales, "ru", {"{n} file": ["{n} файл", "{n} файла", "{n} файлов"]})
    i18n.set_language("ru")
    assert [i18n.ngettext("{n} file", "{n} files", n) for n in (1, 3, 5, 21, 11)] == [
        "1 файл", "3 файла", "5 файлов", "21 файл", "11 файлов"]


def test_ngettext_wrong_form_count_gives_english_with_one_warning(
        locales: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_catalog(locales, "ru", {"{n} file": ["{n} файл", "{n} файлов"]})
    i18n.set_language("ru")
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        assert i18n.ngettext("{n} file", "{n} files", 5) == "5 files"
        assert i18n.ngettext("{n} file", "{n} files", 1) == "1 file"
    assert len(caplog.records) == 1


def test_catalog_plural_rule_mismatch_uses_the_table_rule(locales: Path) -> None:
    write_catalog(locales, "fr", {"{n} file": ["{n} fichier", "{n} fichiers"]}, plural="one_other")
    i18n.set_language("fr")
    assert i18n.ngettext("{n} file", "{n} files", 0) == "0 fichier"  # fr: 0 is singular


def test_direction_follows_the_table(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", {"Save": "ذخیره"})
    assert i18n.current_direction() == "ltr"
    monkeypatch.setattr(sys, "platform", "linux")  # no Windows direction marks (tests/test_i18n_rtl.py)
    i18n.set_language("fa")
    assert i18n.current_direction() == "rtl"
    assert i18n._("Save") == "ذخیره"


def test_lookups_are_safe_while_another_thread_switches(locales: Path) -> None:
    write_catalog(locales, "de", {"Save": "Speichern", "{n} file": ["{n} Datei", "{n} Dateien"]})
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                assert i18n._("Save") in ("Save", "Speichern")
                assert i18n.ngettext("{n} file", "{n} files", 2) in ("2 files", "2 Dateien")
        except BaseException as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=reader) for _i in range(4)]
    for t in threads:
        t.start()
    for _i in range(200):
        i18n.set_language("de" if _i % 2 else "en")
    stop.set()
    for t in threads:
        t.join(5)
    assert errors == []


# --- R6 pseudo-locale ----------------------------------------------------------------------

def test_pseudo_locale_shape() -> None:
    out = i18n.pseudo_translate("Save all files")
    assert out.startswith("[") and out.endswith("]")
    body, pad = out[1:-1].rsplit(" ", 1)
    assert set(pad) == {"~"} and len(pad) == round(len("Save all files") * 0.3)
    assert body != "Save all files" and len(body) == len("Save all files")
    assert all(not c.isascii() for c in body if c.isalpha())


def test_pseudo_locale_keeps_placeholders_percent_and_newlines() -> None:
    out = i18n.pseudo_translate("Saved {name} ({size:.1f} MB)\n100% %(count)d %s {{x}}")
    for kept in ("{name}", "{size:.1f}", "\n", "%(count)d", "%s", "{{", "}}", "100%"):
        assert kept in out
    assert out.format(name="n", size=1.0).count("{") == 1  # escaped braces stay escaped
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    assert "a.txt" in i18n._("Saved {name}", name="a.txt")
    assert i18n._("Save").startswith("[")
    assert i18n.pgettext("menu", "Open").startswith("[")
    assert "3" in i18n.ngettext("{n} file", "{n} files", 3)


def test_pseudo_locale_is_never_listed(locales: Path) -> None:
    assert i18n.PSEUDO_LOCALE not in {lang.code for lang in i18n.available_languages()}


# --- available_languages -------------------------------------------------------------------

def test_available_lists_english_reviewed_and_machine_catalogs(locales: Path) -> None:
    write_catalog(locales, "de", {}, status="reviewed")
    write_catalog(locales, "fr", {}, status="machine")
    (locales / "it.json").write_text("{broken", encoding="utf-8")
    (locales / "xx.json").write_text("{}", encoding="utf-8")  # not a supported code
    listed = i18n.available_languages()
    assert [lang.code for lang in listed] == ["en", "de", "fr"]
    assert listed[0] == i18n.LanguageInfo("en", "English", "ltr", "source")
    assert listed[1].status == "reviewed"
    assert listed[2] == i18n.LanguageInfo("fr", "Français", "ltr", "machine")


def test_available_offers_rtl_catalogs_only_once_the_layout_is_mirrored(
        locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "de", {}, status="machine")
    write_catalog(locales, "ar", {}, status="reviewed")
    write_catalog(locales, "he", {}, status="machine")
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", False)
    assert [lang.code for lang in i18n.available_languages()] == ["en", "de"]
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    listed = i18n.available_languages()
    assert [lang.code for lang in listed] == ["en", "de", "ar", "he"]
    assert {lang.direction for lang in listed if lang.code in ("ar", "he")} == {"rtl"}
    # An explicit setting still loads an rtl catalog while the picker hides it (translators).
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", False)
    assert i18n.resolve_language("he", os_language=None, available=i18n.catalog_statuses()) == "he"


def test_rtl_is_offered_on_windows_only_in_this_release(monkeypatch: pytest.MonkeyPatch) -> None:
    # Adding a platform offers Arabic, Persian and Hebrew there; do it only after checking how a
    # right-to-left catalog looks on that platform.
    assert i18n.RTL_LAYOUT_READY is None
    assert i18n.RTL_PLATFORMS == frozenset({"win32"})
    monkeypatch.setattr(sys, "platform", "darwin")
    assert i18n.rtl_layout_ready() is False


# --- R5 choosing the language --------------------------------------------------------------

AVAILABLE = {"en": "source", "de": "reviewed", "fr": "machine", "pt-BR": "reviewed",
             "zh-Hant": "reviewed", "zh-Hans": "reviewed", "nb": "reviewed"}


@pytest.mark.parametrize("os_language,expected", [
    ("de-DE", "de"), ("de_AT.UTF-8", "de"), ("fr-FR", "en"),  # machine: never automatic
    ("pt-BR", "pt-BR"), ("pt_PT", "en"), ("zh-TW", "zh-Hant"), ("zh-HK", "zh-Hant"),
    ("zh_CN", "zh-Hans"), ("zh-SG", "zh-Hans"), ("zh-Hant-TW", "zh-Hant"), ("en-GB", "en"),
    ("no_NO", "nb"), ("ja-JP", "en"), (None, "en"), ("", "en"), ("C", "en"),
])
def test_auto_takes_a_reviewed_os_language_only(os_language: str | None, expected: str) -> None:
    assert i18n.resolve_language("auto", os_language=os_language, available=AVAILABLE) == expected


def test_region_falls_back_to_the_base_language() -> None:
    available = {"en": "source", "pt": "reviewed"}  # a base code, as the spec's 'pt' fallback
    assert i18n._candidates("pt-BR") == ["pt-BR", "pt"]
    assert i18n.resolve_language("auto", os_language="pt-BR", available=available) == "en"


@pytest.mark.parametrize("value,expected", [
    ("de", "de"), ("fr", "fr"), ("FR", "fr"), ("pt_br", "pt-BR"), ("qps-ploc", "qps-ploc"),
    ("en", "en"), ("ja", "en"), ("xx", "en"), (5, "en"), ("", "en"), (None, "en"),
    ("de-AT", "de"), ("en-US", "en"), ("zh-TW", "zh-Hant"), ("zh", "zh-Hans"),
])
def test_explicit_code_uses_any_status_else_english(value: object, expected: str) -> None:
    assert i18n.resolve_language(value, os_language="ja-JP", available=AVAILABLE) == expected


def test_explicit_code_without_catalog_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        for _round in range(3):
            assert i18n.resolve_language("ja", os_language=None, available=AVAILABLE) == "en"
    assert len(caplog.records) == 1


def test_detect_os_language_windows_and_posix() -> None:
    assert i18n.detect_os_language(platform="win32", windows_ui_language=lambda: 0x0416) == "pt-BR"
    assert i18n.detect_os_language(platform="win32", windows_ui_language=lambda: 0x0404) == "zh-TW"
    env = {"LANG": "de_DE.UTF-8"}
    assert i18n.detect_os_language(platform="linux", environ=env) == "de-DE"
    env = {"LANG": "de_DE.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8", "LC_ALL": ""}
    assert i18n.detect_os_language(platform="linux", environ=env) == "fr-FR"
    # macOS without a readable language list: the locale, as on Linux.
    assert i18n.detect_os_language(platform="darwin", environ={"LANG": "C"},
                                   getlocale=lambda: ("ja_JP", "UTF-8"),
                                   mac_preferred_language=lambda: None) == "ja-JP"
    assert i18n.detect_os_language(platform="darwin", environ={},
                                   getlocale=lambda: (None, None),
                                   mac_preferred_language=lambda: None) is None


def test_detect_os_language_never_raises() -> None:
    def boom() -> int:
        raise OSError("no kernel32")

    def boom_locale() -> tuple[str | None, str | None]:
        raise ValueError("unknown locale")

    def boom_mac() -> str | None:
        raise RuntimeError("defaults crashed")

    assert i18n.detect_os_language(platform="win32", windows_ui_language=boom) is None
    assert i18n.detect_os_language(platform="linux", environ={}, getlocale=boom_locale) is None
    assert i18n.detect_os_language(platform="darwin", environ={"LANG": "de_DE.UTF-8"},
                                   mac_preferred_language=boom_mac) is None


# --- macOS: the preferred-languages list (AppleLanguages) -----------------------------------

# The shapes `defaults read -g AppleLanguages` prints (an old-style plist array): hyphenated
# entries are quoted, plain ones are not; one entry per line, four-space indent, LF line ends.
MAC_DE_FIRST = '(\n    "de-DE",\n    "en-US"\n)\n'
MAC_PLAIN_FIRST = '(\n    en,\n    "fr-FR"\n)\n'
MAC_HANS = '(\n    "zh-Hans-CN",\n    "en-GB"\n)\n'


@pytest.mark.parametrize("output,expected", [
    (MAC_DE_FIRST, "de-DE"), (MAC_PLAIN_FIRST, "en"), (MAC_HANS, "zh-Hans-CN"),
    ('(\n    "pt-BR"\n)', "pt-BR"), ("(\n)\n", None), ("()", None), ("", None),
    ("The domain/default pair of (kCFPreferencesAnyApplication, AppleLanguages) does not exist\n",
     None),
    ('"de-DE"', None),
])
def test_parse_apple_languages(output: str, expected: str | None) -> None:
    assert i18n.parse_apple_languages(output) == expected


def test_detect_os_language_on_macos_prefers_the_language_list() -> None:
    env = {"LANG": "en_US.UTF-8"}  # the region format often says English while the UI is German
    found = i18n.detect_os_language(platform="darwin", environ=env,
                                    mac_preferred_language=lambda: "de-DE")
    assert found == "de-DE"
    assert i18n.resolve_language("auto", os_language=found, available=AVAILABLE) == "de"
    hans = i18n.detect_os_language(platform="darwin", environ=env,
                                   mac_preferred_language=lambda: "zh-Hans-CN")
    assert i18n.resolve_language("auto", os_language=hans, available=AVAILABLE) == "zh-Hans"
    # Linux never asks macOS.
    def never() -> str | None:
        raise AssertionError("read on Linux")
    assert i18n.detect_os_language(platform="linux", environ=env, mac_preferred_language=never) == "en-US"


class _Done:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_mac_preferred_language_reads_defaults_with_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    calls: list[tuple[Any, dict[str, Any]]] = []

    def run(cmd: Any, **kwargs: Any) -> _Done:
        calls.append((cmd, kwargs))
        return _Done(0, MAC_DE_FIRST)

    monkeypatch.setattr(subprocess, "run", run)
    assert i18n._mac_preferred_language() == "de-DE"
    cmd, kwargs = calls[0]
    assert cmd == ["/usr/bin/defaults", "read", "-g", "AppleLanguages"]
    assert 0 < kwargs["timeout"] <= 5 and kwargs["check"] is False


@pytest.mark.parametrize("outcome,logged", [
    (FileNotFoundError(2, "No such file", "/usr/bin/defaults"), "FileNotFoundError"),
    ("timeout", "TimeoutExpired"),
    (_Done(1, "", "Domain AppleLanguages does not exist"), "exit 1"),
    (_Done(0, "garbage"), "Unexpected"),
])
def test_mac_preferred_language_failures_log_and_return_none(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, outcome: Any,
        logged: str) -> None:
    import subprocess

    def run(cmd: Any, **kwargs: Any) -> _Done:
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", run)
    with caplog.at_level(logging.WARNING, logger="app.i18n"):
        assert i18n._mac_preferred_language() is None
    assert len(caplog.records) == 1 and logged in caplog.records[0].getMessage()
    # detect_os_language then falls back to the locale.
    assert i18n.detect_os_language(platform="darwin", environ={"LANG": "fr_FR.UTF-8"}) == "fr-FR"


def test_setting_language_resolves_like_start_up(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "de", {}, status="reviewed")
    write_catalog(locales, "fr", {}, status="machine")
    seen: list[int] = []

    def detect(**_k: Any) -> str:
        seen.append(1)
        return "de-AT"

    monkeypatch.setattr(i18n, "detect_os_language", detect)
    assert i18n.setting_language("auto") == "de"
    assert i18n.setting_language("") == "de"
    assert i18n.setting_language("fr") == "fr"  # an explicit machine catalog
    assert i18n.setting_language("en") == "en"
    assert i18n.setting_language("ja") == "en"  # no catalog
    assert i18n.setting_language("qps-ploc") == "qps-ploc"
    assert len(seen) == 1  # the OS language is read once per process


def test_init_language_env_overrides_config(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "de", {"Save": "Speichern"}, status="machine")
    assert i18n.init_language(lambda: {"ui_language": "de"}, environ={}) == "de"
    assert i18n._("Save") == "Speichern"
    env = {i18n.ENV_LANGUAGE: "qps-ploc"}
    assert i18n.init_language(lambda: {"ui_language": "de"}, environ=env) == "qps-ploc"


def test_init_language_survives_a_broken_config(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> dict[str, Any]:
        raise OSError("disk gone")

    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: "de-DE")
    write_catalog(locales, "de", {}, status="reviewed")
    assert i18n.init_language(broken, environ={}) == "de"  # treated as "auto"


def test_init_language_auto_does_not_pick_machine_catalog(locales: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_os_language", lambda **_k: "de-DE")
    write_catalog(locales, "de", {"Save": "Speichern"}, status="machine")
    assert i18n.init_language(lambda: {"ui_language": "auto"}, environ={}) == "en"
    assert i18n._("Save") == "Save"


# --- R3 catalog location in source and frozen builds ---------------------------------------

def test_locales_dir_in_source_and_frozen_layouts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sys
    repo = Path(__file__).resolve().parent.parent
    assert i18n.locales_dir() == repo / "app" / "locales"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert i18n.locales_dir() == tmp_path / "app" / "locales"
    monkeypatch.delattr(sys, "_MEIPASS")
    exe_dir = tmp_path / "onedir"
    monkeypatch.setattr(sys, "executable", str(exe_dir / "WhisperTranscriber.exe"))
    assert i18n.locales_dir() == exe_dir / "app" / "locales"


def test_frozen_build_loads_its_bundled_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sys
    folder = tmp_path / "app" / "locales"
    folder.mkdir(parents=True)
    write_catalog(folder, "de", {"Save": "Speichern"})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert i18n.set_language("de") == "de"
    assert i18n._("Save") == "Speichern"


# --- R5 start-up order and config key ------------------------------------------------------

def test_run_sets_the_language_after_the_crash_hook_and_before_app_import() -> None:
    import inspect

    import app
    src = inspect.getsource(app.run)
    hook = src.find("crash_report.install_excepthook()")
    init = src.find("i18n.init_language(")
    app_import = src.find("from .app import App")
    assert -1 not in (hook, init, app_import)
    assert hook < init < app_import
    assert "load_config(fetch_online=False)" in src[hook:app_import]


def test_ui_language_is_a_local_only_config_key() -> None:
    from core import config
    assert config.DEFAULT_CONFIG["ui_language"] == "auto"
    assert "ui_language" in config.LOCAL_ONLY_KEYS
    assert "ui_language" not in config.ONLINE_ALLOWED_KEYS
    merged = config.merge_config_sources(dict(config.DEFAULT_CONFIG), {"ui_language": "de"}, None)
    assert merged.get("ui_language") == "auto"


def test_config_doc_describes_ui_language() -> None:
    doc = (Path(__file__).resolve().parent.parent / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| `ui_language`"))
    assert '`"auto"`' in row and "WTS_UI_LANGUAGE" in row


# --- invariants (Hypothesis) ---------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_names = st.from_regex(r"[a-z][a-z_]{0,7}", fullmatch=True)
_words = st.text(alphabet=string.ascii_letters + " ", max_size=20)


@st.composite
def _msgids(draw: Any) -> tuple[str, set[str]]:
    parts = draw(st.lists(st.one_of(_words, _names.map(lambda n: "{" + n + "}")), max_size=8))
    msgid = "".join(parts)
    names = {n for _l, n, _s, _c in string.Formatter().parse(msgid) if n}
    return msgid, names


@settings(max_examples=300, deadline=None)
@given(_msgids())
def test_pseudo_keeps_placeholders_and_formats(case: tuple[str, set[str]]) -> None:
    msgid, names = case
    pseudo = i18n.pseudo_translate(msgid)
    assert {n for _l, n, _s, _c in string.Formatter().parse(pseudo) if n} == names
    values = {n: "V" for n in names}
    pseudo.format(**values)  # never fails
    i18n.set_language(i18n.PSEUDO_LOCALE)
    try:
        if names:
            assert i18n._(msgid, **values).count("V") >= len(names)
    finally:
        i18n.set_language("en")


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=40))
def test_english_returns_any_msgid_unchanged(msgid: str) -> None:
    assert i18n._(msgid) == msgid
    assert i18n.pgettext("ctx", msgid) == msgid
    assert i18n.translate(msgid) == msgid


@settings(max_examples=500, deadline=None)
@given(st.sampled_from(sorted(i18n.PLURAL_RULES)), st.integers(min_value=0, max_value=10**6))
def test_plural_index_always_in_range(rule: str, n: int) -> None:
    assert 0 <= i18n.plural_index(rule, n) < i18n.PLURAL_RULES[rule][0]


@settings(max_examples=200, deadline=None)
@given(_msgids(), st.text(max_size=30))
def test_any_catalog_value_never_raises(case: tuple[str, set[str]], bad: str) -> None:
    """Whatever a translator wrote, a correct call returns text and never raises."""
    msgid, names = case
    state = i18n._Catalog("de", {msgid: bad, "{n} x": [bad, bad]}, 2, i18n._one_other, "ltr")
    old = i18n._STATE
    i18n._STATE = state
    try:
        assert isinstance(i18n._(msgid, **{n: 1 for n in names}), str)
        assert isinstance(i18n._(msgid), str)
        assert isinstance(i18n.ngettext("{n} x", "{n} xs", 3), str)
    finally:
        i18n._STATE = old
