"""Work offline: one switch that keeps the app off the network.

The switch is ``work_offline`` in ``config.json`` (**File > Work offline**, or
the same checkbox in **Advanced > App behaviour**). It is local only: the online
config can never set it, and while it is on the online config is not fetched.

Every place that can reach the network asks this module first:

* automatic requests (the online config, the update check, usage statistics,
  the launch ping and crash reports, the model check, the automatic yt-dlp
  update, the server's webhook) skip themselves: :func:`is_offline`;
* user actions (a link lookup or download, a model or component download, a
  cloud engine, the remote AI provider, SMTV, the YouTube helper) stop with
  :class:`OfflineModeError` from :func:`require_online`. Its text says what was
  refused and names the switch, so nothing fails silently.

:func:`install_network_guard` is the backstop for third-party code that
downloads by itself (Hugging Face weights, PyTorch Hub checkpoints, Sentry):
while the switch is on it refuses, inside the process that installed it, every
outbound TCP connection, UDP send and host-name lookup that does not stay on
this computer.

While the switch is on, this process also keeps a short Network log
(:func:`activity`): every refused action (:func:`refused`, :func:`require_online`
and the backstop), every automatic request that was skipped (:func:`skipped`)
and every connection allowed because it stays on this computer.
:func:`poll_connections` lists the open connections of this process and its
children, so the app can show what is really open, not only what was asked.

The switch is read from ``config.json`` on each call, so the desktop app, its
worker processes, the CLI and the server follow the same saved choice; the
desktop app also holds it in memory (:func:`set_offline`) from the moment the
user flips it.
"""
from __future__ import annotations

import errno
import ipaddress
import logging
import math
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: The config.json key (default False; in core.config.LOCAL_ONLY_KEYS).
CONFIG_KEY = "work_offline"

#: Where the user turns it off; named in every refusal.
SWITCH_NAME = "File > Work offline"


class OfflineModeError(ConnectionError):
    """A network use was refused because Work offline is on.

    A ``ConnectionError`` (an ``OSError``), so code that already treats "no
    network" as a normal outcome handles this one the same way.
    """


def message(what: str) -> str:
    """The sentence shown when ``what`` (e.g. "downloading this link") is refused."""
    return (
        f"Offline mode is on: {what} needs the internet. "
        f"Turn off {SWITCH_NAME} to allow it."
    )


_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})


def coerce_flag(value: Any, unknown: bool) -> bool:
    """Read an on/off setting; anything that is not clearly on or off is ``unknown``.

    A bool is taken as is, a finite number by its truth and the words
    true/false, yes/no, on/off, 1/0 (any case) by their meaning. The privacy
    switches pass their closed value as ``unknown``, so a hand-edited or
    damaged value never turns the network or usage statistics back on.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, float):
        return value != 0 if math.isfinite(value) else unknown
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return unknown


def flag_from(config: Mapping[str, Any]) -> bool:
    """The switch as ``core.config.load_config`` would read it from ``config``.

    A missing key is the shipped default, off; a value that is neither
    clearly on nor clearly off is on (fail closed, see :func:`coerce_flag`).
    """
    if CONFIG_KEY not in config:
        return False
    return coerce_flag(config.get(CONFIG_KEY), True)


# Set by the desktop app (and tests); None means "read config.json".
_override: bool | None = None
# The last value read from config.json: a transient read failure (the file
# is being replaced by a save on Windows) keeps it instead of switching on
# the network for that one call. Unknown before the first good read, which
# counts as on.
_last_saved = True
# (st_ino, st_size, st_mtime_ns) of the file _last_saved came from: the
# switch is asked on every socket connect, so an unchanged file is not
# parsed again. st_ino changes on every atomic replace. An edit in place
# within one file-time tick can keep the key, so a cached value is also
# trusted for at most _CACHE_SECONDS.
_cache_key: tuple[int, int, int] | None = None
_cache_time = 0.0
_CACHE_SECONDS = 1.5


def set_offline(on: bool | None) -> None:
    """Hold the switch in memory for this process; ``None`` reads config.json again."""
    global _override
    _override = None if on is None else bool(on)


def _saved_flag() -> bool:
    global _last_saved, _cache_key, _cache_time
    import os
    import time

    from core import config as _config

    path = _config.config_path()
    try:
        st = os.stat(path)
        key = (st.st_ino, st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        key = (-1, -1, -1)
    except OSError:
        return _last_saved
    now = time.monotonic()
    if key == _cache_key and now - _cache_time < _CACHE_SECONDS:
        return _last_saved
    data = _config.read_local_config_for_switches()
    if data is None:
        # Unreadable right now (a save is replacing it): keep the last value.
        return _last_saved
    _last_saved = flag_from(data)
    _cache_key = key
    _cache_time = now
    return _last_saved


def is_offline(config: Mapping[str, Any] | None = None) -> bool:
    """True while Work offline is on.

    The in-memory switch wins; otherwise ``config`` (a local config dict the
    caller has just read) or else ``config.json`` decides.
    """
    if _override is not None:
        return _override
    if config is not None:
        return flag_from(config)
    return _saved_flag()


def require_online(what: str) -> None:
    """Raise :class:`OfflineModeError` for ``what`` while Work offline is on."""
    if is_offline():
        raise OfflineModeError(refused(what))


# --- the Network log: what the switch did in this process ------------------

#: Event kinds: a refused action or connection, an automatic request that was
#: not sent, a connection allowed because it stays on this computer, and a
#: Verify offline now probe that was refused (kept out of the refused count).
REFUSED = "refused"
SKIPPED = "skipped"
LOCAL = "local"
TEST = "test"

#: The feature name of the Verify offline now probes.
SELF_TEST_FEATURE = "Verify offline now"

_LOG_SIZE = 500


@dataclass(frozen=True)
class NetEvent:
    """One line of the Network log. ``host`` is empty for a refused action."""

    when: float
    kind: str
    feature: str
    host: str = ""


@dataclass(frozen=True)
class Activity:
    """Counts since ``since`` (a ``time.time()``) and the newest events, oldest first."""

    since: float
    counts: dict[str, int]
    events: tuple[NetEvent, ...]


_log_lock = threading.Lock()
_events: deque[NetEvent] = deque(maxlen=_LOG_SIZE)
# Allowed local connections can be many (a local AI server): their own ring,
# so they never push refusals out of the log.
_local_events: deque[NetEvent] = deque(maxlen=_LOG_SIZE)
_counts = {REFUSED: 0, SKIPPED: 0, LOCAL: 0, TEST: 0}
_since = time.time()
_skipped_once: set[str] = set()
_feature_label = threading.local()

# Modules that only carry a connection for someone else: the Network log
# names the first caller outside them.
_CARRIER_PREFIXES = (
    "core.offline", "socket", "ssl", "http.", "urllib", "requests", "httpx",
    "asyncio", "selectors", "concurrent.", "threading", "contextlib", "functools",
)


def _caller_feature() -> str:
    label = getattr(_feature_label, "name", None)
    if label:
        return str(label)
    first = ""
    frame = sys._getframe(1)
    while frame is not None:
        name = str(frame.f_globals.get("__name__", ""))
        if name.startswith(("app.", "core.")) and not name.startswith("core.offline"):
            return name
        if not first and name and not name.startswith(_CARRIER_PREFIXES):
            first = name
        frame = frame.f_back
    return first or "unknown caller"


def _record(kind: str, feature: str, host: object = "") -> None:
    event = NetEvent(time.time(), kind, feature, _host_text(host) if host else "")
    with _log_lock:
        (_local_events if kind == LOCAL else _events).append(event)
        _counts[kind] = _counts.get(kind, 0) + 1


def refused(what: str) -> str:
    """Count ``what`` as refused and return the sentence to show (:func:`message`).

    For call sites that stop an action themselves while offline.
    """
    logger.info("Refused while offline: %s", what)
    _record(REFUSED, what)
    return message(what)


def skipped(what: str, *, once: bool = False) -> None:
    """Count an automatic request (``what``, e.g. "the update check") as not sent.

    ``once``: count it only the first time since the count started, for a
    request the app sends at most once per run (the online config, which
    every config read would otherwise count again).
    """
    if once:
        with _log_lock:
            if what in _skipped_once:
                return
            _skipped_once.add(what)
    logger.debug("Skipped while offline: %s", what)
    _record(SKIPPED, what)


@contextmanager
def feature(name: str) -> Generator[None]:
    """Name the feature for backstop events from this thread inside the block."""
    previous = getattr(_feature_label, "name", None)
    _feature_label.name = name
    try:
        yield
    finally:
        _feature_label.name = previous


def activity() -> Activity:
    """A snapshot of this process's Network log."""
    with _log_lock:
        events = sorted((*_events, *_local_events), key=lambda e: e.when)
        return Activity(_since, dict(_counts), tuple(events))


def reset_activity() -> None:
    """Start counting again (when the switch is turned on)."""
    global _since
    with _log_lock:
        _events.clear()
        _local_events.clear()
        _skipped_once.clear()
        for kind in _counts:
            _counts[kind] = 0
        _since = time.time()


# --- backstop: refuse sockets that leave this computer --------------------

_guard_lock = threading.Lock()
_originals: dict[str, Any] = {}


def _host_text(host: object) -> str:
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    return str(host).strip().rstrip(".").lower()


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    return True


def _is_local_name(text: str) -> bool:
    return text in ("", "localhost") or text.endswith(".localhost")


def lookup_allowed(host: object) -> bool:
    """A name lookup that sends nothing: local names, IP literals, this computer's name."""
    if host is None:
        return True
    text = _host_text(host)
    if _is_local_name(text) or _is_ip(text):
        return True
    try:
        return text == socket.gethostname().lower()
    except OSError:
        return False


def connect_allowed(family: int, sock_type: int, address: object) -> bool:
    """A connection that stays on this computer (loopback, a local socket).

    A UDP ``connect`` only picks the route and sends nothing (the server uses
    one to find its LAN address), so it is allowed.
    """
    if family not in (socket.AF_INET, socket.AF_INET6):
        return True
    if sock_type == socket.SOCK_DGRAM:
        return True
    if not isinstance(address, tuple) or not address:
        return False
    text = _host_text(address[0])
    if _is_local_name(text):
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def url_stays_local(url: str) -> bool:
    """True for an http(s) URL on this computer (a local AI server, for example)."""
    from urllib.parse import urlsplit

    try:
        host = urlsplit(str(url)).hostname or ""
    except ValueError:
        return False
    if not host:
        return False
    text = _host_text(host)
    if _is_local_name(text):
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def send_allowed(family: int, address: object) -> bool:
    """A UDP datagram (``sendto`` / ``sendmsg``) that stays on this computer."""
    if family not in (socket.AF_INET, socket.AF_INET6):
        return True
    if address is None:
        return True  # sendmsg on a connected socket: no address to check
    return connect_allowed(family, socket.SOCK_STREAM, address)


def reverse_lookup_allowed(address: object) -> bool:
    """A reverse lookup (``gethostbyaddr``) that sends nothing.

    Loopback addresses, local names and this computer's own name only: the
    reverse lookup of any other IP address is a DNS query.
    """
    if address is None:
        return True
    text = _host_text(address)
    if _is_local_name(text):
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        pass
    try:
        return text == socket.gethostname().lower()
    except OSError:
        return False


def _refusal(target: object) -> OfflineModeError:
    # Logged: a refusal here means a call site did not ask first.
    logger.info("Work offline: refused a connection to %s", target)
    feature_name = _caller_feature()
    _record(TEST if feature_name == SELF_TEST_FEATURE else REFUSED, feature_name, target)
    return OfflineModeError(message(f"a connection to {target}"))


def _allowed_local(target: object) -> None:
    _record(LOCAL, _caller_feature(), target)


def _is_inet_stream(sock: socket.socket) -> bool:
    # A UDP connect only picks a route (connect_allowed): not logged as a connection.
    return sock.family in (socket.AF_INET, socket.AF_INET6) and sock.type == socket.SOCK_STREAM


def _target(address: object) -> object:
    return address[0] if isinstance(address, tuple) and address else address


# The audit hook (PEP 578) cannot be removed once added, so it is added once
# per process and acts only while the guard is installed.
_audit_hook_added = False
_AUDIT_EVENTS = frozenset({
    "socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg",
    "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
})


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    # Every audited event of the process passes here: return at once for
    # everything that is not one of the five socket calls.
    if event not in _AUDIT_EVENTS or not _originals or not is_offline():
        return
    if event == "socket.connect":
        # The C-level connect / connect_ex: code that calls _socket directly
        # or a getaddrinfo bound before the patch (the patched methods asked first).
        sock, address = args[0], args[1]
        family = getattr(sock, "family", socket.AF_INET)
        if not connect_allowed(family, getattr(sock, "type", socket.SOCK_STREAM), address):
            raise _refusal(_target(address))
    elif event == "socket.getaddrinfo":
        if not lookup_allowed(args[0]):
            raise _refusal(args[0])
    elif event in ("socket.sendto", "socket.sendmsg"):
        sock, address = args[0], args[1]
        family = getattr(sock, "family", socket.AF_INET)
        if not send_allowed(family, address):
            raise _refusal(_target(address))
    elif event == "socket.gethostbyname":
        if not lookup_allowed(args[0]):
            raise _refusal(args[0])
    elif event == "socket.gethostbyaddr":
        if not reverse_lookup_allowed(args[0]):
            raise _refusal(args[0])
    else:  # socket.getnameinfo((host, port[, ...]))
        address = args[0]
        if not reverse_lookup_allowed(_target(address)):
            raise _refusal(_target(address))


def install_network_guard() -> None:
    """Patch :mod:`socket` so that, while offline, nothing leaves this computer.

    Idempotent. Costs one :func:`is_offline` call per connection or lookup
    while the switch is off. Covers ``socket.socket.connect`` / ``connect_ex``
    (and so ``ssl``, ``http.client``, ``urllib``, ``requests``),
    ``socket.getaddrinfo`` (``create_connection``) and, through an audit hook,
    the same calls made on ``_socket`` directly, UDP ``sendto`` / ``sendmsg``
    with an address and the lookups ``gethostbyname`` / ``gethostbyaddr`` /
    ``getnameinfo``; on Windows also asyncio's Proactor loop (IOCP connect and
    sendto). Not covered: a UDP socket connected to an outside address and
    then used with ``send``, and code that does not go through Python's
    :mod:`socket` module or asyncio. Child
    processes (workers, yt-dlp, ffmpeg) are guarded by their own entry point
    or call site, not by this process.
    """
    global _audit_hook_added
    with _guard_lock:
        if _originals:
            return
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex
        orig_getaddrinfo = socket.getaddrinfo

        def connect(self: socket.socket, address: Any) -> None:
            if is_offline():
                if not connect_allowed(self.family, self.type, address):
                    raise _refusal(_target(address))
                if _is_inet_stream(self):
                    _allowed_local(_target(address))
            return orig_connect(self, address)

        def connect_ex(self: socket.socket, address: Any) -> int:
            if is_offline():
                if not connect_allowed(self.family, self.type, address):
                    # connect_ex reports a failure as an error number, never raises.
                    _refusal(_target(address))
                    return errno.EACCES
                if _is_inet_stream(self):
                    _allowed_local(_target(address))
            return orig_connect_ex(self, address)

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            if is_offline() and not lookup_allowed(host):
                raise _refusal(host)
            return orig_getaddrinfo(host, *args, **kwargs)

        _originals.update(
            connect=orig_connect, connect_ex=orig_connect_ex, getaddrinfo=orig_getaddrinfo,
        )
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo
        if not _audit_hook_added:
            sys.addaudithook(_audit_hook)
            _audit_hook_added = True
        _guard_asyncio_proactor()


def _guard_asyncio_proactor() -> None:
    """Windows: asyncio's default (Proactor) loop connects and sends through
    IOCP (ConnectEx / WSASendTo), which fires no socket audit event, so its two
    entry points ask too. Called with ``_guard_lock`` held."""
    if sys.platform != "win32":
        return
    from asyncio import windows_events

    cls = windows_events.IocpProactor
    orig_connect = cls.connect
    orig_sendto = cls.sendto

    def connect(self: Any, conn: socket.socket, address: Any) -> Any:
        if is_offline() and not connect_allowed(conn.family, conn.type, address):
            raise _refusal(_target(address))
        return orig_connect(self, conn, address)

    def sendto(self: Any, conn: socket.socket, buf: Any, flags: int = 0, addr: Any = None) -> Any:
        if is_offline() and not send_allowed(conn.family, addr):
            raise _refusal(_target(addr))
        return orig_sendto(self, conn, buf, flags, addr)

    _originals["proactor"] = (cls, orig_connect, orig_sendto)
    cls.connect = connect  # type: ignore[method-assign]
    cls.sendto = sendto  # type: ignore[method-assign]


def uninstall_network_guard() -> None:
    """Undo :func:`install_network_guard` (tests)."""
    with _guard_lock:
        if not _originals:
            return
        socket.socket.connect = _originals["connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = _originals["connect_ex"]  # type: ignore[method-assign]
        socket.getaddrinfo = _originals["getaddrinfo"]
        proactor = _originals.get("proactor")
        if proactor is not None:
            cls, connect, sendto = proactor
            cls.connect = connect
            cls.sendto = sendto
        _originals.clear()


def network_guard_installed() -> bool:
    return bool(_originals)


# --- what is really open: the app's own process tree -----------------------

@dataclass(frozen=True)
class OpenConnection:
    """A connection of the app's process tree to another computer."""

    pid: int
    process: str
    protocol: str  # "TCP" or "UDP"
    remote: str  # "address:port"
    incoming: bool  # to a port this app listens on (the local server)


@dataclass(frozen=True)
class ConnectionCheck:
    """One look at the open connections. ``ok`` is False when it could not look."""

    when: float
    ok: bool
    outside: tuple[OpenConnection, ...] = ()
    processes: int = 0
    error: str = ""


def _is_loopback_ip(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(text).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(ip.is_loopback or (mapped is not None and mapped.is_loopback))


def poll_connections(root_pid: int | None = None) -> ConnectionCheck:
    """List the open connections to other computers of this process and its children.

    Reads the operating system's connection table (psutil): what is open at
    this moment, whatever opened it. Children are found through their parent
    links, so a process whose parent has already ended is not seen. Windows
    reports no remote address for UDP sockets, so in practice this lists TCP
    connections. A connection that opens and closes between two checks is
    not seen, and nothing here measures bytes.
    """
    import os

    now = time.time()
    try:
        import psutil
    except ImportError as e:
        return ConnectionCheck(now, False, error=f"psutil is not available ({e})")
    try:
        root = psutil.Process(root_pid if root_pid is not None else os.getpid())
        procs = [root, *root.children(recursive=True)]
    except (psutil.Error, OSError) as e:
        return ConnectionCheck(now, False, error=f"could not list the app's processes ({e})")
    rows: list[tuple[int, str, Any]] = []
    listening: set[int] = set()
    looked = 0
    for proc in procs:
        try:
            conns = proc.net_connections(kind="inet")
        except psutil.NoSuchProcess:
            continue  # ended between the listing and the look
        except (psutil.Error, OSError) as e:
            return ConnectionCheck(now, False, error=f"could not read process {proc.pid} ({e})")
        try:
            name = proc.name()
        except (psutil.Error, OSError):
            name = f"process {proc.pid}"
        looked += 1
        for conn in conns:
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                listening.add(conn.laddr.port)
            rows.append((proc.pid, name, conn))
    outside: list[OpenConnection] = []
    for pid, name, conn in rows:
        if not conn.raddr or _is_loopback_ip(conn.raddr.ip):
            continue
        outside.append(OpenConnection(
            pid=pid,
            process=name,
            protocol="TCP" if conn.type == socket.SOCK_STREAM else "UDP",
            remote=f"{conn.raddr.ip}:{conn.raddr.port}",
            incoming=bool(conn.laddr) and conn.laddr.port in listening,
        ))
    return ConnectionCheck(now, True, tuple(outside), processes=looked)


# --- "Verify offline now" ----------------------------------------------------

#: TEST-NET-3 (RFC 5737): reserved for documentation, never a real computer.
SELF_TEST_ADDRESS = "203.0.113.1"
#: ``.invalid`` names never resolve (RFC 6761).
SELF_TEST_NAME = "work-offline-check.invalid"


@dataclass(frozen=True)
class ProbeResult:
    what: str
    refused: bool
    detail: str


def _probe(what: str, attempt: Any) -> ProbeResult:
    try:
        attempt()
    except OfflineModeError:
        return ProbeResult(what, True, "refused by Work offline")
    except OSError as e:
        return ProbeResult(what, False, f"NOT refused by Work offline, it was tried: {e}")
    return ProbeResult(what, False, "NOT refused by Work offline, it went through")


def self_test() -> list[ProbeResult]:
    """Try one outside connection, one name lookup and one UDP send; each must be refused.

    Only while Work offline is on (otherwise these would really be sent).
    The targets are reserved addresses that reach no real computer.
    """
    if not is_offline():
        raise RuntimeError("Work offline is off: the check would really connect.")

    def tcp() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((SELF_TEST_ADDRESS, 443))

    def lookup() -> None:
        socket.getaddrinfo(SELF_TEST_NAME, 443)

    def udp() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"", (SELF_TEST_ADDRESS, 9))

    with feature(SELF_TEST_FEATURE):
        return [
            _probe(f"TCP connection to {SELF_TEST_ADDRESS}", tcp),
            _probe(f"name lookup of {SELF_TEST_NAME}", lookup),
            _probe(f"UDP send to {SELF_TEST_ADDRESS}", udp),
        ]


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """``env`` for a child process that may download by itself (Demucs).

    While offline, every proxy variable points at a closed port on this
    computer: tools that honour them (urllib, requests, pip, PyTorch Hub) then
    fail at once without a name lookup, and a model already on disk still
    loads. Hugging Face libraries are told to stay offline too.
    """
    out = dict(env)
    if not is_offline():
        return out
    closed = "http://127.0.0.1:9"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        out[name] = closed
    for name in ("NO_PROXY", "no_proxy"):
        out.pop(name, None)
    out["HF_HUB_OFFLINE"] = "1"
    out["TRANSFORMERS_OFFLINE"] = "1"
    return out
