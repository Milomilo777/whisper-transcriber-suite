"""A failed working-copy update must not poison the next Try it now attempt."""
import errno
from pathlib import Path

import pytest

from core import sample_clip


@pytest.fixture
def working_sample(tmp_path, monkeypatch):
    folder = tmp_path / "samples"
    folder.mkdir()
    monkeypatch.setattr(sample_clip, "samples_dir", lambda: folder)
    source = Path(sample_clip.bundled_clip_path())
    return source, folder / sample_clip.SAMPLE_CLIP_NAME


def test_same_length_damaged_sample_is_repaired(working_sample):
    source, target = working_sample
    complete = source.read_bytes()
    target.write_bytes(b"?" * len(complete))
    transcript = target.with_suffix(".srt")
    transcript.write_bytes(b"synthetic earlier transcript")
    assert sample_clip.prepare_working_copy() == str(target)
    assert target.read_bytes() == complete
    assert transcript.read_bytes() == b"synthetic earlier transcript"


@pytest.mark.parametrize("existing", [False, True])
def test_interrupted_full_size_copy_keeps_previous_sample(working_sample, monkeypatch, existing):
    source, target = working_sample
    complete = source.read_bytes()
    previous = b"synthetic earlier sample"
    if existing:
        target.write_bytes(previous)

    def fail_copy(src, destination):
        Path(destination).write_bytes(b"?" * len(complete))
        raise OSError(errno.ENOSPC, "synthetic sample copy failure")

    with monkeypatch.context() as failure:
        failure.setattr(sample_clip.shutil, "copyfile", fail_copy)
        with pytest.raises(OSError):
            sample_clip.prepare_working_copy()
        assert target.read_bytes() == previous if existing else not target.exists()
        assert list(target.parent.iterdir()) == ([target] if existing else [])
    assert sample_clip.prepare_working_copy() == str(target)
    assert target.read_bytes() == complete


@pytest.mark.parametrize("failure", ["sync", "replace"])
def test_failed_publication_preserves_previous_sample(working_sample, monkeypatch, failure):
    source, target = working_sample
    complete = source.read_bytes()
    previous = b"synthetic earlier sample"
    target.write_bytes(previous)

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic sample publication failure")

    with monkeypatch.context() as failing:
        failing.setattr(sample_clip.os, "fsync" if failure == "sync" else "replace", fail)
        with pytest.raises(OSError):
            sample_clip.prepare_working_copy()
        assert target.read_bytes() == previous
        assert list(target.parent.iterdir()) == [target]
    assert sample_clip.prepare_working_copy() == str(target)
    assert target.read_bytes() == complete


def test_identical_sample_is_reused_without_rewrite(working_sample, monkeypatch):
    source, target = working_sample
    target.write_bytes(source.read_bytes())
    stamp = target.stat().st_mtime_ns

    def unexpected_copy(*args, **kwargs):
        pytest.fail("an identical sample should be reused")

    monkeypatch.setattr(sample_clip.shutil, "copyfile", unexpected_copy)
    assert sample_clip.prepare_working_copy() == str(target)
    assert target.stat().st_mtime_ns == stamp
