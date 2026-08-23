"""Optional Sentry crash reporting + anonymous launch telemetry.

Both pieces are *strictly opt-in* via the Advanced dialog's
``Send anonymous crash reports + launch counts`` checkbox, which maps
to ``config["telemetry_opt_in"]``. Without that flag, this module is
a complete no-op — nothing is sent, no DSN is contacted, no thread
is spawned.

Even with the flag on, both pieces additionally require the matching
environment variable so packaged installers that don't ship a DSN
stay quiet by default:

  * Crash reports → ``SENTRY_DSN``
  * Launch telemetry → ``WHISPER_TELEMETRY_URL`` (POST endpoint)

The launch ping carries ``{os, version, anonymised_id}`` only —
no file paths, no transcript content, no IP address from us (the
HTTP layer's source IP is unavoidable, but the receiving server can
strip it before logging).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Bumped whenever the launch-ping payload schema changes.
_PAYLOAD_VERSION = 1
_LAUNCH_PING_TIMEOUT_S = 4


def _telemetry_opted_in() -> bool:
    """Read the opt-in flag from config.json on demand.

    Looked up dynamically so a user toggling the flag in Advanced
    takes effect on the *next* app launch without any restart
    plumbing in this module.
    """
    try:
        from core.config import load_config  # type: ignore[import-not-found]
        return bool(load_config().get("telemetry_opt_in", False))
    except Exception:  # noqa: BLE001
        return False


def _anonymised_id() -> str:
    """Stable, non-reversible per-install identifier.

    Built from a random UUID4 written to ``user_cache_dir() /
    telemetry_id`` on first use. Hashed via SHA-256 so the stored
    value alone identifies an install but cannot be linked back to a
    machine without the file on disk.
    """
    try:
        from core.config import user_cache_dir  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return ""
    cache = user_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
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


def init_sentry() -> bool:
    """Initialise Sentry SDK if opted-in and SENTRY_DSN is set."""
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
    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, send_default_pii=False)
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
