"""Upload robustness of the job server (card C2.63, findings S11-3, S11-4, V1).

* a browser sends a non-English file name as raw UTF-8 bytes in the multipart
  header; it used to be read as latin-1 and saved as mojibake;
* a client that disconnects mid-upload must not create a job from the partial
  file; a chunked upload (no Content-Length) gets a clear 411;
* discarding a refused body has a total deadline: a client that declares a big
  length and trickles bytes cannot pin a handler thread.

Loopback sockets with ephemeral ports only; the transcriber is a fake.
"""
from __future__ import annotations

import os
import socket
import threading
import time

from core.server import httpd
from core.server.httpd import extract_upload, scan_multipart_file
from tests.core.test_server_security import (
    _RunningServer,
    _multipart,
    _request,
    _wait_terminal,
)

# Persian "audio file" (escaped: tracked files stay ASCII)
_PERSIAN_NAME = "\u0641\u0627\u06cc\u0644 \u0635\u0648\u062a\u06cc.wav"


def test_extract_upload_decodes_a_utf8_file_name():
    body = _multipart(_PERSIAN_NAME, b"DATA")
    name, data, _ = extract_upload(body, "BOUND")
    assert name == _PERSIAN_NAME
    assert data == b"DATA"


def test_scan_multipart_file_decodes_a_utf8_file_name():
    body = _multipart(_PERSIAN_NAME, b"DATA")
    assert scan_multipart_file(body, "BOUND").filename == _PERSIAN_NAME


def test_a_latin1_file_name_still_decodes():
    # An old client that sends latin-1 bytes (not valid UTF-8) must not fail.
    body = (b'--BOUND\r\nContent-Disposition: form-data; name="file"; '
            b'filename="caf\xe9.wav"\r\n\r\nDATA\r\n--BOUND--\r\n')
    assert extract_upload(body, "BOUND")[0] == "café.wav"
    assert scan_multipart_file(body, "BOUND").filename == "café.wav"


def test_uploaded_persian_name_is_kept_on_disk(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs", _multipart(_PERSIAN_NAME, b"abc"),
            {"Content-Type": "multipart/form-data; boundary=BOUND"})
        assert status == 202, raw
        job_id = __import__("json").loads(raw)["job_id"]
        job = _wait_terminal(srv.manager, job_id)
        assert os.path.basename(job.media_path) == _PERSIAN_NAME


def _raw_post(port, headers: bytes, body: bytes = b"") -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\n" + headers
              + b"\r\n" + body)
    return s


def test_disconnect_mid_upload_creates_no_job(tmp_path):
    full = _multipart("clip.wav", b"x" * 5000)
    with _RunningServer(tmp_path) as srv:
        s = _raw_post(
            srv.port,
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            + f"Content-Length: {len(full)}\r\n".encode(),
            full[:2000])
        try:
            # Half-close: the server sees the end of the stream early.
            s.shutdown(socket.SHUT_WR)
            head = s.recv(200)
        finally:
            s.close()
        assert head.startswith(b"HTTP/1.1 400"), head
        assert srv.manager.list() == []
        assert not [n for n in os.listdir(tmp_path / "server_jobs")]


def test_complete_upload_still_creates_a_job(tmp_path):
    with _RunningServer(tmp_path) as srv:
        status, raw = _request(
            srv, "POST", "/api/jobs", _multipart("clip.wav", b"x" * 5000),
            {"Content-Type": "multipart/form-data; boundary=BOUND"})
        assert status == 202, raw
        assert len(srv.manager.list()) == 1


def test_chunked_upload_gets_411(tmp_path):
    with _RunningServer(tmp_path) as srv:
        s = _raw_post(
            srv.port,
            b"Content-Type: multipart/form-data; boundary=BOUND\r\n"
            b"Transfer-Encoding: chunked\r\n",
            b"0\r\n\r\n")
        try:
            head = s.recv(200)
        finally:
            s.close()
        assert head.startswith(b"HTTP/1.1 411"), head
        assert srv.manager.list() == []


def test_oversized_body_discard_has_a_total_deadline(tmp_path, monkeypatch):
    """A client that declares an over-cap length and trickles bytes gets its
    413 within the deadline, not after the whole declared body."""
    monkeypatch.setattr(httpd, "_DISCARD_TOTAL_S", 0.6)
    monkeypatch.setattr(httpd, "_DISCARD_IDLE_S", 0.4)
    declared = httpd._MAX_JSON_BODY_BYTES + 1000
    with _RunningServer(tmp_path) as srv:
        s = _raw_post(
            srv.port,
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {declared}\r\n".encode())
        stop = threading.Event()

        def _trickle():
            try:
                while not stop.is_set():
                    s.sendall(b"x")
                    time.sleep(0.05)
            except OSError:
                pass

        threading.Thread(target=_trickle, daemon=True).start()
        try:
            t0 = time.monotonic()
            head = s.recv(200)
            assert head.startswith(b"HTTP/1.1 413"), head
            assert time.monotonic() - t0 < 4
        finally:
            stop.set()
            s.close()


def test_unread_control_body_closes_the_connection(tmp_path, monkeypatch):
    """A cancel POST whose declared body never arrives must not leave the
    connection open for a desynchronised keep-alive."""
    monkeypatch.setattr(httpd, "_DISCARD_TOTAL_S", 0.5)
    monkeypatch.setattr(httpd, "_DISCARD_IDLE_S", 0.3)
    with _RunningServer(tmp_path) as srv:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        try:
            s.sendall(
                b"POST /api/jobs/" + b"0" * 32 + b"/cancel HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nContent-Length: 1000\r\n\r\nabc")
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            assert data.startswith(b"HTTP/1.1 404") or data.startswith(b"HTTP/1.1 200")
        finally:
            s.close()
