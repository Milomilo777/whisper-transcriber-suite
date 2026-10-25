"""The main window (app/app.py): its texts stay byte-identical in English and all go through
the translation layer (app/i18n.py).

The fixture ``tests/fixtures/i18n/i18n_wave_7_en.json`` was captured from app/app.py BEFORE its
strings went through the layer. It has two parts:

* ``windowless``: texts the App methods hand to message boxes, notices, error dialogs, status
  lines, button texts, the window title and the hover texts, driven on a stand-in object with
  ``tkinter.messagebox`` and friends replaced. No Tk root is created (a guard makes sure).
* ``tk``: the menu bar, the right-click menus, the notebook tabs, the About window, the format
  picker, the exit wait window, the install window and the Last result card, built on a small
  real Tk host (tests named ``*_tk_*``; they need a display).

Set ``WTS_CAPTURE_I18N=1`` to (re)write the part a test captures; without it the tests compare.
The pseudo-locale tests build the same states with ``qps-ploc`` and expect every text to be
marked, apart from the listed exceptions.
"""
from __future__ import annotations

import json
import ntpath
import os
import re
import threading
import tkinter
import types
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

import app.app as app_mod
from app import i18n, mac_native, shortcuts
from app.app import App
from tests.app.i18n_walk import is_pseudo_marked

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_7_en.json"
# A remote run does not carry environment variables: an (untracked) marker file next to the
# fixture does the same there.
CAPTURE = (os.environ.get("WTS_CAPTURE_I18N") == "1"
           or FIXTURE.with_name("CAPTURE_WAVE_7").exists())
# The video-site feature stays English-only and never reaches a catalog (or this fixture).
_VIDEO_SITE = "Supreme " + "Master"

# The English captures were made on Windows, so the made-up paths the tests hand to the app are
# written there as ``\media\talks\...``. ``_fake`` builds such a path in the running platform's
# form (the app splits and joins it with ``os.path``) and remembers its Windows form, which
# ``_windows_form`` puts back into the texts the app showed, before they are compared.
_FAKE_PATHS: dict[str, str] = {}


def _fake(*parts: str) -> str:
    here = os.path.join(os.sep, *parts)
    # The stem, without the extension: the app also shows the media file's ".srt" sibling.
    _FAKE_PATHS[os.path.splitext(here)[0]] = ntpath.splitext(ntpath.join("\\", *parts))[0]
    return here


def _windows_form(value: Any) -> Any:
    if isinstance(value, str):
        if os.sep == "\\":
            return value
        for here, windows in sorted(_FAKE_PATHS.items(), key=lambda kv: -len(kv[0])):
            value = re.sub(re.escape(here) + r"(?!\w)", lambda _m, w=windows: w, value)
        return value
    if isinstance(value, dict):
        return {key: _windows_form(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_windows_form(item) for item in value]
    return value


MEDIA = _fake("media", "talks", "talk one.mp4")

Rows = list[list[str]]


# ----------------------------------------------------------------------------- helpers

def _load_fixture() -> dict[str, Any]:
    try:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _save_part(part: str, states: dict[str, Any]) -> None:
    doc = _load_fixture()
    doc[part] = states
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                       encoding="utf-8", newline="\n")


@pytest.fixture
def english() -> Iterator[None]:
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo() -> Iterator[None]:
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    try:
        yield
    finally:
        i18n.set_language("en")


class Var:
    """A Tk variable stand-in that remembers every value it was set to."""

    def __init__(self, value: Any = "") -> None:
        self.value = value
        self.history: list[Any] = []

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value
        self.history.append(value)


class Widget:
    """A widget stand-in that records the texts it is configured with."""

    def __init__(self, texts: list[str] | None = None, **options: Any) -> None:
        self.options = dict(options)
        self.texts = texts if texts is not None else []

    def configure(self, **options: Any) -> None:
        self.options.update(options)
        if "text" in options:
            self.texts.append(str(options["text"]))

    config = configure

    def cget(self, name: str) -> Any:
        return self.options.get(name, "")

    def state(self, *_a: Any) -> None: ...
    def pack(self, *_a: Any, **_k: Any) -> None: ...
    def pack_forget(self) -> None: ...
    def set(self, *_a: Any) -> None: ...

    def winfo_exists(self) -> bool:
        return True

    def winfo_manager(self) -> str:
        return ""


class Stub(types.SimpleNamespace):
    """An App stand-in: App's own methods are bound on demand, the rest is set by the test."""

    def __getattr__(self, name: str) -> Any:
        attr = App.__dict__.get(name)
        if attr is None:
            raise AttributeError(name)
        if isinstance(attr, staticmethod):
            return attr.__func__
        if callable(attr):
            return types.MethodType(attr, self)
        return attr


class Shown:
    """Every text a stand-in run shows a person, as [kind, text] rows."""

    def __init__(self) -> None:
        self.rows: Rows = []
        self.answer: Any = False

    def add(self, kind: str, text: Any) -> None:
        self.rows.append([kind, str(text)])

    def take(self) -> Rows:
        rows, self.rows = self.rows, []
        return rows


def _patch_dialogs(mp: pytest.MonkeyPatch, shown: Shown) -> None:
    from tkinter import filedialog, messagebox

    def box(kind: str) -> Callable[..., Any]:
        def show(title: str = "", message: str = "", **_k: Any) -> Any:
            shown.add(f"{kind}.title", title)
            shown.add(f"{kind}.message", message)
            return shown.answer
        return show

    for name in ("askyesno", "askokcancel", "askyesnocancel", "showwarning", "showinfo",
                 "showerror"):
        mp.setattr(messagebox, name, box(name))

    def file_box(kind: str) -> Callable[..., Any]:
        def ask(**kw: Any) -> str:
            shown.add(f"{kind}.title", kw.get("title", ""))
            for label, _pattern in kw.get("filetypes", ()):
                shown.add(f"{kind}.filetype", label)
            return ""
        return ask

    mp.setattr(filedialog, "asksaveasfilename", file_box("asksaveasfilename"))
    mp.setattr(filedialog, "askopenfilename", file_box("askopenfilename"))
    mp.setattr(app_mod, "notify", lambda _w, text, kind="info": shown.add(f"notify.{kind}", text))
    mp.setattr(app_mod, "show_error", lambda _p, title, message, detail=None: (
        shown.add("show_error.title", title), shown.add("show_error.message", message)))


class _NoThread:
    def __init__(self, *_a: Any, **_k: Any) -> None: ...
    def start(self) -> None: ...


def _no_root(*_a: Any, **_k: Any) -> None:
    raise AssertionError("the windowless capture created a Tk window")


def _guard_windowless(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(tkinter.Tk, "__init__", _no_root)
    mp.setattr(tkinter.Toplevel, "__init__", _no_root)
    mp.setattr(tkinter, "_support_default_root", False)


def _stub(shown: Shown, **attrs: Any) -> Stub:
    base: dict[str, Any] = dict(
        app_config={}, logs=[], queue=[], download_queue=[], tray=None, _closing=False,
        post_to_main=lambda fn: fn(), after=lambda *_a, **_k: "after#1",
        status_var=Var(), _base_title="Whisper Transcriber Suite v9.9.9",
    )
    base.update(attrs)
    stub = Stub(**base)
    stub.log = stub.logs.append
    stub.title = lambda text: shown.add("window.title", text)
    return stub


# --------------------------------------------------------------- windowless capture

def capture_pure() -> dict[str, Rows]:
    """The texts the Tk-free module helpers build."""
    from core.history import EXIT_REASON

    states: dict[str, Rows] = {}
    rows: Rows = []
    for title, subsections in app_mod.build_about_sections():
        rows.append(["about.section", title])
        for sub_title, bullets in subsections:
            rows.append(["about.subsection", sub_title])
            rows += [["about.bullet", b] for b in bullets if _VIDEO_SITE not in b]
    states["about_sections"] = rows
    states["about_links"] = [["about.link", label] for label, _url in app_mod.build_about_links()]
    states["resume_prompt"] = [
        ["askyesno.message", app_mod._resume_prompt_text(r)] for r in (
            [{"error": EXIT_REASON}],
            [{"error": None}],
            [{"error": EXIT_REASON}, {"error": EXIT_REASON}],
            [{"error": None}, {"error": ""}, {"error": None}],
            [{"error": EXIT_REASON}, {"error": None}],
            [{"error": EXIT_REASON}, {"error": None}, {"error": None}],
        )
    ]
    folder = os.path.join(os.sep, "work")
    states["not_updated"] = [
        ["showwarning.message", app_mod._not_updated_message(left)] for left in (
            [os.path.join(folder, "a", "talk.docx")],
            [os.path.join(folder, "a", "talk.docx"), os.path.join(folder, "b", "talk.docx")],
            [os.path.join(folder, f"part{i}.srt") for i in range(11)],
        )
    ]
    return states


def capture_windowless(mp: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Rows]:
    """Drive the App methods on a stand-in and collect what they show."""
    from core import offline

    _guard_windowless(mp)
    shown = Shown()
    _patch_dialogs(mp, shown)
    mp.setattr(app_mod, "save_config", lambda _c: None)
    mp.setattr(app_mod, "_APP_VERSION", "9.9.9")
    mp.setattr(shortcuts, "is_mac", lambda: False)
    mp.setattr(mac_native, "is_aqua", lambda _w: False)
    states: dict[str, Rows] = dict(capture_pure())
    task = types.SimpleNamespace(file_path=MEDIA, output_paths=[], language="", detected_language="")

    # Burn subtitles: no SRT on disk, then the save dialog, then a failure.
    stub = _stub(shown)
    mp.setattr(app_mod, "task_srt_output", lambda _t: None)
    App._burn_subs_for(stub, task)  # type: ignore[arg-type]
    mp.setattr(app_mod, "task_srt_output", lambda _t: _fake("x.srt"))
    App._burn_subs_for(stub, task)  # type: ignore[arg-type]
    App._burn_subs_failed(stub, "ffmpeg stopped")  # type: ignore[arg-type]
    states["burn_subs"] = shown.take()

    # View transcript when no JSON was saved; a page that cannot be read; a missing recent file.
    App.open_transcript_viewer_for(stub, _fake("nowhere", "gone.mp4"))  # type: ignore[arg-type]
    mp.setattr(app_mod.share_page, "load_transcript", lambda _p: (_ for _ in ()).throw(OSError("nope")))
    App._save_shareable_page_for(stub, MEDIA, _fake("x.json"))  # type: ignore[arg-type]
    App._open_recent(stub, _fake("nowhere", "gone.mp4"))  # type: ignore[arg-type]
    states["viewer_and_recent"] = shown.take()

    # Work offline: a failed save, then the "needs the internet" question.
    def _fail_save(_c: Any) -> None:
        raise OSError("disk full")

    off = _stub(shown, work_offline_var=None, _hide_update_bar=lambda: None,
                _hide_star_bar=lambda: None, _refresh_window_title=lambda: None,
                _refresh_offline_status=lambda: None, _retry_refused_link_lookup=lambda: None)
    try:
        mp.setattr(app_mod, "save_config", _fail_save)
        App._set_work_offline(off, True)  # type: ignore[arg-type]
        mp.setattr(app_mod, "save_config", lambda _c: None)
        offline.set_offline(True)
        for what in ("Checking for updates", "Installing the YouTube helper",
                     "Updating the video downloader"):
            App.ensure_online(off, what)  # type: ignore[arg-type]
    finally:
        offline.set_offline(False)
    states["work_offline"] = shown.take()

    # Stop running transcriptions to switch the engine or the model.
    for busy in (1, 3):
        svc = types.SimpleNamespace(active_workers=lambda b=busy: [{"task": object()}] * b)
        sw = _stub(shown, transcription_service=svc)
        App._confirm_backend_switch(sw)  # type: ignore[arg-type]
        mvar = Var("new")
        sw.transcribe_model_var = mvar
        sw._transcribe_model_label_to_slug = {"new": "new-slug", "old": "old-slug"}
        sw.app_config = {"whisper_model": "old-slug"}
        mp.setattr("core.model_manager.catalog_resolve_entry", lambda _c, _s: {"name": "x"})
        App._on_model_selected(sw)  # type: ignore[arg-type]
    states["backend_switch"] = shown.take()

    # The Transcribe tab's engine and model lines.
    from core.backends import availability as eng

    other = eng.VALUE_TO_LABEL.get("whisper_cpp") or next(
        label for value, label in eng.VALUE_TO_LABEL.items() if value != "faster_whisper")
    combo = Widget(state="disabled")
    lines = _stub(shown, transcribe_model_combo=combo, transcribe_engine_var=Var(other),
                  model_status_var=Var(), engine_status_var=Var(), engine_status_label=None,
                  probe_engine_status=lambda *_a, **_k: None)
    shown.add("hover", App._model_picker_disabled_reason(lines))  # type: ignore[arg-type]
    App._refresh_model_status(lines)  # type: ignore[arg-type]
    lines.transcribe_engine_var = Var(eng.VALUE_TO_LABEL.get("faster_whisper", ""))
    for present in (True, False):
        mp.setattr("core.model_manager.model_downloaded", lambda _c, _s, p=present: p)
        App._refresh_model_status(lines)  # type: ignore[arg-type]
    App._refresh_engine_status(lines)  # type: ignore[arg-type]
    shown.rows += [["status", str(v)] for v in lines.model_status_var.history]
    shown.rows += [["status", str(v)] for v in lines.engine_status_var.history]
    states["engine_model_lines"] = shown.take()

    # The YouTube helper install: progress, failure, success.
    status = Var()
    js = _stub(shown, format_status_var=status, js_runtime_button=None, download_url_var=Var(""),
               ensure_online=lambda _w: True, update_js_runtime_prompt=lambda *_a: None)
    work: list[Callable[[], None]] = []
    mp.setattr("core._threads.safe_thread", lambda fn, **_k: work.append(fn))

    def _install(progress_cb: Callable[[int], None]) -> str:
        progress_cb(45)
        return _fake("deno")

    mp.setattr("core.js_runtime.install_deno", _install)
    mp.setattr("core.js_runtime.DENO_DOWNLOAD_MB", 40)
    App.install_js_runtime(js)  # type: ignore[arg-type]
    work.pop()()
    App._js_runtime_install_done(js, "", "HTTP 404")  # type: ignore[arg-type]
    shown.rows += [["status", str(v)] for v in status.history]
    states["youtube_helper"] = shown.take()

    # "Use captions instead": both kinds, with and without a language name.
    from app.domain import languages

    for kind in ("manual", "auto"):
        for sub, detected in (("German", ""), ("Automatic", "fr"), ("Automatic", "")):
            cap_status = Var()
            cap = _stub(shown, caption_bar_var=None, caption_bar_label=None,
                        caption_shortcut_status_var=cap_status, caption_shortcut_button=Widget(),
                        subtitle_lang_var=Var(sub), current_video_language=detected,
                        current_video_caption_langs={}, _smtv_episode=None)
            mp.setattr(languages, "resolve_caption_kind", lambda *_a, k=kind, **_kw: k)
            App.update_caption_shortcut_state(cap)  # type: ignore[arg-type]
            shown.rows += [["status", str(v)] for v in cap_status.history]
    states["caption_shortcut"] = shown.take()

    # Device badge hover texts and the one-time CPU warning.
    badge = _stub(shown, device_badge_var=Var(), device_badge_labels=[], device_badge_tip="")
    for kind, worker in (
        ("gpu", {"device": "cuda", "compute_type": "float16"}),
        ("gpu", {"device": "cuda"}),
        ("cpu", {"device": "cpu", "compute_type": "int8"}),
        ("cpu", {}),
        ("cpu_downgraded", {"device": "cpu", "compute_type": "int8", "requested_device": "cuda"}),
        ("cpu_downgraded", {"device": "cpu"}),
    ):
        App.apply_device_badge(badge, "CPU", kind, worker)  # type: ignore[arg-type]
        shown.add("hover", badge.device_badge_tip)
    App.warn_cpu_once(badge, True)  # type: ignore[arg-type]
    App.warn_cpu_once(badge, False)  # type: ignore[arg-type]
    states["device_badge"] = shown.take()

    # Model setup: loaded, cancelled download, the download question, the optional install.
    model = _stub(shown, model_ready=True, model_setup_running=False,
                  wait_window=lambda _w: None, _refresh_model_status=lambda: None,
                  _refresh_engine_status=lambda: None)
    App.ensure_model_with_modal(model)  # type: ignore[arg-type]
    model.model_ready = False
    mp.setattr(app_mod, "ModelDownloadDialog", lambda _app: types.SimpleNamespace(success=False))
    App.ensure_model_with_modal(model)  # type: ignore[arg-type]
    shown.rows += [["status", str(v)] for v in model.status_var.history]
    model._model_bytes_present = lambda: False
    for hint in ("about 1.5 GB, ", ""):
        model._model_download_size_hint = lambda h=hint: h
        App._ensure_transcribe_ready(model)  # type: ignore[arg-type]
    mp.setattr("core.optional_deps.is_available", lambda _f: False)
    mp.setattr("core.optional_deps.can_install", lambda: True)
    App._offer_optional_install(model, "alignment", "Word-timestamp alignment", "700 MB")  # type: ignore[arg-type]
    states["model_setup"] = shown.take()

    # Download tab: the slider hint.
    scale = Widget()
    dl = _stub(shown, download_start_scale=scale, download_end_scale=scale,
               download_duration_var=Var())
    App.set_download_duration(dl, 3725.0)  # type: ignore[arg-type]
    shown.rows += [["status", str(v)] for v in dl.download_duration_var.history]
    states["download_range"] = shown.take()

    # Web / LAN access: start, the three running lines, a failure, stop.
    mp.setattr(threading, "Thread", _NoThread)
    button_texts: list[str] = []
    srv = _stub(shown, server_port_var=Var(8765), server_share_lan_var=Var(False),
                server_token_var=Var(""), server_https_enabled_var=Var(False),
                server_webhook_url_var=Var(""), server_status_var=Var(), server_url_var=Var(),
                server_toggle_btn=Widget(button_texts), server_open_btn=Widget(),
                _server_handle=None, _server_busy=False)
    App._start_server_async(srv)  # type: ignore[arg-type]
    App._stop_server_async(srv)  # type: ignore[arg-type]
    loop = "http://127.0.0.1:8765/"
    App._on_server_started(srv, [loop, "http://192.168.1.5:8765/"], 8765, True)  # type: ignore[arg-type]
    App._on_server_started(srv, [loop], 8765, True)  # type: ignore[arg-type]
    App._on_server_started(srv, [loop], 8765, False)  # type: ignore[arg-type]
    App._on_server_failed(srv, "Port 8765 is in use.")  # type: ignore[arg-type]
    App._on_server_stopped(srv)  # type: ignore[arg-type]
    shown.rows += [["status", str(v)] for v in srv.server_status_var.history]
    shown.rows += [["status", str(v)] for v in srv.server_url_var.history if v]
    shown.rows += [["button", t] for t in button_texts]
    states["web_access"] = shown.take()

    # The window title while jobs run.
    t1 = types.SimpleNamespace(status="running", progress=34, file_path=MEDIA)
    t2 = types.SimpleNamespace(status="running", progress=50, file_path=MEDIA)
    d1 = types.SimpleNamespace(status="running", progress=12, title="A talk about rivers",
                               url="https://example.invalid/v/1")
    d2 = types.SimpleNamespace(status="running", progress=12, title="", url="https://example.invalid/v/2")
    for on in (False, True):
        try:
            offline.set_offline(on)
            for queue, downloads in (([], []), ([t1], []), ([], [d1]), ([], [d2]),
                                     ([t1, t2], [d1])):
                App._refresh_window_title(_stub(shown, queue=queue, download_queue=downloads))  # type: ignore[arg-type]
        finally:
            offline.set_offline(False)
    states["window_title"] = shown.take()

    # Updates: the manual check's three answers, the passive signs.
    from core import updates

    upd = _stub(shown, _update_bar=None, _latest_update=None, _save_update_prefs=lambda: None,
                _refresh_update_signs=lambda: None, _show_update_bar=lambda _i: None,
                _hide_update_bar=lambda: None)
    App._on_update_result(upd, None, manual=True)  # type: ignore[arg-type]
    App._on_update_result(upd, updates.UpdateInfo("v0.0.1", "", False), manual=True)  # type: ignore[arg-type]
    upd.app_config = {"update_skipped_version": "v99.0.0"}
    mp.setattr(updates, "is_skipped", lambda _c, _t: True)
    App._on_update_result(upd, updates.UpdateInfo("v99.0.0", "", True), manual=True)  # type: ignore[arg-type]
    menu_labels: list[str] = []

    class _Menu:
        def entryconfigure(self, _index: Any, label: str = "") -> None:
            menu_labels.append(label)

    signs = _stub(shown, _menubar=_Menu(), _help_menu=_Menu(), _help_cascade_index=3,
                  _check_updates_index=7)
    for version in ("2.1.0", None):
        mp.setattr(updates, "passive_sign_version", lambda _c, _v, ver=version: ver)
        App._refresh_update_signs(signs)  # type: ignore[arg-type]
    shown.rows += [["menu", label] for label in menu_labels]
    states["updates"] = shown.take()

    # The video downloader update bar.
    from core import yt_dlp_update

    bar_texts: list[str] = []
    bar = types.SimpleNamespace(
        show_offer=lambda text, **_k: bar_texts.append(text),
        show_result=lambda text, **_k: bar_texts.append(text),
        show_progress=lambda text, **_k: bar_texts.append(text),
    )
    yt = _stub(shown, _yt_dlp_bar=bar, _yt_dlp_bar_dismissed=False, _yt_dlp_updating=False,
               _yt_dlp_offer_open=False, nb=None, ensure_online=lambda _w: True)
    mp.setattr(yt_dlp_update, "update_mode", lambda _c: "ask")
    mp.setattr(yt_dlp_update, "can_self_update", lambda *_a: True)
    mp.setattr(yt_dlp_update, "download_mb", lambda: 18)
    App.offer_yt_dlp_update(yt, "HTTP Error 403")  # type: ignore[arg-type]
    mp.setattr(yt_dlp_update, "downloads_running", lambda: 1)
    App._yt_dlp_update_now(yt)  # type: ignore[arg-type]
    mp.setattr(yt_dlp_update, "downloads_running", lambda: 0)
    App._yt_dlp_update_now(yt)  # type: ignore[arg-type]
    shown.rows += [["bar", t] for t in bar_texts]
    states["downloader_update"] = shown.take()

    # Esc: cancel the running job; the exit question; exports left old at the exit.
    running = types.SimpleNamespace(status="running", file_path=MEDIA)
    esc = _stub(shown, queue=[running], download_queue=[])
    App._cancel_running(esc)  # type: ignore[arg-type]
    esc = _stub(shown, queue=[], download_queue=[types.SimpleNamespace(status="running")])
    App._cancel_running(esc)  # type: ignore[arg-type]
    for mac in (False, True):
        mp.setattr(shortcuts, "is_mac", lambda m=mac: m)
        leave = _stub(shown, queue=[types.SimpleNamespace(status="waiting")], download_queue=[],
                      _exit_from_tray=True, _exit_prompt_open=False)
        App.on_exit(leave)  # type: ignore[arg-type]
    mp.setattr(shortcuts, "is_mac", lambda: False)
    app_mod._warn_exports_not_updated(_stub(shown), [_fake("w", "talk.docx")])
    states["exit_and_cancel"] = shown.take()

    # Convert transcript: a parse error, a write error, success (Windows and macOS wording).
    from core import convert

    conv = _stub(shown, _ask_convert_format=lambda _p: "srt")
    mp.setattr(app_mod.filedialog, "askopenfilename",
               lambda **kw: (shown.add("askopenfilename.title", kw.get("title", "")),
                             [shown.add("askopenfilename.filetype", label)
                              for label, _p in kw.get("filetypes", ())], "in.vtt")[-1])

    def _parse_error(_p: str, _f: str) -> str:
        raise convert.ConvertError("Not a subtitle file.")

    def _write_error(_p: str, _f: str) -> str:
        raise OSError("read-only folder")

    for convert_file in (_parse_error, _write_error, lambda _p, _f: "out.srt"):
        mp.setattr(convert, "convert_file", convert_file)
        App.convert_transcript(conv)  # type: ignore[arg-type]
    mp.setattr(shortcuts, "is_mac", lambda: True)
    App.convert_transcript(conv)  # type: ignore[arg-type]
    mp.setattr(shortcuts, "is_mac", lambda: False)
    states["convert"] = shown.take()

    # The sample clip cannot be prepared.
    from core import sample_clip

    def _no_copy() -> str:
        raise OSError("no space")

    for prepare in (_no_copy, lambda: None):
        mp.setattr(sample_clip, "prepare_working_copy", prepare)
        App.try_sample_clip(_stub(shown))  # type: ignore[arg-type]
    states["sample_clip"] = shown.take()
    assert not shown.rows
    return _windows_form(states)


def _english_rows(states: dict[str, Rows]) -> list[str]:
    return [text for rows in states.values() for _kind, text in rows]


def test_windowless_english_texts_match_the_capture(
        english: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_windowless(monkeypatch, tmp_path)
    if CAPTURE:
        _save_part("windowless", states)
    expected = _load_fixture()["windowless"]
    assert sorted(states) == sorted(expected)
    # Every differing state at once, so one run shows all of them.
    differ = [name for name in expected if states[name] != expected[name]]
    assert {n: states[n] for n in differ} == {n: expected[n] for n in differ}


# Texts the windowless states show that do not belong to app/app.py's catalog entries: the
# engine names and messages from core/ (not translated yet), file names and links, versions.
def _foreign_windowless(text: str) -> bool:
    from core.backends import availability as eng

    return (
        text in ("Not a subtitle file.", "Port 8765 is in use.", "ffmpeg stopped", "HTTP 404")
        or text.startswith("Whisper Transcriber Suite v9.9.9") and is_pseudo_marked(
            text.replace("Whisper Transcriber Suite v9.9.9", ""))
        or text in eng.VALUE_TO_LABEL.values()
        or text.startswith("http://")
        or text == "CPU"
        # File-type names in the open dialog are format names, not interface text.
        or text in ("SubRip", "WebVTT", "TSV", "Whisper JSON", "oTranscribe", "ELAN", "InqScribe")
    )


def test_windowless_pseudo_locale_leaves_nothing_untranslated(
        pseudo: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_windowless(monkeypatch, tmp_path)
    left = sorted({f"{name}: {kind}: {text}" for name, rows in states.items()
                   for kind, text in rows
                   if text.strip() and not is_pseudo_marked(text) and not _foreign_windowless(text)})
    assert left == []


def test_the_video_site_text_stays_english_and_out_of_the_catalog(pseudo: None) -> None:
    bullets = [b for _t, subs in app_mod.build_about_sections() for _s, bs in subs for b in bs
               if _VIDEO_SITE in b]
    assert bullets and all(not is_pseudo_marked(b) for b in bullets)
    catalog = (Path(app_mod.__file__).resolve().parent / "locales" / "en.json").read_text(
        encoding="utf-8")
    assert _VIDEO_SITE not in catalog and "SMTV" not in catalog


def test_the_engine_status_fallback_recognises_the_translated_checking_text(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The "Checking…" line is compared with what was set; in another language too."""
    from core.backends import availability as eng

    var = Var()
    stub = Stub(engine_status_var=var, engine_status_label=None, app_config={},
                transcribe_engine_var=Var(""), probe_engine_status=lambda *_a, **_k: None,
                after=lambda *_a, **_k: None)
    App._refresh_engine_status(stub)  # type: ignore[arg-type]
    assert is_pseudo_marked(var.get())
    monkeypatch.setattr(eng, "format_engine_status", lambda _st: "cheap status")
    App._engine_status_fallback(stub, stub._engine_status_seq, "faster_whisper")  # type: ignore[arg-type]
    assert var.get() == "cheap status"


def test_the_ensure_online_log_and_saved_switch_are_the_same_in_every_language(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The question is translated; the log line and the stored config stay English."""
    from tkinter import messagebox

    from core import offline

    shown = Shown()
    asked: list[str] = []
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda title, text, **_k: asked.append(text) or True)
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(dict(c)))
    stub = _stub(shown, work_offline_var=None, _hide_update_bar=lambda: None,
                 _hide_star_bar=lambda: None, _refresh_window_title=lambda: None,
                 _refresh_offline_status=lambda: None, _retry_refused_link_lookup=lambda: None,
                 app_config={"work_offline": True})
    try:
        offline.set_offline(True)
        assert App.ensure_online(stub, "Checking for updates") is True  # type: ignore[arg-type]
    finally:
        offline.set_offline(False)
    assert asked and is_pseudo_marked(asked[0])
    assert saved == [{"work_offline": False}]


# ------------------------------------------------------------------- real Tk capture

@pytest.fixture
def tk_root() -> Iterator[None]:
    try:
        probe = tkinter.Tk()
        probe.destroy()
    except tkinter.TclError:
        pytest.skip("no Tk display available")
    yield


def _host_class() -> type:
    names = (
        "_build_menu", "_populate_recent_menu", "_refresh_update_signs", "menu_row",
        "download_menu_row", "_bulk_task_menu", "_bulk_download_menu", "_resumable_tasks",
        "_task_has_checkpoint", "_show_about", "_ask_convert_format", "_build_tabs",
        "show_last_result", "_offer_optional_install", "_finish_optional_install",
        "_install_text_context_menu", "_task_json_output", "_open_file", "_open_folder",
    )
    attrs = {n: App.__dict__[n] for n in names}
    attrs["_COMMON_CONVERT_FORMATS"] = App._COMMON_CONVERT_FORMATS
    return type("_Host", (tkinter.Tk,), attrs)


def _new_host(mp: pytest.MonkeyPatch) -> Any:
    from unittest.mock import MagicMock

    host = _host_class()()
    host.withdraw()
    host.app_config = {}
    host.theme_var = tkinter.StringVar(master=host, value="system")
    for name in ("browse", "convert_transcript", "show_statistics", "_force_exit", "apply_theme",
                 "_save_chime_pref", "_open_transcript_viewer_picker", "_open_search_dialog",
                 "open_log_folder", "copy_mcp_setup", "_check_for_updates_manual", "_save_telemetry_pref",
                 "open_ui_language_chooser",
                 "_show_about_mock", "_toggle_work_offline", "_open_problem_report",
                 "_star_open_page", "pause", "resume", "cancel", "resume_task", "_rerun_task",
                 "remove_task", "pause_download", "resume_download", "cancel_download",
                 "_rerun_download", "remove_download", "_burn_subs_for",
                 "open_transcript_viewer_for", "_save_shareable_page_for", "_bulk_apply",
                 "_bulk_rerun", "_bulk_resume", "_clear_recent", "_open_recent"):
        setattr(host, name, MagicMock(name=name))
    host.integrations_service = MagicMock()
    host.history = None
    return host


def _texts(widget: Any) -> list[str]:
    from tests.app.i18n_walk import visible_texts

    return [text for _path, text in visible_texts(widget)]


def _menu_texts(menu: Any) -> list[str]:
    from tests.app.i18n_walk import _menu_labels

    return [text for _path, text in _menu_labels(menu)]


def _cascade_menus(host: Any, menubar: Any) -> list[Any]:
    """The submenus of a menu bar's cascade entries, in order.

    ``tk.Menu(parent)`` has a tear-off entry at index 0 in Tk 8.6 (it has no ``-menu`` option
    and raises ``TclError`` on ``entrycget``) and none in Tk 9, where tear-off is off by default.
    Counting only the cascades gives the same names and order on both.
    """
    return [host.nametowidget(str(menubar.entrycget(i, "menu")))
            for i in range(int(menubar.index("end")) + 1) if menubar.type(i) == "cascade"]


def capture_tk(mp: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list[str]]:
    """Build the parts of the main window app/app.py owns on a real Tk host."""
    from app.widgets import tabs

    states: dict[str, list[str]] = {}
    mp.setattr(shortcuts, "is_mac", lambda: False)
    mp.setattr(mac_native, "is_aqua", lambda _w: False)
    mp.setattr(app_mod, "save_config", lambda _c: None)
    # A grab needs a mapped window; the host stays withdrawn.
    mp.setattr(tkinter.Misc, "grab_set", lambda _self: None)
    popped: list[Any] = []
    mp.setattr(tkinter.Menu, "tk_popup", lambda self, *_a, **_k: popped.append(self))

    host = _new_host(mp)
    try:
        # The menu bar (Windows / Linux form) and the recent-files submenu.
        host._build_menu()
        states["menubar"] = _menu_texts(host._menubar)
        for n, sub in enumerate(_cascade_menus(host, host._menubar)):
            states[f"menu_{n}"] = _menu_texts(sub)
        host._populate_recent_menu()
        states["recent_empty"] = _menu_texts(host._recent_menu)
        host.history = types.SimpleNamespace(list_transcriptions=lambda limit=10: [
            {"file_path": MEDIA}])
        host._populate_recent_menu()
        states["recent_list"] = [t for t in _menu_texts(host._recent_menu)
                                 if "talk one.mp4" not in t]
        from core import updates

        mp.setattr(updates, "passive_sign_version", lambda _c, _v: "2.1.0")
        host._refresh_update_signs()
        states["update_signs"] = [host._menubar.entrycget(host._help_cascade_index, "label"),
                                  host._help_menu.entrycget(host._check_updates_index, "label")]

        # Right-click menus of the Queue and the Download lists.
        from core import _checkpoint

        mp.setattr(_checkpoint, "has_checkpoint", lambda _p: True)
        event = types.SimpleNamespace(x=0, y=0, x_root=0, y_root=0)
        host.tree = types.SimpleNamespace(identify_row=lambda _y: "i1", selection=lambda: (),
                                          selection_set=lambda _i: None)
        for status in ("waiting", "running", "paused", "finished", "cancelled", "error"):
            t = types.SimpleNamespace(status=status, file_path=MEDIA, output_paths=[],
                                      language="", detected_language="")
            host.row_map = {"i1": t}
            host.menu_row(event)
            states[f"queue_menu_{status}"] = _menu_texts(popped.pop())
        host.download_tree = types.SimpleNamespace(identify_row=lambda _y: "d1", selection=lambda: ())
        saved = tmp_path / "video.mp4"
        saved.write_bytes(b"x")
        for status in ("waiting", "running", "paused", "finished", "cancelled"):
            d = types.SimpleNamespace(status=status, saved_path=str(saved), folder=str(tmp_path),
                                      format_info={})
            host.download_row_map = {"d1": d}
            host.download_menu_row(event)
            states[f"download_menu_{status}"] = _menu_texts(popped.pop())
        many = [types.SimpleNamespace(status=s, file_path=MEDIA)
                for s in ("running", "waiting", "finished", "cancelled", "error")]
        host._bulk_task_menu(many, event)
        states["queue_menu_bulk"] = _menu_texts(popped.pop())
        host._bulk_download_menu(many, event)
        states["download_menu_bulk"] = _menu_texts(popped.pop())

        # The text-field menu (Cut / Copy / Paste / Select all).
        bound: list[Callable[..., Any]] = []
        mp.setattr(host, "bind_class", lambda _c, _s, fn, add="": bound.append(fn))
        host._install_text_context_menu()
        entry = tkinter.Entry(host)
        bound[0](types.SimpleNamespace(widget=entry, x_root=0, y_root=0))
        states["text_field_menu"] = _menu_texts(popped.pop())

        # The notebook tabs (the tab builders are left out: their files have their own tests).
        for name in ("build_transcribe_tab", "build_queue_tab", "build_live_tab",
                     "build_download_tab", "build_smtv_tab", "build_server_tab",
                     "build_voice_clone_tab"):
            mp.setattr(app_mod, name, lambda *_a, **_k: None)
        mp.setattr(tabs, "fit_or_scroll", lambda page: page)
        mp.setattr(app_mod, "voice_clone_tab_enabled", lambda: True)
        host._build_tabs()
        states["tabs"] = [str(host.nb.tab(t, "text")) for t in host.nb.tabs()
                          if str(host.nb.tab(t, "text")) and _VIDEO_SITE not in str(host.nb.tab(t, "text"))]

        # The About window: widget texts and the feature text in its Text box.
        mp.setattr(updates, "passive_sign_version", lambda _c, _v: "2.1.0")
        before = set(host.winfo_children())
        host._show_about()
        about = next(w for w in host.winfo_children() if w not in before)
        texts = _texts(about)
        states["about_window"] = [t.split(" — v")[0] if t.startswith("Whisper Transcriber Suite — v")
                                  else t for t in texts]
        box = next(w for w in _walk(about) if w.winfo_class() == "Text")
        states["about_text"] = [line for line in box.get("1.0", "end").splitlines()
                                if line.strip() and _VIDEO_SITE not in line]
        about.grab_release()
        about.destroy()

        # The format picker of File > Convert transcript.
        picker: list[list[str]] = []

        def _wait(dlg: Any) -> None:
            picker.append(_texts(dlg))
            dlg.destroy()

        mp.setattr(host, "wait_window", _wait)
        host._ask_convert_format(_fake("x", "talk.srt"))
        states["convert_picker"] = picker.pop()

        # The optional install window (and its Cancel).
        from core import optional_deps

        mp.setattr(optional_deps, "is_available", lambda _f: False)
        mp.setattr(optional_deps, "can_install", lambda: True)
        mp.setattr(optional_deps, "install", lambda *_a, **_k: False)
        mp.setattr("tkinter.messagebox.askyesno", lambda *_a, **_k: True)
        host.transcription_service = types.SimpleNamespace(stop_all=lambda: None)
        host._closing = False
        host.post_to_main = lambda fn: None
        host.log = lambda _m: None

        def _wait_install(win: Any) -> None:
            picker.append(_texts(win))
            button = next(w for w in _walk(win) if w.winfo_class() == "TButton")
            button.invoke()
            picker.append(_texts(win))
            win.destroy()

        mp.setattr(host, "wait_window", _wait_install)
        host._offer_optional_install("alignment", "Word-timestamp alignment", "700 MB")
        states["install_window"] = picker.pop(0) + picker.pop(0)

        # The exit wait window.
        wait = app_mod._open_exit_wait_dialog(host)
        assert wait is not None
        states["exit_wait"] = _texts(wait)
        wait.grab_release()
        wait.destroy()

        # The Last result card: files found, none found, no speech.
        from app import desktop_alert
        from core import subtitle_edit

        mp.setattr(desktop_alert, "job_done", lambda *_a, **_k: None)
        mp.setattr(subtitle_edit, "is_supported", lambda *_a: False)
        host.last_result_frame = tkinter.Frame(host)
        host.last_result_empty_label = tkinter.Label(host.last_result_frame)
        host.last_result_body = tkinter.Frame(host.last_result_frame)
        host.chime_on_complete_var = None  # no bell on the test machine
        tray: list[str] = []
        host.tray = types.SimpleNamespace(notify=lambda title, body: tray.extend([title, body]))
        out = tmp_path / "talk one.srt"
        out.write_bytes(b"1\r\n")  # 3 bytes on every platform, as in the Windows capture
        js = tmp_path / "talk one.json"
        js.write_text("{}", encoding="utf-8")
        for name, outputs, no_speech in (("two_files", [str(out), str(js)], False),
                                         ("one_file", [str(out)], True),
                                         # no speech: no viewer or share buttons over empty files
                                         ("silent_two_files", [str(out), str(js)], True),
                                         ("no_files", [str(tmp_path / "gone.srt")], False)):
            task = types.SimpleNamespace(file_path=str(tmp_path / "talk one.mp4"),
                                         output_paths=outputs, no_speech=no_speech, language="",
                                         detected_language="", speed_audio_s=0.0,
                                         speed_seconds=0.0, speed_model="")
            host.show_last_result(task)
            states[f"last_result_{name}"] = [_strip_path(t, str(tmp_path))
                                             for t in _texts(host.last_result_body)]
        states["tray_notice"] = [_strip_path(t, str(tmp_path)) for t in tray]
    finally:
        host.destroy()
    return _windows_form(states)


def _walk(widget: Any) -> Iterator[Any]:
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _strip_path(text: str, folder: str) -> str:
    return text.replace(folder, "<tmp>")


def test_tk_english_texts_match_the_capture(
        english: None, tk_root: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_tk(monkeypatch, tmp_path)
    if CAPTURE:
        _save_part("tk", states)
    expected = _load_fixture()["tk"]
    assert sorted(states) == sorted(expected)
    # Every differing state at once, so one run shows all of them.
    differ = [name for name in expected if states[name] != expected[name]]
    assert {n: states[n] for n in differ} == {n: expected[n] for n in differ}


def test_tk_pseudo_locale_leaves_nothing_untranslated(
        pseudo: None, tk_root: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states = capture_tk(monkeypatch, tmp_path)
    # The product name and the file names shown.
    foreign = {"Whisper Transcriber Suite"}
    left = sorted({
        f"{name}: {text}" for name, rows in states.items() for text in rows
        if text.strip() and not is_pseudo_marked(text) and text not in foreign
        and not text.startswith(("✓ talk one.mp4", "⚠ talk one.mp4", "• talk one."))
        # The format picker lists format ids with their extension ("srt (.srt)").
        and not (name == "convert_picker" and re.fullmatch(r"\w+ \(\.\w+\)", text))
    })
    assert left == []


def test_tk_the_theme_menu_stores_english_values(
        pseudo: None, tk_root: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The View menu's labels are translated; the theme it stores is still light/dark/system."""
    monkeypatch.setattr(shortcuts, "is_mac", lambda: False)
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    host = _new_host(monkeypatch)
    try:
        host._build_menu()
        view = _cascade_menus(host, host._menubar)[1]
        radios = [i for i in range(int(view.index("end")) + 1) if view.type(i) == "radiobutton"]
        assert [str(view.entrycget(i, "value")) for i in radios] == ["light", "dark", "system"]
        assert all(is_pseudo_marked(str(view.entrycget(i, "label"))) for i in radios)
        view.invoke(radios[1])
        assert host.theme_var.get() == "dark"
    finally:
        host.destroy()
