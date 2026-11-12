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
