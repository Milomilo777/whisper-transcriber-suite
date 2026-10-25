"""Embedded IPv4 addresses in IPv6 translation forms (review round 2, item 1).

Hermetic: pure address logic.
"""
from __future__ import annotations

import ipaddress

import pytest

from core.server import netguard


def _build(prefix: bytes, v4: str, length: int) -> ipaddress.IPv6Address:
    """Place ``v4`` in a 16-byte address by the RFC 6052 layout (the inverse of
    netguard.rfc6052_embedded, written independently from the RFC table)."""
    a = bytearray(16)
    a[:len(prefix)] = prefix
    four = ipaddress.IPv4Address(v4).packed
    if length == 32:
        a[4:8] = four
    elif length == 40:
        a[5:8] = four[:3]
        a[9] = four[3]
    elif length == 48:
        a[6:8] = four[:2]
        a[9:11] = four[2:]
    elif length == 56:
        a[7] = four[0]
        a[9:12] = four[1:]
    elif length == 64:
        a[9:13] = four
    elif length == 96:
        a[12:16] = four
    return ipaddress.IPv6Address(bytes(a))


@pytest.mark.parametrize("length", [32, 40, 48, 56, 64, 96])
@pytest.mark.parametrize("v4", ["169.254.169.254", "127.0.0.1", "93.184.216.34"])
def test_rfc6052_decoding_matches_every_layout(length, v4):
    prefix = bytes([0x20, 0x01, 0x0d, 0xb8, 0x11, 0x22, 0x33, 0x44])[:length // 8]
    ip = _build(prefix, v4, length)
    assert str(netguard.rfc6052_embedded(ip, length)) == v4


def test_rfc6052_rejects_other_lengths():
    with pytest.raises(ValueError):
        netguard.rfc6052_embedded(ipaddress.IPv6Address("2001:db8::1"), 80)


@pytest.mark.parametrize("length,prefix_net", [
    (96, "64:ff9b::"), (48, "64:ff9b:1::"),
])
def test_well_known_prefixes_are_decoded_for_every_embedded_target(
        length, prefix_net):
    base = ipaddress.IPv6Address(prefix_net).packed[:length // 8]
    for v4 in ("169.254.169.254", "127.0.0.1", "10.1.2.3"):
        ip = _build(base, v4, length)
        assert netguard.address_blocked(ip, allow_private=False), (v4, ip)
    # The decoder, not a blanket rule, drives the helper: 93.184.216.34 is
    # fine as an IPv4 address.
    assert not netguard.address_blocked(
        netguard.rfc6052_embedded(_build(base, "93.184.216.34", length), length))


def test_a_listed_network_does_not_hide_an_embedded_metadata_address():
    nets = netguard.parse_private_networks(["fd00:1234::/96"])
    bad = ipaddress.ip_address("fd00:1234::a9fe:a9fe")  # -> 169.254.169.254
    assert netguard.address_blocked(bad, allow_private=False,
                                    allowed_networks=nets)
    assert netguard.address_blocked(
        ipaddress.ip_address("fd00:1234::7f00:1"), allow_private=False,
        allowed_networks=nets)
    # A normal host of the listed network is still allowed.
    assert not netguard.address_blocked(
        ipaddress.ip_address("fd00:1234::5"), allow_private=False,
        allowed_networks=nets)


def test_a_listed_network_may_hold_hosts_whose_last_bits_look_private():
    nets = netguard.parse_private_networks(["fd00:5::/64"])
    assert not netguard.address_blocked(
        ipaddress.ip_address("fd00:5::c0a8:1"), allow_private=False,
        allowed_networks=nets)
    # ...but not when the network is not listed.
    assert netguard.address_blocked(
        ipaddress.ip_address("fd00:6::c0a8:1"), allow_private=False,
        allowed_networks=nets)
