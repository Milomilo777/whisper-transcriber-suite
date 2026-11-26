"""Headless assistant-control security and transport checks."""
import errno
import io
import json
import os
from types import SimpleNamespace
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


def test_missing_grant_does_not_block_another_trusted_folder(monkeypatch, tmp_path):
    from core import config

    folder = tmp_path / "connected"
    folder.mkdir()
    media = folder / "sample.wav"
    media.touch()
    monkeypatch.setattr(config, "load_config", lambda: {
        **config.DEFAULT_CONFIG,
        "mcp_allowed_folders": [str(tmp_path / "disconnected"), str(folder)],
    })
    manager = Mock()
    manager.submit_local.return_value = "job"
    assert call("transcribe_file", {"path": str(media)}, manager=manager)["result"]["isError"] is False
    assert manager.submit_local.call_args.args[:2] == (str(media.resolve()), str(folder.resolve()))


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


@pytest.mark.parametrize(("reported", "expected"), [("55.56", 56), ("61", 61), ("[N/A]", None)])
def test_system_status_reads_decimal_gpu_temperature(monkeypatch, reported, expected):
    # Recent NVIDIA drivers report temperature.gpu with decimals (seen: 59.81 on an RTX 3070).
    from core import config
    from core.server import mcp_control
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    monkeypatch.setattr(mcp_control, "models", lambda cfg: [])
    monkeypatch.setattr(mcp_control.subprocess, "run", Mock(return_value=Mock(
        returncode=0, stdout=f"GPU, 2048, 8192, {reported}\n")))
    data = call("system_status")["result"]["structuredContent"]
    assert data["gpus"][0]["temperature_c"] == expected


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


def test_local_export_publishes_only_complete_output(tmp_path, monkeypatch):
    from core.server import jobs

    source = tmp_path / "media.wav"
    source.write_bytes(b"original")
    output = tmp_path / "archived.txt"
    output.write_bytes(b"complete transcript")
    job = jobs.Job("job", "upload", ["txt"], local_source=str(source),
                   local_root=str(tmp_path), outputs=[("txt", str(output))])
    manager = object.__new__(jobs.JobManager)
    target = tmp_path / "media.job.0.txt"

    with monkeypatch.context() as patch:
        def interrupted_copy(src, dest):
            dest.write(src.read(4))
            assert not target.exists()
            raise OSError(errno.ENOSPC, "disk full")

        patch.setattr(jobs.shutil, "copyfileobj", interrupted_copy)
        with pytest.raises(OSError, match="disk full"):
            manager._export_local_outputs(job)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["archived.txt", "media.wav"]
    manager._export_local_outputs(job)
    assert target.read_bytes() == output.read_bytes()


@pytest.fixture
def posix_export(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from core.server import mcp_files

    folder = tmp_path.resolve()
    if os.name == "nt":
        # Windows cannot open directory-relative FDs. Translate them to paths
        # while leaving exclusive creation, writes and file identity to the OS.
        directory_fd = -2
        nofollow = 1 << 20
        posix_os = SimpleNamespace(**vars(os))
        posix_os.name = "posix"
        posix_os.O_NOFOLLOW = nofollow
        deferred_unlinks = set()

        def open_at(name, flags, mode, *, dir_fd):
            assert dir_fd == directory_fd
            assert flags & nofollow
            return os.open(folder / name, (flags & ~nofollow) | os.O_BINARY, mode)

        def stat_at(name, *, dir_fd, follow_symlinks):
            assert dir_fd == directory_fd
            return os.stat(folder / name, follow_symlinks=follow_symlinks)

        def unlink_at(name, *, dir_fd):
            assert dir_fd == directory_fd
            try:
                os.unlink(folder / name)
            except PermissionError:
                # POSIX permits unlink while the owned descriptor is open.
                deferred_unlinks.add(name)

        def close(fd):
            os.close(fd)
            for name in tuple(deferred_unlinks):
                os.unlink(folder / name)
                deferred_unlinks.remove(name)

        posix_os.open = open_at
        posix_os.stat = stat_at
        posix_os.unlink = unlink_at
        posix_os.close = close
        monkeypatch.setattr(mcp_files, "os", posix_os)
        monkeypatch.setattr(mcp_files, "_pinned_directory", lambda *_: nullcontext(directory_fd))
        monkeypatch.setattr(mcp_files, "opened_path", lambda _: folder)

    return mcp_files, folder


def _fail_export_link(monkeypatch, mcp_files, code):
    def fail_link(_entry, _name, *, src_dir_fd, dst_dir_fd, follow_symlinks):
        assert src_dir_fd is not None and src_dir_fd == dst_dir_fd
        assert not follow_symlinks
        raise OSError(code, "synthetic link error")

    monkeypatch.setattr(mcp_files.os, "link", fail_link)


@pytest.mark.parametrize("code", [errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP,
                                 errno.EXDEV, errno.ENOSYS, errno.EMLINK])
def test_posix_export_copies_when_hard_links_are_unavailable(posix_export, monkeypatch, code):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, code)
    name = "résumé.txt"
    payload = bytes(range(256)) * 513
    with mcp_files.confined_open(folder, folder, name, "xb") as dest:
        dest.write(payload)
        assert not (folder / name).exists()

    assert (folder / name).read_bytes() == payload
    assert list(folder.iterdir()) == [folder / name]


@pytest.mark.parametrize("code", [errno.EEXIST, errno.EACCES])
def test_posix_export_propagates_other_link_errors(posix_export, monkeypatch, code):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, code)
    with pytest.raises(OSError) as failure:
        with mcp_files.confined_open(folder, folder, "transcript.txt", "xb") as dest:
            dest.write(b"new transcript")

    assert failure.value.errno == code
    assert list(folder.iterdir()) == []


def test_posix_export_copy_refuses_an_existing_output(posix_export, monkeypatch):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, errno.EPERM)
    target = folder / "transcript.txt"
    target.write_bytes(b"previous transcript")
    with pytest.raises(FileExistsError):
        with mcp_files.confined_open(folder, folder, target.name, "xb") as dest:
            dest.write(b"new transcript")

    assert target.read_bytes() == b"previous transcript"
    assert list(folder.iterdir()) == [target]


@pytest.mark.parametrize("raises", [True, False], ids=["write-error", "short-copy"])
def test_posix_export_copy_cleans_up_partial_output(posix_export, monkeypatch, raises):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, errno.EPERM)

    def partial_copy(source, output, *args):
        output.write(source.read(3))
        output.flush()
        if raises:
            raise OSError(errno.ENOSPC, "synthetic write failure")

    monkeypatch.setattr("shutil.copyfileobj", partial_copy)
    with pytest.raises(OSError, match="synthetic write failure" if raises else "size"):
        with mcp_files.confined_open(folder, folder, "transcript.txt", "xb") as dest:
            dest.write(b"complete transcript")

    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("fail_sync", [False, True], ids=["synced", "sync-error"])
def test_posix_export_copy_syncs_the_complete_output(posix_export, monkeypatch, fail_sync):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, errno.EPERM)
    target = folder / "transcript.txt"
    payload = b"complete transcript"
    real_fsync = os.fsync
    synced = []

    def sync(fd):
        identity = os.fstat(fd)
        assert os.path.samestat(identity, target.stat())
        assert identity.st_size == len(payload)
        synced.append(fd)
        if fail_sync:
            raise OSError(errno.EIO, "synthetic sync failure")
        real_fsync(fd)

    def export():
        with mcp_files.confined_open(folder, folder, target.name, "xb") as dest:
            dest.write(payload)

    with monkeypatch.context() as patch:
        patch.setattr(mcp_files.os, "fsync", sync)
        if fail_sync:
            with pytest.raises(OSError, match="synthetic sync failure"):
                export()
        else:
            export()

    assert len(synced) == 1
    if fail_sync:
        assert list(folder.iterdir()) == []
    else:
        assert target.read_bytes() == payload
        assert list(folder.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX replacement of an open file")
def test_posix_export_copy_failure_preserves_a_replacement(posix_export, monkeypatch):
    mcp_files, folder = posix_export
    _fail_export_link(monkeypatch, mcp_files, errno.EPERM)
    target = folder / "transcript.txt"
    replacement = folder / "replacement.txt"
    replacement.write_bytes(b"other writer's transcript")

    def partial_copy(source, output):
        output.write(source.read(3))
        output.flush()
        replacement.replace(target)
        raise OSError(errno.ENOSPC, "synthetic write failure")

    monkeypatch.setattr("shutil.copyfileobj", partial_copy)
    with pytest.raises(OSError, match="synthetic write failure"):
        with mcp_files.confined_open(folder, folder, target.name, "xb") as dest:
            dest.write(b"complete transcript")

    assert target.read_bytes() == b"other writer's transcript"
    assert list(folder.iterdir()) == [target]


@pytest.fixture
def fat_inode_numbers(posix_export, monkeypatch):
    mcp_files, folder = posix_export
    fd_stat = mcp_files.os.fstat
    entry_stat = mcp_files.os.stat

    def simulate_unallocated_inode(info):
        if info.st_size:
            return info
        fields = list(info)
        fields[1] = 999_999_999
        return os.stat_result(fields)

    def stat_at(path, *args, **kwargs):
        info = entry_stat(path, *args, **kwargs)
        return simulate_unallocated_inode(info) if kwargs.get("dir_fd") is not None else info

    monkeypatch.setattr(mcp_files.os, "fstat", lambda fd: simulate_unallocated_inode(fd_stat(fd)))
    monkeypatch.setattr(mcp_files.os, "stat", stat_at)
    return mcp_files, folder


@pytest.mark.parametrize("fail_copy", [False, True], ids=["publish", "rollback"])
def test_posix_export_handles_identity_changes_after_allocation(fat_inode_numbers, monkeypatch, fail_copy):
    mcp_files, folder = fat_inode_numbers
    _fail_export_link(monkeypatch, mcp_files, errno.ENOTSUP)
    target = folder / "transcript.txt"
    payload = b"complete transcript"

    def partial(source, output):
        output.write(source.read(3))
        output.flush()
        raise OSError(errno.ENOSPC, "synthetic write failure")

    def export():
        with mcp_files.confined_open(folder, folder, target.name, "xb") as dest:
            dest.write(payload)

    if fail_copy:
        monkeypatch.setattr("shutil.copyfileobj", partial)
        with pytest.raises(OSError, match="synthetic write failure"):
            export()
        assert list(folder.iterdir()) == []
    else:
        export()
        assert target.read_bytes() == payload
        assert list(folder.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX metadata changes on an open file")
@pytest.mark.parametrize("replaced", [False, True], ids=["owned", "replaced"])
def test_posix_export_rollback_distinguishes_empty_fat_files(fat_inode_numbers, monkeypatch, replaced):
    mcp_files, folder = fat_inode_numbers
    monkeypatch.setattr(mcp_files, "sys", SimpleNamespace(platform="darwin"), raising=False)
    _fail_export_link(monkeypatch, mcp_files, errno.ENOTSUP)
    target = folder / "transcript.txt"
    timestamp = 1_800_000_000

    def fail_before_writing(_source, output):
        os.utime(output.fileno(), (timestamp, timestamp))
        if replaced:
            other = folder / "other.txt"
            other.touch()
            os.utime(other, (timestamp, timestamp))
            other.replace(target)
        raise OSError(errno.ENOSPC, "synthetic write failure")

    monkeypatch.setattr("shutil.copyfileobj", fail_before_writing)
    with pytest.raises(OSError, match="synthetic write failure"):
        with mcp_files.confined_open(folder, folder, target.name, "xb") as dest:
            dest.write(b"complete transcript")

    if replaced:
        assert list(folder.iterdir()) == [target]
        assert target.stat().st_mtime == timestamp
    else:
        assert list(folder.iterdir()) == []


def test_local_job_retains_transcript_if_original_media_is_moved(tmp_path):
    from pathlib import Path
    from core.server.jobs import JobManager, STATUS_ERROR

    source = tmp_path / "media.wav"
    source.write_bytes(b"original")

    def transcribe(task, *_args):
        source.rename(source.with_name("moved.wav"))
        result = Path(task.file_path).with_suffix(".txt")
        result.write_text("transcript", encoding="utf-8")
        task.output_paths = [str(result)]

    manager = JobManager(transcribe, jobs_root=str(tmp_path / "jobs"),
                         outputs_root=str(tmp_path / "outputs"), record_history=False)
    try:
        job_id = manager.submit_local(str(source), str(tmp_path), ["txt"])
        job = manager.get(job_id)
        manager._run_one(job)
        assert job.status == STATUS_ERROR
        assert job.warning == "Results retained by the server; saving beside the original failed."
        kept = manager.output_path(job_id, "txt")
        assert kept and Path(kept).read_text(encoding="utf-8") == "transcript"
    finally:
        manager.stop()


@pytest.mark.parametrize("first_backend", ["faster_whisper", "whisper_cpp"])
def test_stdio_reuses_models_until_their_settings_change(monkeypatch, first_backend):
    from core import config, hardware, server, transcriber
    from core.server import jobs, mcp_stdio

    cfg = {**config.DEFAULT_CONFIG, "model_path": "first", "device": "cpu",
           "transcribe_backend": first_backend}
    monkeypatch.setattr(config, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(hardware, "detect_device_for", lambda cfg: (cfg["device"], "int8"))
    monkeypatch.setattr(transcriber, "config", {})
    for key, value in (("MODEL", None), ("PIPELINE", None), ("MODEL_READY", False),
                       ("_ALT_BACKEND", None), ("_ALT_BACKEND_NAME", ""),
                       ("_DEVICE_DOWNGRADED", False), ("_CUDA_BATCH_SIZE", 0),
                       ("device", "cpu"), ("compute_type", "int8")):
        monkeypatch.setattr(transcriber, key, value)
    loads = []
    alternate = Mock()

    def load(_status):
        assert transcriber.MODEL is None
        assert transcriber._ALT_BACKEND is None
        backend = transcriber.config["transcribe_backend"]
        loads.append((backend, transcriber.config["model_path"], transcriber.device))
        if backend == "whisper_cpp":
            transcriber._ALT_BACKEND = alternate
            transcriber._ALT_BACKEND_NAME = backend
        else:
            transcriber.MODEL = object()
        transcriber.MODEL_READY = True
        return True

    monkeypatch.setattr(transcriber, "load_existing_model", load)
    decode = Mock()
    monkeypatch.setattr(server, "_real_transcribe", decode)
    factory = Mock()
    monkeypatch.setattr(jobs, "JobManager", factory)
    monkeypatch.setattr(mcp_stdio.sys, "stdin", io.StringIO())
    monkeypatch.setattr(mcp_stdio.sys, "stdout", io.StringIO())

    def serve(*_args):
        submit = factory.call_args.args[0]
        submit("first job")
        cfg["batch_size"] = 3
        submit("second job")
        assert transcriber.config["batch_size"] == 3
        cfg["transcribe_backend"] = "faster_whisper"
        cfg["model_path"] = "second"
        submit("changed model")
        cfg["device"] = "cuda"
        submit("changed device")

    monkeypatch.setattr(mcp_stdio, "serve", serve)
    assert mcp_stdio.main() == 0
    assert loads == [(first_backend, "first", "cpu"),
                     ("faster_whisper", "second", "cpu"),
                     ("faster_whisper", "second", "cuda")]
    assert alternate.unload.call_count == int(first_backend == "whisper_cpp")
    assert decode.call_count == 4


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

@pytest.mark.parametrize("enabled,ceiling", [(True, 60), (False, 70), (True, 90)])
def test_temperature_settings_save_and_reach_assistant_jobs(monkeypatch, tmp_path, enabled, ceiling):
    from core import config
    cfg = dict(config.DEFAULT_CONFIG)
    media = tmp_path / "media.wav"
    media.write_bytes(b"media")
    cfg["mcp_allowed_folders"] = [str(tmp_path)]
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    save = Mock()
    monkeypatch.setattr(config, "save_config", save)
    values = {"gpu_temperature_limit_enabled": enabled, "gpu_temperature_limit_c": ceiling}
    response = call("set_settings", {"settings": values})
    assert response["result"]["isError"] is False
    save.assert_called_once_with(cfg)
    settings = call("get_settings")["result"]["structuredContent"]["settings"]
    assert all(settings[key] == value for key, value in values.items())
    for tool, args, submit in [("transcribe_file", {"path": str(media)}, "submit_local"),
                               ("transcribe_url", {"url": "https://example.com/media"}, "submit_url")]:
        manager = Mock()
        getattr(manager, submit).return_value = "job"
        assert call(tool, args, manager=manager)["result"]["isError"] is False
        options = getattr(manager, submit).call_args.kwargs["options"]
        assert all(options[key] == value for key, value in values.items())
        assert config._validate_overrides(options, tmp_path) == options
        from core import transcriber as tr
        from core.task import TranscriptionTask
        monkeypatch.setattr(tr, "config", dict(config.DEFAULT_CONFIG))
        monkeypatch.setattr(tr, "load_config", lambda: cfg)
        (tmp_path / config.PROJECT_FILE_NAME).write_text(json.dumps(options), encoding="utf-8")
        before = dict(tr.config)
        with tr._runtime_overrides_scope(TranscriptionTask(str(media))):
            assert all(tr.config[key] == value for key, value in values.items())
        assert all(tr.config[key] == before[key] for key in values)


@pytest.mark.parametrize("values", [
    {"gpu_temperature_limit_c": 59}, {"gpu_temperature_limit_c": 91},
    {"gpu_temperature_limit_c": True}, {"gpu_temperature_limit_c": 83.0},
    {"gpu_temperature_limit_c": "83"}, {"gpu_temperature_limit_enabled": 1},
])
def test_invalid_temperature_settings_are_atomic(monkeypatch, values):
    from core import config
    cfg = dict(config.DEFAULT_CONFIG)
    original = dict(cfg)
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    save = Mock()
    monkeypatch.setattr(config, "save_config", save)
    response = call("set_settings", {"settings": {"batch_size": 4, **values}})
    assert response["result"]["isError"] is True
    save.assert_not_called()
    assert cfg == original
