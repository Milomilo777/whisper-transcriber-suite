"""Translation wave 4: the main tabs (app/widgets/tabs.py) and the Live tab (app/widgets/live_tab.py).

``capture_all`` builds the Transcribe, Queue, Download, Web / LAN and Live tabs on a real (hidden)
Tk root with a stub app, drives the Live tab through its states (loading, listening, no signal,
draining, stopped, failures, saving, the exit question, the English-only hints) and collects
every text a person can see: widget texts, combobox values and current choices, menu entries,
list headings, hover help, status-line writes, error dialogs and message boxes.

The fixture ``tests/fixtures/i18n/i18n_wave_4_en.json`` was captured from the files BEFORE their
strings went through the translation layer (run with ``WTS_CAPTURE_I18N=1``, or with a file
``i18n_wave_4_en.capture`` next to it, to write it again).
In English the texts must stay byte-identical; in the pseudo-locale every text the two files own
must be marked. Values that are stored or compared in English stay English (checked below).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any, Callable

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from app import i18n  # noqa: E402
from app.widgets import live_tab, tabs  # noqa: E402
from tests.app.i18n_walk import is_pseudo_marked, visible_texts  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_4_en.json"
CAPTURE_ENV = "WTS_CAPTURE_I18N"
# Same as the environment variable, for runners that cannot pass one: an (untracked) file here.
CAPTURE_MARKER = FIXTURE.with_suffix(".capture")

Rows = list[list[str]]

# Fixed engine rows: the real list depends on what this machine has installed.
_ENGINES = [
    types.SimpleNamespace(display_label="Faster-Whisper (offline)", value="faster_whisper", ready=True),
    types.SimpleNamespace(display_label="Cloud engine  ⚠ unavailable", value="cloud", ready=False),
]
_ENGINE_SUMMARY = "ENGINE SUMMARY"
# The video-site feature stays English-only (never translated, never in a catalog).
_VIDEO_SITE_TEXTS = {
    "Download all parts of this series (SMTV)",
    "This episode has multiple parts on the source site. Checking this queues every part, "
    "not just the one you pasted.",
}


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover - no display
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo():
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    yield
    i18n.set_language("en")


# ----------------------------------------------------------------- recording helpers


def _noop(*_a: Any, **_k: Any) -> None:
    return None


class _Tips:
    """Hover help, section titles and device-badge hints recorded while a tab is built."""

    def __init__(self) -> None:
        self.rows: Rows = []

    def add(self, kind: str, text: Any) -> None:
        value = text() if callable(text) else text
        if value:
            self.rows.append([kind, str(value)])

    def take(self) -> Rows:
        out, self.rows = self.rows, []
        return out


def _patch_tooltips(mp: pytest.MonkeyPatch, tips: _Tips) -> None:
    from app.widgets import tooltip

    def help_icon(parent: Any, text: Any, **kw: Any) -> Any:
        tips.add("help", text)
        return tooltip.help_icon(parent, text, **kw)

    def bind_tooltip(widget: Any, text: Any, **kw: Any) -> None:
        tips.add("tooltip", text)
        tooltip.bind_tooltip(widget, text, **kw)

    def section_labelframe(parent: Any, title: str, help_text: str, **kw: Any) -> Any:
        tips.add("section", title)
        tips.add("help", help_text)
        return tooltip.section_labelframe(parent, title, help_text, **kw)

    for module in (tabs, live_tab):
        mp.setattr(module, "help_icon", help_icon)
        mp.setattr(module, "section_labelframe", section_labelframe)
    mp.setattr(tabs, "bind_tooltip", bind_tooltip)


def _walk(widget: tk.Misc) -> Rows:
    """i18n_walk.visible_texts plus the current choice of every combobox (shown in its field)."""
    rows = [[path, text] for path, text in visible_texts(widget)]

    def visit(w: tk.Misc) -> None:
        if w.winfo_class() == "TCombobox":
            current = str(w.get())  # type: ignore[attr-defined]
            if current.strip():
                rows.append([f"{w}:current", current])
        for child in w.winfo_children():
            visit(child)

    visit(widget)
    return rows


def _headings(tree: ttk.Treeview) -> Rows:
    return [[f"heading:{c}", str(tree.heading(c, "text"))] for c in tree.cget("columns")]


# ----------------------------------------------------------------- the main tabs


class _StubApp:
    """Just enough of App for the build_*_tab functions: unknown methods do nothing."""

    def __init__(self, root: tk.Tk) -> None:
        self.app_config: dict[str, Any] = {}
        self.device_badge_var = tk.StringVar(master=root, value="")
        self.status_var = tk.StringVar(master=root, value="")
        self.format_service = types.SimpleNamespace(schedule_lookup=_noop, poll=_noop)
        self.download_service = types.SimpleNamespace(
            enqueue_caption_only_from_form=_noop, poll=_noop)
        self.badge_hints: list[str] = []

    def register_device_badge_label(self, _label: Any, tier_label: str | None = None) -> None:
        if tier_label:
            self.badge_hints.append(tier_label)

    def after(self, *_a: Any, **_k: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return _noop


def _patch_main_tabs(mp: pytest.MonkeyPatch, *, diarization: str, sample: bool) -> None:
    import core
    from core import sample_clip
    from core.backends import availability

    mp.setattr(availability, "engine_options", lambda *_a, **_k: list(_ENGINES))
    mp.setattr(availability, "engine_status_summary", lambda *_a, **_k: _ENGINE_SUMMARY)
    mp.setattr(sample_clip, "bundled_clip_path", lambda: "sample.mp3" if sample else "")
    fake = types.ModuleType("core.diarization")
    if diarization == "broken":
        def _broken() -> bool:
            raise RuntimeError("no diarization here")
        fake.is_available = _broken  # type: ignore[attr-defined]
    else:
        fake.is_available = lambda: diarization == "ready"  # type: ignore[attr-defined]
    fake.availability_reason = lambda: "DIARIZATION REASON"  # type: ignore[attr-defined]
    mp.setitem(sys.modules, "core.diarization", fake)
    mp.setattr(core, "diarization", fake, raising=False)


def capture_main_tabs(mp: pytest.MonkeyPatch, root: tk.Tk) -> dict[str, Rows]:
    tips = _Tips()
    _patch_tooltips(mp, tips)
    states: dict[str, Rows] = {}

    def build(name: str, builder: Callable[[Any, Any], None], app: _StubApp) -> Any:
        frame = ttk.Frame(root)
        builder(app, frame)
        frame.pack()
        root.update_idletasks()
        states[name] = _walk(frame) + tips.take()
        return frame

    _patch_main_tabs(mp, diarization="broken", sample=True)
    app = _StubApp(root)
    build("transcribe", tabs.build_transcribe_tab, app)
    states["transcribe"] += [["badge", h] for h in app.badge_hints]

    _patch_main_tabs(mp, diarization="unavailable", sample=False)
    build("transcribe_no_sample_no_speakers", tabs.build_transcribe_tab, _StubApp(root))
    _patch_main_tabs(mp, diarization="ready", sample=False)
    build("transcribe_speakers_ready", tabs.build_transcribe_tab, _StubApp(root))

    app = _StubApp(root)
    build("queue", tabs.build_queue_tab, app)
    states["queue"] += _headings(app.tree)
    app = _StubApp(root)
    build("download", tabs.build_download_tab, app)
    states["download"] += _headings(app.download_tree)
    build("server", tabs.build_server_tab, _StubApp(root))

    pure: Rows = []
    for dnd in (False, True):
        for sample in (False, True):
            pure.append([f"headline dnd={dnd} sample={sample}", tabs.empty_state_headline(dnd, sample)])
    for status in list(tabs.STATUS_ICON) + ["unknown-status"]:
        pure.append([f"status {status}", tabs.status_label(status)])
    states["pure"] = pure
    return states


# ----------------------------------------------------------------- the Live tab


class _FakeThread:
    started: list["_FakeThread"] = []

    def __init__(self, target: Callable[[], Any], name: str = "", daemon: bool = False) -> None:
        self.target = target

    def start(self) -> None:
        _FakeThread.started.append(self)


class _Session:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.signal = "ok"
        self.pending = 0
        self.keep_recording = False

    def drain_events(self) -> list[Any]:
        out, self.events = self.events, []
        return out

    def capture_error(self) -> str:
        return ""

    def input_signal_state(self) -> str:
        return self.signal

    def pending_chunks(self) -> int:
        return self.pending

    def finish_recording(self) -> str:
        return ""

    stop = stop_capture = wait_drained = discard_pending = _noop


class _Transcriber:
    def __init__(self, running: bool = True) -> None:
        self.running = running

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        return None


def _live_app(root: tk.Tk) -> Any:
    a = types.SimpleNamespace()
    a.app_config = {}
    a.entry_file = "gui.py"
    a.logged = []
    a.log = a.logged.append
    a.queued = []
    a.post_to_main = a.queued.append
    a.afters = []
    a.after = lambda ms, fn=None: a.afters.append((ms, fn))
    a.clipboard_clear = root.clipboard_clear
    a.clipboard_append = root.clipboard_append
    return a


def _run_queued(app: Any) -> None:
    while app.queued:
        app.queued.pop(0)()


def _event(kind: str, text: str = "", detail: str = "") -> Any:
    return types.SimpleNamespace(kind=kind, text=text, detail=detail)


def capture_live(mp: pytest.MonkeyPatch, root: tk.Tk, tmp_path: Path) -> dict[str, Rows]:
    from core import live as _live
    from core import live_model as _lm
    from core import model_manager as _mm

    tips = _Tips()
    _patch_tooltips(mp, tips)
    mp.setattr(_live, "is_available", lambda mode="mic": True)
    mp.setattr(_live, "availability_reason", lambda mode="mic": "CORE AVAILABILITY REASON")
    mp.setattr(_live, "list_input_devices", lambda: [])
    mp.setattr(_mm, "model_downloaded", lambda cfg, slug: slug == "base")
    mp.setattr(_mm, "approx_download_size_text", lambda cfg, slug: "about 1 MB")
    mp.setattr("core.hardware.detect_device_for", lambda cfg: ("cpu", "int8"))
    mp.setattr(threading, "Thread", _FakeThread)
    dialogs: Rows = []

    def show_error(_parent: Any, title: str, message: str, detail: str | None = None) -> None:
        dialogs.append(["show_error.title", title])
        dialogs.append(["show_error.message", message])

    mp.setattr(live_tab, "show_error", show_error)

    def ask(title: str, message: str, **_k: Any) -> None:
        dialogs.append(["askyesnocancel.title", title])
        dialogs.append(["askyesnocancel.message", message])
        return None

    mp.setattr("tkinter.messagebox.askyesnocancel", ask)

    def ask_file(**kw: Any) -> str:
        dialogs.append(["asksaveasfilename.title", kw["title"]])
        for label, _pattern in kw["filetypes"]:
            dialogs.append(["asksaveasfilename.filetype", label])
        return str(tmp_path / "missing-folder" / "live.txt")

    mp.setattr(live_tab.filedialog, "asksaveasfilename", ask_file)

    states: dict[str, Rows] = {}
    app = _live_app(root)
    frame = ttk.Frame(root)
    live_tab.build_live_tab(app, frame)
    frame.pack()
    root.update_idletasks()
    states["live_built"] = _walk(frame) + tips.take()

    status: list[str] = []
    app.live_status_var.trace_add("write", lambda *_a: status.append(app.live_status_var.get()))
    buttons: Rows = []

    def snap_buttons(when: str) -> None:
        buttons.append([f"{when}: stop", str(app.live_stop_btn.cget("text"))])
        buttons.append([f"{when}: download", str(app.live_model_dl_btn.cget("text"))])
        buttons.append([f"{when}: download status", app.live_model_dl_var.get()])

    # Stop while the model loads, then the session starts and listens.
    live_tab._stop(app)
    app._live_cancel_pending = False
    session, transcriber = _Session(), _Transcriber()
    live_tab._started(app, transcriber, session)
    for signal in ("no_audio", "silent", "ok"):
        session.signal = signal
        live_tab._check_health(app)
    session.events = [_event("warning", detail="CORE WARNING"), _event("state", detail="started")]
    live_tab._poll_once(app)

    # First Stop drains, a second one discards the rest.
    live_tab._stop(app)
    snap_buttons("draining")
    for left in (1, 3):
        session.pending = left
        live_tab._poll_once(app)
    live_tab._stop(app)
    session.pending = 0
    live_tab._stopped(app, "")
    snap_buttons("stopped")
    app._live_stop_reason = "CORE STOP REASON"
    live_tab._stopped(app, "")

    # Failures while listening: a capture problem, the worker dying, repeated errors.
    def listen_again() -> _Session:
        s = _Session()
        app.live_session, app.live_transcriber = s, _Transcriber()
        app._live_draining, app._live_stop_reason, app._closing = False, "", False
        return s

    def run_afters() -> None:
        pending, app.afters = app.afters, []
        for ms, fn in pending:
            if ms == 0 and fn is not None:
                fn()

    listen_again()
    live_tab._fail_live(app, "CORE CAPTURE ERROR")
    run_afters()
    listen_again()
    app.live_transcriber = _Transcriber(running=False)
    live_tab._check_health(app)
    run_afters()
    s = listen_again()
    s.events = [_event("fatal", detail="CORE FATAL")]
    live_tab._poll_once(app)
    run_afters()

    # Start refused, start failed.
    app.live_session = app.live_transcriber = None
    app._live_draining = False
    mp.setattr(_live, "is_available", lambda mode="mic": False)
    live_tab._start(app)
    live_tab._start_failed(app, RuntimeError("CORE START ERROR"))

    # The model download button.
    app.live_model_var.set(next(label for label, value in live_tab._live_model_choices(app)
                                if value == "tiny"))
    live_tab._download_live_model(app)
    snap_buttons("downloading")
    live_tab._download_finished(app, "tiny", "CORE DOWNLOAD ERROR")
    snap_buttons("download failed")
    live_tab._download_finished(app, "tiny", None)
    snap_buttons("downloaded")

    # Saving: nothing to save, a folder that does not exist, the exit question.
    app.live_lines = []
    live_tab._save(app)
    app.live_lines = ["a line"]
    app._live_saved_count = 0
    live_tab._save(app)
    live_tab.save_before_exit(app)

    # The English-only hints (the reason line the dialog shows).
    reasons: Rows = []
    for lang in ("Auto", "German"):
        app.live_lang_var.set(lang)
        for alt_value, device in ((_lm.LIVE_MAIN, "cuda"), ("small", "cpu"), ("small", "cuda")):
            prompt = live_tab._english_only_prompt(app, "tiny.en", alt_value, "small", device)
            reasons.append([f"reason {lang} {alt_value} {device}", prompt.reason])

    # Falling back to the main model, and when that is refused.
    mp.setattr(_lm, "resolve_live_slug", lambda *_a, **_k: "tiny")
    mp.setattr(_lm, "live_model_config", lambda cfg, slug: {"whisper_model": slug})
    mp.setattr(_lm, "is_downloaded", lambda cfg: False)

    def ensure_ok(_cfg: Any, progress_cb: Any = None, **_k: Any) -> str:
        progress_cb({"percent": 50})
        return "path"

    mp.setattr(_mm, "ensure_model", ensure_ok)
    mp.setattr(_mm, "english_only_mismatch", lambda *_a, **_k: False)
    live_tab._prepare_live_model(app, "de")
    _run_queued(app)

    def ensure_fail(*_a: Any, **_k: Any) -> str:
        raise OSError("CORE OFFLINE")

    mp.setattr(_mm, "ensure_model", ensure_fail)
    mp.setattr(_mm, "english_only_mismatch", lambda *_a, **_k: True)
    refused: Rows = []
    for config in ({"whisper_model": "x"}, None):
        mp.setattr(_lm, "live_model_config", lambda cfg, slug, c=config: c)
        try:
            live_tab._prepare_live_model(app, "de")
        except RuntimeError as e:
            refused.append(["refused", str(e)])
    _run_queued(app)

    states["live_status"] = [["status", t] for t in status]
    states["live_buttons"] = buttons
    states["live_dialogs"] = dialogs
    states["live_reasons"] = reasons
    states["live_refused"] = refused
    states["live_menu_after"] = _walk(frame)
    return states


def capture_all(mp: pytest.MonkeyPatch, root: tk.Tk, tmp_path: Path) -> dict[str, Rows]:
    states = capture_main_tabs(mp, root)
    states.update(capture_live(mp, root, tmp_path))
    return states


# ----------------------------------------------------------------- tests


def test_english_texts_match_the_capture_made_before_translation(
        english: None, root: tk.Tk, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_all(monkeypatch, root, tmp_path)
    if os.environ.get(CAPTURE_ENV) == "1" or CAPTURE_MARKER.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(states, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert states == expected


def _outside_texts() -> dict[str, str]:
    """Texts the two files show but do not own, with the reason they stay untranslated here."""
    from app.domain.cookies import cookie_browser_choices
    from app.domain.languages import SUBTITLE_LANGUAGES
    from core.model_manager import catalog_models

    allowed: dict[str, str] = {}
    for engine in _ENGINES:
        allowed[engine.display_label] = "engine label from core/backends/availability.py"
    for _slug, label in catalog_models({}):
        allowed[label] = "model label from the core model catalog"
    for name, _code in SUBTITLE_LANGUAGES:
        allowed[name] = "language name from app/domain/languages.py"
    for choice in cookie_browser_choices(""):
        allowed[choice] = "cookie choice from app/domain/cookies.py"
    for text in _VIDEO_SITE_TEXTS:
        allowed[text] = "video-site feature: English only by design"
    allowed["mp4"] = "a file format id"
    allowed["CORE WARNING"] = "a warning the core live session sends"
    allowed["unknown-status"] = "a status value the table does not know is shown as it is"
    return allowed


def test_pseudo_locale_leaves_no_tab_text_untranslated(
        pseudo: None, root: tk.Tk, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_all(monkeypatch, root, tmp_path)
    allowed = _outside_texts()
    left = sorted({(name, text) for name, rows in states.items() for _w, text in rows
                   if text not in allowed and not is_pseudo_marked(text)})
    assert left == []
    # Placeholders keep the person's values inside the marked text.
    statuses = [t for _w, t in states["live_status"]]
    assert any("CORE STOP REASON" in t and t.startswith("[") for t in statuses)
    assert any("3" in t and t.startswith("[") for t in statuses)


def test_pseudo_locale_keeps_the_video_site_texts_english(
        pseudo: None, root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    states = capture_main_tabs(monkeypatch, root)
    texts = {t for _w, t in states["download"]}
    assert _VIDEO_SITE_TEXTS <= texts


def test_headline_and_status_words_are_whole_translated_texts(pseudo: None) -> None:
    for dnd in (False, True):
        for sample in (False, True):
            assert is_pseudo_marked(tabs.empty_state_headline(dnd, sample))
    for status, icon in tabs.STATUS_ICON.items():
        shown = tabs.status_label(status)
        assert shown.startswith(icon) and is_pseudo_marked(shown[len(icon):])
    assert tabs.status_label("unknown-status") == "unknown-status"


# ----------------------------------------------------------------- stored values stay English


def _stored_values(mp: pytest.MonkeyPatch, root: tk.Tk) -> dict[str, Any]:
    """Pick choices by position (the same in every language) and return what gets stored."""
    from core import live as _live
    from core import model_manager as _mm

    _patch_main_tabs(mp, diarization="ready", sample=False)
    mp.setattr(_live, "is_available", lambda mode="mic": True)
    mp.setattr(_live, "list_input_devices", lambda: [])
    mp.setattr(_mm, "model_downloaded", lambda cfg, slug: True)
    saved: list[dict[str, Any]] = []
    mp.setattr("core.config.save_config", lambda cfg: saved.append(dict(cfg)))
    out: dict[str, Any] = {}

    app = _StubApp(root)
    frame = ttk.Frame(root)
    tabs.build_transcribe_tab(app, frame)
    combos = [w for w in _descendants(frame) if w.winfo_class() == "TCombobox"]
    lang_combo, speakers_combo = combos[2], combos[3]
    lang_combo.current(3)
    out["language after a name"] = app.transcribe_lang_var.get()
    lang_combo.current(0)
    out["language after Auto"] = app.transcribe_lang_var.get()
    speakers_combo.current(4)
    out["speakers after a count"] = app.diarization_speakers_var.get()
    speakers_combo.current(0)
    out["speakers after Auto"] = app.diarization_speakers_var.get()
    app.transcribe_lang_var.set("German")
    out["language combo shows a set name"] = lang_combo.current()  # the label is translated

    app = _StubApp(root)
    frame = ttk.Frame(root)
    tabs.build_download_tab(app, frame)
    app.download_mode_combo.current(1)
    out["mode after the second choice"] = app.download_mode_var.get()
    app.download_mode_combo.current(0)
    out["mode after the first choice"] = app.download_mode_var.get()
    app.download_mode_var.set("Audio")  # what the video-site tab does
    out["mode combo follows a stored value"] = app.download_mode_combo.current()
    # The Subtitles language: the English name is stored (and saved as download_subtitle_lang).
    app.subtitle_lang_combo.current(5)
    out["subtitle language after a name"] = app.subtitle_lang_var.get()
    app.subtitle_lang_combo.current(0)
    out["subtitle language after Automatic"] = app.subtitle_lang_var.get()
    app.subtitle_lang_var.set("German")
    out["subtitle combo follows a stored name"] = app.subtitle_lang_combo.current()

    live = _live_app(root)
    frame = ttk.Frame(root)
    live_tab.build_live_tab(live, frame)
    for index in (0, 1, 3):
        live.live_model_menu.invoke(index)
        out[f"live model entry {index}"] = live.app_config.get("live_model")
    out["live saved configs"] = [c.get("live_model") for c in saved]
    live.live_source_combo.current(1)
    live.live_source_combo.event_generate("<<ComboboxSelected>>")
    root.update()
    out["live source after the second choice"] = live.live_source_var.get()
    out["live device combo disabled for system audio"] = str(live.live_device_combo.cget("state"))
    live.live_source_combo.current(0)
    out["live source after the first choice"] = live.live_source_var.get()
    live.live_lang_combo.current(0)
    out["live language after Auto"] = (live.live_lang_var.get(),
                                       live_tab._selected_language_code(live))
    live.live_lang_combo.current(5)
    out["live language after a name"] = (live.live_lang_var.get(),
                                         live_tab._selected_language_code(live))
    live.live_device_combo.current(0)
    out["live default device"] = live_tab._selected_device_index(live)
    return out


def _descendants(w: tk.Misc) -> list[tk.Misc]:
    out: list[tk.Misc] = []
    for child in w.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


def test_choices_store_the_same_values_in_every_language(
        root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    i18n.set_language("en")
    try:
        english = _stored_values(monkeypatch, root)
        i18n.set_language(i18n.PSEUDO_LOCALE)
        pseudo_values = _stored_values(monkeypatch, root)
    finally:
        i18n.set_language("en")
    assert pseudo_values == english
    assert english["language after Auto"] == "Auto"
    assert english["speakers after Auto"] == "Auto"
    assert english["mode after the second choice"] == "Audio"
    assert english["mode combo follows a stored value"] == 1
    assert english["live model entry 0"] == "auto" and english["live model entry 1"] == "main"
    assert english["live source after the second choice"] == live_tab._SOURCE_SYSTEM
    assert english["live device combo disabled for system audio"] == "disabled"
    assert english["live language after Auto"] == ("Auto", None)
    from app.domain.languages import SUBTITLE_LANGUAGES
    assert english["language after a name"] == SUBTITLE_LANGUAGES[2][0]
    assert english["live language after a name"][0] in {n for n, _c in SUBTITLE_LANGUAGES}
    assert english["subtitle language after a name"] == SUBTITLE_LANGUAGES[5][0]
    assert english["subtitle language after Automatic"] == "Automatic"
    names = [n for n, _c in SUBTITLE_LANGUAGES]
    assert english["subtitle combo follows a stored name"] == names.index("German")
    assert english["live default device"] is None
