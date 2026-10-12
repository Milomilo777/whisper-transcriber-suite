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
has them (no reordering, no added marks off macOS), and the language picker does not offer the
right-to-left catalog while ``app.i18n.RTL_LAYOUT_READY`` is False.

These tests need a real Tk root; run them on the remote test machine (see AGENTS.md).
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import pytest

from app import i18n

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
    # Exactly the catalog's text, character for character (Tk on Windows and Linux does not
    # reorder; nothing adds a direction mark off macOS).
    tabs = {str(app.nb.tab(t, "text")) for t in app.nb.tabs()}
    expected = {messages["Transcription Queue"], messages["Download Videos"],
                messages["Web / LAN access"], messages["tab" + i18n.CONTEXT_SEPARATOR + "Live"]}
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

    dlg = AdvancedDialog(app)
    try:
        values = list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))
        assert values[1:] == ["English"], values
        assert values[0].startswith(HEBREW_MARK)
    finally:
        dlg.destroy()
    monkeypatch.setattr(i18n, "RTL_LAYOUT_READY", True)
    dlg = AdvancedDialog(app)
    try:
        values = list(dlg.tk.splitlist(dlg._ui_language_combo.cget("values")))
        assert values[1] == "English"
        # "{language} (machine translation)" as the test catalog has it.
        assert values[2].endswith(HEBREW_MARK + "עברית (machine translation)"), values
    finally:
        dlg.destroy()
