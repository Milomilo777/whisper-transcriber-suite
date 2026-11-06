"""Deterministic lock seams for scratch retention."""
import os
from pathlib import Path
import stat

from core import tts_job, voice_clone
from tests.core.test_voice_clone_sweep_ownership import root, _age


def test_fresh_work_without_prior_lock_survives(root, monkeypatch):
    folder = root / '20200101-000000'
    folder.mkdir()
    _age(folder)
    acquire = tts_job._JobLock.acquire
    def fresh(lock):
        (folder / 'new.wav').write_bytes(b'finished audio')
        acquire(lock)
    monkeypatch.setattr(tts_job._JobLock, 'acquire', fresh)
    voice_clone.sweep_old_session_dirs()
    assert (folder / 'new.wav').read_bytes() == b'finished audio'


def test_dangling_lock_reparse_is_not_opened(root, monkeypatch):
    folder = root / '20200101-000000'
    folder.mkdir()
    _age(folder)
    path = folder / tts_job.LOCK_FILE
    lstat = Path.lstat
    def dangling(p, *args, **kwargs):
        if p == path:
            return type('Reparse', (), {'st_mode': stat.S_IFREG,
                'st_file_attributes': stat.FILE_ATTRIBUTE_REPARSE_POINT})()
        return lstat(p, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', dangling)
    attempts = []
    monkeypatch.setattr(tts_job._JobLock, 'acquire', lambda lock: attempts.append(lock.path))
    voice_clone.sweep_old_session_dirs()
    assert attempts == []


def test_sweep_never_unlinks_lock_after_release(root, monkeypatch):
    folder = root / '20200101-000000'
    folder.mkdir()
    lock_path = folder / tts_job.LOCK_FILE
    lock_path.write_bytes(b'0')
    _age(folder)
    release = tts_job._JobLock.release
    unlinked = []
    unlink = Path.unlink
    released = []
    def unlocked(lock):
        release(lock)
        released.append(True)
    def remove(path, *args, **kwargs):
        if path == lock_path and released:
            unlinked.append(path)
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(tts_job._JobLock, 'release', unlocked)
    monkeypatch.setattr(Path, 'unlink', remove)
    voice_clone.sweep_old_session_dirs()
    assert unlinked == []


def test_windows_active_lock_cannot_be_unlinked(root):
    if os.name != 'nt':
        return
    folder = root / '20200101-000000'
    lock = tts_job._JobLock(folder / tts_job.LOCK_FILE)
    lock.acquire()
    try:
        try:
            lock.path.unlink()
        except PermissionError:
            pass
        else:
            raise AssertionError('Windows lock unexpectedly shared DELETE')
    finally:
        lock.release()
