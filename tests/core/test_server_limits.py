"""Resource limits and request guards of the job server (finding set C266-A).

* the number of simultaneous connections is capped (a flood of idle sockets
  used to start one thread each, without limit) and the surplus gets a fast
  503;
* a client that trickles bytes can no longer hold a handler thread past a total
  time budget, for the request line + headers and for an upload body;
* a full job queue is answered before the upload body is written to disk;
* an English-only Whisper model refuses a request in another language instead
  of returning made-up English;
* out-of-range web options are clamped instead of silently dropped.

Loopback sockets with ephemeral ports only; the transcriber is a fake.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from core.server import httpd
from core.server.httpd import (
    JobHTTPServer,
    JobRequestHandler,
    english_only_problem,
    normalize_options,
)
from core.server.jobs import JobManager
from tests.core.test_server_security import (
    _RunningServer,
    _multipart,
    _request,
    _writing_transcribe,
)

_BOUNDARY_HDR = {"Content-Type": "multipart/form-data; boundary=BOUND"}


def _read_status(sock: socket.socket) -> bytes:
    """First bytes the server sends, or b"" when it just closed."""
    try:
        return sock.recv(4096)
    except OSError:
        return b""


def _closed_by_server(sock: socket.socket, within: float) -> bool:
    """True when the server ends the connection (EOF or reset) in time."""
    sock.settimeout(within)
    try:
        data = sock.recv(4096)
    except socket.timeout:
        return False
    except OSError:
        return True
    return data == b"" or not data.startswith(b"HTTP/1.1 2")


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class _Server:
    """A JobHTTPServer with explicit constructor arguments."""

    def __init__(self, tmp_path, **kw):
        self.manager = JobManager(
            _writing_transcribe, jobs_root=str(tmp_path / "jobs"),
            record_history=False, max_queued=kw.pop("max_queued", 50))
        self.manager.start()
        self.server = JobHTTPServer(("127.0.0.1", 0), self.manager, **kw)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.stop()


@pytest.fixture
def small_server(tmp_path):
    srv = _Server(tmp_path, max_connections=3)
    yield srv
    srv.close()


# --- connection cap ------------------------------------------------------------

def test_connections_beyond_the_cap_get_a_fast_503(small_server):
    held = []
    try:
        for _ in range(3):
            s = socket.create_connection(("127.0.0.1", small_server.port))
            s.sendall(b"GET /api/he")  # half a request line: the handler waits
            held.append(s)
        assert _wait_until(
            lambda: small_server.server.active_connections() == 3)
        extra = socket.create_connection(("127.0.0.1", small_server.port),
                                         timeout=3)
        started = time.monotonic()
        reply = _read_status(extra)
        extra.close()
        assert reply.startswith(b"HTTP/1.1 503"), reply
        assert time.monotonic() - started < 2.0
        assert small_server.server.active_connections() == 3
    finally:
        for s in held:
            s.close()


def test_a_slot_is_free_again_after_a_client_leaves(small_server):
    held = []
    for _ in range(3):
        s = socket.create_connection(("127.0.0.1", small_server.port))
        s.sendall(b"GET /api/he")
        held.append(s)
    assert _wait_until(lambda: small_server.server.active_connections() == 3)
    held.pop().close()
    assert _wait_until(lambda: small_server.server.active_connections() == 2)
    status, body = _request(small_server, "GET", "/api/health")
    assert status == 200, body
    for s in held:
        s.close()
    assert _wait_until(lambda: small_server.server.active_connections() == 0)


def test_the_default_cap_is_sane():
    assert 16 <= httpd._MAX_CONNECTIONS <= 256


# --- total time budgets --------------------------------------------------------

def test_a_header_trickle_is_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_HEADER_TOTAL_S", 0.6)
    monkeypatch.setattr(httpd, "_WATCH_TICK_S", 0.05)
    srv = _Server(tmp_path, max_connections=4)
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        # A byte every 0.1 s never trips the 60 s per-read timeout; only the
        # total budget can end this.
        try:
            for ch in b"GET /api/health HTTP/1.1\r\nX-Slow: aaaa":
                s.sendall(bytes([ch]))
                time.sleep(0.1)
        except OSError:
            pass  # the server already cut the connection
        assert _closed_by_server(s, 4.0)
        s.close()
        assert _wait_until(lambda: srv.server.active_connections() == 0)
    finally:
        srv.close()


def test_a_normal_request_still_works_with_the_deadlines(tmp_path):
    srv = _Server(tmp_path)
    try:
        status, body = _request(srv, "GET", "/api/health")
        assert status == 200, body
    finally:
        srv.close()


def test_an_upload_trickle_is_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_UPLOAD_BASE_S", 0.6)
    monkeypatch.setattr(httpd, "_WATCH_TICK_S", 0.05)
    srv = _Server(tmp_path, max_connections=4)
    try:
        full = _multipart("clip.wav", b"x" * 5000)
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall(
            b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(full)}\r\n\r\n".encode() + full[:10])
        # The client now goes quiet (a trickle that never completes). The
        # per-read timeout is 60 s, so only the total budget can end this.
        assert _closed_by_server(s, 4.0)
        s.close()
        assert srv.manager.list() == []  # no job from the partial upload
        assert _wait_until(lambda: srv.server.active_connections() == 0)
    finally:
        srv.close()


def test_a_normal_upload_still_works(tmp_path):
    srv = _Server(tmp_path)
    try:
        status, body = _request(srv, "POST", "/api/jobs",
                                _multipart("clip.wav", b"abc"), _BOUNDARY_HDR)
        assert status == 202, body
    finally:
        srv.close()


# --- full queue is answered before the body is stored --------------------------

def test_a_full_queue_refuses_before_the_upload_is_stored(tmp_path, monkeypatch):
    def boom(self, boundary):
        raise AssertionError("the upload body must not be written to disk")

    monkeypatch.setattr(JobRequestHandler, "_receive_upload", boom)
    srv = _Server(tmp_path, max_queued=0)
    try:
        status, body = _request(srv, "POST", "/api/jobs",
                                _multipart("clip.wav", b"abc" * 100),
                                _BOUNDARY_HDR)
        assert status == 503, body
        status, body = _request(
            srv, "POST", "/v1/audio/transcriptions",
            _multipart("clip.wav", b"abc" * 100), _BOUNDARY_HDR)
        assert status == 503, body
        assert "error" in json.loads(body)
    finally:
        srv.close()


# --- English-only model with another language ----------------------------------

@pytest.fixture
def english_only_model(monkeypatch):
    from core import transcriber as t

    monkeypatch.setitem(t.config, "whisper_model", "tiny.en")
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")


def test_helper_flags_a_non_english_language(english_only_model):
    msg = english_only_problem("fr")
    assert msg and "tiny.en" in msg and "'tiny'" in msg
    assert english_only_problem("en") is None
    assert english_only_problem("") is None  # auto-detect is allowed


def test_helper_is_silent_for_a_multilingual_model(monkeypatch):
    from core import transcriber as t

    monkeypatch.setitem(t.config, "whisper_model", "small")
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")
    assert english_only_problem("fr") is None


def test_helper_is_silent_for_another_engine(monkeypatch):
    from core import transcriber as t

    monkeypatch.setitem(t.config, "whisper_model", "tiny.en")
    monkeypatch.setitem(t.config, "transcribe_backend", "whisper_cpp")
    assert english_only_problem("fr") is None


def test_helper_is_silent_for_a_custom_model(monkeypatch):
    from core import transcriber as t

    monkeypatch.setitem(t.config, "whisper_model", "my-own-model")
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")
    assert english_only_problem("fr") is None


def _fields(**kv):
    out = b""
    for k, v in kv.items():
        out += (f'--BOUND\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n").encode()
    return out


def _upload_body(**fields):
    return (
        b'--BOUND\r\nContent-Disposition: form-data; name="file"; '
        b'filename="clip.wav"\r\nContent-Type: audio/wav\r\n\r\nabc\r\n'
        + _fields(**fields) + b"--BOUND--\r\n")


def test_web_upload_in_another_language_is_refused(tmp_path, english_only_model):
    with _RunningServer(tmp_path) as srv:
        status, body = _request(
            srv, "POST", "/api/jobs", _upload_body(language="fr"),
            _BOUNDARY_HDR)
        assert status == 400, body
        assert "tiny" in json.loads(body)["error"]
        assert srv.manager.list() == []
        status, body = _request(
            srv, "POST", "/api/jobs", _upload_body(language="en"),
            _BOUNDARY_HDR)
        assert status == 202, body
        status, body = _request(srv, "POST", "/api/jobs",
                                _upload_body(), _BOUNDARY_HDR)
        assert status == 202, body  # auto-detect still runs


def test_web_url_job_in_another_language_is_refused(tmp_path, english_only_model):
    with _RunningServer(tmp_path) as srv:
        status, body = _request(
            srv, "POST", "/api/jobs",
            json.dumps({"url": "http://192.0.2.10/a.mp4",
                        "language": "de"}).encode(),
            {"Content-Type": "application/json"})
        assert status == 400, body
        assert "tiny" in json.loads(body)["error"]


def test_openai_request_in_another_language_is_refused(tmp_path,
                                                       english_only_model):
    with _RunningServer(tmp_path) as srv:
        status, body = _request(
            srv, "POST", "/v1/audio/transcriptions",
            _upload_body(model="whisper-1", language="fr"), _BOUNDARY_HDR)
        assert status == 400, body
        err = json.loads(body)["error"]
        assert err["param"] == "language" and "tiny" in err["message"]


# --- web option ranges ------------------------------------------------------------

def test_oversized_options_are_clamped_not_dropped():
    out = normalize_options({
        "vad_min_silence_ms": 10_000_000,
        "diarization_num_speakers": 5000,
    })
    assert out["vad_min_silence_ms"] == 60_000
    assert out["diarization_num_speakers"] == 100


def test_in_range_options_are_unchanged():
    out = normalize_options({
        "vad_min_silence_ms": 300, "diarization_num_speakers": 3})
    assert out == {"vad_min_silence_ms": 300, "diarization_num_speakers": 3}


# --- the page keeps the password out of download addresses ------------------------

def _page() -> str:
    import os
    with open(os.path.join(httpd._STATIC_DIR, "index.html"),
              encoding="utf-8") as f:
        return f.read()


def test_download_links_do_not_carry_the_token_in_the_address():
    text = _page()
    start = text.index("function downloadLink(")
    body = text[start:text.index("return '<a class=", start)]
    href_line = body[body.index("var href"):]
    assert "tokenQuery" not in href_line and "token" not in href_line
    # With a password set the click handler sends it as a header, saves a Blob.
    assert "X-Auth-Token" in text and "authHeaders()" in text
    assert "URL.createObjectURL" in text
    # Without a password the plain link still works (no preventDefault then).
    assert "!tokenVal()" in text


# --- TLS: the cap and the time budget hold there too ---------------------------

def _tls_server(tmp_path, monkeypatch, **kw):
    from core.server import tls

    monkeypatch.setattr(tls, "cert_dir", lambda: tmp_path)
    return _Server(tmp_path, ssl_context=tls.build_server_ssl_context(), **kw)


def test_tls_surplus_connection_is_closed_and_slots_are_released(
        tmp_path, monkeypatch):
    srv = _tls_server(tmp_path, monkeypatch, max_connections=2)
    held = []
    try:
        for _ in range(2):
            held.append(socket.create_connection(("127.0.0.1", srv.port)))
        assert _wait_until(lambda: srv.server.active_connections() == 2)
        extra = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        assert _read_status(extra) == b""  # closed, no plain-text reply
        extra.close()
        for s in held:
            s.close()
        assert _wait_until(lambda: srv.server.active_connections() == 0)
    finally:
        for s in held:
            s.close()
        srv.close()


def test_tls_header_trickle_is_cut_off(tmp_path, monkeypatch):
    import ssl

    monkeypatch.setattr(httpd, "_HEADER_TOTAL_S", 0.6)
    monkeypatch.setattr(httpd, "_WATCH_TICK_S", 0.05)
    srv = _tls_server(tmp_path, monkeypatch, max_connections=4)
    try:
        ctx = ssl._create_unverified_context()
        raw = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s = ctx.wrap_socket(raw)
        s.sendall(b"GET /api/health HTTP/1.1\r\nX-Slow: aaaa")
        assert _closed_by_server(s, 4.0)
        s.close()
        assert _wait_until(lambda: srv.server.active_connections() == 0)
    finally:
        srv.close()


# --- positive control for the queue pre-check -----------------------------------

def test_queue_precheck_counts_queued_jobs_only(tmp_path, monkeypatch):
    gate = threading.Event()

    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        gate.wait(10)
        return _writing_transcribe(task, progress_cb, log_cb, language_cb)

    manager = JobManager(slow, jobs_root=str(tmp_path / "jobs"),
                         record_history=False, max_queued=1)
    manager.start()
    server = JobHTTPServer(("127.0.0.1", 0), manager)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class _Ref:
        port = server.server_address[1]

    try:
        body = _multipart("clip.wav", b"abc")
        status, raw = _request(_Ref, "POST", "/api/jobs", body, _BOUNDARY_HDR)
        assert status == 202, raw  # runs (taken by the worker)
        assert _wait_until(lambda: any(
            r["status"] == "running" for r in manager.list()))
        status, raw = _request(_Ref, "POST", "/api/jobs", body, _BOUNDARY_HDR)
        assert status == 202, raw  # waits in the queue: the queue is now full

        def boom(self, boundary):
            raise AssertionError("must be refused before the body is stored")

        monkeypatch.setattr(JobRequestHandler, "_receive_upload", boom)
        status, raw = _request(_Ref, "POST", "/api/jobs", body, _BOUNDARY_HDR)
        assert status == 503, raw
    finally:
        gate.set()
        server.shutdown()
        server.server_close()
        manager.stop()
