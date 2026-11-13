"""A routed IPv6 allocation must not multiply the password-guess allowance."""
import threading

from core.server.auth_throttle import AuthThrottle, prefix_key
from tests.core.test_server_auth_throttle import _Clock


def _address(subnet, host=1, allocation="1234"):
    return f"2001:db8:{allocation}:{subnet:x}::{host:x}"


def test_rotating_routed_subnets_shares_a_prefix_budget():
    throttle = AuthThrottle(clock=_Clock())
    admitted = sum(throttle.admit(_address(subnet, host + 1)) == 0
                   for subnet in range(64) for host in range(40))
    assert admitted == 200
    assert throttle.admit(_address(0, allocation="1235")) == 0


def test_prefix_refusals_never_extend_the_fixed_window():
    clock = _Clock()
    throttle = AuthThrottle(clock=clock)
    for subnet in range(200):
        assert throttle.admit(_address(subnet)) == 0
    assert throttle.admit(_address(201)) > 0
    clock.now += 300
    for subnet in range(202, 500):
        assert throttle.admit(_address(subnet)) > 0
    clock.now += 301
    assert throttle.admit(_address(501)) == 0


def test_trusted_host_survives_pressure_until_trust_expires():
    clock = _Clock()
    throttle = AuthThrottle(clock=clock, trust_s=300)
    known = _address(600)
    assert throttle.admit(known) == 0
    throttle.refund(known)
    for subnet in range(200):
        assert throttle.admit(_address(subnet)) == 0
    assert throttle.admit(_address(601)) > 0
    assert throttle.admit(known) == 0
    throttle.refund(known)
    clock.now += 301
    assert throttle.admit(known) > 0


def test_host_eviction_does_not_reset_the_prefix_budget():
    throttle = AuthThrottle(clock=_Clock(), max_hosts=4)
    admitted = sum(throttle.admit(_address(subnet)) == 0 for subnet in range(400))
    assert admitted == 200
    assert len(throttle) <= 4


def test_concurrent_subnet_rotation_has_one_atomic_budget():
    throttle = AuthThrottle(clock=_Clock())
    barrier = threading.Barrier(64)
    admitted = []

    def guess(subnet):
        barrier.wait(timeout=5)
        for host in range(5):
            if throttle.admit(_address(subnet, host + 1)) == 0:
                admitted.append(1)

    threads = [threading.Thread(target=guess, args=(n,)) for n in range(64)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(admitted) == 200


def test_prefix_keys_keep_ipv4_and_distinct_allocations_separate():
    assert prefix_key("2001:db8:1234:1::1") == prefix_key("2001:db8:1234:ffff::9")
    assert prefix_key("2001:db8:1234::1") != prefix_key("2001:db8:1235::1")
    assert prefix_key("fe80::1%eth0") == prefix_key("fe80::1")
    for address in ("127.0.0.1", "::ffff:127.0.0.1", "bad-address"):
        assert prefix_key(address) is None


def test_live_prefix_counters_survive_table_churn():
    throttle = AuthThrottle(clock=_Clock(), max_prefixes=2, prefix_budget=2,
                            overflow_budget=3)
    for allocation in ("1234", "1235"):
        for subnet in range(2):
            assert throttle.admit(_address(subnet, allocation=allocation)) == 0
    admitted = sum(throttle.admit(_address(0, allocation=f"{n:x}")) == 0
                   for n in range(0x1236, 0x1300))
    assert admitted == 3
    assert len(throttle._prefixes) == 2
    assert throttle.admit(_address(10)) > 0
    assert throttle.admit(_address(10, allocation="1235")) > 0


def test_expired_prefixes_make_room_and_overflow_window_ends():
    clock = _Clock()
    throttle = AuthThrottle(clock=clock, max_prefixes=1, prefix_budget=1,
                            overflow_budget=1)
    assert throttle.admit(_address(0)) == 0
    assert throttle.admit(_address(0, allocation="1235")) == 0
    assert throttle.admit(_address(1, allocation="1235")) > 0
    clock.now += 601
    assert throttle.admit(_address(0, allocation="1236")) == 0
    assert list(throttle._prefixes) == [prefix_key(_address(0, allocation="1236"))]
    assert throttle.admit(_address(0, allocation="1237")) == 0
    assert throttle.admit(_address(1, allocation="1237")) > 0


def test_subnet_refusals_do_not_spend_the_prefix_budget():
    throttle = AuthThrottle(clock=_Clock(), subnet_budget=1, prefix_budget=2)
    assert throttle.admit(_address(0)) == 0
    for host in range(2, 20):
        assert throttle.admit(_address(0, host)) > 0
    assert throttle.admit(_address(1)) == 0
    assert throttle.admit(_address(2)) > 0
    assert throttle._prefixes[prefix_key(_address(0))][0] == 2


def test_success_refunds_both_subnet_and_prefix_allowances():
    throttle = AuthThrottle(clock=_Clock(), prefix_budget=2)
    assert throttle.admit(_address(0)) == 0
    throttle.refund(_address(0))
    assert throttle._prefixes[prefix_key(_address(0))][0] == 0
    assert throttle.admit(_address(1)) == 0
    assert throttle.admit(_address(2)) == 0
    assert throttle.admit(_address(3)) > 0


def test_host_saturation_and_prefix_saturation_share_one_overflow():
    throttle = AuthThrottle(clock=_Clock(), max_hosts=1, max_prefixes=1,
                            free_attempts=0, overflow_budget=2)
    assert throttle.admit(_address(0)) == 0  # fills and locks the host table
    assert throttle.admit("192.0.2.1") == 0  # host saturation consumes one
    assert throttle.admit(_address(0, allocation="1235")) == 0
    assert throttle.admit(_address(1, allocation="1235")) > 0
    assert throttle.admit("192.0.2.2") > 0


def test_host_saturation_cannot_bypass_an_exhausted_known_prefix():
    throttle = AuthThrottle(clock=_Clock(), max_hosts=1, free_attempts=0,
                            prefix_budget=1)
    assert throttle.admit(_address(0)) == 0
    assert throttle.admit(_address(1)) > 0
    assert throttle._overflow[0] == 0


def test_host_overflow_admissions_still_spend_the_known_prefix_budget():
    throttle = AuthThrottle(clock=_Clock(), max_hosts=1, free_attempts=0,
                            prefix_budget=2)
    assert throttle.admit(_address(0)) == 0
    assert throttle.admit(_address(1)) == 0
    assert throttle.admit(_address(2)) > 0
    assert throttle._prefixes[prefix_key(_address(0))][0] == 2


def test_concurrent_prefix_table_churn_stays_bounded():
    throttle = AuthThrottle(clock=_Clock(), max_prefixes=2, overflow_budget=5)
    barrier = threading.Barrier(24)
    admitted = []

    def guess(allocation):
        barrier.wait(timeout=5)
        if throttle.admit(_address(0, allocation=f"{allocation:x}")) == 0:
            admitted.append(1)

    threads = [threading.Thread(target=guess, args=(n,)) for n in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(throttle._prefixes) == 2
    assert len(admitted) == 7  # two tracked allocations plus shared overflow
