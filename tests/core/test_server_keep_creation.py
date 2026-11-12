"""A failed receipt creation must not make completed outputs disposable."""
import builtins
import errno
import os
from pathlib import Path
import time

import pytest

from core.server import jobs as J


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("failure", ["none", "copy", "copy-and-receipt", "receipt-only"])
def test_completed_output_survives_receipt_creation_failure_and_real_restart(tmp_path, monkeypatch, nested, failure):
    complete = b"1\n00:00:00,000 --> 00:00:01,000\nCompleted result.\n"
    phase = {"completed": False}
    source_paths = []
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if (phase["completed"] and failure in ("copy-and-receipt", "receipt-only") and
                os.path.basename(os.fspath(file)) == J._KEEP_FILE and
                any(flag in mode for flag in "wax")):
            raise OSError(errno.ENOSPC, "synthetic receipt creation failure")
        return real_open(file, mode, *args, **kwargs)

    def render(task, *args, **kwargs):
        folder = Path(task.file_path).parent
        if nested:
            folder = folder / "captions"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / "done.srt"
        output.write_bytes(complete)
        source_paths.append(output)
        task.output_paths = [str(output)]
        phase["completed"] = True

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic archive failure")

    jobs_root, outputs_root = tmp_path / "jobs", tmp_path / "outputs"
    manager = J.JobManager(render, jobs_root=str(jobs_root), outputs_root=str(outputs_root), record_history=False)
    with monkeypatch.context() as fault:
        fault.setattr(builtins, "open", guarded_open)
        if failure.startswith("copy"):
            fault.setattr(J, "_copy_output_atomic", cannot_copy)
        manager.start()
        try:
            job_id = manager.submit_upload("fixture.wav", b"RIFF0000", ["srt"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job = manager.get(job_id)
                if job is not None and job.status in J._TERMINAL:
                    break
                time.sleep(0.01)
            assert job is not None and job.status == J.STATUS_FINISHED
            assert source_paths[0].read_bytes() == complete
        finally:
            manager.stop()
    work = Path(job.work_dir)
    old = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
    os.utime(work, (old, old))
    assert J._marker_owner_state((work / J._JOB_DIR_MARKER).read_text()) == "gone"
    restart = J.JobManager(render, jobs_root=str(jobs_root), outputs_root=str(outputs_root), record_history=False)
    restart.start()
    restart.stop()
    archived = outputs_root / job_id[:12] / ("captions/done.srt" if nested else "done.srt")
    assert any(path.is_file() and path.read_bytes() == complete for path in (source_paths[0], archived))
    if failure not in ("copy-and-receipt", "receipt-only"):
        assert not work.exists() and archived.read_bytes() == complete


@pytest.mark.parametrize("nested", [False, True])
def test_forced_process_exit_after_output_write_keeps_the_only_completed_copy(tmp_path, nested):
    import json
    import subprocess
    import sys

    roots = {"jobs": str(tmp_path / "jobs"), "outputs": str(tmp_path / "outputs"), "nested": nested}
    code = r"""
import json, os, sys
from pathlib import Path
from core.server import jobs as J
roots=json.loads(sys.argv[1])
def render(task,*args):
    folder=Path(task.file_path).parent
    if roots['nested']:folder=folder/'captions'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'done.srt').write_bytes(b'completed before process exit')
    os._exit(0)
m=J.JobManager(render,jobs_root=roots['jobs'],outputs_root=roots['outputs'],record_history=False)
with m._lock:job=m._new_job('upload',['srt'],'','fixture.wav')
media=Path(job.work_dir)/'fixture.wav';media.write_bytes(b'RIFF0000');job.media_path=str(media)
m._run_one(job)
raise SystemExit(91)
"""
    env = os.environ.copy()
    env["APPDATA"] = str(tmp_path / "profile")
    env["LOCALAPPDATA"] = str(tmp_path / "profile-local")
    child = subprocess.run([sys.executable, "-c", code, json.dumps(roots)],
                           capture_output=True, timeout=15, env=env)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    work = next((tmp_path / "jobs").iterdir())
    source = work / ("captions/done.srt" if nested else "done.srt")
    assert source.read_bytes() == b"completed before process exit"
    old = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
    os.utime(work, (old, old))
    manager = J.JobManager(lambda *args: None, jobs_root=roots["jobs"],
                           outputs_root=roots["outputs"], record_history=False)
    manager.start()
    manager.stop()
    archived = Path(roots["outputs"]) / work.name[:12] / source.relative_to(work)
    assert any(path.is_file() and path.read_bytes() == b"completed before process exit"
               for path in (source, archived))


@pytest.mark.parametrize("failure", ["create", "sync"])
def test_engine_never_runs_without_a_persisted_retention_guard(tmp_path, monkeypatch, failure):
    calls = []
    real_open, real_sync = builtins.open, J._strict_sync

    def blocked_open(file, mode="r", *args, **kwargs):
        if failure == "create" and os.path.basename(os.fspath(file)) == J._KEEP_FILE and "x" in mode:
            raise OSError(errno.ENOSPC, "synthetic guard creation failure")
        return real_open(file, mode, *args, **kwargs)

    def blocked_sync(file):
        if failure == "sync" and os.path.basename(os.fspath(file.name)) == J._KEEP_FILE:
            raise OSError(errno.ENOSPC, "synthetic guard sync failure")
        return real_sync(file)

    monkeypatch.setattr(builtins, "open", blocked_open)
    monkeypatch.setattr(J, "_strict_sync", blocked_sync)
    manager = J.JobManager(lambda *args: calls.append("engine"), jobs_root=str(tmp_path / "jobs"),
                           outputs_root=str(tmp_path / "outputs"), record_history=False)
    manager.start()
    try:
        job_id = manager.submit_upload("fixture.wav", b"RIFF0000", ["srt"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = manager.get(job_id)
            if job is not None and job.status in J._TERMINAL:
                break
            time.sleep(0.01)
        assert job is not None and job.status == J.STATUS_ERROR
        assert calls == [] and job.error
    finally:
        manager.stop()


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("reported", [False, True])
@pytest.mark.parametrize("outcome", ["error", "cancel"])
def test_late_engine_exit_never_discards_already_written_results(tmp_path, nested, reported, outcome):
    paths = []

    def render(task, *args):
        folder = Path(task.file_path).parent / "captions" if nested else Path(task.file_path).parent
        folder.mkdir(parents=True, exist_ok=True)
        result = folder / "done.srt"
        result.write_bytes(b"complete before late engine exit")
        paths.append(result)
        if reported:
            task.output_paths = [str(result)]
        if outcome == "error":
            raise RuntimeError("synthetic failure after completed output")
        task.cancelled = True

    root, archive = tmp_path / "jobs", tmp_path / "outputs"
    manager = J.JobManager(render, jobs_root=str(root), outputs_root=str(archive), record_history=False)
    manager.start()
    try:
        job_id = manager.submit_upload("fixture.wav", b"RIFF0000", ["srt"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = manager.get(job_id)
            if job is not None and job.status in J._TERMINAL:
                break
            time.sleep(0.01)
        assert job is not None and job.status == (J.STATUS_ERROR if outcome == "error" else J.STATUS_CANCELLED)
    finally:
        manager.stop()
    work = Path(job.work_dir)
    if work.exists():
        old = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
        os.utime(work, (old, old))
    restarted = J.JobManager(render, jobs_root=str(root), outputs_root=str(archive), record_history=False)
    restarted.start()
    restarted.stop()
    destination = archive / job_id[:12] / ("captions/done.srt" if nested else "done.srt")
    assert any(p.is_file() and p.read_bytes() == b"complete before late engine exit" for p in (paths[0], destination))
    if reported:
        assert any(fmt == "srt" for fmt, _ in job.outputs)


def test_reported_output_does_not_authorize_deleting_an_unreported_sibling(tmp_path):
    paths = []

    def render(task, *args):
        root = Path(task.file_path).parent
        known = root / "known.srt"
        hidden = root / "nested" / "unreported.txt"
        hidden.parent.mkdir()
        known.write_bytes(b"reported completed result")
        hidden.write_bytes(b"completed before result registration")
        paths.extend((known, hidden))
        task.output_paths = [str(known)]
        raise RuntimeError("synthetic interruption before registering sibling")

    root, archive = tmp_path / "jobs", tmp_path / "outputs"
    manager = J.JobManager(render, jobs_root=str(root), outputs_root=str(archive), record_history=False)
    manager.start()
    try:
        job_id = manager.submit_upload("fixture.wav", b"RIFF0000", ["srt"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = manager.get(job_id)
            if job is not None and job.status in J._TERMINAL:
                break
            time.sleep(0.01)
        assert job is not None and job.status == J.STATUS_ERROR
    finally:
        manager.stop()
    work = Path(job.work_dir)
    if work.exists():
        old = time.time() - 2 * J._STALE_JOB_DIR_AGE_S
        os.utime(work, (old, old))
    restarted = J.JobManager(render, jobs_root=str(root), outputs_root=str(archive), record_history=False)
    restarted.start()
    restarted.stop()
    assert paths[1].read_bytes() == b"completed before result registration"
    copied = archive / job_id[:12] / "known.srt"
    assert any(p.is_file() and p.read_bytes() == b"reported completed result" for p in (paths[0], copied))
    # Once every remaining result is identified, normal retry can reclaim
    # the folder without losing the previously unreported file.
    manager._write_keep_file(job, [str(path) for path in paths], uncertain=True)
    assert restarted._discard_dir(job.work_dir)
    assert not work.exists()
    assert (archive / job_id[:12] / "nested/unreported.txt").read_bytes() == b"completed before result registration"


def test_uncertain_receipt_is_fail_closed_for_legacy_readers_and_unknown_files(tmp_path):
    import json

    root = tmp_path / "jobs" / ("a" * 32)
    root.mkdir(parents=True)
    known = root / "known.srt"
    known.write_bytes(b"known result")
    unknown = root / "nested" / "unknown.txt"
    unknown.parent.mkdir()
    unknown.write_bytes(b"unregistered completed result")
    receipt = root / J._KEEP_FILE
    receipt.write_text(json.dumps({"version": 2, "uncertain": True, "paths": ["known.srt"]}))
    assert J._read_keep_list(str(receipt)) is None
    assert J._read_keep_record(str(receipt)) == (["known.srt"], True)
    # Both old list-only and v1 readers reject this entire receipt shape.
    data = json.loads(receipt.read_text())
    assert not isinstance(data, list) and data["version"] != 1
    manager = J.JobManager(lambda *args: None, jobs_root=str(root.parent),
                           outputs_root=str(tmp_path / "outputs"), record_history=False)
    assert not manager._discard_dir(str(root))
    assert unknown.read_bytes() == b"unregistered completed result"
    assert (tmp_path / "outputs" / root.name[:12] / known.name).read_bytes() == b"known result"


def test_uncertain_cleanup_does_not_follow_an_unknown_directory_link(tmp_path):
    import json
    from tests.core.test_server_output_retention import _make_directory_link

    work = tmp_path / "jobs" / ("b" * 32)
    work.mkdir(parents=True)
    source = work / "known.srt"
    source.write_bytes(b"completed result")
    outside = tmp_path / "owner-originals"
    outside.mkdir()
    original = outside / "original.txt"
    original.write_bytes(b"outside original")
    link = work / "unrecognized-link"
    _make_directory_link(link, outside)
    try:
        (work / J._KEEP_FILE).write_text(json.dumps({"version": 2, "uncertain": True, "paths": ["known.srt"]}))
        manager = J.JobManager(lambda *args: None, jobs_root=str(work.parent),
                               outputs_root=str(tmp_path / "outputs"), record_history=False)
        assert not manager._discard_dir(str(work))
        assert work.is_dir() and original.read_bytes() == b"outside original"
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()
