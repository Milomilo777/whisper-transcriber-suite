"""Slow down repeated wrong access passwords per client address.

The access password is the only gate of the local server, and a LAN client can
try passwords as fast as the network allows. :class:`AuthThrottle` counts the
password attempts of each HOST (an IPv4 address, or one IPv6 address). The
first few wrong ones are free (people mistype). After that the host is locked
out for a delay that doubles with every further attempt, up to a ceiling.

Rules that keep the throttle from becoming a weapon:

* One host's wrong passwords never lock another host out. A correct password
  from a host that is not itself locked always works, whatever its
  neighbours did.
* An IPv6 attacker owns a whole /64, so a second, higher budget is kept per
  /64. When a /64 has sent more wrong passwords than that budget, hosts in it
  get no free attempts any more (their first wrong password locks them) until
  the /64 has been quiet for ``forget_after`` seconds. The attacker's own
  attempts cannot extend anyone else's lockout, and the pressure only ends
  sooner when the attacker stops.
* A lockout always ends by itself and an idle host is forgotten, so the right
  password is never refused forever.

Admission is atomic: :meth:`admit` checks the lockout AND books the attempt
under one lock, before the password is compared, so N threads guessing at once
get at most ``free_attempts + 1`` comparisons between them, not N.

Memory is bounded (``max_hosts`` / ``max_subnets``, least recently seen
dropped first). Thread-safe; the clock is injectable for tests.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict
from typing import Callable

FREE_ATTEMPTS = 5
SUBNET_FREE_ATTEMPTS = 50
BASE_DELAY_S = 15.0
MAX_DELAY_S = 900.0
FORGET_AFTER_S = 1800.0
MAX_HOSTS = 2048
MAX_SUBNETS = 1024


def _parse(address: str):
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def host_key(address: str) -> str:
    """The key one host is counted by (IPv4 /32, IPv6 /128)."""
    ip = _parse(address)
    return address if ip is None else str(ip)


def subnet_key(address: str) -> str | None:
    """The IPv6 /64 a host belongs to; None for IPv4 and unparsable input."""
    ip = _parse(address)
    if isinstance(ip, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return None


class AuthThrottle:
    """Per-host count of password attempts with a growing lockout."""

    def __init__(self, *, free_attempts: int = FREE_ATTEMPTS,
                 subnet_free_attempts: int = SUBNET_FREE_ATTEMPTS,
                 base_delay: float = BASE_DELAY_S,
                 max_delay: float = MAX_DELAY_S,
                 forget_after: float = FORGET_AFTER_S,
                 max_hosts: int = MAX_HOSTS,
                 max_subnets: int = MAX_SUBNETS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._free = max(0, free_attempts)
        self._subnet_free = max(0, subnet_free_attempts)
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
        self._max_hosts = max(1, max_hosts)
        self._max_subnets = max(1, max_subnets)
        self._clock = clock
        self._lock = threading.Lock()
        # key -> [attempts booked, locked until, last seen]
        self._hosts: OrderedDict[str, list[float]] = OrderedDict()
        self._subnets: OrderedDict[str, list[float]] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._hosts)

    # --- internals (lock held) -------------------------------------------------

    def _live(self, table: "OrderedDict[str, list[float]]", key: str,
              now: float) -> list[float] | None:
        entry = table.get(key)
        if entry is not None and now - entry[2] > self._forget:
            del table[key]
            return None
        return entry

    @staticmethod
    def _touch(table: "OrderedDict[str, list[float]]", key: str,
               entry: list[float], limit: int) -> None:
        table[key] = entry
        table.move_to_end(key)
        while len(table) > limit:
            table.popitem(last=False)

    def _delay(self, over: int) -> float:
        return min(self._max, self._base * (2 ** min(max(over, 1) - 1, 30)))

    # --- public API --------------------------------------------------------------

    def peek(self, address: str) -> int:
        """Whole seconds this host must still wait; 0 when it may try.

        Read-only: books nothing (used for a request that carries no password).
        """
        key = host_key(address)
        now = self._clock()
        with self._lock:
            entry = self._live(self._hosts, key, now)
            if entry is None:
                return 0
            remaining = entry[1] - now
            return int(remaining) + 1 if remaining > 0 else 0

    def admit(self, address: str) -> int:
        """Admit one password attempt, or say how long to wait.

        Returns 0 and BOOKS the attempt (as wrong, until :meth:`refund` says
        it was right) in one atomic step, or the seconds still to wait.
        """
        key = host_key(address)
        sub = subnet_key(address)
        now = self._clock()
        with self._lock:
            entry = self._live(self._hosts, key, now)
            if entry is not None:
                remaining = entry[1] - now
                if remaining > 0:
                    return int(remaining) + 1
            else:
                entry = [0.0, 0.0, now]
            free = self._free
            sub_entry = None
            if sub is not None:
                sub_entry = self._live(self._subnets, sub, now)
                if sub_entry is None:
                    sub_entry = [0.0, 0.0, now]
                if sub_entry[0] > self._subnet_free:
                    free = 0  # this /64 is under pressure: no free attempts
                sub_entry[0] += 1
                sub_entry[2] = now
                self._touch(self._subnets, sub, sub_entry, self._max_subnets)
            entry[0] += 1
            entry[2] = now
            over = int(entry[0]) - free
            if over > 0:
                entry[1] = now + self._delay(over)
            self._touch(self._hosts, key, entry, self._max_hosts)
            return 0

    def refund(self, address: str) -> None:
        """The booked attempt was the right password: forget this host's count
        and give its attempts back to its /64."""
        key = host_key(address)
        sub = subnet_key(address)
        with self._lock:
            entry = self._hosts.pop(key, None)
            if entry is not None and sub is not None:
                sub_entry = self._subnets.get(sub)
                if sub_entry is not None:
                    sub_entry[0] = max(0.0, sub_entry[0] - entry[0])
                    if sub_entry[0] == 0:
                        del self._subnets[sub]
