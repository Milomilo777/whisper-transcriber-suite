"""Connect-time address checks for connections the SERVER makes itself.

A host name can resolve to a harmless address when the server first checks a
URL and to ``127.0.0.1`` a moment later (DNS rebinding), or to both at once.
So where this process opens the connection itself (the completion webhook,
the download proxy) the address is checked at connect time, on the very
addresses that are then connected to, never on a second lookup.

Refused always: loopback, link-local (including the ``169.254.169.254``
cloud-metadata address), unspecified, multicast and reserved addresses.
Ordinary private LAN ranges (10.x, 172.16-31.x, 192.168.x) are allowed unless
``allow_private`` is False; a LAN webhook receiver or media server is a normal
use of this server.
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
import threading
import time
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class BlockedAddressError(OSError):
    """The host resolves to an address the server must not connect to."""


_NETWORKS_TTL_S = 5.0
_networks_lock = threading.Lock()
_networks_cache: tuple[float, tuple[Any, ...]] = (float("-inf"), ())


def parse_private_networks(values: Any) -> tuple[Any, ...]:
    """The usable networks of a ``server_allowed_private_networks`` value.

    Entries that are not CIDR text are ignored with a warning. Listing a
    loopback or link-local network has no effect: those addresses are refused
    before this list is looked at.
    """
    if not isinstance(values, (list, tuple)):
        return ()
    nets = []
    for value in values:
        try:
            nets.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            logger.warning("server: ignoring %r in "
                           "server_allowed_private_networks (not a CIDR)",
                           value)
    return tuple(nets)


def configured_private_networks() -> tuple[Any, ...]:
    """The private networks the operator allowed for link jobs (config key
    ``server_allowed_private_networks``; empty by default). Re-read at most
    every few seconds."""
    global _networks_cache
    now = time.monotonic()
    with _networks_lock:
        stamp, cached = _networks_cache
        if now - stamp < _NETWORKS_TTL_S:
            return cached
    try:
        from core.config import load_config
        nets = parse_private_networks(
            load_config(fetch_online=False).get(
                "server_allowed_private_networks", []))
    except Exception:  # noqa: BLE001 -- a broken config means "none allowed"
        logger.exception("server: could not read the allowed private networks")
        nets = ()
    with _networks_lock:
        _networks_cache = (now, nets)
    return nets


_NAT64_LENGTHS = (32, 40, 48, 56, 64, 96)
_nat64_cache: tuple[float, tuple[Any, ...]] = (float("-inf"), ())


def parse_nat64_prefixes(values: Any) -> tuple[Any, ...]:
    """The usable prefixes of a ``server_nat64_prefixes`` value: IPv6 CIDRs
    whose length is one RFC 6052 allows (32, 40, 48, 56, 64 or 96). Anything
    else is ignored with a warning."""
    if not isinstance(values, (list, tuple)):
        return ()
    nets = []
    for value in values:
        try:
            net = ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError:
            net = None
        if (not isinstance(net, ipaddress.IPv6Network)
                or net.prefixlen not in _NAT64_LENGTHS):
            logger.warning("server: ignoring %r in server_nat64_prefixes "
                           "(not an IPv6 prefix of length %s)", value,
                           "/".join(map(str, _NAT64_LENGTHS)))
            continue
        nets.append(net)
    return tuple(nets)


def configured_nat64_prefixes() -> tuple[Any, ...]:
    """The NAT64/DNS64 translator prefixes the operator configured (config key
    ``server_nat64_prefixes``; empty by default). Re-read at most every few
    seconds."""
    global _nat64_cache
    now = time.monotonic()
    with _networks_lock:
        stamp, cached = _nat64_cache
        if now - stamp < _NETWORKS_TTL_S:
            return cached
    try:
        from core.config import load_config
        nets = parse_nat64_prefixes(
            load_config(fetch_online=False).get("server_nat64_prefixes", []))
    except Exception:  # noqa: BLE001 -- a broken config means "none"
        logger.exception("server: could not read the NAT64 prefixes")
        nets = ()
    with _networks_lock:
        _nat64_cache = (now, nets)
    return nets


def address_blocked(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address",
                    *, allow_private: bool = True,
                    allowed_networks: Any = None,
                    nat64_prefixes: Any = None) -> bool:
    """True when ``ip`` is a target the server must not connect to.

    With ``allow_private`` False a private-network address is refused unless
    it lies in ``allowed_networks`` (default: the configured
    ``server_allowed_private_networks``). Loopback, link-local (cloud
    metadata), unspecified, multicast and reserved addresses are refused
    whatever that list says.

    An IPv4-mapped IPv6 address (``::ffff:a.b.c.d``) is judged as its IPv4
    address: Python before 3.11.10 / 3.12.4 calls every such address
    "reserved" (it falls in ``::/8``), newer versions look at the IPv4 part.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if (ip.is_loopback or ip.is_link_local or ip.is_unspecified
            or ip.is_multicast or ip.is_reserved):
        return True
    nets = ()
    if not allow_private:
        nets = (configured_private_networks() if allowed_networks is None
                else allowed_networks)
    allowlisted = any(ip.version == net.version and ip in net for net in nets)
    # Embedded IPv4 forms are judged BEFORE the allowlist is looked at: a
    # listed network must not let a translation address through that reaches
    # loopback or the metadata address.
    if isinstance(ip, ipaddress.IPv6Address) and _ipv6_embeds_blocked_ipv4(
            ip, allow_private, allowlisted, nets,
            configured_nat64_prefixes() if nat64_prefixes is None
            else nat64_prefixes):
        return True
    if not allow_private and not ip.is_global:
        return not allowlisted
    return False


_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_USE = ipaddress.ip_network("64:ff9b:1::/48")
_TEREDO = ipaddress.ip_network("2001::/32")


def rfc6052_embedded(ip: ipaddress.IPv6Address,
                     prefix_len: int) -> ipaddress.IPv4Address:
    """The IPv4 address an RFC 6052 translator embeds in ``ip``.

    ``prefix_len`` is the translator prefix length: 32, 40, 48, 56, 64 or 96.
    Bits 64-71 (the "u" octet) are skipped, so for 40 to 64 the IPv4 address is
    split around them.
    """
    b = ip.packed
    layouts = {
        32: b[4:8],
        40: b[5:8] + b[9:10],
        48: b[6:8] + b[9:11],
        56: b[7:8] + b[9:12],
        64: b[9:13],
        96: b[12:16],
    }
    if prefix_len not in layouts:
        raise ValueError(f"not an RFC 6052 prefix length: {prefix_len}")
    return ipaddress.IPv4Address(layouts[prefix_len])


_SHARED_V4 = ipaddress.ip_network("100.64.0.0/10")  # carrier-grade NAT


def _always_blocked_v4(v4: ipaddress.IPv4Address) -> bool:
    return v4.is_loopback or v4.is_link_local


def _ipv6_embeds_blocked_ipv4(ip: ipaddress.IPv6Address,
                              allow_private: bool,
                              allowlisted: bool = False,
                              nets: Any = (),
                              nat64: Any = ()) -> bool:
    """True when an IPv6 address carries a blocked IPv4 address inside it.

    NAT64 gateways (and 6to4) turn an IPv6 destination into an IPv4 one, so
    ``64:ff9b::a9fe:a9fe`` can reach ``169.254.169.254`` although the IPv6
    address itself looks like an ordinary global one. The rule is deliberately
    conservative:

    * The well-known prefixes are decoded exactly (RFC 6052 layouts):
      64:ff9b::/96 and the local-use 64:ff9b:1::/48; the embedded IPv4 address
      gets the full check. 6to4 (2002::/16) is decoded the same way.
    * Teredo (2001::/32) is refused outright.
    * Prefixes in ``server_nat64_prefixes`` (an operator's own translator, any
      RFC 6052 length) are decoded by their layout and the embedded IPv4
      address gets the full policy, whatever IPv6 network is listed.
    * A listed IPv6 network whose length is an RFC 6052 length is also tried as
      a translator layout; its embedded loopback / link-local address is
      refused.
    * Any other address: only the LAST 32 bits are read as IPv4 (the common /96
      case) and refused when they are a loopback, link-local (metadata) or,
      with ``allow_private`` False and the address not in a listed network, a
      private-range or shared (100.64/10) address. The price: a public IPv6
      host whose last 32 bits happen to look like such an address (about 1 in
      100) is refused too. **Residual:** an UNCONFIGURED translator with a /32
      to /64 prefix cannot be recognised; put its prefix in
      ``server_nat64_prefixes``.
    """
    if ip in _TEREDO:
        return True
    for net, length in ((_NAT64_WELL_KNOWN, 96), (_NAT64_LOCAL_USE, 48)):
        if ip in net:
            return address_blocked(
                rfc6052_embedded(ip, length), allow_private=allow_private,
                allowed_networks=nets, nat64_prefixes=())
    sixtofour = ip.sixtofour
    if sixtofour is not None and address_blocked(
            sixtofour, allow_private=allow_private, allowed_networks=nets,
            nat64_prefixes=()):
        return True
    matching = [net for net in nat64 if net.version == 6 and ip in net]
    if matching:
        # The LONGEST matching prefix is the translator that really serves
        # this address; the order of the configured list must not matter.
        net = max(matching, key=lambda n: n.prefixlen)
        # An exact decode of a translator the operator named: the full IPv4
        # policy, applied before any allowlist is consulted.
        return address_blocked(
            rfc6052_embedded(ip, net.prefixlen),
            allow_private=allow_private, allowed_networks=nets,
            nat64_prefixes=())
    for net in nets:
        if (net.version == 6 and ip in net
                and net.prefixlen in _NAT64_LENGTHS
                and _always_blocked_v4(rfc6052_embedded(ip, net.prefixlen))):
            return True
    low = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if _always_blocked_v4(low):
        return True
    if allow_private or allowlisted:
        return False
    return ((low.is_private or low in _SHARED_V4)
            and not low.is_unspecified and int(low) >> 24 != 0)


def resolve_checked(host: str, port: int, *, allow_private: bool = True
                    ) -> list[tuple[int, int, int, str, Any]]:
    """Resolve ``host`` once; refuse it when ANY answer is a blocked address.

    Returns the ``getaddrinfo`` tuples to connect to. One bad answer among
    good ones refuses the whole name: a rebinding server answers with both.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        if address_blocked(ip, allow_private=allow_private):
            raise BlockedAddressError(
                f"{host} resolves to {ip}, which the server does not "
                "connect to")
    return list(infos)


def guarded_create_connection(
        address: tuple[str, int], timeout: Any = None,
        source_address: tuple[str, int] | None = None,
        *, allow_private: bool = True) -> socket.socket:
    """``socket.create_connection`` that connects only to checked addresses."""
    host, port = address
    infos = resolve_checked(host.strip("[]"), port, allow_private=allow_private)
    return connect_checked(infos, timeout, source_address, host=host)


def connect_checked(infos: list[tuple[int, int, int, str, Any]],
                    timeout: Any = None,
                    source_address: tuple[str, int] | None = None,
                    *, host: str = "") -> socket.socket:
    """Connect to the first reachable of already checked ``getaddrinfo``
    answers (no second lookup)."""
    last: OSError | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            if isinstance(timeout, (int, float)):  # else: the default
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError(f"could not connect to {host}")


class GuardedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection whose socket goes through the connect-time check."""

    allow_private = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        allow_private = self.allow_private

        def _connect(address: tuple[str, int], timeout: Any = None,
                     source_address: tuple[str, int] | None = None
                     ) -> socket.socket:
            return guarded_create_connection(
                address, timeout, source_address, allow_private=allow_private)

        self._create_connection = _connect  # type: ignore[assignment]


class GuardedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS twin; the certificate is still checked against the host NAME."""

    allow_private = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        allow_private = self.allow_private

        def _connect(address: tuple[str, int], timeout: Any = None,
                     source_address: tuple[str, int] | None = None
                     ) -> socket.socket:
            return guarded_create_connection(
                address, timeout, source_address, allow_private=allow_private)

        self._create_connection = _connect  # type: ignore[assignment]


class GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(GuardedHTTPConnection, req)


class GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self) -> None:
        self._guard_context = ssl.create_default_context()
        super().__init__(context=self._guard_context)

    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(GuardedHTTPSConnection, req,
                            context=self._guard_context)
