"""Sequential, pinned model downloads. Only verified bytes acquire a final name."""
from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from core import model_manager as mm
from core import offline, verified_download as verified

logger = logging.getLogger(__name__)
MANIFEST_PATH = Path(__file__).with_name("model_manifest.json")
DEFAULT_HOSTS = ("https://huggingface.co", "https://hf-mirror.com")
_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")
_COMMIT = re.compile(r"[a-fA-F0-9]{40}\Z")
_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")
_RETRY_DELAYS = (1, 2, 4, 8, 16, 32)
_RATE_WINDOW = 120
_MINIMUM_RATE = 10 * 1024
_FILE_RETRY_TIMEOUT = 30


@dataclass(frozen=True)
class FileInfo:
    size: int
    sha256: str


@dataclass(frozen=True)
class ManifestEntry:
    commit: str
    files: dict[str, FileInfo]
    hosts: tuple[str, ...] = ()


def _host(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        # urlsplit defers checking non-numeric and out-of-range ports until .port.
        _ = parsed.port
    except ValueError:
        raise ValueError("invalid model host") from None
    if not value.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid model host")
    # Plain HTTP is solely for hermetic loopback tests, never a public mirror.
    if (parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname == "127.0.0.1")):
        raise ValueError("invalid model host scheme")
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path.rstrip("/")):
        raise ValueError("invalid model host")
    return value.rstrip("/")


def parse_entry(raw: Any) -> ManifestEntry:
    """Reject the entire entry if any file lacks a pinned size or SHA-256."""
    if not isinstance(raw, dict) or not isinstance(raw.get("commit"), str):
        raise ValueError("missing model commit")
    if not _COMMIT.fullmatch(raw["commit"]):
        raise ValueError("invalid model commit")
    files = raw.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("missing model files")
    parsed: dict[str, FileInfo] = {}
    for name, info in files.items():
        # Runtime model files are flat. Block Windows devices, ADS and traversal too.
        if (not isinstance(name, str) or not re.fullmatch(r"[\w.-]+", name, re.ASCII)
                or name.startswith(".") or name.endswith((".", ".part", ".lock"))
                or name.split(".")[0].upper() in {
                    "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                    *[f"LPT{i}" for i in range(10)]}
                or name.casefold() in {n.casefold() for n in parsed}):
            raise ValueError("invalid model filename")
        if (not isinstance(info, dict) or type(info.get("size")) is not int
                or info["size"] < 0 or not isinstance(info.get("sha256"), str)
                or not _SHA256.fullmatch(info["sha256"])):
            raise ValueError("missing or invalid model file hash/size")
        parsed[name] = FileInfo(info["size"], info["sha256"].lower())
    hosts = raw.get("hosts", [])
    if not isinstance(hosts, list) or any(not isinstance(h, str) for h in hosts):
        raise ValueError("invalid model hosts")
    return ManifestEntry(raw["commit"].lower(), parsed, tuple(_host(h) for h in hosts))


def load_manifest(path: Path | None = None) -> dict[str, ManifestEntry]:
    """Missing/bad manifests fall back to the primary-only legacy downloader."""
    try:
        raw = json.loads((path or MANIFEST_PATH).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("manifest must map repositories to entries")
    except (OSError, ValueError) as exc:
        logger.warning("Model manifest unavailable (%s); using the legacy downloader", type(exc).__name__)
        return {}
    result = {}
    for repo, value in raw.items():
        try:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo, re.ASCII):
                raise ValueError("invalid model repository")
            result[repo] = parse_entry(value)
        except ValueError as exc:
            logger.warning("Invalid model manifest entry (%s); using the legacy downloader", exc)
    return result


def model_complete(folder: Path, entry: ManifestEntry) -> bool:
    """Weights install last; older installs need not match today's file list."""
    if any((folder / (name + ".part")).exists() for name in entry.files):
        return False
    return (mm.model_weights_present(folder)
            or all((folder / name).is_file() for name in entry.files))


class _Cancelled(Exception):
    pass


class _Stalled(TimeoutError):
    pass


class _Retryable(Exception):
    pass


class _HostUnavailable(Exception):
    def __init__(self, message: str, *, reject_bytes: bool = False):
        super().__init__(message)
        self.reject_bytes = reject_bytes


class _RenameBlocked(PermissionError):
    pass


class _ModelRedirects(verified._HttpsOnlyRedirects):
    """Retain urllib's redirect limits without draining an untrusted body."""

    def __init__(self, allow_loopback: bool = False):
        self.allow_loopback = allow_loopback

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        # urllib reads this empty substitute while handling relative URLs,
        # redirect counts and method/header rules. It never reads the socket body.
        return super().http_error_302(req, io.BytesIO(), code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            target = urllib.parse.urlsplit(newurl)
            _host(f"{target.scheme}://{target.netloc}")
            if not (self.allow_loopback and target.hostname == "127.0.0.1"):
                addresses = socket.getaddrinfo(target.hostname, target.port or 443,
                                               type=socket.SOCK_STREAM)
                ips = [ipaddress.ip_address(a[4][0]) for a in addresses]
                if not ips or any(ip.is_loopback or ip.is_link_local or ip.is_unspecified
                                  or ip.is_multicast for ip in ips):
                    raise ValueError("invalid model host")
        except socket.gaierror as exc:
            raise urllib.error.URLError(exc) from exc
        except (ValueError, OSError):
            raise _HostUnavailable("invalid model host") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_cancel(event: threading.Event | None) -> None:
    if event is not None and event.is_set():
        raise _Cancelled


class _MinimumRate:
    """Measure payload across reconnects; allow two minutes to establish a rate."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self.started = clock()
        self.received = 0

    def check(self) -> None:
        now = self.clock()
        elapsed = now - self.started
        if elapsed >= _RATE_WINDOW:
            if self.received < _MINIMUM_RATE * elapsed:
                raise _HostUnavailable("repeated download stalls")
            self.started = now
            self.received = 0


class _SocketReader(io.RawIOBase):
    """Poll recv directly: unlike SocketIO, a timeout does not poison this reader.

    The makefile reference retains the socket after urllib closes its connection.
    HTTPResponse still parses headers, chunk framing and redirects normally.
    """

    def __init__(self, sock: Any, cancel: threading.Event | None,
                 idle_timeout: float, deadline: float | None, rate: _MinimumRate | None = None):
        self.sock = sock
        self.holder = sock.makefile("rb", buffering=0)
        self.cancel = cancel
        self.idle_timeout = idle_timeout
        self.deadline = deadline
        self.rate = rate
        self.last_byte = time.monotonic()
        self.body_started = False
        sock.settimeout(min(0.1, idle_timeout))

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while True:
            _check_cancel(self.cancel)
            if self.rate is not None:
                self.rate.check()
            now = time.monotonic()
            if now - self.last_byte >= self.idle_timeout or (
                    self.deadline is not None and now >= self.deadline):
                raise _Stalled("no bytes received before the download timeout")
            try:
                count = self.sock.recv_into(buffer)
            except socket.timeout:
                continue
            if count and not self.body_started:
                self.last_byte = time.monotonic()
            return count

    def close(self) -> None:
        self.holder.close()
        super().close()


class ModelDownloader:
    """One download's host preferences and probes; no persistent host state."""

    def __init__(self, *, hosts: list[str] | None = None,
                 retry_delays: tuple[float, ...] = _RETRY_DELAYS,
                 stall_timeout: float = 30, probe_timeout: float = 5,
                 max_stalls: int = 3, chunk_size: int = 256 * 1024,
                 allow_loopback_redirects: bool = False):
        self.hosts = [_host(h) for h in (hosts if hosts is not None else DEFAULT_HOSTS)]
        self.retry_delays = retry_delays
        self.stall_timeout = stall_timeout
        self.probe_timeout = min(5, probe_timeout)
        self.max_stalls = max_stalls
        self.chunk_size = chunk_size
        self.allow_loopback_redirects = allow_loopback_redirects
        self._rate_clock: Callable[[], float] = time.monotonic
        self._rate: _MinimumRate | None = None
        self.probed: dict[str, bool] = {}
        self.unavailable: set[str] = set()
        self.tried: list[str] = []
        self.preferred: str | None = None

    def _open(self, url: str, headers: dict[str, str], cancel: threading.Event | None,
              *, probe: bool = False) -> Any:
        timeout = self.probe_timeout if probe else self.stall_timeout
        deadline = time.monotonic() + timeout if probe else None
        rate = None if probe else self._rate

        class Response(http.client.HTTPResponse):
            def __init__(self, sock, *args, **kwargs):
                super().__init__(sock, *args, **kwargs)
                if self.fp is not None:
                    self.fp.close()
                self.download_reader = _SocketReader(sock, cancel, timeout, deadline, rate)
                self.fp = io.BufferedReader(self.download_reader)

        def connection(cls, host, **kwargs):
            conn = cls(host, **kwargs)
            connect = conn.connect

            def connect_or_unavailable():
                try:
                    connect()
                except (OSError, http.client.HTTPException) as exc:
                    # Only connection/TLS setup failures discard this host at once.
                    raise _HostUnavailable(self._cause(exc)) from None

            conn.connect = connect_or_unavailable
            conn.response_class = Response
            return conn

        class HTTP(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(lambda host, **kw: connection(http.client.HTTPConnection, host, **kw), req)

        class HTTPS(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(lambda host, **kw: connection(http.client.HTTPSConnection, host, **kw), req)

        opener = urllib.request.build_opener(HTTP(), HTTPS(), _ModelRedirects(self.allow_loopback_redirects))
        req = urllib.request.Request(url, headers={
            "User-Agent": "WhisperTranscriberSuite", "Accept-Encoding": "identity", **headers,
        }, method="HEAD" if probe else "GET")
        return opener.open(req, timeout=timeout if probe else min(30, self.stall_timeout))

    @staticmethod
    def _url(host: str, repo: str, commit: str, name: str) -> str:
        return f"{host}/{urllib.parse.quote(repo, safe='/')}/resolve/{commit}/{urllib.parse.quote(name)}"

    def _probe(self, host: str, url: str, cancel: threading.Event | None) -> bool:
        if host in self.probed:
            return self.probed[host]
        self.probed[host] = False
        try:
            with self._open(url, {}, cancel, probe=True):
                pass
        except urllib.error.HTTPError as exc:
            exc.close()
            # A failed HEAD only changes priority; GET remains authoritative.
            self.probed[host] = exc.code in (405, 501)
        except (urllib.error.URLError, OSError, http.client.HTTPException, _HostUnavailable):
            pass
        else:
            self.probed[host] = True
        return self.probed[host]

    def _ordered_hosts(self, hosts: list[str], repo: str, commit: str, name: str,
                       cancel: threading.Event | None) -> Iterator[str]:
        deferred = []
        ordered = ([self.preferred] if self.preferred else []) + hosts
        for host in dict.fromkeys(ordered):
            if host in self.unavailable:
                continue
            if self._probe(host, self._url(host, repo, commit, name), cancel):
                yield host
            else:
                deferred.append(host)
        yield from deferred

    @staticmethod
    def _cause(exc: BaseException) -> str:
        if isinstance(exc, urllib.error.URLError):
            exc = exc.reason if isinstance(exc.reason, BaseException) else exc
        return mm.redact_urls(str(exc))[:300] or type(exc).__name__

    @staticmethod
    def _wait(delay: float, cancel: threading.Event | None) -> None:
        if cancel is None:
            time.sleep(delay)
        elif cancel.wait(delay):
            raise _Cancelled

    def _fetch(self, url: str, part: Path, info: FileInfo,
               cancel: threading.Event | None) -> str | None:
        offset = part.stat().st_size if part.exists() else 0
        if offset > info.size:
            self._file_op(part.unlink, cancel)
            offset = 0
        if offset == info.size and part.exists():
            return None
        mm._require_free_space(part.parent, info.size - offset, "the model download")
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with self._open(url, headers, cancel) as response:
            target = part
            status = response.status
            if status == 206:
                match = _RANGE.fullmatch(response.headers.get("Content-Range", ""))
                if not match or tuple(map(int, match.groups())) != (offset, info.size - 1, info.size):
                    raise _HostUnavailable("server returned an incorrect Content-Range", reject_bytes=True)
            elif status == 200:
                if offset:
                    # A host ignoring Range must earn the saved prefix's replacement.
                    target = part.with_name("." + part.name + ".restart")
                    if target.is_symlink():
                        raise mm.ModelDestinationNotWritable(part.parent)
                    mm._require_free_space(part.parent, info.size, "the model download")
                offset = 0
            else:
                raise _HostUnavailable(f"HTTP {status}")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) != info.size - offset):
                raise _HostUnavailable("server returned an incorrect Content-Length", reject_bytes=True)
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise _HostUnavailable("server returned an encoded model file", reject_bytes=True)
            try:
                digest = self._receive(response, target, offset, info, cancel)
                if target != part:
                    if digest != info.sha256:
                        raise _HostUnavailable("download does not match its pinned checksum", reject_bytes=True)
                    self._replace(target, part, cancel)
                return digest
            finally:
                if target != part:
                    self._remove_restart(part)

    def _receive(self, response: Any, target: Path, offset: int, info: FileInfo,
                 cancel: threading.Event | None) -> str | None:
        # Count payload progress, not trickled HTTP chunk headers/keepalives.
        response.download_reader.body_started = True
        response.download_reader.last_byte = time.monotonic()
        digest = hashlib.sha256() if offset == 0 else None
        done = offset
        with self._file_op(lambda: open(target, "ab" if offset else "wb"), cancel) as stream:
            while True:
                _check_cancel(cancel)
                if self._rate is not None and done < info.size:
                    self._rate.check()
                chunk = response.read1(self.chunk_size)
                if not chunk:
                    break
                response.download_reader.last_byte = time.monotonic()
                if done + len(chunk) > info.size:
                    raise _HostUnavailable("server sent more bytes than the pinned size", reject_bytes=True)
                if self._rate is not None:
                    self._rate.received += len(chunk)
                    if done + len(chunk) < info.size:
                        self._rate.check()
                stream.write(chunk)
                if digest is not None:
                    digest.update(chunk)
                done += len(chunk)
                if done == info.size:
                    response.download_reader.rate = None
            stream.flush()
            os.fsync(stream.fileno())
        if done != info.size:
            raise _Retryable(f"download stopped early ({done} of {info.size} bytes)")
        return digest.hexdigest() if digest is not None else None

    def _transfer(self, url: str, part: Path, info: FileInfo,
                  cancel: threading.Event | None) -> str | None:
        retries = iter(self.retry_delays)
        stalls = restarts = failures = 0
        highest = part.stat().st_size if part.exists() else 0
        self._rate = _MinimumRate(self._rate_clock)
        # Adapted from Ollama (https://github.com/ollama/ollama/blob/main/server/download.go) —
        # retained partials, a 30-second idle watchdog, and stalls outside the backoff budget.
        while True:
            _check_cancel(cancel)
            self._rate.check()
            try:
                return self._fetch(url, part, info, cancel)
            except _Stalled:
                stalls += 1
                if stalls >= self.max_stalls:
                    raise _HostUnavailable("repeated download stalls") from None
                continue
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code == 416 and restarts == 0:
                    self._file_op(lambda: part.unlink(missing_ok=True), cancel)
                    restarts += 1
                    continue
                if exc.code < 500 and exc.code not in (408, 429):
                    raise _HostUnavailable(f"HTTP {exc.code}") from None
                cause = f"HTTP {exc.code}"
            except (urllib.error.URLError, ssl.SSLError, ConnectionError, TimeoutError,
                    http.client.HTTPException, _Retryable) as exc:
                cause = self._cause(exc)
            current = part.stat().st_size if part.exists() else 0
            if current > highest:
                highest = current
                failures = 0
                retries = iter(self.retry_delays)
            else:
                failures += 1
            delay = next(retries, None)
            if delay is None:
                raise _HostUnavailable(cause)
            self._wait(delay, cancel)
            if failures >= 6:
                raise _HostUnavailable(cause)

    def _digest(self, path: Path, cancel: threading.Event | None) -> str:
        digest = hashlib.sha256()
        with self._file_op(lambda: path.open("rb"), cancel) as stream:
            while chunk := stream.read(1024 * 1024):
                _check_cancel(cancel)
                digest.update(chunk)
        return digest.hexdigest()

    def _file_op(self, operation: Callable[[], Any], cancel: threading.Event | None,
                 *, rename: bool = False) -> Any:
        deadline = time.monotonic() + _FILE_RETRY_TIMEOUT
        while True:
            _check_cancel(cancel)
            try:
                return operation()
            except PermissionError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if rename:
                        raise _RenameBlocked(str(exc)) from exc
                    raise
                self._wait(min(0.1, remaining), cancel)

    def _replace(self, part: Path, final: Path, cancel: threading.Event | None) -> None:
        self._file_op(lambda: os.replace(part, final), cancel, rename=True)

    def _remove_restart(self, part: Path) -> None:
        side = part.with_name("." + part.name + ".restart")
        # Cleanup must still run when the transfer was cancelled.
        self._file_op(lambda: side.unlink(missing_ok=True), None)

    def download(self, repo: str, folder: Path, entry: ManifestEntry,
                 *, cancel_event: threading.Event | None = None) -> bool:
        """Return False on cancellation; retain saved prefixes, discard rejected bytes."""
        try:
            _check_cancel(cancel_event)
            if model_complete(folder, entry):
                return True
            offline.require_online(f"downloading the model {repo}")
            folder.mkdir(parents=True, exist_ok=True)
            busy = ("This file is already being downloaded (another window of the app?); "
                    "wait for that download to finish.")
            with verified.exclusive_lock(folder / ".model-download.lock", busy):
                return self._download(repo, folder, entry, cancel_event)
        except _Cancelled:
            return False
        except OSError as exc:
            if isinstance(exc, _RenameBlocked) or getattr(exc, "winerror", None) in mm._FILE_IN_USE_WINERRORS:
                raise mm.HuggingFaceDownloadError(
                    "a file in the model folder is in use by another program "
                    "(often an antivirus scan). Wait a moment, then try again. "
                    f"[{type(exc).__name__}: {exc}]") from exc
            if mm._is_permission_error(exc) and not mm._is_disk_full(exc):
                raise mm.ModelDestinationNotWritable(folder) from exc
            raise mm.HuggingFaceDownloadError(mm._describe_download_error(
                exc, folder, self._tried_names())) from exc
        except verified.DownloadError as exc:
            raise mm.HuggingFaceDownloadError(str(exc)) from exc

    def _tried_names(self) -> str:
        return ", ".join(dict.fromkeys(urllib.parse.urlsplit(h).hostname or "" for h in self.tried))

    def _download(self, repo: str, folder: Path, entry: ManifestEntry,
                  cancel: threading.Event | None) -> bool:
        missing = []
        needed = 0
        for name, info in entry.files.items():
            final = folder / name
            part = verified.part_path(final)
            self._remove_restart(part)
            if final.exists():
                if not final.is_file():
                    raise mm.ModelDestinationNotWritable(folder)
                continue
            if part.is_symlink():
                raise mm.ModelDestinationNotWritable(folder)
            have = part.stat().st_size if part.exists() else 0
            needed += info.size - have if have <= info.size else info.size
            missing.append((name, info))
        if not missing:
            return True
        mm._require_free_space(folder, needed, "the model download")
        hosts = list(dict.fromkeys([*self.hosts, *entry.hosts]))
        # The weights go last: a folder holding model.bin counts as installed,
        # so a cut-off download must not leave it there without its small files.
        missing.sort(key=lambda item: (item[0] == "model.bin", item[1].size))
        for name, info in missing:
            _check_cancel(cancel)
            final = folder / name
            part = verified.part_path(final)
            cause = "no download host is available"
            for host in self._ordered_hosts(hosts, repo, entry.commit, name, cancel):
                if host not in self.tried:
                    self.tried.append(host)
                url = self._url(host, repo, entry.commit, name)
                checkpoint = part.stat().st_size if part.exists() else 0
                if checkpoint > info.size:
                    checkpoint = 0
                try:
                    for restart in range(2):
                        digest = self._transfer(url, part, info, cancel)
                        if (part.stat().st_size == info.size
                                and (digest or self._digest(part, cancel)) == info.sha256):
                            break
                        self._file_op(part.unlink, cancel)
                        if digest is not None or restart:
                            raise _HostUnavailable("download does not match its pinned checksum")
                        # A resumed prefix may be stale or damaged; give this host
                        # one clean transfer before attributing bad bytes to it.
                    _check_cancel(cancel)
                    self._replace(part, final, cancel)
                    self._remove_restart(part)
                    self.preferred = host
                    break
                except _HostUnavailable as exc:
                    if exc.reject_bytes and part.exists():
                        if checkpoint:
                            with self._file_op(lambda: part.open("r+b"), cancel) as stream:
                                stream.truncate(min(checkpoint, part.stat().st_size))
                        else:
                            self._file_op(part.unlink, cancel)
                    cause = str(exc)
                    self.unavailable.add(host)
            else:
                raise mm.HuggingFaceDownloadError(f"{cause}. Tried: {self._tried_names()}.")
        _check_cancel(cancel)
        return True
