"""The download proxy of server link jobs (roadmap S1c).

A stub client (urllib through the proxy, like yt-dlp) and raw sockets talk to
the proxy; local listeners stand in for "internal" hosts. The core assertion
is that a refused destination gets 0 connections. Every refusal test has a
positive control with the same plumbing where the guard is lifted, so a zero
cannot come from a broken harness.

Hermetic: loopback sockets with ephemeral ports only.
"""
from __future__ import annotations

import base64
import socket
import threading
import urllib.error
import urllib.request

import pytest

from core import server
from core.server import dlproxy, netguard


class _Listener:
    """Loopback listener that counts connections and answers a fixed reply."""

    def __init__(self, reply: bytes = b"", host: str = "127.0.0.1") -> None:
        self.reply = reply or (b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                               b"Connection: close\r\n\r\nok")
        self.sock = socket.socket()
        self.sock.bind((host, 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.received: list[bytes] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            try:
                conn.settimeout(2)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                self.received.append(data)
                conn.sendall(self.reply)
            except OSError:
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def private(monkeypatch):
    srv = _Listener()
    # Open the listener's port, so the ADDRESS check is what refuses it.
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {srv.port})
    yield srv
    srv.close()


@pytest.fixture
def proxy():
    p = dlproxy.DownloadProxy()
    yield p
    p.close()


def _auth(p: dlproxy.DownloadProxy) -> str:
    pw = p.url.split("//wts:", 1)[1].split("@", 1)[0]
    return "Basic " + base64.b64encode(f"wts:{pw}".encode()).decode()


def _talk(p: dlproxy.DownloadProxy, head: str, *, auth: bool = True) -> bytes:
    """Send a raw request head to the proxy; return everything it answers."""
    lines = [head, "Host: x"]
    if auth:
        lines.append(f"Proxy-Authorization: {_auth(p)}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    sock = socket.create_connection(("127.0.0.1", p.port), timeout=5)
    try:
        sock.sendall(request)
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


def _status(reply: bytes) -> int:
    return int(reply.split(b" ", 2)[1])


def _resolving(monkeypatch, table: dict[str, list[str]]) -> None:
    """Make chosen host names resolve to chosen addresses; others are real."""
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host in table:
            out = []
            for addr in table[host]:
                fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
                sockaddr = (addr, port, 0, 0) if ":" in addr else (addr, port)
                out.append((fam, socket.SOCK_STREAM, 6, "", sockaddr))
            return out
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _lift_guard(monkeypatch, blocked: tuple[str, ...] = ()) -> None:
    monkeypatch.setattr(
        netguard, "address_blocked",
        lambda ip, allow_private=True: str(ip) in blocked)


# --- refusals: 0 connections reach the internal listener ------------------------

def test_connect_to_a_loopback_listener_is_refused(proxy, private):
    reply = _talk(proxy, f"CONNECT 127.0.0.1:{private.port} HTTP/1.1")
    assert _status(reply) == 403
    assert private.connections == 0


@pytest.mark.parametrize("target", [
    "[::1]:80", "169.254.169.254:80", "10.0.0.5:80", "192.168.1.20:443",
    "172.16.0.9:80", "100.64.0.9:80", "0.0.0.0:80", "224.0.0.1:80",
    "[fe80::1]:80", "[::ffff:127.0.0.1]:80",
])
def test_connect_to_non_public_addresses_is_refused(proxy, target):
    assert _status(_talk(proxy, f"CONNECT {target} HTTP/1.1")) == 403


def test_a_name_that_resolves_to_loopback_is_refused(
        proxy, private, monkeypatch):
    _resolving(monkeypatch, {"rebind.example": ["127.0.0.1"]})
    reply = _talk(proxy, f"CONNECT rebind.example:{private.port} HTTP/1.1")
    assert _status(reply) == 403
    reply = _talk(
        proxy, f"GET http://rebind.example:{private.port}/x HTTP/1.1")
    assert _status(reply) == 403
    assert private.connections == 0


def test_one_bad_answer_refuses_the_name(proxy, private, monkeypatch):
    _resolving(monkeypatch, {"mixed.example": ["93.184.216.34", "127.0.0.1"]})
    reply = _talk(proxy, f"CONNECT mixed.example:{private.port} HTTP/1.1")
    assert _status(reply) == 403
    assert private.connections == 0


def test_plain_http_to_loopback_is_refused_even_with_user_info(proxy, private):
    for url in (f"http://127.0.0.1:{private.port}/a",
                f"http://public.example@127.0.0.1:{private.port}/a",
                f"http://localhost:{private.port}/a"):
        assert _status(_talk(proxy, f"GET {url} HTTP/1.1")) == 403
    assert private.connections == 0


def test_requests_without_the_password_are_refused(proxy, private):
    head = f"CONNECT 127.0.0.1:{private.port} HTTP/1.1"
    assert _status(_talk(proxy, head, auth=False)) == 407
    bad = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    bad.sendall(f"{head}\r\nProxy-Authorization: Basic d3RzOm5vcGU=\r\n\r\n"
                .encode())
    assert bad.recv(100).startswith(b"HTTP/1.1 407")
    bad.close()
    assert private.connections == 0


def test_other_methods_and_junk_are_refused(proxy):
    assert _status(_talk(proxy, "GET /relative HTTP/1.1")) == 400
    assert _status(_talk(proxy, "GET https://example.com/ HTTP/1.1")) == 400
    assert _status(_talk(proxy, "NONSENSE")) == 400
    assert _status(_talk(proxy, "CONNECT nohost HTTP/1.1")) == 400
    assert _status(_talk(proxy, "CONNECT x:99999 HTTP/1.1")) == 400


# --- positive controls: the same plumbing reaches a listener when allowed -------

def test_connect_tunnel_relays_bytes_when_the_address_is_allowed(
        proxy, private, monkeypatch):
    _lift_guard(monkeypatch)
    sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    try:
        sock.sendall(
            f"CONNECT 127.0.0.1:{private.port} HTTP/1.1\r\n"
            f"Proxy-Authorization: {_auth(proxy)}\r\n\r\n".encode())
        assert sock.recv(100).startswith(b"HTTP/1.1 200")
        sock.sendall(b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
        data = b""
        while not data.endswith(b"ok"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        assert data.endswith(b"ok")
    finally:
        sock.close()
    assert private.connections == 1
    assert private.received[0].startswith(b"GET /hello")


def test_plain_http_is_forwarded_in_origin_form(proxy, private, monkeypatch):
    _lift_guard(monkeypatch)
    reply = _talk(proxy, f"GET http://127.0.0.1:{private.port}/p?q=1 HTTP/1.1")
    assert _status(reply) == 200 and reply.endswith(b"ok")
    sent = private.received[0]
    assert sent.startswith(b"GET /p?q=1 HTTP/1.1")
    assert b"Proxy-Authorization" not in sent
    assert b"Connection: close" in sent


# --- a stub extractor (urllib, like yt-dlp) through the proxy -------------------

def _opener(proxy: dlproxy.DownloadProxy):
    return urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy.url, "https": proxy.url}))


def test_stub_extractor_cannot_reach_an_internal_host(
        proxy, private, monkeypatch):
    _resolving(monkeypatch, {"media.example": ["127.0.0.1"]})
    opener = _opener(proxy)
    with pytest.raises(urllib.error.HTTPError) as info:
        opener.open(f"http://media.example:{private.port}/v.mp4", timeout=5)
    assert info.value.code == 403
    with pytest.raises(urllib.error.URLError):
        opener.open(f"https://media.example:{private.port}/v.mp4", timeout=5)
    assert private.connections == 0
    # Control: the same stub reaches the listener once the guard is lifted.
    _lift_guard(monkeypatch)
    assert opener.open(
        f"http://media.example:{private.port}/v.mp4", timeout=5).read() == b"ok"
    assert private.connections == 1


def test_a_redirect_to_an_internal_host_is_refused(proxy, monkeypatch):
    """The redirect is a new request through the proxy, so it is checked."""
    try:
        internal = _Listener(host="127.0.0.2")
    except OSError:
        pytest.skip("127.0.0.2 is not available as a loopback address here")
    public = None
    try:
        monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                            dlproxy.ALLOWED_PORTS | {internal.port})
        _resolving(monkeypatch, {"public.example": ["127.0.0.1"],
                                 "internal.example": ["127.0.0.2"]})
        # "public.example" is allowed, 127.0.0.2 stays blocked.
        _lift_guard(monkeypatch, blocked=("127.0.0.2",))
        public = _Listener(
            reply=(b"HTTP/1.1 302 Found\r\nLocation: http://internal.example:"
                   + str(internal.port).encode() + b"/secret\r\n"
                   b"Content-Length: 0\r\nConnection: close\r\n\r\n"))
        monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                            dlproxy.ALLOWED_PORTS | {internal.port, public.port})
        with pytest.raises(urllib.error.HTTPError) as info:
            _opener(proxy).open(
                f"http://public.example:{public.port}/start", timeout=5)
        assert info.value.code == 403
        assert public.connections == 1  # the first hop was allowed
        assert internal.connections == 0  # the redirect target never was
    finally:
        internal.close()
        if public:
            public.close()


# --- limits ------------------------------------------------------------------------

def test_oversized_headers_are_refused(proxy):
    big = "CONNECT example.com:443 HTTP/1.1\r\nX-Pad: " + "a" * 20000 + "\r\n\r\n"
    sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    try:
        sock.sendall(big.encode())
        assert sock.recv(100).startswith(b"HTTP/1.1 400")
    finally:
        sock.close()


# --- the server job uses it, and fails closed -----------------------------------

class _FakePopen:
    seen: list = []
    returncode = 0

    envs: list = []

    def __init__(self, cmd, **kwargs):
        type(self).seen.append(list(cmd))
        type(self).envs.append(kwargs.get("env"))
        self.pid = 4242

    def communicate(self, timeout=None):
        return "", ""

    def poll(self):
        return None


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    _FakePopen.seen = []
    _FakePopen.envs = []
    _FakePopen.returncode = 0
    monkeypatch.setattr(server.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])


def test_server_job_goes_through_the_proxy_without_a_password_in_argv(
        tmp_path, fake_yt_dlp, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("http_proxy", "http://corp.example:3128")
    (tmp_path / "clip.mp4").write_bytes(b"media")
    server._download_url("https://example.com/v", str(tmp_path))
    cmd = _FakePopen.seen[0]
    url = dlproxy.shared_proxy().url
    password = url.split("//wts:", 1)[1].split("@", 1)[0]
    assert "--proxy" not in cmd
    assert not any(password in part for part in cmd), "password in argv"
    env = _FakePopen.envs[0]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert env[name] == url
    assert env["NO_PROXY"] == ""
    assert "http_proxy" not in env  # the user's own proxy setting is replaced
    assert url.startswith("http://wts:") and "@127.0.0.1:" in url
    assert cmd[cmd.index("--downloader") + 1] == "native"


def test_a_failed_download_error_does_not_carry_the_password(
        tmp_path, fake_yt_dlp):
    import subprocess

    _FakePopen.returncode = 1
    password = dlproxy.shared_proxy().url.split("//wts:", 1)[1].split("@")[0]
    with pytest.raises(subprocess.CalledProcessError) as info:
        server._download_url("https://example.com/v", str(tmp_path))
    assert password not in repr(info.value.cmd)
    assert password not in str(info.value)


def test_server_job_does_not_run_without_the_proxy(
        tmp_path, fake_yt_dlp, monkeypatch):
    def boom():
        raise OSError(10048, "address in use")

    monkeypatch.setattr(server, "shared_proxy", boom)
    with pytest.raises(RuntimeError, match="download guard could not start"):
        server._download_url("https://example.com/v", str(tmp_path))
    assert _FakePopen.seen == []


def test_only_ports_80_and_443_are_relayed(proxy, monkeypatch):
    other = _Listener()
    try:
        # Address check lifted: only the PORT rule can refuse this.
        _lift_guard(monkeypatch)
        reply = _talk(proxy, f"CONNECT 127.0.0.1:{other.port} HTTP/1.1")
        assert _status(reply) == 403 and b"port refused" in reply
        reply = _talk(proxy, f"GET http://127.0.0.1:{other.port}/ HTTP/1.1")
        assert _status(reply) == 403
        assert other.connections == 0
    finally:
        other.close()
