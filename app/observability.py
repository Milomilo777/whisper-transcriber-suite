"""Optional Sentry crash reporting + launch ping.

Both pieces need two things at once:

  * ``config["telemetry_opt_in"]`` — the Advanced dialog's usage-statistics
    checkbox, which is ON by default (it also gates ``core.stats``); and
  * the matching environment variable:
      - crash reports → ``SENTRY_DSN``
      - launch ping   → ``WHISPER_TELEMETRY_URL`` (POST endpoint)

The published builds set neither variable, so by default this module
sends nothing, contacts no DSN and spawns no thread. With the flag off it
is a no-op whatever the environment says. When crash reports are on, each
event passes through :func:`scrub_sentry_event` first (no host name, file
paths, local variables or log breadcrumbs).

The launch ping carries ``schema``, ``version``, ``os``, ``os_release``,
``python`` and ``anonymised_id`` — no file paths and no transcript
content. ``anonymised_id`` is a stable per-install id (see
:func:`_anonymised_id`), so pings from one install can be linked to each
other. The receiving server sees the connection's IP address like any web
server; whether it stores it is up to that server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bumped whenever the launch-ping payload schema changes.
_PAYLOAD_VERSION = 1
_LAUNCH_PING_TIMEOUT_S = 4


def _telemetry_opted_in() -> bool:
    """Read ``telemetry_opt_in`` (the usage-statistics switch) on demand.

    Looked up dynamically so a user toggling the flag in Advanced
    takes effect on the *next* app launch without any restart
    plumbing in this module. Work offline counts as "off".
    """
    try:
        from core import offline
        from core.config import load_config  # type: ignore[import-not-found]
        if offline.is_offline():
            offline.skipped("crash reports and the launch ping")
            return False
        return bool(load_config().get("telemetry_opt_in", False))
    except Exception:  # noqa: BLE001
        return False


def _anonymised_id() -> str:
    """Stable per-install identifier for the launch ping.

    A SHA-256 digest of a random UUID4, written to ``user_cache_dir() /
    telemetry_id`` on first use and reused on every later launch. It
    identifies the install (pings from one install share it) but holds
    nothing derived from the machine or the user. Returns ``""`` when the cache
    directory or the file cannot be written — the caller must never
    fail because telemetry could not be persisted.
    """
    try:
        from core.config import user_cache_dir  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return ""
    cache = user_cache_dir()
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # A blocked / read-only cache path must not escape: this is called
        # while building the launch-ping payload on the Tk main thread, so
        # an uncaught OSError here would abort startup. Fall back to no id.
        logger.info("Could not create telemetry cache dir (%s); skipping id", e)
        return ""
    p: Path = cache / "telemetry_id"
    if p.exists():
        try:
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                return raw
        except OSError:
            pass
    raw = uuid.uuid4().hex
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    try:
        p.write_text(digest, encoding="utf-8")
    except OSError:
        pass
    return digest


def _app_version() -> str:
    """Best-effort version string for the launch ping."""
    try:
        # pyproject.toml's [project].version is the canonical source.
        import importlib.metadata as md
        return md.version("whisper-transcriber-suite")
    except Exception:  # noqa: BLE001
        pass
    # Fall back to the bundled version constant — works in the frozen /
    # embed build, where importlib.metadata has no package to read.
    try:
        from core import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0.0.0"


# Crash-report scrubbing. A default Sentry event carries the host name,
# every frame's absolute path (the install folder holds the account name),
# frame local variables, log breadcrumbs and sys.argv, and exception
# messages quote file paths ("No such file or directory: 'C:\\...'"). The
# event keeps what the code itself defines -- exception type, module and
# function names, source file base names, line numbers, log templates --
# and loses or masks the rest.
_SENTRY_DROPPED_KEYS = ("server_name", "user", "request", "extra", "breadcrumbs")
_SENTRY_DROPPED_FRAME_KEYS = ("abs_path", "vars")
_SCRUBBED = "[removed]"
_URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"]*")
# A drive, UNC, home or absolute POSIX path runs to the end of the line:
# file names hold spaces, so no shorter end is safe.
_ABS_PATH_RE = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|\\\\|~[\\/]|(?<![\w.:/\\~])/(?=[^\s/\\]+/))[^\n]*"
)
# A quoted value with a separator or a file extension: a relative path
# or a bare file name as repr() prints it.
_QUOTED_FILE_RE = re.compile(
    r"'[^'\n]*(?:[\\/][^'\n]*|\.[A-Za-z0-9]{1,5})'"
    r"|\"[^\"\n]*(?:[\\/][^\"\n]*|\.[A-Za-z0-9]{1,5})\""
)


def _scrub_text(text: str) -> str:
    text = _URL_RE.sub(_SCRUBBED, text)
    text = _ABS_PATH_RE.sub(_SCRUBBED, text)
    return _QUOTED_FILE_RE.sub(_SCRUBBED, text)


def _scrub_frame(frame: Any) -> Any:
    if not isinstance(frame, dict):
        return _scrub_value(frame)
    out = {k: v for k, v in frame.items() if k not in _SENTRY_DROPPED_FRAME_KEYS}
    filename = out.get("filename")
    if isinstance(filename, str):
        out["filename"] = re.split(r"[\\/]", filename)[-1]
    return out


def _scrub_value(value: Any, key: str = "") -> Any:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, list):
        if key == "frames":
            return [_scrub_frame(f) for f in value]
        return [_scrub_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_value(v, str(k)) for k, v in value.items()}
    return value


def scrub_sentry_event(event: dict[str, Any], hint: Any = None) -> dict[str, Any]:
    """``before_send`` hook: strip paths, file names and machine details.

    Drops the host name, user, request, extra (``sys.argv``) and
    breadcrumbs; drops each frame's absolute path and local variables and
    keeps only the source file's base name; drops log-record arguments
    (the template stays); masks URLs, absolute paths (to the end of the
    line) and quoted paths or file names in every remaining string.
    A file name written into a message without quotes or a folder cannot
    be told apart from other words and is not masked.
    """
    del hint
    event = dict(event)
    for key in _SENTRY_DROPPED_KEYS:
        event.pop(key, None)
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        event["logentry"] = {
            k: v for k, v in logentry.items() if k not in ("params", "formatted")
        }
    return _scrub_value(event)


def _sentry_options(dsn: str) -> dict[str, Any]:
    """Keyword arguments for ``sentry_sdk.init``: no personal data."""
    return {
        "dsn": dsn,
        "traces_sample_rate": 0.0,
        "send_default_pii": False,
        "include_local_variables": False,
        "max_breadcrumbs": 0,
        "before_send": scrub_sentry_event,
    }


def init_sentry() -> bool:
    """Initialise Sentry SDK if ``telemetry_opt_in`` is on and SENTRY_DSN is set.

    Returns True only when the SDK was actually initialised. Every
    failure — flag off, no DSN, missing package, or an SDK error such
    as a malformed DSN — returns False and is logged, never raised.
    Every event passes through :func:`scrub_sentry_event`.
    """
    if not _telemetry_opted_in():
        return False
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        logger.info("SENTRY_DSN set but sentry-sdk is not installed; skipping")
        return False
    try:
        sentry_sdk.init(**_sentry_options(dsn))
    except Exception as e:  # noqa: BLE001
        # A malformed DSN (or any other SDK init failure) must not take
        # down launch: this is called unguarded from App.__init__, and the
        # module's contract is "optional crash reporting", not "crash the app
        # in order to report crashes". Stay off and log it.
        logger.warning("Sentry init failed (ignored): %s", e)
        return False
    logger.info("Sentry crash reporting enabled")
    return True


def send_launch_ping_async() -> None:
    """Fire a single POST on a daemon thread. Best-effort, never blocks.

    The receiving URL comes from ``$WHISPER_TELEMETRY_URL`` — an
    empty env var disables the ping entirely. Bad DNS, timeouts,
    non-2xx responses, and dropped sockets are all logged at INFO
    and swallowed; nothing about the ping is surfaced to the user.
    """
    if not _telemetry_opted_in():
        return
    url = os.environ.get("WHISPER_TELEMETRY_URL", "").strip()
    if not url:
        return

    payload = {
        "schema": _PAYLOAD_VERSION,
        "version": _app_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "python": platform.python_version(),
        "anonymised_id": _anonymised_id(),
    }

    def _worker() -> None:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=_LAUNCH_PING_TIMEOUT_S).read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.info("Launch ping failed (ignored): %s", e)
        except Exception as e:  # noqa: BLE001
            logger.info("Launch ping crashed (ignored): %s", e)

    from core._threads import safe_thread
    safe_thread(_worker, name="launch-ping")
