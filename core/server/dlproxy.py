"""A small local proxy that server link jobs download through.

The app cannot hook the requests yt-dlp makes itself, so a server job points
yt-dlp at this proxy (``--proxy``). The proxy resolves every destination
itself, refuses a loopback, link-local (cloud metadata), private, CGNAT,
multicast or otherwise non-public address at connect time, and connects only
to the addresses it checked (see :mod:`core.server.netguard`). Every redirect
yt-dlp follows is a new request through the proxy, so it is checked too.

Supported: ``CONNECT host:port`` (HTTPS) and absolute-form ``http://`` requests
(sent on with ``Connection: close``). Nothing else is relayed. The proxy
listens on 127.0.0.1 only and wants a random per-run password, so another
program on this computer cannot use it as a relay.

Not covered: a program that ignores the proxy setting (yt-dlp hands it to
ffmpeg for external downloads; the server job asks for yt-dlp's own native
downloaders, so ffmpeg only post-processes local files).
"""
from __future__ import annotations

import base64
import binascii
import hmac
import logging
import secrets
import socket
import socketserver
import threading
import urllib.parse
from typing import Any

from core.server.netguard import BlockedAddressError, guarded_create_connection

logger = logging.getLogger(__name__)

_HEADER_TIMEOUT_S = 15.0
_CONNECT_TIMEOUT_S = 15.0
_IDLE_TIMEOUT_S = 120.0
_MAX_HEADER_BYTES = 16 * 1024
_MAX_HEADER_LINES = 100
_MAX_CONNECTIONS = 128
_HOP_BY_HOP = {"proxy-authorization", "proxy-connection", "connection",
               "keep-alive", "te", "trailer", "upgrade"}


def _split_host_port(target: str, default_port: int | None
                     ) -> tuple[str, int] | None:
    """``host:port`` / ``[v6]:port`` into (host, port); None when invalid."""
    target = target.strip()
    if target.startswith("["):
        end = target.find("]")
        if end < 0:
            return None
        host, rest = target[1:end], target[end + 1:]
        port_text = rest[1:] if rest.startswith(":") else ""
    elif target.count(":") == 1:
        host, _, port_text = target.partition(":")
    else:
        host, port_text = target, ""
    try:
        port = int(port_text) if port_text else default_port
    except ValueError:
        return None
    if not host or port is None or not 0 < port < 65536:
        return None
    return host, port


class _Handler(socketserver.StreamRequestHandler):
    server: "_ProxyServer"

    def handle(self) -> None:
        try:
            self.connection.settimeout(_HEADER_TIMEOUT_S)
            self._serve()
        except (OSError, ValueError):
            pass

    # --- helpers -------------------------------------------------------------

    def _reply(self, status: int, text: str) -> None:
        body = (text + "\n").encode("utf-8")
        head = (f"HTTP/1.1 {status} {text}\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n")
        if status == 407:
            head += 'Proxy-Authenticate: Basic realm="wts"\r\n'
        try:
            self.wfile.write(head.encode("ascii") + b"\r\n" + body)
            self.wfile.flush()
        except OSError:
            pass

    def _read_head(self) -> tuple[str, list[tuple[str, str]]] | None:
        line = self.rfile.readline(_MAX_HEADER_BYTES + 1)
        if not line or len(line) > _MAX_HEADER_BYTES:
            return None
        request_line = line.decode("latin-1").strip()
        headers: list[tuple[str, str]] = []
        total = len(line)
        while True:
            raw = self.rfile.readline(_MAX_HEADER_BYTES + 1)
            total += len(raw)
            if (not raw or total > _MAX_HEADER_BYTES
                    or len(headers) > _MAX_HEADER_LINES):
                return None
            text = raw.decode("latin-1").rstrip("\r\n")
            if not text:
                return request_line, headers
            name, sep, value = text.partition(":")
            if not sep:
                return None
            headers.append((name.strip(), value.strip()))

    def _authorised(self, headers: list[tuple[str, str]]) -> bool:
        for name, value in headers:
            if name.lower() != "proxy-authorization":
                continue
            scheme, _, blob = value.partition(" ")
            if scheme.lower() != "basic":
                return False
            try:
                given = base64.b64decode(blob.strip(), validate=True)
            except (binascii.Error, ValueError):
                return False
            return hmac.compare_digest(given, self.server.credentials)
        return False

    def _connect_upstream(self, host: str, port: int) -> socket.socket | None:
        try:
            return guarded_create_connection(
                (host, port), _CONNECT_TIMEOUT_S, allow_private=False)
        except BlockedAddressError:
            logger.warning("server: download proxy refused %s:%d "
                           "(not a public address)", host, port)
            self._reply(403, "address refused: not a public address")
        except (OSError, UnicodeError):
            self._reply(502, "could not connect")
        return None

    # --- request handling -----------------------------------------------------

    def _serve(self) -> None:
        head = self._read_head()
        if head is None:
            self._reply(400, "bad request")
            return
        request_line, headers = head
        parts = request_line.split()
        if len(parts) != 3:
            self._reply(400, "bad request")
            return
        method, target, version = parts
        if not self._authorised(headers):
            self._reply(407, "proxy authentication required")
            return
        if method.upper() == "CONNECT":
            hp = _split_host_port(target, None)
            if hp is None:
                self._reply(400, "bad request")
                return
            upstream = self._connect_upstream(*hp)
            if upstream is None:
                return
            with upstream:
                self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                self.wfile.flush()
                self._relay(upstream)
            return
        split = urllib.parse.urlsplit(target)
        if split.scheme != "http" or not split.hostname:
            self._reply(400, "only CONNECT and http:// requests are relayed")
            return
        hp = _split_host_port(
            split.netloc.rsplit("@", 1)[-1], 80)
        if hp is None:
            self._reply(400, "bad request")
            return
        upstream = self._connect_upstream(*hp)
        if upstream is None:
            return
        with upstream:
            path = urllib.parse.urlunsplit(
                ("", "", split.path or "/", split.query, ""))
            out = [f"{method} {path} {version}"]
            length = 0
            for name, value in headers:
                low = name.lower()
                if low in _HOP_BY_HOP:
                    continue
                if low == "content-length":
                    try:
                        length = max(0, int(value))
                    except ValueError:
                        self._reply(400, "bad request")
                        return
                out.append(f"{name}: {value}")
            out.append("Connection: close")
            upstream.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    return
                upstream.sendall(chunk)
                remaining -= len(chunk)
            self._relay(upstream)

    def _relay(self, upstream: socket.socket) -> None:
        client = self.connection
        client.settimeout(_IDLE_TIMEOUT_S)
        upstream.settimeout(_IDLE_TIMEOUT_S)

        def pump(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        back = threading.Thread(target=pump, args=(upstream, client),
                                daemon=True, name="dlproxy-relay")
        back.start()
        pump(client, upstream)
        back.join(timeout=_IDLE_TIMEOUT_S)


class _ProxyServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, credentials: bytes) -> None:
        self.credentials = credentials
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        super().__init__(("127.0.0.1", 0), _Handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class DownloadProxy:
    """The running proxy: ``url`` is what yt-dlp gets as ``--proxy``."""

    def __init__(self) -> None:
        self._password = secrets.token_urlsafe(24)
        self._server = _ProxyServer(f"wts:{self._password}".encode("ascii"))
        self.port = self._server.server_address[1]
        self.url = f"http://wts:{self._password}@127.0.0.1:{self.port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
            name="dlproxy-serve")
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


_shared: DownloadProxy | None = None
_shared_lock = threading.Lock()


def shared_proxy() -> DownloadProxy:
    """The process-wide proxy, started on first use. Raises OSError if it
    cannot start: a server job then fails instead of running without it."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = DownloadProxy()
        return _shared
