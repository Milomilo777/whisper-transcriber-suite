"""Windowless Store policy checks at executable-install and media URL seams."""
from __future__ import annotations

from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import format_service
from core import _threads, distribution, js_runtime, llama_runtime
from core import server
from core.server import jobs


@pytest.fixture
def policy(monkeypatch, request):
    value = request.param
    marker = None if value is None else {
        "schema": 1, "variant": "microsoft-store", "runtime_guards": True,
        "download_policy": value,
    }
    monkeypatch.setattr(distribution, "_store_metadata", lambda: marker)
    return value


@pytest.mark.parametrize("policy", ["retain", "omit"], indirect=True)
def test_store_deno_install_refuses_before_target_or_network(policy, monkeypatch, tmp_path):
    import requests
    asset = Mock(return_value="deno.zip")
    target = Mock(return_value=tmp_path / "new-cache/deno.exe")
    network = Mock(side_effect=AssertionError("network must not start"))
    monkeypatch.setattr(js_runtime, "release_asset_name", asset)
    monkeypatch.setattr(js_runtime, "installed_deno_path", target)
    monkeypatch.setattr(requests, "get", network)
    with pytest.raises(RuntimeError, match="Microsoft Store"):
        js_runtime.install_deno()
    asset.assert_not_called()
    target.assert_not_called()
    network.assert_not_called()
    assert not (tmp_path / "new-cache").exists()


@pytest.mark.parametrize("policy", ["retain", "omit"], indirect=True)
def test_store_llama_install_refuses_before_cache_lock_or_network(policy, monkeypatch, tmp_path):
    target = Mock(return_value=tmp_path / "new-cache")
    installed = Mock(return_value=None)
    transfer = Mock(side_effect=AssertionError("network must not start"))
    monkeypatch.setattr(llama_runtime, "runtime_root", target)
    monkeypatch.setattr(llama_runtime, "installed_server", installed)
    monkeypatch.setattr(llama_runtime.verified_download, "download_verified", transfer)
    with pytest.raises(RuntimeError, match="Microsoft Store"):
        llama_runtime.install_runtime(asset=llama_runtime.RuntimeAsset("runtime.zip", 1, "0" * 64))
    target.assert_not_called()
    installed.assert_not_called()
    transfer.assert_not_called()
    assert not (tmp_path / "new-cache").exists()


@pytest.mark.parametrize("policy", ["retain", "omit"], indirect=True)
def test_store_vc_install_refuses_before_dll_planning_or_writes(policy, monkeypatch, tmp_path):
    plan = Mock(return_value=({}, []))
    monkeypatch.setattr(llama_runtime, "plan_vc_runtime", plan)
    monkeypatch.setattr(llama_runtime.sys, "platform", "win32")
    folder = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="Microsoft Store"):
        llama_runtime.ensure_vc_runtime(folder)
    plan.assert_not_called()
    assert not folder.exists()


@pytest.mark.parametrize("policy", [None], indirect=True)
def test_direct_runtime_paths_keep_existing_install_behavior(policy, monkeypatch, tmp_path):
    deno = tmp_path / "deno.exe"
    deno.write_bytes(b"existing bundled-compatible tool")
    monkeypatch.setattr(js_runtime, "release_asset_name", lambda: "deno.zip")
    monkeypatch.setattr(js_runtime, "installed_deno_path", lambda: deno)
    assert js_runtime.install_deno() == str(deno)
    llama = tmp_path / "llama-server.exe"
    monkeypatch.setattr(llama_runtime, "installed_server", lambda: llama)
    vc = Mock(return_value=[])
    monkeypatch.setattr(llama_runtime, "ensure_vc_runtime", vc)
    assert llama_runtime.install_runtime(asset=llama_runtime.RuntimeAsset("rt.zip", 1, "0" * 64)) == llama
    vc.assert_called_once_with(tmp_path)


@pytest.mark.parametrize("policy", [None], indirect=True)
def test_direct_vc_path_keeps_list_contract(policy, monkeypatch, tmp_path):
    monkeypatch.setattr(llama_runtime.sys, "platform", "win32")
    monkeypatch.setattr(llama_runtime, "plan_vc_runtime", lambda *args: ({}, []))
    assert llama_runtime.ensure_vc_runtime(tmp_path) == []


def manager(tmp_path):
    return jobs.JobManager(lambda task: None, jobs_root=str(tmp_path / "jobs"),
                           outputs_root=str(tmp_path / "outputs"), record_history=False)


@pytest.mark.parametrize("policy", ["omit"], indirect=True)
def test_omit_url_submission_uses_value_error_before_dns_or_job_insert(policy, monkeypatch, tmp_path):
    mgr = manager(tmp_path)
    dns = Mock(return_value=True)
    insert = Mock(return_value=SimpleNamespace(job_id="job", media_path=""))
    monkeypatch.setattr(jobs, "is_safe_url", dns)
    monkeypatch.setattr(mgr, "_new_job", insert)
    monkeypatch.setattr(jobs.offline, "is_offline", lambda: False)
    with pytest.raises(ValueError, match="Microsoft Store"):
        mgr.submit_url("https://example.com/video", ["txt"])
    dns.assert_not_called()
    insert.assert_not_called()
    assert mgr._queue.empty()
    assert not (tmp_path / "jobs").exists()


@pytest.mark.parametrize("policy", [None, "retain"], indirect=True)
def test_allowed_url_submission_keeps_existing_queue_behavior(policy, monkeypatch, tmp_path):
    mgr = manager(tmp_path)
    job = SimpleNamespace(job_id="job", media_path="stale")
    monkeypatch.setattr(jobs, "is_safe_url", lambda *args, **kwargs: True)
    monkeypatch.setattr(jobs.offline, "is_offline", lambda: False)
    insert = Mock(return_value=job)
    monkeypatch.setattr(mgr, "_new_job", insert)
    assert mgr.submit_url("https://example.com/video", ["txt"]) == "job"
    assert mgr._queue.get_nowait() == "job"
    assert job.media_path == ""
    insert.assert_called_once()


@pytest.mark.parametrize("policy", ["omit"], indirect=True)
def test_omit_direct_url_download_refuses_before_lan_network_or_proxy(policy, monkeypatch, tmp_path):
    detect = Mock(return_value=True)
    fetch = Mock(return_value=str(tmp_path / "media.wav"))
    proxy = Mock(side_effect=AssertionError("proxy must not start"))
    monkeypatch.setattr(server.lanfetch, "is_lan_direct_url", detect)
    monkeypatch.setattr(server.lanfetch, "fetch", fetch)
    monkeypatch.setattr(server, "shared_proxy", proxy)
    with pytest.raises(RuntimeError, match="Microsoft Store"):
        server._download_url("https://example.com/video", str(tmp_path / "new-cache"))
    detect.assert_not_called()
    fetch.assert_not_called()
    proxy.assert_not_called()
    assert not (tmp_path / "new-cache").exists()


@pytest.mark.parametrize("policy", [None, "retain"], indirect=True)
def test_allowed_url_download_reaches_existing_downloader(policy, monkeypatch, tmp_path):
    monkeypatch.setattr(server.lanfetch, "is_lan_direct_url", lambda url: True)
    fetch = Mock(return_value=str(tmp_path / "media.wav"))
    monkeypatch.setattr(server.lanfetch, "fetch", fetch)
    assert server._download_url("https://example.com/video", str(tmp_path)) == str(tmp_path / "media.wav")
    fetch.assert_called_once_with("https://example.com/video", str(tmp_path), None)


class Var:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


def lookup_app():
    return SimpleNamespace(
        download_url_var=Var("https://example.com/video"), format_status_var=Var("Loading formats..."),
        format_lookup_after="old-timer", after_cancel=Mock(), after=Mock(return_value="new-timer"),
        audio_format_map={"old": {}}, video_format_map={"old": {}},
        audio_format_combo={"values": ["old"]}, video_format_combo={"values": ["old"]},
        audio_format_var=Var("old"), video_format_var=Var("old"),
        current_video_title="old", current_video_language="en", current_video_caption_langs={"en": "manual"},
        format_lookup_error="", pending_link_start="https://example.com/video", format_events=Queue(),
        update_caption_shortcut_state=Mock(), update_js_runtime_prompt=Mock(), set_download_duration=Mock(),
        app_config={}, entry_file=__file__, yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "",
    )


@pytest.mark.parametrize("policy", ["omit"], indirect=True)
@pytest.mark.parametrize("method", ["lookup_formats", "schedule_lookup"])
def test_omit_lookup_sets_existing_error_state_without_scheduling(policy, method, monkeypatch):
    app = lookup_app()
    thread = Mock(side_effect=AssertionError("lookup thread must not start"))
    monkeypatch.setattr(_threads, "safe_thread", thread)
    getattr(format_service.FormatService(app), method)()
    assert "Microsoft Store" in app.format_lookup_error
    assert app.format_status_var.get() == app.format_lookup_error
    assert app.format_lookup_after is None
    assert app.pending_link_start == ""
    assert not app.audio_format_map and not app.video_format_map
    assert app.audio_format_combo["values"] == [] and app.video_format_combo["values"] == []
    app.after.assert_not_called()
    thread.assert_not_called()
    app.update_js_runtime_prompt.assert_not_called()


@pytest.mark.parametrize("policy", [None, "retain"], indirect=True)
@pytest.mark.parametrize("method", ["lookup_formats", "schedule_lookup"])
def test_allowed_lookup_keeps_scheduling_behavior(policy, method, monkeypatch):
    app = lookup_app()
    thread = Mock()
    monkeypatch.setattr(_threads, "safe_thread", thread)
    monkeypatch.setattr(format_service.offline, "is_offline", lambda: False)
    monkeypatch.setattr(format_service.smtv_mod, "parse_episode_id", lambda url: None)
    getattr(format_service.FormatService(app), method)()
    if method == "schedule_lookup":
        app.after.assert_called_once()
        assert app.format_lookup_after == "new-timer"
    else:
        thread.assert_called_once()
        assert app.format_status_var.get() == "Loading formats..."


def test_invalid_store_metadata_uses_submission_and_ui_error_contracts(monkeypatch, tmp_path):
    def invalid():
        raise distribution.StoreBuildError("Invalid Store build metadata.")
    monkeypatch.setattr(distribution, "_store_metadata", invalid)
    monkeypatch.setattr(jobs, "is_safe_url", Mock(return_value=True))
    with pytest.raises(ValueError, match="metadata"):
        manager(tmp_path).submit_url("https://example.com/video", ["txt"])
    app = lookup_app()
    format_service.FormatService(app).lookup_formats()
    assert "metadata" in app.format_lookup_error
    app.after.assert_not_called()


@pytest.mark.parametrize("policy", ["retain", "omit"], indirect=True)
def test_store_policy_does_not_block_model_data_downloads(policy, monkeypatch, tmp_path):
    from core import model_download
    downloader = model_download.ModelDownloader()
    transfer = Mock(return_value=True)
    monkeypatch.setattr(downloader, "_download", transfer)
    monkeypatch.setattr(model_download, "model_complete", lambda *args: False)
    monkeypatch.setattr(model_download.offline, "require_online", lambda *args: None)
    entry = model_download.ManifestEntry("a" * 40, {"model.bin": model_download.FileInfo(1, "0" * 64)})
    folder = tmp_path / "model-cache"
    assert downloader.download("example/model", folder, entry) is True
    transfer.assert_called_once_with("example/model", folder, entry, None)


@pytest.mark.parametrize("policy", ["retain", "omit"], indirect=True)
def test_store_llm_command_resolution_refuses_cached_engine_before_execution(policy, monkeypatch, tmp_path):
    from core import local_llm_server
    engine = tmp_path / "llama-server.exe"
    engine.write_bytes(b"installed-engine fixture; never executed")
    controller = local_llm_server.LocalLLMServer.__new__(local_llm_server.LocalLLMServer)
    controller._command = None
    monkeypatch.setattr(llama_runtime, "unsupported_reason", lambda: "")
    monkeypatch.setattr(llama_runtime, "installed_server", lambda: engine)
    planning = Mock(return_value=({}, []))
    launch = Mock(side_effect=AssertionError("engine must not execute"))
    monkeypatch.setattr(llama_runtime, "plan_vc_runtime", planning)
    monkeypatch.setattr(local_llm_server.subprocess, "Popen", launch)
    with pytest.raises(distribution.StoreFeatureUnavailable, match="dynamic runtime"):
        controller._resolve_command()
    planning.assert_not_called()
    launch.assert_not_called()
    assert engine.read_bytes() == b"installed-engine fixture; never executed"
    assert not (tmp_path / llama_runtime._VC_MARKER).exists()
