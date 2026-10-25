"""Short-lived signed session cookie for clients that already logged in.

The wrong-password throttle counts per client ADDRESS. Behind a NAT or a
reverse proxy many people share one address, so an attacker's wrong passwords
can lock that address and, by renewing the lockout, keep a legitimate user out.

A client that sent the right password gets a cookie it can present instead of
the password. A valid cookie is checked without touching the throttle, so the
anonymous failure bucket cannot lock out an already authenticated client.

The cookie is ``<expiry>.<signature>``. The signature is an HMAC-SHA256 over the
expiry and a digest of the access password, keyed with a random per-process
key: it dies at its expiry, when the password changes and when the server
restarts. It is not bound to an address (clients roam, and a shared address is
exactly the case this exists for). It grants what the password grants.
"""
from __future__ import annotations

import hashlib
import hmac

COOKIE_NAME = "wts_session"
SESSION_TTL_S = 900.0


def _signature(key: bytes, token: str, expiry: int) -> str:
    material = (f"{expiry}|".encode("ascii")
                + hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest())
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def issue(key: bytes, token: str, *, now: float,
          ttl: float = SESSION_TTL_S) -> str:
    """A cookie value valid for ``ttl`` seconds from ``now``."""
    expiry = int(now + ttl)
    return f"{expiry}.{_signature(key, token, expiry)}"


def remaining(key: bytes, token: str, value: str, *, now: float) -> float:
    """Seconds the cookie stays valid; 0.0 when it is forged or expired."""
    expiry_text, dot, signature = value.partition(".")
    # isascii(): str.isdigit() is also true for superscript and other
    # non-ASCII digits, which int() then rejects with a ValueError.
    if (not dot or not expiry_text.isascii() or not expiry_text.isdigit()
            or len(expiry_text) > 12):
        return 0.0
    expiry = int(expiry_text)
    if expiry <= now:
        return 0.0
    expected = _signature(key, token, expiry)
    if not hmac.compare_digest(expected.encode("ascii"),
                               signature.encode("ascii", "replace")):
        return 0.0
    return float(expiry) - now


def valid(key: bytes, token: str, value: str, *, now: float) -> bool:
    return remaining(key, token, value, now=now) > 0.0


def from_cookie_header(header: str | None) -> str:
    """The session value inside a ``Cookie`` request header ('' if absent)."""
    if not header:
        return ""
    for part in header.split(";"):
        name, eq, value = part.strip().partition("=")
        if eq and name == COOKIE_NAME:
            return value.strip()
    return ""
