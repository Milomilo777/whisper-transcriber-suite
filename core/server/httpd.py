"""Stdlib-only HTTP job server for Whisper Transcriber Suite.

A ``ThreadingHTTPServer`` plus a typed ``BaseHTTPRequestHandler`` that
exposes a tiny JSON API and one static page so people on a trusted LAN
transcribe through a browser instead of each installing the desktop app.

Routes
------
  GET  /                          -> the bundled static index.html
  GET  /api/health                -> {status, version, formats}
  GET  /api/formats               -> {formats}
  GET  /api/options               -> {formats, languages, diarization_available,
                                     backend_switchable}
  GET  /api/jobs                  -> {jobs: [{id, status, progress, paused,
                                     source, formats, created_at}, ...]}
  POST /api/jobs                  -> create a job (multipart upload OR
                                     JSON {"url", "formats", "language", and
                                     the advanced options}) -> {job_id}
  GET  /api/jobs/<id>             -> {status, progress, paused, error, outputs}
  GET  /api/jobs/<id>/outputs     -> {outputs: [{fmt, name}, ...]}
  GET  /api/jobs/<id>/result?fmt= -> stream the written output as download
  POST /api/jobs/<id>/cancel      -> flag the job for cancellation
  POST /api/jobs/<id>/pause       -> pause the running/queued job
  POST /api/jobs/<id>/resume      -> resume a paused job
  GET  /v1/models                 -> OpenAI-compatible model list
  POST /v1/audio/transcriptions   -> OpenAI-compatible transcription
                                     (multipart upload, synchronous response)

The ``/v1/...`` routes mirror OpenAI's real audio API closely enough that
Open-WebUI / LM Studio and the ``openai`` SDKs can point at this server as a
drop-in STT backend: multipart ``file`` + ``model``, optional ``language`` /
``response_format`` (json / text / srt / verbose_json / vtt), and the same
``{"text": ...}`` / verbose-JSON response shapes and ``{"error": {...}}``
error envelope. The existing optional token also accepts an OpenAI-style
``Authorization: Bearer <token>`` header. The request blocks until its job
finishes (the manager still runs one transcription at a time).

Per-job advanced options (vad / diarization / word-timestamps / demucs /
hallucination / chapters) are validated by the pure ``normalize_options``
seam and written into a per-job ``.whisperproject.json`` so the engine's
per-folder override mechanism applies them to THAT job only. ``clip_start`` /
``clip_end`` map onto the task's clip attributes. ``transcribe_backend`` is
intentionally NOT per-job switchable over the web (cloud engines upload audio
+ need keys; an alt-backend switch is a heavy server-global reload).

Design constraints honoured here:
  * No third-party deps — only the standard library.
  * Tk-free; imports nothing from ``app/``.
  * Route / query / multipart parsing live in small PURE helpers below so
    they can be unit-tested without binding a socket (mirroring how
    ``app/services`` exposes pure ``build_*`` seams).
  * Optional shared-secret auth via ``X-Auth-Token`` header or ``?token=``.
  * A hard max-upload-size cap enforced before any bytes are buffered.
"""
from __future__ import annotations

import hmac
import json
import logging
import math
import os
import ssl
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NamedTuple

from core import __version__
from core.server.jobs import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FINISHED,
    Job,
    JobManager,
    QueueFull,
)
from core.writers import get_writer, supported_formats


def content_disposition_attachment(filename: str) -> str:
    """Build a latin-1-safe ``Content-Disposition: attachment`` header value.

    ``http.server`` encodes header values as latin-1, so a filename containing
    any non-ASCII character — e.g. the en-dash in the SMTV ``.docx`` template
    name ``"… –Transcription in English – Translation…"`` — raised
    ``UnicodeEncodeError`` mid-response and dropped the connection (the client
    saw ``RemoteDisconnected``), making that output un-downloadable over the
    LAN server. Emit an ASCII-only ``filename="..."`` fallback PLUS the RFC 6266
    ``filename*=UTF-8''<pct-encoded>`` form, so modern clients still receive the
    exact Unicode name while the header bytes stay pure ASCII.
    """
    name = (filename or "download").replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch != '"' else "_" for ch in name
    ) or "download"
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"

logger = logging.getLogger(__name__)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Hard ceiling regardless of config, so a typo in config can't open the
# door to an unbounded upload. The configured cap is min()'d against this.
_ABSOLUTE_MAX_UPLOAD_MB = 4096

# The leading window of a multipart body we read into RAM to locate the file
# part's header + the small text fields. A real form's headers + text fields
# are a few hundred bytes; 1 MiB is a generous ceiling that still keeps RAM
# bounded regardless of the (possibly multi-GB) file payload that follows.
_MULTIPART_HEADER_WINDOW = 1024 * 1024

# A bounded window read from the END of the temp file to find the closing
# boundary, so the file part's end offset is located without buffering the
# payload. The trailing boundary + any text parts after the file are small.
_MULTIPART_TAIL_WINDOW = 64 * 1024

# A dedicated, small cap for the JSON / URL control POST body, applied
# independently of the (large) multipart upload cap. A control request is a
# few hundred bytes; 1 MiB stops a tiny intended JSON call from being inflated
# to the multimedia upload cap (a memory-amplification DoS distinct from the
# upload path).
_MAX_JSON_BODY_BYTES = 1024 * 1024

# OpenAI-compatible route: the response formats this server can render.
# ``diarized_json`` is deliberately absent (the engine's diarization output is
# not wired to that shape); an unknown value gets a 400, matching the real
# API's own validation.
OPENAI_RESPONSE_FORMATS: tuple[str, ...] = (
    "json", "text", "srt", "verbose_json", "vtt",
)

# The synchronous OpenAI route polls its job for a terminal state at this
# cadence while the HTTP handler thread waits.
_OPENAI_POLL_INTERVAL_S = 0.1


# --- pure parsing helpers (unit-testable, no socket needed) ------------------

class Route(NamedTuple):
    """A parsed request line split into the pieces the handler dispatches on."""

    method: str
    # Logical route name, e.g. "root", "health", "formats", "jobs",
    # "job", "result", "cancel", or "unknown".
    name: str
    # Path-extracted job id for /api/jobs/<id>[/...] routes, else "".
    job_id: str
    query: dict[str, str]


def parse_route(method: str, raw_path: str) -> Route:
    """Map ``(method, path)`` onto a logical route without touching a socket.

    Unknown paths resolve to ``name="unknown"`` so the handler returns 404.
    Query values are flattened to their first occurrence (single-valued API).
    """
    split = urllib.parse.urlsplit(raw_path)
    path = split.path.rstrip("/") or "/"
    query = {k: (v[0] if v else "")
             for k, v in urllib.parse.parse_qs(split.query).items()}
    parts = [p for p in path.split("/") if p]

    m = method.upper()
    if path == "/" or path == "":
        return Route(m, "root", "", query)
    if parts == ["api", "health"]:
        return Route(m, "health", "", query)
    if parts == ["api", "formats"]:
        return Route(m, "formats", "", query)
    if parts == ["api", "options"]:
        return Route(m, "options", "", query)
    if parts == ["api", "jobs"]:
        # GET = list, POST = create — the handler dispatches on method.
        return Route(m, "jobs", "", query)
    if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs":
        return Route(m, "job", parts[2], query)
    if (len(parts) == 4 and parts[0] == "api" and parts[1] == "jobs"
            and parts[3] in ("result", "cancel", "pause", "resume",
                             "outputs")):
        return Route(m, parts[3], parts[2], query)
    # OpenAI-compatible surface (see the module docstring). The real API
    # lives under /v1, so tools configured with a .../v1 base URL hit these.
    if parts == ["v1", "models"]:
        return Route(m, "openai_models", "", query)
    if parts == ["v1", "audio", "transcriptions"]:
        return Route(m, "openai_transcriptions", "", query)
    return Route(m, "unknown", "", query)


def token_ok(expected: str, header_token: str | None,
             query_token: str | None) -> bool:
    """Auth gate. When no token is configured, every request passes.

    Otherwise the request must present the matching secret via the
    ``X-Auth-Token`` header OR the ``?token=`` query parameter. The compare
    is constant-time (``hmac.compare_digest``) so a remote client can't
    recover the token byte-by-byte via response-timing.
    """
    if not expected:
        return True
    # Compare as BYTES, not str: hmac.compare_digest raises TypeError on any
    # str operand carrying a non-ASCII code point. The candidate token is
    # fully attacker-controlled (?token= is percent-decoded by parse_qs, and
    # the X-Auth-Token header is latin-1-decoded by http.client), so a str
    # compare would let a remote client crash the handler with a non-ASCII
    # ?token=, and would lock out an operator who chose a non-Latin token.
    # Encoding both sides with the same codec preserves the constant-time
    # property for the realistic (matching) case.
    exp_b = expected.encode("utf-8")
    for candidate in (header_token, query_token):
        if candidate is None:
            continue
        cand_b = candidate.encode("utf-8", "ignore")
        if hmac.compare_digest(cand_b, exp_b):
            return True
    return False


def parse_multipart_filename(content_type: str | None) -> str:
    """Pull the multipart boundary's significance out of a Content-Type.

    Returns the boundary string for a multipart/form-data body, or "" when
    the content type is not multipart. Kept tiny + pure so the handler's
    decision ("is this an upload or a JSON body?") is testable.
    """
    if not content_type:
        return ""
    ctype = content_type.lower()
    if not ctype.startswith("multipart/form-data"):
        return ""
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return ""


def extract_upload(body: bytes, boundary: str) -> tuple[str, bytes,
                                                        dict[str, str]]:
    """Parse a multipart/form-data body into ``(filename, file_bytes, fields)``.

    A deliberately small parser for exactly the shape this server's own
    page sends: one ``file`` part plus optional plain ``formats`` /
    ``language`` text fields. Returns ``("", b"", fields)`` when no file
    part is present. Pure (no I/O) so it is unit-testable.
    """
    if not boundary:
        return "", b"", {}
    delim = b"--" + boundary.encode("latin-1")
    fields: dict[str, str] = {}
    filename = ""
    file_bytes = b""
    for chunk in body.split(delim):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        # Strip a single leading CRLF that follows the boundary line.
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head_end = chunk.find(b"\r\n\r\n")
        if head_end == -1:
            continue
        raw_headers = chunk[:head_end].decode("latin-1", "replace")
        value = chunk[head_end + 4:]
        # Trailing CRLF before the next boundary.
        if value.endswith(b"\r\n"):
            value = value[:-2]
        name = _header_param(raw_headers, "name")
        fname = _header_param(raw_headers, "filename")
        if fname:
            filename = fname
            file_bytes = value
        elif name:
            fields[name] = value.decode("utf-8", "replace")
    return filename, file_bytes, fields


class _UploadParts(NamedTuple):
    """Result of locating the parts in a multipart temp file (no payload copy).

    ``filename`` / ``file_start`` / ``file_end`` describe the byte range of the
    single ``file`` part's body inside the temp file (``file_start == -1`` when
    there is no file part). ``fields`` holds the small plain text parts.
    """

    filename: str
    file_start: int
    file_end: int
    fields: dict[str, str]


class _UploadError(Exception):
    """A multipart receive failure, carrying the HTTP status to reply with.

    Raised by :meth:`JobRequestHandler._receive_upload` so its two callers
    (the JSON job API and the OpenAI-compatible route) can each render the
    failure in their own error envelope.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _StreamedUpload(NamedTuple):
    """A multipart body streamed to a temp file, with its file part located.

    ``tmp_path`` is owned by the caller, which must delete it. The file part
    body lives at ``[file_start, file_end)`` inside that temp file.
    """

    tmp_path: str
    filename: str
    file_start: int
    file_end: int
    fields: dict[str, str]


def scan_multipart_file(data: bytes, boundary: str) -> _UploadParts:
    """Locate the ``file`` part's byte RANGE + text fields without copying it.

    A streaming-friendly companion to :func:`extract_upload`: instead of
    returning the file bytes (a second large allocation), it returns the
    ``[file_start, file_end)`` offsets of the file part's body within ``data``
    so the caller can copy that slice straight from the temp file to disk in
    fixed-size chunks. Text fields (small) are still decoded eagerly. Pure (no
    I/O) so it is unit-testable; the live path feeds it only the leading window
    of the temp file (large file payloads are never materialised in RAM).
    """
    if not boundary:
        return _UploadParts("", -1, -1, {})
    delim = b"--" + boundary.encode("latin-1")
    fields: dict[str, str] = {}
    filename = ""
    file_start = -1
    file_end = -1
    pos = 0
    n = len(data)
    while pos < n:
        nxt = data.find(delim, pos)
        if nxt == -1:
            break
        # The body of the part that ended at ``nxt`` ran from the previous
        # header block; we only need each part's own header + body, so walk
        # forward from just after this delimiter.
        seg_start = nxt + len(delim)
        # A trailing "--" marks the final boundary.
        if data[seg_start:seg_start + 2] == b"--":
            break
        # Skip the CRLF after the boundary line.
        if data[seg_start:seg_start + 2] == b"\r\n":
            seg_start += 2
        head_end = data.find(b"\r\n\r\n", seg_start)
        if head_end == -1:
            break
        raw_headers = data[seg_start:head_end].decode("latin-1", "replace")
        body_start = head_end + 4
        # The body ends just before the next delimiter (with its leading CRLF).
        body_delim = data.find(delim, body_start)
        if body_delim == -1:
            # Header parsed but the closing boundary is past the window we were
            # given; treat the body as open-ended to the window's end.
            body_end = n
            next_pos = n
        else:
            body_end = body_delim
            next_pos = body_delim
        # Strip the trailing CRLF that precedes the next boundary line.
        if data[body_end - 2:body_end] == b"\r\n":
            body_end -= 2
        name = _header_param(raw_headers, "name")
        fname = _header_param(raw_headers, "filename")
        if fname:
            filename = fname
            file_start = body_start
            file_end = body_end
        elif name:
            fields[name] = data[body_start:body_end].decode("utf-8", "replace")
        pos = next_pos
    return _UploadParts(filename, file_start, file_end, fields)


def _header_param(raw_headers: str, key: str) -> str:
    """Find ``key="value"`` inside a Content-Disposition header block."""
    needle = f'{key}="'
    for line in raw_headers.split("\r\n"):
        idx = line.find(needle)
        if idx == -1:
            continue
        rest = line[idx + len(needle):]
        end = rest.find('"')
        if end == -1:
            continue
        return rest[:end]
    return ""


def normalize_formats(raw: Any) -> list[str]:
    """Coerce a formats value (list, CSV string, or None) to known formats.

    Drops unknown names; falls back to ``["srt"]`` when nothing valid is
    left so a job always has at least one output to write.
    """
    available = set(supported_formats())
    items: list[str]
    if isinstance(raw, str):
        items = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        items = [str(p).strip() for p in raw]
    else:
        items = []
    out = [p.lower() for p in items if p and p.lower() in available]
    # Preserve order, de-dupe.
    seen: set[str] = set()
    deduped = [p for p in out if not (p in seen or seen.add(p))]
    return deduped or ["srt"]


# Curated language whitelist for the web UI, mirroring the desktop's
# ~26-language list (app.domain.languages.SUBTITLE_LANGUAGES) but expressed as
# the ISO codes Whisper accepts directly (core.transcriber._normalize_language
# would otherwise strip BCP-47 region/script suffixes). ``""`` = auto-detect.
# core stays Tk-free, so this is duplicated here rather than imported from app/.
WEB_LANGUAGE_CODES: tuple[str, ...] = (
    "", "en", "ar", "zh", "cs", "da", "nl", "fi", "fr", "de", "el", "he",
    "hi", "hu", "id", "it", "ja", "ko", "no", "fa", "pl", "pt", "ro", "ru",
    "es", "sv", "th", "tr", "uk", "vi",
)


def normalize_language(raw: Any) -> str:
    """Coerce a language hint to a whitelisted ISO code, or "" (auto-detect).

    Lower-cases, strips a BCP-47 region/script suffix (``en-US`` -> ``en``),
    and validates against :data:`WEB_LANGUAGE_CODES`. Unknown / blank values
    return "" so the job auto-detects rather than failing. Pure + testable.
    """
    if not isinstance(raw, str):
        return ""
    code = raw.strip().lower()
    if not code:
        return ""
    # Split a region/script suffix the way the engine's normaliser does.
    code = code.replace("_", "-").split("-", 1)[0]
    return code if code in WEB_LANGUAGE_CODES else ""


# Per-job options the web may set. Each entry is (key, kind) where kind drives
# the coercion in normalize_options. These mirror the desktop Advanced dialog /
# Transcribe-tab keys and are written into the per-job .whisperproject.json so
# the engine's per-folder override mechanism applies them to THAT job only.
#
# ``transcribe_backend`` is deliberately ABSENT: switching backend per job can
# trigger an alt-backend (re)load (a heavy, server-global side effect) and the
# cloud backends upload audio to third parties + need keys. Backend stays a
# server-level setting. ``clip_start`` / ``clip_end`` are handled separately
# (they map onto the _ServerTask attributes, not the override file).
_OPTION_SPEC: tuple[tuple[str, str], ...] = (
    ("vad_enabled", "bool"),
    ("vad_threshold", "float01"),
    ("vad_min_silence_ms", "int_nonneg"),
    ("word_timestamps", "bool"),
    ("diarization_enabled", "bool"),
    ("diarization_num_speakers", "int_speakers"),
    ("demucs_enabled", "bool"),
    ("hallucination_detect_enabled", "bool"),
    ("auto_chapters_enabled", "bool"),
)


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off", ""):
            return False
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    f = _coerce_float(value)
    # Reject non-finite floats. A client int option of 'inf' / 'nan' /
    # '1e400' parses to inf/nan here, and int(inf) raises OverflowError while
    # int(nan) raises ValueError — unhandled in the POST handler, that drops
    # the connection (RemoteDisconnected) instead of a clean 400. Returning
    # None lets normalize_options skip the option cleanly, mirroring the
    # float01 clamp that already neutralises inf/nan.
    if f is None or not math.isfinite(f):
        return None
    return int(f)


def normalize_options(raw: Any) -> dict[str, Any]:
    """Whitelist + type-coerce a raw options blob into a validated dict.

    PURE (no I/O). Whitelists exactly the keys in :data:`_OPTION_SPEC`,
    coerces each to the right type, drops unknown keys and any value that
    can't be coerced. The result is shaped to overlay DEFAULT_CONFIG, so
    writing it into a per-job ``.whisperproject.json`` passes
    ``core.config._validate_overrides`` cleanly. Mirrors the existing
    ``normalize_formats`` / ``parse_*`` seams so it is unit-testable without
    a socket.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, kind in _OPTION_SPEC:
        if key not in raw:
            continue
        value = raw[key]
        if kind == "bool":
            coerced: Any = _coerce_bool(value)
        elif kind == "float01":
            f = _coerce_float(value)
            coerced = None if f is None else max(0.0, min(1.0, f))
        elif kind == "int_nonneg":
            i = _coerce_int(value)
            coerced = None if i is None else max(0, i)
        elif kind == "int_speakers":
            # -1 = auto-cluster (the engine's sentinel); otherwise >= 1.
            i = _coerce_int(value)
            if i is None:
                coerced = None
            else:
                coerced = -1 if i < 1 else i
        else:  # pragma: no cover - guarded by the static spec
            coerced = None
        if coerced is not None:
            out[key] = coerced
    return out


def parse_clip(raw_start: Any, raw_end: Any) -> tuple[float | None, float | None]:
    """Validate a clip window into ``(clip_start, clip_end)`` seconds.

    Either may be ``None`` (omit that bound). A non-positive start is treated
    as no start; an end at/<= the start is dropped (no valid window). Pure.
    """
    start = _coerce_float(raw_start)
    end = _coerce_float(raw_end)
    if start is not None and start <= 0.0:
        start = None
    if end is not None and end <= 0.0:
        end = None
    if start is not None and end is not None and end <= start:
        end = None
    return start, end


# --- OpenAI-compatible response helpers (pure, unit-testable) ----------------

def openai_error_payload(
    message: str,
    *,
    err_type: str = "invalid_request_error",
    param: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """The ``{"error": {message, type, param, code}}`` envelope OpenAI
    clients (and the official SDKs) parse on a failed request."""
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        },
    }


def openai_full_text(segments: list[dict[str, Any]]) -> str:
    """The concatenated transcript text the ``json`` / ``text`` responses use."""
    parts = [str(seg.get("text") or "").strip() for seg in segments]
    return " ".join(p for p in parts if p).strip()


def openai_verbose_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map our segment dicts onto OpenAI's ``TranscriptionSegment`` shape.

    Every field the SDK type declares is present. Our engine does not expose
    per-segment logprobs / token ids, so those fields carry neutral values
    (0.0 / empty list) rather than being omitted — a client that types the
    response with the official SDK requires the keys to exist.
    """
    out: list[dict[str, Any]] = []
    for index, seg in enumerate(segments):
        start = _coerce_float(seg.get("start"))
        end = _coerce_float(seg.get("end"))
        start = start if start is not None else 0.0
        end = end if end is not None else start
        out.append({
            "id": index,
            # whisper's own seek unit is a 10 ms frame; centiseconds keeps
            # the field in the same spirit for consumers that display it.
            "seek": int(round(start * 100)),
            "start": start,
            "end": end,
            "text": str(seg.get("text") or ""),
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": 0.0,
            "compression_ratio": 0.0,
            "no_speech_prob": 0.0,
        })
    return out


def openai_verbose_words(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten per-segment ``words`` onto OpenAI's ``TranscriptionWord`` shape."""
    words: list[dict[str, Any]] = []
    for seg in segments:
        for word in seg.get("words") or []:
            if not isinstance(word, dict):
                continue
            start = _coerce_float(word.get("start"))
            end = _coerce_float(word.get("end"))
            start = start if start is not None else 0.0
            end = end if end is not None else start
            words.append({
                "word": str(word.get("word") or ""),
                "start": start,
                "end": end,
            })
    return words


def build_openai_verbose_json(
    segments: list[dict[str, Any]], *, language: str = "",
) -> dict[str, Any]:
    """Build the ``verbose_json`` response from our segment list.

    ``language`` is the engine's detected ISO code (e.g. ``en``); the real
    API returns an English name (e.g. ``english``), but the field is free
    text and a code is the honest value this server actually knows.
    """
    duration = 0.0
    for seg in segments:
        end = _coerce_float(seg.get("end"))
        if end is not None and end > duration:
            duration = end
    payload: dict[str, Any] = {
        "task": "transcribe",
        "language": language,
        "duration": duration,
        "text": openai_full_text(segments),
        "segments": openai_verbose_segments(segments),
        "usage": {"type": "duration", "seconds": int(round(duration))},
    }
    words = openai_verbose_words(segments)
    if words:
        payload["words"] = words
    return payload


# --- the HTTP server ---------------------------------------------------------

class JobHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the shared JobManager + auth token."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int],
                 manager: JobManager, *, token: str = "",
                 max_upload_mb: int = 512,
                 ssl_context: ssl.SSLContext | None = None) -> None:
        self.manager = manager
        self.token = token
        self.max_upload_bytes = (
            min(max(1, max_upload_mb), _ABSOLUTE_MAX_UPLOAD_MB) * 1024 * 1024
        )
        super().__init__(server_address, JobRequestHandler)
        if ssl_context is not None:
            # Wrap the listening socket before serve_forever runs, so every
            # accepted connection is TLS from the first byte.
            self.socket = ssl_context.wrap_socket(self.socket, server_side=True)


class JobRequestHandler(BaseHTTPRequestHandler):
    """Typed request handler dispatching the small JSON API + static page."""

    server_version = "WhisperTranscriberSuiteServer/" + __version__
    protocol_version = "HTTP/1.1"

    # narrow the loosely-typed server attr for the type checker
    @property
    def _srv(self) -> JobHTTPServer:
        srv = self.server
        assert isinstance(srv, JobHTTPServer)
        return srv

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.info("%s - %s", self.address_string(), format % args)

    # --- shared helpers ------------------------------------------------------

    def _route(self) -> Route:
        return parse_route(self.command, self.path)

    def _bearer_token(self) -> str | None:
        """The OpenAI-style ``Authorization: Bearer <token>`` value, if any.

        Tools that treat this server as a drop-in OpenAI STT backend put
        their API key in this header; accepting it (as an alternative to
        ``X-Auth-Token``) is what lets them authenticate at all.
        """
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[len("bearer "):].strip()
        return None

    def _authed(self, route: Route) -> bool:
        return token_ok(
            self._srv.token,
            self.headers.get("X-Auth-Token") or self._bearer_token(),
            route.query.get("token"),
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _send_json_close(self, status: int, payload: dict[str, Any]) -> None:
        """Send a JSON body and close the connection.

        Used when we reject a request WITHOUT consuming its body (the
        oversized-upload path). Under HTTP/1.1 keep-alive an unread body
        desyncs the connection, so the next read would mangle the client's
        bytes — close instead of trying to keep the socket alive.
        """
        body = json.dumps(payload).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json_close(self, status: int, message: str) -> None:
        self._send_json_close(status, {"error": message})

    def _send_openai_error(
        self,
        status: int,
        message: str,
        *,
        err_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        self._send_json(status, openai_error_payload(
            message, err_type=err_type, param=param, code=code))

    def _send_openai_error_close(
        self,
        status: int,
        message: str,
        *,
        err_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        self._send_json_close(status, openai_error_payload(
            message, err_type=err_type, param=param, code=code))

    def _send_body(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- GET -----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = self._route()
        if route.name == "root":
            self._serve_index()
            return
        if not self._authed(route):
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "auth required")
            return
        if route.name == "health":
            self._send_json(HTTPStatus.OK, {
                "status": "ok",
                "version": __version__,
                "formats": supported_formats(),
            })
        elif route.name == "formats":
            self._send_json(HTTPStatus.OK, {"formats": supported_formats()})
        elif route.name == "options":
            self._send_json(HTTPStatus.OK, self._options_payload())
        elif route.name == "openai_models":
            self._send_json(HTTPStatus.OK, self._openai_models_payload())
        elif route.name == "jobs":
            # GET /api/jobs -> the live job list.
            self._send_json(HTTPStatus.OK,
                            {"jobs": self._srv.manager.list()})
        elif route.name == "job":
            job = self._srv.manager.get(route.job_id)
            if job is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "no such job")
            else:
                self._send_json(HTTPStatus.OK, job.public_dict())
        elif route.name == "outputs":
            job = self._srv.manager.get(route.job_id)
            if job is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "no such job")
            else:
                self._send_json(HTTPStatus.OK, {
                    "job_id": job.job_id,
                    "outputs": [{"fmt": fmt, "name": os.path.basename(p)}
                                for fmt, p in job.outputs],
                })
        elif route.name == "result":
            self._serve_result(route)
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def _options_payload(self) -> dict[str, Any]:
        """Describe formats, languages, and available backends for the page.

        Backend availability is probed cheaply (no model load); diarization
        availability gates whether the page offers the "Identify speakers"
        toggle. Defensive: any probe failure degrades to "unavailable".
        """
        try:
            from core import diarization as _diar
            diar_available = bool(_diar.is_available())
        except Exception:  # noqa: BLE001
            diar_available = False
        return {
            "formats": supported_formats(),
            "languages": list(WEB_LANGUAGE_CODES),
            "diarization_available": diar_available,
            # Backend is a server-level setting and NOT switchable per job
            # over the web (cloud engines need keys + upload audio; an
            # alt-backend switch is a heavy server-global reload).
            "backend_switchable": False,
        }

    def _serve_index(self) -> None:
        path = os.path.join(_STATIC_DIR, "index.html")
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "index missing")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_result(self, route: Route) -> None:
        fmt = route.query.get("fmt", "")
        if not fmt:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "fmt required")
            return
        path = self._srv.manager.output_path(route.job_id, fmt)
        if not path or not os.path.isfile(path):
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such output")
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "output unreadable")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition",
            content_disposition_attachment(os.path.basename(path)),
        )
        self.end_headers()
        self.wfile.write(body)

    # --- POST ----------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        route = self._route()
        if not self._authed(route):
            # Drain the declared body before replying. Under HTTP/1.1
            # keep-alive an unread request body desyncs the connection —
            # the next request would read this body's leftover bytes. We
            # send Connection: close as a belt-and-braces guard too.
            if route.name == "openai_transcriptions":
                self._reject_openai_post_early(
                    HTTPStatus.UNAUTHORIZED, "Incorrect API key provided.",
                    code="invalid_api_key")
            else:
                self._reject_post_early(
                    HTTPStatus.UNAUTHORIZED, "auth required")
            return
        if route.name == "jobs":
            self._create_job()
        elif route.name == "openai_transcriptions":
            self._openai_transcribe()
        elif route.name == "cancel":
            self._drain_declared_body()
            ok = self._srv.manager.cancel(route.job_id)
            if ok:
                self._send_json(HTTPStatus.OK, {"cancelled": route.job_id})
            else:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND, "no such active job")
        elif route.name == "pause":
            self._drain_declared_body()
            ok = self._srv.manager.pause(route.job_id)
            if ok:
                self._send_json(HTTPStatus.OK, {"paused": route.job_id})
            else:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND, "no such active job")
        elif route.name == "resume":
            self._drain_declared_body()
            ok = self._srv.manager.resume(route.job_id)
            if ok:
                self._send_json(HTTPStatus.OK, {"resumed": route.job_id})
            else:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND, "no such active job")
        else:
            self._reject_post_early(HTTPStatus.NOT_FOUND, "not found")

    def _declared_length(self) -> int:
        """The non-negative Content-Length, or 0 when absent / malformed."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return 0
        return length if length > 0 else 0

    def _drain_declared_body(self) -> None:
        """Consume the request body for a control POST that carries one.

        cancel/pause/resume take no body, but a client may still send one
        (or a stray Content-Length); draining keeps keep-alive in sync.
        """
        length = self._declared_length()
        if length:
            self._drain_body(length)

    def _reject_post_early(self, status: int, message: str) -> None:
        """Reject a POST before reading its body, keeping HTTP/1.1 in sync.

        Drains the declared Content-Length, then replies with
        Connection: close. Without the drain, the unread body would desync
        a keep-alive connection (the historical 401-on-POST bug).
        """
        length = self._declared_length()
        if length:
            if length > self._srv.max_upload_bytes:
                # Don't read an oversized body just to discard it on an early
                # reject — close immediately instead.
                self._send_error_json_close(status, message)
                return
            self._drain_body(length)
        self._send_error_json_close(status, message)

    def _reject_openai_post_early(
        self,
        status: int,
        message: str,
        *,
        err_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        """OpenAI-envelope twin of :meth:`_reject_post_early`."""
        length = self._declared_length()
        if length:
            if length > self._srv.max_upload_bytes:
                self._send_openai_error_close(
                    status, message, err_type=err_type, param=param, code=code)
                return
            self._drain_body(length)
        self._send_openai_error_close(
            status, message, err_type=err_type, param=param, code=code)

    def _read_body(self) -> bytes | None:
        """Read the request body, enforcing the max-upload cap.

        Returns ``None`` after sending a 413 when the declared length
        exceeds the cap (the worker's 1 MB JSON guard does NOT cover
        uploads, so this is the only size gate on the upload path).
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        if length < 0:
            self._send_error_json_close(HTTPStatus.BAD_REQUEST, "bad length")
            return None
        if length > self._srv.max_upload_bytes:
            # Drain + discard the oversized body in bounded chunks before
            # replying, so the client finishes sending and reliably reads
            # the 413 (an immediate close races the still-uploading client
            # into a connection-reset on Windows). We never buffer it.
            self._drain_body(length)
            self._send_error_json_close(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"upload exceeds {self._srv.max_upload_bytes // (1024 * 1024)} MB cap",
            )
            return None
        return self.rfile.read(length) if length else b""

    def _read_json_body(self) -> bytes | None:
        """Read a small JSON / control body, capped well below the upload cap.

        The JSON control path (``POST /api/jobs`` with a ``{"url": ...}`` body)
        is a few hundred bytes; without a dedicated cap it would buffer a body
        as large as the multimedia upload cap (default 512 MB, up to 4096 MB)
        — a memory-amplification DoS with no media file even involved. Reject
        anything over :data:`_MAX_JSON_BODY_BYTES` with a 413, draining the
        declared body first so HTTP/1.1 keep-alive stays in sync.
        """
        length = self._declared_length()
        if length > _MAX_JSON_BODY_BYTES:
            self._drain_body(length)
            self._send_error_json_close(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"request body exceeds "
                f"{_MAX_JSON_BODY_BYTES // (1024 * 1024)} MB cap",
            )
            return None
        return self.rfile.read(length) if length else b""

    def _drain_body(self, length: int) -> None:
        """Read + discard ``length`` bytes from the request body in chunks.

        Used on the reject path so an oversized upload is consumed (never
        buffered whole) and the client can read our response instead of
        hitting a mid-upload connection reset.
        """
        remaining = length
        chunk = 64 * 1024
        try:
            while remaining > 0:
                buf = self.rfile.read(min(chunk, remaining))
                if not buf:
                    break
                remaining -= len(buf)
        except OSError:
            pass

    def _create_job(self) -> None:
        ctype = self.headers.get("Content-Type", "")
        boundary = parse_multipart_filename(ctype)
        if boundary:
            self._create_upload_job(boundary)
        else:
            self._create_url_job()

    def _options_from(self, getter: Any) -> tuple[dict[str, Any], float | None,
                                                  float | None]:
        """Build (options, clip_start, clip_end) from a raw-field getter.

        ``getter`` maps a key to its raw value (JSON dict or multipart fields).
        Validated through the pure ``normalize_options`` / ``parse_clip``
        seams so the caller never touches raw client data directly.
        """
        raw_opts = {key: getter(key) for key, _ in _OPTION_SPEC
                    if getter(key) is not None}
        options = normalize_options(raw_opts)
        clip_start, clip_end = parse_clip(getter("clip_start"),
                                          getter("clip_end"))
        return options, clip_start, clip_end

    def _receive_upload(self, boundary: str) -> _StreamedUpload:
        """Stream a multipart body to a temp file and locate its file part.

        Reads the raw body in 64 KB chunks, enforcing the upload cap against
        Content-Length, then locates the single ``file`` part's byte RANGE
        (from a bounded leading + trailing window — never the whole body).
        The payload is therefore never materialised in RAM (the old
        whole-body ``read()`` + ``extract_upload`` copy buffered it ~twice);
        ``extract_upload`` itself is retained only as the PURE unit-test seam.

        Raises :class:`_UploadError` (already drained/cleaned up) on any
        failure; on success the caller owns ``tmp_path`` and must delete it.
        """
        import tempfile

        length = self._declared_length()
        if length > self._srv.max_upload_bytes:
            self._drain_body(length)
            raise _UploadError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"upload exceeds "
                f"{self._srv.max_upload_bytes // (1024 * 1024)} MB cap",
            )

        fd, tmp_path = tempfile.mkstemp(prefix="upload-", suffix=".part")
        written = 0
        try:
            with os.fdopen(fd, "wb") as out:
                remaining = length
                chunk = 64 * 1024
                while remaining > 0:
                    buf = self.rfile.read(min(chunk, remaining))
                    if not buf:
                        break
                    out.write(buf)
                    written += len(buf)
                    remaining -= len(buf)
            # Hard cap guard even when Content-Length lied about the size.
            if written > self._srv.max_upload_bytes:
                raise _UploadError(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "upload too large")
            filename, file_start, file_end, fields = (
                self._extract_upload_from_file(tmp_path, written, boundary))
        except OSError as e:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise _UploadError(
                HTTPStatus.BAD_REQUEST, f"could not read upload: {e}") from e
        except _UploadError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return _StreamedUpload(
            tmp_path, filename, file_start, file_end, fields)

    def _create_upload_job(self, boundary: str) -> None:
        """Create a job from a streamed multipart upload.

        The payload is streamed disk-to-disk (see :meth:`_receive_upload`)
        and only the file part's byte range is copied into the per-job dir.
        """
        try:
            upload = self._receive_upload(boundary)
        except _UploadError as e:
            self._send_error_json_close(e.status, e.message)
            return
        manager = self._srv.manager
        try:
            if (not upload.filename or upload.file_start < 0
                    or upload.file_end <= upload.file_start):
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST, "no file part in upload")
                return
            formats = normalize_formats(upload.fields.get("formats"))
            language = normalize_language(upload.fields.get("language", ""))
            options, clip_start, clip_end = self._options_from(
                upload.fields.get)
            try:
                job_id, media_path = manager.submit_upload_stream(
                    upload.filename, formats, language, options=options,
                    clip_start=clip_start, clip_end=clip_end)
            except QueueFull as e:
                self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, str(e))
                return
            except ValueError as e:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(e))
                return
            try:
                # Copy just the file part's byte range from the temp file to
                # its final per-job location, in fixed-size chunks — the
                # payload never sits whole in RAM.
                self._copy_range(
                    upload.tmp_path, media_path,
                    upload.file_start, upload.file_end)
            except OSError as e:
                manager.discard(job_id)
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                      f"could not save upload: {e}")
                return
            manager.enqueue_upload(job_id)
            self._send_json(HTTPStatus.ACCEPTED, {"job_id": job_id})
        finally:
            try:
                os.unlink(upload.tmp_path)
            except OSError:
                pass

    @staticmethod
    def _extract_upload_from_file(
        tmp_path: str, size: int, boundary: str,
    ) -> tuple[str, int, int, dict[str, str]]:
        """Locate the file part's ``[start, end)`` range + text fields on disk.

        Reads only a bounded leading window (headers + the file part's header)
        and a bounded trailing window (the closing boundary + any text parts
        placed after the file) of the temp file — never the payload. Returns
        ``(filename, file_start, file_end, fields)`` with ``file_start == -1``
        when no file part is present.

        The server's own page (and a browser ``FormData`` in general) sends the
        ``file`` part FIRST and the small ``formats`` / ``language`` / option
        text fields AFTER it, so for any real (multi-MB) upload those fields lie
        BEYOND the leading window. We therefore scan the trailing window not
        just for the file part's true end but for those after-file text fields
        too, merging them with anything the leading window already yielded. The
        file's true end is the FIRST delimiter after its body start (the one
        closing the file part) — using the LAST delimiter would swallow the
        trailing text-field parts into the saved media as junk bytes.
        """
        delim = b"--" + boundary.encode("latin-1")
        with open(tmp_path, "rb") as f:
            head = f.read(min(size, _MULTIPART_HEADER_WINDOW))
            parts = scan_multipart_file(head, boundary)
            file_start = parts.file_start
            file_end = parts.file_end
            fields = dict(parts.fields)
            if file_start < 0:
                return "", -1, -1, fields
            # Whenever the whole body did NOT fit the leading window, the small
            # after-file text fields (formats / language / options the server's
            # page appends AFTER the file part) may lie beyond it — and so may
            # the file part's true end. Read a bounded tail window to recover
            # BOTH without buffering the payload. The field recovery must run
            # even when file_end was located inside the head window: the file's
            # closing boundary can fit the window while the trailing fields
            # spill past it, and gating the recovery on file_end-past-the-window
            # would silently drop those fields (-> [srt] + auto fallback).
            if len(head) < size:
                tail_len = min(size, _MULTIPART_TAIL_WINDOW)
                # Never read back past the file part's start, so we don't
                # buffer the payload; otherwise overlap a delimiter that may
                # straddle the window boundary by reading the trailing window.
                tail_start = max(file_start, size - tail_len)
                f.seek(tail_start)
                tail = f.read(size - tail_start)
                # The file part's body ends at the FIRST delimiter after its
                # start, NOT the last: any text-field parts sit between that
                # first delimiter and the closing boundary, and must not be
                # copied into the media file.
                idx = tail.find(delim)
                if idx == -1:
                    # No delimiter in the tail: only re-resolve the end if it
                    # was still pinned at the window edge (the closing boundary
                    # lay past both windows). An end already found inside the
                    # head window is correct and stays put.
                    if file_end >= len(head):
                        file_end = size
                else:
                    end = tail_start + idx
                    # Strip the CRLF that precedes the boundary line.
                    if tail[idx - 2:idx] == b"\r\n":
                        end -= 2
                    # Only adopt the tail's end when the head scan left file_end
                    # pinned at the window edge; an end already resolved inside
                    # the head window is authoritative and must not move.
                    if file_end >= len(head):
                        file_end = end
                    # Re-scan the tail from the file part's closing delimiter so
                    # the after-file text fields (formats/language/options) are
                    # recovered. Leading-window fields, if any, take precedence.
                    tail_parts = scan_multipart_file(tail[idx:], boundary)
                    for key, val in tail_parts.fields.items():
                        fields.setdefault(key, val)
            return parts.filename, file_start, file_end, fields

    @staticmethod
    def _copy_range(src_path: str, dst_path: str, start: int, end: int) -> None:
        """Copy bytes ``[start, end)`` from ``src_path`` to ``dst_path``.

        Fixed-size chunks via ``shutil.copyfileobj``-style loop, so a multi-GB
        file part is streamed disk-to-disk without a large RAM allocation.
        """
        remaining = max(0, end - start)
        chunk = 1024 * 1024
        with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
            src.seek(start)
            while remaining > 0:
                buf = src.read(min(chunk, remaining))
                if not buf:
                    break
                dst.write(buf)
                remaining -= len(buf)

    def _create_url_job(self) -> None:
        body = self._read_json_body()
        if body is None:
            return  # error already sent (JSON cap exceeded)
        manager = self._srv.manager
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON body")
            return
        if not isinstance(data, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "JSON object expected")
            return
        url = str(data.get("url", "")).strip()
        if not url:
            self._send_error_json(
                HTTPStatus.BAD_REQUEST, "provide a file upload or a JSON url")
            return
        formats = normalize_formats(data.get("formats"))
        language = normalize_language(data.get("language", ""))
        options, clip_start, clip_end = self._options_from(data.get)
        try:
            job_id = manager.submit_url(
                url, formats, language, options=options,
                clip_start=clip_start, clip_end=clip_end)
        except ValueError as e:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(e))
            return
        except QueueFull as e:
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, str(e))
            return
        self._send_json(HTTPStatus.ACCEPTED, {"job_id": job_id})

    # --- OpenAI-compatible surface -------------------------------------------

    def _openai_models_payload(self) -> dict[str, Any]:
        """A one-entry model list so OpenAI clients can validate the backend.

        ``whisper-1`` is the real API's STT model id. The server ignores the
        requested model (the engine/model is a server-level setting) but
        clients insist on selecting one from this list.
        """
        return {
            "object": "list",
            "data": [{
                "id": "whisper-1",
                "object": "model",
                "created": 0,
                "owned_by": "whisper-transcriber-suite",
            }],
        }

    def _openai_transcribe(self) -> None:
        """POST /v1/audio/transcriptions — synchronous, OpenAI-shaped.

        Streams the multipart upload into the normal job queue, then waits
        for the single worker to finish and renders the transcript in the
        requested ``response_format``. Blocking here is deliberate: the
        OpenAI contract is request/response, and the manager still runs one
        transcription at a time. ThreadingHTTPServer serves other clients
        meanwhile.
        """
        boundary = parse_multipart_filename(
            self.headers.get("Content-Type", ""))
        if not boundary:
            self._reject_openai_post_early(
                HTTPStatus.BAD_REQUEST,
                "Expected multipart/form-data with a 'file' field.",
                param="file")
            return
        try:
            upload = self._receive_upload(boundary)
        except _UploadError as e:
            self._send_openai_error_close(e.status, e.message)
            return
        try:
            self._openai_handle_upload(upload)
        finally:
            try:
                os.unlink(upload.tmp_path)
            except OSError:
                pass

    def _openai_handle_upload(self, upload: _StreamedUpload) -> None:
        """Validate the OpenAI fields, run the job, and send the response."""
        if (not upload.filename or upload.file_start < 0
                or upload.file_end <= upload.file_start):
            self._send_openai_error(
                HTTPStatus.BAD_REQUEST,
                "Invalid file: no file part in the upload.", param="file")
            return
        fields = upload.fields
        model = str(fields.get("model") or "").strip()
        if not model:
            # Matches the real API, which rejects a missing model.
            self._send_openai_error(
                HTTPStatus.BAD_REQUEST,
                "You must provide a model parameter.", param="model")
            return
        response_format = str(
            fields.get("response_format") or "json").strip().lower()
        if response_format not in OPENAI_RESPONSE_FORMATS:
            self._send_openai_error(
                HTTPStatus.BAD_REQUEST,
                f"Invalid response_format '{response_format}'. Supported "
                "formats: " + ", ".join(OPENAI_RESPONSE_FORMATS) + ".",
                param="response_format")
            return
        # ``prompt`` / ``temperature`` / ``timestamp_granularities[]`` are
        # accepted but ignored — the engine's own settings decide those.
        language = normalize_language(fields.get("language", ""))
        manager = self._srv.manager
        try:
            job_id, media_path = manager.submit_upload_stream(
                upload.filename, ["json"], language)
        except QueueFull as e:
            self._send_openai_error(
                HTTPStatus.SERVICE_UNAVAILABLE, str(e),
                err_type="server_error")
            return
        except ValueError as e:
            self._send_openai_error(
                HTTPStatus.BAD_REQUEST, str(e), param="file")
            return
        try:
            self._copy_range(upload.tmp_path, media_path,
                             upload.file_start, upload.file_end)
        except OSError as e:
            manager.discard(job_id)
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"could not save upload: {e}", err_type="server_error")
            return
        manager.enqueue_upload(job_id)
        job = manager.get(job_id)
        if job is None:  # pragma: no cover - just registered
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR, "job disappeared",
                err_type="server_error")
            return
        job = self._wait_for_job(job)
        if job is None:
            self._send_openai_error(
                HTTPStatus.SERVICE_UNAVAILABLE, "server is shutting down",
                err_type="server_error")
            return
        if job.status == STATUS_CANCELLED:
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "transcription was cancelled", err_type="server_error")
            return
        if job.status == STATUS_ERROR:
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                job.error or "transcription failed", err_type="server_error")
            return
        self._openai_send_result(job, response_format)

    def _wait_for_job(self, job: Job) -> Job | None:
        """Block until ``job`` is terminal, or the server stops.

        Returns the job, or ``None`` when the manager was stopped first
        (in-process GUI stop / CLI shutdown) so the caller can answer 503
        instead of hanging forever. The Job object reference is kept rather
        than re-looking it up, so terminal-job eviction can't race us.
        """
        manager = self._srv.manager
        while True:
            if job.status in (STATUS_FINISHED, STATUS_ERROR, STATUS_CANCELLED):
                return job
            if manager.stopped:
                return None
            time.sleep(_OPENAI_POLL_INTERVAL_S)

    def _openai_send_result(self, job: Job, response_format: str) -> None:
        """Read the job's JSON sidecar and render the requested format."""
        path = self._srv.manager.output_path(job.job_id, "json")
        if not path or not os.path.isfile(path):
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "transcription produced no JSON output",
                err_type="server_error")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                segments = json.load(f)
        except (OSError, ValueError) as e:
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"could not read the transcript: {e}",
                err_type="server_error")
            return
        if not isinstance(segments, list):
            self._send_openai_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "transcript output has an unexpected shape",
                err_type="server_error")
            return
        language = job.detected_language or job.language
        if response_format == "text":
            body = openai_full_text(segments).encode("utf-8")
            self._send_body(HTTPStatus.OK, body, "text/plain; charset=utf-8")
            return
        if response_format in ("srt", "vtt"):
            try:
                text = get_writer(response_format)(segments, "")
            except (KeyError, TypeError, ValueError) as e:
                self._send_openai_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"could not render the transcript: {e}",
                    err_type="server_error")
                return
            self._send_body(
                HTTPStatus.OK, text.encode("utf-8"),
                "text/plain; charset=utf-8")
            return
        if response_format == "verbose_json":
            self._send_json(HTTPStatus.OK, build_openai_verbose_json(
                segments, language=language))
            return
        self._send_json(
            HTTPStatus.OK, {"text": openai_full_text(segments)})
