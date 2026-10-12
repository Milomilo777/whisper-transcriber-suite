"""Right-to-left catalogs on Windows: direction marks per line, the platform gate, plain() (no Tk root).

Tk draws every string with a left-to-right base direction, so a Persian line with a Latin word, a
number or a trailing ":" comes out in the wrong order. On Windows ``app.i18n`` wraps each line of
a right-to-left catalog's translation in RIGHT-TO-LEFT EMBEDDING ... POP DIRECTIONAL FORMATTING;
the English fallback and the pseudo-locale never get them, and macOS and Linux are not offered
right-to-left catalogs yet. Texts that leave the screen (log file, clipboard) go through
``plain()``. The platform is chosen with a patched ``sys.platform``; the marks are written here as
``chr(0x202B)`` / ``chr(0x202C)`` so a test never depends on the module's own constants.
"""
from __future__ import annotations

import json
import logging
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import i18n

RLE = chr(0x202B)
PDF = chr(0x202C)
LRE, LRO, RLO = chr(0x202A), chr(0x202D), chr(0x202E)
ISOLATES = {chr(c) for c in range(0x2066, 0x206A)}
RLM, LRM = chr(0x200F), chr(0x200E)

FA = {
    "Save": "ذخیره",
    "Interface language:": "زبان رابط:",
    "Saved {name}": "{name} ذخیره شد",
    "Model {model} ({size} GB)": "مدل {model} ({size} GB)",
    "First line.\n\nSecond line: {n} files\n{path}": "خط اول.\n\nخط دوم: {n} فایل\n{path}",
    "Indented": "  تورفته  ",
    "Broken {name}": "خراب {other}",
    "Already marked": RLE + "علامت‌دار" + PDF,
    "Latin only": "Whisper",
    "{n} file": ["{n} فایل", "{n} فایل"],
    "menu\x04Open": "باز کردن",
    "Status:\r\nready": "وضعیت:\r\nآماده",
}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch):
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


def write_catalog(folder: Path, code: str, messages: dict[str, Any], status: str = "reviewed") -> None:
    lang = i18n.LANGUAGES_BY_CODE[code]
    doc = {"_meta": {"code": code, "name": lang.endonym, "direction": lang.direction,
                     "status": status, "plural": lang.plural}, "messages": messages}
    (folder / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def on(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(sys, "platform", platform)


@pytest.fixture
def fa_windows(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "fa", FA)
    on(monkeypatch, "win32")
    assert i18n.set_language("fa") == "fa"


# --- R1 the marks ----------------------------------------------------------------------------------

def test_a_translated_line_is_wrapped(fa_windows: None) -> None:
    assert i18n.rtl_marks() is True
    assert i18n._("Save") == RLE + "ذخیره" + PDF
    # The trailing colon stays inside, so it is drawn at the left end of the Persian line.
    assert i18n._("Interface language:") == RLE + "زبان رابط:" + PDF


def test_placeholders_are_inside_the_marks(fa_windows: None) -> None:
    assert i18n._("Saved {name}", name="report.txt") == RLE + "report.txt ذخیره شد" + PDF
    assert i18n._("Model {model} ({size} GB)", model="large-v3", size=3) == \
        RLE + "مدل large-v3 (3 GB)" + PDF


def test_each_line_gets_its_own_pair_and_empty_or_latin_lines_none(fa_windows: None) -> None:
    out = i18n._("First line.\n\nSecond line: {n} files\n{path}", n=3, path="C:/x/a.txt")
    assert out.split("\n") == [RLE + "خط اول." + PDF, "", RLE + "خط دوم: 3 فایل" + PDF, "C:/x/a.txt"]


def test_carriage_returns_stay_outside(fa_windows: None) -> None:
    assert i18n._("Status:\r\nready") == RLE + "وضعیت:" + PDF + "\r\n" + RLE + "آماده" + PDF


def test_edge_whitespace_stays_outside_so_strip_still_works(fa_windows: None) -> None:
    out = i18n._("Indented")
    assert out == "  " + RLE + "تورفته" + PDF + "  "
    assert out.strip() == RLE + "تورفته" + PDF


def test_pgettext_ngettext_translate_and_lazy_are_wrapped(fa_windows: None) -> None:
    assert i18n.pgettext("menu", "Open") == RLE + "باز کردن" + PDF
    assert i18n.ngettext("{n} file", "{n} files", 2) == RLE + "2 فایل" + PDF
    assert i18n.translate(i18n.N_("Save")) == RLE + "ذخیره" + PDF
    assert i18n.lazy("Saved {name}", name="a")() == RLE + "a ذخیره شد" + PDF


def test_a_line_without_a_right_to_left_letter_is_left_alone(fa_windows: None) -> None:
    assert i18n._("Latin only") == "Whisper"


def test_already_wrapped_text_is_not_wrapped_twice(fa_windows: None) -> None:
    assert i18n._("Already marked") == RLE + "علامت‌دار" + PDF
    once = i18n._("Saved {name}", name="x")
    assert i18n.embed_rtl(once) == once


def test_two_translated_texts_still_compare_equal(fa_windows: None) -> None:
    # A label stored on a widget and the same label built again (combobox maps, cookie "(off)").
    assert i18n._("Save") == i18n._("Save")
    assert i18n.pgettext("menu", "Open") in {i18n.pgettext("menu", "Open"): 1}


def test_english_fallback_gets_no_marks(fa_windows: None) -> None:
    assert i18n._("Not in the catalog") == "Not in the catalog"
    assert i18n._("Not in the catalog {x}", x="ی") == "Not in the catalog ی"
    # A translation whose placeholders do not fit falls back to the English text: no marks.
    assert i18n._("Broken {name}", name="n") == "Broken n"
    assert i18n.ngettext("{n} folder", "{n} folders", 2) == "2 folders"


def test_english_and_left_to_right_catalogs_get_no_marks(locales: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "win32")
    write_catalog(locales, "de", {"Save": "Speichern", "Saved {name}": "{name} gespeichert"})
    assert i18n._("Save") == "Save"
    i18n.set_language("de")
    assert i18n.rtl_marks() is False
    assert i18n._("Save") == "Speichern"
    assert i18n._("Saved {name}", name="ذخیره.txt") == "ذخیره.txt gespeichert"


def test_pseudo_locale_gets_no_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "win32")
    i18n.set_language(i18n.PSEUDO_LOCALE)
    out = i18n._("Saved {name}", name="ذخیره")
    assert RLE not in out and PDF not in out and out.startswith("[")


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_no_marks_where_rtl_is_not_offered(locales: Path, monkeypatch: pytest.MonkeyPatch,
                                           platform: str) -> None:
    """macOS and Linux: an explicit fa still loads (translators), without the Windows marks."""
    write_catalog(locales, "fa", FA)
    on(monkeypatch, platform)
    assert i18n.set_language("fa") == "fa"
    assert i18n.current_direction() == "rtl"
    assert i18n.rtl_marks() is False
    assert i18n._("Save") == "ذخیره"


def test_the_isolates_are_never_emitted(fa_windows: None) -> None:
    texts = [i18n._(k) for k in FA if "{" not in k and "\x04" not in k]
    texts.append(i18n._("First line.\n\nSecond line: {n} files\n{path}", n=1, path="p"))
    assert texts and not any(ISOLATES & set(t) for t in texts)


# --- embed_rtl / plain as functions ------------------------------------------------------------------

def test_plain_removes_the_embedding_marks_only() -> None:
    marked = LRE + "a" + PDF + RLE + "ب" + PDF + LRO + "c" + RLO + "d" + PDF
    assert i18n.plain(marked) == "aبcd"
    # Marks plain() does not own stay: RLM, LRM and the isolates (never emitted here).
    other = RLM + "x" + LRM + chr(0x2067) + "y" + chr(0x2069)
    assert i18n.plain(other) == other


def test_plain_of_the_marked_text_is_the_catalog_text(fa_windows: None) -> None:
    assert i18n.plain(i18n._("Saved {name}", name="report.txt")) == "report.txt ذخیره شد"
    assert i18n.plain(i18n._("First line.\n\nSecond line: {n} files\n{path}", n=2, path="p")) == \
        "خط اول.\n\nخط دوم: 2 فایل\np"


hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

PIECES = list("ab Z09.:()،؟«»-\n\r\t ") + ["ذ", "خیره", "ש", "۳", chr(0x200C), RLM, LRM]
TEXTS = st.lists(st.sampled_from(PIECES), max_size=30).map("".join)


def _depth_ok(line: str) -> bool:
    depth = 0
    for ch in line:
        if ch == RLE:
            depth += 1
        elif ch == PDF:
            depth -= 1
            if depth < 0:
                return False
        elif unicodedata.bidirectional(ch) in ("R", "AL") and depth == 0:
            return False
    return depth == 0


@given(TEXTS)
def test_property_round_trip_idempotence_and_coverage(text: str) -> None:
    out = i18n.embed_rtl(text)
    assert i18n.plain(out) == text  # nothing lost, nothing reordered
    assert i18n.embed_rtl(out) == out  # idempotent
    assert out.count("\n") == text.count("\n")
    assert not (ISOLATES & set(out))
    for line in out.split("\n"):
        assert _depth_ok(line), repr(line)  # every right-to-left letter inside a pair
        if not any(unicodedata.bidirectional(c) in ("R", "AL") for c in line):
            assert RLE not in line and PDF not in line
    assert out.strip() == i18n.embed_rtl(text.strip())


def test_a_line_of_two_wrapped_values_with_text_between_is_wrapped_as_a_whole() -> None:
    # "{a} ب {c}" filled with two translated values: starts with RLE and ends with PDF, but the
    # middle letter is outside both pairs, so the whole line still needs its own pair.
    line = RLE + "الف" + PDF + " ب " + RLE + "ج" + PDF
    assert i18n.embed_rtl(line) == RLE + line + PDF
    assert i18n.embed_rtl(RLE + line + PDF) == RLE + line + PDF


@given(TEXTS, TEXTS, TEXTS)
def test_property_filled_placeholders_keep_every_letter_inside_a_pair(a: str, b: str, c: str) -> None:
    line = (i18n.embed_rtl(a) + b + i18n.embed_rtl(c)).replace("\n", " ").replace("\r", " ")
    out = i18n.embed_rtl(line)
    assert _depth_ok(out), repr(out)
    assert i18n.plain(out) == i18n.plain(line)
    assert i18n.embed_rtl(out) == out



# --- R2 the platform gate ----------------------------------------------------------------------------

def test_rtl_is_ready_on_windows_only_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert i18n.RTL_LAYOUT_READY is None  # decided by the platform, not forced
    assert i18n.RTL_PLATFORMS == frozenset({"win32"})
    for platform, ready in (("win32", True), ("darwin", False), ("linux", False)):
        on(monkeypatch, platform)
        assert i18n.rtl_layout_ready() is ready, platform


@pytest.mark.parametrize("platform,listed", [
    ("win32", ["en", "de", "ar", "fa", "he"]), ("darwin", ["en", "de"]), ("linux", ["en", "de"]),
])
def test_picker_offers_rtl_catalogs_on_windows_only(locales: Path, monkeypatch: pytest.MonkeyPatch,
                                                    platform: str, listed: list[str]) -> None:
    for code in ("de", "ar", "fa", "he"):
        write_catalog(locales, code, {}, status="machine")
    on(monkeypatch, platform)
    assert [lang.code for lang in i18n.available_languages()] == listed


@pytest.mark.parametrize("platform,chosen", [("win32", "fa"), ("darwin", "en"), ("linux", "en")])
def test_auto_takes_a_reviewed_rtl_catalog_only_where_it_is_offered(
        locales: Path, monkeypatch: pytest.MonkeyPatch, platform: str, chosen: str) -> None:
    write_catalog(locales, "fa", FA, status="reviewed")
    on(monkeypatch, platform)
    statuses = i18n.catalog_statuses()
    assert i18n.resolve_language("auto", os_language="fa-IR", available=statuses) == chosen
    # An explicit code still loads it everywhere (translators checking their work).
    assert i18n.resolve_language("fa", os_language=None, available=statuses) == "fa"


def test_forcing_the_flag_wins_over_the_platform(locales: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_catalog(locales, "he", {}, status="reviewed")
    on(monkeypatch, "win32")
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", False)
    assert i18n.rtl_layout_ready() is False
    assert i18n.resolve_language("auto", os_language="he", available=i18n.catalog_statuses()) == "en"
    on(monkeypatch, "linux")
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    assert i18n.rtl_layout_ready() is True
    assert i18n.resolve_language("auto", os_language="he", available=i18n.catalog_statuses()) == "he"


# --- R3 texts that leave the screen -------------------------------------------------------------------

def test_app_log_writes_the_plain_text_to_the_log_file(fa_windows: None,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    from app.app import App

    log = logging.getLogger("test.rtl.ui")
    msg = i18n._("Saved {name}", name="report.txt")
    assert RLE in msg
    with caplog.at_level(logging.INFO, logger="test.rtl.ui"):
        App.log(SimpleNamespace(_ui_logger=log, txt=None), msg)  # type: ignore[arg-type]
    assert [r.getMessage() for r in caplog.records] == ["report.txt ذخیره شد"]


def test_a_lost_notice_is_logged_plain(fa_windows: None, monkeypatch: pytest.MonkeyPatch,
                                       caplog: pytest.LogCaptureFixture) -> None:
    import tkinter as tk

    from app.widgets import notice

    class _Gone:
        def post(self, *_a: Any) -> None:
            raise tk.TclError("window closing")

    monkeypatch.setattr(notice, "host_for", lambda _w: _Gone())
    with caplog.at_level(logging.INFO, logger=notice.logger.name):
        notice.notify(object(), i18n._("Save"))  # type: ignore[arg-type]
    assert any(r.getMessage().endswith(": ذخیره") for r in caplog.records)
    assert not any(RLE in r.getMessage() or PDF in r.getMessage() for r in caplog.records)


def test_viewer_notice_failure_is_logged_plain(fa_windows: None, monkeypatch: pytest.MonkeyPatch,
                                               caplog: pytest.LogCaptureFixture) -> None:
    from app.dialogs import transcript_viewer as tv

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no window")

    monkeypatch.setattr(tv, "notify", boom)
    with caplog.at_level(logging.WARNING, logger=tv.logger.name):
        tv.TranscriptViewer._notice_quietly(object(), i18n._("Save"), "info")  # type: ignore[arg-type]
    assert [r.getMessage() for r in caplog.records] == ["Could not show the notice: ذخیره"]


class _Clip:
    def __init__(self, data: str = "") -> None:
        self.data = data
        self.clip: list[str] = []

    def get(self, *_a: Any) -> str:
        return self.data

    def clipboard_clear(self) -> None:
        self.clip.clear()

    def clipboard_append(self, text: str) -> None:
        self.clip.append(text)


def test_console_copy_all_copies_plain_text(fa_windows: None) -> None:
    from app.widgets import console

    txt = _Clip("Started\n" + i18n._("Saved {name}", name="a.srt"))
    console._copy_all(txt)  # type: ignore[arg-type]
    assert txt.clip == ["Started\na.srt ذخیره شد"]


def test_network_log_copy_is_plain_text(fa_windows: None) -> None:
    from app.widgets.offline_status import NetworkLogWindow

    win = _Clip()
    win.content = lambda: i18n._("Save") + "\n  12:00  " + i18n._("Interface language:")  # type: ignore[attr-defined]
    NetworkLogWindow.copy_all(win)  # type: ignore[arg-type]
    assert win.clip == ["ذخیره\n  12:00  زبان رابط:"]
