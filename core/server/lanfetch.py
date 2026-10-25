"""Direct media links on an allowlisted local network.

Server link jobs run yt-dlp with its generic extractor off (see
:mod:`core.server`), so a plain media link, for example a file on a NAS, is
refused. When the operator listed the network in
``server_allowed_private_networks``, a link whose host lies entirely inside a
listed network is fetched here instead, by the app's own downloader:

* only ``http`` and ``https``; no proxy from the environment;
* every connection (the first and each redirect hop) goes through the
  connect-time address check of :mod:`core.server.netguard` with private
  addresses NOT generally allowed, so only listed networks and public hosts
  pass and loopback, link-local and metadata addresses never do;
* the size cap, time limit and cancel flag of the job are honoured, and a
  partial file is never left behind.

Hosts outside the listed networks still go to yt-dlp as before.
"""
from __future__ import annotations

import ipaddress
import http.client
import logging
import mimetypes
import os
import re
import select
import socket
import threading
import time
import urllib.parse
from typing import Any

from core import offline
from core.server import dlproxy, netguard
from core.server.jobs import DownloadCancelled, DownloadLimits, strip_url_secrets

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
PORT_REFUSED = "only ports 80 and 443 are allowed for links"
_READ_TIMEOUT_S = 30.0
_CHUNK = 64 * 1024
_UNSAFE_NAME_RE = re.compile(r"[^\w.\- ()]+")


def is_lan_direct_url(url: str) -> bool:
    """True when every address of the link's host lies in a listed network."""
    nets = netguard.configured_private_networks()
    if not nets:
        return False
    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not host:
        return False
    # Same destination ports as the download proxy; another port is never
    # fetched here (and fetch() refuses it again on every hop).
    if port is not None and port not in dlproxy.ALLOWED_PORTS:
        return False
    try:
        addresses = [ipaddress.ip_address(host.split("%", 1)[0])]
    except ValueError:
        try:
            infos = socket.getaddrinfo(
                host, port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(str(i[4][0]).split("%", 1)[0])
                         for i in infos]
        except (OSError, ValueError):
            return False
    if not addresses:
        return False
    return all(any(a.version == n.version and a in n for n in nets)
               for a in addresses)


class _LanHTTPConnection(netguard.GuardedHTTPConnection):
    allow_private = False


class _LanHTTPSConnection(netguard.GuardedHTTPSConnection):
    allow_private = False


class _Watchdog(threading.Thread):
    """Enforces the job's deadline and cancel flag during EVERY blocking
    network call (connect aside): when either trips, it shuts the current
    socket down, which wakes the blocked read."""

    def __init__(self, limits: DownloadLimits | None, started: float) -> None:
        super().__init__(name="lanfetch-watchdog", daemon=True)
        self._limits = limits
        self._t0 = started
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self.reason = ""

    def watch(self, sock: socket.socket | None) -> None:
        """Register the socket the next blocking calls use. When the job was
        already stopped (for example during connect, before any socket was
        registered), the socket is shut down at once, so no later read can
        wait on a server that keeps answering."""
        with self._lock:
            self._sock = sock
            if sock is None:
                return
            reason = self.reason or self.poll()
            if reason:
                self.reason = reason
                self._shutdown(sock)

    @staticmethod
    def _shutdown(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def poll(self) -> str:
        limits = self._limits
        if limits is None:
            return ""
        if limits.cancelled():
            return "cancelled"
        if (limits.timeout_s > 0
                and time.monotonic() - self._t0 > limits.timeout_s):
            return "timeout"
        return ""

    def run(self) -> None:
        while not self._stop_event.wait(0.2):
            reason = self.poll()
            if not reason:
                continue
            with self._lock:
                self.reason = reason
                sock = self._sock
                if sock is not None:
                    self._shutdown(sock)
            return

    def stop(self) -> None:
        self._stop_event.set()


def _wait_readable(sock: Any, dog: _Watchdog,
                   limits: DownloadLimits | None) -> None:
    """Wait for the first answer bytes in short slices, so the deadline and
    the cancel flag are honoured while a server stays silent."""
    waited = time.monotonic()
    while True:
        _raise_if_stopped(dog, limits)
        ready, _w, _x = select.select([sock], [], [], 0.25)
        if ready:
            _raise_if_stopped(dog, limits)
            return
        if time.monotonic() - waited > _READ_TIMEOUT_S:
            raise RuntimeError("could not fetch the link: the server did "
                               "not answer in time")


def _raise_if_stopped(dog: _Watchdog, limits: DownloadLimits | None) -> None:
    reason = dog.reason or dog.poll()
    if reason == "cancelled":
        raise DownloadCancelled()
    if reason == "timeout":
        minutes = int((limits.timeout_s if limits else 0) // 60)
        raise TimeoutError(
            f"the download took longer than {minutes} minutes and was stopped")


def _file_name(url: str, content_type: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    name = _UNSAFE_NAME_RE.sub("_", path.rsplit("/", 1)[-1]).strip(" .")[:80]
    if not name:
        name = "download"
    if not os.path.splitext(name)[1]:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if ext:
            name += ext
    return name


def fetch(url: str, dest_dir: str, limits: DownloadLimits | None = None) -> str:
    """Download ``url`` into ``dest_dir``; return the saved file's path.

    Redirects are followed here, one hop at a time, and the body of a redirect
    is never read: the connection is simply dropped. The job's deadline and
    cancel flag are enforced by a watchdog during connect-free waits (headers,
    redirects, every body read); every read also has a stall timeout.
    """
    offline.require_online("downloading this link")
    max_bytes = limits.max_bytes if limits is not None else 0
    too_big = ("download produced no file: the file is larger than the "
               "server's download limit")
    logger.info("server: downloading %s from the local network",
                strip_url_secrets(url))
    started = time.monotonic()
    dog = _Watchdog(limits, started)
    dog.start()
    part = ""
    conn: http.client.HTTPConnection | None = None
    response: http.client.HTTPResponse | None = None
    try:
        current = url
        for _hop in range(_MAX_REDIRECTS + 1):
            _raise_if_stopped(dog, limits)
            parts = urllib.parse.urlsplit(current)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise RuntimeError(
                    "the link redirects to an address that is not http(s)")
            try:
                hop_port = parts.port
            except ValueError:
                hop_port = -1
            # Checked before any connection, with one fixed message, so the
            # error text cannot tell which ports a host listens on.
            if hop_port is not None and hop_port not in dlproxy.ALLOWED_PORTS:
                raise RuntimeError(PORT_REFUSED)
            cls = (_LanHTTPSConnection if parts.scheme == "https"
                   else _LanHTTPConnection)
            conn = cls(parts.hostname, hop_port, timeout=_READ_TIMEOUT_S)
            target = urllib.parse.urlunsplit(
                ("", "", parts.path or "/", parts.query, ""))
            try:
                conn.connect()
                # getresponse() hands the socket to the response and clears
                # conn.sock, so keep our own reference for the watchdog. A
                # stop that came during connect shuts the socket down here.
                dog.watch(conn.sock)
                _raise_if_stopped(dog, limits)
                conn.request("GET", target, headers={
                    "User-Agent": "WhisperTranscriberSuite",
                    "Accept-Encoding": "identity", "Connection": "close"})
                _wait_readable(conn.sock, dog, limits)
                response = conn.getresponse()
            except netguard.BlockedAddressError:
                raise
            except (OSError, http.client.HTTPException) as exc:
                _raise_if_stopped(dog, limits)
                raise RuntimeError(f"could not fetch the link: {exc}") from exc
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                # The redirect body is NOT read. A response detached from the
                # connection (HTTP/1.0, Connection: close) keeps the socket
                # open after conn.close(), so close both explicitly.
                response.close()
                response = None
                conn.close()
                conn = None
                if not location:
                    raise RuntimeError("the link redirects without a target")
                current = urllib.parse.urljoin(current, location)
                continue
            break
        else:
            raise RuntimeError("the link redirects too many times")
        if response.status != 200:
            raise RuntimeError(
                f"the server answered HTTP {response.status} for the link")
        declared = response.getheader("Content-Length", "")
        if max_bytes > 0 and declared.isdigit() and int(declared) > max_bytes:
            raise RuntimeError(too_big)
        name = _file_name(current, response.getheader("Content-Type", ""))
        path = os.path.join(dest_dir, name)
        part = path + ".part"
        total = 0
        with open(part, "wb") as out:
            while True:
                try:
                    chunk = response.read(_CHUNK)
                except (OSError, http.client.HTTPException) as exc:
                    _raise_if_stopped(dog, limits)
                    raise RuntimeError(
                        f"the download was interrupted: {exc}") from exc
                _raise_if_stopped(dog, limits)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes > 0 and total > max_bytes:
                    raise RuntimeError(too_big)
                out.write(chunk)
        if declared.isdigit() and total < int(declared):
            raise RuntimeError("the download ended early")
        if total == 0:
            raise RuntimeError("download produced no file")
        os.replace(part, path)
        part = ""
        return path
    finally:
        dog.stop()
        if response is not None:
            response.close()
        if conn is not None:
            conn.close()
        if part:  # an unfinished file of this download only
            try:
                os.remove(part)
            except OSError:
                pass
