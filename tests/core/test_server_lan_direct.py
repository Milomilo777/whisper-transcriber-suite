"""Direct media links on an allowlisted local network (review round 3).

With the generic yt-dlp extractor off, a plain NAS link would be refused. A
link whose host lies inside ``server_allowed_private_networks`` is fetched by
the app's own downloader instead, with the connect-time address check on
every hop. Loopback listeners with ephemeral ports only: the allowlist and the
address check are patched so 127.0.0.1 can stand in for a LAN host.
"""
from __future__ import annotations

import http.server
import ipaddress
import os
import subprocess
import threading

import pytest

import core.server as server
from core import offline
from core.server import netguard
from core.server.jobs import DownloadCancelled, DownloadLimits

PAYLOAD = b"RIFF" + bytes(range(256)) * 40


class _Origin(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        if self.path.startswith("/redirect-meta"):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest")
            self.end_headers()
            return
        if self.path.startswith("/redirect-ftp"):
            self.send_response(302)
            self.send_header("Location", "ftp://127.0.0.1/x")
            self.end_headers()
            return
        if self.path.startswith("/missing"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)


@pytest.fixture
def origin():
    _Origin.hits = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Origin)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    # 127.0.0.1 stands in for a host of the allowlisted LAN.
    monkeypatch.setattr(
        netguard, "configured_private_networks",
        lambda: (ipaddress.ip_network("127.0.0.0/8"),))

    def no_yt_dlp(*a, **k):
        raise AssertionError("yt-dlp must not be used for a LAN direct link")

    monkeypatch.setattr(subprocess, "Popen", no_yt_dlp)


def _lift_guard(monkeypatch, blocked=("169.254.169.254",)):
    monkeypatch.setattr(
        netguard, "address_blocked",
        lambda ip, allow_private=True, **kw: str(ip) in blocked)


def _limits(**kw):
    return DownloadLimits(cancelled=lambda: False, **kw)


def test_a_direct_link_on_an_allowlisted_network_is_downloaded(
        origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    path = server._download_url(
        f"http://127.0.0.1:{origin}/media/talk%20one.wav", str(tmp_path),
        _limits())
    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path) == "talk one.wav"
    assert open(path, "rb").read() == PAYLOAD
    assert os.listdir(tmp_path) == ["talk one.wav"]  # no .part left behind


def test_the_connect_time_check_still_runs_for_a_listed_host(
        origin, tmp_path):
    """Allowlisted, but loopback is refused whatever is listed."""
    with pytest.raises(netguard.BlockedAddressError):
        server._download_url(f"http://127.0.0.1:{origin}/a.wav",
                             str(tmp_path), _limits())
    assert _Origin.hits == []
    assert os.listdir(tmp_path) == []


def test_a_redirect_to_a_blocked_address_is_refused(
        origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    with pytest.raises(netguard.BlockedAddressError):
        server._download_url(f"http://127.0.0.1:{origin}/redirect-meta",
                             str(tmp_path), _limits())
    assert os.listdir(tmp_path) == []


def test_a_redirect_to_another_scheme_is_refused(origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    with pytest.raises(RuntimeError):
        server._download_url(f"http://127.0.0.1:{origin}/redirect-ftp",
                             str(tmp_path), _limits())
    assert os.listdir(tmp_path) == []


def test_the_size_cap_and_cancel_are_honoured(origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    with pytest.raises(RuntimeError, match="larger"):
        server._download_url(f"http://127.0.0.1:{origin}/a.wav",
                             str(tmp_path), _limits(max_bytes=100))
    assert os.listdir(tmp_path) == []
    with pytest.raises(DownloadCancelled):
        server._download_url(f"http://127.0.0.1:{origin}/a.wav",
                             str(tmp_path), DownloadLimits(cancelled=lambda: True))
    assert os.listdir(tmp_path) == []


def test_an_http_error_is_reported_and_leaves_nothing(
        origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    with pytest.raises(RuntimeError, match="404"):
        server._download_url(f"http://127.0.0.1:{origin}/missing.wav",
                             str(tmp_path), _limits())
    assert os.listdir(tmp_path) == []


def test_work_offline_refuses_the_direct_download(origin, tmp_path, monkeypatch):
    _lift_guard(monkeypatch)
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    with pytest.raises(offline.OfflineModeError):
        server._download_url(f"http://127.0.0.1:{origin}/a.wav",
                             str(tmp_path), _limits())
    assert _Origin.hits == []


def test_a_host_outside_the_allowlist_keeps_using_the_downloader(
        tmp_path, monkeypatch):
    """Public (or unlisted) hosts still go to yt-dlp, whose generic extractor
    stays off. The sentinel Popen proves the branch was taken."""
    monkeypatch.setattr(
        netguard, "configured_private_networks",
        lambda: (ipaddress.ip_network("192.168.77.0/24"),))
    with pytest.raises(AssertionError, match="yt-dlp must not be used"):
        server._download_url("http://127.0.0.1:9/a.wav", str(tmp_path),
                             _limits())


def test_nothing_is_direct_when_no_network_is_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(netguard, "configured_private_networks", lambda: ())
    with pytest.raises(AssertionError, match="yt-dlp must not be used"):
        server._download_url("http://127.0.0.1:9/a.wav", str(tmp_path),
                             _limits())
