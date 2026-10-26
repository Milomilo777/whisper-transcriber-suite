"""Right-to-left display shaping for Linux (app.rtl_shaping + its hooks in app.i18n / bidi_display).

Tk 8.6 on X11 neither joins Arabic-script letters nor reorders right-to-left text, so on Linux the
interface texts that ``_()`` returns are reshaped (arabic-reshaper) and put in visual order
(python-bidi) once, for display only. Windows and macOS draw right-to-left text natively and must
get exactly what they got before. No Tk root; the platform is chosen with a patched
``sys.platform``. Real Linux screens are NOT covered here (no Linux desktop; see the CHANGELOG).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app import i18n, rtl_shaping
from app.theme import bidi_display

RLE = chr(0x202B)
PDF = chr(0x202C)

FA_SAMPLE = "ذخیره شد: report.txt (12 GB)"
HE_SAMPLE = "נשמרו 12 קבצים ב-C"
# Visual order, base direction right to left: the first logical letter ends up at the right end.
FA_VISUAL = "report.txt (12 GB) :ﺪﺷ ﻩﺮﯿﺧﺫ"
HE_VISUAL = "C-ב םיצבק 12 ורמשנ"

FA = {
    "Save": "ذخیره",
    "Saved {name}": "{name} ذخیره شد",
    "Interface language:": "زبان رابط:",
    "Latin only": "Whisper",
}
HE = {"Save": "שמור", "Saved {name}": "{name} נשמר"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(i18n, "_WARNED", set())
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
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


def write_catalog(folder: Path, code: str, messages: dict[str, Any], status: str = "reviewed") -> None:
    lang = i18n.LANGUAGES_BY_CODE[code]
    doc = {"_meta": {"code": code, "name": lang.endonym, "direction": lang.direction,
                     "status": status, "plural": lang.plural}, "messages": messages}
    (folder / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def on(monkeypatch: pytest.MonkeyPatch, platform: str, engine: bool = True) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(rtl_shaping, "available", lambda: engine)


@pytest.fixture
def fa_linux(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA)
    write_catalog(locales, "he", HE)
    on(monkeypatch, "linux")


# --- the transform ------------------------------------------------------------------------------

def test_persian_sample_is_joined_and_in_visual_order() -> None:
    out = rtl_shaping.visual(FA_SAMPLE)
    assert out == FA_VISUAL
    # No plain Arabic-block letter is left: every one is a presentation form (joined).
    assert not any(0x0600 <= ord(ch) <= 0x06FF for ch in out)
    # The Latin name and the bracketed number stay in reading order, left of the Persian words,
    # and the first logical letter (an isolated "zal") ends the line at the right.
    assert out.startswith("report.txt (12 GB) :")
    assert out.endswith(chr(0xFEAB))


def test_hebrew_sample_is_in_visual_order_without_shaping() -> None:
    assert rtl_shaping.visual(HE_SAMPLE) == HE_VISUAL


def test_brackets_around_latin_stay_a_pair_and_brackets_around_persian_are_mirrored() -> None:
    # "ELAN (.eaf)" in a Persian line: the pair keeps its shape and its place next to the name
    # (python-bidi's pure-Python algorithm alone gave "(ELAN (.eaf").
    out = rtl_shaping.visual("ورود/خروجی ELAN (.eaf)")
    assert "ELAN (.eaf)" in out
    # A pair around Persian words is mirrored: in visual order it still reads "(" ... ")".
    inner = rtl_shaping.visual("(ب)")
    assert inner == "(" + rtl_shaping.visual("ب") + ")"
    assert out.count("(") == out.count(")") == 1
    # An unmatched bracket does not break anything.
    assert rtl_shaping.visual("ب )") != ""
    # No mark used to force the pair leaks out (Tk on X11 could draw it as a box).
    assert not set(out) & {chr(0x200E), chr(0x200F), chr(0x200C)}


def test_latin_digits_and_empty_text_are_untouched() -> None:
    for text in ("", "Save", "12 files (3 GB)", "C:/a/b.wav", "ABC 123\nxyz"):
        assert rtl_shaping.visual(text) == text


def test_every_line_is_ordered_on_its_own() -> None:
    out = rtl_shaping.visual(FA_SAMPLE + "\n\nplain line\r\n" + HE_SAMPLE)
    assert out == FA_VISUAL + "\n\nplain line\r\n" + HE_VISUAL


@pytest.mark.parametrize("sample", [FA_SAMPLE, HE_SAMPLE, "زبان رابط:", "أهلاً بالعالم 5"])
def test_never_shaped_twice(sample: str) -> None:
    once = rtl_shaping.visual(sample)
    assert once != sample
    assert rtl_shaping.visual(once) == once
    assert rtl_shaping.visual(rtl_shaping.visual(once)) == once


def test_logical_gives_back_the_text_that_was_shaped() -> None:
    for sample in (FA_SAMPLE, HE_SAMPLE):
        assert rtl_shaping.logical(rtl_shaping.visual(sample)) == sample
    assert rtl_shaping.logical("never shaped") == "never shaped"


def test_base_direction_left_to_right_keeps_a_latin_start_in_front() -> None:
    out = rtl_shaping.visual("Use فارسی", base="L")
    assert out.startswith("Use ")
    assert rtl_shaping.visual(out, base="L") == out


def test_a_missing_engine_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rtl_shaping, "_engine", lambda: None)
    assert rtl_shaping.available() is False
    assert rtl_shaping.visual(FA_SAMPLE) == FA_SAMPLE


# --- the Linux gate -----------------------------------------------------------------------------

def test_linux_is_ready_only_with_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    assert i18n.RTL_PLATFORMS == frozenset({"win32", "darwin"})  # the platforms that draw RTL natively
    assert i18n.SHAPED_PLATFORMS == frozenset({"linux"})
    for platform, engine, ready in (("win32", False, True), ("darwin", False, True),
                                    ("linux", True, True), ("linux", False, False)):
        on(monkeypatch, platform, engine)
        assert i18n.rtl_layout_ready() is ready, (platform, engine)


def test_picker_offers_the_three_languages_on_linux(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for code in ("de", "ar", "fa", "he"):
        write_catalog(locales, code, {}, status="machine")
    on(monkeypatch, "linux")
    assert [lang.code for lang in i18n.available_languages()] == ["en", "de", "ar", "fa", "he"]
    on(monkeypatch, "linux", engine=False)
    assert [lang.code for lang in i18n.available_languages()] == ["en", "de"]


def test_auto_follows_the_system_to_persian_on_linux_with_the_engine(
        locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA)
    on(monkeypatch, "linux")
    assert i18n.resolve_language("auto", os_language="fa-IR", available=i18n.catalog_statuses()) == "fa"
    on(monkeypatch, "linux", engine=False)
    assert i18n.resolve_language("auto", os_language="fa-IR", available=i18n.catalog_statuses()) == "en"


# --- _() on Linux -------------------------------------------------------------------------------

def test_translations_come_out_shaped_without_embedding_marks(fa_linux: None) -> None:
    assert i18n.set_language("fa") == "fa"
    assert i18n.rtl_shaped() is True
    assert i18n.rtl_marks() is False
    assert i18n._("Save") == rtl_shaping.visual("ذخیره")
    out = i18n._("Saved {name}", name="report.txt")
    assert out == rtl_shaping.visual("report.txt ذخیره شد")
    assert RLE not in out and PDF not in out


def test_hebrew_is_reordered_too(fa_linux: None) -> None:
    i18n.set_language("he")
    assert i18n._("Save") == "רומש"
    assert i18n._("Saved {name}", name="a.txt") == "רמשנ a.txt"


def test_english_fallback_and_latin_only_texts_are_untouched(fa_linux: None) -> None:
    i18n.set_language("fa")
    assert i18n._("Not in the catalog") == "Not in the catalog"
    assert i18n._("Latin only") == "Whisper"


def test_a_translated_value_inside_another_text_is_shaped_once(fa_linux: None) -> None:
    i18n.set_language("fa")
    inner = i18n._("Save")
    out = i18n._("Saved {name}", name=inner)
    assert out == rtl_shaping.visual("ذخیره ذخیره شد")


def test_plain_recovers_the_catalog_text(fa_linux: None) -> None:
    i18n.set_language("fa")
    assert i18n.plain(i18n._("Saved {name}", name="report.txt")) == "report.txt ذخیره شد"


def test_an_explicit_code_without_the_engine_loads_unshaped(locales: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA)
    on(monkeypatch, "linux", engine=False)
    assert i18n.set_language("fa") == "fa"
    assert i18n.rtl_shaped() is False
    assert i18n._("Save") == "ذخیره"


def test_left_to_right_catalogs_on_linux_are_untouched(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "de", {"Save": "Speichern"})
    on(monkeypatch, "linux")
    i18n.set_language("de")
    assert i18n.rtl_shaped() is False
    assert i18n._("Save") == "Speichern"


# --- Windows and macOS stay as they were ---------------------------------------------------------

@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_native_platforms_get_marks_and_no_shaping(locales: Path, monkeypatch: pytest.MonkeyPatch,
                                                   platform: str) -> None:
    write_catalog(locales, "fa", FA)
    on(monkeypatch, platform)
    i18n.set_language("fa")
    assert i18n.rtl_shaped() is False
    assert i18n.rtl_marks() is True
    assert i18n._("Save") == RLE + "ذخیره" + PDF
    assert i18n._("Saved {name}", name="a.txt") == RLE + "a.txt ذخیره شد" + PDF
    assert i18n.plain(i18n._("Save")) == "ذخیره"


def test_ltr_base_shapes_only_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "فارسی"
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: False)
    on(monkeypatch, "win32")
    assert bidi_display.ltr_base(text) == text
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: True)
    on(monkeypatch, "darwin")
    assert bidi_display.ltr_base(text) == bidi_display.LRM + text
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: False)
    on(monkeypatch, "linux")
    shaped = bidi_display.ltr_base(text)
    assert shaped == rtl_shaping.visual(text, base="L") != text
    assert bidi_display.ltr_base(shaped) == shaped


def test_layout_is_mirrored_on_linux_when_shaped(fa_linux: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import rtl_layout
    monkeypatch.delenv(rtl_layout.ENV_OVERRIDE, raising=False)
    assert rtl_layout.active() is False
    i18n.set_language("fa")
    assert rtl_layout.active() is True
