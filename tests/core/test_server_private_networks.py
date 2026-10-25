"""server_allowed_private_networks: the opt-in list of local networks that
server link jobs may use (default empty; loopback and link-local stay refused).

Hermetic: no real network, the config is faked.
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

from core import config as config_mod
from core.server import jobs as jobs_mod
from core.server import netguard


def _nets(*cidrs: str):
    return netguard.parse_private_networks(list(cidrs))


def _ip(text: str):
    return ipaddress.ip_address(text)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(netguard, "_networks_cache", (float("-inf"), ()))


def test_default_config_key_exists_and_is_empty():
    assert config_mod.DEFAULT_CONFIG["server_allowed_private_networks"] == []


def test_private_addresses_are_refused_by_default():
    for text in ("10.0.0.5", "192.168.1.20", "172.16.0.9", "100.64.0.9"):
        assert netguard.address_blocked(
            _ip(text), allow_private=False, allowed_networks=())


def test_a_listed_network_is_allowed_and_others_are_not():
    nets = _nets("192.168.1.0/24", "fd00:1::/64")
    assert not netguard.address_blocked(
        _ip("192.168.1.20"), allow_private=False, allowed_networks=nets)
    assert netguard.address_blocked(
        _ip("192.168.2.20"), allow_private=False, allowed_networks=nets)
    assert netguard.address_blocked(
        _ip("10.0.0.5"), allow_private=False, allowed_networks=nets)
    assert not netguard.address_blocked(
        _ip("fd00:1::5"), allow_private=False, allowed_networks=nets)
    assert netguard.address_blocked(
        _ip("fd00:2::5"), allow_private=False, allowed_networks=nets)


@pytest.mark.parametrize("listed,addr", [
    ("127.0.0.0/8", "127.0.0.1"),
    ("169.254.0.0/16", "169.254.169.254"),
    ("0.0.0.0/0", "127.0.0.1"),
    ("0.0.0.0/0", "169.254.169.254"),
    ("::/0", "::1"),
    ("::/0", "fe80::1"),
    ("0.0.0.0/0", "0.0.0.0"),
    ("0.0.0.0/0", "224.0.0.1"),
])
def test_loopback_and_link_local_stay_refused_even_if_listed(listed, addr):
    assert netguard.address_blocked(
        _ip(addr), allow_private=False, allowed_networks=_nets(listed))


def test_translation_prefix_to_a_listed_private_range_stays_refused():
    nets = _nets("192.168.1.0/24")
    assert netguard.address_blocked(
        _ip("2001:4860:64::c0a8:114"), allow_private=False,
        allowed_networks=nets)


def test_bad_entries_are_ignored():
    assert _nets("not a network", "", "10.0.0.0/8") == (
        ipaddress.ip_network("10.0.0.0/8"),)
    assert netguard.parse_private_networks("10.0.0.0/8") == ()
    assert netguard.parse_private_networks(None) == ()


def test_the_config_value_reaches_the_check(monkeypatch):
    monkeypatch.setattr(
        config_mod, "load_config",
        lambda **_k: {"server_allowed_private_networks": ["192.168.1.0/24"]})
    assert not netguard.address_blocked(_ip("192.168.1.20"),
                                        allow_private=False)
    assert netguard.address_blocked(_ip("192.168.7.20"), allow_private=False)


def test_a_broken_config_means_none_allowed(monkeypatch):
    def boom(**_k):
        raise OSError("unreadable")

    monkeypatch.setattr(config_mod, "load_config", boom)
    assert netguard.address_blocked(_ip("192.168.1.20"), allow_private=False)


def test_link_job_to_a_listed_lan_host_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_mod, "load_config",
        lambda **_k: {"server_allowed_private_networks": ["192.168.1.0/24"]})
    assert jobs_mod.is_safe_url("http://192.168.1.20/v", allow_private=False)
    assert not jobs_mod.is_safe_url("http://192.168.2.20/v",
                                    allow_private=False)
    assert not jobs_mod.is_safe_url("http://127.0.0.1/v", allow_private=False)
    mgr = jobs_mod.JobManager(lambda *a, **k: None,
                              jobs_root=str(tmp_path / "jobs"),
                              record_history=False)
    assert mgr.submit_url("http://192.168.1.20/v", ["srt"])
    with pytest.raises(ValueError, match="server_allowed_private_networks"):
        mgr.submit_url("http://192.168.2.20/v", ["srt"])


def test_the_proxy_check_honours_the_list(monkeypatch):
    def answers(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 ("192.168.1.20", port))]

    monkeypatch.setattr(socket, "getaddrinfo", answers)
    with pytest.raises(netguard.BlockedAddressError):
        netguard.resolve_checked("nas.example", 80, allow_private=False)
    monkeypatch.setattr(
        config_mod, "load_config",
        lambda **_k: {"server_allowed_private_networks": ["192.168.1.0/24"]})
    monkeypatch.setattr(netguard, "_networks_cache", (float("-inf"), ()))
    assert netguard.resolve_checked("nas.example", 80, allow_private=False)
