"""Real recovery ZIPs retain exact source binding and survive failed delivery."""
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import threading
import zipfile

import pytest

from core import _checkpoint, config, convert
from core.writers import bilingual_srt


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / "source.json"
    segments = [{"start": 1.25, "end": 3.5, "text": "Original words", "speaker": "Speaker 1"}]
    source.write_text(json.dumps(segments), encoding="utf-8")
    return source, segments, tmp_path / "result.srt"


def save(sample, translated="Translated words"):
    source, segments, target = sample
    return bilingual_srt.save_result(segments, [translated], source_json=str(source),
                                     language="French", target=str(target))


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        return archive.read("translation.srt"), json.loads(archive.read("metadata.json"))


def test_self_contained_zip_binds_exact_payload_and_request_snapshot(sample):
    source, segments, target = sample
    source_bytes = source.read_bytes()
    result = save(sample)
    assert result.saved_path == str(target) and result.recovery_path and not result.error
    body, metadata = read_archive(result.recovery_path)
    assert body == target.read_bytes() == result.body.encode("utf-8")
    assert b"00:00:01,250 --> 00:00:03,500" in body and b"\r" not in body
    assert metadata["version"] == 1 and metadata["source_json"] == str(source.resolve())
    assert metadata["segments_sha256"] == hashlib.sha256(json.dumps(
        segments, ensure_ascii=True, sort_keys=True,
    ).encode()).hexdigest()
    assert metadata["translation_sha256"] == hashlib.sha256(body).hexdigest()
    assert source.read_bytes() == source_bytes


def test_archive_is_closed_and_readable_before_output_publication(sample, monkeypatch):
    install = convert._install_new_output
    checked = []

    def check_recovery_before_output(staged, target):
        archives = list((config.user_data_dir() / "translation-recovery").glob("bilingual-*.zip"))
        assert len(archives) == 1
        assert b"Translated words" in read_archive(archives[0])[0]
        checked.append(True)
        return install(staged, target)

    monkeypatch.setattr(convert, "_install_new_output", check_recovery_before_output)
    result = save(sample)
    assert checked and result.saved_path


@pytest.mark.parametrize("damage", ["truncated", "edited_payload", "foreign_metadata"])
def test_retry_keeps_damaged_or_edited_archive_and_creates_a_bound_copy(sample, damage):
    result = save(sample)
    archive_path = Path(result.recovery_path)
    old_body, metadata = read_archive(archive_path)
    if damage == "truncated":
        archive_path.write_bytes(b"incomplete archive")
    else:
        if damage == "foreign_metadata":
            metadata["source_json"] = "foreign-request.json"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("translation.srt", b"user-edited translation" if damage == "edited_payload" else old_body)
            archive.writestr("metadata.json", json.dumps(metadata))
    edited = archive_path.read_bytes()
    previous_output = Path(result.saved_path)
    output_bytes = previous_output.read_bytes()
    bilingual_srt.retry_save(result)
    assert result.recovery_path != str(archive_path)
    assert archive_path.read_bytes() == edited
    assert previous_output.read_bytes() == output_bytes
    assert read_archive(result.recovery_path)[0] == old_body
    assert Path(result.saved_path).read_bytes() == old_body


@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC])
def test_recovery_sync_failure_is_not_advertised_as_a_verified_copy(sample, monkeypatch, code):
    fsync = os.fsync
    calls = []

    def first_sync_fails(fd):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError(code, "synthetic archive sync failure")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", first_sync_fails)
    result = save(sample)
    assert calls and result.recovery_path is None and result.recovery_error
    assert result.saved_path and not result.error
    retained = list((config.user_data_dir() / "translation-recovery").glob("*.zip"))
    assert retained, "uncertain bytes must be retained rather than deleted"
    assert Path(result.saved_path).read_bytes() == result.body.encode("utf-8")


def test_unsupported_fsync_keeps_both_usable_outputs(sample, monkeypatch):
    def unsupported(fd):
        raise OSError(errno.EINVAL, "synthetic fsync unsupported")

    monkeypatch.setattr(os, "fsync", unsupported)
    result = save(sample)
    assert result.saved_path and result.recovery_path and not result.error
    assert read_archive(result.recovery_path)[0] == Path(result.saved_path).read_bytes()


def test_failed_output_sync_keeps_recovery_and_existing_new_file_for_retry(sample, monkeypatch):
    strict = _checkpoint._strict_sync
    calls = []

    def fail_output_sync(stream):
        calls.append(True)
        if len(calls) == 2:
            raise OSError(errno.EIO, "synthetic final output sync failure")
        strict(stream)

    monkeypatch.setattr(_checkpoint, "_strict_sync", fail_output_sync)
    result = save(sample)
    previous = sample[2].read_bytes()
    archive_path = result.recovery_path
    assert result.saved_path is None and result.error and archive_path
    bilingual_srt.retry_save(result)
    assert result.saved_path != str(sample[2]) and result.recovery_path == archive_path
    assert sample[2].read_bytes() == previous == Path(result.saved_path).read_bytes()


def test_changed_destination_never_discards_owner_edit_or_recovery(sample, monkeypatch):
    publish = convert._publish_new_output

    def edit_after_publication(target, payload):
        path = publish(target, payload)
        Path(path).write_bytes(b"other editor's completed changes")
        return path

    with monkeypatch.context() as editor:
        editor.setattr(convert, "_publish_new_output", edit_after_publication)
        result = save(sample)
    assert result.saved_path is None and result.error and result.recovery_path
    assert sample[2].read_bytes() == b"other editor's completed changes"
    bilingual_srt.retry_save(result)
    assert result.saved_path and sample[2].read_bytes() == b"other editor's completed changes"


def test_parallel_requests_keep_independent_archives_and_outputs(sample, monkeypatch):
    install = convert._install_new_output
    barrier = threading.Barrier(2)
    thread = threading.local()

    def install_together(staged, target):
        if not getattr(thread, "staged", False):
            thread.staged = True
            barrier.wait(timeout=10)
        return install(staged, target)

    monkeypatch.setattr(convert, "_install_new_output", install_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, sample, "FIRST TRANSLATION")
        second = pool.submit(save, sample, "SECOND TRANSLATION")
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert len({result.saved_path for result in results}) == 2
    assert len({result.recovery_path for result in results}) == 2
    for result in results:
        assert result.saved_path and result.recovery_path and not result.error
        assert read_archive(result.recovery_path)[0] == Path(result.saved_path).read_bytes()
