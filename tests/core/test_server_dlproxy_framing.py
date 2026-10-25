"""Request framing in the download proxy: Content-Length and chunked bodies are
forwarded intact, conflicting framing is refused, nothing after the declared
body is forwarded (no request smuggling).

Loopback sockets with ephemeral ports only; the address check is lifted for
the positive cases so the plain-HTTP path can reach a local listener.
"""
from __future__ import annotations

import socket

import pytest

from core.server import dlproxy
from tests.core.test_server_dlproxy import (  # noqa: F401  (fixtures)
    _auth,
    _Listener,
    _lift_guard,
    _status,
    private,
    proxy,
)

CRLF = b"\r\n"


def _send(proxy_: dlproxy.DownloadProxy, raw: bytes) -> bytes:
    sock = socket.create_connection(("127.0.0.1", proxy_.port), timeout=5)
    try:
        sock.sendall(raw)
        out = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        sock.close()


def _head(proxy_, port: int, extra: list[bytes]) -> bytes:
    lines = [f"POST http://127.0.0.1:{port}/up HTTP/1.1".encode(),
             b"Host: x",
             f"Proxy-Authorization: {_auth(proxy_)}".encode()] + extra
    return CRLF.join(lines) + CRLF + CRLF


@pytest.fixture(autouse=True)
def _no_environment_proxy(monkeypatch):
    """A proxy set on the developer's machine must not change these tests."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


class _BodyListener(_Listener):
    """Records the whole request (head and body) the upstream receives."""

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            try:
                conn.settimeout(1.0)
                data = b""
                while True:
                    try:
                        chunk = conn.recv(65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    data += chunk
                    if b"0" + CRLF + CRLF in data or data.endswith(b"abc"):
                        break
                self.received.append(data)
                conn.sendall(self.reply)
            except OSError:
                pass
            finally:
                conn.close()


@pytest.fixture
def body_listener(monkeypatch):
    srv = _BodyListener()
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {srv.port})
    yield srv
    srv.close()


def test_a_chunked_post_arrives_intact(proxy, body_listener, monkeypatch):
    _lift_guard(monkeypatch)
    body = b"5" + CRLF + b"hello" + CRLF + b"6" + CRLF + b" world" + CRLF \
        + b"0" + CRLF + CRLF
    reply = _send(proxy, _head(proxy, body_listener.port,
                               [b"Transfer-Encoding: chunked"]) + body)
    assert _status(reply) == 200
    got = body_listener.received[0]
    assert got.endswith(body), got
    assert b"Transfer-Encoding: chunked" in got
    assert b"Proxy-Authorization" not in got


def test_a_content_length_post_arrives_intact(proxy, body_listener, monkeypatch):
    _lift_guard(monkeypatch)
    reply = _send(proxy, _head(proxy, body_listener.port,
                               [b"Content-Length: 3"]) + b"abc")
    assert _status(reply) == 200
    assert body_listener.received[0].endswith(CRLF + CRLF + b"abc")


def test_bytes_after_the_declared_body_are_not_forwarded(
        proxy, body_listener, monkeypatch):
    """Smuggling: a second request hidden behind the body must not reach the
    upstream."""
    _lift_guard(monkeypatch)
    smuggled = b"GET /evil HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF
    _send(proxy, _head(proxy, body_listener.port,
                       [b"Content-Length: 3"]) + b"abc" + smuggled)
    assert b"/evil" not in b"".join(body_listener.received)


@pytest.mark.parametrize("extra", [
    [b"Content-Length: 3", b"Transfer-Encoding: chunked"],
    [b"Content-Length: 3", b"Content-Length: 4"],
    [b"Transfer-Encoding: gzip, chunked"],
    [b"Transfer-Encoding: chunked", b"Transfer-Encoding: chunked"],
    [b"Content-Length: -1"],
    [b"Content-Length: 3x"],
])
def test_conflicting_or_unsupported_framing_is_refused(
        proxy, body_listener, monkeypatch, extra):
    _lift_guard(monkeypatch)
    reply = _send(proxy, _head(proxy, body_listener.port, extra) + b"abc")
    assert _status(reply) == 400
    assert body_listener.connections == 0


def test_a_malformed_chunk_is_refused(proxy, body_listener, monkeypatch):
    _lift_guard(monkeypatch)
    reply = _send(proxy, _head(proxy, body_listener.port,
                               [b"Transfer-Encoding: chunked"])
                  + b"zz" + CRLF + b"oops" + CRLF)
    assert _status(reply) == 400


def _header_names(received: bytes) -> list[str]:
    head = received.split(CRLF + CRLF, 1)[0].split(CRLF)[1:]
    return [line.split(b":", 1)[0].strip().lower().decode() for line in head]


def test_a_strict_receiver_sees_exactly_one_transfer_encoding(
        proxy, body_listener, monkeypatch):
    _lift_guard(monkeypatch)
    body = b"3" + CRLF + b"abc" + CRLF + b"0" + CRLF + CRLF
    # Mixed case and odd spacing in the client's own header.
    _send(proxy, _head(proxy, body_listener.port,
                       [b"transfer-ENCODING:   chunked"]) + body)
    names = _header_names(body_listener.received[0])
    assert names.count("transfer-encoding") == 1
    assert names.count("content-length") == 0
    assert names.count("connection") == 1
    assert names.count("host") == 1


def test_a_strict_receiver_sees_exactly_one_content_length(
        proxy, body_listener, monkeypatch):
    _lift_guard(monkeypatch)
    _send(proxy, _head(proxy, body_listener.port,
                       [b"content-length:  3"]) + b"abc")
    names = _header_names(body_listener.received[0])
    assert names.count("content-length") == 1
    assert names.count("transfer-encoding") == 0
    assert b"Content-Length: 3" in body_listener.received[0]
