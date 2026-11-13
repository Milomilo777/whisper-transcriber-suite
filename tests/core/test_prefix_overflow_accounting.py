"""A full prefix table must still honor live subnet comparison counters."""
import pytest

from core.server.auth_throttle import AuthThrottle


def staggered_throttle(*, max_prefixes=1, **kwargs):
    clock = [1000.0]
    throttle = AuthThrottle(clock=lambda: clock[0], max_prefixes=max_prefixes, **kwargs)
    assert throttle.admit("2001:db8:1:1::1") == 0
    clock[0] = 1100.0
    return throttle, clock


def replace_expired_prefix(throttle, clock, max_prefixes):
    clock[0] = 1601.0
    for index in range(max_prefixes):
        assert throttle.admit(f"2001:db8:{index + 2:x}:1::1") == 0
    assert "2001:db8:1::/48" not in throttle._prefixes


@pytest.mark.parametrize("capacity", [1, 1024])
def test_live_exhausted_subnet_survives_prefix_table_replacement(capacity):
    throttle, clock = staggered_throttle(max_prefixes=capacity)
    for host in range(1, 51):
        assert throttle.admit(f"2001:db8:1:2::{host:x}") == 0
    replace_expired_prefix(throttle, clock, capacity)
    before = list(throttle._overflow)
    assert throttle.admit("2001:db8:1:2::100") > 0
    assert throttle._subnets["2001:db8:1:2::/64"] == [50, 1100]
    assert throttle._overflow == before, "A known exhausted subnet must not spend overflow capacity"


def test_untracked_prefix_still_charges_known_subnet():
    throttle, clock = staggered_throttle(subnet_budget=2)
    assert throttle.admit("2001:db8:1:2::1") == 0
    replace_expired_prefix(throttle, clock, 1)
    assert throttle.admit("2001:db8:1:2::2") == 0
    assert throttle._subnets["2001:db8:1:2::/64"][0] == 2
    assert throttle.admit("2001:db8:1:2::3") > 0


def test_trusted_host_under_prefix_pressure_is_counted_and_refunded():
    throttle, clock = staggered_throttle(subnet_budget=2)
    trusted = "2001:db8:1:2::1"
    assert throttle.admit(trusted) == 0
    throttle.refund(trusted)
    assert throttle.admit("2001:db8:1:2::2") == 0
    assert throttle.admit("2001:db8:1:2::3") == 0
    replace_expired_prefix(throttle, clock, 1)
    assert throttle.admit(trusted) == 0
    assert throttle._subnets["2001:db8:1:2::/64"][0] == 3
    throttle.refund(trusted)
    assert throttle._subnets["2001:db8:1:2::/64"][0] == 2


def test_overlapping_capacity_limits_charge_overflow_once():
    clock = [1000.0]
    throttle = AuthThrottle(clock=lambda: clock[0], max_hosts=1, max_subnets=1,
                            max_prefixes=1, free_attempts=0, base_delay=600,
                            max_delay=600, overflow_budget=2)
    assert throttle.admit("2001:db8:1:1::1") == 0
    assert throttle.admit("2001:db8:2:1::1") == 0
    assert throttle._overflow[0] == 1
    assert throttle.admit("2001:db8:3:1::1") == 0
    assert throttle._overflow[0] == 2
    assert throttle.admit("2001:db8:4:1::1") > 0
    assert len(throttle._prefixes) == len(throttle._subnets) == len(throttle) == 1


def test_expired_subnet_can_use_shared_allowance_after_prefix_replacement():
    throttle, clock = staggered_throttle(subnet_budget=1)
    assert throttle.admit("2001:db8:1:2::1") == 0
    clock[0] = 1701.0
    assert throttle.admit("2001:db8:2:1::1") == 0
    assert throttle.admit("2001:db8:1:2::2") == 0


def test_host_lockout_survives_its_prefix_expiring():
    throttle, clock = staggered_throttle(free_attempts=0, base_delay=600, max_delay=600)
    host = "2001:db8:1:2::1"
    assert throttle.admit(host) == 0
    replace_expired_prefix(throttle, clock, 1)
    assert throttle.admit(host) > 0
    assert throttle._overflow[0] == 0


def test_available_subnet_counter_limits_repeated_overflow_windows():
    throttle, clock = staggered_throttle(subnet_budget=2, overflow_budget=1, overflow_window=1)
    # Leave the old prefix unallocated while the newer prefix fills its slot.
    replace_expired_prefix(throttle, clock, 1)
    for index in range(2):
        assert throttle.admit(f"2001:db8:1:2::{index + 1:x}") == 0
        clock[0] += 2
    assert throttle.admit("2001:db8:1:2::3") > 0
    assert len(throttle._prefixes) == 1
    assert throttle._subnets["2001:db8:1:2::/64"][0] == 2
