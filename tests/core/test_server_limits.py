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
import os
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

    def __init__(self, tmp_path, transcribe_fn=_writing_transcribe, **kw):
        self.manager = JobManager(
            transcribe_fn, jobs_root=str(tmp_path / "jobs"),
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
    monkeypatch.setattr(httpd, "_UPLOAD_STALL_S", 0.6)
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


# --- round 2: synchronous /v1 waits, refusal reply, keep-alive, deadlines ---------

def _blocking_server(tmp_path, **kw):
    """A server whose transcriber blocks until ``gate`` is set."""
    gate = threading.Event()

    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        gate.wait(20)
        return _writing_transcribe(task, progress_cb, log_cb, language_cb)

    srv = _Server(tmp_path, transcribe_fn=slow, **kw)
    return srv, gate


def _v1_request(port: int, name: str = "clip.wav") -> socket.socket:
    body = _upload_body(model="whisper-1")
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(
        b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    return s


def _reset_close(sock: socket.socket) -> None:
    """Close with an RST (what a crashed or killed client leaves behind)."""
    import struct

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                    struct.pack("ii", 1, 0))
    sock.close()


def test_v1_wait_cancels_the_job_when_the_client_resets(tmp_path):
    srv, gate = _blocking_server(tmp_path)
    try:
        s = _v1_request(srv.port)
        assert _wait_until(lambda: len(srv.manager.list()) == 1)
        assert _wait_until(lambda: srv.server.active_connections() == 1)
        job_id = srv.manager.list()[0]["job_id"]
        _reset_close(s)
        job = srv.manager.get(job_id)
        assert job is not None
        assert _wait_until(lambda: job.cancelled, 5.0)
        assert _wait_until(lambda: srv.server.active_connections() == 0, 5.0)
    finally:
        gate.set()
        srv.close()


def _json_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    path = f"{base}.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write('[{"start": 0.0, "end": 1.0, "text": "hello"}]')
    task.output_paths = [path]
    if progress_cb:
        progress_cb(100)


def _read_all(sock: socket.socket, limit: float = 10.0) -> bytes:
    sock.settimeout(limit)
    out = b""
    while True:
        try:
            part = sock.recv(65536)
        except OSError:
            break
        if not part:
            break
        out += part
    return out


def test_v1_half_closed_client_keeps_its_job_and_gets_the_reply(tmp_path):
    """HTTP/1.0 style: send everything, shut down the write side, read."""
    gate = threading.Event()

    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        gate.wait(20)
        return _json_transcribe(task, progress_cb, log_cb, language_cb)

    srv = _Server(tmp_path, transcribe_fn=slow)
    try:
        body = _upload_body(model="whisper-1")
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
        s.sendall(
            b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: close\r\n"
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        s.shutdown(socket.SHUT_WR)  # a FIN, not a reset
        assert _wait_until(lambda: len(srv.manager.list()) == 1)
        time.sleep(0.6)  # several polls with the FIN pending
        job_id = srv.manager.list()[0]["job_id"]
        job = srv.manager.get(job_id)
        assert job is not None and not job.cancelled
        gate.set()
        reply = _read_all(s)
        s.close()
        assert reply.startswith(b"HTTP/1.1 200"), reply[:80]
        assert b"hello" in reply
    finally:
        gate.set()
        srv.close()


def test_client_gone_helper_treats_only_a_reset_as_gone():
    import struct
    from types import SimpleNamespace

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        def pair():
            c = socket.create_connection(listener.getsockname())
            srv_side, _ = listener.accept()
            return c, srv_side

        gone = lambda sock: JobRequestHandler._client_gone(  # noqa: E731
            SimpleNamespace(connection=sock))  # type: ignore[arg-type]
        # quiet connection
        c, sv = pair()
        assert gone(sv) is False
        # pipelined bytes are seen but never consumed
        c.sendall(b"GET /next")
        time.sleep(0.2)
        assert gone(sv) is False
        sv.settimeout(2)
        assert sv.recv(100) == b"GET /next"
        # FIN: a half-close or a finished client, not "gone"
        c.shutdown(socket.SHUT_WR)
        time.sleep(0.2)
        assert gone(sv) is False
        c.close()
        sv.close()
        # RST: gone
        c, sv = pair()
        c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                     struct.pack("ii", 1, 0))
        c.close()
        time.sleep(0.3)
        assert gone(sv) is True
        sv.close()
    finally:
        listener.close()


def test_tls_v1_wait_cancels_on_a_reset_and_keeps_the_job_on_close(
        tmp_path, monkeypatch):
    import ssl

    gate = threading.Event()

    def slow(task, progress_cb=None, log_cb=None, language_cb=None):
        gate.wait(20)
        return _json_transcribe(task, progress_cb, log_cb, language_cb)

    from core.server import tls

    monkeypatch.setattr(tls, "cert_dir", lambda: tmp_path)
    srv = _Server(tmp_path, transcribe_fn=slow,
                  ssl_context=tls.build_server_ssl_context())
    try:
        ctx = ssl._create_unverified_context()
        body = _upload_body(model="whisper-1")

        def send(raw):
            tl = ctx.wrap_socket(raw)
            tl.sendall(
                b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            return tl

        # 1. a clean close (close_notify + FIN) leaves the job alone
        raw = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        tl = send(raw)
        assert _wait_until(lambda: len(srv.manager.list()) == 1)
        # (A real close() with unread TLS session tickets would send an RST.)
        socket.socket.shutdown(tl, socket.SHUT_WR)  # FIN, as after close_notify
        time.sleep(0.8)
        first = srv.manager.get(srv.manager.list()[0]["job_id"])
        assert first is not None and not first.cancelled
        # 2. a reset cancels it
        raw2 = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        tl2 = send(raw2)
        assert _wait_until(lambda: len(srv.manager.list()) == 2)
        second = [srv.manager.get(r["job_id"]) for r in srv.manager.list()
                  if r["job_id"] != first.job_id][0]
        assert second is not None
        _reset_close(tl2)
        assert _wait_until(lambda: second.cancelled, 5.0)
    finally:
        gate.set()
        srv.close()


def test_sync_v1_waits_are_capped_and_leave_slots_for_the_web_page(tmp_path):
    srv, gate = _blocking_server(tmp_path, max_connections=6)
    waiting = []
    try:
        # 6 slots -> at most 4 synchronous waiters.
        for _ in range(4):
            waiting.append(_v1_request(srv.port))
        assert _wait_until(lambda: len(srv.manager.list()) == 4)
        fifth = _v1_request(srv.port)
        fifth.settimeout(5)
        reply = b""
        while True:  # read to the end of the reply (head and body)
            part = fifth.recv(4096)
            if not part:
                break
            reply += part
        fifth.close()
        assert reply.startswith(b"HTTP/1.1 503"), reply[:40]
        assert b"waiting" in reply
        # The page and the status route still work.
        status, body = _request(srv, "GET", "/api/health")
        assert status == 200, body
        status, body = _request(srv, "GET", "/api/jobs")
        assert status == 200, body
    finally:
        for s in waiting:
            s.close()
        gate.set()
        srv.close()


def test_a_surplus_client_in_the_middle_of_an_upload_still_sees_the_503(tmp_path):
    srv = _Server(tmp_path, max_connections=1)
    holder = socket.create_connection(("127.0.0.1", srv.port))
    try:
        assert _wait_until(lambda: srv.server.active_connections() == 1)
        got = 0
        for _ in range(5):
            size = 3 * 1024 * 1024
            c = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
            c.sendall(
                b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Content-Type: multipart/form-data; boundary=B\r\n"
                + f"Content-Length: {size}\r\n\r\n".encode())
            try:
                c.sendall(b"x" * size)
            except OSError:
                pass
            try:
                if c.recv(4096).startswith(b"HTTP/1.1 503"):
                    got += 1
            except OSError:
                pass
            c.close()
        assert got == 5
    finally:
        holder.close()
        srv.close()


def test_the_refusal_drain_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_REFUSE_DRAIN_BYTES", 64 * 1024)
    srv = _Server(tmp_path, max_connections=1)
    holder = socket.create_connection(("127.0.0.1", srv.port))
    try:
        assert _wait_until(lambda: srv.server.active_connections() == 1)
        c = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        c.sendall(b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 99999999\r\n\r\n")
        assert c.recv(4096).startswith(b"HTTP/1.1 503")
        try:
            c.sendall(b"x" * (1024 * 1024))  # more than the drain takes
        except OSError:
            pass
        assert _closed_by_server(c, 4.0)  # the refuser gave up and closed
        c.close()
    finally:
        holder.close()
        srv.close()


def test_idle_keep_alive_clients_do_not_hold_slots(tmp_path, monkeypatch):
    import http.client

    monkeypatch.setattr(httpd, "_HEADER_TOTAL_S", 0.6)
    srv = _Server(tmp_path, max_connections=4)
    clients = []
    try:
        for _ in range(3):
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request("GET", "/api/health")
            c.getresponse().read()
            clients.append(c)  # kept open and idle, like a browser's
        assert _wait_until(lambda: srv.server.active_connections() == 0, 3.0)
        c5 = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c5.request("GET", "/api/health")
        assert c5.getresponse().status == 200
        c5.close()
    finally:
        for c in clients:
            c.close()
        srv.close()


def test_a_crowded_server_ends_keep_alive_connections(tmp_path):
    import http.client

    srv = _Server(tmp_path, max_connections=4)
    holders = []
    try:
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", srv.port))
            s.sendall(b"GET /api/he")
            holders.append(s)
        assert _wait_until(lambda: srv.server.active_connections() == 2)
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c.request("GET", "/api/health")  # the third connection: 3 of 4
        r = c.getresponse()
        r.read()
        assert r.status == 200
        assert (r.getheader("Connection") or "").lower() == "close"
        c.close()
    finally:
        for s in holders:
            s.close()
        srv.close()


def test_an_uncrowded_server_keeps_connections_alive(tmp_path):
    import http.client

    srv = _Server(tmp_path, max_connections=64)
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c.request("GET", "/api/health")
        r = c.getresponse()
        r.read()
        assert (r.getheader("Connection") or "").lower() != "close"
        c.close()
    finally:
        srv.close()


def test_the_reader_stops_a_silent_peer_at_its_deadline():
    a, b = socket.socketpair()
    try:
        reader = httpd._DeadlineReader(a)
        a.settimeout(30)  # the per-read timeout alone would wait 30 s
        reader.deadline = time.monotonic() + 0.3
        started = time.monotonic()
        with pytest.raises(httpd._BudgetExceeded):
            reader.readinto(bytearray(10))
        assert time.monotonic() - started < 2.0
        assert a.gettimeout() == 30  # the socket's own timeout is restored
    finally:
        a.close()
        b.close()


def test_the_reader_stops_a_trickle_at_its_deadline():
    a, b = socket.socketpair()
    stop = threading.Event()

    def trickle():
        while not stop.is_set():
            try:
                b.sendall(b"x")
            except OSError:
                return
            time.sleep(0.05)

    t = threading.Thread(target=trickle, daemon=True)
    t.start()
    try:
        reader = httpd._DeadlineReader(a)
        a.settimeout(30)
        reader.deadline = time.monotonic() + 0.4
        started = time.monotonic()
        with pytest.raises(httpd._BudgetExceeded):
            while True:  # bytes keep arriving, yet the budget still ends it
                reader.readinto(bytearray(1))
        assert time.monotonic() - started < 2.0
    finally:
        stop.set()
        t.join(2)
        a.close()
        b.close()


def test_the_reader_without_a_deadline_reads_normally():
    a, b = socket.socketpair()
    try:
        reader = httpd._DeadlineReader(a)
        b.sendall(b"hello")
        buf = bytearray(10)
        assert reader.readinto(buf) == 5 and bytes(buf[:5]) == b"hello"
    finally:
        a.close()
        b.close()


def test_a_slow_but_steady_upload_is_not_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_UPLOAD_STALL_S", 0.8)
    srv = _Server(tmp_path)
    try:
        payload = b"x" * (3 * 64 * 1024)
        full = _multipart("clip.wav", payload)
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
        s.sendall(
            b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(full)}\r\n\r\n".encode())
        started = time.monotonic()
        step = 64 * 1024
        for i in range(0, len(full), step):
            s.sendall(full[i:i + step])
            time.sleep(0.5)  # each chunk arrives inside the window...
        assert time.monotonic() - started > 1.2  # ...the whole takes longer
        reply = s.recv(4096)
        s.close()
        assert reply.startswith(b"HTTP/1.1 202"), reply[:60]
    finally:
        srv.close()


def test_a_clamped_option_is_logged(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger=httpd.logger.name):
        normalize_options({"vad_min_silence_ms": 10_000_000})
    assert any("vad_min_silence_ms" in r.getMessage() for r in caplog.records)


def test_the_page_explains_download_failures_and_the_header_download():
    text = _page()
    assert "wrong or missing password" in text
    assert "no longer available" in text
    assert "Save link as" in text  # the hint shown while a password is set


# --- round 3: Expect: 100-continue, slot after upload, 408 -------------------------

def test_expect_continue_when_crowded_gets_connection_close_on_the_final_reply_only(
        tmp_path):
    srv = _Server(tmp_path, max_connections=4)
    holders = []
    try:
        for _ in range(2):
            h = socket.create_connection(("127.0.0.1", srv.port))
            h.sendall(b"GET /api/he")
            holders.append(h)
        assert _wait_until(lambda: srv.server.active_connections() == 2)
        body = _multipart("clip.wav", b"abc")
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall(
            b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\nExpect: 100-continue\r\n"
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode())
        interim = s.recv(4096)
        assert interim.startswith(b"HTTP/1.1 100"), interim
        assert b"onnection" not in interim  # not on the interim reply
        s.sendall(body)
        final = _read_all(s, 5.0)
        s.close()
        head, _sep, payload = final.partition(b"\r\n\r\n")
        assert head.startswith(b"HTTP/1.1 202"), head[:60]
        assert b"connection: close" in head.lower()
        assert b"job_id" in payload  # the reply arrived whole
    finally:
        for h in holders:
            h.close()
        srv.close()


def test_slow_uploads_do_not_hold_sync_waiter_slots(tmp_path):
    srv, gate = _blocking_server(tmp_path, max_connections=6)
    partial = []
    try:
        body = _upload_body(model="whisper-1")
        for _ in range(4):  # headers and half of the body, then silence
            s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
            s.sendall(
                b"POST /v1/audio/transcriptions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body[:len(body) // 2])
            partial.append(s)
        assert _wait_until(lambda: srv.server.active_connections() == 4)
        full = _v1_request(srv.port)  # a complete request still gets in
        assert _wait_until(lambda: len(srv.manager.list()) == 1)
        full.close()
    finally:
        for s in partial:
            s.close()
        gate.set()
        srv.close()


def test_a_stalled_upload_gets_a_408_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_UPLOAD_STALL_S", 0.5)
    srv = _Server(tmp_path)
    try:
        full = _multipart("clip.wav", b"x" * 5000)
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall(
            b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(full)}\r\n\r\n".encode() + full[:10])
        reply = _read_all(s, 5.0)
        s.close()
        assert reply.startswith(b"HTTP/1.1 408"), reply[:60]
        assert b"too slow" in reply
    finally:
        srv.close()


def test_a_stalled_json_body_gets_a_408(tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_JSON_BODY_TOTAL_S", 1.0)
    srv = _Server(tmp_path)
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        s.sendall(
            b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
            b'{"url"')
        reply = _read_all(s, 5.0)
        s.close()
        assert reply.startswith(b"HTTP/1.1 408"), reply[:60]
    finally:
        srv.close()
