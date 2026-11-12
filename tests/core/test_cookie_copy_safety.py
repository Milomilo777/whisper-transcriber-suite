"""Failed cookie isolation must never hand the original file to a writer."""
import errno
from pathlib import Path

import pytest

from app.domain import cookies as ck
from app.services.download_service import DownloadService
from tests.core.test_download_cookie_retry import _app, _drain, _task
from tests.core.test_format_service import _LookupApp, _run_lookup


@pytest.fixture
def cookie_source(tmp_path, monkeypatch):
    source = tmp_path / "cookies.txt"
    source.write_bytes(b"# Netscape HTTP Cookie File\n# Synthetic empty cookie jar.\n")
    private = tmp_path / "private"
    private.mkdir()
    mkstemp = ck.tempfile.mkstemp
    monkeypatch.setattr(ck.tempfile, "mkstemp", lambda **kwargs: mkstemp(**kwargs, dir=private))
    monkeypatch.setattr(ck, "_COPIES", [])
    return source, private


def fail_copy(monkeypatch, phase):
    def failed_create(**kwargs):
        raise OSError(errno.ENOSPC, "synthetic temporary storage failure")

    def failed_copy(source, destination):
        Path(destination).write_bytes(b"synthetic partial copy")
        raise OSError(errno.ENOSPC, "synthetic copy storage failure")

    if phase == "create":
        monkeypatch.setattr(ck.tempfile, "mkstemp", failed_create)
    else:
        monkeypatch.setattr(ck.shutil, "copyfile", failed_copy)


@pytest.mark.parametrize("phase", ["create", "copy"])
def test_copy_failure_raises_and_removes_partial_file(cookie_source, monkeypatch, phase):
    source, private = cookie_source
    original = source.read_bytes()
    fail_copy(monkeypatch, phase)
    with pytest.raises(OSError):
        ck.private_cookies_copy(str(source))
    assert source.read_bytes() == original
    assert list(private.iterdir()) == [] and ck._COPIES == []


@pytest.mark.parametrize("phase", ["create", "copy"])
def test_format_lookup_reports_copy_failure_without_starting_yt_dlp(cookie_source, monkeypatch, phase):
    source, private = cookie_source
    original = source.read_bytes()
    fail_copy(monkeypatch, phase)
    app = _LookupApp(str(source))
    calls = _run_lookup(monkeypatch, app, [(0, "{}", "")])
    assert calls == []
    event = app.format_events.get_nowait()
    assert event[0] == "error" and "private" in event[2].lower()
    assert source.read_bytes() == original and not list(private.iterdir())


@pytest.mark.parametrize("phase", ["create", "copy"])
def test_download_worker_reports_one_error_before_cookie_consumer(cookie_source, monkeypatch, phase):
    from core import yt_dlp_update

    source, private = cookie_source
    original = source.read_bytes()
    fail_copy(monkeypatch, phase)
    app = _app(str(source))
    service = DownloadService(app)
    consumers = []
    monkeypatch.setattr(service, "_start_history", lambda task: None)
    monkeypatch.setattr(service, "maybe_update_yt_dlp", lambda task: None)
    monkeypatch.setattr(yt_dlp_update, "begin_download", lambda key: None)
    monkeypatch.setattr(yt_dlp_update, "end_download", lambda key: None)

    def consume(task, run_generation=None):
        consumers.append(service._cookies_setting())

    monkeypatch.setattr(service, "_media_phase", consume)
    service._run_task(_task())
    assert consumers == []
    terminal = [event for event in _drain(app) if event[0] in {"error", "done", "done_full"}]
    assert len(terminal) == 1 and terminal[0][0] == "error"
    assert "private" in str(terminal[0][2]).lower()
    assert source.read_bytes() == original and not list(private.iterdir())


def test_failed_copy_cleanup_is_retried_when_unlink_was_blocked(cookie_source, monkeypatch):
    source, private = cookie_source
    original = source.read_bytes()
    fail_copy(monkeypatch, "copy")
    unlink = ck.os.unlink

    def blocked(path, *args, **kwargs):
        if Path(path).parent == private:
            raise PermissionError("synthetic temporary file lock")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as locked:
        locked.setattr(ck.os, "unlink", blocked)
        with pytest.raises(OSError):
            ck.private_cookies_copy(str(source))
    assert len(ck._COPIES) == 1 and Path(ck._COPIES[0]).is_file()
    ck._remove_copies()
    assert ck._COPIES == [] and list(private.iterdir()) == []
    assert source.read_bytes() == original


def test_rotation_preserves_locked_partial_copy_for_exit_cleanup(cookie_source, monkeypatch):
    source, private = cookie_source
    copy = ck.shutil.copyfile
    unlink = ck.os.unlink
    monkeypatch.setattr(ck, "_MAX_COPIES", 1)
    locked_files = set()

    def blocked(path, *args, **kwargs):
        if path in locked_files:
            raise PermissionError("synthetic temporary file lock")
        return unlink(path, *args, **kwargs)

    def interrupted(src, dst):
        Path(dst).write_bytes(b"synthetic partial copy")
        locked_files.add(dst)
        raise OSError(errno.ENOSPC, "synthetic copy storage failure")

    monkeypatch.setattr(ck.os, "unlink", blocked)
    with monkeypatch.context() as failing:
        failing.setattr(ck.shutil, "copyfile", interrupted)
        with pytest.raises(OSError):
            ck.private_cookies_copy(str(source))
    assert len(locked_files) == 1
    first = ck.private_cookies_copy(str(source))
    second = ck.private_cookies_copy(str(source))
    assert copy is ck.shutil.copyfile and first != second
    assert locked_files.issubset(set(ck._COPIES))
    locked_files.clear()
    ck._remove_copies()
    assert list(private.iterdir()) == [] and ck._COPIES == []
