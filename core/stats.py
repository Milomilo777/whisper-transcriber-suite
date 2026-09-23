"""Best-effort, opt-in usage-stats POST (P4-4).

Sends per-transcription usage to the maintainer's stats endpoint
(``config['stats_url']``). PRIVACY: the payload includes the file name (no
path), model, language, audio duration, AI transcription time, status, the
running app version, and coarse host/hardware facts (OS, machine, CPU count,
total RAM — no serial numbers, no user names, no IPs; the client IP + geoip
country are added server-side from the request, not by this module). It is
therefore sent ONLY when the user has opted in
(``config['telemetry_opt_in']``); the caller must gate on that.

Design rules (mirrors app.observability's opt-in posture):

  * Tk-free; local-only introspection (``platform``, ``psutil``) plus
    stdlib ``urllib`` for the POST — no data leaves the machine besides the
    one opt-in request. Short timeout, daemon thread — never blocks or
    crashes a transcription if stats fail. Every error is swallowed.
  * The payload builder :func:`build_stats_payload` is a PURE, testable
    function (no network I/O); :func:`post_stats_async` does the
    fire-and-forget POST.
  * No POST is attempted when ``stats_url`` is empty.

The matching server is ``stats/transcription_stats.php`` in this repo.
"""
from __future__ import annotations

import logging
import platform
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# psutil only feeds the two optional hardware fields below. This module's
# contract is "stats never break anything", so a missing wheel (e.g. a
# source checkout whose venv predates the 1.5.0 requirements bump) must
# degrade those fields to "0", not blow up every importer at import time.
try:
    import psutil
except ImportError:  # pragma: no cover - exercised via a blocked import in tests
    psutil = None  # type: ignore[assignment]

from core import __version__ as _PROGRAM_VERSION

logger = logging.getLogger(__name__)

# Fields the PHP endpoint records (form_submitted toggles the insert).
_FORM_FLAG = "form_submitted"


def count_words(text: str) -> int:
    """Whitespace-split word count of *text* (0 for empty / None)."""
    return len((text or "").split())


def count_words_in_segments(segments: list[dict] | None) -> int:
    """Total words across a faster-whisper segment list's ``text`` fields.

    A non-string / missing ``text`` counts as 0 words. ``str(None)`` is
    ``"None"`` which would otherwise be miscounted as one real word.
    """
    if not segments:
        return 0
    total = 0
    for s in segments:
        # A JSON sidecar that is a list of non-dicts (a hand-edited or
        # malformed file -> e.g. ["a", "b"]) would AttributeError on
        # ``.get``; skip any element that is not a segment dict.
        if not isinstance(s, dict):
            continue
        text = s.get("text", "")
        if isinstance(text, str):
            total += count_words(text)
    return total


def audio_duration_from_segments(segments: list[dict] | None) -> float:
    """Best-effort audio duration = the last segment's end time (seconds).

    The transcript covers the audio, so the final segment's end is a close
    lower bound on the media length when no probed duration is available.
    Returns 0.0 for an empty list.
    """
    if not segments:
        return 0.0
    last = segments[-1]
    # The final element may not be a segment dict (a malformed sidecar list
    # of non-dicts); ``.get`` would raise AttributeError, which the
    # (TypeError, ValueError) handler below does NOT catch. Guard it.
    if not isinstance(last, dict):
        return 0.0
    try:
        return float(last.get("end", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_stats_payload(
    *,
    file_name: str,
    model: str,
    language: str,
    audio_duration: float,
    transcription_time: float,
    status: str,
    word_count: int = 0,
) -> dict[str, str]:
    """Build the form-encoded stats payload (PURE — no I/O, no network).

    ``file_name`` is reduced to its basename so no local path leaks. All values
    are stringified for ``application/x-www-form-urlencoded``. The
    ``form_submitted`` flag tells the PHP endpoint to record the row; the
    client IP + geoip are added server-side from the request, NOT here.
    """
    # Local alias: a module-level global is never narrowed by a None
    # check (it could be reassigned elsewhere), a local is.
    ps = psutil
    return {
        _FORM_FLAG: "1",
        "file_name": Path(str(file_name or "")).name,
        "model": str(model or ""),
        "language": str(language or ""),
        "audio_duration": f"{float(audio_duration or 0.0):.3f}",
        "transcription_time": f"{float(transcription_time or 0.0):.3f}",
        "status": str(status or ""),
        "word_count": str(int(word_count or 0)),
        "program_version": str(_PROGRAM_VERSION or ""),
        "platform_system": platform.system(),
        "platform_node": platform.node(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "platform_machine": platform.machine(),
        "platform_processor": platform.processor(),
        "cpu_count": str(ps.cpu_count() or 0) if ps is not None else "0",
        "mem_total": (
            str(int(ps.virtual_memory().total)) if ps is not None else "0"
        ),
    }


def _post(url: str, payload: dict[str, str], timeout: float) -> None:
    """Blocking POST of a form-encoded payload; swallows every error."""
    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "WhisperTranscriberSuite",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(1)  # drain a byte; we don't care about the body
        logger.debug("usage stats posted to %s", url)
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Offline / timeout / HTTP error / bad URL — stats are best-effort.
        logger.debug("usage stats post failed (ignored): %s", e)
    except Exception as e:  # noqa: BLE001 — never let stats crash anything
        logger.debug("usage stats post error (ignored): %s", e)


def post_stats_async(
    config: dict[str, Any],
    payload: dict[str, str],
    *,
    timeout: float = 5.0,
) -> bool:
    """Fire-and-forget the stats POST on a daemon thread, IF opted in.

    Returns ``True`` when a POST thread was started, ``False`` when it was
    skipped (telemetry off, no ``stats_url``, or a bad payload). The caller has
    already gated on ``telemetry_opt_in`` in the normal path, but this re-checks
    so a mistaken direct call can never leak data without opt-in.

    Never raises and never blocks the caller.
    """
    try:
        if not bool(config.get("telemetry_opt_in", False)):
            return False
        url = str(config.get("stats_url") or "").strip()
        if not url:
            return False
        # stats_url is in ONLINE_ALLOWED_KEYS, so a compromised / MITM'd online
        # config could point telemetry at an arbitrary scheme (file://, ftp://,
        # an attacker collector). urlopen honours whatever scheme it is given,
        # so reject anything that is not plain web traffic before the request.
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            logger.debug("stats post skipped: non-http(s) stats_url scheme")
            return False
        if not isinstance(payload, dict) or not payload:
            return False
        t = threading.Thread(
            target=_post, args=(url, dict(payload), float(timeout)),
            daemon=True, name="stats-post",
        )
        t.start()
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("post_stats_async skipped (ignored): %s", e)
        return False
