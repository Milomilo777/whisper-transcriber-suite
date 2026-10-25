"""Wrong access passwords are slowed down per host (roadmap S1a).

Unit tests drive :class:`AuthThrottle` with a fake clock; the HTTP tests use
a loopback server with ephemeral ports and a throttle that has a fake clock,
plus one test that guesses from many threads at once.
"""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from core.server.auth_throttle import AuthThrottle, host_key, subnet_key
from tests.core.test_server_security import _RunningServer, _request


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _throttle(clock: _Clock, **kw) -> AuthThrottle:
    kw.setdefault("free_attempts", 3)
    kw.setdefault("subnet_budget", 10)
    kw.setdefault("subnet_window", 600.0)
    kw.setdefault("trust_s", 300.0)
    kw.setdefault("base_delay", 10.0)
    kw.setdefault("max_delay", 80.0)
    kw.setdefault("forget_after", 300.0)
    return AuthThrottle(clock=clock, **kw)


def _lock_after(t: AuthThrottle, clock: _Clock, who: str, n: int) -> list[int]:
    """Make n admitted (wrong) attempts, waiting out each lock; return waits."""
    waits = []
    for _ in range(n):
        wait = t.admit(who)
        while wait:
            clock.now += wait
            wait = t.admit(who)
        waits.append(int(t.peek(who)))
    return waits


def test_free_attempts_then_growing_lockout():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        assert t.admit("10.0.0.5") == 0
        assert t.peek("10.0.0.5") == 0
    assert t.admit("10.0.0.5") == 0  # the 4th is admitted and locks
    assert t.peek("10.0.0.5") == 11
    assert t.admit("10.0.0.5") == 11  # refused while locked, books nothing
    clock.now += 11
    assert t.admit("10.0.0.5") == 0
    assert t.peek("10.0.0.5") == 21  # doubles
    clock.now += 21
    assert t.admit("10.0.0.5") == 0
    assert t.peek("10.0.0.5") == 41
    clock.now += 41
    assert t.admit("10.0.0.5") == 0
    assert t.peek("10.0.0.5") == 81
    clock.now += 81
    assert t.admit("10.0.0.5") == 0
    assert t.peek("10.0.0.5") == 81  # capped, never longer


def test_refused_attempts_do_not_renew_the_lockout():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(4):
        t.admit("10.0.0.5")
    first = t.peek("10.0.0.5")
    for _ in range(100):  # an attacker hammering a locked host
        assert t.admit("10.0.0.5") > 0
    assert t.peek("10.0.0.5") <= first


def test_lockout_ends_and_other_hosts_are_untouched():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(10):
        t.admit("10.0.0.5")
    assert t.peek("10.0.0.5") > 0
    assert t.admit("10.0.0.6") == 0
    assert t.peek("10.0.0.6") == 0
    clock.now += 81
    assert t.peek("10.0.0.5") == 0


def test_refund_clears_the_count():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.admit("10.0.0.5")
    t.admit("10.0.0.5")  # the right password, but it crossed the limit
    t.refund("10.0.0.5")
    assert t.peek("10.0.0.5") == 0
    assert len(t) == 0
    assert t.admit("10.0.0.5") == 0  # free attempts again


def test_idle_host_is_forgotten():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(4):
        t.admit("10.0.0.5")
    clock.now += 301
    assert t.peek("10.0.0.5") == 0
    assert t.admit("10.0.0.5") == 0
    assert t.peek("10.0.0.5") == 0  # the old count is gone


def test_memory_is_bounded():
    clock = _Clock()
    t = _throttle(clock, max_hosts=50, max_subnets=20)
    for n in range(500):
        t.admit(f"10.1.{n // 250}.{n % 250}")
    assert len(t) == 50
    for n in range(500):
        t.admit(f"2001:db8:{n}::1")
    assert len(t) == 50
    assert len(t._subnets) == 20


def test_keys():
    assert host_key("2001:db8:1:2:aaaa::1") != host_key("2001:db8:1:2:bbbb::9")
    assert subnet_key("2001:db8:1:2:aaaa::1") == subnet_key("2001:db8:1:2:bbbb::9")
    assert subnet_key("2001:db8:1:3::1") != subnet_key("2001:db8:1:2::1")
    assert host_key("::ffff:10.0.0.5") == "10.0.0.5"
    assert subnet_key("10.0.0.5") is None
    assert host_key("fe80::1%eth0") == host_key("fe80::1")
    assert host_key("not an address") == "not an address"


def test_rotating_ipv6_hosts_share_one_subnet_budget():
    """The probe: 10,000 guesses from as many addresses of one /64, clock
    frozen. Only the /64's budget of comparisons gets through."""
    clock = _Clock()
    t = _throttle(clock)
    admitted = sum(
        1 for n in range(10_000)
        if t.admit(f"2001:db8:1:2:{n:x}::1") == 0)
    assert admitted == 10  # the subnet budget, not 10,000 free attempts
    # Another /64 is untouched.
    assert t.admit("2001:db8:1:9::1") == 0


def test_the_subnet_window_is_fixed_refusals_do_not_extend_it():
    clock = _Clock()
    t = _throttle(clock)
    for n in range(10):
        assert t.admit(f"2001:db8:1:2:{n:x}::1") == 0
    first = t.admit("2001:db8:1:2:aaaa::1")
    assert 0 < first <= 601
    clock.now += 300
    for n in range(500):  # the attacker keeps hammering
        assert t.admit(f"2001:db8:1:2:{n + 100:x}::1") > 0
    clock.now += 301  # 601 s after the start: the window is over
    assert t.admit("2001:db8:1:2:bbbb::1") == 0


def test_a_recently_authenticated_host_is_not_blocked_by_subnet_pressure():
    clock = _Clock()
    t = _throttle(clock)
    neighbour = "2001:db8:1:2::1"
    assert t.admit(neighbour) == 0
    t.refund(neighbour)  # it logged in with the right password
    for n in range(50):
        t.admit(f"2001:db8:1:2:{n + 100:x}::1")  # the attacker, budget gone
    assert t.admit("2001:db8:1:2:ffff::1") > 0  # a stranger is refused
    assert t.admit(neighbour) == 0              # the known neighbour is not
    t.refund(neighbour)
    clock.now += 301  # trust (300 s) has run out, the window (600 s) has not
    assert t.admit(neighbour) > 0
    clock.now += 300
    assert t.admit(neighbour) == 0


def test_evicting_the_host_table_does_not_free_a_locked_attacker():
    clock = _Clock()
    t = _throttle(clock, max_hosts=20)
    for _ in range(10):
        t.admit("10.9.9.9")
    locked = t.peek("10.9.9.9")
    assert locked > 0
    for n in range(500):  # a flood of other hosts fills the table
        t.admit(f"10.1.{n // 250}.{n % 250}")
    assert len(t) == 20
    assert t.peek("10.9.9.9") > 0  # the lockout survived the evictions
    assert t.admit("10.9.9.9") > 0


def test_subnet_counters_survive_host_table_eviction():
    clock = _Clock()
    t = _throttle(clock, max_hosts=5)
    for n in range(10):
        t.admit(f"2001:db8:1:2:{n:x}::1")
    for n in range(200):
        t.admit(f"10.1.{n // 250}.{n % 250}")  # evicts every IPv6 host entry
    assert t.admit("2001:db8:1:2:ffff::1") > 0  # the /64 budget is still spent


def test_concurrent_guesses_are_admitted_at_most_limit_plus_one():
    t = AuthThrottle(free_attempts=5, base_delay=600.0)
    admitted = []
    barrier = threading.Barrier(40)

    def guess() -> None:
        barrier.wait()
        if t.admit("10.0.0.5") == 0:
            admitted.append(1)

    threads = [threading.Thread(target=guess) for _ in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(admitted) == 6  # 5 free + the one that crosses the limit


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
        assert status == 401  # the 3rd wrong one is compared, then locks
        status, retry, body = _get(srv, "/api/health", "bad4")
        assert status == 429
        assert int(retry) >= 1
        assert "too many wrong passwords" in json.loads(body)["error"]
        # The right password is refused while THIS host is locked.
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


def test_many_concurrent_http_guesses_compare_at_most_limit_plus_one(tmp_path):
    clock = _Clock()
    compared = []
    from core.server import httpd

    real = httpd.token_ok

    def counting(expected, header, query):
        compared.append(1)
        return real(expected, header, query)

    with _RunningServer(tmp_path, token="s3cret") as srv:
        srv.server.auth_throttle = _throttle(clock, free_attempts=5,
                                             base_delay=600.0)
        httpd.token_ok = counting
        try:
            statuses: list[int] = []
            barrier = threading.Barrier(30)

            def guess(n: int) -> None:
                barrier.wait()
                statuses.append(_get(srv, "/api/health", f"guess{n}")[0])

            threads = [threading.Thread(target=guess, args=(n,))
                       for n in range(30)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            httpd.token_ok = real
    assert len(compared) <= 6
    assert statuses.count(401) <= 6 and statuses.count(429) >= 24


def _saturate(t: AuthThrottle, clock: _Clock, hosts: int) -> None:
    """Fill the host table with locked-out hosts (free attempts used up)."""
    for i in range(hosts):
        who = f"10.1.{i // 250}.{i % 250 + 1}"
        for _ in range(8):
            t.admit(who)
    assert len(t) == hosts


def test_a_saturated_table_still_limits_a_fresh_host():
    """Every stored host is locked: a new address must not get unlimited
    guesses because its own accounting is evicted at once."""
    clock = _Clock()
    t = _throttle(clock, max_hosts=20, overflow_budget=10,
                  overflow_window=600.0)
    _saturate(t, clock, 20)
    admitted = sum(1 for _ in range(1000) if t.admit("203.0.113.9") == 0)
    assert admitted <= 10
    # The table stayed bounded.
    assert len(t) <= 20
    # The window ends by itself.
    clock.now += 601
    assert t.admit("203.0.113.9") == 0


def test_a_trusted_host_still_passes_a_saturated_table():
    clock = _Clock()
    t = _throttle(clock, max_hosts=20, overflow_budget=2)
    assert t.admit("198.51.100.7") == 0
    t.refund("198.51.100.7")
    _saturate(t, clock, 20)
    for _ in range(2):
        t.admit("203.0.113.9")
    assert t.admit("203.0.113.9") > 0
    assert t.admit("198.51.100.7") == 0
