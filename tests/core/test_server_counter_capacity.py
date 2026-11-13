"""Capacity pressure must preserve every available authentication bound."""
import pytest
from core.server.auth_throttle import AuthThrottle


def fill_subnet_table(throttle):
    for number in range(1024):
        assert throttle.admit(f"2001:db8:{number // 200 + 1:x}:{number % 200 + 1:x}::1") == 0
    for number in range(25, 55):
        assert throttle.admit(f"2001:db8:6:{number:x}::1") == 0
    assert len(throttle._subnets) == 1024


@pytest.mark.parametrize("trusted", [False, True])
def test_default_subnet_pressure_does_not_lock_an_unrelated_allocation(trusted):
    now = [1000.0]
    throttle = AuthThrottle(clock=lambda: now[0])
    victim = "2001:db8:7:1::1"
    if trusted:
        assert throttle.admit(victim) == 0
        throttle.refund(victim)
        now[0] += 601
    fill_subnet_table(throttle)
    assert throttle.admit(victim) == 0
    assert throttle._overflow[0] == 0
    assert throttle._prefixes["2001:db8:7::/48"][0] == 1


def test_untracked_subnet_still_books_host_lockout():
    throttle = AuthThrottle(max_subnets=1, clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    victim = "2001:db8:2:1::1"
    assert [throttle.admit(victim) for _ in range(7)] == [0] * 6 + [16]
    assert throttle._hosts[victim][0] == 6
    assert throttle._prefixes["2001:db8:2::/48"][0] == 6
    assert throttle._overflow[0] == 0


def test_known_subnet_bounds_an_untracked_prefix_without_global_overflow():
    throttle = AuthThrottle(max_prefixes=1, subnet_budget=2, overflow_budget=1,
                            clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:2:1::1") == 0
    assert throttle.admit("2001:db8:2:1::2") == 0
    assert throttle.admit("2001:db8:2:1::3") == 601
    assert throttle._overflow[0] == 0
    assert len(throttle._prefixes) == 1


def test_refused_host_does_not_charge_a_known_network_counter():
    throttle = AuthThrottle(max_subnets=1, clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    for _ in range(6):
        assert throttle.admit("2001:db8:2:1::1") == 0
    count = list(throttle._prefixes["2001:db8:2::/48"])
    assert throttle.admit("2001:db8:2:1::1") == 16
    assert throttle._prefixes["2001:db8:2::/48"] == count


def test_tracked_allocation_survives_unrelated_exhausted_overflow():
    throttle = AuthThrottle(max_subnets=1, max_prefixes=2, overflow_budget=1,
                            clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:2:1::1") == 0
    assert throttle.admit("2001:db8:3:1::1") == 0
    assert throttle.admit("2001:db8:3:1::2") == 601
    assert throttle.admit("2001:db8:2:1::2") == 0
    assert throttle._prefixes["2001:db8:2::/48"][0] == 2
    assert throttle._overflow[0] == 1


def test_untracked_network_still_has_the_full_tracked_allocation_bound():
    throttle = AuthThrottle(max_subnets=1, clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert sum(throttle.admit(f"2001:db8:2:{n:x}::1") == 0
               for n in range(1, 251)) == 200
    assert throttle._prefixes["2001:db8:2::/48"][0] == 200
    assert len(throttle._subnets) == 1
    assert throttle._overflow[0] == 0


def test_neither_network_tracked_still_books_host_and_charges_overflow_once():
    throttle = AuthThrottle(max_subnets=1, max_prefixes=1, overflow_budget=10,
                            clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    unknown = "2001:db8:2:1::1"
    assert [throttle.admit(unknown) for _ in range(7)] == [0] * 6 + [16]
    assert throttle._overflow[0] == 6
    assert throttle._hosts[unknown][0] == 6
    assert len(throttle._prefixes) == len(throttle._subnets) == 1


def test_concurrent_untracked_subnet_keeps_atomic_host_budget():
    from concurrent.futures import ThreadPoolExecutor
    throttle = AuthThrottle(max_subnets=1, clock=lambda: 1000.0)
    assert throttle.admit("2001:db8:1:1::1") == 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        waits = list(pool.map(throttle.admit, ["2001:db8:2:1::1"] * 64))
    assert waits.count(0) == 6
    assert throttle._prefixes["2001:db8:2::/48"][0] == 6
    assert len(throttle) == 2
