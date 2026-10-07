"""Security of the local web / LAN job server.

A web page the user visits, or another program on the PC, must not be able
to drive or read the server, and secrets must never reach logs or error
bodies. Each test pins one hole the server used to have:

* any website could POST ``text/plain`` JSON (a "simple" request that needs
  no CORS preflight) and start a URL job; DNS rebinding read ``/api/jobs``;
* the request line, including ``?token=``, was logged at INFO;
* error bodies carried absolute paths / raw ``OSError`` text, and long
  upload names failed on Windows;
* the handler had no socket timeout, and an unauthenticated POST with a
  huge ``Content-Length`` was drained before the 401;
* HTTPS ran the TLS handshake inside ``accept()`` on the single serve
  thread, so one idle TCP connection froze the server;
* ``allow_reuse_address`` let a second server bind a busy port on Windows.

Loopback sockets with ephemeral ports only; the transcriber is a fake.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import ssl
import subprocess
import threading
import time

import pytest

from core.server import httpd
from core.server.httpd import (
    JobHTTPServer,
    JobRequestHandler,
    host_allowed,
    is_json_content_type,
    origin_allowed,
    redact_secrets,
)
from core.server.jobs import (
    JobManager,
    _safe_filename,
    post_webhook,
    public_error_text,
    redact_paths,
    redact_url,
)


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    written = []
    for fmt in task.output_formats:
        path = f"{base}.{fmt}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"dummy {fmt}")
        written.append(path)
    task.output_paths = written
    if progress_cb:
        progress_cb(100)


class _RunningServer:
    def __init__(self, tmp_path, token="", transcribe_fn=_writing_transcribe,
                 download_fn=None, ssl_context=None):
        self.tmp_path = tmp_path
        self.token = token
        self.transcribe_fn = transcribe_fn
        self.download_fn = download_fn
        self.ssl_context = ssl_context

    def __enter__(self):
        self.manager = JobManager(
            self.transcribe_fn,
            download_fn=self.download_fn,
            jobs_root=str(self.tmp_path / "server_jobs"),
            record_history=False,
        )
        self.manager.start()
        self.server = JobHTTPServer(
            ("127.0.0.1", 0), self.manager, token=self.token,
            ssl_context=self.ssl_context,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()


def _request(srv, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _multipart(filename: str, payload: bytes, boundary: str = "BOUND") -> bytes:
    return (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode()


def _wait_terminal(manager, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job is not None and job.status in ("finished", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


# Neutral shared value for the access-password tests.
_SHARED = "letmein"

_URL_JOB = json.dumps({"url": "http://192.0.2.10/a.mp4"}).encode()


# --- S11-12: Content-Type, Origin and Host checks ----------------------------

def test_text_plain_json_post_is_refused(tmp_path):
    """A cross-site form can send text/plain without a preflight: refuse it."""
    with _RunningServer(tmp_path) as srv:
        status, body = _request(srv, "POST", "/api/jobs", _URL_JOB,
                                {"Content-Type": "text/plain"})
        assert status == 415, body
        assert srv.manager.list() == []


def test_json_post_without_content_type_is_refused(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ = _request(srv, "POST", "/api/jobs", _URL_JOB)
        assert status == 415
        assert srv.manager.list() == []


def test_cross_origin_post_is_refused(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, body = _request(srv, "POST", "/api/jobs", _URL_JOB, {
            "Content-Type": "application/json",
            "Origin": "http://evil.example",
        })
        assert status == 403, body
        assert srv.manager.list() == []


def test_cross_origin_upload_and_control_posts_are_refused(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ = _request(srv, "POST", "/api/jobs", _multipart("a.wav", b"x"), {
            "Content-Type": "multipart/form-data; boundary=BOUND",
            "Origin": "http://evil.example",
        })
        assert status == 403
        status, _ = _request(srv, "POST", "/v1/audio/transcriptions",
                             _multipart("a.wav", b"x"), {
                                 "Content-Type": "multipart/form-data; boundary=BOUND",
                                 "Origin": "http://evil.example",
                             })
        assert status == 403
        status, _ = _request(srv, "POST", "/api/jobs/abc/cancel", b"", {
            "Origin": "http://evil.example"})
        assert status == 403
        assert srv.manager.list() == []


def test_another_local_port_is_a_foreign_origin(tmp_path):
    """A dev server on localhost:3000 must not drive the API on its port."""
    with _RunningServer(tmp_path) as srv:
        status, _ = _request(srv, "POST", "/api/jobs", _URL_JOB, {
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:3000",
        })
        assert status == 403


def test_null_origin_is_refused(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, _ = _request(srv, "POST", "/api/jobs", _URL_JOB, {
            "Content-Type": "application/json", "Origin": "null"})
        assert status == 403


def test_same_origin_page_post_is_accepted(tmp_path):
    """The server's own page sends Origin == its address: accepted."""
    with _RunningServer(tmp_path, download_fn=lambda u, d: "") as srv:
        status, body = _request(srv, "POST", "/api/jobs", _URL_JOB, {
            "Content-Type": "application/json; charset=utf-8",
            "Origin": f"http://127.0.0.1:{srv.port}",
        })
        assert status == 202, body


def test_foreign_host_is_refused_without_a_token(tmp_path):
    """DNS rebinding: the browser sends the attacker's name as Host."""
    with _RunningServer(tmp_path) as srv:
        for path in ("/api/jobs", "/", "/api/health"):
            status, _ = _request(srv, "GET", path,
                                 headers={"Host": f"rebind.example:{srv.port}"})
            assert status == 403, path
        status, _ = _request(srv, "POST", "/api/jobs", _URL_JOB, {
            "Content-Type": "application/json",
            "Host": f"rebind.example:{srv.port}"})
        assert status == 403
        assert srv.manager.list() == []


@pytest.mark.parametrize("host", [
    "127.0.0.1:{port}", "localhost:{port}", "LOCALHOST:{port}", "[::1]:{port}",
    "192.168.1.42:{port}", "10.0.0.5", "{name}:{port}", "{name}.local:{port}",
])
def test_direct_host_names_are_accepted(tmp_path, host):
    name = socket.gethostname()
    with _RunningServer(tmp_path) as srv:
        value = host.format(port=srv.port, name=name)
        status, _ = _request(srv, "GET", "/api/health", headers={"Host": value})
        assert status == 200, value


def test_a_token_replaces_the_host_check(tmp_path):
    """With a token the rebinding page cannot authenticate, so any Host works
    (a reverse proxy may forward its own name)."""
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        host = {"Host": f"proxy.example:{srv.port}"}
        status, _ = _request(srv, "GET", "/api/health", headers=host)
        assert status == 401
        status, _ = _request(srv, "GET", "/api/health", headers={
            **host, "X-Auth-Token": _SHARED})
        assert status == 200


def test_host_and_origin_helpers():
    names = frozenset({"mypc", "mypc.local"})
    assert host_allowed(None, names)
    assert host_allowed("127.0.0.1:8765", names)
    assert host_allowed("[::1]:8765", names)
    assert host_allowed("MyPC:8765", names)
    assert host_allowed("mypc.local.", names)
    assert not host_allowed("evil.example:8765", names)
    assert not host_allowed("127.0.0.1.evil.example", names)
    assert not host_allowed("", names)
    assert not host_allowed("user@127.0.0.1", names)
    assert not host_allowed("127.0.0.1:notaport", names)

    assert origin_allowed(None, "127.0.0.1:8765", https=False)
    assert origin_allowed("http://127.0.0.1:8765", "127.0.0.1:8765", https=False)
    assert origin_allowed("http://LocalHost:8765", "localhost:8765", https=False)
    assert origin_allowed("http://mypc", "mypc:80", https=False)
    assert origin_allowed("https://mypc:8765", "mypc:8765", https=True)
    assert not origin_allowed("http://mypc:8765", "mypc:8765", https=True)
    assert not origin_allowed("https://mypc:8765", "mypc:8765", https=False)
    assert not origin_allowed("http://evil.example", "127.0.0.1:8765", https=False)
    assert not origin_allowed("null", "127.0.0.1:8765", https=False)
    assert not origin_allowed("http://127.0.0.1:8765", None, https=False)

    assert is_json_content_type("application/json")
    assert is_json_content_type("Application/JSON; charset=utf-8")
    assert not is_json_content_type("text/plain")
    assert not is_json_content_type("application/x-www-form-urlencoded")
    assert not is_json_content_type(None)


# --- S11-7: the token never reaches the log ----------------------------------

def test_query_token_is_redacted_in_the_request_log(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="core.server.httpd")
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        status, _ = _request(srv, "GET", f"/api/jobs?token={_SHARED}")
        assert status == 200
        status, _ = _request(srv, "GET", f"/api/health?fmt=x&%74oken={_SHARED}")
        assert status == 200
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "/api/jobs?token=[redacted]" in text
    assert _SHARED not in text


def test_redact_secrets_variants():
    assert redact_secrets("GET /a?token=s3 HTTP/1.1") == "GET /a?token=[redacted] HTTP/1.1"
    assert redact_secrets("/r?fmt=srt&token=s3&x=1") == "/r?fmt=srt&token=[redacted]&x=1"
    assert "s3" not in redact_secrets("/r?TOKEN=s3")
    assert "s3" not in redact_secrets("/r?%74oken=s3")
    assert redact_secrets("/r?tokens=keep") == "/r?tokens=keep"
    assert redact_secrets("no query here") == "no query here"


# --- S11-8: the page reads ?token= once and drops it from the address --------

def test_page_adopts_a_token_from_the_address_and_removes_it():
    page = (httpd._STATIC_DIR + os.sep + "index.html")
    with open(page, encoding="utf-8") as f:
        text = f.read()
    assert "new URLSearchParams(location.search)" in text
    assert 'params.get("token")' in text
    assert 'params.delete("token")' in text
    assert "history.replaceState(" in text
    # The token is kept for this tab only, never in long-lived storage.
    assert "localStorage" not in text
    assert "sessionStorage" in text


# --- S11-17: no absolute paths in error bodies; long names fit ---------------

_PATHY = OSError(22, "Invalid argument", r"C:\Users\someone\AppData\Local\Temp\x\clip.wav")


def test_upload_save_error_body_has_no_path(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise _PATHY
    monkeypatch.setattr(JobRequestHandler, "_copy_range", staticmethod(_boom))
    with _RunningServer(tmp_path) as srv:
        for path in ("/api/jobs", "/v1/audio/transcriptions"):
            body = _multipart("clip.wav", b"RIFF")
            if path.startswith("/v1"):
                body = body.replace(b"--BOUND--", (
                    b"--BOUND\r\nContent-Disposition: form-data; name=\"model\""
                    b"\r\n\r\nwhisper-1\r\n--BOUND--"))
            status, raw = _request(srv, "POST", path, body, {
                "Content-Type": "multipart/form-data; boundary=BOUND"})
            assert status == 500, raw
            assert b"Users" not in raw and b"Temp" not in raw and b"Errno" not in raw, raw


def test_long_upload_name_is_shortened_and_saved(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, raw = _request(srv, "POST", "/api/jobs",
                               _multipart("a" * 300 + ".wav", b"RIFF" * 4), {
                                   "Content-Type": "multipart/form-data; boundary=BOUND"})
        assert status == 202, raw
        job = _wait_terminal(srv.manager, json.loads(raw)["job_id"])
        assert job.status == "finished", job.error
        name = os.path.basename(job.media_path)
        assert name.endswith(".wav") and len(name) <= 120


def test_safe_filename_caps_length_and_trailing_dots():
    assert _safe_filename("a" * 300 + ".wav") == "a" * 100 + ".wav"
    long_ext = _safe_filename("clip." + "x" * 50)
    assert len(long_ext) <= 120
    assert _safe_filename("name. . .wav") == "name. . .wav"
    assert _safe_filename("trailing. .") == "trailing"
    assert _safe_filename("CON" + "." + "x" * 40).startswith("_CON")
    assert _safe_filename("ok.wav") == "ok.wav"


def test_job_error_hides_paths_and_commands(tmp_path):
    def _oserror(task, *_a, **_k):
        raise PermissionError(13, "Permission denied", task.file_path)

    with _RunningServer(tmp_path, transcribe_fn=_oserror) as srv:
        status, raw = _request(srv, "POST", "/api/jobs", _multipart("c.wav", b"x"), {
            "Content-Type": "multipart/form-data; boundary=BOUND"})
        job = _wait_terminal(srv.manager, json.loads(raw)["job_id"])
        assert job.status == "error"
        assert job.error == "Permission denied: c.wav"
        status, raw = _request(srv, "GET", f"/api/jobs/{job.job_id}")
        assert str(tmp_path).encode() not in raw


def test_public_error_text_and_redact_paths():
    err = subprocess.CalledProcessError(
        1, [r"C:\Program Files\WTS\bin\yt-dlp.exe", "--", "https://x.example/v"],
        stderr="WARNING: x\nERROR: [generic] Unable to download webpage\n")
    assert public_error_text(err) == (
        "yt-dlp.exe failed (exit code 1): ERROR: [generic] Unable to download webpage")
    assert public_error_text(RuntimeError("no media file to transcribe")) == (
        "no media file to transcribe")
    assert redact_paths(r"cannot open 'C:\\Users\\me\\x\\clip.wav' now") == (
        "cannot open 'clip.wav' now")
    assert redact_paths(r"cannot open C:\Users\me\clip.wav") == "cannot open clip.wav"
    assert redact_paths("no such file: /home/me/jobs/abc/clip.wav") == (
        "no such file: clip.wav")
    assert redact_paths("Unsupported URL: https://x.example/a/b") == (
        "Unsupported URL: https://x.example/a/b")


# --- S11-18: socket timeout; no drain before a 401 ---------------------------

def test_handler_has_a_socket_timeout():
    assert JobRequestHandler.timeout is not None
    assert 0 < JobRequestHandler.timeout <= 120


def test_idle_client_is_disconnected(tmp_path, monkeypatch):
    monkeypatch.setattr(JobRequestHandler, "timeout", 0.5)
    with _RunningServer(tmp_path) as srv:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
        try:
            t0 = time.time()
            assert s.recv(10) == b""   # the server closed the idle connection
            assert time.time() - t0 < 5
        finally:
            s.close()


def test_unauthenticated_huge_post_is_refused_without_reading_it(tmp_path):
    with _RunningServer(tmp_path, token=_SHARED) as srv:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        try:
            s.sendall(
                b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Content-Type: multipart/form-data; boundary=B\r\n"
                b"Content-Length: 104857600\r\n\r\n")
            head = s.recv(200)   # times out (5 s) if the server drains first
            assert head.startswith(b"HTTP/1.1 401"), head
        finally:
            s.close()


# --- S11-1: the TLS handshake cannot freeze the server -----------------------

def test_idle_tls_connection_does_not_block_other_clients(tmp_path):
    from core.server import tls

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    tls.generate_self_signed_cert(cert, key)
    ctx = tls.build_server_ssl_context(cert, key)
    with _RunningServer(tmp_path, ssl_context=ctx) as srv:
        idle = socket.create_connection(("127.0.0.1", srv.port))
        try:
            time.sleep(0.3)
            conn = http.client.HTTPSConnection(
                "127.0.0.1", srv.port, timeout=5,
                context=ssl._create_unverified_context())
            try:
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                assert resp.status == 200
                resp.read()
            finally:
                conn.close()
        finally:
            idle.close()


def test_plain_http_to_the_tls_port_is_refused(tmp_path):
    from core.server import tls

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    tls.generate_self_signed_cert(cert, key)
    ctx = tls.build_server_ssl_context(cert, key)
    with _RunningServer(tmp_path, ssl_context=ctx) as srv:
        with pytest.raises((OSError, http.client.HTTPException)):
            _request(srv, "GET", "/api/health")
        conn = http.client.HTTPSConnection(
            "127.0.0.1", srv.port, timeout=5,
            context=ssl._create_unverified_context())
        conn.request("GET", "/api/health")
        assert conn.getresponse().status == 200
        conn.close()


# --- S11-2: a busy port is reported, never shared ----------------------------

def test_second_server_cannot_bind_a_busy_port(tmp_path):
    with _RunningServer(tmp_path) as srv:
        other = JobManager(_writing_transcribe, record_history=False,
                           jobs_root=str(tmp_path / "other"))
        with pytest.raises(OSError):
            JobHTTPServer(("127.0.0.1", srv.port), other)


def test_server_can_rebind_its_port_right_after_stopping(tmp_path):
    with _RunningServer(tmp_path) as srv:
        port = srv.port
        assert _request(srv, "GET", "/api/health")[0] == 200
    again = JobHTTPServer(("127.0.0.1", port), JobManager(
        _writing_transcribe, record_history=False,
        jobs_root=str(tmp_path / "again")))
    again.server_close()


# --- optional: the webhook URL is not logged ---------------------------------

def test_webhook_url_is_not_logged(caplog):
    caplog.set_level(logging.INFO, logger="core.server.jobs")
    post_webhook(f"http://127.0.0.1/hook/{_SHARED}?k={_SHARED}", {})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "refusing webhook" in text
    assert _SHARED not in text
    assert redact_url("https://someone@hooks.example:8443/x/y?z=1") == (
        "https://hooks.example:8443/...")
    assert redact_url("not a url") == "<invalid URL>"
