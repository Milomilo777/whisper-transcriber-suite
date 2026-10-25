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
import logging
import mimetypes
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core import offline
from core.server import netguard
from core.server.jobs import DownloadCancelled, DownloadLimits, strip_url_secrets

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
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


class _LanHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_LanHTTPConnection, req)


class _LanHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_LanHTTPSConnection, req)


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTS

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        scheme = urllib.parse.urlsplit(newurl).scheme.lower()
        if scheme not in ("http", "https"):
            raise RuntimeError(
                "the link redirects to an address that is not http(s)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
    """Download ``url`` into ``dest_dir``; return the saved file's path."""
    offline.require_online("downloading this link")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _LanHTTPHandler(), _LanHTTPSHandler(),
        _Redirects())
    request = urllib.request.Request(
        url, headers={"User-Agent": "WhisperTranscriberSuite"})
    max_bytes = limits.max_bytes if limits is not None else 0
    too_big = ("download produced no file: the file is larger than the "
               "server's download limit")
    logger.info("server: downloading %s from the local network",
                strip_url_secrets(url))
    started = time.monotonic()
    part = ""
    try:
        try:
            response = opener.open(request, timeout=_READ_TIMEOUT_S)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"the server answered HTTP {exc.code} for the link") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, netguard.BlockedAddressError):
                raise exc.reason from exc
            raise RuntimeError(
                f"could not fetch the link: {exc.reason}") from exc
        with response:
            declared = response.headers.get("Content-Length", "")
            if max_bytes > 0 and declared.isdigit() and int(declared) > max_bytes:
                raise RuntimeError(too_big)
            name = _file_name(response.geturl(),
                              response.headers.get("Content-Type", ""))
            path = os.path.join(dest_dir, name)
            part = path + ".part"
            total = 0
            with open(part, "wb") as out:
                while True:
                    if limits is not None and limits.cancelled():
                        raise DownloadCancelled()
                    if (limits is not None and limits.timeout_s > 0
                            and time.monotonic() - started > limits.timeout_s):
                        minutes = int(limits.timeout_s // 60)
                        raise TimeoutError(
                            f"the download took longer than {minutes} "
                            "minutes and was stopped")
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes > 0 and total > max_bytes:
                        raise RuntimeError(too_big)
                    out.write(chunk)
        if total == 0:
            raise RuntimeError("download produced no file")
        os.replace(part, path)
        part = ""
        return path
    finally:
        if part:  # an unfinished file of this download only
            try:
                os.remove(part)
            except OSError:
                pass
