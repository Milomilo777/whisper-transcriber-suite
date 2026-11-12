"""Cleanup must verify output contents before deleting the complete original."""
import errno
import json
from pathlib import Path
import stat

import pytest

from core.server import jobs as J


@pytest.fixture
def retained_job(tmp_path):
    job_id = "a" * 32
    work = tmp_path / "jobs" / job_id
    work.mkdir(parents=True)
    source = work / "transcript.srt"
    source.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nComplete transcript.\n")
    archive = tmp_path / "outputs"
    destination = archive / job_id[:12] / source.name
    destination.parent.mkdir(parents=True)
    manager = J.JobManager(
        lambda *args, **kwargs: None, jobs_root=str(work.parent),
        outputs_root=str(archive), record_history=False,
    )
    job = J.Job(job_id, "upload", ["srt"], work_dir=str(work), outputs=[("srt", str(source))])
    return manager, job, source, destination


@pytest.mark.parametrize("from_keep_list", [False, True])
def test_same_size_corrupt_archive_cannot_authorize_original_deletion(retained_job, from_keep_list):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    destination.write_bytes(b"?" * len(complete))
    if from_keep_list:
        (source.parent / J._KEEP_FILE).write_text(json.dumps([source.name]), encoding="utf-8")
    assert manager._discard_dir(job.work_dir, None if from_keep_list else job)
    assert destination.read_bytes() == complete
    assert not source.parent.exists()


@pytest.mark.parametrize("from_keep_list", [False, True])
def test_failed_full_size_copy_keeps_original_through_cleanup_retry(
    retained_job, monkeypatch, from_keep_list,
):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    if from_keep_list:
        (source.parent / J._KEEP_FILE).write_text(json.dumps([source.name]), encoding="utf-8")

    def interrupted_copy(src, dst):
        Path(dst).write_bytes(b"?" * len(complete))
        raise OSError(errno.ENOSPC, "synthetic interrupted preallocated copy")

    with monkeypatch.context() as failing:
        failing.setattr(J.shutil, "copy2", interrupted_copy)
        assert manager._archive_outputs(job) == [str(source)]
        assert not manager._discard_dir(job.work_dir, None if from_keep_list else job)
        assert source.read_bytes() == complete
    assert manager._discard_dir(job.work_dir, None if from_keep_list else job)
    assert destination.read_bytes() == complete
    assert not source.parent.exists()


def test_failed_archive_does_not_truncate_previous_copy(retained_job, monkeypatch):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    previous = b"Previously retained transcript.\n"
    destination.write_bytes(previous)

    def interrupted_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr(J.shutil, "copy2", interrupted_copy)
    assert manager._archive_outputs(job) == [str(source)]
    assert destination.read_bytes() == previous and source.read_bytes() == complete


@pytest.mark.parametrize("failure", ["sync", "replace"])
def test_publish_failure_keeps_source_and_previous_archive(retained_job, monkeypatch, failure):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    previous = b"Previously retained transcript.\n"
    destination.write_bytes(previous)

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic publish failure")

    with monkeypatch.context() as failing:
        failing.setattr(J.os, "fsync" if failure == "sync" else "replace", fail)
        assert manager._archive_outputs(job) == [str(source)]
        assert not manager._discard_dir(job.work_dir, job)
        assert source.read_bytes() == complete and destination.read_bytes() == previous
        assert list(destination.parent.iterdir()) == [destination]
    assert manager._discard_dir(job.work_dir, job)
    assert destination.read_bytes() == complete


def test_identical_readonly_archive_is_reused_without_copy(retained_job, monkeypatch):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    destination.write_bytes(complete)
    destination.chmod(stat.S_IREAD)

    def unexpected_copy(*args, **kwargs):
        pytest.fail("an identical archive should be reused")

    monkeypatch.setattr(J.shutil, "copy2", unexpected_copy)
    try:
        assert manager._discard_dir(job.work_dir, job)
        assert destination.read_bytes() == complete and not source.parent.exists()
    finally:
        destination.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_readonly_source_can_be_archived(retained_job):
    manager, job, source, destination = retained_job
    complete = source.read_bytes()
    source.chmod(stat.S_IREAD)
    try:
        assert manager._archive_outputs(job) == [str(destination)]
        assert destination.read_bytes() == complete == source.read_bytes()
    finally:
        for path in source, destination:
            if path.exists():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_large_same_size_mismatch_is_repaired(retained_job):
    manager, job, source, destination = retained_job
    complete = b"x" * (2 * 1024 * 1024) + b"complete"
    source.write_bytes(complete)
    destination.write_bytes(complete[:-1] + b"?")
    assert manager._discard_dir(job.work_dir, job)
    assert destination.read_bytes() == complete


@pytest.mark.parametrize("restart", [False, True])
def test_nested_completed_output_survives_failed_copy_and_cleanup_retry(retained_job, monkeypatch, restart):
    manager, job, source, destination = retained_job
    nested = source.parent / "exports" / "completed.srt"
    nested.parent.mkdir()
    complete = b"1\n00:00:00,000 --> 00:00:01,000\nCompleted nested transcript.\n"
    nested.write_bytes(complete)
    job.outputs = [("srt", str(nested))]

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic nested archive failure")

    with monkeypatch.context() as fault:
        fault.setattr(J, "_copy_output_atomic", cannot_copy)
        assert manager._archive_outputs(job) == [str(nested)]
        if restart:
            manager._write_keep_file(job, [str(nested)])
        assert not manager._discard_dir(job.work_dir, None if restart else job)
        assert nested.read_bytes() == complete
    assert manager._discard_dir(job.work_dir, None if restart else job)
    assert not nested.exists()
    copies = [path for path in Path(manager._outputs_root).rglob("completed.srt") if path.is_file()]
    assert len(copies) == 1 and copies[0].read_bytes() == complete


def test_archive_preserves_two_output_paths_with_identical_basename(retained_job):
    manager, job, source, destination = retained_job
    files = []
    for folder, body in [("plain", b"Plain transcript\n"), ("timed", b"[00:00:00] Timed transcript\n")]:
        path = source.parent / folder / "transcript.txt"
        path.parent.mkdir()
        path.write_bytes(body)
        files.append(path)
    job.formats = ["txt", "express_scribe"]
    job.outputs = list(zip(job.formats, map(str, files)))
    expected = [path.read_bytes() for path in files]
    copies = manager._archive_outputs(job)
    assert len(set(copies)) == 2
    assert [Path(path).read_bytes() for path in copies] == expected
    assert manager._discard_dir(job.work_dir, job)
    assert [Path(path).read_bytes() for path in copies] == expected


@pytest.mark.parametrize("bad", [
    {"version": True, "paths": ["exports/a.srt"]},
    {"version": 2, "paths": ["exports/a.srt"]},
    {"version": 1, "paths": "exports/a.srt"},
    {"version": 1, "paths": ["../outside.srt"]},
    {"version": 1, "paths": ["exports/../../outside.srt"]},
    {"version": 1, "paths": ["/outside.srt"]},
    {"version": 1, "paths": ["exports//a.srt"]},
    {"version": 1, "paths": [J._KEEP_FILE]},
])
def test_invalid_nested_receipt_never_authorizes_cleanup(retained_job, bad):
    manager, job, source, destination = retained_job
    original = source.read_bytes()
    receipt = source.parent / J._KEEP_FILE
    receipt.write_text(json.dumps(bad), encoding="utf-8")
    assert J._read_keep_list(str(receipt)) is None
    assert not manager._discard_dir(job.work_dir)
    assert source.read_bytes() == original


def test_nested_receipt_round_trip_keeps_unicode_and_old_readers_conservative(retained_job):
    manager, job, source, destination = retained_job
    nested = source.parent / "captions" / "complete-\u00e9.srt"
    nested.parent.mkdir()
    nested.write_bytes(b"completed transcript")
    manager._write_keep_file(job, [str(nested)])
    receipt = source.parent / J._KEEP_FILE
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload == {"version": 1, "paths": ["captions/complete-\u00e9.srt"]}
    # Old readers accept only lists and retain folders for every other type.
    assert not isinstance(payload, list)
    assert J._read_keep_list(str(receipt)) == ["captions/complete-\u00e9.srt"]
    assert manager._discard_dir(job.work_dir)
    assert (destination.parent / "captions" / nested.name).read_bytes() == b"completed transcript"


def test_nested_copy_failure_is_warned_and_receipted_before_history(retained_job, monkeypatch):
    manager, job, source, destination = retained_job
    nested = source.parent / "captions" / "complete.srt"
    nested.parent.mkdir()
    original = b"completed nested transcript"
    nested.write_bytes(original)
    job.outputs = [("srt", str(nested))]
    observed = []

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic nested archive failure")

    def finish_history(db, rid, item, duration, language, **kwargs):
        assert item.warning == J._UNSAVED_WARNING
        assert J._read_keep_list(str(source.parent / J._KEEP_FILE)) == ["captions/complete.srt"]
        observed.append(kwargs["output_paths"])

    monkeypatch.setattr(J, "_copy_output_atomic", cannot_copy)
    monkeypatch.setattr(manager, "_finish_history", finish_history)
    manager._settle(job, J.STATUS_FINISHED, None, None, 1.0, "en")
    assert observed == [[str(nested)]] and job.status == J.STATUS_FINISHED
    assert not manager._discard_dir(job.work_dir)
    assert nested.read_bytes() == original


def _make_directory_link(link, target):
    import os
    import subprocess

    if os.name == "nt":
        # A junction in this test's private temporary directory requires no
        # security-setting change, unlike enabling symbolic-link privileges.
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    else:
        link.symlink_to(target, target_is_directory=True)


def test_nested_receipt_cannot_copy_through_outside_directory_link(retained_job, tmp_path):
    manager, job, source, destination = retained_job
    outside = tmp_path / "outside-source"
    outside.mkdir()
    secret = outside / "outside.srt"
    secret.write_bytes(b"outside retained original")
    link = source.parent / "escape"
    _make_directory_link(link, outside)
    try:
        receipt = source.parent / J._KEEP_FILE
        receipt.write_text(json.dumps({"version": 1, "paths": ["escape/outside.srt"]}), encoding="utf-8")
        assert not manager._discard_dir(job.work_dir)
        assert secret.read_bytes() == b"outside retained original"
        assert not list(Path(manager._outputs_root).rglob("outside.srt"))
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()  # removes only the Windows junction, never its target


def test_nested_archive_cannot_replace_file_through_outside_directory_link(retained_job, tmp_path):
    manager, job, source, destination = retained_job
    nested = source.parent / "captions" / "complete.srt"
    nested.parent.mkdir()
    nested.write_bytes(b"completed nested result")
    job.outputs = [("srt", str(nested))]
    outside = tmp_path / "outside-destination"
    outside.mkdir()
    original = outside / "complete.srt"
    original.write_bytes(b"outside retained original")
    link = destination.parent / "captions"
    _make_directory_link(link, outside)
    try:
        assert manager._archive_outputs(job) == [str(nested)]
        assert not manager._discard_dir(job.work_dir, job)
        assert nested.read_bytes() == b"completed nested result"
        assert original.read_bytes() == b"outside retained original"
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_failed_copy_of_linked_output_preserves_its_job_alias_and_warning(retained_job, tmp_path, monkeypatch):
    manager, job, source, destination = retained_job
    outside = tmp_path / "linked-source"
    outside.mkdir()
    original = outside / "complete.srt"
    original.write_bytes(b"completed linked result")
    link = source.parent / "linked"
    _make_directory_link(link, outside)
    alias = link / "complete.srt"
    job.outputs = [("srt", str(alias))]

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic linked archive failure")

    monkeypatch.setattr(J, "_copy_output_atomic", cannot_copy)
    try:
        manager._settle(job, J.STATUS_FINISHED, None, None, 1.0, "en")
        assert job.warning == J._UNSAVED_WARNING
        assert J._read_keep_list(str(source.parent / J._KEEP_FILE)) == ["linked/complete.srt"]
        assert not manager._discard_dir(job.work_dir)
        assert alias.read_bytes() == original.read_bytes() == b"completed linked result"
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            link.rmdir()


@pytest.mark.parametrize("archive_fails", [False, True])
def test_http_download_identity_and_retained_nested_copies(retained_job, tmp_path, monkeypatch, archive_fails):
    import http.client
    import io
    import wave

    from core import transcriber
    from core.config import DEFAULT_CONFIG
    from tests.core.test_server_http_control import _RunningServer, _submit_upload, _wait_finished

    monkeypatch.setattr(transcriber, "config", {
        **DEFAULT_CONFIG, "output_filename_template": "{base}/../{ext}/transcript",
    })

    def render(task, *callbacks):
        # Real format writers/template/metadata; only ASR inference is replaced.
        task.output_paths = transcriber._write_outputs(
            str(Path(task.file_path).with_suffix("")),
            [{"start": 0, "end": 1, "text": "Hello"}],
            task.file_path, formats=task.output_formats,
        )

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic archive failure during HTTP job")

    payload = io.BytesIO()
    with wave.open(payload, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 16000)
    with _RunningServer(tmp_path / "http", transcribe_fn=render) as server:
        server.manager._max_jobs = 1
        with monkeypatch.context() as fault:
            if archive_fails:
                fault.setattr(J, "_copy_output_atomic", cannot_copy)
            status, submitted = _submit_upload(server, {"formats": "srt,txt"},
                                               filename="meeting.wav", file_bytes=payload.getvalue())
            assert status == 202
            job_id = submitted["job_id"]
            finished = _wait_finished(server, job_id, timeout=5)
            assert finished and finished["status"] == J.STATUS_FINISHED
            assert bool(finished.get("warning")) is archive_fails
            assert {item["fmt"] for item in finished["outputs"]} == {"srt", "txt"}
            job = server.manager.get(job_id)
            assert job is not None
            work = Path(job.work_dir)
            assert {Path(path).name for _, path in job.outputs} == {"transcript"}
            received = {}
            for fmt in ("srt", "txt"):
                connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
                try:
                    connection.request("GET", f"/api/jobs/{job_id}/result?fmt={fmt}")
                    response = connection.getresponse()
                    assert response.status == 200
                    received[fmt] = response.read()
                finally:
                    connection.close()
            assert received["txt"].decode("utf-8-sig") == "Hello\n"
            srt = received["srt"].decode("utf-8-sig")
            assert "00:00:00,000 --> 00:00:01,000" in srt and srt.rstrip().endswith("Hello")
            assert received["srt"] != received["txt"]
            # A second completed job triggers the real cap-eviction path.
            status, next_job = _submit_upload(server, {"formats": "txt"},
                                              filename="second.wav", file_bytes=payload.getvalue())
            assert status == 202 and _wait_finished(server, next_job["job_id"], timeout=5)
            assert server.manager.get(job_id) is None
            assert work.exists() is archive_fails
        if archive_fails:
            # Startup-style retry has no in-memory Job; paths come from its receipt.
            assert server.manager._discard_dir(str(work))
        assert not work.exists()
        kept = Path(server.manager._outputs_root) / job_id[:12]
        assert (kept / "srt" / "transcript").read_bytes() == received["srt"]
        assert (kept / "txt" / "transcript").read_bytes() == received["txt"]
