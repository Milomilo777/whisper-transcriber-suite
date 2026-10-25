"""Slowloris: connections that have not finished their headers have a small
budget of their own (roadmap S1, review finding).

Loopback sockets with ephemeral ports only.
"""
from __future__ import annotations

import socket
import time

from core.server import httpd
from tests.core.test_server_limits import (
    _closed_by_server,
    _read_status,
    _Server,
    _wait_until,
)
from tests.core.test_server_security import _request


def test_a_dripping_client_is_cut_at_the_absolute_header_deadline(
        tmp_path, monkeypatch):
    """One byte at a time, always inside the per-read timeout: the deadline
    counts from the start of the request, not from the last byte."""
    monkeypatch.setattr(httpd, "_HEADER_TOTAL_S", 1.5)
    srv = _Server(tmp_path)
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        started = time.monotonic()
        closed = False
        payload = b"GET /api/health HTTP/1.1" + bytes([13, 10]) + b"X-Slow: " + b"a" * 40
        try:
            for ch in payload:
                s.sendall(bytes([ch]))
                time.sleep(0.2)
        except OSError:
            closed = True
        if not closed:
            closed = _closed_by_server(s, 2.0)
        assert closed
        assert time.monotonic() - started < 5.0  # 40 bytes would take 8 s
        s.close()
        assert _wait_until(lambda: srv.server.active_connections() == 0)
        assert srv.server.pending_connections() == 0
    finally:
        srv.close()


def test_one_address_cannot_hold_more_than_its_pending_budget(tmp_path):
    srv = _Server(tmp_path, max_connections=20, max_pending=20,
                  max_pending_per_host=3)
    held = []
    try:
        for _ in range(3):
            s = socket.create_connection(("127.0.0.1", srv.port))
            s.sendall(b"GET /api/he")  # never finishes its request line
            held.append(s)
        assert _wait_until(lambda: srv.server.pending_connections() == 3)
        extra = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        assert _read_status(extra).startswith(b"HTTP/1.1 503")
        extra.close()
        assert srv.server.pending_connections() == 3
        # Closing one dripper frees budget: a normal request works again.
        held.pop().close()
        assert _wait_until(lambda: srv.server.pending_connections() == 2)
        status, _ = _request(srv, "GET", "/api/health")
        assert status == 200
    finally:
        for s in held:
            s.close()
        srv.close()


def test_pending_connections_leave_the_budget_when_headers_arrive(tmp_path):
    srv = _Server(tmp_path, max_connections=20, max_pending=20,
                  max_pending_per_host=2)
    try:
        for _ in range(10):  # far more than 2, one after the other
            status, _ = _request(srv, "GET", "/api/health")
            assert status == 200
        assert _wait_until(lambda: srv.server.pending_connections() == 0)
    finally:
        srv.close()


def test_full_pending_budget_still_serves_a_prompt_complete_request(tmp_path):
    """Round-2 finding: 48 drippers used to make every other connection a
    503 although handler slots were free."""
    srv = _Server(tmp_path, max_connections=12, max_pending=4,
                  max_pending_per_host=100)
    held = []
    try:
        for _ in range(4):
            s = socket.create_connection(("127.0.0.1", srv.port))
            s.sendall(b"GET /")
            held.append(s)
        assert _wait_until(lambda: srv.server.pending_connections() == 4)
        status, _ = _request(srv, "GET", "/api/health")
        assert status == 200
    finally:
        for s in held:
            s.close()
        srv.close()


def test_a_dripper_in_the_overflow_is_cut_after_a_short_deadline(
        tmp_path, monkeypatch):
    monkeypatch.setattr(httpd, "_OVERFLOW_HEADER_S", 0.5)
    srv = _Server(tmp_path, max_connections=12, max_pending=2,
                  max_pending_per_host=100)
    held = []
    try:
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", srv.port))
            s.sendall(b"GET /")
            held.append(s)
        assert _wait_until(lambda: srv.server.pending_connections() == 2)
        extra = socket.create_connection(("127.0.0.1", srv.port))
        extra.sendall(b"GET /")  # overflow connection that never finishes
        assert _wait_until(lambda: srv.server.pending_connections() == 3)
        started = time.monotonic()
        assert _closed_by_server(extra, 3.0)
        assert time.monotonic() - started < 3.0
        extra.close()
        # The normal pending connections keep their long (15 s) deadline.
        assert _wait_until(lambda: srv.server.pending_connections() == 2)
    finally:
        for s in held:
            s.close()
        srv.close()


def test_a_prompt_client_is_served_when_every_slot_holds_a_dripper(tmp_path):
    """Capacity full of unauthenticated half-sent requests: the oldest stalled
    pending connection is evicted, so a complete request still gets in."""
    # Many addresses are simulated by a per-address budget above the slot count.
    srv = _Server(tmp_path, max_connections=4, max_pending=4,
                  max_pending_per_host=10)
    held = []
    try:
        for _ in range(4):
            s = socket.create_connection(("127.0.0.1", srv.port))
            s.sendall(b"GET /api/he")
            held.append(s)
        assert _wait_until(lambda: srv.server.active_connections() == 4)
        status, _ = _request(srv, "GET", "/api/health")
        assert status == 200
        # The evicted dripper's connection was closed by the server.
        assert _wait_until(lambda: srv.server.active_connections() <= 4)
        assert sum(1 for s in held if _closed_by_server(s, 0.3)) == 1
    finally:
        for s in held:
            s.close()
        srv.close()


HEAD = (b"POST /api/jobs HTTP/1.1" + bytes([13, 10]) + b"Host: x" + bytes([13, 10])
        + b"Content-Length: 10" + bytes([13, 10, 13, 10]))


def test_connections_that_sent_their_header_are_never_evicted(tmp_path):
    srv = _Server(tmp_path, max_connections=3, max_pending=3,
                  max_pending_per_host=10)
    held = []
    try:
        for _ in range(3):
            s = socket.create_connection(("127.0.0.1", srv.port))
            # Header complete, body still to come: not pending any more.
            s.sendall(HEAD)
            held.append(s)
        assert _wait_until(lambda: srv.server.pending_connections() == 0)
        assert _wait_until(lambda: srv.server.active_connections() == 3)
        extra = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        assert _read_status(extra).startswith(b"HTTP/1.1 503")
        extra.close()
        assert srv.server.active_connections() == 3
    finally:
        for s in held:
            s.close()
        srv.close()
