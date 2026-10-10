"""Problem reports sent through the usage-statistics endpoint, for people without a GitHub account.

The statistics server (``platform/stats-server/transcription_stats.php``) is used exactly as it
is: it stores one row of short, length-capped text fields per request. A report is one such row
with ``status`` = ``problem_report``: the app version and the operating system go into their own
fields, and the person's own words are spread over the three longest text fields
(``model`` 128, ``platform_version`` 256 and ``platform_processor`` 128 characters), so a report
holds at most :data:`MAX_CHARS` characters.

Nothing else is sent: no file names, paths, logs, settings or computer name. The person sees the
full text before sending, and Work offline blocks the send like every other network call. A
report is an explicit action, so it is sent even when the usage-statistics switch is off.
"""
from __future__ import annotations

import logging
import platform
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core import __version__ as _APP_VERSION
from core import offline

logger = logging.getLogger(__name__)

STATUS = "problem_report"
# (field, characters it holds on the server), in reading order.
TEXT_FIELDS: tuple[tuple[str, int], ...] = (
    ("model", 128), ("platform_version", 256), ("platform_processor", 128),
)
MAX_CHARS = sum(n for _f, n in TEXT_FIELDS)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r" {2,}")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


class ProblemReportError(Exception):
    """The report could not be sent; the message says why, in plain words."""


def clean_text(text: str) -> str:
    """The person's words as they will be stored: one line, no control characters, capped."""
    text = _SURROGATE.sub("\ufffd", str(text or ""))
    text = _CONTROL.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text[:MAX_CHARS]


def split_text(text: str) -> dict[str, str]:
    """``text`` (already cleaned) cut into the capped server fields, in order."""
    out: dict[str, str] = {}
    pos = 0
    for field, size in TEXT_FIELDS:
        out[field] = text[pos:pos + size]
        pos += size
    return out


def os_name() -> str:
    """The operating system as people know it: "macOS 10.15.7", not "Darwin 19.6.0"."""
    system = platform.system()
    if system == "Darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    return f"{system} {platform.release()}".strip()


def system_summary() -> str:
    """The facts that go with a report, as the dialog shows them."""
    return f"Whisper Transcriber Suite {_APP_VERSION} on {os_name()} ({platform.machine()})"


def build_payload(text: str) -> dict[str, str]:
    """The form fields for one report (no network I/O)."""
    cleaned = clean_text(text)
    if not cleaned:
        raise ProblemReportError("Please describe the problem first.")
    payload = {
        "form_submitted": "1",
        "status": STATUS,
        "language": "",
        "program_version": str(_APP_VERSION),
        "platform_system": platform.system(),
        "platform_release": os_name(),
        "platform_machine": platform.machine(),
        "audio_duration": "0",
        "transcription_time": "0",
        "word_count": "0",
        "cpu_count": "0",
        "mem_total": "0",
    }
    payload.update(split_text(cleaned))
    return payload


def send(config: dict[str, Any], text: str, *, timeout: float = 15.0) -> None:
    """POST one report; raises :class:`ProblemReportError` with a readable reason on failure.

    Blocking: call it from a worker thread.
    """
    payload = build_payload(text)
    if offline.is_offline():
        raise ProblemReportError(
            "Work offline is on, so nothing is sent. Switch it off in the File menu and try again.")
    url = str(config.get("stats_url") or "").strip()
    if not url or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ProblemReportError("This copy of the app has no report address set.")
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "WhisperTranscriberSuite"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(1)
    except urllib.error.HTTPError as e:
        logger.info("problem report refused: HTTP %s", e.code)
        raise ProblemReportError(f"The server refused the report (HTTP {e.code}).") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.info("problem report not sent: %s", e)
        raise ProblemReportError(
            "Could not reach the server. Check the internet connection and try again.") from e
    logger.info("problem report sent (%d characters)", len(clean_text(text)))
