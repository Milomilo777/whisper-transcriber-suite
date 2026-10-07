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
outbound TCP connection and host-name lookup that does not stay on this
computer.

The switch is read from ``config.json`` on each call, so the desktop app, its
worker processes, the CLI and the server follow the same saved choice; the
desktop app also holds it in memory (:func:`set_offline`) from the moment the
user flips it.
"""
from __future__ import annotations

import ipaddress
import logging
import math
import socket
import threading
from collections.abc import Mapping
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
# parsed again. st_ino changes on every atomic replace.
_cache_key: tuple[int, int, int] | None = None


def set_offline(on: bool | None) -> None:
    """Hold the switch in memory for this process; ``None`` reads config.json again."""
    global _override
    _override = None if on is None else bool(on)


def _saved_flag() -> bool:
    global _last_saved, _cache_key
    import os

    from core import config as _config

    path = _config.config_path()
    try:
        st = os.stat(path)
        key = (st.st_ino, st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        key = (-1, -1, -1)
    except OSError:
        return _last_saved
    if key == _cache_key:
        return _last_saved
    data = _config.read_local_config_for_switches()
    if data is None:
        # Unreadable right now (a save is replacing it): keep the last value.
        return _last_saved
    _last_saved = flag_from(data)
    _cache_key = key
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
        logger.info("Refused while offline: %s", what)
        raise OfflineModeError(message(what))


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


def _refusal(target: object) -> OfflineModeError:
    # Logged: a refusal here means a call site did not ask first.
    logger.info("Work offline: refused a connection to %s", target)
    return OfflineModeError(message(f"a connection to {target}"))


def _target(address: object) -> object:
    return address[0] if isinstance(address, tuple) and address else address


def install_network_guard() -> None:
    """Patch :mod:`socket` so that, while offline, nothing leaves this computer.

    Idempotent. Costs one :func:`is_offline` call per connection or lookup
    while the switch is off. Covers ``socket.socket.connect`` / ``connect_ex``
    (and so ``ssl``, ``http.client``, ``urllib``, ``requests``) and
    ``socket.getaddrinfo`` (``create_connection``), not raw UDP sends.
    Child processes are guarded by their own call sites.
    """
    with _guard_lock:
        if _originals:
            return
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex
        orig_getaddrinfo = socket.getaddrinfo

        def connect(self: socket.socket, address: Any) -> None:
            if is_offline() and not connect_allowed(self.family, self.type, address):
                raise _refusal(_target(address))
            return orig_connect(self, address)

        def connect_ex(self: socket.socket, address: Any) -> int:
            if is_offline() and not connect_allowed(self.family, self.type, address):
                raise _refusal(_target(address))
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


def uninstall_network_guard() -> None:
    """Undo :func:`install_network_guard` (tests)."""
    with _guard_lock:
        if not _originals:
            return
        socket.socket.connect = _originals["connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = _originals["connect_ex"]  # type: ignore[method-assign]
        socket.getaddrinfo = _originals["getaddrinfo"]
        _originals.clear()


def network_guard_installed() -> bool:
    return bool(_originals)


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
