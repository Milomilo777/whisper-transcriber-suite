"""Operator NAT64 prefixes and embedded private/CGNAT IPv4 (review round 3).

Hermetic: pure address logic. The tests drive ``address_blocked`` itself, not
just the decoder, because the decoder alone does not prove the policy runs.
"""
from __future__ import annotations

import ipaddress

import pytest

from core import config as config_mod
from core.server import netguard
from tests.core.test_server_netguard_embedded import _build

LENGTHS = (32, 40, 48, 56, 64, 96)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(netguard, "_networks_cache", (float("-inf"), ()))
    monkeypatch.setattr(netguard, "_nat64_cache", (float("-inf"), ()))


def _prefix(length: int) -> ipaddress.IPv6Network:
    base = bytes([0x20, 0x01, 0x48, 0x60, 0x12, 0x34, 0x56, 0x78, 0, 0, 0, 0,
                  0, 0, 0, 0])
    packed = bytes(base[:length // 8]) + bytes(16 - length // 8)
    return ipaddress.IPv6Network((packed, length))


def test_default_config_key_exists_and_is_empty():
    assert config_mod.DEFAULT_CONFIG["server_nat64_prefixes"] == []


@pytest.mark.parametrize("length", LENGTHS)
@pytest.mark.parametrize("v4", ["169.254.169.254", "127.0.0.1"])
def test_a_configured_prefix_is_decoded_for_every_layout(length, v4):
    net = _prefix(length)
    ip = _build(net.network_address.packed[:length // 8], v4, length)
    assert netguard.address_blocked(ip, nat64_prefixes=(net,))
    assert netguard.address_blocked(ip, allow_private=False,
                                    nat64_prefixes=(net,))


@pytest.mark.parametrize("length", LENGTHS)
def test_a_configured_prefix_applies_the_full_ipv4_policy(length):
    net = _prefix(length)
    pre = net.network_address.packed[:length // 8]
    private = _build(pre, "10.1.2.3", length)
    cgnat = _build(pre, "100.64.0.1", length)
    public = _build(pre, "93.184.216.34", length)
    # Private and shared-address IPv4 are refused when private is not allowed...
    assert netguard.address_blocked(private, allow_private=False,
                                    nat64_prefixes=(net,))
    assert netguard.address_blocked(cgnat, allow_private=False,
                                    nat64_prefixes=(net,))
    # ...allowed when it is, and a public one is allowed.
    assert not netguard.address_blocked(private, allow_private=True,
                                        nat64_prefixes=(net,))
    assert not netguard.address_blocked(public, allow_private=False,
                                        nat64_prefixes=(net,))
    # An operator-listed IPv4 network lets that private IPv4 through.
    allowed = netguard.parse_private_networks(["10.1.2.0/24"])
    assert not netguard.address_blocked(
        private, allow_private=False, allowed_networks=allowed,
        nat64_prefixes=(net,))


def test_the_review_examples_are_refused():
    ip = ipaddress.ip_address
    net56 = ipaddress.ip_network("2001:4860:1234:5600::/56")
    assert netguard.address_blocked(
        ip("2001:4860:1234:56a9:fe:a9fe::"), nat64_prefixes=(net56,))
    # CGNAT behind a /96 translator that is NOT configured: the last-32-bits
    # rule now sees shared address space too.
    assert netguard.address_blocked(ip("2001:4860:64::6440:1"),
                                    allow_private=False)


def test_a_configured_prefix_is_judged_before_an_ipv6_allowlist():
    net = ipaddress.ip_network("fd00:1234::/56")
    allowed = (net,)
    bad = ipaddress.ip_address("fd00:1234:0:a9:fe:a9fe::")
    assert netguard.address_blocked(bad, allow_private=False,
                                    allowed_networks=allowed,
                                    nat64_prefixes=(net,))


def test_a_listed_ipv6_network_decodes_its_own_layout():
    """No NAT64 prefix configured: the listed network's own length is tried as
    a translator layout, so a metadata translation inside it is refused."""
    nets = netguard.parse_private_networks(["fd00:1234::/56"])
    bad = ipaddress.ip_address("fd00:1234:0:a9:fe:a9fe::")
    assert netguard.address_blocked(bad, allow_private=False,
                                    allowed_networks=nets, nat64_prefixes=())
    assert not netguard.address_blocked(
        ipaddress.ip_address("fd00:1234:0:5::7"), allow_private=False,
        allowed_networks=nets, nat64_prefixes=())


@pytest.mark.parametrize("v4", ["100.64.0.1", "10.0.0.1", "192.168.1.1"])
@pytest.mark.parametrize("length,pfx", [(96, "64:ff9b::"), (48, "64:ff9b:1::")])
def test_well_known_prefixes_flag_embedded_private_and_cgnat(v4, length, pfx):
    pre = ipaddress.IPv6Address(pfx).packed[:length // 8]
    ip = _build(pre, v4, length)
    assert netguard.address_blocked(ip, allow_private=False)


def test_parse_nat64_prefixes_keeps_only_valid_rfc6052_prefixes(caplog):
    got = netguard.parse_nat64_prefixes(
        ["2001:db8::/32", "2001:db8:1::/48", "2001:db8::/80", "10.0.0.0/8",
         "nonsense", 5])
    assert [str(n) for n in got] == ["2001:db8::/32", "2001:db8:1::/48"]
    assert netguard.parse_nat64_prefixes("2001:db8::/32") == ()


@pytest.mark.parametrize("order", [0, 1])
def test_the_longest_matching_prefix_wins_whatever_the_order(order):
    wide = ipaddress.ip_network("2001:4860::/32")
    narrow = ipaddress.ip_network("2001:4860:5db8:d822::/96")
    prefixes = (wide, narrow) if order == 0 else (narrow, wide)
    bad = ipaddress.ip_address("2001:4860:5db8:d822::a9fe:a9fe")
    assert netguard.address_blocked(bad, nat64_prefixes=prefixes)
