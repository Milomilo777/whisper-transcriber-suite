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
import socket
import ssl
import urllib.request
from typing import Any


class BlockedAddressError(OSError):
    """The host resolves to an address the server must not connect to."""


def address_blocked(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address",
                    *, allow_private: bool = True) -> bool:
    """True when ``ip`` is a target the server must not connect to.

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
    if not allow_private and not ip.is_global:
        return True
    return False


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
