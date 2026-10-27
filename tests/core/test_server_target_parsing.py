"""Parsing of the request TARGET (the request line's path part).

An absolute-form target (``GET http://host/path HTTP/1.1``) is what proxies
send; ``http.server`` hands it to the handler verbatim. A target with
unbalanced IPv6 brackets (``http://[::1``) makes ``urllib.parse.urlsplit``
raise ``ValueError``, and a target with control-free but odd characters must
still be answered, never crash the handler thread and drop the connection
(the client then sees a network error instead of a status code).

Loopback sockets with ephemeral ports only; the transcriber is a fake.
"""
from __future__ import annotations

import pathlib
import socket

import pytest

from tests.core.test_server_security import _RunningServer


def _raw_request(srv, request_line: bytes) -> bytes:
    """Send one raw request; return the reply bytes (b'' if the socket died)."""
    s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    try:
        s.sendall(request_line)
        try:
            return s.recv(4096)
        except OSError:
            return b""
    finally:
        s.close()


@pytest.mark.parametrize(
    "target",
    [
        b"http://[::1",          # unclosed IPv6 bracket
        b"http://foo]bar/x",     # ']' without '['
        b"https://[::1",         # same over https
    ],
)
def test_a_bracket_broken_target_gets_a_404_not_a_dropped_connection(
        tmp_path: pathlib.Path, target: bytes):
    with _RunningServer(tmp_path) as srv:
        reply = _raw_request(
            srv, b"GET " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        assert reply.startswith(b"HTTP/1.1 404"), reply[:120]


def test_a_bracket_broken_post_target_is_answered(tmp_path: pathlib.Path):
    with _RunningServer(tmp_path) as srv:
        reply = _raw_request(
            srv,
            b"POST http://[::1 HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Length: 0\r\n\r\n")
        assert reply.startswith(b"HTTP/1.1 "), reply[:120]
        assert b"404" in reply.split(b"\r\n", 1)[0], reply[:120]


def test_parse_route_maps_a_broken_target_to_unknown():
    from core.server.httpd import parse_route

    for raw in ("http://[::1", "http://foo]bar/x", "https://[::1"):
        assert parse_route("GET", raw).name == "unknown"
