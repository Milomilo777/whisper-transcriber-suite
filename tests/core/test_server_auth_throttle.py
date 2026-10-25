"""Wrong access passwords are slowed down per client address (roadmap S1a).

Unit tests drive :class:`AuthThrottle` with a fake clock; the HTTP tests use
a loopback server with ephemeral ports and a throttle that has a fake clock.
"""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from core.server.auth_throttle import AuthThrottle, client_key
from tests.core.test_server_security import _RunningServer, _request


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _throttle(clock: _Clock, **kw) -> AuthThrottle:
    kw.setdefault("free_attempts", 3)
    kw.setdefault("base_delay", 10.0)
    kw.setdefault("max_delay", 80.0)
    kw.setdefault("forget_after", 300.0)
    return AuthThrottle(clock=clock, **kw)


def test_free_attempts_then_growing_lockout():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        assert t.failure("10.0.0.5") == 0
        assert t.retry_after("10.0.0.5") == 0
    assert t.failure("10.0.0.5") == 10
    assert t.retry_after("10.0.0.5") == 11
    clock.now += 11
    assert t.retry_after("10.0.0.5") == 0
    assert t.failure("10.0.0.5") == 20  # doubles
    clock.now += 21
    assert t.failure("10.0.0.5") == 40
    clock.now += 41
    assert t.failure("10.0.0.5") == 80
    clock.now += 81
    assert t.failure("10.0.0.5") == 80  # capped, never longer


def test_lockout_always_ends_and_other_clients_are_untouched():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(10):
        t.failure("10.0.0.5")
    assert t.retry_after("10.0.0.5") > 0
    assert t.retry_after("10.0.0.6") == 0
    clock.now += 81
    assert t.retry_after("10.0.0.5") == 0  # right password may be tried again


def test_success_clears_the_count():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.failure("10.0.0.5")
    t.success("10.0.0.5")
    assert len(t) == 0
    assert t.failure("10.0.0.5") == 0  # free attempts again


def test_idle_client_is_forgotten():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(4):
        t.failure("10.0.0.5")
    clock.now += 301
    assert t.retry_after("10.0.0.5") == 0
    assert t.failure("10.0.0.5") == 0  # the old count is gone


def test_memory_is_bounded():
    clock = _Clock()
    t = _throttle(clock, max_clients=50)
    for n in range(500):
        t.failure(f"10.1.{n // 250}.{n % 250}")
    assert len(t) == 50


def test_ipv6_clients_share_their_64_network():
    assert client_key("2001:db8:1:2:aaaa::1") == client_key("2001:db8:1:2:bbbb::9")
    assert client_key("2001:db8:1:3::1") != client_key("2001:db8:1:2::1")
    assert client_key("::ffff:10.0.0.5") == "10.0.0.5"
    assert client_key("fe80::1%eth0") == client_key("fe80::2")
    assert client_key("not an address") == "not an address"


def test_thread_safe_counting():
    t = AuthThrottle(free_attempts=10_000, max_clients=10)

    def hammer() -> None:
        for _ in range(500):
            t.failure("10.0.0.5")

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # 4000 wrong passwords, all counted: the 4001st is still inside the
    # free allowance, so a lost update would be invisible; check via limit.
    t2 = AuthThrottle(free_attempts=3999, base_delay=5.0, max_clients=10)
    threads = [threading.Thread(target=lambda: [t2.failure("a") for _ in range(500)])
               for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert t2.retry_after("a") > 0  # 4000 > 3999 only if no update was lost


# --- over HTTP -----------------------------------------------------------------

def _get(srv, path, token=None):
    headers = {"X-Auth-Token": token} if token is not None else {}
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Retry-After"), resp.read()
    finally:
        conn.close()


def test_wrong_passwords_lock_out_then_the_lockout_ends(tmp_path):
    clock = _Clock()
    with _RunningServer(tmp_path, token="s3cret") as srv:
        srv.server.auth_throttle = _throttle(clock, free_attempts=2)
        assert _get(srv, "/api/health", "bad1")[0] == 401
        assert _get(srv, "/api/health", "bad2")[0] == 401
        status, retry, body = _get(srv, "/api/health", "bad3")
        assert status == 401  # the 3rd wrong one is allowed through, then locks
        status, retry, body = _get(srv, "/api/health", "bad4")
        assert status == 429
        assert int(retry) >= 1
        assert "too many wrong passwords" in json.loads(body)["error"]
        # The right password is refused while locked, but only for a while.
        assert _get(srv, "/api/health", "s3cret")[0] == 429
        clock.now += 1000
        assert _get(srv, "/api/health", "s3cret")[0] == 200
        # A good login cleared the count: wrong passwords are free again.
        assert _get(srv, "/api/health", "bad")[0] == 401


def test_post_is_throttled_too_and_a_missing_password_is_not_counted(tmp_path):
    clock = _Clock()
    with _RunningServer(tmp_path, token="s3cret") as srv:
        srv.server.auth_throttle = _throttle(clock, free_attempts=1)
        for _ in range(20):  # no password at all: never counted
            assert _request(srv, "POST", "/api/jobs", body=b"{}")[0] == 401
        assert _get(srv, "/api/health", "x")[0] == 401
        assert _get(srv, "/api/health", "y")[0] == 401  # locks now
        status, body = _request(
            srv, "POST", "/api/jobs", body=b"{}",
            headers={"X-Auth-Token": "z", "Content-Type": "application/json"})
        assert status == 429


def test_no_token_configured_means_no_throttling(tmp_path):
    with _RunningServer(tmp_path, token="") as srv:
        for _ in range(30):
            assert _get(srv, "/api/health", "whatever")[0] == 200


@pytest.mark.parametrize("route", ["/v1/models"])
def test_openai_route_reports_429_with_retry_after(tmp_path, route):
    clock = _Clock()
    with _RunningServer(tmp_path, token="s3cret") as srv:
        srv.server.auth_throttle = _throttle(clock, free_attempts=0)
        assert _get(srv, route, "bad")[0] == 401
        status, retry, _body = _get(srv, route, "bad")
        assert status == 429 and int(retry) >= 1
