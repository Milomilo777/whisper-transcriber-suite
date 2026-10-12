"""Translation wave 9: the texts the services and helpers show a person, without a Tk root.

Covers ``app/services/{download,format,transcription,integrations}_service.py``,
``app/domain/languages.py``, ``app/desktop_alert.py`` and ``app/crash_report.py``: every
message box, error dialog, file dialog, status line, combobox value and desktop notification
they produce, in each state a test can reach cheaply. The services are driven with stand-in
apps and patched dialogs, so no window opens.

The fixture ``tests/fixtures/i18n/i18n_wave_9_en.json`` was captured BEFORE these files went
through the translation layer; the English texts must stay byte-identical to it. With the
pseudo-locale every text the files own is marked (the allowed exceptions are listed in
``_NOT_OURS`` with their reason).
"""
from __future__ import annotations

import json
import os
import queue
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from tests.app import fake_tk

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_9_en.json"

Record = list[str]
States = dict[str, list[Record]]


class _Box:
    """Stand-in for ``tkinter.messagebox`` / ``filedialog``: records each call, returns ``answer``."""

    def __init__(self, out: list[Record], answer: Any = None) -> None:
        self.out = out
        self.answer = answer

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            texts = [str(a) for a in args[:2]]
            if "title" in kwargs:
                texts.insert(0, str(kwargs["title"]))
            for t in texts:
                self.out.append([name, t])
            for label, _pattern in kwargs.get("filetypes", ()):
                self.out.append([name + ":filetype", str(label)])
            return self.answer
        return call


class _Var(fake_tk.FakeVar):
    """A StringVar stand-in that records every value it is set to."""

    def __init__(self, out: list[Record], channel: str, value: str = "") -> None:
        super().__init__(value=value)
        self.out = out
        self.channel = channel

    def set(self, value: str) -> None:
        super().set(value)
        self.out.append([self.channel, str(value)])


# --------------------------------------------------------------------------- integrations

def _integrations(mp: pytest.MonkeyPatch, tmp: Path) -> States:
    from app.services import integrations_service as mod

    states: States = {}
    out: list[Record] = []
    errors: list[Record] = []
    mp.setattr(mod, "show_error", lambda _p, title, message, detail=None: (
        errors.extend([["show_error", title], ["show_error", message]])))
    app = SimpleNamespace(log=lambda _m: None, status_var=_Var(out, "status"))
    service = mod.IntegrationsService(app)  # type: ignore[arg-type]
    task = SimpleNamespace(file_path=str(tmp / "talk.mp4"), output_files=[])

    mp.setattr(mod, "messagebox", _Box(out))
    mp.setattr(mod, "task_srt_output", lambda _t: None)
    service.export_task_to_otr(task)  # type: ignore[arg-type]
    states["otr_no_srt"] = out[:]

    srt = tmp / "talk.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    (tmp / "talk.otr").write_text("{}", encoding="utf-8")
    mp.setattr(mod, "task_srt_output", lambda _t: str(srt))
    out.clear()
    mp.setattr(mod, "messagebox", _Box(out, answer=None))  # Cancel
    service.export_task_to_otr(task)  # type: ignore[arg-type]
    states["otr_replace_question"] = out[:]

    out.clear()
    mp.setattr(mod, "messagebox", _Box(out, answer=True))
    mp.setattr(mod, "srt_to_otr", lambda *_a: (_ for _i in ()).throw(ValueError("bad srt")))
    service.export_task_to_otr(task)  # type: ignore[arg-type]
    states["otr_export_failed"] = out[:] + errors[:]
    errors.clear()

    out.clear()
    mp.setattr(mod, "srt_to_otr", lambda *_a: "{}")
    service.export_task_to_otr(task)  # type: ignore[arg-type]
    states["otr_exported"] = out[:]

    out.clear()
    mp.setattr(mod, "filedialog", _Box(out, answer=""))
    service.import_otr_to_srt()
    states["import_choose"] = out[:]

    out.clear()
    answers = iter([str(tmp / "talk.otr"), str(tmp / "out.srt")])

    class _Dialogs(_Box):
        def __getattr__(self, name: str) -> Callable[..., Any]:
            inner = super().__getattr__(name)

            def call(*args: Any, **kwargs: Any) -> Any:
                inner(*args, **kwargs)
                return next(answers)
            return call

    mp.setattr(mod, "filedialog", _Dialogs(out))
    mp.setattr(mod, "otr_to_srt", lambda _p: (_ for _i in ()).throw(ValueError("bad otr")))
    service.import_otr_to_srt()
    states["import_failed"] = out[:] + errors[:]
    errors.clear()

    out.clear()
    answers = iter([str(tmp / "talk.otr"), str(tmp / "out.srt")])
    mp.setattr(mod, "otr_to_srt", lambda _p: "1\n")
    service.import_otr_to_srt()
    states["import_done"] = out[:]
    return states


# ------------------------------------------------------------------------------ download

def _download_app(out: list[Record], **extra: Any) -> SimpleNamespace:
    base: dict[str, Any] = dict(
        download_url_var=fake_tk.FakeVar(value="https://example.invalid/v"),
        download_folder_var=fake_tk.FakeVar(value="/tmp/folder"),
        download_mode_var=fake_tk.FakeVar(value="Audio and video"),
        audio_format_var=fake_tk.FakeVar(value="Best audio"),
        video_format_var=fake_tk.FakeVar(value="Best video"),
        output_format_var=fake_tk.FakeVar(value="mp4"),
        subtitle_lang_var=fake_tk.FakeVar(value="Automatic"),
        audio_format_map={"Best audio": {"kind": "best_audio"}},
        video_format_map={"Best video": {"kind": "best_video"}},
        current_video_language="",
        current_video_caption_langs={},
        current_video_title="Clip",
        format_lookup_after=None,
        _smtv_episode=None,
        app_config={},
        download_events=queue.Queue(),
        log=lambda _m: None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _download(mp: pytest.MonkeyPatch, tmp: Path) -> States:
    from app.dialogs import caption_choice
    from app.services import download_service as mod
    from core import offline

    mp.setattr(offline, "is_offline", lambda *_a, **_k: False)
    mp.setattr(mod, "save_config", lambda _c: None)
    states: States = {}
    out: list[Record] = []
    mp.setattr("tkinter.messagebox", _Box(out))

    def run(name: str, app: SimpleNamespace, action: Callable[[Any], None]) -> None:
        out.clear()
        action(mod.DownloadService(app))  # type: ignore[arg-type]
        states[name] = out[:]

    for name, method in (("form", "enqueue_from_form"), ("captions", "enqueue_caption_only_from_form")):
        run(f"{name}_no_url", _download_app(out, download_url_var=fake_tk.FakeVar(value="")),
            lambda s, m=method: getattr(s, m)())
        run(f"{name}_no_folder", _download_app(out, download_folder_var=fake_tk.FakeVar(value="")),
            lambda s, m=method: getattr(s, m)())

    subbed = _download_app(out, download_mode_var=fake_tk.FakeVar(value="Audio"))
    subbed.make_subbed_video_var = fake_tk.FakeVar(value=True)  # type: ignore[arg-type]
    run("form_subbed_audio_only", subbed, lambda s: s.enqueue_from_form())
    run("form_no_audio_format", _download_app(out, audio_format_map={}), lambda s: s.enqueue_from_form())
    run("form_no_video_format", _download_app(out, video_format_map={}), lambda s: s.enqueue_from_form())
    run("form_lookup_failed", _download_app(out, video_format_map={}, format_lookup_error="HTTP 404"),
        lambda s: s.enqueue_from_form())
    run("form_lookup_failed_audio", _download_app(out, audio_format_map={}, format_lookup_error="HTTP 404"),
        lambda s: s.enqueue_from_form())
    run("form_no_output", _download_app(out, output_format_var=fake_tk.FakeVar(value="")),
        lambda s: s.enqueue_from_form())
    run("captions_none_found", _download_app(out), lambda s: s.enqueue_caption_only_from_form())

    def no_folder(*_a: Any, **_k: Any) -> None:
        raise OSError("Access is denied")

    real_makedirs = os.makedirs
    mp.setattr(mod.os, "makedirs", no_folder)
    run("form_folder_unavailable", _download_app(out), lambda s: s.enqueue_from_form())
    run("captions_folder_unavailable",
        _download_app(out, current_video_caption_langs={"en": "manual"},
                      subtitle_lang_var=fake_tk.FakeVar(value="English")),
        lambda s: s.enqueue_caption_only_from_form())
    mp.setattr(mod.os, "makedirs", real_makedirs)

    # The "subtitles or transcription?" question gets the language name to show.
    asked: list[Record] = []
    mp.setattr(caption_choice, "ask_caption_choice",
               lambda _m, *, kind, language: (asked.append(["caption_choice", language]), ("cancel", False))[1])
    for name, sub_lang, detected, langs in (
            ("choice_named", "German", "", {"de": "manual"}),
            ("choice_detected", "Automatic", "es", {"es": "auto"}),
            ("choice_detected_unknown", "Automatic", "xx", {"xx": "auto"})):
        asked.clear()
        app = _download_app(out, subtitle_lang_var=fake_tk.FakeVar(value=sub_lang),
                            current_video_language=detected, current_video_caption_langs=langs)
        app.auto_transcribe_var = fake_tk.FakeVar(value=True)  # type: ignore[arg-type]
        mod.DownloadService(app)._caption_choice()  # type: ignore[arg-type]
        states[name] = asked[:]

    states.update(_subtitle_statuses(mp, mod, tmp))
    return states


def _statuses(app: SimpleNamespace) -> list[Record]:
    found: list[Record] = []
    while True:
        try:
            kind, _task, payload = app.download_events.get_nowait()
        except queue.Empty:
            return found
        if kind == "subtitle_status":
            found.append(["subtitle_status", str(payload)])


def _subtitle_statuses(mp: pytest.MonkeyPatch, mod: Any, tmp: Path) -> States:
    from core import convert

    states: States = {}
    mp.setattr(mod, "write_subtitle_extra_formats", lambda *_a, **_k: [])
    caption = tmp / "clip.en.vtt"
    caption.write_text("WEBVTT\n", encoding="utf-8")

    def task(**kw: Any) -> SimpleNamespace:
        base = dict(subtitle_lang="en", detected_language="", cancelled=False, paused=False,
                    caption_kind="manual")
        base.update(kw)
        return SimpleNamespace(**base)

    def phase(name: str, result: tuple[list[str], bool, int], method: str = "_subtitle_phase",
              config: dict[str, Any] | None = None, **task_kw: Any) -> None:
        app = _download_app([], app_config=config or {})
        service = mod.DownloadService(app)
        mp.setattr(service, "_fetch_subtitles", lambda *_a: result)
        getattr(service, method)(task(**task_kw))
        states[name] = _statuses(app)

    files = [str(caption)]
    phase("subs_no_language", ([], False, 0), subtitle_lang="")
    phase("subs_one_file", (files, False, 0))
    phase("subs_two_files", (files * 2, False, 0))
    phase("subs_none_available", ([], True, 0))
    phase("subs_failed", ([], False, 2))
    phase("subs_nothing_written", ([], False, 0))
    phase("subs_cancelled", ([], False, 0), cancelled=True)

    co = "_run_caption_only_task"
    phase("captions_no_language", ([], False, 0), co, subtitle_lang="")
    phase("captions_cancelled", (files, False, 0), co, cancelled=True)
    phase("captions_paused", (files, False, 0), co, paused=True)
    phase("captions_none_available", ([], True, 0), co)
    phase("captions_failed", ([], False, 1), co)
    phase("captions_nothing_written", ([], False, 0), co)
    phase("captions_no_target", (files, False, 0), co, config={"output_formats": ["docx"]})
    mp.setattr(convert, "parse_to_segments", lambda _p: [])
    mp.setattr(convert, "convert_file", lambda src, fmt, target=None, **_k: str(tmp / f"clip.{fmt}"))
    phase("captions_one_format", (files, False, 0), co, config={"output_formats": ["srt"]})
    phase("captions_two_formats", (files, False, 0), co, config={"output_formats": ["srt", "vtt"]})

    def unreadable(_p: str) -> Any:
        raise convert.ConvertError("not a caption file")

    mp.setattr(convert, "parse_to_segments", unreadable)
    phase("captions_unreadable", (files, False, 0), co)
    return states


# -------------------------------------------------------------------------------- format

def _format(mp: pytest.MonkeyPatch) -> States:
    from app.services import format_service as mod
    from core import _threads, offline

    mp.setattr(offline, "is_offline", lambda *_a, **_k: False)
    mp.setattr(_threads, "safe_thread", lambda *_a, **_k: None)
    states: States = {}
    out: list[Record] = []

    class _Combo(dict):  # type: ignore[type-arg]
        def __setitem__(self, key: str, value: Any) -> None:
            super().__setitem__(key, value)
            for v in value:
                out.append(["combobox", str(v)])

    def app_for(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            download_url_var=fake_tk.FakeVar(value=url), format_lookup_after=None,
            audio_format_combo=_Combo(), video_format_combo=_Combo(),
            audio_format_var=fake_tk.FakeVar(), video_format_var=fake_tk.FakeVar(),
            format_status_var=_Var(out, "format_status"), app_config={},
            format_events=queue.Queue(), after=lambda *_a: None,
            update_download_mode=lambda: None, set_download_duration=lambda _d: None,
            update_caption_shortcut_state=lambda: None, hide_yt_dlp_offer=lambda: None,
            yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "", entry_file=__file__,
        )

    out.clear()
    mod.FormatService(app_for("")).lookup_formats()  # type: ignore[arg-type]
    states["format_no_url"] = out[:]

    out.clear()
    url = "https://example.invalid/watch"
    mod.FormatService(app_for(url)).lookup_formats()  # type: ignore[arg-type]
    states["format_loading"] = out[:]

    out.clear()
    app = app_for(url)
    payload = {"title": "Clip", "formats": [
        {"format_id": "140", "ext": "m4a", "acodec": "mp4a", "vcodec": "none", "abr": 128},
        {"format_id": "137", "ext": "mp4", "acodec": "none", "vcodec": "avc1", "width": 1920,
         "height": 1080, "fps": 30},
    ]}
    mod.FormatService(app)._handle_event("formats", url, payload)  # type: ignore[arg-type]
    states["format_loaded"] = out[:]

    out.clear()
    app = app_for(url)
    app.format_events.put(("formats", url, ["not", "a", "dict"]))
    mod.FormatService(app).poll()  # type: ignore[arg-type]
    states["format_unreadable"] = out[:]
    return states


# ------------------------------------------------------------------------- transcription

def _transcription(mp: pytest.MonkeyPatch) -> States:
    from app.services import transcription_service as mod
    from app.widgets import error_dialog

    states: States = {}
    out: list[Record] = []

    def app_for(**extra: Any) -> SimpleNamespace:
        base: dict[str, Any] = dict(
            workers=[], queue=[], parallel_workers=1, worker_events=queue.Queue(),
            status_var=_Var(out, "status"), update_overall_progress=lambda: None,
            log=lambda _m: None, after=lambda *_a: None, next_worker_id=1, entry_file=__file__,
            app_config={"model": {"name": "test"}, "transcribe_backend": "faster_whisper",
                        "cpu_warning_shown": True},
            apply_device_badge=lambda text, kind, _w: out.append(["device_badge", text]),
        )
        base.update(extra)
        return SimpleNamespace(**base)

    def worker(n: int, **info: Any) -> dict[str, Any]:
        return {"id": n, "process": SimpleNamespace(pid=100 + n, poll=lambda: None),
                "ready": True, "task": None, **info}

    for name, workers in (
            ("model_ready_one", [worker(1)]),
            ("model_ready_two", [worker(1), worker(2)]),
            ("badge_gpu", [worker(1, device="cuda", compute_type="float16")]),
            ("badge_gpu_no_type", [worker(1, device="cuda", compute_type="")]),
            ("badge_cpu", [worker(1, device="cpu", compute_type="")]),
            ("badge_cpu_typed", [worker(1, device="cpu", compute_type="int8_float32")]),
            ("badge_downgraded", [worker(1, device="cpu", compute_type="int8", downgraded=True)])):
        out.clear()
        mod.TranscriptionService(app_for(workers=workers)).update_model_state()  # type: ignore[arg-type]
        states[name] = out[:]

    out.clear()

    def no_spawn(*_a: Any, **_k: Any) -> Any:
        raise OSError("cannot start")

    mp.setattr(mod.subprocess, "Popen", no_spawn)
    with pytest.raises(OSError):
        mod.TranscriptionService(app_for()).start_worker()  # type: ignore[arg-type]
    states["worker_loading"] = out[:]

    out.clear()
    mp.setattr(error_dialog, "show_error", lambda _p, title, message, detail=None: (
        out.extend([["show_error", title], ["show_error", message]])))
    app = app_for(model_setup_running=False)
    app.app_config["transcribe_backend"] = "whisper_cpp"
    app.workers.append({"id": 1, "process": SimpleNamespace(pid=111, poll=lambda: None,
                                                            wait=lambda **_kw: 0)})
    app.worker_events.put({"event": "startup_error", "message": "model missing",
                           "_worker_id": 1, "_pid": 111})
    mod.TranscriptionService(app).poll()  # type: ignore[arg-type]
    states["engine_failed"] = [r for r in out if r[0] == "show_error"]
    return states


# ----------------------------------------------------------------- languages, alerts, crash

def _languages() -> States:
    from app.domain.languages import caption_availability_text

    samples = {
        "caption_line_one": ({"en": "manual"}, ()),
        "caption_line_mixed": ({"de": "manual", "fr": "auto", "pt-BR": "auto"}, ()),
        "caption_line_original": ({"es-orig": "auto", "es": "auto", "de": "auto"}, ()),
        "caption_line_unknown_code": ({"xx": "manual"}, ()),
        "caption_line_many": ({c: "auto" for c in ("en", "de", "fr", "es", "it", "nl", "pl", "ru")},
                              ("ru",)),
        "caption_line_one_more": ({c: "manual" for c in ("en", "de", "fr", "es", "it", "nl", "zh-Hans")},
                                  ()),
    }
    return {name: [["caption_line", caption_availability_text(langs, prefer)]]
            for name, (langs, prefer) in samples.items()}


def _alerts(mp: pytest.MonkeyPatch) -> States:
    from app import desktop_alert as da

    posted: list[Record] = []
    mp.setattr(da.mac_native, "is_aqua", lambda _w: True)
    mp.setattr(da, "window_has_focus", lambda _a: False)
    mp.setattr(da, "post_notification", lambda text, title: posted.extend(
        [["notification", text], ["notification_title", title]]))
    app = SimpleNamespace(queue=[], app_config={"chime_on_complete": True})
    states: States = {}

    def take(name: str, action: Callable[[], None]) -> None:
        posted.clear()
        da.reset_for_tests()
        action()
        states[name] = posted[:]

    def job(**kw: Any) -> SimpleNamespace:
        return SimpleNamespace(file_path="/x/talk.mp4", start_time=1.0, end_time=2.0, **kw)

    take("alert_done_one", lambda: da.job_done(app, job(), 1))
    take("alert_done_three", lambda: da.job_done(app, job(), 3))
    take("alert_done_none", lambda: da.job_done(app, job(), 0))
    take("alert_no_speech", lambda: da.job_done(app, job(no_speech=True), 2))

    def queue_of(n: int) -> None:
        da._batch.update(count=n - 1, last_end=1.5)
        da.job_done(app, job(), 1)

    take("alert_queue_two", lambda: queue_of(2))
    take("alert_queue_five", lambda: queue_of(5))
    take("alert_downloaded", lambda: da.download_done(app, "/x/clip.mp4"))
    take("alert_burned", lambda: da.burn_done(app, "/x/clip-subbed.mp4"))
    dl = SimpleNamespace(saved_path="/x/clip.mp4", title="Clip")
    take("alert_chain_failed", lambda: da.chain_failed(app, dl, "Burning failed"))
    take("alert_chain_no_speech", lambda: da.chain_failed(app, dl, "No speech was found; x"))
    mp.setattr(da.mac_native, "is_aqua", lambda w: bool(getattr(w, "aqua", False)))
    states["chime_labels"] = [["menu", da.chime_menu_label(SimpleNamespace(aqua=True))],
                              ["menu", da.chime_menu_label(SimpleNamespace(aqua=False))]]
    return states


def _crash(mp: pytest.MonkeyPatch) -> States:
    from app import crash_report

    shown: list[Record] = []
    states: States = {}
    import core.config

    def broken() -> Any:
        raise OSError("no folder")

    mp.setattr(crash_report, "_ensure_log_file", lambda: None)
    # The folder lookup failing first (the real _log_folder), then a known folder.
    for name, folder in (("crash_no_folder", None), ("crash_with_folder", "/logs")):
        shown.clear()
        mp.setattr(sys, "excepthook", lambda *_a: None)
        if folder is None:
            mp.setattr(core.config, "user_log_dir", broken)
        else:
            mp.setattr(crash_report, "_log_folder", lambda f=folder: f)
        crash_report.install_excepthook(notify=lambda m: shown.append(["crash_box", m]))
        sys.excepthook(ValueError, ValueError("boom"), None)
        states[name] = shown[:]
    return states


def capture_states(mp: pytest.MonkeyPatch, tmp: Path) -> States:
    """Every text the wave-9 files show, per reachable state."""
    states: States = {}
    states.update(_crash(mp))
    states.update(_integrations(mp, tmp))
    states.update(_download(mp, tmp))
    states.update(_format(mp))
    states.update(_transcription(mp))
    states.update(_languages())
    states.update(_alerts(mp))
    return states


def _normalise(states: States, tmp: Path) -> States:
    """Replace the per-run temp folder so the fixture does not depend on it."""
    root = str(tmp)
    return {k: [[c, t.replace(root, "<tmp>").replace("\\", "/")] for c, t in v]
            for k, v in states.items()}


def test_english_texts_match_the_capture_made_before_translation(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app import i18n
    i18n.set_language("en")
    states = _normalise(capture_states(monkeypatch, tmp_path), tmp_path)
    if os.environ.get("WTS_CAPTURE_I18N") == "1":
        FIXTURE.write_text(json.dumps(states, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert states == expected
