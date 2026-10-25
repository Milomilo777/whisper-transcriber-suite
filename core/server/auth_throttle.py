"""Slow down repeated wrong access passwords per client address.

The access password is the only gate of the local server, and a LAN client can
try passwords as fast as the network allows. :class:`AuthThrottle` counts the
password attempts of each HOST (an IPv4 address, or one IPv6 address). The
first few wrong ones are free (people mistype). After that the host is locked
out for a delay that doubles with every further attempt, up to a ceiling.

Rules that keep the throttle from becoming a weapon:

* One host's wrong passwords never lock another host out. A correct password
  from a host that is not itself locked works, whatever its neighbours did,
  with one exception below.
* An IPv6 attacker owns a whole /64 and can rotate addresses, so every host
  would otherwise get its own free comparisons. Each /64 therefore has a real
  budget of password comparisons per fixed window (``subnet_budget`` per
  ``subnet_window`` seconds). When it is used up, hosts of that /64 are
  refused until the window ends, EXCEPT hosts that gave the right password
  within the last ``trust_s`` seconds (they are not blocked by their subnet's
  pressure). Refused requests are not counted and never extend the window, so
  the attacker cannot keep the pressure up beyond one window per budget.
* Evicting a table entry never helps an attacker: the oldest idle entry whose
  lockout has ended goes first, and the /64 counters are separate from the
  host table.
* When the host table is full of locked hosts, a new host cannot be stored
  (storing it would evict a locked entry, and evicting its own fresh entry
  would let it guess without limit). Such attempts share ONE bounded overflow
  limiter instead (``overflow_budget`` comparisons per ``overflow_window``
  seconds, counted for the whole server). While the table is saturated every
  unstored host's guesses are therefore capped as a group, recently
  authenticated addresses included (their session cookie is the way in).
* A lockout always ends by itself and an idle host is forgotten, so the right
  password is never refused forever.

Admission is atomic: :meth:`admit` checks the lockout AND books the attempt
under one lock, before the password is compared, so N threads guessing at once
get at most ``free_attempts + 1`` comparisons between them, not N.

Memory is bounded (``max_hosts`` / ``max_subnets`` / ``max_trusted``).
Thread-safe; the clock is injectable for tests.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict
from typing import Callable

FREE_ATTEMPTS = 5
SUBNET_BUDGET = 50
SUBNET_WINDOW_S = 600.0
TRUST_S = 1800.0
BASE_DELAY_S = 15.0
MAX_DELAY_S = 900.0
FORGET_AFTER_S = 1800.0
MAX_HOSTS = 2048
MAX_SUBNETS = 1024
MAX_TRUSTED = 2048
OVERFLOW_BUDGET = 30
OVERFLOW_WINDOW_S = 600.0


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
                 subnet_budget: int = SUBNET_BUDGET,
                 subnet_window: float = SUBNET_WINDOW_S,
                 trust_s: float = TRUST_S,
                 base_delay: float = BASE_DELAY_S,
                 max_delay: float = MAX_DELAY_S,
                 forget_after: float = FORGET_AFTER_S,
                 max_hosts: int = MAX_HOSTS,
                 max_subnets: int = MAX_SUBNETS,
                 max_trusted: int = MAX_TRUSTED,
                 overflow_budget: int = OVERFLOW_BUDGET,
                 overflow_window: float = OVERFLOW_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._free = max(0, free_attempts)
        self._budget = max(1, subnet_budget)
        self._window = subnet_window
        self._trust = trust_s
        self._base = base_delay
        self._max = max_delay
        self._forget = forget_after
        self._max_hosts = max(1, max_hosts)
        self._max_subnets = max(1, max_subnets)
        self._max_trusted = max(1, max_trusted)
        self._overflow_budget = max(1, overflow_budget)
        self._overflow_window = overflow_window
        self._clock = clock
        self._lock = threading.Lock()
        # host key -> [attempts booked, locked until, last seen]
        self._hosts: OrderedDict[str, list[float]] = OrderedDict()
        # /64 key -> [comparisons in this window, window start]
        self._subnets: OrderedDict[str, list[float]] = OrderedDict()
        # [comparisons by unstored hosts in this window, window start]
        self._overflow: list[float] = [0.0, float("-inf")]
        # host key -> time of its last right password
        self._trusted: OrderedDict[str, float] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._hosts)

    # --- internals (lock held) -------------------------------------------------

    def _live(self, key: str, now: float) -> list[float] | None:
        entry = self._hosts.get(key)
        if entry is not None and now - entry[2] > self._forget:
            del self._hosts[key]
            return None
        return entry

    def _evict_hosts(self, now: float) -> None:
        while len(self._hosts) > self._max_hosts:
            victim = next((k for k, e in self._hosts.items() if e[1] <= now),
                          None)
            if victim is None:  # every entry is locked out: drop the oldest
                victim = next(iter(self._hosts))
            del self._hosts[victim]

    def _evict_subnets(self, now: float) -> None:
        while len(self._subnets) > self._max_subnets:
            victim = next((k for k, e in self._subnets.items()
                           if now - e[1] >= self._window
                           or e[0] < self._budget), None)
            if victim is None:  # all exhausted: drop the oldest
                victim = next(iter(self._subnets))
            del self._subnets[victim]

    def _saturated(self, key: str, now: float) -> bool:
        """True when ``key`` is new and the table holds only locked hosts."""
        if key in self._hosts or len(self._hosts) < self._max_hosts:
            return False
        return not any(e[1] <= now for e in self._hosts.values())

    def _is_trusted(self, key: str, now: float) -> bool:
        at = self._trusted.get(key)
        if at is None:
            return False
        if now - at > self._trust:
            del self._trusted[key]
            return False
        return True

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
            entry = self._live(key, now)
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
            entry = self._live(key, now)
            if entry is not None:
                remaining = entry[1] - now
                if remaining > 0:
                    return int(remaining) + 1
            else:
                entry = [0.0, 0.0, now]
            if self._saturated(key, now):
                # Not stored: share the bounded overflow limiter instead.
                ovf = self._overflow
                if now - ovf[1] >= self._overflow_window:
                    ovf[0], ovf[1] = 0.0, now
                # Trust belongs to an address, so it does not exempt anyone
                # here: logged-in clients use their session cookie instead.
                if ovf[0] >= self._overflow_budget:
                    return int(ovf[1] + self._overflow_window - now) + 1
                ovf[0] += 1
                return 0
            if sub is not None:
                sub_entry = self._subnets.get(sub)
                if sub_entry is not None and now - sub_entry[1] >= self._window:
                    sub_entry = None  # a new window starts
                if sub_entry is None:
                    sub_entry = [0.0, now]
                trusted = self._is_trusted(key, now)
                if sub_entry[0] >= self._budget and not trusted:
                    # Budget used up: refuse without booking, so the refusal
                    # neither counts nor extends the window.
                    return int(sub_entry[1] + self._window - now) + 1
                sub_entry[0] += 1  # a trusted host is counted, never refused
                self._subnets[sub] = sub_entry
                self._subnets.move_to_end(sub)
                self._evict_subnets(now)
            entry[0] += 1
            entry[2] = now
            over = int(entry[0]) - self._free
            if over > 0:
                entry[1] = now + self._delay(over)
            self._hosts[key] = entry
            self._hosts.move_to_end(key)
            self._evict_hosts(now)
            return 0

    def refund(self, address: str) -> None:
        """The booked attempt was the right password: forget this host's count,
        give its comparison back to its /64 and trust the host for a while."""
        key = host_key(address)
        sub = subnet_key(address)
        now = self._clock()
        with self._lock:
            self._hosts.pop(key, None)
            if sub is not None:
                sub_entry = self._subnets.get(sub)
                if sub_entry is not None and sub_entry[0] > 0:
                    sub_entry[0] -= 1
            self._trusted[key] = now
            self._trusted.move_to_end(key)
            while len(self._trusted) > self._max_trusted:
                self._trusted.popitem(last=False)
