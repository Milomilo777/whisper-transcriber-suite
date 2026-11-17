"""Headless assistant-control security and transport checks."""
import io
import json
from unittest.mock import Mock

import pytest

from core.server import mcp


def call(name, arguments=None, peer="stdio", manager=None):
    if manager is None:
        manager = Mock()
        manager.submit_local.return_value = "job"
    return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}},
                      manager, app_version="test", client_address=peer)


def test_settings_never_expose_secrets(monkeypatch):
    from core import config
    monkeypatch.setattr(config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "server_token": "SECRET", "api_key": "SECRET"})
    response = call("get_settings")
    assert response["result"]["isError"] is False
    assert "SECRET" not in json.dumps(response)
    assert "mcp_allowed_folders" not in json.dumps(response)


@pytest.mark.parametrize("peer", ["192.168.1.2", "::1", "", "127.0.0.1.evil"])
def test_file_refused_for_nonlocal_peer(peer):
    response = call("transcribe_file", {"path": "/file.wav"}, peer)
    assert response["result"]["isError"] is True


def test_stdio_round_trip():
    from core.server.mcp_stdio import serve
    source = io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                         'invalid\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    out = io.StringIO()
    serve(Mock(), source, out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32700
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_file_allowlist_and_staging(monkeypatch, tmp_path):
    from core import config
    folder = tmp_path / "allowed"
    folder.mkdir()
    media = folder / "sample.wav"
    media.write_bytes(b"media")
    monkeypatch.setattr(config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "mcp_allowed_folders": [str(folder)]})
    manager = Mock()
    manager.submit_local.return_value = "job"
    assert call("transcribe_file", {"path": str(media)}, manager=manager)["result"]["isError"] is False
    manager.submit_local.assert_called_once()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    for path in (outside, folder / ".." / "outside.wav"):
        assert call("transcribe_file", {"path": str(path)})["result"]["isError"] is True
    link = folder / "escape.wav"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert call("transcribe_file", {"path": str(link)})["result"]["isError"] is True


@pytest.mark.parametrize("values", [{"server_token": "secret"}, {"model_path": "/tmp"},
                                   {"batch_size": True}, {"batch_size": 0},
                                   {"device": "evil"}, {"output_formats": ["evil"]},
                                   {"whisper_model": "../../evil"}, {"vad_enabled": 1}])
def test_settings_refuse_invalid(values, monkeypatch):
    from core import config
    save = Mock()
    monkeypatch.setattr(config, "save_config", save)
    response = call("set_settings", {"settings": values})
    assert response["result"]["isError"] is True
    save.assert_not_called()


def test_empty_allowlist_explains_grant(monkeypatch, tmp_path):
    from core import config
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    response = call("transcribe_file", {"path": str(tmp_path / "file.wav")})
    assert response["result"]["isError"] is True
    assert "mcp_allowed_folders" in response["result"]["content"][0]["text"]


def test_settings_save_atomic_validation(monkeypatch):
    from core import config
    cfg = dict(config.DEFAULT_CONFIG)
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    save = Mock()
    monkeypatch.setattr(config, "save_config", save)
    response = call("set_settings", {"settings": {"batch_size": 4, "language": "en"}})
    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["settings"]["language"] == "en"
    assert cfg["mcp_language"] == "en"
    save.assert_called_once_with(cfg)
    response = call("set_settings", {"settings": {"batch_size": 8, "server_token": "secret"}})
    assert response["result"]["isError"] is True
    assert cfg["batch_size"] == 4


def test_settings_save_failure_hides_paths(monkeypatch):
    from core import config
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    monkeypatch.setattr(config, "save_config", Mock(side_effect=OSError("C:/private/secret/config.json")))
    response = call("set_settings", {"settings": {"batch_size": 4}})
    assert response["result"]["isError"] is True
    assert "C:/private/secret" not in json.dumps(response)


def test_model_catalogue_has_no_paths(monkeypatch):
    from core import config, model_manager
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    monkeypatch.setattr(model_manager, "catalog_models", lambda cfg: [("tiny", "Tiny")])
    monkeypatch.setattr(model_manager, "model_downloaded", lambda cfg, slug: True)
    response = call("list_models")
    assert response["result"]["structuredContent"] == {"models": [{"id": "tiny", "installed": True}]}
    assert call("list_models", {"path": "secret"})["result"]["isError"] is True


def test_system_status_gpu_and_versions(monkeypatch):
    from core import config
    from core.server import mcp_control
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    monkeypatch.setattr(mcp_control, "models", lambda cfg: [])
    monkeypatch.setattr(mcp_control.subprocess, "run", Mock(return_value=Mock(
        returncode=0, stdout="GPU, 2048, 8192, 40\n")))
    data = call("system_status")["result"]["structuredContent"]
    assert data["gpus"] == [{"name": "GPU", "free_vram_mib": 2048,
                             "total_vram_mib": 8192, "temperature_c": 40}]
    assert "python" in data["versions"]
    assert call("system_status", {"command": "evil"})["result"]["isError"] is True


def test_local_job_preserves_original_and_exports_before_done(tmp_path):
    from core.server.jobs import JobManager, STATUS_FINISHED
    source = tmp_path / "media.wav"
    source.write_bytes(b"original")

    def transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
        output = task.file_path + ".txt"
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("transcript")
        task.output_paths = [output]

    manager = JobManager(transcribe, jobs_root=str(tmp_path / "jobs"),
                         outputs_root=str(tmp_path / "outputs"), record_history=False)
    job_id = manager.submit_local(str(source), str(tmp_path), ["txt"])
    job = manager.get(job_id)
    assert job.media_path != str(source)
    manager._run_one(job)
    assert job.status == STATUS_FINISHED
    assert source.read_bytes() == b"original"
    exported = tmp_path / f"media.{job_id}.0.txt"
    assert exported.read_text() == "transcript"
    assert manager.output_path(job_id, "txt")
    # Existing local results must not be overwritten on a repeated export.
    exported.write_text("existing")
    with pytest.raises(FileExistsError):
        manager._export_local_outputs(job)
    assert exported.read_text() == "existing"
    manager.stop()


def test_stdio_oversize_frame_and_diagnostic_isolation(monkeypatch, capsys):
    from core.server import mcp_stdio
    monkeypatch.setattr(mcp_stdio, "MAX_MESSAGE", 80)
    original = mcp.handle

    def noisy(*args, **kwargs):
        print("diagnostic")
        return original(*args, **kwargs)

    monkeypatch.setattr(mcp, "handle", noisy)
    out = io.StringIO()
    mcp_stdio.serve(Mock(), io.StringIO("x" * 100 + '\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), out)
    frames = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(frames) == 2 and frames[1]["result"] == {}
    assert "diagnostic" in capsys.readouterr().err


@pytest.mark.parametrize("peer", ["127.0.0.1", "192.168.1.20"])
def test_http_dispatch_uses_actual_peer_not_forwarded_header(peer, monkeypatch, tmp_path):
    from core import config
    from core.server.httpd import JobRequestHandler
    source = tmp_path / "sample.wav"
    source.write_bytes(b"audio")
    monkeypatch.setattr(config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "mcp_allowed_folders": [str(tmp_path)]})
    request = Mock()
    request.headers = {"Content-Type": "application/json", "X-Forwarded-For": "127.0.0.1"}
    request.client_address = (peer, 1000)
    request._read_json_body.return_value = json.dumps({"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": "transcribe_file",
        "arguments": {"path": str(source)}}}).encode()
    request._srv.manager.submit_local.return_value = "job"
    JobRequestHandler._mcp_dispatch(request)
    response = request._send_json.call_args.args[1]
    assert response["result"]["isError"] is (peer != "127.0.0.1")
    assert request._srv.manager.submit_local.called is (peer == "127.0.0.1")


def test_staging_refuses_file_swapped_after_validation(monkeypatch, tmp_path):
    from core.server import mcp_control
    from core.server.jobs import JobManager
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "sample.wav"
    source.write_bytes(b"media")
    outside = tmp_path / "private.wav"
    outside.write_bytes(b"private")
    probe = allowed / "probe.wav"
    try:
        probe.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    probe.unlink()
    original = mcp_control.allowed_file

    def swap(*args):
        result = original(*args)
        source.unlink()
        source.symlink_to(outside)
        return result

    monkeypatch.setattr(mcp_control, "allowed_file", swap)
    manager = JobManager(Mock(), jobs_root=str(tmp_path / "jobs"), record_history=False)
    with pytest.raises((OSError, ValueError)):
        manager.submit_local(str(source), str(allowed), ["txt"])
    assert manager.list() == []
    assert outside.read_bytes() == b"private"
    manager.stop()


def test_export_refuses_directory_swapped_after_validation(monkeypatch, tmp_path):
    from core.server import mcp_control
    from core.server.jobs import Job, JobManager
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sub = allowed / "sub"
    sub.mkdir()
    (sub / "sample.wav").write_bytes(b"media")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sample.wav").write_bytes(b"private")
    probe = allowed / "probe"
    try:
        probe.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    probe.unlink()
    output = tmp_path / "result.txt"
    output.write_text("transcript")
    original = mcp_control.allowed_file

    def swap(*args):
        result = original(*args)
        sub.rename(allowed / "saved")
        sub.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(mcp_control, "allowed_file", swap)
    job = Job("job", "upload", ["txt"], local_source=str(sub / "sample.wav"),
              local_root=str(allowed), outputs=[("txt", str(output))])
    manager = JobManager(Mock(), record_history=False, jobs_root=str(tmp_path / "jobs"))
    with pytest.raises((OSError, ValueError)):
        manager._export_local_outputs(job)
    assert list(outside.iterdir()) == [outside / "sample.wav"]
    manager.stop()


def test_stdio_invalid_utf8_becomes_parse_error():
    from core.server.mcp_stdio import serve
    out = io.StringIO()
    serve(Mock(), io.TextIOWrapper(io.BytesIO(b"\xff\n"), encoding="utf-8"), out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


@pytest.mark.parametrize("arguments,windowed", [(["mcp"], False),
    (["--safe-mode", "mcp"], False), (["mcp"], True)])
def test_cli_stdio_process_round_trip(tmp_path, arguments, windowed):
    import subprocess
    import sys
    import os
    if windowed and os.name != "nt":
        pytest.skip("Windows inherited pipe restoration")
    script = '''
import json, sys, platformdirs
from core import config
root = sys.argv[1]
for name in ('user_config_dir', 'user_cache_dir', 'user_data_dir', 'user_log_dir', 'user_state_dir'):
    setattr(platformdirs, name, lambda *a, **k: root)
config.load_config = lambda: dict(config.DEFAULT_CONFIG)
import gui
gui._activate_safe_mode = lambda: None
if sys.argv[3] == 'True':
    sys.stdin = sys.stdout = None
sys.argv = ['gui.py', *json.loads(sys.argv[2])]
raise SystemExit(gui.main())
'''
    frames = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-06-18"}},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 3, "method": "ping"}]
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), json.dumps(arguments), str(windowed)],
                            input="".join(json.dumps(frame) + "\n" for frame in frames),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    answers = [json.loads(line) for line in result.stdout.splitlines()]
    assert [answer["id"] for answer in answers] == [1, 2, 3]
    assert len(answers[1]["result"]["tools"]) == 10
    assert answers[2]["result"] == {}
