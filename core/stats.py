"""Best-effort usage-stats POST (P4-4).

Sends per-transcription usage to the maintainer's stats endpoint
(``config['stats_url']``). PRIVACY: the payload includes the model,
language, audio duration, AI transcription time, status, word count, the
running app version, a two-letter country code taken from the operating
system's region setting (:func:`region_country`, read locally, no network
lookup), and coarse host/hardware facts (OS, machine, CPU count, total RAM).
It never includes the source file's name or folder, a local model folder,
the computer name, a user name, a serial number or an IP address
(:func:`build_stats_payload` takes no file argument at all and passes the
model through :func:`public_model_name`). The server sees the connection's address
like any web server; what
it stores is decided by the server script. The payload is sent only while
``config['telemetry_opt_in']`` is true, which is the default; the user can
switch it off in the Advanced dialog. :func:`post_stats_async` checks the
flag itself. Every field is listed in docs/CONFIG.md ("Usage statistics").

Design rules:

  * Tk-free; local-only introspection (``platform``, ``psutil``, the OS
    region setting) plus stdlib ``urllib`` for the POST — nothing leaves the
    machine besides the one stats request. Short timeout, daemon thread —
    never blocks or crashes a transcription if stats fail. Every error is
    swallowed.
  * The payload builder :func:`build_stats_payload` is a testable function
    with no network I/O; :func:`post_stats_async` does the fire-and-forget
    POST.
  * No POST is attempted when ``stats_url`` is empty.

The matching server is ``platform/stats-server/transcription_stats.php`` in
this repo (deployment notes in that folder's README).
"""
from __future__ import annotations

import logging
import os
import platform
import re
import sys
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

# ISO 3166-1 alpha-2 country code shape.
_ISO2_RE = re.compile(r"[A-Za-z]{2}")

# The ``model`` field may name a catalog model ("faster-whisper-large-v3"),
# an engine ("whisper_cpp") or a Hugging Face repo id
# ("nvidia/parakeet-tdt-0.6b-v3"), optionally behind an "<engine>:" prefix.
# Anything else -- above all a local model folder typed into Advanced, whose
# path usually holds the account name -- is sent as LOCAL_MODEL_LABEL.
LOCAL_MODEL_LABEL = "local-model"
_ENGINE_PREFIX_RE = re.compile(r"([a-z][a-z0-9_]+):(.*)", re.DOTALL)
_PUBLIC_MODEL_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?"
)

# Windows NLS constants (winnls.h).
_GEOCLASS_NATION = 16
_GEO_ISO2 = 4
_GEOID_NOT_AVAILABLE = -1


def _iso2(value: str) -> str:
    """``value`` upper-cased when it is exactly two ASCII letters, else ""."""
    return value.upper() if _ISO2_RE.fullmatch(value) else ""


def _region_from_locale_name(name: str) -> str:
    """Region part of a POSIX / ICU locale name, or "".

    Handles ``fa_IR.UTF-8``, ``sr_RS@latin``, ``zh_Hant_TW``, ``en-US`` and
    the macOS region override keyword (``en_US@rg=gbzzzz`` -> ``GB``).
    ``C`` / ``POSIX`` / a bare language carry no region.
    """
    base, _, modifiers = name.partition("@")
    for modifier in modifiers.split(";"):
        key, _, value = modifier.partition("=")
        if key.strip().lower() == "rg":
            code = _iso2(value.strip()[:2])
            if code:
                return code
    base = base.partition(".")[0]
    for part in re.split(r"[_-]", base)[1:]:
        code = _iso2(part)
        if code:
            return code
    return ""


def _windows_region() -> str:
    """The Windows "Country or region" setting as ISO alpha-2, or ""."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    # A private WinDLL instance, so setting argtypes here cannot clash with
    # other callers of ctypes.windll.kernel32.
    kernel32 = ctypes.WinDLL("kernel32")
    get_user_geo_id = kernel32.GetUserGeoID
    get_user_geo_id.argtypes = [wintypes.DWORD]
    get_user_geo_id.restype = ctypes.c_long
    geo_id = get_user_geo_id(_GEOCLASS_NATION)
    if geo_id == _GEOID_NOT_AVAILABLE:
        return ""
    get_geo_info = kernel32.GetGeoInfoW
    get_geo_info.argtypes = [
        ctypes.c_long, wintypes.DWORD, ctypes.c_wchar_p, ctypes.c_int,
        wintypes.WORD,
    ]
    get_geo_info.restype = ctypes.c_int
    buf = ctypes.create_unicode_buffer(16)
    if get_geo_info(geo_id, _GEO_ISO2, buf, len(buf), 0) <= 0:
        return ""
    return _iso2(buf.value)


def _macos_region(prefs_path: Path | None = None) -> str:
    """Region of the macOS ``AppleLocale`` preference, or "".

    Read from the global preferences plist (what ``defaults read -g
    AppleLocale`` prints), so no subprocess and no PyObjC is needed.
    """
    import plistlib

    path = prefs_path or (
        Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
    )
    try:
        with open(path, "rb") as fh:
            prefs = plistlib.load(fh)
    except (OSError, ValueError) as e:
        logger.debug("AppleLocale not readable (ignored): %s", e)
        return ""
    locale_name = prefs.get("AppleLocale") if isinstance(prefs, dict) else None
    if not isinstance(locale_name, str):
        return ""
    return _region_from_locale_name(locale_name)


def _env_region(environ: Any) -> str:
    """Region of the locale environment (``LC_ALL``, then ``LANG``), or "".

    The first non-empty variable wins, as in POSIX, so ``LC_ALL=C`` means
    no region even when ``LANG`` names one.
    """
    for key in ("LC_ALL", "LANG"):
        value = environ.get(key) or ""
        if value:
            return _region_from_locale_name(str(value))
    return ""


def _region_for(platform_name: str) -> str:
    """Dispatch of :func:`region_country` by ``sys.platform`` value."""
    try:
        if platform_name == "win32":
            return _windows_region()
        if platform_name == "darwin":
            code = _macos_region()
            if code:
                return code
        return _env_region(os.environ)
    except Exception as e:  # noqa: BLE001 — stats never break anything
        logger.debug("region lookup failed (ignored): %s", e)
        return ""


def region_country() -> str:
    """Two-letter country code (e.g. ``"DE"``) from the OS region setting.

    Windows: the "Country or region" setting (``GetUserGeoID`` +
    ``GetGeoInfoW(GEO_ISO2)``). macOS: the ``AppleLocale`` preference,
    falling back to the locale environment. Linux and others: the region
    part of ``LC_ALL`` / ``LANG``. Returns "" when no region is set or the
    lookup fails. Local only: no network, never raises.
    """
    return _region_for(sys.platform)


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


def public_model_name(value: object) -> str:
    """The ``model`` value as the stats payload may carry it: never a path.

    A catalog name, an engine id or a ``owner/name`` repo id passes
    unchanged (an ``<engine>:`` prefix is kept). A value that is a path
    (drive, UNC, home, absolute, ``..``, more than one separator) or names
    an existing local folder becomes :data:`LOCAL_MODEL_LABEL`, so a model
    folder the user picked never sends its location or the account name in
    it.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    prefix = ""
    match = _ENGINE_PREFIX_RE.fullmatch(text)
    if match:
        prefix, text = match.group(1), match.group(2).strip()
        if not text:
            return prefix
        prefix += ":"
    if (
        _PUBLIC_MODEL_RE.fullmatch(text)
        and ".." not in text
        and not os.path.isdir(text)
    ):
        return prefix + text
    return prefix + LOCAL_MODEL_LABEL


def build_stats_payload(
    *,
    model: str,
    language: str,
    audio_duration: float,
    transcription_time: float,
    status: str,
    word_count: int = 0,
) -> dict[str, str]:
    """Build the form-encoded stats payload (no network I/O).

    All values are stringified for ``application/x-www-form-urlencoded``.
    The ``form_submitted`` flag tells the PHP endpoint to record the row.
    ``country`` comes from the OS region setting (:func:`region_country`).
    The source file's name or path, the computer name and any IP address
    are never included; there is deliberately no file parameter, so no
    caller can add one by accident. ``model`` passes through
    :func:`public_model_name`, so a local model folder is never sent.
    """
    # Local alias: a module-level global is never narrowed by a None
    # check (it could be reassigned elsewhere), a local is.
    ps = psutil
    return {
        _FORM_FLAG: "1",
        "model": public_model_name(model),
        "language": str(language or ""),
        "audio_duration": f"{float(audio_duration or 0.0):.3f}",
        "transcription_time": f"{float(transcription_time or 0.0):.3f}",
        "status": str(status or ""),
        "word_count": str(int(word_count or 0)),
        "program_version": str(_PROGRAM_VERSION or ""),
        "country": region_country(),
        "platform_system": platform.system(),
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
    """Fire-and-forget the stats POST on a daemon thread while stats are on.

    Returns ``True`` when a POST thread was started, ``False`` when it was
    skipped (``telemetry_opt_in`` off, no ``stats_url``, or a bad payload).
    This is the gate: it reads ``telemetry_opt_in`` itself, so no caller can
    send while the user has switched stats off.

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
