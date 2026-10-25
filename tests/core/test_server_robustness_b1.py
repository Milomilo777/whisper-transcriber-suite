"""Malformed or unlucky requests answer cleanly instead of killing a handler.

Covers: non-ASCII digits in the session cookie, deeply nested JSON, a full or
read-only disk while a job is created, non-finite clip times and raw
exception text in MCP tool errors.

Hermetic: loopback server with an ephemeral port, fake transcriber and fake
downloader (no network).
"""
from __future__ import annotations

import json
import logging
import os

import pytest

from core.server import auth_session, httpd, mcp
from tests.core.test_server_mcp import _call, _StubManager, _tool_err
from tests.core.test_server_openai import _json_transcribe
from tests.core.test_server_security import (
    _multipart,
    _request,
    _RunningServer,
)

SECRET_DIR = "C:\\Users\\Owner\\secret-folder"


def _no_download(url, dest_dir, limits=None):
    raise RuntimeError("no network in tests")


# --- cookie expiry ---------------------------------------------------------------

@pytest.mark.parametrize("expiry", ["\u00b2\u00b2\u00b2\u00b2",
                                    "\uff11\uff12\uff13",
                                    "\u0661\u0662\u0663"])
def test_non_ascii_digits_in_the_cookie_expiry_are_just_invalid(expiry):
    key = b"k" * 32
    assert auth_session.remaining(
        key, "tok", f"{expiry}.deadbeef", now=1000.0) == 0.0
    assert not auth_session.valid(key, "tok", f"{expiry}.x", now=1000.0)


def test_a_real_cookie_still_validates():
    key = b"k" * 32
    value = auth_session.issue(key, "tok", now=1000.0, ttl=60.0)
    assert auth_session.valid(key, "tok", value, now=1030.0)


# --- deeply nested JSON ------------------------------------------------------------

DEEP = ("[" * 200000).encode()
JSON_HEADERS = {"Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"}


def test_deeply_nested_json_is_a_400_on_the_jobs_endpoint(tmp_path):
    with _RunningServer(tmp_path, download_fn=_no_download) as srv:
        status, body = _request(srv, "POST", "/api/jobs", DEEP, JSON_HEADERS)
        assert status == 400, body
        assert b"invalid JSON" in body
        # Control: a normal body on the same server is accepted.
        ok = json.dumps({"url": "https://93.184.216.34/v"}).encode()
        status, body = _request(srv, "POST", "/api/jobs", ok, JSON_HEADERS)
        assert status == 202, body


def test_deeply_nested_json_is_a_parse_error_on_the_mcp_endpoint(tmp_path):
    with _RunningServer(tmp_path, download_fn=_no_download) as srv:
        status, body = _request(srv, "POST", "/mcp", DEEP, JSON_HEADERS)
        assert status == 400, body
        assert json.loads(body)["error"]["code"] == mcp.PARSE_ERROR
        # Control: the same server still answers a valid message.
        ping = json.dumps({"jsonrpc": "2.0", "id": 1,
                           "method": "ping"}).encode()
        status, body = _request(srv, "POST", "/mcp", ping, JSON_HEADERS)
        assert status == 200, body


# --- a disk that cannot hold the job ------------------------------------------------

def _break_job_folders(monkeypatch, jobs_root):
    real = os.makedirs

    def full_disk(path, *a, **k):
        if str(path).startswith(str(jobs_root)):
            raise OSError(28, "No space left on device",
                          os.path.join(SECRET_DIR, "jobs", "abc"))
        return real(path, *a, **k)

    monkeypatch.setattr("core.server.jobs.os.makedirs", full_disk)


def _upload_request(srv, path, fields=()):
    extra = b"".join(
        ("--BOUND\r\nContent-Disposition: form-data; "
         f'name="{name}"\r\n\r\n{value}\r\n').encode()
        for name, value in fields)
    body = extra + _multipart("a.wav", b"RIFF" + b"\0" * 64)
    headers = {"Content-Type": "multipart/form-data; boundary=BOUND"}
    return _request(srv, "POST", path, body, headers)


@pytest.mark.parametrize("kind", ["url", "upload", "openai"])
def test_a_full_disk_is_a_clean_500_without_the_reason(
        tmp_path, monkeypatch, caplog, kind):
    def send(srv):
        if kind == "url":
            body = json.dumps({"url": "https://93.184.216.34/v"}).encode()
            return _request(srv, "POST", "/api/jobs", body, JSON_HEADERS)
        if kind == "upload":
            return _upload_request(srv, "/api/jobs")
        return _upload_request(srv, "/v1/audio/transcriptions",
                               [("model", "whisper-1")])

    with _RunningServer(tmp_path, download_fn=_no_download,
                        transcribe_fn=_json_transcribe) as srv:
        # Control: the same request works while the disk is fine.
        status, body = send(srv)
        assert status in (200, 202), body
        _break_job_folders(monkeypatch, tmp_path / "server_jobs")
        with caplog.at_level(logging.WARNING, logger=httpd.logger.name):
            status, body = send(srv)
        assert status == 500, body
        text = body.decode("utf-8", "replace")
        assert "No space left" not in text and "secret-folder" not in text
        assert "could not store the job" in text
        assert any("No space left on device" in r.getMessage()
                   for r in caplog.records), "reason missing from the log"


# --- clip times ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 "nan", "inf", "-inf", "1e999", 1e999])
def test_non_finite_clip_times_count_as_missing(bad):
    assert httpd.parse_clip(bad, 5) == (None, 5.0)
    assert httpd.parse_clip(1, bad) == (1.0, None)
    assert httpd.parse_clip(bad, bad) == (None, None)


def test_normal_clip_times_are_kept():
    assert httpd.parse_clip("2", 9.5) == (2.0, 9.5)
    assert httpd.parse_clip(1, 5) == (1.0, 5.0)


# --- MCP tool errors -----------------------------------------------------------------

def test_an_unexpected_tool_failure_does_not_leak_host_paths():
    mgr = _StubManager()
    mgr.raise_on_submit = OSError(
        28, "No space left on device",
        os.path.join(SECRET_DIR, "jobs", "abc", "x.wav"))
    text = _tool_err(_call(mgr, "transcribe_url",
                           {"url": "https://example.com/v"}))
    assert "secret-folder" not in text and "Users" not in text
    assert "No space left on device" in text

