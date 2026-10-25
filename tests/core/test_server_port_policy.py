"""Link jobs use the download proxy's destination ports (80 and 443) everywhere.

The proxy already refuses other ports; the direct LAN fetch (lanfetch) and the
submit-time URL check follow the same rule, on the first URL and on every
redirect hop, so a link job cannot probe other services of an allowed LAN host
and the error text is no port oracle.

Hermetic: loopback listeners with ephemeral ports only.
"""
from __future__ import annotations

import http.server
import ipaddress
import threading

import pytest

import core.server as server
from core import config as config_mod
from core.server import dlproxy, lanfetch, netguard
from core.server import jobs as jobs_mod
from core.server.jobs import DownloadLimits

BODY = b"RIFF" + bytes(range(256)) * 8


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(netguard, "_networks_cache", (float("-inf"), ()))


class _Origin(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []
    redirect_to = ""

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        if self.path.startswith("/hop") and type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)


def _start(handler_cls):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture
def origins(monkeypatch):
    """Two listeners ("first" and "second") that count requests."""
    class First(_Origin):
        hits: list[str] = []

    class Second(_Origin):
        hits: list[str] = []

    one, two = _start(First), _start(Second)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        netguard, "configured_private_networks",
        lambda: (ipaddress.ip_network("127.0.0.0/8"),))
    monkeypatch.setattr(
        netguard, "address_blocked", lambda ip, allow_private=True, **kw: False)
    yield First, Second, one.server_address[1], two.server_address[1]
    for httpd in (one, two):
        httpd.shutdown()
        httpd.server_close()


def _limits():
    return DownloadLimits(cancelled=lambda: False)


def test_a_first_url_on_a_disallowed_port_is_refused_without_connecting(
        origins, tmp_path, monkeypatch):
    first, _second, port1, _port2 = origins
    # Control: with the port allowed the very same fetch works.
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {port1})
    path = lanfetch.fetch(f"http://127.0.0.1:{port1}/a.wav", str(tmp_path),
                          _limits())
    assert open(path, "rb").read() == BODY
    assert first.hits == ["/a.wav"]
    # The real rule: the port is not allowed, nothing is sent.
    monkeypatch.undo()
    first.hits.clear()
    monkeypatch.setattr(
        netguard, "address_blocked", lambda ip, allow_private=True, **kw: False)
    with pytest.raises(RuntimeError, match="only ports 80 and 443"):
        lanfetch.fetch(f"http://127.0.0.1:{port1}/b.wav", str(tmp_path),
                       _limits())
    assert first.hits == []


def test_a_redirect_to_a_disallowed_port_is_refused_before_connecting(
        origins, tmp_path, monkeypatch):
    first, second, port1, port2 = origins
    first.redirect_to = f"http://127.0.0.1:{port2}/secret.wav"
    # Only the first port is allowed: the second hop must be refused.
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {port1})
    with pytest.raises(RuntimeError, match="only ports 80 and 443"):
        lanfetch.fetch(f"http://127.0.0.1:{port1}/hop", str(tmp_path),
                       _limits())
    assert first.hits == ["/hop"]
    assert second.hits == [], "the disallowed hop was contacted"
    # Control: allow the second port and the same redirect is followed.
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {port1, port2})
    path = lanfetch.fetch(f"http://127.0.0.1:{port1}/hop", str(tmp_path),
                          _limits())
    assert open(path, "rb").read() == BODY
    assert second.hits == ["/secret.wav"]


def test_the_refusal_text_is_the_same_whatever_listens_on_the_port(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        netguard, "configured_private_networks",
        lambda: (ipaddress.ip_network("127.0.0.0/8"),))
    messages = set()
    for port in (1, 22, 8080):  # closed, "ssh", "alt-http": no connect is made
        with pytest.raises(RuntimeError) as info:
            lanfetch.fetch(f"http://127.0.0.1:{port}/x", str(tmp_path),
                           _limits())
        messages.add(str(info.value))
    assert messages == {lanfetch.PORT_REFUSED}


def test_is_lan_direct_url_follows_the_port_rule(monkeypatch):
    monkeypatch.setattr(
        netguard, "configured_private_networks",
        lambda: (ipaddress.ip_network("127.0.0.0/8"),))
    assert lanfetch.is_lan_direct_url("http://127.0.0.1/a.wav")
    assert lanfetch.is_lan_direct_url("https://127.0.0.1:443/a.wav")
    assert not lanfetch.is_lan_direct_url("http://127.0.0.1:8080/a.wav")
    assert not lanfetch.is_lan_direct_url("http://127.0.0.1:22/a.wav")
    # The download dispatcher then never takes the direct branch.
    assert "ports" not in server.DIRECT_LINK_REFUSED  # sanity: unchanged text


def test_a_malformed_port_in_a_redirect_is_refused(origins, tmp_path,
                                                   monkeypatch):
    first, _second, port1, _port2 = origins
    first.redirect_to = "http://127.0.0.1:99999/x"
    monkeypatch.setattr(dlproxy, "ALLOWED_PORTS",
                        dlproxy.ALLOWED_PORTS | {port1})
    with pytest.raises(RuntimeError, match="only ports 80 and 443"):
        lanfetch.fetch(f"http://127.0.0.1:{port1}/hop", str(tmp_path),
                       _limits())


@pytest.mark.parametrize("url,expected", [
    ("http://93.184.216.34/v", True),
    ("http://93.184.216.34:80/v", True),
    ("https://93.184.216.34:443/v", True),
    ("http://93.184.216.34:8080/v", False),
    ("https://93.184.216.34:22/v", False),
    ("http://93.184.216.34:99999/v", False),
])
def test_submit_time_check_uses_the_proxy_ports(url, expected):
    assert jobs_mod.is_safe_url(url, allow_private=False,
                                restrict_ports=True) is expected


def test_the_default_check_still_allows_any_port_for_webhooks():
    assert jobs_mod.is_safe_url("http://93.184.216.34:8080/hook")


def test_submit_url_refuses_a_disallowed_port(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_mod, "load_config",
        lambda **_k: {"server_allowed_private_networks": ["192.168.1.0/24"]})
    mgr = jobs_mod.JobManager(lambda *a, **k: None,
                              jobs_root=str(tmp_path / "jobs"),
                              record_history=False)
    assert mgr.submit_url("http://192.168.1.20:80/v", ["srt"])
    with pytest.raises(ValueError, match="port 80 or 443"):
        mgr.submit_url("http://192.168.1.20:2222/v", ["srt"])
