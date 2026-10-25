"""0.0.0.0/8 and fec0::/10 are refused under every address policy.

Python calls 0.0.0.0/8 "private" and (before 3.13 for some forms) fec0::/10
unremarkable, so the default policy (used by the completion webhook) and an
operator's allowlist used to let them through. Each refusal has a public
control address with the same plumbing.

Hermetic: pure address logic.
"""
from __future__ import annotations

import ipaddress

import pytest

from core.server import netguard

THIS_NET = ["0.0.0.0", "0.0.0.1", "0.1.2.3", "0.255.255.255"]
SITE_LOCAL = ["fec0::1", "fec0:0:0:1::5", "feef::1", "feff:ffff::1"]
PUBLIC = ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"]


def _blocked(text, **kw):
    kw.setdefault("nat64_prefixes", ())
    return netguard.address_blocked(ipaddress.ip_address(text), **kw)


@pytest.mark.parametrize("text", THIS_NET + SITE_LOCAL)
@pytest.mark.parametrize("allow_private", [True, False])
def test_refused_in_every_policy(text, allow_private):
    assert _blocked(text, allow_private=allow_private)


@pytest.mark.parametrize("text,net", [
    ("0.1.2.3", "0.0.0.0/8"), ("fec0::1", "fec0::/10"),
    ("feef::1", "fec0::/10")])
def test_an_allowlist_cannot_admit_them(text, net):
    nets = (ipaddress.ip_network(net),)
    assert _blocked(text, allow_private=False, allowed_networks=nets)


@pytest.mark.parametrize("text", PUBLIC)
@pytest.mark.parametrize("allow_private", [True, False])
def test_public_addresses_stay_allowed(text, allow_private):
    assert not _blocked(text, allow_private=allow_private)


def test_an_allowlist_still_admits_an_ordinary_private_network():
    nets = (ipaddress.ip_network("192.168.1.0/24"),)
    assert not _blocked("192.168.1.20", allow_private=False,
                        allowed_networks=nets)
    assert _blocked("192.168.2.20", allow_private=False, allowed_networks=nets)


def test_the_webhook_default_policy_keeps_lan_receivers():
    assert not _blocked("192.168.1.20")
    assert not _blocked("10.0.0.5")


@pytest.mark.parametrize("text", ["::ffff:0.1.2.3", "64:ff9b::0.1.2.3",
                                  "2002:0001:0203::1"])
def test_this_network_inside_an_ipv6_form_is_refused(text):
    assert _blocked(text)
    assert _blocked(text, allow_private=False)
