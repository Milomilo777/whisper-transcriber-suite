"""Cancellation while real HTTP parsing or a body read waits for more bytes."""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import socket
import socketserver
import ssl
import threading
import time
import urllib.request

import pytest

from core import verified_download as vd


class _Server:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.sent = threading.Event()
        self.release = threading.Event()
        self.peer_closed = threading.Event()
        self.connections = []
        self.handlers = []
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                owner.handlers.append(threading.current_thread())
                owner.connections.append(self.request)
                self.request.settimeout(3)
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    block = self.request.recv(1)
                    if not block:
                        return
                    request += block
                owner.requests.append(request)
                reply = owner.replies.pop(0)
                with contextlib.suppress(OSError):
                    reply(owner, self.request)

        class TCP(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = TCP(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/file"

    def close(self):
        self.release.set()
        for conn in self.connections:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        for handler in self.handlers:
            handler.join(2)
            assert not handler.is_alive()
        assert not self.thread.is_alive()


def _stall(initial):
    def reply(server, conn):
        conn.sendall(initial)
        server.sent.set()
        conn.settimeout(0.05)
        deadline = time.monotonic() + 4
        while not server.release.is_set() and time.monotonic() < deadline:
            try:
                if not conn.recv(1):
                    server.peer_closed.set()
                    return
            except socket.timeout:
                continue
    return reply


def _get(url, dest, **kwargs):
    return vd.download_verified(url, dest, size=4,
                                sha256=hashlib.sha256(b"data").hexdigest(),
                                what="test file", chunk_size=1024, **kwargs)


@pytest.mark.parametrize("phase,initial", [
    ("status", b"HTTP/1.1 20"),
    ("header", b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nX-Test: par"),
    ("body", b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n"),
    ("prefix", b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nd"),
    ("chunk-size", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"),
    ("chunk-body", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nd"),
    ("trailer", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\ndata\r\n0\r\nX-Test: par"),
    ("redirect-body", b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 4\r\n\r\nd"),
])
def test_cancel_finishes_before_server_release(tmp_path, monkeypatch, phase, initial):
    entered = threading.Event()
    for name in ("begin",) if phase in {"status", "header"} else ("read", "read1"):
        original = getattr(http.client.HTTPResponse, name)

        def observed(self, *args, _original=original, **kwargs):
            entered.set()
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(http.client.HTTPResponse, name, observed)
    server = _Server([_stall(initial)])
    cancel = threading.Event()
    finished = threading.Event()
    errors = []  # Retain tracebacks to prove cleanup does not depend on GC.
    dest = tmp_path / "file.bin"
    progress = threading.Event()

    def download():
        try:
            _get(server.url, dest, cancel_event=cancel, timeout=3,
                 progress_cb=lambda *_: progress.set())
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    try:
        assert server.sent.wait(2) and entered.wait(2)
        if phase == "prefix":
            progress.wait(0.5)
        cancel.set()
        assert finished.wait(1), "cancel stayed inside a blocking HTTP read"
        assert not server.release.is_set()
        assert len(errors) == 1 and isinstance(errors[0], vd.DownloadCancelled)
        assert server.peer_closed.wait(1), "retained traceback kept the transport open"
        assert not dest.exists()
        if phase == "prefix":
            assert vd.part_path(dest).read_bytes() == b"d"
        assert all(b"verified_download_context" not in req.lower() for req in server.requests)
    finally:
        server.close()
        thread.join(2)
        assert not thread.is_alive()


def test_redirect_preserves_cancellation_on_the_next_request(tmp_path):
    def redirect(server, conn):
        conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 0\r\n\r\n")

    server = _Server([redirect, _stall(b"HTTP/1.1 20")])
    cancel = threading.Event()
    errors = []

    def download():
        try:
            _get(server.url, tmp_path / "file", cancel_event=cancel, timeout=3)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    try:
        assert server.sent.wait(2)
        cancel.set()
        thread.join(1)
        assert not thread.is_alive(), "redirect lost its cancellation context"
        assert len(errors) == 1 and isinstance(errors[0], vd.DownloadCancelled)
        assert server.peer_closed.wait(1)
        assert len(server.requests) == 2
    finally:
        server.close()
        thread.join(2)
        assert not thread.is_alive()


def test_polling_does_not_turn_timeout_into_a_total_transfer_deadline(tmp_path):
    def paced(server, conn):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n")
        for byte in b"data":
            time.sleep(0.16)
            conn.sendall(bytes([byte]))

    server = _Server([paced])
    try:
        dest = tmp_path / "file"
        _get(server.url, dest, timeout=0.5)
        assert dest.read_bytes() == b"data"
    finally:
        server.close()


@pytest.mark.parametrize("initial", [
    b"HTTP/1.1 20",
    b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nX-Test: par",
    b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n",
    b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 4\r\n\r\nd",
])
def test_timeout_disposes_transport_even_with_retained_exception(tmp_path, monkeypatch, initial):
    responses = []
    begin = http.client.HTTPResponse.begin

    def track_response(response):
        responses.append(response)
        return begin(response)

    monkeypatch.setattr(http.client.HTTPResponse, "begin", track_response)
    server = _Server([_stall(initial)])
    try:
        with pytest.raises(vd.DownloadError) as error:
            _get(server.url, tmp_path / "file", timeout=0.25)
        assert error.value is not None  # Keep the entire exception chain alive.
        assert not server.release.is_set()
        assert server.peer_closed.wait(1)
        assert responses and all(response.closed for response in responses)
        assert not (tmp_path / "file").exists()
    finally:
        server.close()


def test_received_prefix_is_resumed_after_cancel(tmp_path):
    def remainder(server, conn):
        conn.sendall(b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\n"
                     b"Content-Range: bytes 1-3/4\r\n\r\nata")

    server = _Server([_stall(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nd"), remainder])
    cancel = threading.Event()
    progress = threading.Event()
    errors = []
    dest = tmp_path / "file"

    def download():
        try:
            _get(server.url, dest, cancel_event=cancel, timeout=3,
                 progress_cb=lambda *_: progress.set())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    try:
        assert progress.wait(2), "available prefix was held inside a full-chunk read"
        cancel.set()
        thread.join(1)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], vd.DownloadCancelled)
        assert vd.part_path(dest).read_bytes() == b"d" and not dest.exists()
        _get(server.url, dest, timeout=1)
        assert b"Range: bytes=1-\r\n" in server.requests[1]
        assert dest.read_bytes() == b"data"
        assert not vd.part_path(dest).exists()
    finally:
        cancel.set()
        server.close()
        thread.join(2)
        assert not thread.is_alive()


def test_concurrent_requests_do_not_share_cancellation(tmp_path):
    stalled = _Server([_stall(b"HTTP/1.1 20")])
    successful = _Server([lambda s, c: c.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata")])
    cancel = threading.Event()
    errors = []

    def download():
        try:
            _get(stalled.url, tmp_path / "cancelled", timeout=3, cancel_event=cancel)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=download, daemon=True)
    thread.start()
    try:
        assert stalled.sent.wait(2)
        _get(successful.url, tmp_path / "complete", timeout=1)
        assert (tmp_path / "complete").read_bytes() == b"data"
        assert thread.is_alive()
        cancel.set()
        thread.join(1)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], vd.DownloadCancelled)
        assert stalled.peer_closed.wait(1)
    finally:
        cancel.set()
        stalled.close()
        successful.close()
        thread.join(2)
        assert not thread.is_alive()


@pytest.mark.parametrize("hostname,cancel_body", [
    ("download.example", False), ("different.example", False), ("download.example", True),
])
def test_connect_retains_tls_timeout_auth_and_hostname_validation(
        tmp_path, monkeypatch, hostname, cancel_body):
    from core.server.tls import generate_self_signed_cert

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    generate_self_signed_cert(cert, key, hosts=["download.example"])
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(cert), str(key))
    client_context = ssl.create_default_context(cafile=str(cert))
    client_context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    timeouts = []
    tunneled = []
    original = client_context.wrap_socket

    def observed(sock, *args, **kwargs):
        timeouts.append(sock.gettimeout())
        return original(sock, *args, **kwargs)

    monkeypatch.setattr(client_context, "wrap_socket", observed)

    def proxy(server, conn):
        conn.sendall(b"HTTP/1.0 200 Connection established\r\n\r\n")
        time.sleep(0.2)  # TLS handshake needs longer than the polling interval.
        with server_context.wrap_socket(conn, server_side=True) as secure:
            request = b""
            while not request.endswith(b"\r\n\r\n"):
                block = secure.recv(1)
                if not block:
                    return
                request += block
            tunneled.append(request)
            if cancel_body:
                _stall(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nd")(server, secure)
            else:
                secure.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata")

    server = _Server([proxy])
    proxy_url = server.url.replace("http://", "http://fixture:fixture@")
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _: False)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy_url}),
        vd._DownloadHTTPHandler(), vd._DownloadHTTPSHandler(context=client_context),
        vd._HttpsOnlyRedirects())
    monkeypatch.setattr(vd, "_opener", opener)
    cancel = threading.Event()
    thread = None
    try:
        dest = tmp_path / "file"
        if cancel_body:
            errors = []

            def download():
                try:
                    _get(f"https://{hostname}/file", dest, timeout=1.5, cancel_event=cancel)
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=download, daemon=True)
            thread.start()
            assert server.sent.wait(2)
            cancel.set()
            thread.join(1)
            assert not thread.is_alive()
            assert len(errors) == 1 and isinstance(errors[0], vd.DownloadCancelled)
            assert server.peer_closed.wait(1)
            assert not dest.exists()
        elif hostname == "download.example":
            _get(f"https://{hostname}/file", dest, timeout=1.5)
            assert dest.read_bytes() == b"data"
            assert b"Proxy-Authorization:" not in tunneled[0]
        else:
            with pytest.raises(vd.DownloadError) as error:
                _get(f"https://{hostname}/file", dest, timeout=1.5)
            assert "CERTIFICATE_VERIFY_FAILED" in str(error.value)
            assert not dest.exists()
        assert timeouts == [1.5]
        assert server.requests[0].startswith(f"CONNECT {hostname}:443 HTTP/".encode())
        assert b"Proxy-Authorization: Basic " in server.requests[0]
        assert b"verified_download_context" not in server.requests[0].lower()
    finally:
        cancel.set()
        server.close()
        if thread is not None:
            thread.join(2)
            assert not thread.is_alive()


def test_failed_reader_installation_releases_both_makefile_references(monkeypatch):
    left, right = socket.socketpair()
    request = urllib.request.Request("http://download.example/file")
    context = vd._ReadContext(lambda: None, 1)
    setattr(request, "_verified_download_context", context)
    original = vd.io.BufferedReader

    def fail_new_reader(raw, *args, **kwargs):
        if isinstance(raw, vd._PollingReader):
            raise MemoryError("injected buffered-reader allocation failure")
        return original(raw, *args, **kwargs)

    monkeypatch.setattr(vd.io, "BufferedReader", fail_new_reader)
    try:
        connection = vd._download_connection(http.client.HTTPConnection, request)("download.example")
        with pytest.raises(MemoryError):
            connection.response_class(left)
        assert not context.readers
        assert left._io_refs == 0
        # Closing a response reader must not kill a still-owned CONNECT socket.
        left.sendall(b"x")
        assert right.recv(1) == b"x"
    finally:
        left.close()
        right.close()
