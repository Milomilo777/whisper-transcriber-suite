"""Upload edge cases of the job server: client paths in the file name and empty uploads.

A client may send the whole client-side path as the multipart file name
(older browsers and some scripts do), with Windows separators even when the
server runs on macOS or Linux. The saved name must be the last component
either way, and a 0-byte upload must be refused without leaving a job behind.

Loopback sockets with ephemeral ports only; the transcriber is a fake.
"""
from __future__ import annotations

import json
import os
import posixpath

import pytest

from core.server import jobs
from core.server.jobs import _safe_filename
from tests.core.test_server_security import (
    _RunningServer,
    _multipart,
    _request,
    _wait_terminal,
)

_HEADERS = {"Content-Type": "multipart/form-data; boundary=BOUND"}


def _safe_filename_as_on_posix(monkeypatch: pytest.MonkeyPatch, name: str) -> str:
    """``_safe_filename`` with ``os.path`` swapped for ``posixpath``, as on macOS/Linux."""
    with monkeypatch.context() as patch:
        patch.setattr(jobs.os, "path", posixpath)
        return _safe_filename(name)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:\\Windows\\System32\\file.txt", "file.txt"),
        ("..\\..\\evil.wav", "evil.wav"),
        ("\\\\server\\share\\talk.mp4", "talk.mp4"),
        ("C:/mixed\\separators/clip.mp3", "clip.mp3"),
    ],
)
def test_a_windows_path_keeps_only_its_last_component(monkeypatch, raw, expected):
    assert _safe_filename_as_on_posix(monkeypatch, raw) == expected
    assert _safe_filename(raw) == expected


def test_a_windows_path_upload_is_saved_under_its_base_name(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs",
            _multipart("C:\\Users\\me\\Music\\clip.wav", b"abc"), _HEADERS)
        assert status == 202, raw
        job = _wait_terminal(srv.manager, json.loads(raw)["job_id"])
        assert os.path.basename(job.media_path) == "clip.wav"


def test_an_empty_file_upload_is_refused_and_leaves_no_job(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs", _multipart("empty.wav", b""), _HEADERS)
        assert status == 400, raw
        assert srv.manager.list() == []
        assert os.listdir(tmp_path / "server_jobs") == []
