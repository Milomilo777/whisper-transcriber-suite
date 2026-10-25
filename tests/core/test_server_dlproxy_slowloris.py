"""Slowloris against the download proxy: an absolute header deadline and a
small budget for connections that have not sent their header yet.

Loopback sockets with ephemeral ports only.
"""
from __future__ import annotations

import socket
import time

import pytest

from core.server import dlproxy
from tests.core.test_server_dlproxy import (  # noqa: F401  (fixtures)
    _auth,
    _status,
    _talk,
    proxy,
)


def _wait_until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _closed(sock: socket.socket, within: float) -> bool:
    sock.settimeout(within)
    try:
        sock.recv(4096)  # EOF or a reply: the server ended the exchange
        return True
    except socket.timeout:
        return False
    except OSError:
        return True


def test_a_dripping_client_is_cut_at_the_absolute_header_deadline(
        proxy, monkeypatch):
    """One byte every 0.2 s, always inside the 15 s per-read timeout: only an
    absolute deadline ends it."""
    monkeypatch.setattr(dlproxy, "_HEADER_DEADLINE_S", 1.0)
    sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    started = time.monotonic()
    payload = b"CONNECT example.com:443 HTTP/1.1" + bytes([13, 10]) + b"X: " + b"a" * 60
    cut = False
    try:
        for ch in payload:
            sock.sendall(bytes([ch]))
            time.sleep(0.2)
    except OSError:
        cut = True
    if not cut:
        cut = _closed(sock, 2.0)
    assert cut
    assert time.monotonic() - started < 6.0  # the payload alone takes 12 s
    sock.close()
    assert _wait_until(lambda: proxy._server.pending_connections() == 0)


def test_drippers_filling_the_budget_do_not_lock_out_a_prompt_client(
        proxy, monkeypatch):
    monkeypatch.setattr(dlproxy, "_MAX_PENDING", 3)
    monkeypatch.setattr(dlproxy, "_OVERFLOW_HEADER_S", 0.5)
    held = []
    try:
        for _ in range(3):
            s = socket.create_connection(("127.0.0.1", proxy.port))
            s.sendall(b"CONNECT exa")  # never finishes
            held.append(s)
        assert _wait_until(lambda: proxy._server.pending_connections() == 3)
        # A real client, header complete at once: served (403 for the
        # internal address proves the proxy answered it).
        reply = _talk(proxy, "CONNECT 169.254.169.254:80 HTTP/1.1")
        assert _status(reply) == 403
        # A further dripper lands in the overflow and is cut quickly.
        extra = socket.create_connection(("127.0.0.1", proxy.port))
        extra.sendall(b"CONNECT exa")
        started = time.monotonic()
        extra.settimeout(3.0)
        try:
            data = extra.recv(4096)
        except OSError:
            data = b""
        assert time.monotonic() - started < 3.0
        assert data == b"" or data.startswith(b"HTTP/1.1 400")
        extra.close()
    finally:
        for s in held:
            s.close()


def test_pending_connections_leave_the_budget_after_their_header(proxy):
    for _ in range(40):  # far more than the budget, one after the other
        assert _status(_talk(proxy, "CONNECT 169.254.169.254:80 HTTP/1.1")) == 403
    assert _wait_until(lambda: proxy._server.pending_connections() == 0)


def test_a_prompt_client_is_served_when_every_slot_holds_a_dripper(
        monkeypatch):
    """All handler slots taken by half-sent headers: the oldest stalled
    pending connection is evicted so a complete request still gets in."""
    monkeypatch.setattr(dlproxy, "_MAX_CONNECTIONS", 4)
    monkeypatch.setattr(dlproxy, "_MAX_PENDING", 4)
    p = dlproxy.DownloadProxy()
    held = []
    try:
        for _ in range(4):
            s = socket.create_connection(("127.0.0.1", p.port))
            s.sendall(b"CONNECT exa")
            held.append(s)
        assert _wait_until(lambda: p._server.pending_connections() == 4)
        reply = _talk(p, "CONNECT 169.254.169.254:80 HTTP/1.1")
        assert _status(reply) == 403
        assert sum(1 for s in held if _closed(s, 0.3)) == 1
    finally:
        for s in held:
            s.close()
        p.close()
