"""Scratch cleanup preserves foreign data and work held by another app."""
import os
from pathlib import Path
import stat
import time

import pytest

from core import config, tts_job, voice_clone


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_cache_dir", lambda: tmp_path)
    folder = tmp_path / "voice_clone"
    folder.mkdir()
    return folder


def _age(folder, days=40):
    old = time.time() - days * 86400
    for path in [*folder.rglob("*"), folder]:
        os.utime(path, (old, old))


@pytest.mark.parametrize("name", ["voices", "models", "foreign", "20200101-000000-not-a-session",
                                 "job-music", "\u0635\u062f\u0627"])
def test_foreign_folder_survives(root, name):
    folder = root / name
    folder.mkdir()
    (folder / "keep.wav").write_bytes(b"irreplaceable")
    _age(folder)
    voice_clone.sweep_old_session_dirs()
    assert (folder / "keep.wav").read_bytes() == b"irreplaceable"


def test_all_created_folder_families_are_swept(root):
    # Both historical creators and the actual current creator.
    legacy = root / "20200101-000000"
    legacy.mkdir()
    current = Path(voice_clone.session_work_dir())
    unfinished = tts_job.open_job("kokoro", "unfinished", {}, 1.0, root=root)
    unfinished.parts_dir.mkdir(parents=True)
    unfinished.progress_path.write_text("{}", encoding="utf-8")
    finished = tts_job.open_job("kokoro", "finished", {}, 1.0, root=root)
    finished.folder.mkdir()
    finished.finished_path.write_text("{}", encoding="utf-8")
    no_piece = tts_job.open_job("kokoro", "no piece yet", {}, 1.0, root=root)
    with no_piece.claimed():
        pass
    for folder in [legacy, current, unfinished.folder, finished.folder, no_piece.folder]:
        with_lock = tts_job._JobLock(folder / tts_job.LOCK_FILE)
        with_lock.acquire()
        with_lock.release()
        _age(folder)
    voice_clone.sweep_old_session_dirs()
    # Stable locks survive cleanup so a concurrent claimant never locks an
    # unlinked inode. All saved data still has to be removed.
    assert len(list(root.iterdir())) == 5
    assert all(list(p.iterdir()) == [p / tts_job.LOCK_FILE] for p in root.iterdir())


@pytest.mark.parametrize("unfinished", [False, True])
def test_active_job_survives_even_with_ancient_timestamps(root, unfinished):
    job = tts_job.open_job("kokoro", "active job", {}, 1.0, root=root)
    with job.claimed():
        recording = job.folder / "keep.wav"
        recording.write_bytes(b"active finished work")
        if unfinished:
            job.parts_dir.mkdir(exist_ok=True)
            job.progress_path.write_text("{}", encoding="utf-8")
        _age(job.folder)
        voice_clone.sweep_old_session_dirs()
        assert job.folder.is_dir()
        assert job._lock.path.is_file()
        assert recording.read_bytes() == b"active finished work"


def test_recent_progress_extends_retention(root):
    job = tts_job.open_job("kokoro", "recent progress", {}, 1.0, root=root)
    job.parts_dir.mkdir(parents=True)
    job.progress_path.write_text("{}", encoding="utf-8")
    _age(job.folder)
    os.utime(job.progress_path, None)
    voice_clone.sweep_old_session_dirs()
    assert job.progress_path.exists()


def test_reparse_point_is_never_removed_or_traversed(root, monkeypatch):
    folder = root / "20200101-000000"
    folder.mkdir()
    _age(folder)
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == folder:
            return type("JunctionStat", (), {"st_file_attributes": stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "st_mode": stat.S_IFLNK, "st_mtime": result.st_mtime})()
        return result

    monkeypatch.setattr(Path, "lstat", reparse)
    removed = []
    monkeypatch.setattr("shutil.rmtree", lambda *args, **kwargs: removed.append(args[0]))
    voice_clone.sweep_old_session_dirs()
    assert removed == []


def test_stale_cleanup_quarantine_is_swept(root):
    folder = root / (".sweep-" + "a" * 32)
    folder.mkdir()
    (folder / 'old.wav').write_bytes(b'old')
    lock = tts_job._JobLock(folder / tts_job.LOCK_FILE)
    lock.acquire()
    lock.release()
    _age(folder)
    voice_clone.sweep_old_session_dirs()
    assert list(folder.iterdir()) == [folder / tts_job.LOCK_FILE]


def _link_directory(target, link):
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_real_directory_link_is_never_swept(root):
    target = root / "foreign"
    target.mkdir()
    saved = target / "keep.wav"
    saved.write_bytes(b"keep")
    _age(target)
    link = root / "20200101-000000"
    _link_directory(target, link)
    voice_clone.sweep_old_session_dirs()
    assert link.is_dir() and saved.read_bytes() == b"keep"


def test_linked_cache_root_is_not_traversed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_cache_dir", lambda: tmp_path)
    target = tmp_path / "foreign-root"
    owned_name = target / "20200101-000000"
    owned_name.mkdir(parents=True)
    (owned_name / "keep.wav").write_bytes(b"keep")
    _age(owned_name)
    _link_directory(target, tmp_path / "voice_clone")
    voice_clone.sweep_old_session_dirs()
    assert (owned_name / "keep.wav").read_bytes() == b"keep"


def test_job_refreshed_before_lock_is_retained(root, monkeypatch):
    job = tts_job.open_job("kokoro", "just finished", {}, 1.0, root=root)
    with job.claimed():
        pass
    _age(job.folder)
    acquire = tts_job._JobLock.acquire

    def refreshed(lock):
        acquire(lock)
        os.utime(job.folder, None)

    monkeypatch.setattr(tts_job._JobLock, "acquire", refreshed)
    voice_clone.sweep_old_session_dirs()
    assert job.folder.is_dir()


def test_job_starting_as_cleanup_releases_lock_is_preserved(root, monkeypatch):
    job = tts_job.open_job("kokoro", "starting after cleanup", {}, 1.0, root=root)
    with job.claimed():
        pass
    _age(job.folder)
    release = tts_job._JobLock.release
    next_lock = tts_job._JobLock(job._lock.path)
    restarted = []

    def restart(lock):
        release(lock)
        if not restarted:
            restarted.append(True)
            next_lock.acquire()
            (job.folder / "new.wav").write_bytes(b"new saved work")

    monkeypatch.setattr(tts_job._JobLock, "release", restart)
    try:
        voice_clone.sweep_old_session_dirs()
        assert (job.folder / "new.wav").read_bytes() == b"new saved work"
    finally:
        release(next_lock)
