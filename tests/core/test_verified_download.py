"""core.verified_download: pinned size + SHA-256, resume, cancel, offline, disk space."""
from __future__ import annotations

import hashlib
import os
import threading
from collections import namedtuple
from pathlib import Path

import pytest

from core import offline
from core import verified_download as vd
from tests.core._fake_file_server import FakeFileServer

PAYLOAD = os.urandom(300_000) + b"tail"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def server():
    srv = FakeFileServer()
    srv.state.payload = PAYLOAD
    yield srv
    srv.close()


def _get(server, dest: Path, **kw):
    kw.setdefault("size", len(PAYLOAD))
    kw.setdefault("sha256", SHA)
    kw.setdefault("what", "downloading the test file")
    kw.setdefault("chunk_size", 16_384)
    return vd.download_verified(server.url(), dest, **kw)


def test_download_lands_only_after_verification(server, tmp_path):
    seen: list[tuple[int, int]] = []
    dest = tmp_path / "f.bin"
    assert _get(server, dest, progress_cb=lambda d, t: seen.append((d, t))) == dest
    assert dest.read_bytes() == PAYLOAD
    assert not vd.part_path(dest).exists()
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert server.state.ranges == [None]


def test_present_and_verified_file_sends_no_request(server, tmp_path):
    dest = tmp_path / "f.bin"
    dest.write_bytes(PAYLOAD)
    _get(server, dest)
    assert server.state.requests == 0


def test_wrong_sha256_deletes_the_bytes_and_installs_nothing(server, tmp_path):
    dest = tmp_path / "f.bin"
    with pytest.raises(vd.DownloadError, match="pinned checksum"):
        _get(server, dest, sha256="0" * 64)
    assert not dest.exists()
    assert not vd.part_path(dest).exists()


def test_a_present_file_with_the_wrong_content_is_replaced(server, tmp_path):
    dest = tmp_path / "f.bin"
    dest.write_bytes(b"x" * len(PAYLOAD))  # right size, wrong bytes
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD


def test_truncated_stream_fails_and_keeps_the_part_for_a_resume(server, tmp_path):
    dest = tmp_path / "f.bin"
    server.state.cut_after = 100_000
    with pytest.raises(vd.DownloadError, match="resumes"):
        _get(server, dest)
    assert not dest.exists()
    assert vd.part_path(dest).stat().st_size == 100_000


def test_resume_after_a_cut_asks_for_the_rest_only(server, tmp_path):
    dest = tmp_path / "f.bin"
    server.state.cut_after = 123_457
    with pytest.raises(vd.DownloadError):
        _get(server, dest)
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD
    assert server.state.ranges == [None, "bytes=123457-"]


def test_a_server_that_ignores_the_range_restarts_from_zero(server, tmp_path):
    dest = tmp_path / "f.bin"
    part = vd.part_path(dest)
    part.write_bytes(b"garbage-that-must-not-stay")
    server.state.ignore_range = True
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD  # the old prefix was dropped, not kept


def test_a_resumed_part_of_another_file_is_downloaded_again_once(server, tmp_path):
    dest = tmp_path / "f.bin"
    vd.part_path(dest).write_bytes(b"z" * 1000)  # a prefix from some other file
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD
    assert server.state.ranges == ["bytes=1000-", None]


def test_a_part_past_the_end_restarts(server, tmp_path):
    dest = tmp_path / "f.bin"
    vd.part_path(dest).write_bytes(b"y" * (len(PAYLOAD) + 10))
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD
    assert server.state.ranges == [None]


def test_a_416_for_the_resume_range_starts_over(server, tmp_path):
    dest = tmp_path / "f.bin"
    vd.part_path(dest).write_bytes(PAYLOAD[:1000])
    server.state.payload = PAYLOAD[:500]  # the server's file got shorter
    with pytest.raises(vd.DownloadError):  # pinned size no longer reachable
        _get(server, dest)
    assert server.state.ranges == ["bytes=1000-", None]


def test_a_larger_file_than_pinned_is_refused_and_deleted(server, tmp_path):
    dest = tmp_path / "f.bin"
    server.state.payload = PAYLOAD + b"extra"
    with pytest.raises(vd.DownloadError, match="larger than expected"):
        _get(server, dest)
    assert not dest.exists()
    assert not vd.part_path(dest).exists()


def test_cancel_keeps_the_part_and_installs_nothing(server, tmp_path):
    dest = tmp_path / "f.bin"
    ev = threading.Event()

    def progress(done: int, total: int) -> None:
        if done >= 50_000:
            ev.set()

    with pytest.raises(vd.DownloadCancelled):
        _get(server, dest, progress_cb=progress, cancel_event=ev)
    assert not dest.exists()
    assert 0 < vd.part_path(dest).stat().st_size < len(PAYLOAD)


def test_work_offline_refuses_before_any_request(server, tmp_path, monkeypatch):
    monkeypatch.setattr(offline, "_override", True)
    with pytest.raises(offline.OfflineModeError):
        _get(server, tmp_path / "f.bin")
    assert server.state.requests == 0


def test_not_enough_disk_space_refuses_before_any_request(server, tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(vd.shutil, "disk_usage", lambda p: usage(10**9, 10**9, 1000))
    with pytest.raises(vd.DownloadError, match="free disk space"):
        _get(server, tmp_path / "f.bin")
    assert server.state.requests == 0


def test_http_error_is_a_readable_download_error(server, tmp_path):
    server.state.status = 404
    with pytest.raises(vd.DownloadError, match="Could not download downloading the test file|404"):
        _get(server, tmp_path / "f.bin")


def test_a_second_download_of_the_same_file_is_refused_while_one_runs(server, tmp_path):
    dest = tmp_path / "f.bin"
    with vd.exclusive_lock(dest.with_name(dest.name + ".lock"), "busy"):
        with pytest.raises(vd.DownloadError, match="already being downloaded"):
            _get(server, dest)
    assert server.state.requests == 0
    _get(server, dest)  # the lock is free again
    assert dest.read_bytes() == PAYLOAD


def test_a_file_system_without_locks_goes_on_without_one(server, tmp_path, monkeypatch):
    import errno

    def no_locks(*a):
        raise OSError(errno.ENOLCK, "No locks available")

    if os.name == "nt":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", no_locks)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", no_locks)
    dest = tmp_path / "f.bin"
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD


def test_a_scanner_holding_the_file_is_waited_out(server, tmp_path, monkeypatch):
    real = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError(32, "The process cannot access the file")
        real(src, dst)

    monkeypatch.setattr(vd.os, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    dest = tmp_path / "f.bin"
    _get(server, dest)
    assert dest.read_bytes() == PAYLOAD and len(calls) == 3


def test_a_scanner_that_never_lets_go_is_a_download_error(server, tmp_path, monkeypatch):
    def held(src, dst):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(vd.os, "replace", held)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(vd.DownloadError, match="Could not save"):
        _get(server, tmp_path / "f.bin")


def test_a_redirect_from_https_to_http_is_refused():
    import http.client
    import io
    import urllib.error
    import urllib.request

    handler = vd._HttpsOnlyRedirects()
    fp, hdrs = io.BytesIO(), http.client.HTTPMessage()
    req = urllib.request.Request("https://github.com/x/releases/download/a.zip")
    with pytest.raises(urllib.error.HTTPError, match="away from https"):
        handler.redirect_request(req, fp, 302, "Found", hdrs, "http://evil.example/a.zip")
    ok = handler.redirect_request(req, fp, 302, "Found", hdrs, "https://objects.example/a.zip")
    assert ok is not None and ok.full_url == "https://objects.example/a.zip"
    plain = urllib.request.Request("http://127.0.0.1/a.zip")  # http may go anywhere
    assert handler.redirect_request(plain, fp, 302, "Found", hdrs, "http://127.0.0.1/b.zip") is not None
