"""The whole app in the pseudo-locale and in a right-to-left test catalog (needs a display).

``test_tk_*_pseudo_*`` builds the real main window (``app.app.App``) with the config, the
network and the blocking calls replaced, under ``qps-ploc``: every tab, the menus, the bars
above the tabs and every dialog the menus and buttons open without real data (About, Report a
problem, Statistics, Search, Advanced settings, the model advisor, Quick start). Every visible
text (``tests.app.i18n_walk.untranslated``) and every message box must carry the pseudo marker,
except the short list in ``ALLOWED`` (each with its reason) and the video-site tab, which is
English-only by design and allowed as a whole.

``test_tk_rtl_*`` does the same with a Hebrew test catalog (every message prefixed with a Hebrew
letter): the layer switches to right to left, the texts reach the widgets exactly as the catalog
has them (no reordering; on Windows each line inside one RLE ... PDF pair, no LRM off macOS),
and the language picker does not offer the right-to-left catalog while
``app.i18n.rtl_layout_ready()`` is False.

``test_tk_persian_*`` (Windows) builds the app with a small Persian catalog: every right-to-left
letter on screen sits inside a direction-mark pair, translated combobox labels still map back to
the stored English values, and the error dialog copies its details without the marks.

These tests need a real Tk root; run them on the remote test machine (see AGENTS.md).
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import pytest

from app import i18n, rtl_shaping

# Texts the app shows that do not go through the translation layer, with the reason.
ALLOWED: dict[str, str] = {
    "Download all parts of this series (SMTV)": "the video-site option on the Download tab "
                                                "(English-only by design)",
}
# Texts allowed because they are values from core/, names or the person's data, computed at run
# time by _dynamic_allowed / _allowed_shape. core/ is not translated; the ones a person reads as
# sentences are listed for a later change in docs/TRANSLATING.md ("Not translated yet").
ALLOWED_KINDS = {
    "engine labels": "the Engine pickers show core.backends.availability labels, with its "
                     "UNAVAILABLE_MARK for a blocked engine (core/)",
    "model labels": "the Whisper model pickers show the core model catalog's labels; Quick start "
                    "lists a model's short name before its translated details",
    "voices": "the Text to Voice voice picker shows core.tts_kokoro's voice labels (core/)",
    "update bar": "core.updates.bar_text builds the new-version line (core/)",
    "cloud usage": "core.backends.google_cloud_stt.format_usage builds the usage line (core/)",
    "language names": "the interface-language picker shows each language by its own name",
    "browser ids": "the cookies pickers list browser ids (chrome, edge, ...)",
    "format ids": "output format ids and product names (SRT, mp4, Express Scribe, ...)",
    "video-site export": "the video-site team's export label stays English-only",
    "product name": "the window title and About header carry the product name",
    "urls": "a link shows the URL itself",
    "audio devices": "the Live tab lists the system's audio devices by number and name",
}

HEBREW_MARK = "א "  # HEBREW LETTER ALEF and a space in front of every test translation
CORE_USAGE = "«core usage line»"
UPDATE_INFO = SimpleNamespace(latest_tag="v9.9.9", headline="Faster start")
CONTAINERS = {"mp4", "mkv", "webm", "mp3", "m4a", "opus", "wav", "flac", "ogg", "aac"}


def _dynamic_allowed() -> set[str]:
    from app.app import _APP_VERSION
    from app.dialogs import advanced as adv
    from app.dialogs import ui_language
    from app.domain.cookies import cookie_browser_choices
    from core import tts_kokoro, updates
    from core.backends.availability import ENGINE_CHOICES, UNAVAILABLE_MARK
    from core.model_manager import catalog_models
    from core.writers import supported_formats

    texts = {label for label, _value in ENGINE_CHOICES}
    texts |= {label + UNAVAILABLE_MARK for label, _value in ENGINE_CHOICES}
    texts |= {label for _slug, label in catalog_models({})}
    texts |= {voice.label for voice in tts_kokoro.VOICES}
    texts.add(updates.bar_text(UPDATE_INFO.latest_tag, _APP_VERSION, UPDATE_INFO.headline))
    texts.add(CORE_USAGE)
    texts |= {lang.endonym for lang in i18n.SUPPORTED_LANGUAGES}
    # Linux with arabic-reshaper and python-bidi: the same names, display-shaped (ltr_base).
    texts |= {rtl_shaping.visual(lang.endonym, base="L") for lang in i18n.SUPPORTED_LANGUAGES}
    texts.add(ui_language.button_text())  # the language button: the running language's own name
    texts |= set(cookie_browser_choices("")[1:])
    texts |= {name.upper() for name in supported_formats() if name not in adv._FORMAT_LABELS}
    texts |= {adv._FORMAT_LABELS[n] for n in adv._UNTRANSLATED_FORMAT_LABELS}
    texts |= {adv._FORMAT_HELP["smtv_docx"]}
    texts |= CONTAINERS
    return texts


def _model_short_names() -> set[str]:
    from app.dialogs.quick_start import short_model_name
    from core.model_manager import catalog_models

    return {short_model_name({}, slug) for slug, _label in catalog_models({})}


def _allowed_shape(text: str, rest: str) -> bool:
    """Allowed by its shape: the product name, a URL, an audio device, a model's short name
    followed by translated details (``rest`` is what is left outside the marker)."""
    import re

    if text.startswith(("Whisper Transcriber Suite", "https://")):
        return True
    if re.match(r"\d+: \S", text):  # "3: Microphone Array (Realtek ...)"
        return True
    return rest.replace("·", " ").strip() in _model_short_names()


class _Recorder:
    def __init__(self) -> None:
        self.boxes: list[tuple[str, str, str]] = []


def _all_toplevels(root: tk.Misc) -> list[tk.Misc]:
    out: list[tk.Misc] = []

    def visit(w: tk.Misc) -> None:
        for child in w.winfo_children():
            if isinstance(child, tk.Toplevel):
                out.append(child)
            visit(child)

    visit(root)
    return out


@pytest.fixture
def build_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Returns a function that builds the real App in the current interface language."""
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as e:
        pytest.skip(f"Tk unavailable: {e}")
    from tkinter import filedialog, messagebox

    from core.config import DEFAULT_CONFIG

    recorder = _Recorder()
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                 "askyesnocancel", "askretrycancel", "askquestion"):
        def box(title: Any = "", message: Any = "", *_a: Any, _kind: str = name, **_k: Any) -> Any:
            recorder.boxes.append((_kind, str(title), str(message)))
            return False
        monkeypatch.setattr(messagebox, name, box)
    for name in ("askopenfilename", "askopenfilenames", "asksaveasfilename", "askdirectory"):
        monkeypatch.setattr(filedialog, name, lambda *_a, **_k: "")
    monkeypatch.setattr(tk.Misc, "wait_window", lambda *_a, **_k: None)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *_a, **_k: True)
    # The search dialog starts a reindex thread that holds the dialog (and so
    # the App) alive; a real reindex can outlive the test and release the
    # destroyed root on that worker thread, where GC freeing it aborts Tcl.
    monkeypatch.setattr("core.search.reindex_all_history", lambda: 0)
    monkeypatch.setattr("app.app.voice_clone_tab_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr("core.backends.google_cloud_stt.format_usage", lambda *_a, **_k: CORE_USAGE)

    made: list[Any] = []

    def build(**cfg_overrides: Any) -> Any:
        from app.app import App

        cfg = dict(DEFAULT_CONFIG)
        cfg.update(cfg_overrides)
        with patch("core.config.user_config_dir", return_value=tmp_path / "c"), \
             patch("core.config.user_data_dir", return_value=tmp_path / "d"), \
             patch("core.config.user_cache_dir", return_value=tmp_path / "k"), \
             patch("core.stats.post_stats_async", return_value=False), \
             patch("app.app.load_config", return_value=cfg), \
             patch("app.app.save_config"):
            app = App()
        app.withdraw()
        made.append(app)
        return app

    build.recorder = recorder  # type: ignore[attr-defined]
    try:
        yield build
    finally:
        for app in made:
            try:
                app.destroy()
            except tk.TclError:
                pass
        i18n.set_language("en")


def _openers(app: Any) -> list[tuple[str, Callable[[], Any]]]:
    from app.dialogs.quick_start import QuickStartDialog

    return [
        ("about", app._show_about),
        ("report a problem", lambda: app._open_problem_report(app)),
        ("statistics", app.show_statistics),
        ("search", app._open_search_dialog),
        ("advanced", app.open_advanced_dialog),
        ("model advisor", app.open_model_advisor),
        ("quick start", lambda: QuickStartDialog(app, app.app_config, on_done=lambda _c: None)),
    ]


def _collect(app: Any) -> list[tuple[str, str, str]]:
    """(state, widget path, text) for the main window, its bars and every dialog."""
    from tests.app.i18n_walk import visible_texts

    rows: list[tuple[str, str, str]] = []
    populate = getattr(app, "_populate_recent_menu", None)
    if callable(populate):
        populate()
    app._show_update_bar(UPDATE_INFO)
    app._show_star_bar()
    app.update_idletasks()
    rows += [("main window", path, text) for path, text in visible_texts(app)]
    for state, opener in _openers(app):
        before = set(map(str, _all_toplevels(app)))
        opener()
        app.update_idletasks()
        new = [w for w in _all_toplevels(app) if str(w) not in before]
        assert new, f"{state}: no window opened"
        for window in new:
            rows += [(state, path, text) for path, text in visible_texts(window)]
        for window in new:
            try:
                window.destroy()
            except tk.TclError:
                pass
    return rows


def _video_site(app: Any, path: str) -> bool:
    tab = str(app.t8)
    return path == tab or path.startswith(tab + ".") or path == f"{app.nb}:{tab}"


def _left_over(app: Any, rows: list[tuple[str, str, str]], marked: Callable[[str], bool],
               recorder: _Recorder, rest: Callable[[str], str] = lambda t: t) -> list[str]:
    allowed = set(ALLOWED) | _dynamic_allowed()
    left = sorted({f"{state} | {path} | {text!r}" for state, path, text in rows
                   if not marked(text) and text not in allowed
                   and not _allowed_shape(text, rest(text)) and not _video_site(app, path)})
    left += [f"message box {kind} | {title!r} | {message!r}"
             for kind, title, message in recorder.boxes
             if not (marked(title) and marked(message))]
    return left


def test_tk_whole_app_pseudo_leaves_no_text_untranslated(build_app: Any) -> None:
    from tests.app.i18n_walk import is_pseudo_marked, unmarked_rest

    i18n.set_language(i18n.PSEUDO_LOCALE)
    app = build_app()
    rows = _collect(app)
    states = {state for state, _p, _t in rows}
    assert {"main window", "about", "advanced", "statistics"} <= states
    # The walk saw every tab and the menus (a guard against walking an empty window).
    tab_texts = [t for _s, p, t in rows if p.startswith(f"{app.nb}:")]
    assert len(tab_texts) >= 7, tab_texts
    assert any("#" in p for _s, p, _t in rows), "no menu entries collected"
    left = _left_over(app, rows, is_pseudo_marked, build_app.recorder, unmarked_rest)
    if left:
        pytest.fail(f"{len(left)} texts without the pseudo marker:\n" + "\n".join(left))


def test_tk_whole_app_english_is_unmarked(build_app: Any) -> None:
    """The control: in English the same walk reports (nearly) everything, so it does look."""
    from tests.app.i18n_walk import is_pseudo_marked

    i18n.set_language("en")
    app = build_app()
    rows = _collect(app)
    left = _left_over(app, rows, is_pseudo_marked, build_app.recorder)
    assert len(left) > 200, len(left)


def test_star_lines_are_the_english_of_core() -> None:
    """app.app marks core.star_invite's two lines for the catalog; they must stay the same text."""
    from app import app as app_mod
    from core import star_invite

    assert app_mod._STAR_ABOUT_LINE == star_invite.ABOUT_LINE
    assert app_mod._STAR_BAR_TEXT == star_invite.BAR_TEXT


# --- right to left -------------------------------------------------------------------------------

def _hebrew_catalog(folder: Path) -> dict[str, Any]:
    """A he.json whose every message is the English text after a Hebrew letter and a space."""
    source = json.loads((Path(__file__).resolve().parents[2] / "app" / "locales" / "en.json")
                        .read_text(encoding="utf-8"))
    nforms = i18n.PLURAL_RULES["he"][0]
    messages: dict[str, Any] = {}
    for key, value in source["messages"].items():
        if isinstance(value, list):
            one, other = value[0], value[-1]
            messages[key] = [HEBREW_MARK + one] + [HEBREW_MARK + other] * (nforms - 1)
        else:
            messages[key] = HEBREW_MARK + value
    doc = {"_meta": {"code": "he", "name": "עברית", "direction": "rtl", "status": "machine",
                     "plural": "he"}, "messages": messages}
    (folder / "he.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return messages


def _hebrew_marked(text: str) -> bool:
    return HEBREW_MARK.strip() in text or not any(c.isalpha() for c in text)


def test_tk_rtl_catalog_reaches_the_widgets_unchanged(build_app: Any, monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    from app.theme import bidi_display

    folder = tmp_path / "locales"
    folder.mkdir()
    messages = _hebrew_catalog(folder)
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    assert i18n.set_language("he") == "he"
    assert i18n.current_direction() == "rtl"
    app = build_app()
    # The catalog's text, character for character; on Windows each line inside one RLE ... PDF
    # pair (U+202B ... U+202C), on Linux with the display shaping (app.rtl_shaping) in visual
    # order, elsewhere unchanged. Tk does not reorder, and no LRM is added off macOS.
    marks = (chr(0x202B), chr(0x202C)) if sys.platform == "win32" else ("", "")

    def shown(text: str) -> str:
        from app import rtl_shaping
        return rtl_shaping.visual(text) if i18n.rtl_shaped() else marks[0] + text + marks[1]

    tabs = {str(app.nb.tab(t, "text")) for t in app.nb.tabs()}
    expected = {shown(messages[key]) for key in (
        "Transcription Queue", "Download Videos", "Web / LAN access",
        "tab" + i18n.CONTEXT_SEPARATOR + "Live")}
    assert expected <= tabs, tabs
    if not bidi_display.is_aqua():
        rows = _collect(app)
        bad = [t for _s, _p, t in rows if bidi_display.LRM in t]
        assert bad == []
        left = _left_over(app, rows, _hebrew_marked, build_app.recorder)
        if left:
            pytest.fail(f"{len(left)} texts without the test translation:\n" + "\n".join(left))


def test_tk_rtl_catalog_is_not_offered_until_the_layout_is_mirrored(
        build_app: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "locales"
    folder.mkdir()
    _hebrew_catalog(folder)
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    i18n.set_language("he")
    app = build_app()
    from app.dialogs.advanced import AdvancedDialog

    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", False)
    dlg = AdvancedDialog(app)
    try:
        values = list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))
        assert values[1:] == ["English"], values
        assert i18n.plain(values[0]).startswith(HEBREW_MARK)
    finally:
        dlg.destroy()
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    dlg = AdvancedDialog(app)
    try:
        values = list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))
        assert values[1] == "English"
        # The language name stands alone: no "(machine translation)" note next to it.
        assert i18n.plain(values[2]) == "עברית", values
    finally:
        dlg.destroy()


# --- right to left on Windows: the direction marks ------------------------------------------------

RLE_MARK = chr(0x202B)
PDF_MARK = chr(0x202C)
ISOLATE_MARKS = {chr(c) for c in range(0x2066, 0x206A)}
SEP = i18n.CONTEXT_SEPARATOR
# A small Persian catalog: a few texts of the main window and of Advanced settings, mixed with
# Latin and digits and ending in ":" or ")" like the texts that came out wrong without the marks.
PERSIAN = {
    "Transcription Queue": "صف رونویسی",
    "Download Videos": "دانلود ویدیو",
    "Web / LAN access": "دسترسی Web / LAN",
    "tab" + SEP + "Live": "زنده",
    "download mode" + SEP + "Audio and video": "صدا و ویدیو (MP4)",
    "download mode" + SEP + "Audio": "فقط صدا",
    "Advanced settings": "تنظیمات پیشرفته",
    "App behaviour": "رفتار برنامه",
    "Interface language:": "زبان رابط:",
    "Automatic (system language)": "خودکار (زبان سیستم)",
}


def _rtl_letter(ch: str) -> bool:
    import unicodedata

    return unicodedata.bidirectional(ch) in ("R", "AL")


def _unembedded(text: str) -> list[str]:
    """Problems of one shown text: a right-to-left letter outside RLE ... PDF, unbalanced pairs,
    a pair around a line without a right-to-left letter, an isolate mark."""
    problems: list[str] = []
    if ISOLATE_MARKS & set(text):
        problems.append("isolate mark")
    for line in text.split("\n"):
        depth = 0
        for ch in line:
            if ch == RLE_MARK:
                depth += 1
            elif ch == PDF_MARK:
                depth -= 1
                if depth < 0:
                    problems.append("PDF without RLE")
                    break
            elif _rtl_letter(ch) and depth == 0:
                problems.append(f"letter {ch!r} outside the marks")
                break
        if depth > 0:
            problems.append("RLE not closed")
        if (RLE_MARK in line or PDF_MARK in line) and not any(_rtl_letter(c) for c in line):
            problems.append("marks around a left-to-right line")
    return problems


@pytest.mark.skipif(sys.platform != "win32", reason="the marks are added on Windows only")
def test_tk_persian_catalog_marks_every_translated_line(
        build_app: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "locales"
    folder.mkdir()
    doc = {"_meta": {"code": "fa", "name": "فارسی", "direction": "rtl", "status": "machine",
                     "plural": "zero_one_other"}, "messages": PERSIAN}
    (folder / "fa.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "locales_dir", lambda: folder)
    monkeypatch.setattr(i18n, "_DOC_CACHE", {})
    assert i18n.set_language("fa") == "fa"
    assert i18n.rtl_marks() is True
    app = build_app()

    # The tabs: exactly the catalog text inside one pair.
    tabs = {str(app.nb.tab(t, "text")) for t in app.nb.tabs()}
    for key in ("Transcription Queue", "Download Videos", "Web / LAN access", "tab" + SEP + "Live"):
        assert RLE_MARK + PERSIAN[key] + PDF_MARK in tabs, (key, tabs)
    # A tab the small catalog does not translate stays English, without marks.
    assert any(RLE_MARK not in t and PDF_MARK not in t for t in tabs), tabs

    # A translated combobox label still maps back to the stored English value through Tk.
    values = list(app.tk.splitlist(app.download_mode_combo.cget("values")))
    assert values == [RLE_MARK + PERSIAN["download mode" + SEP + "Audio and video"] + PDF_MARK,
                      RLE_MARK + PERSIAN["download mode" + SEP + "Audio"] + PDF_MARK]
    app.download_mode_combo.set(values[1])
    app.update_idletasks()
    assert app.download_mode_var.get() == "Audio"
    app.download_mode_combo.set(values[0])
    app.update_idletasks()
    assert app.download_mode_var.get() == "Audio and video"

    # Advanced settings: the picker row and its value <-> label map.
    from app.dialogs.advanced import AdvancedDialog

    dlg = AdvancedDialog(app)
    try:
        dlg.update_idletasks()
        assert str(dlg.title()) == RLE_MARK + PERSIAN["Advanced settings"] + PDF_MARK
        from tests.app.i18n_walk import visible_texts

        shown = [t for _p, t in visible_texts(dlg)]
        assert RLE_MARK + PERSIAN["Interface language:"] + PDF_MARK in shown
        assert RLE_MARK + PERSIAN["App behaviour"] + PDF_MARK in shown
        picker = list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))
        assert picker[0] == RLE_MARK + PERSIAN["Automatic (system language)"] + PDF_MARK
        assert "فارسی" in picker, picker
        assert dlg._ui_language_value(dlg._ui_language_display.get()) == "auto"
        assert dlg._ui_language_value(picker[0]) == "auto"
    finally:
        dlg.destroy()

    # The whole app and its dialogs: every right-to-left letter inside a pair, no isolates,
    # and the app did not fail building any of it.
    rows = _collect(app)
    # Language names (the picker lists each by its own name) and the English-only video-site
    # tab are data, not translations.
    from app.dialogs import ui_language

    names = {lang.endonym for lang in i18n.SUPPORTED_LANGUAGES} | {ui_language.button_text()}
    names |= {rtl_shaping.visual(lang.endonym, base="L") for lang in i18n.SUPPORTED_LANGUAGES}
    bad = sorted({f"{state} | {path} | {text!r}: {', '.join(p)}" for state, path, text in rows
                  if text not in names and not _video_site(app, path)
                  for p in [_unembedded(text)] if p})
    if bad:
        pytest.fail(f"{len(bad)} texts with misplaced direction marks:\n" + "\n".join(bad))
    persian_rows = [t for _s, _p, t in rows if any(_rtl_letter(c) for c in t)]
    assert len(persian_rows) >= 6, persian_rows
    # Negative control: the same texts without their marks are all reported.
    assert all(_unembedded(i18n.plain(t)) for t in persian_rows if RLE_MARK in t)


def test_tk_error_details_are_copied_without_marks() -> None:
    from tkinter import ttk

    from app.widgets.error_dialog import show_error

    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk unavailable: {e}")
    root.withdraw()
    try:
        detail = RLE_MARK + "خطا: disk full" + PDF_MARK
        show_error(root, "t", "m", detail=detail)
        root.update_idletasks()

        def find(widget: tk.Misc) -> Any:
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button) and i18n.plain(str(child.cget("text"))) == "Copy details":
                    return child
                found = find(child)
                if found is not None:
                    return found
            return None

        button = find(root)
        assert button is not None
        button.invoke()
        try:
            copied = root.clipboard_get()
        except tk.TclError as e:
            pytest.skip(f"no clipboard on this desktop: {e}")
        assert copied == "خطا: disk full"
    finally:
        root.destroy()
