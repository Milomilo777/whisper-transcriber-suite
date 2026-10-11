"""Server binding on IPv6 hosts (`serve --host ::1`) and is_safe_url userinfo tricks."""
import socket
import threading
import urllib.request

import pytest

from core.server import _port_is_free, find_available_port, reachable_urls
from core.server.httpd import JobHTTPServer
from core.server.jobs import JobManager, is_safe_url


def _can_bind_ipv6_loopback() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        s.bind(("::1", 0))
        return True
    except OSError:
        return False
    finally:
        s.close()


needs_ipv6 = pytest.mark.skipif(not _can_bind_ipv6_loopback(), reason="no IPv6 loopback on this machine")


@needs_ipv6
def test_find_available_port_on_ipv6_loopback():
    port = find_available_port(0, "::1")
    assert 1 <= port <= 65535
    assert _port_is_free("::1", port) is True


@needs_ipv6
def test_busy_ipv6_port_is_detected_and_skipped():
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        s.bind(("::1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert _port_is_free("::1", port) is False
        new_port = find_available_port(port, "::1")
        assert new_port != port
        assert 1 <= new_port <= 65535
    finally:
        s.close()


@needs_ipv6
def test_job_server_serves_on_ipv6_loopback():
    server = JobHTTPServer(("::1", 0), JobManager(lambda *_a, **_k: None), token="")
    try:
        assert server.address_family == socket.AF_INET6
        assert server.server_address[0] == "::1"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://[::1]:{port}/api/health", timeout=5) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_reachable_urls_brackets_an_ipv6_host():
    assert reachable_urls("::1", 8765) == ["http://[::1]:8765/"]
    assert reachable_urls("192.168.1.7", 8765) == ["http://192.168.1.7:8765/"]


@pytest.mark.parametrize("url", ["http://user:pass@127.0.0.1/", "http://name@127.0.0.1/",
                                 "http://google.com@127.0.0.1/"])
def test_is_safe_url_sees_through_userinfo(url):
    assert not is_safe_url(url)
