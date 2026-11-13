"""Live IPv6 counters survive pressure; overflow requires both tables full."""
from concurrent.futures import ThreadPoolExecutor

from core.server.auth_throttle import AuthThrottle


def test_partial_network_counters_are_not_evicted():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=2)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:1:2::1") == 0
    before = {key: list(row) for key, row in throttle._subnets.items()}
    assert throttle.admit("2001:db8:1:3::1") == 0
    assert dict(throttle._subnets) == before


def test_new_subnet_uses_overflow_when_live_counters_are_exhausted():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=2, max_prefixes=1)
    for subnet in (1, 2):
        for host in range(1, 51):
            assert throttle.admit(f"2001:db8:1:{subnet:x}::{host:x}") == 0
    admitted = sum(throttle.admit(f"2001:db8:2:3::{host:x}") == 0
                   for host in range(1, 101))
    assert admitted == 30  # The existing shared overflow allowance.


def test_unknown_subnets_share_one_overflow_allowance():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1, max_prefixes=1,
                            overflow_budget=3)
    assert throttle.admit("2001:db8:1:1::1") == 0
    admitted = sum(throttle.admit(f"2001:db8:2:{subnet:x}::1") == 0
                   for subnet in range(2, 101))
    assert admitted == 3
    assert set(throttle._subnets) == {"2001:db8:1:1::/64"}


def test_counter_pressure_does_not_reset_a_prior_count():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1)
    for host in range(1, 26):
        assert throttle.admit(f"2001:db8:1:1::{host:x}") == 0
    assert throttle.admit("2001:db8:1:2::1") == 0
    admitted = sum(throttle.admit(f"2001:db8:1:1::{host:x}") == 0
                   for host in range(26, 101))
    assert admitted == 25


def test_ipv4_clients_do_not_need_an_ipv6_network_counter():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1,
                            overflow_budget=1)
    assert throttle.admit("2001:db8:1:1::1") == 0
    for host in range(1, 20):
        assert throttle.admit(f"192.0.2.{host}") == 0
    assert len(throttle._subnets) == 1


def test_only_expired_networks_are_removed_to_make_room():
    clock = [1000.0]
    throttle = AuthThrottle(clock=lambda: clock[0], max_subnets=2)
    assert throttle.admit("2001:db8:1:1::1") == 0
    clock[0] += 100
    assert throttle.admit("2001:db8:1:2::1") == 0
    retained = list(throttle._subnets["2001:db8:1:2::/64"])
    clock[0] += 501
    assert throttle.admit("2001:db8:1:3::1") == 0
    assert set(throttle._subnets) == {"2001:db8:1:2::/64", "2001:db8:1:3::/64"}
    assert throttle._subnets["2001:db8:1:2::/64"] == retained


def test_overflow_refusals_do_not_extend_network_or_overflow_windows():
    clock = [1000.0]
    throttle = AuthThrottle(clock=lambda: clock[0], max_subnets=1, max_prefixes=1,
                            overflow_budget=1)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:2:2::1") == 0
    clock[0] += 300
    for subnet in range(3, 20):
        assert throttle.admit(f"2001:db8:2:{subnet:x}::1") > 0
    assert throttle._subnets["2001:db8:1:1::/64"][1] == 1000
    assert throttle._overflow[1] == 1000
    clock[0] += 301
    assert throttle.admit("2001:db8:2:2::2") == 0
    assert set(throttle._subnets) == {"2001:db8:2:2::/64"}
    assert throttle.admit("2001:db8:3:3::1") == 0
    assert throttle.admit("2001:db8:3:4::1") > 0


def test_tracked_network_keeps_working_when_overflow_is_exhausted():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1, max_prefixes=1,
                            overflow_budget=1)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:2:2::1") == 0
    assert throttle.admit("2001:db8:2:3::1") > 0
    assert throttle.admit("2001:db8:1:1::2") == 0
    assert throttle._subnets["2001:db8:1:1::/64"][0] == 2


def test_concurrent_unknown_networks_share_one_atomic_allowance():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1, max_prefixes=1,
                            overflow_budget=5)
    assert throttle.admit("2001:db8:1:1::1") == 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        waits = list(pool.map(throttle.admit,
                             (f"2001:db8:2:{n:x}::1" for n in range(2, 66))))
    assert waits.count(0) == 5
    assert throttle._subnets == {"2001:db8:1:1::/64": [1, 1000]}
    assert throttle._prefixes["2001:db8:1::/48"][0] == 1
    assert len(throttle) == 6
    assert throttle._overflow[0] == 5


def test_host_and_network_pressure_book_overflow_only_once():
    throttle = AuthThrottle(clock=lambda: 1000.0, max_subnets=1,
                            max_hosts=1, free_attempts=0, overflow_budget=2)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:1:2::1") == 0
    assert throttle.admit("2001:db8:1:3::1") == 0
    assert throttle.admit("2001:db8:1:4::1") > 0
    assert throttle._overflow[0] == 2
    assert throttle._prefixes["2001:db8:1::/48"][0] == 3
