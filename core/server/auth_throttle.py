"""Slow down repeated wrong access passwords from one client address.

The access password is the only gate of the local server, and a LAN client can
try passwords as fast as the network allows. :class:`AuthThrottle` counts wrong
passwords per client address. The first few are free (people mistype). After
that the client is locked out for a delay that doubles with every further
wrong password, up to a ceiling. A lockout always ends by itself, and a client
that stops trying is forgotten, so the right password is never refused forever.

Memory is bounded: at most ``max_clients`` addresses are remembered, the least
recently seen one is dropped first. IPv6 clients are keyed by their /64
network, because one machine owns a whole /64 and could otherwise rotate
addresses to dodge the count.

Thread-safe: every method takes one lock. The clock is injectable for tests.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict
from typing import Callable

FREE_ATTEMPTS = 5
BASE_DELAY_S = 15.0
MAX_DELAY_S = 900.0
FORGET_AFTER_S = 1800.0
MAX_CLIENTS = 2048


def client_key(address: str) -> str:
    """Normalise a client address into the key the throttle counts by."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return address
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return str(mapped)
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class AuthThrottle:
    """Per-client count of wrong passwords with a growing lockout."""

    def __init__(self, *, free_attempts: int = FREE_ATTEMPTS,
                 base_delay: float = BASE_DELAY_S,
                 max_delay: float = MAX_DELAY_S,
                 forget_after: float = FORGET_AFTER_S,
                 max_clients: int = MAX_CLIENTS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._free = max(0, free_attempts)
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
        self._max_clients = max(1, max_clients)
        self._clock = clock
        self._lock = threading.Lock()
        # key -> [wrong passwords, locked until, last seen]
        self._clients: OrderedDict[str, list[float]] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._clients)

    def retry_after(self, address: str) -> int:
        """Whole seconds this client must still wait; 0 when it may try."""
        key = client_key(address)
        now = self._clock()
        with self._lock:
            entry = self._clients.get(key)
            if entry is None:
                return 0
            if now - entry[2] > self._forget:
                del self._clients[key]
                return 0
            remaining = entry[1] - now
            return int(remaining) + 1 if remaining > 0 else 0

    def failure(self, address: str) -> int:
        """Record a wrong password; return the lockout it caused (seconds)."""
        key = client_key(address)
        now = self._clock()
        with self._lock:
            entry = self._clients.get(key)
            if entry is None or now - entry[2] > self._forget:
                entry = [0.0, 0.0, now]
            entry[0] += 1
            entry[2] = now
            over = int(entry[0]) - self._free
            delay = 0.0
            if over > 0:
                delay = min(self._max, self._base * (2 ** min(over - 1, 30)))
                entry[1] = now + delay
            self._clients[key] = entry
            self._clients.move_to_end(key)
            while len(self._clients) > self._max_clients:
                self._clients.popitem(last=False)
            return int(delay)

    def success(self, address: str) -> None:
        """The right password was given: forget this client's failures."""
        key = client_key(address)
        with self._lock:
            self._clients.pop(key, None)
