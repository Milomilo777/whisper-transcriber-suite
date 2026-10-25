"""SSRF hardening of server-submitted URL jobs and of the webhook (roadmap S1b).

* a server job never lets yt-dlp use its generic extractor, and a direct
  media link is refused with a clear message;
* the webhook checks the address a name resolves to at connect time, on the
  addresses it connects to (DNS rebinding), and still reaches LAN receivers;
* the desktop Download tab command is unchanged.

Hermetic: local listeners on ephemeral loopback ports only, fakes elsewhere.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import urllib.error

import pytest

from app.services import download_service as ds
from core import server
from core.server import jobs as jobs_mod
from core.server import netguard
from core.server.jobs import post_webhook


# --- the generic extractor is off for server jobs ------------------------------

class _FakePopen:
    seen: list = []
    stderr_text = ""
    returncode = 0

    def __init__(self, cmd, **kwargs):
        type(self).seen.append(list(cmd))
        self.pid = 4242

    def communicate(self, timeout=None):
        return "", type(self).stderr_text

    def poll(self):
        return None


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    _FakePopen.seen = []
    _FakePopen.stderr_text = ""
    _FakePopen.returncode = 0
    monkeypatch.setattr(server.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])


def test_server_job_command_switches_the_generic_extractor_off(
        tmp_path, fake_yt_dlp):
    (tmp_path / "clip.mp4").write_bytes(b"media")
    server._download_url("https://example.com/v", str(tmp_path))
    cmd = _FakePopen.seen[0]
    assert cmd[cmd.index("--use-extractors") + 1] == "default,-generic"
    # An option, so before the end-of-options separator and the URL.
    assert cmd.index("--use-extractors") < cmd.index("--")
    assert cmd[-2:] == ["--", "https://example.com/v"]


@pytest.mark.parametrize("stderr", [
    "ERROR: No suitable extractor found for URL http://x.test/a.mp3\n",
    "ERROR: Unsupported URL: http://x.test/a.mp3\n",
])
def test_direct_media_link_is_refused_with_a_clear_message(
        tmp_path, fake_yt_dlp, stderr):
    _FakePopen.returncode = 1
    _FakePopen.stderr_text = stderr
    with pytest.raises(RuntimeError, match="not from a site the server can"):
        server._download_url("http://x.test/a.mp3", str(tmp_path))


def test_other_download_failures_keep_their_own_error(tmp_path, fake_yt_dlp):
    import subprocess

    _FakePopen.returncode = 1
    _FakePopen.stderr_text = "ERROR: HTTP Error 404: Not Found\n"
    with pytest.raises(subprocess.CalledProcessError):
        server._download_url("https://example.com/v", str(tmp_path))


def test_desktop_download_command_is_unchanged():
    from app.domain.tasks import VideoDownloadTask

    task = VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc", folder="C:/out",
        format_label="x",
        format_info={"mode": "Audio and video", "output": "mp4",
                     "audio": {"kind": "best_audio"},
                     "video": {"kind": "best_video"}})
    cmd = ds.build_download_command(task, yt_dlp_path="y", bin_path="")
    assert "--use-extractors" not in cmd and "--ies" not in cmd


# --- connect-time address check -------------------------------------------------

def _answers(*addrs):
    def fake_getaddrinfo(host, port, *a, **kw):
        out = []
        for addr in addrs:
            fam = (socket.AF_INET6 if ":" in addr else socket.AF_INET)
            sockaddr = (addr, port, 0, 0) if ":" in addr else (addr, port)
            out.append((fam, socket.SOCK_STREAM, 6, "", sockaddr))
        return out
    return fake_getaddrinfo


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "127.8.9.10", "::1", "169.254.169.254", "0.0.0.0",
    "::ffff:127.0.0.1", "fe80::1", "224.0.0.1",
])
def test_names_resolving_to_internal_addresses_are_refused(monkeypatch, addr):
    monkeypatch.setattr(socket, "getaddrinfo", _answers(addr))
    with pytest.raises(netguard.BlockedAddressError):
        netguard.resolve_checked("rebind.example", 80)


def test_one_bad_answer_refuses_the_whole_name(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        _answers("93.184.216.34", "127.0.0.1"))
    with pytest.raises(netguard.BlockedAddressError):
        netguard.resolve_checked("mixed.example", 80)


@pytest.mark.parametrize("addr", ["10.0.0.5", "192.168.1.20", "172.16.3.4",
                                  "93.184.216.34"])
def test_lan_and_public_names_are_allowed_by_default(monkeypatch, addr):
    monkeypatch.setattr(socket, "getaddrinfo", _answers(addr))
    assert netguard.resolve_checked("ok.example", 80)


def test_private_addresses_can_be_refused_too(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _answers("192.168.1.20"))
    with pytest.raises(netguard.BlockedAddressError):
        netguard.resolve_checked("lan.example", 80, allow_private=False)
    monkeypatch.setattr(socket, "getaddrinfo", _answers("100.64.0.9"))
    with pytest.raises(netguard.BlockedAddressError):  # CGNAT / tailnet
        netguard.resolve_checked("cgnat.example", 80, allow_private=False)


class _Listener:
    """A loopback listener counting the connections it receives."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.requests: list[bytes] = []
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            try:
                conn.settimeout(2)
                self.requests.append(self._read_request(conn))
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n"
                             b"Connection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                conn.close()

    @staticmethod
    def _read_request(conn: socket.socket) -> bytes:
        end = b"\r\n\r\n"
        data = b""
        while end not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return data
            data += chunk
        head, _, body = data.partition(end)
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        while len(body) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
        return head + end + body

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def listener():
    srv = _Listener()
    yield srv
    srv.close()


def test_webhook_rebinding_to_loopback_reaches_nothing(monkeypatch, listener):
    """The first check passes (public answer); the connect-time lookup says
    127.0.0.1: nothing may connect."""
    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda _u: True)
    monkeypatch.setattr(socket, "getaddrinfo", _answers("127.0.0.1"))
    with pytest.raises(urllib.error.URLError) as info:
        post_webhook(f"http://rebind.example:{listener.port}/hook", {"a": 1})
    assert isinstance(info.value.reason, netguard.BlockedAddressError)
    assert listener.connections == 0


def test_webhook_connects_only_to_the_checked_address(monkeypatch, listener):
    """Positive control: when the guard allows the address, the very same call
    reaches the listener, so the zero above is not an artefact."""
    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda _u: True)
    monkeypatch.setattr(socket, "getaddrinfo", _answers("127.0.0.1"))
    monkeypatch.setattr(netguard, "address_blocked",
                        lambda ip, allow_private=True: False)
    post_webhook(f"http://lan.example:{listener.port}/hook", {"a": 1})
    assert listener.connections == 1
    assert listener.requests[0].startswith(b"POST /hook")
    assert b"Host: lan.example" in listener.requests[0]


def test_webhook_resolves_once_so_a_second_answer_cannot_win(
        monkeypatch, listener):
    calls = []
    answers = iter([["127.0.0.1"], ["8.8.8.8"]])

    def flip(host, port, *a, **kw):
        calls.append(host)
        return _answers(*next(answers))(host, port)

    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda _u: True)
    monkeypatch.setattr(socket, "getaddrinfo", flip)
    with pytest.raises(urllib.error.URLError) as info:
        post_webhook(f"http://flip.example:{listener.port}/hook", {})
    assert isinstance(info.value.reason, netguard.BlockedAddressError)
    assert len(calls) == 1
    assert listener.connections == 0


def test_address_blocked_matches_the_old_job_url_rules():
    for text in ("127.0.0.1", "169.254.169.254", "::1", "0.0.0.0"):
        assert netguard.address_blocked(ipaddress.ip_address(text))
    for text in ("10.1.2.3", "192.168.0.9", "93.184.216.34"):
        assert not netguard.address_blocked(ipaddress.ip_address(text))


# --- link jobs refuse private-network hosts up front ----------------------------

@pytest.mark.parametrize("url", [
    "http://10.0.0.5/v", "https://192.168.1.20/v", "http://172.16.3.4/v",
    "http://100.64.0.9/v", "http://127.0.0.1/v",
])
def test_link_jobs_refuse_private_network_literals(url):
    assert not jobs_mod.is_safe_url(url, allow_private=False)


def test_default_is_safe_url_still_allows_the_lan(monkeypatch):
    assert jobs_mod.is_safe_url("http://192.168.1.20/hook")
    monkeypatch.setattr(socket, "getaddrinfo", _answers("192.168.1.20"))
    assert jobs_mod.is_safe_url("http://nas.example/hook")
    assert not jobs_mod.is_safe_url("http://nas.example/v", allow_private=False)


def test_submit_url_refuses_a_lan_host(tmp_path):
    mgr = jobs_mod.JobManager(lambda *a, **k: None,
                              jobs_root=str(tmp_path / "jobs"),
                              record_history=False)
    with pytest.raises(ValueError, match="local-network"):
        mgr.submit_url("http://192.168.1.20/v", ["srt"])


# --- the webhook ignores environment proxies -------------------------------------

@pytest.mark.parametrize("scheme,var", [("http", "HTTP_PROXY"),
                                        ("https", "HTTPS_PROXY")])
def test_webhook_ignores_proxy_environment(monkeypatch, listener, scheme, var):
    """With a proxy in the environment the guard would only see the proxy
    (which then resolves the real target itself). The webhook must connect
    itself, never through the proxy."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, f"http://127.0.0.1:{listener.port}")
    monkeypatch.setattr(jobs_mod, "is_safe_url", lambda _u, **_k: True)
    # Let the guard pass loopback so the proxy would be reachable; the hook
    # host is a different, closed port: only a proxy path can reach `listener`.
    monkeypatch.setattr(netguard, "address_blocked",
                        lambda ip, allow_private=True: False)
    monkeypatch.setattr(socket, "getaddrinfo", _answers("127.0.0.1"))
    with pytest.raises(urllib.error.URLError):
        post_webhook(f"{scheme}://hook.example:9/x", {}, timeout=3)
    assert listener.connections == 0


# --- NAT64 / translation prefixes ------------------------------------------------

@pytest.mark.parametrize("addr", [
    "64:ff9b::a9fe:a9fe",        # well-known NAT64 -> 169.254.169.254
    "64:ff9b::7f00:1",           # -> 127.0.0.1
    "64:ff9b:1::a9fe:a9fe",      # local-use NAT64
    "2001:4860:64::a9fe:a9fe",   # operator /96 prefix -> 169.254.169.254
    "2001:db8:1:2:3:4:7f00:1",   # operator /96 prefix -> 127.0.0.1
    "2002:a9fe:a9fe::1",         # 6to4 of the metadata address
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
])
def test_translation_prefixes_embedding_blocked_ipv4_are_refused(addr):
    assert netguard.address_blocked(ipaddress.ip_address(addr))


@pytest.mark.parametrize("addr", [
    "2606:4700:4700::1111", "2a00:1450:4001:81b::200e", "2001:4860:4860::8888",
])
def test_ordinary_global_ipv6_stays_allowed(addr):
    assert not netguard.address_blocked(ipaddress.ip_address(addr))


def test_well_known_nat64_is_refused_even_for_public_targets():
    """64:ff9b::/96 is in Python's reserved ::/8; an IPv6-only host with DNS64
    cannot use link jobs or webhooks (documented)."""
    assert netguard.address_blocked(ipaddress.ip_address("64:ff9b::5db8:d822"))


def test_translation_prefix_to_a_private_range_follows_allow_private():
    ip = ipaddress.ip_address("2001:4860:64::c0a8:114")  # -> 192.168.1.20
    assert not netguard.address_blocked(ip)
    assert netguard.address_blocked(ip, allow_private=False)
