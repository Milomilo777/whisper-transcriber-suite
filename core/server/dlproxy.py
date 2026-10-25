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
import urllib.request
from typing import Any

from core.server.netguard import (
    BlockedAddressError,
    connect_checked,
    resolve_checked,
)

logger = logging.getLogger(__name__)

_HEADER_TIMEOUT_S = 15.0
_CONNECT_TIMEOUT_S = 15.0
_IDLE_TIMEOUT_S = 120.0
_MAX_HEADER_BYTES = 16 * 1024
_MAX_HEADER_LINES = 100
_MAX_CONNECTIONS = 128
# Destination ports the proxy connects to. Media sites serve on the standard
# ports; refusing the rest keeps the proxy from probing other services.
ALLOWED_PORTS = frozenset({80, 443})
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


_MAX_REQUEST_BODY = 16 * 1024 * 1024


class _UpstreamProxyError(OSError):
    """The operator's own proxy refused or could not be used."""


def upstream_proxy_for(scheme: str, host: str) -> "urllib.parse.SplitResult | None":
    """The operator's HTTP proxy for a destination, from the environment.

    Reads ``HTTPS_PROXY`` / ``HTTP_PROXY`` / ``ALL_PROXY`` (not the Windows
    registry) and honours ``NO_PROXY``. None means connect directly. Only
    plain ``http://`` proxies are supported; anything else raises
    :class:`_UpstreamProxyError` rather than silently going direct.
    """
    proxies = urllib.request.getproxies_environment()
    url = proxies.get(scheme) or proxies.get("all")
    if not url:
        return None
    if urllib.request.proxy_bypass_environment(  # pyright: ignore[reportAttributeAccessIssue]
            host, proxies):
        return None
    split = urllib.parse.urlsplit(url if "://" in url else "http://" + url)
    if split.scheme != "http" or not split.hostname:
        raise _UpstreamProxyError(
            "only an http:// proxy in HTTP_PROXY / HTTPS_PROXY is supported")
    return split


def _connect_through(proxy: "urllib.parse.SplitResult",
                     infos: list[tuple[int, int, int, str, Any]],
                     port: int) -> socket.socket:
    """Open a tunnel to the CHECKED numeric address through ``proxy``.

    The proxy is asked to ``CONNECT`` to the address this process resolved and
    checked, never to the name, so it cannot be steered to another address by
    a second lookup. The client keeps talking TLS to the real host name
    through the tunnel, so the certificate is still verified against it.
    """
    last: OSError | None = None
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = str(sockaddr[0]).split("%", 1)[0]
        target = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
        sock = socket.create_connection(
            (proxy.hostname or "", proxy.port or 80),
            timeout=_CONNECT_TIMEOUT_S)
        try:
            lines = [f"CONNECT {target} HTTP/1.1", f"Host: {target}"]
            if proxy.username is not None:
                cred = (f"{urllib.parse.unquote(proxy.username)}:"
                        f"{urllib.parse.unquote(proxy.password or '')}")
                lines.append("Proxy-Authorization: Basic "
                             + base64.b64encode(cred.encode()).decode())
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = sock.recv(4096)
                if not chunk or len(head) > _MAX_HEADER_BYTES:
                    raise _UpstreamProxyError("no answer to CONNECT")
                head += chunk
            first = head.split(b"\r\n", 1)[0]
            status = first.split()
            if len(status) < 2 or status[1] != b"200":
                raise _UpstreamProxyError(
                    "CONNECT refused: " + first.decode("latin-1")[:80])
            if head.split(b"\r\n\r\n", 1)[1]:
                raise _UpstreamProxyError("unexpected data after CONNECT")
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or _UpstreamProxyError("could not connect")


def _request_framing(headers: list[tuple[str, str]]) -> "int | str | None":
    """How the request body is framed: a length, ``"chunked"`` or 0 (none).

    None when the framing is conflicting or unsupported: both Content-Length
    and Transfer-Encoding, several different Content-Length values, a
    Transfer-Encoding other than plain ``chunked``, or a bad length. Accepting
    those is how request smuggling starts, so they are refused.
    """
    lengths = {v.strip() for n, v in headers if n.lower() == "content-length"}
    encodings = [v.strip().lower() for n, v in headers
                 if n.lower() == "transfer-encoding"]
    if encodings:
        if lengths or encodings != ["chunked"]:
            return None
        return "chunked"
    if not lengths:
        return 0
    if len(lengths) > 1:
        return None
    value = next(iter(lengths))
    if not value.isascii() or not value.isdigit():
        return None
    return int(value)


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

    def _connect_upstream(self, host: str, port: int,
                          scheme: str = "https") -> socket.socket | None:
        """Resolve and check the destination, then connect to the CHECKED
        address: directly, or through the operator's own HTTP proxy (see
        :func:`upstream_proxy_for`)."""
        if port not in ALLOWED_PORTS:
            logger.warning("server: download proxy refused port %d", port)
            self._reply(403, "port refused: only 80 and 443 are allowed")
            return None
        try:
            infos = resolve_checked(host.strip("[]"), port, allow_private=False)
            via = upstream_proxy_for(scheme, host)
            if via is None:
                return connect_checked(infos, _CONNECT_TIMEOUT_S, host=host)
            return _connect_through(via, infos, port)
        except BlockedAddressError:
            logger.warning("server: download proxy refused %s:%d "
                           "(not a public address)", host, port)
            self._reply(403, "address refused: not a public address")
        except _UpstreamProxyError as exc:
            logger.warning("server: upstream proxy: %s", exc)
            self._reply(502, f"upstream proxy: {exc}")
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
            upstream = self._connect_upstream(*hp, scheme="https")
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
        framing = _request_framing(headers)
        if framing is None:
            self._reply(400, "conflicting or unsupported message framing")
            return
        upstream = self._connect_upstream(*hp, scheme="http")
        if upstream is None:
            return
        with upstream:
            path = urllib.parse.urlunsplit(
                ("", "", split.path or "/", split.query, ""))
            out = [f"{method} {path} {version}"]
            for name, value in headers:
                if name.lower() not in _HOP_BY_HOP:
                    out.append(f"{name}: {value}")
            if framing == "chunked":
                out.append("Transfer-Encoding: chunked")
            out.append("Connection: close")
            upstream.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
            # One framing-aware path: exactly the declared body is forwarded,
            # nothing the client sends after it (no request smuggling).
            if not self._forward_body(upstream, framing):
                return
            self._relay_response(upstream)

    def _forward_body(self, upstream: socket.socket, framing: "int | str"
                      ) -> bool:
        """Copy the request body (Content-Length or chunked); False on error."""
        budget = _MAX_REQUEST_BODY
        try:
            if framing == "chunked":
                return self._copy_chunked(upstream, budget)
            remaining = int(framing)
            if remaining > budget:
                self._reply(413, "request body too large")
                return False
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    return False
                upstream.sendall(chunk)
                remaining -= len(chunk)
            return True
        except ValueError:
            self._reply(400, "bad request body")
            return False

    def _copy_chunked(self, upstream: socket.socket, budget: int) -> bool:
        while True:
            line = self.rfile.readline(1024)
            if not line.endswith(b"\n"):
                raise ValueError("chunk size line")
            size = int(line.split(b";", 1)[0].strip(), 16)
            if size < 0:
                raise ValueError("negative chunk")
            budget -= size
            if budget < 0:
                self._reply(413, "request body too large")
                return False
            upstream.sendall(line)
            if size == 0:
                break
            remaining = size
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    return False
                upstream.sendall(chunk)
                remaining -= len(chunk)
            end = self.rfile.readline(3)
            if end not in (b"\r\n", b"\n"):
                raise ValueError("chunk terminator")
            upstream.sendall(end)
        for _ in range(_MAX_HEADER_LINES):  # trailers, then the blank line
            line = self.rfile.readline(_MAX_HEADER_BYTES + 1)
            if not line or len(line) > _MAX_HEADER_BYTES:
                raise ValueError("trailer")
            upstream.sendall(line)
            if line in (b"\r\n", b"\n"):
                return True
        raise ValueError("too many trailers")

    def _relay_response(self, upstream: socket.socket) -> None:
        """Send the upstream's answer to the client until it closes."""
        upstream.settimeout(_IDLE_TIMEOUT_S)
        try:
            while True:
                data = upstream.recv(65536)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except OSError:
            pass

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
