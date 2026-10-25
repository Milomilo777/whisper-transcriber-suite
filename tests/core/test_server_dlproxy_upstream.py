"""The download proxy behind an operator's own HTTP proxy (HTTP(S)_PROXY).

The guard resolves and checks the destination itself, then asks the upstream
proxy to CONNECT to the CHECKED numeric address (never the name). A stub
upstream proxy on loopback records what it is asked.

Hermetic: loopback sockets with ephemeral ports only.
"""
from __future__ import annotations

import base64
import socket
import threading

import pytest

from core.server import dlproxy
from tests.core.test_server_dlproxy import (  # noqa: F401  (fixtures)
    _auth,
    _resolving,
    _status,
    proxy,
)

CRLF = b"\r\n"


class _UpstreamStub:
    """An HTTP proxy that accepts CONNECT, answers 200 and echoes one read."""

    def __init__(self, reply_status: bytes = b"200 Connection established"):
        self.reply_status = reply_status
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.heads: list[bytes] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._one, args=(conn,),
                             daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2)
            data = b""
            while CRLF + CRLF not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            self.heads.append(data)
            conn.sendall(b"HTTP/1.1 " + self.reply_status + CRLF + CRLF)
            if not self.reply_status.startswith(b"200"):
                return
            payload = conn.recv(65536)
            conn.sendall(b"echo:" + payload)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def upstream(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    stub = _UpstreamStub()
    monkeypatch.setenv(
        "HTTPS_PROXY", f"http://corpuser:p%40ss@127.0.0.1:{stub.port}")
    monkeypatch.setenv(
        "HTTP_PROXY", f"http://corpuser:p%40ss@127.0.0.1:{stub.port}")
    yield stub
    stub.close()


def _tunnel(proxy_, target: str, payload: bytes) -> tuple[bytes, bytes]:
    sock = socket.create_connection(("127.0.0.1", proxy_.port), timeout=5)
    try:
        sock.sendall(f"CONNECT {target} HTTP/1.1".encode() + CRLF
                     + f"Proxy-Authorization: {_auth(proxy_)}".encode()
                     + CRLF + CRLF)
        head = b""
        while CRLF + CRLF not in head:
            chunk = sock.recv(4096)
            if not chunk:
                break
            head += chunk
        if not head.startswith(b"HTTP/1.1 200"):
            return head, b""
        sock.sendall(payload)
        got = b""
        while not got.startswith(b"echo:" + payload[:1]) or len(got) < 5 + len(
                payload):
            chunk = sock.recv(4096)
            if not chunk:
                break
            got += chunk
        return head, got
    finally:
        sock.close()


def test_connect_goes_to_the_checked_numeric_address(
        proxy, upstream, monkeypatch):
    _resolving(monkeypatch, {"site.example": ["93.184.216.34"]})
    head, got = _tunnel(proxy, "site.example:443", b"hello")
    assert head.startswith(b"HTTP/1.1 200")
    assert got == b"echo:hello"
    seen = upstream.heads[0]
    assert seen.startswith(b"CONNECT 93.184.216.34:443 HTTP/1.1")
    assert b"site.example" not in seen  # the name never reaches the upstream
    cred = base64.b64encode(b"corpuser:p@ss")
    assert b"Proxy-Authorization: Basic " + cred in seen


def test_a_name_resolving_to_an_internal_address_never_reaches_the_upstream(
        proxy, upstream, monkeypatch):
    _resolving(monkeypatch, {"rebind.example": ["127.0.0.1"]})
    head, _ = _tunnel(proxy, "rebind.example:443", b"x")
    assert _status(head) == 403
    _resolving(monkeypatch, {"meta.example": ["169.254.169.254"]})
    head, _ = _tunnel(proxy, "meta.example:80", b"x")
    assert _status(head) == 403
    assert upstream.connections == 0


def test_the_upstream_receives_the_address_of_the_first_answer_only(
        proxy, upstream, monkeypatch):
    calls = []
    real = socket.getaddrinfo
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])

    def flip(host, port, *a, **kw):
        if host == "flip.example":
            calls.append(host)
            addr = next(answers)[0]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", flip)
    _tunnel(proxy, "flip.example:443", b"x")
    assert calls == ["flip.example"]
    assert upstream.heads[0].startswith(b"CONNECT 93.184.216.34:443")


def test_plain_http_is_tunnelled_to_the_checked_address_too(
        proxy, upstream, monkeypatch):
    _resolving(monkeypatch, {"site.example": ["93.184.216.34"]})
    sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    try:
        sock.sendall(b"GET http://site.example/p?q=1 HTTP/1.1" + CRLF
                     + f"Proxy-Authorization: {_auth(proxy)}".encode() + CRLF
                     + b"Host: site.example" + CRLF + CRLF)
        got = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            got += chunk
    finally:
        sock.close()
    assert got.startswith(b"echo:GET /p?q=1 HTTP/1.1")
    assert b"Host: site.example" in got  # the Host header keeps the name
    assert upstream.heads[0].startswith(b"CONNECT 93.184.216.34:80")


def test_no_proxy_is_honoured(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://corp.example:3128")
    monkeypatch.setenv("NO_PROXY", "site.example,.internal.test")
    assert dlproxy.upstream_proxy_for("https", "site.example") is None
    assert dlproxy.upstream_proxy_for("https", "a.internal.test") is None
    assert dlproxy.upstream_proxy_for("https", "other.example") is not None
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.delenv("https_proxy", raising=False)
    assert dlproxy.upstream_proxy_for("https", "other.example") is None


def test_an_unsupported_upstream_proxy_is_an_error_not_a_direct_connection(
        proxy, monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "socks5://corp.example:1080")
    _resolving(monkeypatch, {"site.example": ["93.184.216.34"]})
    direct = []
    monkeypatch.setattr(dlproxy, "connect_checked",
                        lambda *a, **k: direct.append(a) or None)
    head, _ = _tunnel(proxy, "site.example:443", b"x")
    assert _status(head) == 502 and b"only an http:// proxy" in head
    assert direct == []  # never fell back to a direct connection


def test_an_upstream_that_refuses_connect_gives_502(
        proxy, monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
                 "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    stub = _UpstreamStub(reply_status=b"403 Forbidden")
    try:
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{stub.port}")
        _resolving(monkeypatch, {"site.example": ["93.184.216.34"]})
        head, _ = _tunnel(proxy, "site.example:443", b"x")
        assert _status(head) == 502
    finally:
        stub.close()
