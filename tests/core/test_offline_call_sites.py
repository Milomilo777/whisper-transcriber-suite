"""Work offline: every place that can reach the network asks core.offline first.

Each test turns the switch on in memory (``offline.set_offline(True)``; the
conftest fixture turns it off again) and makes the network primitive of that
call site fail loudly, so a call site that forgets to ask fails here. A few
tests repeat the call with the switch off as the positive control.
"""
from __future__ import annotations

import inspect
import os
import time
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

from core import offline


def _boom(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("network primitive called while offline")


@pytest.fixture
def offline_on():
    offline.set_offline(True)
    yield


# --- automatic requests: skipped quietly -------------------------------------

def test_update_check_makes_no_request(offline_on, monkeypatch):
    from core import updates

    monkeypatch.setattr(updates.urllib.request, "urlopen", _boom)
    assert updates.check_for_update() is None


def test_usage_statistics_are_not_posted(offline_on, monkeypatch):
    from core import stats

    monkeypatch.setattr(stats.threading, "Thread", _boom)
    monkeypatch.setattr(stats.urllib.request, "urlopen", _boom)
    config = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats.php"}
    assert stats.post_stats_async(config, {"model": "tiny"}) is False


def test_usage_statistics_still_post_while_online(monkeypatch):
    from core import stats

    started: list[str] = []

    class _T:
        def __init__(self, *, target, args, daemon, name):
            started.append(name)

        def start(self) -> None:
            pass

    monkeypatch.setattr(stats.threading, "Thread", _T)
    config = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats.php"}
    assert stats.post_stats_async(config, {"model": "tiny"}) is True
    assert started == ["stats-post"]


def test_crash_reports_and_launch_ping_count_as_off(offline_on, monkeypatch):
    import core.config as cfg
    from app import observability

    monkeypatch.setattr(cfg, "load_config", lambda **_k: {"telemetry_opt_in": True})
    assert observability._telemetry_opted_in() is False
    offline.set_offline(False)
    assert observability._telemetry_opted_in() is True


def test_automatic_yt_dlp_update_is_refused(offline_on, monkeypatch):
    from core import yt_dlp_update as ytu

    monkeypatch.setattr(ytu, "can_self_update", lambda _b=None: True)
    result = ytu.update_cached_copy(run=_boom, version_of=_boom)
    assert result.status == "offline" and result.completed is False
    assert ytu.result_text(result) == offline.message("updating the video downloader")


def test_server_webhook_is_not_sent(offline_on, tmp_path):
    from core.server.jobs import STATUS_FINISHED, JobManager

    sent: list[str] = []

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        base, _ = os.path.splitext(task.file_path)
        Path(f"{base}.txt").write_text("x", encoding="utf-8")

    mgr = JobManager(
        transcribe, jobs_root=str(tmp_path / "jobs"), record_history=False,
        webhook_url="https://example.invalid/hook",
        webhook_sender=lambda url, payload: sent.append(url),
    )
    mgr.start()
    try:
        jid = mgr.submit_upload("clip.mp4", b"d", ["txt"])
        deadline = time.time() + 10
        while time.time() < deadline and mgr.get(jid).status != STATUS_FINISHED:  # type: ignore[union-attr]
            time.sleep(0.02)
        assert mgr.get(jid).status == STATUS_FINISHED  # type: ignore[union-attr]
        time.sleep(0.2)
    finally:
        mgr.stop()
    assert sent == []


# --- models ------------------------------------------------------------------

def _model_config(tmp_path: Path, *, mirror: bool) -> dict[str, Any]:
    url = "https://example.invalid/models/faster-whisper-tiny.zip" if mirror else ""
    return {
        "model": {"name": "faster-whisper-tiny", "url": url, "md5": url + ".md5" if url else "",
                  "hf_repo": "Systran/faster-whisper-tiny"},
        "model_path": str(tmp_path / "hub" / "faster-whisper-tiny"),
    }


def test_installed_mirror_model_is_used_without_the_model_check(offline_on, tmp_path, monkeypatch):
    from core import model_manager as mm

    monkeypatch.setattr(mm.requests, "get", _boom)
    monkeypatch.setattr(mm, "_verify_extracted_files", _boom)
    config = _model_config(tmp_path, mirror=True)
    Path(config["model_path"]).mkdir(parents=True)
    statuses: list[str] = []
    assert mm.ensure_model(config, status_cb=statuses.append) == config["model_path"]
    assert any("offline" in s for s in statuses)


def test_installed_mirror_model_is_checked_while_online(tmp_path, monkeypatch):
    from core import model_manager as mm

    checked: list[object] = []
    monkeypatch.setattr(mm, "_verify_extracted_files", lambda *a, **k: checked.append(a) or [])
    config = _model_config(tmp_path, mirror=True)
    Path(config["model_path"]).mkdir(parents=True)
    mm.ensure_model(config)
    assert len(checked) == 1


def test_missing_mirror_model_is_refused(offline_on, tmp_path, monkeypatch):
    from core import model_manager as mm

    monkeypatch.setattr(mm.requests, "get", _boom)
    monkeypatch.setattr(mm, "_download_zip", _boom)
    monkeypatch.setattr(mm, "_download_via_huggingface", _boom)
    with pytest.raises(offline.OfflineModeError, match="downloading the model faster-whisper-tiny"):
        mm.ensure_model(_model_config(tmp_path, mirror=True))


def test_missing_hugging_face_model_is_refused_and_a_partial_folder_kept(offline_on, tmp_path, monkeypatch):
    from core import model_manager as mm

    monkeypatch.setattr(mm, "_download_via_huggingface", _boom)
    config = _model_config(tmp_path, mirror=False)
    partial = Path(config["model_path"]) / "config.json"
    partial.parent.mkdir(parents=True)
    partial.write_text("{}", encoding="utf-8")
    with pytest.raises(offline.OfflineModeError):
        mm.ensure_model(config)
    assert partial.exists()


def test_whisper_cpp_model_download_is_refused(offline_on, tmp_path, monkeypatch):
    from core.backends import whisper_cpp

    monkeypatch.setattr(whisper_cpp.urllib.request, "urlopen", _boom)
    with pytest.raises(offline.OfflineModeError):
        whisper_cpp.download_default_model(dest=tmp_path / "ggml.bin")


def test_ai_layer_model_download_is_refused(offline_on, tmp_path, monkeypatch):
    from core import llm

    monkeypatch.setattr(llm.urllib.request, "urlopen", _boom)
    with pytest.raises(offline.OfflineModeError):
        llm.download_default_model(dest=tmp_path / "model.gguf")


def test_kokoro_model_download_is_refused(offline_on, tmp_path, monkeypatch):
    import requests

    from core import tts_kokoro

    monkeypatch.setattr(tts_kokoro, "is_downloaded", lambda: False)
    monkeypatch.setattr(tts_kokoro, "model_dir", lambda: tmp_path / "kokoro")
    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(offline.OfflineModeError):
        tts_kokoro.download()


def test_demucs_gets_closed_proxies_while_offline(tmp_path, monkeypatch):
    from core import separator

    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(separator.subprocess, "run", lambda cmd, **kw: seen.append(kw))
    separator._run_demucs_cli("in.wav", tmp_path, model="htdemucs")
    offline.set_offline(True)
    separator._run_demucs_cli("in.wav", tmp_path, model="htdemucs")
    assert "env" not in seen[0]
    assert seen[1]["env"]["HTTPS_PROXY"] == "http://127.0.0.1:9"


# --- components, helpers, sites, engines -------------------------------------

def test_optional_component_is_not_installed(offline_on, monkeypatch):
    from core import optional_deps

    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps, "packages_for", lambda _f: ["some-package"])
    monkeypatch.setattr(optional_deps.subprocess, "Popen", _boom)
    lines: list[str] = []
    assert optional_deps.install("stable_ts", log_cb=lines.append) is False
    assert lines == [offline.message("installing stable_ts")]


def test_youtube_helper_is_not_installed(offline_on, tmp_path, monkeypatch):
    import requests

    from core import js_runtime

    monkeypatch.setattr(js_runtime, "release_asset_name", lambda: "deno-x86_64-pc-windows-msvc.zip")
    monkeypatch.setattr(js_runtime, "installed_deno_path", lambda: tmp_path / "deno" / "deno.exe")
    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(RuntimeError, match="Offline mode is on"):
        js_runtime.install_deno()


def test_smtv_pages_and_listing_are_not_fetched(offline_on, monkeypatch):
    from core.integrations import smtv, smtv_browse

    monkeypatch.setattr(smtv.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(smtv_browse.urllib.request, "urlopen", _boom)
    with pytest.raises(smtv.SmtvError, match="Offline mode is on"):
        smtv._http_get("https://suprememastertv.com/en1/v/1.html", timeout=1)
    with pytest.raises(smtv_browse.SmtvBrowseError, match="Offline mode is on"):
        smtv_browse.search("en", "x")
    with pytest.raises(smtv_browse.SmtvBrowseError, match="Offline mode is on"):
        smtv_browse.fetch_bytes("https://suprememastertv.com/a.jpg")


def test_gemini_engine_and_key_test_are_refused(offline_on, monkeypatch):
    from core.backends import cloud_stt

    monkeypatch.setattr(cloud_stt.urllib.request, "urlopen", _boom)
    backend = cloud_stt.CloudSttBackend({"cloud_stt_api_key": "dummy-credential-A"})
    assert backend.load() is True  # loading never touches the network
    ok, text = backend.ping_key()
    assert ok is False and text == offline.message("testing the key")
    with pytest.raises(offline.OfflineModeError):
        backend.transcribe_to_segments("clip.wav")


def test_google_cloud_engine_is_refused(offline_on):
    from core.backends.google_cloud_stt import GoogleCloudSttBackend

    with pytest.raises(offline.OfflineModeError, match="Google Cloud"):
        GoogleCloudSttBackend({}).transcribe_to_segments("clip.wav")


def test_remote_ai_provider_is_refused(offline_on, monkeypatch):
    from core import llm

    monkeypatch.setattr(llm.urllib.request, "urlopen", _boom)
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://example.invalid/v1", model="m"))
    with pytest.raises(llm.RemoteLLMError, match="Offline mode is on"):
        runner.summarise("some transcript")


# --- server ------------------------------------------------------------------

def test_server_link_job_is_refused_before_the_host_lookup(offline_on, tmp_path, monkeypatch):
    from core.server import jobs

    monkeypatch.setattr(jobs, "is_safe_url", _boom)
    mgr = jobs.JobManager(lambda *a, **k: None, jobs_root=str(tmp_path / "jobs"), record_history=False)
    with pytest.raises(ValueError, match="Offline mode is on"):
        mgr.submit_url("https://www.youtube.com/watch?v=x", ["txt"])


def test_server_link_job_queued_before_the_switch_is_not_downloaded(tmp_path, monkeypatch):
    from core.server import jobs

    monkeypatch.setattr(jobs, "is_safe_url", lambda _u: True)
    mgr = jobs.JobManager(
        lambda *a, **k: None, jobs_root=str(tmp_path / "jobs"), record_history=False,
        download_fn=_boom,
    )
    jid = mgr.submit_url("https://www.youtube.com/watch?v=x", ["txt"])
    offline.set_offline(True)
    mgr.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and mgr.get(jid).status != jobs.STATUS_ERROR:  # type: ignore[union-attr]
            time.sleep(0.02)
        job = mgr.get(jid)
    finally:
        mgr.stop()
    assert job is not None and job.status == jobs.STATUS_ERROR
    assert "Offline mode is on" in (job.error or "")


# --- Download tab ------------------------------------------------------------

class _Var:
    def __init__(self, value: Any = "") -> None:
        self.value = value

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value


def test_a_pasted_link_is_not_looked_up(offline_on, monkeypatch):
    import subprocess

    from app.services.format_service import FormatService

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr("core._threads.safe_thread", _boom)
    app = SimpleNamespace(
        download_url_var=_Var("https://www.youtube.com/watch?v=jNQXAC9IVRw"),
        format_status_var=_Var(), format_lookup_after=None, app_config={},
        audio_format_combo={}, video_format_combo={},
        audio_format_var=_Var(), video_format_var=_Var(),
    )
    FormatService(app).lookup_formats()  # type: ignore[arg-type]
    assert app.format_status_var.get() == offline.message("looking up this link")
    assert app.format_lookup_error == app.format_status_var.get()


def test_a_queued_download_is_refused_before_yt_dlp(offline_on, monkeypatch):
    from app.services import download_service as ds

    monkeypatch.setattr(ds.subprocess, "Popen", _boom)
    svc = ds.DownloadService(SimpleNamespace(download_events=Queue()))  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", _boom)
    task = SimpleNamespace(url="https://www.youtube.com/watch?v=x", caption_only=False)
    svc._run_task(task)  # type: ignore[arg-type]
    kind, got_task, text = svc.app.download_events.get_nowait()
    assert (kind, got_task, text) == ("error", task, offline.message("downloading this link"))
    assert svc.app.download_events.empty()


def test_download_buttons_ask_the_app_or_refuse(monkeypatch):
    from app.services.download_service import _may_go_online

    asked: list[str] = []
    app = SimpleNamespace(ensure_online=lambda what: asked.append(what) or False)
    assert _may_go_online(app, "Downloading this link") is False
    assert asked == ["Downloading this link"]
    offline.set_offline(True)
    assert _may_go_online(SimpleNamespace(), "x") is False
    offline.set_offline(False)
    assert _may_go_online(SimpleNamespace(), "x") is True


def test_both_download_buttons_ask_before_anything_starts():
    from app.services.download_service import DownloadService

    for method in (DownloadService.enqueue_from_form, DownloadService.enqueue_caption_only_from_form):
        src = inspect.getsource(method)
        ask = src.index("_may_go_online(app,")
        assert ask < src.index("VideoDownloadTask(\n"), method.__name__
        assert ask < src.index("process_queue()"), method.__name__


# --- the desktop app ---------------------------------------------------------

def _app_stub(cfg: dict, var: bool = False) -> SimpleNamespace:
    from app.app import App

    logs: list[str] = []
    stub = SimpleNamespace(
        app_config=cfg, work_offline_var=_Var(var), log=logs.append, logs=logs,
        titles=0, retried=0, hidden=0,
    )
    stub._refresh_window_title = lambda: setattr(stub, "titles", stub.titles + 1)
    stub._retry_refused_link_lookup = lambda: setattr(stub, "retried", stub.retried + 1)
    stub._hide_update_bar = lambda: setattr(stub, "hidden", stub.hidden + 1)
    stub._set_work_offline = lambda on: App._set_work_offline(stub, on)  # type: ignore[arg-type]
    return stub


def test_file_menu_has_the_work_offline_item():
    from app.app import _WORK_OFFLINE_LABEL, App

    src = inspect.getsource(App._build_menu)
    item = src[src.index("f.add_checkbutton("):]
    item = item[: item.index(")") + 1]
    assert "label=_WORK_OFFLINE_LABEL" in item and _WORK_OFFLINE_LABEL == "Work offline"
    assert "variable=self.work_offline_var" in item
    assert "command=self._toggle_work_offline" in item
    assert "tk.BooleanVar(value=offline.is_offline())" in src


@pytest.mark.parametrize("on", [True, False])
def test_menu_toggle_switches_and_saves(monkeypatch, on):
    import app.app as app_mod
    from app.app import App

    saved: list[dict] = []
    monkeypatch.setattr(app_mod, "save_config", lambda c: saved.append(dict(c)))
    stub = _app_stub({"work_offline": not on, "other": 1}, var=on)
    App._toggle_work_offline(stub)  # type: ignore[arg-type]
    assert offline.is_offline() is on
    assert saved == [{"work_offline": on, "other": 1}]
    assert stub.logs[-1].startswith("Work offline: on" if on else "Work offline: off")
    assert stub.titles == 1
    assert stub.retried == (0 if on else 1)


def test_turning_it_on_hides_a_shown_update_bar(monkeypatch):
    import app.app as app_mod
    from app.app import App

    monkeypatch.setattr(app_mod, "save_config", lambda c: None)
    stub = _app_stub({})
    stub._update_bar = object()
    App._set_work_offline(stub, True)  # type: ignore[arg-type]
    assert stub.hidden == 1


def test_a_failed_save_is_reported_and_the_process_stays_offline(monkeypatch):
    import app.app as app_mod
    from app.app import App

    def boom(_c):
        raise OSError("disk full")

    monkeypatch.setattr(app_mod, "save_config", boom)
    stub = _app_stub({})
    App._set_work_offline(stub, True)  # type: ignore[arg-type]
    assert offline.is_offline() is True
    assert any("Could not save the Work offline choice (disk full)" in line for line in stub.logs)


def test_advanced_dialog_close_resyncs_the_menu_and_the_switch():
    from app.app import App

    src = inspect.getsource(App.open_advanced_dialog)
    assert src.index("self.wait_window(dlg)") < src.index("self._sync_offline_menu()")
    stub = _app_stub({"work_offline": True})
    App._sync_offline_menu(stub)  # type: ignore[arg-type]
    assert offline.is_offline() is True and stub.work_offline_var.get() is True
    stub.app_config["work_offline"] = False
    App._sync_offline_menu(stub)  # type: ignore[arg-type]
    assert offline.is_offline() is False and stub.work_offline_var.get() is False
    assert stub.retried == 1


def test_advanced_dialog_saves_the_checkbox():
    from app.dialogs.advanced import AdvancedDialog

    src = inspect.getsource(AdvancedDialog)
    assert "cfg[offline.CONFIG_KEY] = bool(self._work_offline.get())" in src
    assert 'text="Work offline (also in the File menu)"' in src
    assert "variable=self._work_offline" in src


def test_ensure_online_without_the_switch_asks_nothing(monkeypatch):
    from tkinter import messagebox

    from app.app import App

    monkeypatch.setattr(messagebox, "askyesno", _boom)
    assert App.ensure_online(_app_stub({}), "Checking for updates") is True  # type: ignore[arg-type]


def test_ensure_online_no_keeps_the_switch_on(monkeypatch):
    from tkinter import messagebox

    from app.app import App

    asked: list[str] = []
    monkeypatch.setattr(messagebox, "askyesno", lambda title, text, parent=None: asked.append(text) or False)
    offline.set_offline(True)
    stub = _app_stub({"work_offline": True})
    assert App.ensure_online(stub, "Downloading this link") is False  # type: ignore[arg-type]
    assert offline.is_offline() is True
    assert asked and asked[0].startswith("Downloading this link needs the internet")
    assert stub.logs == [offline.message("downloading this link")]


def test_ensure_online_yes_turns_it_off(monkeypatch):
    from tkinter import messagebox

    import app.app as app_mod
    from app.app import App

    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(app_mod, "save_config", lambda c: None)
    offline.set_offline(True)
    stub = _app_stub({"work_offline": True}, var=True)
    assert App.ensure_online(stub, "Downloading this link") is True  # type: ignore[arg-type]
    assert offline.is_offline() is False
    assert stub.app_config["work_offline"] is False and stub.work_offline_var.get() is False


def test_user_actions_in_the_app_ask_first():
    from app.app import App

    for method, what in (
        (App._check_for_updates_manual, '"Checking for updates"'),
        (App._yt_dlp_update_now, '"Updating the video downloader"'),
        (App.install_js_runtime, '"Installing the YouTube helper"'),
    ):
        src = inspect.getsource(method)
        assert f"self.ensure_online({what})" in src, method.__name__


def test_quiet_update_check_waits_while_offline(monkeypatch):
    import app.app as app_mod
    from app.app import App

    ran: list[bool] = []
    monkeypatch.setattr(app_mod, "save_config", _boom)
    stub = SimpleNamespace(
        _closing=False, _quick_start_open=False, after=lambda *a: None,
        app_config={"update_check_enabled": True, "last_update_check": ""},
        _run_update_check=lambda manual: ran.append(manual),
    )
    offline.set_offline(True)
    App._maybe_quiet_update_check(stub)  # type: ignore[arg-type]
    assert ran == [] and stub.app_config["last_update_check"] == ""
    offline.set_offline(False)
    monkeypatch.setattr(app_mod, "save_config", lambda c: None)
    App._maybe_quiet_update_check(stub)  # type: ignore[arg-type]
    assert ran == [False]


def test_window_title_says_work_offline(monkeypatch):
    from app.app import App

    titles: list[str] = []
    stub = SimpleNamespace(_base_title="WTS v1", queue=[], download_queue=[], tray=None, title=titles.append)
    offline.set_offline(True)
    App._refresh_window_title(stub)  # type: ignore[arg-type]
    offline.set_offline(False)
    App._refresh_window_title(stub)  # type: ignore[arg-type]
    assert titles == ["WTS v1 — Work offline", "WTS v1"]


def test_retry_looks_the_link_up_again_only_after_an_offline_refusal():
    from app.app import App

    calls: list[int] = []
    service = SimpleNamespace(lookup_formats=lambda: calls.append(1))
    stub = SimpleNamespace(
        format_lookup_error=offline.message("looking up this link"),
        download_url_var=_Var("https://x"), format_service=service,
    )
    App._retry_refused_link_lookup(stub)  # type: ignore[arg-type]
    stub.format_lookup_error = "HTTP Error 403: Forbidden"
    App._retry_refused_link_lookup(stub)  # type: ignore[arg-type]
    stub.format_lookup_error = offline.message("looking up this link")
    stub.download_url_var = _Var("  ")
    App._retry_refused_link_lookup(stub)  # type: ignore[arg-type]
    assert calls == [1]


def test_app_takes_the_switch_from_the_config_before_crash_reports_start():
    from app.app import App

    src = inspect.getsource(App.__init__)
    load = src.index("self.app_config = load_config()")
    switch = src.index("offline.set_offline(offline.flag_from(self.app_config))")
    assert load < switch < src.index("init_sentry()") < src.index("send_launch_ping_async()")


def test_every_entry_point_installs_the_backstop():
    import app as app_pkg
    import gui
    from core import voice_clone_worker, worker

    for fn in (app_pkg.run, gui.main, worker.main, voice_clone_worker.main):
        assert "offline.install_network_guard()" in inspect.getsource(fn), fn.__module__
    gui_src = inspect.getsource(gui.main)
    # The worker branches return before the GUI/CLI install, so each worker installs its own.
    assert gui_src.index('"--worker" in sys.argv') < gui_src.index("offline.install_network_guard()")


# --- review follow-ups -------------------------------------------------------

def test_url_stays_local_only_for_this_computer():
    for url in ("http://localhost:11434/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8000/v1",
                "https://LOCALHOST/v1", "http://127.9.9.9"):
        assert offline.url_stays_local(url), url
    for url in ("https://api.openai.com/v1", "http://192.168.1.5:11434/v1", "http://localhost.evil.com/",
                "", "not a url", "http://[bad"):
        assert not offline.url_stays_local(url), url


def test_a_local_ai_server_still_works_while_offline(offline_on, monkeypatch):
    import json as _json

    from core import llm

    sent: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        sent.append(req.full_url)
        return _Resp()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="http://localhost:11434/v1", model="m"))
    assert runner.summarise("text") == "ok"
    assert sent == ["http://localhost:11434/v1/chat/completions"]


def test_bilingual_translation_reports_the_offline_refusal(offline_on):
    from core import llm

    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://example.invalid/v1", model="m"))
    with pytest.raises(llm.RemoteLLMError, match="Offline mode is on"):
        llm.translate_segments(runner, [{"text": "a"}, {"text": "b"}])


def test_bilingual_translation_still_skips_an_ordinary_failed_segment():
    from core import llm

    class _Runner:
        def translate(self, text, target_language="English"):
            if text == "a":
                raise llm.RemoteLLMError("HTTP 500")
            return text.upper()

    assert llm.translate_segments(_Runner(), [{"text": "a"}, {"text": "b"}]) == ["", "B"]


def _media_task() -> SimpleNamespace:
    return SimpleNamespace(
        url="https://www.youtube.com/watch?v=x", caption_only=False, format_info={},
        subtitles_enabled=True, cancelled=False, paused=False, process=None,
    )


def test_switch_turned_on_during_the_yt_dlp_update_wait_stops_the_download(monkeypatch):
    from app.services import download_service as ds

    svc = ds.DownloadService(SimpleNamespace(download_events=Queue()))  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", lambda task: offline.set_offline(True))
    monkeypatch.setattr(svc, "_subtitle_phase", _boom)
    monkeypatch.setattr(svc, "_media_phase", _boom)
    task = _media_task()
    svc._run_task(task)  # type: ignore[arg-type]
    events = []
    while not svc.app.download_events.empty():
        events.append(svc.app.download_events.get_nowait())
    assert events[-1] == ("error", task, offline.message("downloading this link"))


def test_switch_turned_on_during_the_subtitle_phase_stops_the_media_download(monkeypatch):
    from app.services import download_service as ds

    svc = ds.DownloadService(SimpleNamespace(download_events=Queue()))  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", lambda task: None)
    monkeypatch.setattr(svc, "_subtitle_phase", lambda task: offline.set_offline(True) or False)
    monkeypatch.setattr(svc, "_media_phase", _boom)
    task = _media_task()
    svc._run_task(task)  # type: ignore[arg-type]
    events = []
    while not svc.app.download_events.empty():
        events.append(svc.app.download_events.get_nowait())
    assert events[-1] == ("error", task, offline.message("downloading this link"))


def test_caption_only_task_turned_offline_while_waiting_starts_nothing(monkeypatch):
    from app.services import download_service as ds

    svc = ds.DownloadService(SimpleNamespace(download_events=Queue()))  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "maybe_update_yt_dlp", lambda task: offline.set_offline(True))
    monkeypatch.setattr(svc, "_run_caption_only_task", _boom)
    task = _media_task()
    task.caption_only = True
    svc._run_task(task)  # type: ignore[arg-type]
    events = []
    while not svc.app.download_events.empty():
        events.append(svc.app.download_events.get_nowait())
    assert events[-1] == ("error", task, offline.message("downloading this link"))


def test_download_after_yes_waits_for_the_new_lookup(monkeypatch):
    from tkinter import messagebox

    from app.services import download_service as ds

    monkeypatch.setattr(messagebox, "showwarning", _boom)
    logs: list[str] = []

    def ensure_online(_what):
        offline.set_offline(False)  # the user said Yes
        return True

    app = SimpleNamespace(
        download_url_var=_Var("https://www.youtube.com/watch?v=x"), download_folder_var=_Var("C:/dl"),
        download_mode_var=_Var("Audio"), audio_format_var=_Var(""), video_format_var=_Var(""),
        output_format_var=_Var("mp3"), ensure_online=ensure_online, log=logs.append,
        audio_format_map={}, video_format_map={},
    )
    svc = ds.DownloadService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_caption_choice", _boom)
    offline.set_offline(True)
    svc.enqueue_from_form()
    assert logs and "click Download again" in logs[-1]


def test_smtv_tab_shows_the_offline_reason():
    from app.widgets import smtv_tab

    src = inspect.getsource(smtv_tab)
    assert 'if msg.startswith("Offline mode is on"):' in src


def test_install_failures_name_the_switch(offline_on, monkeypatch):
    from core.backends import nvidia_asr

    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: False)
    statuses: list[str] = []
    backend = nvidia_asr.NvidiaAsrBackend({})
    assert backend.load(statuses.append) is False
    assert backend.get_error() == offline.message("installing the NVIDIA Parakeet engine")
    for module, needle in (
        ("app.widgets.voice_clone_tab", 'offline.message("downloading the speech model software")'),
        ("app.widgets.hardware_wizard", 'offline.message("installing GPU support")'),
        ("app.dialogs.advanced", 'offline.message("installing the Google Cloud libraries")'),
    ):
        import importlib

        assert needle in inspect.getsource(importlib.import_module(module)), module


def test_build_specs_list_the_new_module():
    root = Path(__file__).resolve().parents[2]
    for spec in ("whisper_project_onefile.spec", "whisper_project_onedir.spec",
                 "platform/macos/pyinstaller/whisper_project_mac.spec"):
        assert "'core.offline'," in (root / spec).read_text(encoding="utf-8"), spec
