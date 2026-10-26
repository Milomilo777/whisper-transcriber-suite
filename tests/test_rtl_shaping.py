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

pytest.importorskip("arabic_reshaper")
pytest.importorskip("bidi")

from app import i18n, rtl_shaping  # noqa: E402 - after the importorskip lines
from app.theme import bidi_display  # noqa: E402

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
    for memory in (rtl_shaping._VISUAL_TO_LOGICAL, rtl_shaping._BY_FIRST_CHAR, rtl_shaping._CACHE):
        memory.clear()  # results remembered by an earlier test must not change this one
    i18n.set_language("en")
    yield
    i18n.set_language("en")
    rtl_shaping.uninstall_title_hook()


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


# --- round 2: composed texts, window titles, statuses (review findings D1-D5, E1-E3) ----------------

FA2 = {**FA, "Open the page": "صفحه را باز کنید", "Failed.": "ناموفق.",
       "{progress} — “{words}”": "{progress} — «{words}»",
       "{percent}% done": "{percent}% انجام شد",
       "{name}: {percent}% done": "{name}: {percent}% انجام شد",
       "Transcribing {name}…": "در حال رونویسی {name}…"}


@pytest.fixture
def fa2_linux(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA2)
    on(monkeypatch, "linux")
    i18n.set_language("fa")


def test_plain_recovers_shaped_segments_inside_composed_text(fa2_linux: None) -> None:
    save, page = i18n._("Save"), i18n._("Open the page")
    assert save != "ذخیره"
    assert i18n.plain("  " + save) == "  ذخیره"
    assert i18n.plain(save + " " + page) == "ذخیره صفحه را باز کنید"
    assert i18n.plain(f"{save}: y") == "ذخیره: y"
    assert i18n.plain(save + "\n\n" + page + "\r\n") == "ذخیره\n\nصفحه را باز کنید\r\n"


def _shaped_name(text: str) -> str:
    return rtl_shaping.visual(text, base="L")


def test_a_shaped_name_inside_a_persian_sentence_is_shaped_with_it() -> None:
    line = "فایل " + _shaped_name("گزارش.txt") + " ذخیره شد"
    out = rtl_shaping.visual(line)
    assert out != line
    assert out == rtl_shaping.visual("فایل گزارش.txt ذخیره شد")
    assert rtl_shaping.logical(out) == "فایل گزارش.txt ذخیره شد"


def test_a_hebrew_composed_line_is_not_reversed_twice() -> None:
    inner = rtl_shaping.visual("דוח שנתי")
    line = "הקובץ " + inner + " נשמר"
    assert rtl_shaping.visual(line) == rtl_shaping.visual("הקובץ דוח שנתי נשמר")


def test_a_short_hebrew_word_is_not_taken_for_a_shaped_segment() -> None:
    rtl_shaping.visual("אב")  # remembers the visual "בא" for the logical "אב"
    sentence = "הוא בא הביתה"
    assert rtl_shaping.logical(rtl_shaping.visual(sentence)) == sentence


def test_a_short_hebrew_text_equal_to_an_earlier_result_is_still_shaped() -> None:
    assert rtl_shaping.visual("המר") == "רמה"
    assert rtl_shaping.visual("רמה") == "המר"  # logical "רמה" is not the earlier result
    # logical() is for shaped UI text, so it accepts any exact earlier result, even a short one.
    assert rtl_shaping.logical("המר") == "רמה"


def test_a_translation_equal_to_an_earlier_long_hebrew_result_is_shaped(
        locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    long_logical = "אבגדהוזחט"
    earlier = rtl_shaping.visual(long_logical)
    assert earlier == long_logical[::-1]
    assert rtl_shaping.visual(earlier) == earlier  # sniffed as a result: not reversed back
    write_catalog(locales, "he", {"Save": earlier})  # a catalog text is logical for sure
    on(monkeypatch, "linux")
    i18n.set_language("he")
    assert i18n._("Save") == long_logical


def test_the_rial_sign_and_a_bom_are_not_presentation_forms() -> None:
    for sign in (chr(0xFDFC), chr(0xFD3E), chr(0xFD3F), chr(0xFEFF)):
        assert not rtl_shaping._is_shaped(sign), hex(ord(sign))
    line = "قیمت 100 " + chr(0xFDFC) + " است"
    out = rtl_shaping.visual(line)
    assert out != line and rtl_shaping.logical(out) == line
    assert rtl_shaping._is_shaped(chr(0xFEAB)) and rtl_shaping._is_shaped(chr(0xFB56))


def test_unknown_presentation_forms_are_left_alone() -> None:
    raw = chr(0xFEAB) + chr(0xFEE9)  # not made by visual(): nothing to recover, nothing to reshape
    assert rtl_shaping.visual(raw) == raw


def test_a_line_of_only_a_direction_mark_does_not_poison_logical() -> None:
    rtl_shaping.visual(chr(0x200F))
    assert rtl_shaping.logical("a\n\nb") == "a\n\nb"
    assert rtl_shaping.logical("\n") == "\n"
    assert "" not in rtl_shaping._VISUAL_TO_LOGICAL


def test_window_titles_get_logical_text(fa2_linux: None) -> None:
    class Wm:
        def __init__(self) -> None:
            self.titles: list[Any] = []

        def wm_title(self, string: Any = None) -> str:
            self.titles.append(string)
            return "ok"

        title = wm_title

    class Dialog:
        def __init__(self, **options: Any) -> None:
            self.options = options
            self.seen: dict[str, Any] = {}

        def show(self, **options: Any) -> str:
            self.options.update(options)
            self.seen = dict(self.options)
            return "shown"

    restore = rtl_shaping.install_title_hook(wm=Wm, dialog=Dialog)
    try:
        wm = Wm()
        assert wm.title(i18n._("Save")) == "ok" and wm.wm_title(i18n._("Open the page") + " 1") == "ok"
        assert wm.title() == "ok"
        assert wm.titles == ["ذخیره", "صفحه را باز کنید 1", None]
        dlg = Dialog(title=i18n._("Save"), message=i18n._("Save"))
        assert dlg.show(title=i18n._("Open the page")) == "shown"
        assert dlg.seen["title"] == "صفحه را باز کنید"
        assert dlg.seen["message"] == i18n._("Save")  # the body is drawn by Tk: stays shaped
        first = Dialog(title=i18n._("Save"))
        first.show()
        assert first.seen["title"] == "ذخیره"
        again = rtl_shaping.install_title_hook(wm=Wm, dialog=Dialog)  # twice is harmless
        wm2 = Wm()
        wm2.title(i18n._("Save"))
        assert wm2.titles == ["ذخیره"]
        again()
    finally:
        restore()


def test_status_line_clips_the_logical_text_then_shapes(fa2_linux: None) -> None:
    from app.domain import status_line as sl

    words = "کلمه " * 60
    message = "[file=a.wav] [ 5%] 00:00.000 --> 00:01.000 | " + words
    out = sl.status_line(message)
    assert out is not None
    back = rtl_shaping.logical(out)
    assert back.startswith("a.wav: 5% انجام شد — «کلمه")  # the logical beginning survives
    assert back.endswith("…»")
    assert len(back) <= sl.MAX_CHARS
    assert out == rtl_shaping.visual(back)


def test_status_line_clip_keeps_the_logical_beginning_of_a_long_shaped_line(fa2_linux: None) -> None:
    from app.domain import status_line as sl

    name = "x" * 150 + ".wav"
    out = sl.status_line("Processing: C:/media/" + name)
    assert out is not None
    back = rtl_shaping.logical(out)
    assert back.startswith("در حال رونویسی x") and back.endswith("…")  # the Persian words come first
    assert len(back) <= sl.MAX_CHARS
    assert out == rtl_shaping.visual(back)


def test_display_shapes_a_composed_text_once(fa2_linux: None) -> None:
    a, b = i18n._("Save"), i18n._("Open the page")
    joined = i18n.display(a + " " + b)
    assert joined == rtl_shaping.visual("ذخیره صفحه را باز کنید")
    assert i18n.display(joined) == joined
    assert i18n.display("plain English") == "plain English"


def test_display_is_the_identity_off_linux(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA2)
    for platform in ("win32", "darwin"):
        on(monkeypatch, platform)
        i18n.set_language("fa")
        text = i18n._("Save") + " " + i18n._("Open the page")
        assert i18n.display(text) is text


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_windows_and_macos_output_is_exactly_the_marked_catalog_text(
        monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    """The real catalogs: every message is the catalog text with RLE ... PDF per line, no shaping."""
    on(monkeypatch, platform)
    root = Path(__file__).resolve().parents[1] / "app" / "locales"
    checked = 0
    for code in ("fa", "ar", "he"):
        doc = json.loads((root / f"{code}.json").read_text(encoding="utf-8"))
        assert i18n.set_language(code) == code
        assert i18n.rtl_shaped() is False and i18n.rtl_marks() is True
        for key, value in doc["messages"].items():
            if not isinstance(value, str) or not value or "{" in value or "\x04" in key:
                continue
            assert i18n._(key) == i18n.embed_rtl(value), (code, key)
            assert not any(0xFB50 <= ord(ch) <= 0xFEFC for ch in i18n._(key)), (code, key)
            checked += 1
    assert checked > 500


# --- mutants the first round did not catch -------------------------------------------------------------

def test_zero_width_non_joiners_never_reach_the_output() -> None:
    out = rtl_shaping.visual("می" + chr(0x200C) + "کند")
    assert chr(0x200C) not in out and out != "می" + chr(0x200C) + "کند"


def test_zero_width_non_joiners_are_removed_even_when_the_engine_keeps_them(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from core.writers.pdf_bidi import Engine

    keep = Engine(reshape=lambda t: t, reorder=lambda t, _base: t[::-1])
    monkeypatch.setattr(rtl_shaping, "_engine", lambda: keep)
    monkeypatch.setattr(rtl_shaping, "_CACHE", {})
    out = rtl_shaping.visual("ب" + chr(0x200C) + "ت")
    assert chr(0x200C) not in out and out == "تب"


def test_ltr_base_keeps_a_latin_start_in_front_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: False)
    on(monkeypatch, "linux")
    out = bidi_display.ltr_base("Use فارسی")
    assert out.startswith("Use ")
    assert out != rtl_shaping.visual("Use فارسی", base="R")


def test_a_carriage_return_stays_at_the_end_of_its_line_also_from_the_cache() -> None:
    first = rtl_shaping.visual("ب\r")
    second = rtl_shaping.visual("ب\r")  # served from the cache
    assert first == second and second.endswith("\r") and second.count("\r") == 1
    multi = rtl_shaping.visual("ب\r\nب\r\n")
    assert multi.count("\r") == 2 and multi.endswith("\r\n")


def test_logical_keeps_the_carriage_returns() -> None:
    text = "ذخیره شد\r\nپایان\r"
    assert rtl_shaping.logical(rtl_shaping.visual(text)) == text


# --- round 3: short Hebrew results, speed (review findings D-HE, SPEED) ---------------------------------

HE3 = {
    "Show": "הצג", "Hide": "הסתר", "Exit": "צא", "tray menu\x04Show": "הצג",
    "'{needle}' not found.": "'{needle}' לא נמצא.",
    "Transcribing {name}…": "מתמלל {name}…",
}


@pytest.fixture
def he3_linux(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "he", HE3)
    on(monkeypatch, "linux")
    i18n.set_language("he")


def test_every_hebrew_catalog_text_round_trips_through_plain_and_display(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The real he.json on Linux: plain(_(k)) is the catalog text and display(_(k)) is _(k)."""
    on(monkeypatch, "linux")
    root = Path(__file__).resolve().parents[1] / "app" / "locales"
    doc = json.loads((root / "he.json").read_text(encoding="utf-8"))
    assert i18n.set_language("he") == "he" and i18n.rtl_shaped() is True
    bad_plain: list[str] = []
    bad_display: list[str] = []
    checked = 0
    for key, value in doc["messages"].items():
        if not isinstance(value, str) or not value or "{" in value:
            continue
        shown = i18n._(key)
        checked += 1
        if i18n.plain(shown) != value:
            bad_plain.append(key)
        if i18n.display(shown) != shown:
            bad_display.append(key)
    assert checked > 1000
    assert bad_plain == [] and bad_display == []


def test_short_hebrew_results_reach_the_tray_and_titles_logical(he3_linux: None) -> None:
    assert i18n._("Show") != "הצג"  # reversed for the screen
    assert rtl_shaping.logical(i18n.pgettext("tray menu", "Show")) == "הצג"
    assert rtl_shaping.logical(i18n._("Exit")) == "צא"
    assert i18n.plain(i18n._("Exit")) == "צא"


def test_display_of_short_hebrew_parts_joins_them_once(he3_linux: None) -> None:
    joined = i18n.display(i18n._("Show") + " " + i18n._("Hide"))
    assert joined == rtl_shaping.visual("הצג הסתר", logical_input=True)
    assert i18n.display(i18n._("Exit")) == i18n._("Exit")


def test_a_short_hebrew_placeholder_is_not_reversed_twice(he3_linux: None) -> None:
    out = i18n._("'{needle}' not found.", needle=i18n._("Show"))
    assert out == rtl_shaping.visual("'הצג' לא נמצא.", logical_input=True)


def test_status_clip_keeps_a_short_hebrew_message(he3_linux: None) -> None:
    from app.domain import status_line as sl

    assert sl._clip(i18n._("Exit")) == i18n._("Exit")
    assert sl._clip(i18n._("Show") + "  " + i18n._("Hide")) == i18n.display(
        i18n._("Show") + " " + i18n._("Hide"))


def test_status_clip_shapes_its_logical_result_even_if_that_equals_an_earlier_result(
        he3_linux: None, empty_memory: None) -> None:
    from app.domain import status_line as sl

    a = "אבגדהוזחט"
    x = rtl_shaping.visual(a)  # the reversed text
    assert rtl_shaping.visual(x, logical_input=True) == a  # and now "a" is a remembered result too
    assert sl._clip(x) == x  # logical(x) is a; shaping a (logical for sure) gives x again


def test_the_title_hook_passes_short_hebrew_logical(he3_linux: None) -> None:
    class Wm:
        def __init__(self) -> None:
            self.titles: list[Any] = []

        def wm_title(self, string: Any = None) -> None:
            self.titles.append(string)

        title = wm_title

    class Dialog:
        def show(self, **options: Any) -> None:
            return None

    restore = rtl_shaping.install_title_hook(wm=Wm, dialog=Dialog)
    try:
        wm = Wm()
        wm.title(i18n._("Exit"))
        assert wm.titles == ["צא"]
    finally:
        restore()


def test_leaving_a_shaped_language_removes_the_title_hook(locales: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    import tkinter as tk

    write_catalog(locales, "he", HE3)
    write_catalog(locales, "de", {"Show": "Zeigen"})
    on(monkeypatch, "linux")
    i18n.set_language("he")
    assert tk.Wm.__dict__.get("_wts_logical_title") is True
    i18n.set_language("de")
    assert "_wts_logical_title" not in tk.Wm.__dict__


@pytest.fixture
def empty_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections import OrderedDict
    monkeypatch.setattr(rtl_shaping, "_VISUAL_TO_LOGICAL", OrderedDict())
    monkeypatch.setattr(rtl_shaping, "_BY_FIRST_CHAR", {})
    monkeypatch.setattr(rtl_shaping, "_CACHE", {})


def test_a_thousand_bracket_free_file_names_are_shaped_quickly(empty_memory: None) -> None:
    import time

    names = [f"گزارش جلسه شماره {i} - نسخه نهایی.txt" for i in range(1000)]
    start = time.perf_counter()
    for name in names:
        rtl_shaping.visual(name, base="L")
    elapsed = time.perf_counter() - start
    print(f"\n1000 visual() calls on bracket-free Persian names: {elapsed:.3f} s")
    assert elapsed < 2.0


def test_recovery_over_many_remembered_keys_is_fast(empty_memory: None) -> None:
    import time

    for i in range(rtl_shaping._REMEMBERED):
        rtl_shaping._remember(f"{chr(0xFE8D + i % 40)}ﺏ{i}", f"ب{i}")
    # Worst case: the text holds the first character of every key (about 23k characters).
    text = ("".join(chr(0xFE8D + i) for i in range(40)) + " ") * 550
    start = time.perf_counter()
    rtl_shaping.logical(text)
    elapsed = time.perf_counter() - start
    print(f"\nlogical() on {len(text)} chars with {len(rtl_shaping._VISUAL_TO_LOGICAL)} keys: {elapsed:.3f} s")
    assert elapsed < 1.0


def test_the_index_follows_eviction(empty_memory: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rtl_shaping, "_REMEMBERED", 3)
    for i in range(6):
        rtl_shaping._remember(f"ﺏ{i}", f"ب{i}")
    assert len(rtl_shaping._VISUAL_TO_LOGICAL) == 3
    assert sum(len(v) for v in rtl_shaping._BY_FIRST_CHAR.values()) == 3
