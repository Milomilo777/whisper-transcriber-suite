"""Optional cloud Speech-to-Text backend via the Google Gemini API.

This backend uploads audio to Google and transcribes it with a Gemini
multimodal model. It is **opt-in** and breaks the project's "everything
stays on this machine" guarantee — the audio leaves the device. The UI
makes that trade-off loud; this module just implements the transport.

Why the Gemini API and NOT Google Cloud Speech-to-Text
-------------------------------------------------------
Google *Cloud* Speech-to-Text (the ``speech.googleapis.com`` v2 service)
does **not** authenticate with a simple pasted API key — it needs a GCP
project plus a service-account / OAuth JSON credential. That defeats the
goal of "the user pastes a key from a web page and it just works", so we
do not target it.

The only Google speech path that works with a *bare pasted key* (the kind
you copy from https://aistudio.google.com/apikey) is the **Gemini API**
on ``generativelanguage.googleapis.com`` with ``?key=<API_KEY>``. So this
backend targets the Gemini ``generateContent`` audio-understanding flow
and asks the model to produce a verbatim, timestamped transcript.

On the "$300 / 90-day free credit"
-----------------------------------
That credit balance is a Cloud Billing concept and is **not readable from
an API key** (the Cloud Billing API needs OAuth / a service account). So
this backend does NOT display a live "$300 remaining" figure. Instead it
tracks *minutes transcribed* locally (``cloud_stt_minutes_used`` in
config) and the UI links to Google's billing console. The local counter
is an estimate of usage, not an authoritative balance.

Verified request shape (Google AI / Gemini API docs, fetched 2026-06-06)
------------------------------------------------------------------------
* generateContent endpoint + API-key query param, inline base64 ``parts``,
  the 20 MB inline limit, and the ``file_data``/``file_uri`` reference:
  https://ai.google.dev/gemini-api/docs/audio
* Files API resumable upload (``X-Goog-Upload-*`` headers) + polling the
  uploaded file until ``state == "ACTIVE"``:
  https://ai.google.dev/gemini-api/docs/files
* Current model list — ``gemini-2.0-flash`` was shut down 2026-06-01;
  ``gemini-3.5-flash`` is the current GA flash model (released
  2026-05-19) and the default here:
  https://ai.google.dev/gemini-api/docs/models
  https://ai.google.dev/gemini-api/docs/changelog

Because we chunk the audio (~8 min windows) each chunk usually exceeds the
20 MB *inline* request cap once decoded, so the Files API upload path is
the default. ``_should_inline`` keeps the inline path available for very
small chunks / future tuning.

No new third-party dependency: every HTTP call uses ``urllib.request``
from the stdlib (mirroring ``core/backends/whisper_cpp.py``'s download
style). Audio is decoded + chunked to FLAC with the bundled ffmpeg.
"""
from __future__ import annotations

import json
import logging
import os
import re
import http.client
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .._liveness_tick import liveness_tick
from ..config import load_config
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants

API_HOST = "https://generativelanguage.googleapis.com"
API_VERSION = "v1beta"
#: Gemini accepts the API key either as a ``?key=`` query param or in this
#: request header. We use the HEADER so the secret never lands in urllib
#: exception text, server access logs, HTTP redirects, or proxy logs (a URL
#: query string is logged everywhere; a header is not). Same value, safer
#: transport. (https://ai.google.dev/gemini-api/docs/api-key)
API_KEY_HEADER = "x-goog-api-key"
#: Default model. A CONFIG value (``cloud_stt_model``) overrides it so a
#: renamed / newer model needs no code change. See module docstring for
#: why this is the current GA flash model.
DEFAULT_MODEL = "gemini-3.5-flash"
#: The Gemini inline-request hard cap is 20 MB *including* the prompt. Inline
#: audio is base64-encoded in the JSON body, which inflates the RAW bytes by
#: ~4/3, so the limit MUST be derived from the *post-base64* size, not the raw
#: FLAC size. We size the raw-byte ceiling so that ceil(raw * 4 / 3) plus a
#: 64 KiB headroom for the prompt + JSON envelope stays comfortably under
#: 20 MB; anything larger goes through the Files API. (A raw ceiling of 18 MiB
#: used to slip ~24 MiB of base64 into the body, which Google rejects HTTP 400.)
INLINE_LIMIT_BYTES = int((20 * 1024 * 1024 - 64 * 1024) * 3 / 4)
#: How long to wait for an uploaded file to reach state ACTIVE.
FILE_ACTIVE_TIMEOUT_S = 120.0
#: Per-request network timeout for the generateContent call.
GENERATE_TIMEOUT_S = 600.0
#: Hard ceiling on one ffmpeg FLAC-encode call. A source file on a
#: disconnected network share (or any blocking-device scenario) can make
#: ffmpeg block in open/read forever, and nothing else in this module's
#: liveness/timeout wiring covers the encode step (only the HTTP calls are
#: bounded). The duration probe next door is bounded for the same reason;
#: this is generous enough for a slow machine to decode a whole multi-hour
#: file (batch mode) while still guaranteeing a wedged ffmpeg cannot hang
#: the worker forever.
ENCODE_TIMEOUT_S = 1800.0

#: FLAC is lossless, far smaller than WAV, and a Gemini-supported mime.
CHUNK_MIME = "audio/flac"
CHUNK_EXT = ".flac"

#: When the duration cannot be determined (corrupt header, streamed source,
#: ffprobe missing), the chunk planner must STILL slice into fixed-size windows
#: rather than send the whole file as one request — a long file transcribed in
#: one shot hits Gemini's output-token limit (the bulk of the transcript is
#: lost / the run errors out). We plan this many back-to-back ``chunk_seconds``
#: windows; the ffmpeg ``-ss/-t`` slicer naturally returns empty FLAC for
#: windows past EOF (-> stops early), so the bound just caps wasted requests on
#: a genuinely unknown-length file. 120 * 480 s ~= 16 h, longer than any
#: realistic input. (Mirrors google_cloud_stt.MAX_UNKNOWN_DURATION_CHUNKS.)
#: Reaching this cap costs real money, so the caller refuses the plan up front
#: when ffprobe (the only reliable EOF signal) does not work, and the in-loop
#: EOF test fails closed — a dead probe stops the run instead of trusting the
#: cap.
MAX_UNKNOWN_DURATION_CHUNKS = 120

#: A cheap lower bound for "obviously no audio in this slice". NOTE: this is
#: NOT the reliable past-EOF test — ffmpeg writes a complete FLAC container
#: (streaminfo + VORBIS_COMMENT + padding, measured ~8 KiB) even for a slice
#: that starts past the end of the file, which is well ABOVE this value. The
#: byte check remains as a fast first cut; ``probe_flac_slice`` (an ffprobe
#: duration probe) is what actually detects EOF.
_EMPTY_FLAC_BYTES = 4096

#: The transcription instruction. Asks for strict verbatim output with
#: per-line timestamps we can parse back into segments. Kept terse so the
#: model spends its budget transcribing, not narrating.
_PROMPT_TEMPLATE = (
    "Transcribe this audio VERBATIM. Output ONLY the transcript, no "
    "preamble, no commentary, no markdown fences. Use one line per "
    "utterance in EXACTLY this format:\n"
    "[HH:MM:SS.mmm --> HH:MM:SS.mmm] text\n"
    "Timestamps are relative to the START of THIS audio clip. Do not "
    "translate; transcribe in the spoken language.{lang_hint}"
)


# ---------------------------------------------------------------- pure seams
# Everything in this block is network-free and unit-testable.


def build_generate_request(
    *,
    model: str,
    prompt: str,
    file_uri: str | None = None,
    file_mime: str = CHUNK_MIME,
    inline_b64: str | None = None,
    inline_mime: str = CHUNK_MIME,
) -> tuple[str, dict[str, Any]]:
    """Build the (url, json_body) for a generateContent call.

    Exactly one of ``file_uri`` (Files API reference) or ``inline_b64``
    (inline base64 audio) must be given. Returns the endpoint URL WITHOUT
    any ``?key=`` query (the key travels in the ``x-goog-api-key`` request
    header so it never appears in logs / redirects / test fixtures) and the
    request body dict.

    The field names match the Gemini REST docs: ``contents`` -> ``parts``
    with a ``text`` part plus either a ``file_data`` part
    (``mime_type`` + ``file_uri``) or an ``inline_data`` part
    (``mime_type`` + ``data``).
    """
    if (file_uri is None) == (inline_b64 is None):
        raise ValueError(
            "build_generate_request needs exactly one of file_uri / inline_b64"
        )
    url = f"{API_HOST}/{API_VERSION}/models/{model}:generateContent"
    media_part: dict[str, Any]
    if file_uri is not None:
        media_part = {"file_data": {"mime_type": file_mime, "file_uri": file_uri}}
    else:
        media_part = {"inline_data": {"mime_type": inline_mime, "data": inline_b64}}
    body: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    media_part,
                ],
            }
        ],
        # Deterministic-ish verbatim output: low temperature, no fancy
        # sampling. Kept minimal so it survives model renames.
        "generationConfig": {"temperature": 0.0},
    }
    return url, body


def build_prompt(language: str | None) -> str:
    """Build the transcription prompt, optionally hinting a language.

    ``language`` is the already-normalised Whisper-style code (e.g.
    ``"en"``, ``"fa"``) or None for auto-detect.
    """
    if language:
        hint = (
            f"\nThe spoken language is '{language}'; transcribe in that "
            "language."
        )
    else:
        hint = ""
    return _PROMPT_TEMPLATE.format(lang_hint=hint)


_TS_LINE = re.compile(
    r"""^\s*
    \[?\s*
    (?P<start>\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?|\d{1,2}:\d{2}(?:[.,]\d{1,3})?)
    \s*-->\s*
    (?P<end>\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?|\d{1,2}:\d{2}(?:[.,]\d{1,3})?)
    \s*\]?\s*
    (?P<text>.*\S)\s*$
    """,
    re.VERBOSE,
)


def _parse_ts(value: str) -> float:
    """Parse ``HH:MM:SS.mmm`` / ``MM:SS.mmm`` into seconds."""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    parts_f = [float(p) for p in parts]
    if len(parts_f) == 3:
        h, m, s = parts_f
    elif len(parts_f) == 2:
        h, m, s = 0.0, parts_f[0], parts_f[1]
    else:  # pragma: no cover — regex guarantees 2 or 3 parts
        h, m, s = 0.0, 0.0, parts_f[0]
    return h * 3600.0 + m * 60.0 + s


def extract_text_from_response(resp: dict[str, Any]) -> str:
    """Pull the concatenated text out of a Gemini generateContent JSON.

    Surfaces a clear RuntimeError on a *genuine* failure — an ``error``
    payload, a whole-prompt ``blockReason``, a malformed candidate, or a
    candidate that stopped for a bad reason (a ``finishReason`` other than
    ``STOP``, e.g. ``SAFETY`` / ``MAX_TOKENS``) — so the caller never
    silently writes a transcript that was actually cut short or blocked.

    A candidate that finished CLEANLY (``finishReason`` ``STOP`` or absent)
    but carries no text is NOT an error: it is a window with no recognizable
    speech (music / applause / silence / a per-clip safety pass). Those
    return ``""`` so the per-chunk caller yields zero segments for that
    window and keeps the segments from its other chunks, instead of aborting
    the whole multi-chunk job. (Mirrors ``google_cloud_stt``, where an empty
    result simply contributes 0 segments.)
    """
    if "error" in resp:
        err = resp["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Gemini API error: {msg or 'unknown error'}")
    candidates = resp.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        # A promptFeedback block (whole-prompt safety reject) lives here.
        feedback = resp.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise RuntimeError(
                f"Gemini blocked the request: {feedback.get('blockReason')}"
            )
        raise RuntimeError("Gemini response contained no candidates.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RuntimeError("Gemini response candidate was malformed.")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    texts: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "".join(texts).strip()
    # A bad finishReason must abort the chunk REGARDLESS of whether any text
    # came back. The dangerous case is PARTIAL text with finishReason
    # MAX_TOKENS (a dense window that exceeded the output-token budget):
    # returning that truncated text silently drops the rest of the chunk's
    # audio from the transcript -> data loss. SAFETY / RECITATION are equally
    # truncating. Only STOP (clean finish) or an absent reason are safe.
    reason = first.get("finishReason")
    if reason and reason not in ("STOP", None):
        raise RuntimeError(
            f"Gemini truncated or blocked this clip (finishReason={reason}); "
            "the transcript would be incomplete. The clip may have been "
            "blocked or exceeded the output-token limit."
        )
    if not text:
        # Clean stop with no text == a window with no recognizable speech.
        # Return "" (-> zero segments) rather than raising, so one silent /
        # music-only chunk does not discard the rest of a multi-chunk job.
        return ""
    return text


def parse_transcript_to_segments(text: str) -> list[dict[str, Any]]:
    """Parse the model's timestamped lines into segment dicts.

    Each recognised line ``[HH:MM:SS.mmm --> HH:MM:SS.mmm] text`` becomes
    ``{"start": float, "end": float, "text": str}``. Lines without a
    timestamp prefix are appended to the previous segment's text (the
    model occasionally wraps a long utterance). When NO line matches the
    expected shape but there IS text, the whole thing is returned as a
    single ``start=0`` segment so the user still gets output instead of
    an empty file.
    """
    segments: list[dict[str, Any]] = []
    stripped = text.strip()
    if not stripped:
        return []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Drop a stray markdown fence if the model added one despite the
        # prompt.
        if line.startswith("```"):
            continue
        m = _TS_LINE.match(line)
        if m:
            try:
                start = _parse_ts(m.group("start"))
                end = _parse_ts(m.group("end"))
            except ValueError:
                # A malformed timestamp on an otherwise-matching line:
                # treat the whole line as continuation text rather than
                # crashing the whole transcript.
                if segments:
                    segments[-1]["text"] = (
                        segments[-1]["text"] + " " + line
                    ).strip()
                continue
            segments.append({
                "start": float(start),
                "end": float(max(end, start)),
                "text": m.group("text").strip(),
            })
        elif segments:
            # Continuation of the previous utterance.
            segments[-1]["text"] = (segments[-1]["text"] + " " + line).strip()
        else:
            # First line had no timestamp — start a zero-based segment.
            segments.append({"start": 0.0, "end": 0.0, "text": line})
    if not segments:
        return [{"start": 0.0, "end": 0.0, "text": stripped}]
    return segments


def offset_segments(
    segments: list[dict[str, Any]], offset_seconds: float
) -> list[dict[str, Any]]:
    """Return new segment dicts with start/end shifted by ``offset_seconds``.

    Used to place a chunk's chunk-relative timestamps onto the global
    file timeline. Pure — does not mutate the input. Any nested
    ``words`` list (start/end) is shifted too.
    """
    out: list[dict[str, Any]] = []
    for seg in segments:
        new_seg = dict(seg)
        new_seg["start"] = float(seg.get("start", 0.0)) + offset_seconds
        new_seg["end"] = float(seg.get("end", 0.0)) + offset_seconds
        words = seg.get("words")
        if isinstance(words, list):
            new_words: list[dict[str, Any]] = []
            for w in words:
                if isinstance(w, dict):
                    nw = dict(w)
                    if "start" in nw:
                        nw["start"] = float(nw.get("start", 0.0)) + offset_seconds
                    if "end" in nw:
                        nw["end"] = float(nw.get("end", 0.0)) + offset_seconds
                    new_words.append(nw)
            new_seg["words"] = new_words
        out.append(new_seg)
    return out


def plan_chunks(
    duration: float,
    chunk_seconds: float,
    *,
    chunk_when_unknown: bool = False,
) -> list[tuple[float, float]]:
    """Split ``[0, duration]`` into (start, end) windows of ``chunk_seconds``.

    Pure. With a known ``duration`` this slices ``[0, duration]`` into
    ``chunk_seconds`` windows. When the duration is unknown (``<= 0``):

      * with ``chunk_when_unknown`` False (the default) it returns the legacy
        single whole-file ``(0.0, 0.0)`` marker (``0.0`` end = "to end of
        file" for the ffmpeg slicer);
      * with ``chunk_when_unknown`` True (what ``transcribe_to_segments``
        passes) it returns a bounded run of fixed ``chunk_seconds`` windows so
        a long file with an unreadable header is still chunked instead of being
        sent whole — sending the whole file as one request hits Gemini's
        output-token limit and truncates / loses the bulk of a long
        transcript. Windows past the real end of file produce empty slices,
        which the caller detects (and stops on).
    """
    if chunk_seconds <= 0:
        chunk_seconds = 480.0
    if duration <= 0:
        if not chunk_when_unknown:
            return [(0.0, 0.0)]  # 0.0 end = "to end of file" for the slicer
        unknown_chunks: list[tuple[float, float]] = []
        start = 0.0
        for _ in range(MAX_UNKNOWN_DURATION_CHUNKS):
            unknown_chunks.append((start, start + chunk_seconds))
            start += chunk_seconds
        return unknown_chunks
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < duration - 0.001:
        end = min(start + chunk_seconds, duration)
        chunks.append((start, end))
        start = end
    return chunks or [(0.0, duration)]


def _should_inline(num_bytes: int) -> bool:
    """True when a chunk is small enough to send inline (base64)."""
    return num_bytes <= INLINE_LIMIT_BYTES


def _is_invalid_api_key_body(body: str) -> bool:
    """True when a Gemini error body says the API KEY itself is invalid.

    The Gemini API returns an invalid / revoked key as HTTP 400 with an
    ``INVALID_ARGUMENT`` body ("API key not valid. Please pass a valid API
    key."), NOT the 401/403 the classifier's key branch matches. Without
    this check a user with a bad key sees a raw JSON dump instead of the
    actionable "check the key in Advanced > Backend" message.
    """
    low = (body or "").lower()
    return (
        "api key not valid" in low
        or "api_key_invalid" in low
        or ("invalid_argument" in low and "api key" in low)
    )


def classify_http_error(status: int, body: str) -> str:
    """Map an HTTP status + body into a clear, user-facing message.

    Keeps the raw traceback out of the UI (mirrors parakeet's
    error-translation style).
    """
    snippet = (body or "").strip()[:300]
    if status in (401, 403) or (status == 400 and _is_invalid_api_key_body(body)):
        return (
            "Invalid Google API key (or it lacks Gemini API access). "
            "Check the key in Advanced > Backend, or get a new one at "
            "aistudio.google.com. "
            f"[HTTP {status}] {snippet}"
        )
    if status == 429:
        return (
            "Free quota reached for this Google API key — see Google AI "
            "Studio (aistudio.google.com) for your limits, or wait and "
            f"retry later. [HTTP 429] {snippet}"
        )
    if status == 404:
        return (
            f"The cloud model was not found (it may have been renamed or "
            f"retired). Set a current model name in Advanced > Backend. "
            f"[HTTP 404] {snippet}"
        )
    if status >= 500:
        return (
            f"Google's servers returned an error — try again later. "
            f"[HTTP {status}] {snippet}"
        )
    return f"Cloud transcription failed [HTTP {status}]: {snippet}"


# ---------------------------------------------------------------- backend


class CloudSttBackend(Backend):
    """Gemini-API cloud transcription backend.

    Stateless apart from the API key + model read from config at load().
    Each ``transcribe_to_segments`` call decodes the audio to FLAC,
    chunks it, uploads + transcribes each chunk, and stitches the
    chunk-relative segments onto the global timeline.
    """

    name = "cloud_stt"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config
        self._api_key: str = ""
        self._model: str = DEFAULT_MODEL
        self._chunk_seconds: float = 480.0
        self._error: str | None = None
        self._ready = False
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def _cfg(self) -> dict[str, Any]:
        return self._config if self._config is not None else load_config()

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self._ready = False
        self._error = None
        cfg = self._cfg()
        self._api_key = str(cfg.get("cloud_stt_api_key") or "").strip()
        self._model = str(cfg.get("cloud_stt_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        try:
            self._chunk_seconds = float(cfg.get("cloud_stt_chunk_seconds") or 480.0)
        except (TypeError, ValueError):
            self._chunk_seconds = 480.0
        if not self._api_key:
            self._error = (
                "No Google API key set — paste one in Advanced > Backend "
                "(get a free key at aistudio.google.com)."
            )
            if status_cb:
                status_cb(self._error)
            return False
        # We deliberately do NOT make a network ping mandatory at load:
        # construction must stay fast and offline-safe. The key is
        # validated on the first real request (and by the Advanced
        # dialog's explicit "Test key" button via ping_key()).
        self._ready = True
        if status_cb:
            status_cb(f"Cloud STT ready (model {self._model}).")
        if progress_cb:
            progress_cb({
                "phase": "loaded", "status": "Cloud backend ready",
                "percent": 100, "detail": f"Gemini {self._model}",
            })
        return True

    def is_ready(self) -> bool:
        return self._ready

    def get_error(self) -> str | None:
        return self._error

    # -- key liveness ping (used by the "Test key" button) ----------------

    def ping_key(self) -> tuple[bool, str]:
        """Cheap key check: list models. Returns (ok, message).

        Never raises — returns a clear message on any failure so the UI
        thread can report it. Uses a short timeout so the daemon thread
        the dialog spawns never hangs.
        """
        if not self._api_key:
            return False, "No API key set."
        url = f"{API_HOST}/{API_VERSION}/models?pageSize=1"
        req = urllib.request.Request(
            url, method="GET", headers={API_KEY_HEADER: self._api_key}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                _ = resp.read(1)
            return True, "Key OK — Gemini API reachable."
        except urllib.error.HTTPError as e:
            body = _read_err_body(e)
            return False, classify_http_error(e.code, body)
        except urllib.error.URLError as e:
            return False, (
                "Could not reach Google (offline or blocked): "
                f"{getattr(e, 'reason', e)}"
            )
        except Exception as e:  # noqa: BLE001
            return False, f"Key check failed: {e}"

    # -- transcription -----------------------------------------------------

    def transcribe_to_segments(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        want_words: bool = False,
        vad_parameters: dict[str, Any] | None = None,
        initial_prompt: str | None = None,
        hotwords: str | None = None,
        batch_size: int = 16,
        progress_cb: Callable[[int], None] | None = None,
        log_cb: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        paused: Callable[[], bool] | None = None,
        duration: float = 0.0,
    ) -> tuple[list[dict[str, Any]], LanguageInfo]:
        with self._lock:
            if not self.is_ready() and not self.load(log_cb):
                raise RuntimeError(self._error or "Cloud STT backend not ready")
        if not self._api_key:
            raise RuntimeError(
                self._error or "No Google API key set for the cloud backend."
            )

        prompt = build_prompt(language)

        # Resolve a real duration before planning chunks. A 0 / unknown
        # duration used to collapse the whole file into ONE generateContent
        # request, which hits Gemini's output-token limit on a long clip and
        # truncates / loses the bulk of the transcript. Probe with the bundled
        # ffprobe first; only if that still fails do we fall back to the
        # bounded unknown-length chunk plan (and stop early once we slice past
        # EOF). Mirrors google_cloud_stt._run_standard.
        effective_duration = duration
        if effective_duration <= 0:
            try:
                from ..transcriber import get_duration
                effective_duration = float(get_duration(audio_path) or 0.0)
            except Exception:  # noqa: BLE001 - probe failure is non-fatal
                effective_duration = 0.0
            if log_cb and effective_duration > 0:
                log_cb(
                    f"Cloud STT: probed duration {effective_duration:.0f}s "
                    "for chunk planning."
                )

        duration_unknown = effective_duration <= 0
        if duration_unknown and not ffprobe_is_usable():
            # Fail closed BEFORE any paid request. The unknown-length plan
            # below is only safe because probe_flac_slice can detect a
            # past-EOF slice — and that needs a working ffprobe. With a
            # missing/broken ffprobe every probe is untrusted, so the plan
            # would send up to MAX_UNKNOWN_DURATION_CHUNKS paid chunks even
            # for a short file. Abort with the same kind of clear,
            # recoverable error _encode_chunk_flac gives for missing ffmpeg.
            raise RuntimeError(
                "Could not determine this file's duration and the bundled "
                "ffprobe is missing or not working, so the cloud backend "
                "cannot safely bound how many paid API requests it would "
                "send. Install a full ffmpeg build (which includes ffprobe), "
                "or use the offline engine."
            )
        chunks = plan_chunks(
            effective_duration, self._chunk_seconds, chunk_when_unknown=True
        )
        total = len(chunks)
        if log_cb:
            count_text = (
                "unknown length, chunking until end of file"
                if duration_unknown else f"{total} chunk(s)"
            )
            log_cb(
                f"Cloud STT: uploading {count_text} to Google "
                f"(model {self._model}). Audio leaves this machine."
            )

        all_segments: list[dict[str, Any]] = []
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            if cancelled and cancelled():
                if log_cb:
                    log_cb("Task cancelled")
                break
            while paused and paused() and not (cancelled and cancelled()):
                time.sleep(0.2)
            # Re-check after the pause wait: a Stop that arrives WHILE paused
            # exits the wait loop on the cancel flag, and without this check
            # control would fall straight through to encoding + sending the
            # next paid chunk. (google_cloud_stt's loop already re-checks.)
            if cancelled and cancelled():
                if log_cb:
                    log_cb("Task cancelled")
                break

            flac_path = _encode_chunk_flac(
                audio_path, chunk_start, chunk_end
            )
            try:
                # Unknown-length path: once a slice starting past EOF comes
                # back with no audio, we have reached the end of the file —
                # stop instead of firing the rest of the bounded chunk plan
                # at Google for nothing. The byte-size test is only a cheap
                # first cut: ffmpeg still writes a complete FLAC container
                # (~8 KiB) for a past-EOF slice, so the reliable signal is
                # probe_flac_slice. FAIL CLOSED: only an exact True ("real
                # audio") keeps the loop going. A probe that cannot be
                # trusted (ffprobe missing/broken/unparseable) stops the run
                # here too, so a dead ffprobe can never make every past-EOF
                # slice look like audio and bill the whole worst-case plan.
                if duration_unknown and idx > 0:
                    size_bytes = os.path.getsize(flac_path)
                    probe: bool | None = True
                    if size_bytes >= _EMPTY_FLAC_BYTES:
                        probe = probe_flac_slice(flac_path)
                    if size_bytes < _EMPTY_FLAC_BYTES or probe is not True:
                        if log_cb:
                            if probe is None:
                                log_cb(
                                    "Cloud STT: could not verify audio in "
                                    f"the next slice (ffprobe failed); "
                                    f"stopping after {idx} chunk(s) to avoid "
                                    "unbounded API cost."
                                )
                            else:
                                log_cb(
                                    "Cloud STT: reached end of file "
                                    f"after {idx} chunk(s)."
                                )
                        break
                with liveness_tick(log_cb, f"Cloud STT chunk {idx + 1}/{total}"):
                    text = self._transcribe_one_chunk(flac_path, prompt, log_cb)
            finally:
                try:
                    os.unlink(flac_path)
                except OSError:
                    pass

            seg = parse_transcript_to_segments(text)
            seg = offset_segments(seg, chunk_start)
            all_segments.extend(seg)

            if progress_cb:
                progress_cb(min(100, int(((idx + 1) / max(total, 1)) * 100)))
            if log_cb:
                log_cb(
                    f"Cloud STT: chunk {idx + 1}/{total} -> "
                    f"{len(seg)} segment(s)."
                )

        if want_words:
            # Gemini's transcript is line-level; we don't get reliable
            # word timings. Surface an empty list so word-timestamp
            # writers don't KeyError (mirrors whisper_cpp).
            for s in all_segments:
                s.setdefault("words", [])

        # The model transcribes in the spoken language; report the forced
        # hint when given (we have no separate language-ID signal).
        detected = language or ""
        return all_segments, LanguageInfo(
            language=detected, probability=1.0 if detected else 0.0
        )

    # -- one chunk: upload (or inline) + generateContent ------------------

    def _transcribe_one_chunk(
        self,
        flac_path: str,
        prompt: str,
        log_cb: Callable[[str], None] | None = None,
    ) -> str:
        num_bytes = os.path.getsize(flac_path)
        if _should_inline(num_bytes):
            import base64
            with open(flac_path, "rb") as fp:
                b64 = base64.b64encode(fp.read()).decode("ascii")
            url, body = build_generate_request(
                model=self._model, prompt=prompt,
                inline_b64=b64, inline_mime=CHUNK_MIME,
            )
            resp = self._post_json(url, body, GENERATE_TIMEOUT_S)
            return extract_text_from_response(resp)
        # Files-API path: the audio now sits on Google's servers. Always
        # delete that uploaded blob after we are done with it — success or
        # failure — so the user's audio is not left on Google indefinitely.
        # (Inline audio is never persisted, so only this branch needs it.)
        file_uri, file_name = self._upload_file(flac_path, num_bytes, log_cb)
        try:
            url, body = build_generate_request(
                model=self._model, prompt=prompt,
                file_uri=file_uri, file_mime=CHUNK_MIME,
            )
            resp = self._post_json(url, body, GENERATE_TIMEOUT_S)
            return extract_text_from_response(resp)
        finally:
            self._delete_file(file_name, log_cb)

    # -- Files API resumable upload ---------------------------------------

    def _upload_file(
        self,
        path: str,
        num_bytes: int,
        log_cb: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """Upload ``path`` via the Files API, return ``(file_uri, file_name)``.

        Resumable two-step protocol: start (get an upload URL) then
        upload+finalize, then poll the file until ``state == "ACTIVE"``.
        ``file_name`` (the ``files/<id>`` resource id) is returned so the
        caller can DELETE the blob once transcription is done. ``log_cb`` is
        forwarded to :meth:`_delete_file` so a failed cleanup on an error
        path is surfaced to the user, not just debug-logged.
        """
        start_url = f"{API_HOST}/upload/{API_VERSION}/files"
        start_req = urllib.request.Request(
            start_url,
            data=json.dumps({"file": {"display_name": os.path.basename(path)}}).encode("utf-8"),
            method="POST",
            headers={
                API_KEY_HEADER: self._api_key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(num_bytes),
                "X-Goog-Upload-Header-Content-Type": CHUNK_MIME,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(start_req, timeout=120) as resp:  # noqa: S310
                upload_url = resp.headers.get("X-Goog-Upload-URL")
                resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(classify_http_error(e.code, _read_err_body(e))) from e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise RuntimeError(
                f"Could not reach Google to upload audio: {getattr(e, 'reason', e)}"
            ) from e
        if not upload_url:
            raise RuntimeError(
                "Gemini Files API did not return an upload URL "
                "(X-Goog-Upload-URL missing)."
            )

        with open(path, "rb") as fp:
            data = fp.read()
        up_req = urllib.request.Request(
            upload_url,
            data=data,
            method="POST",
            headers={
                "Content-Length": str(num_bytes),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
        )
        try:
            with urllib.request.urlopen(up_req, timeout=300) as resp:  # noqa: S310
                meta = _json_body(resp)
        except urllib.error.HTTPError as e:
            raise RuntimeError(classify_http_error(e.code, _read_err_body(e))) from e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise RuntimeError(
                f"Audio upload to Google failed: {getattr(e, 'reason', e)}"
            ) from e

        file_obj = meta.get("file") if isinstance(meta, dict) else None
        if not isinstance(file_obj, dict):
            raise RuntimeError("Gemini Files API returned an unexpected response.")
        file_uri = file_obj.get("uri")
        file_name = file_obj.get("name")
        state = file_obj.get("state")
        if not file_name:
            # Nothing was finalized under a known resource id, so there is
            # nothing this method can clean up.
            raise RuntimeError("Gemini Files API response missing file name.")
        if not file_uri:
            # The upload WAS finalized (we have the resource id) but the
            # response carried no uri to transcribe from. The caller's
            # ``finally: self._delete_file(...)`` cannot run — this method
            # raises before returning the name — so delete the known blob
            # here, before raising, rather than leaving the user's audio on
            # Google until its ~48 h expiry.
            deleted = self._delete_file(str(file_name), log_cb)
            raise RuntimeError(
                "Gemini Files API returned no file URI for the uploaded "
                "audio."
                + (
                    " The uploaded audio was deleted from Google."
                    if deleted
                    else " Cleanup of the uploaded audio failed — it will be "
                    "removed automatically within ~48 hours."
                )
            )
        if state != "ACTIVE":
            # The blob is already finalized on Google's servers. If the
            # wait-for-active poll raises (timeout, state FAILED, HTTP / URL
            # error), this method never returns the (uri, name) tuple, so the
            # caller's ``finally: self._delete_file(file_name)`` never runs and
            # the just-uploaded audio would be left on Google until its ~48 h
            # expiry. Delete it best-effort here before re-raising so the
            # "delete on success OR failure" contract holds on this path too.
            try:
                self._wait_for_active(str(file_name))
            except Exception:
                self._delete_file(str(file_name), log_cb)
                raise
        return str(file_uri), str(file_name)

    def _wait_for_active(self, file_name: str) -> None:
        """Poll GET /files/{name} until state==ACTIVE (or FAILED/timeout)."""
        url = f"{API_HOST}/{API_VERSION}/{file_name}"
        deadline = time.time() + FILE_ACTIVE_TIMEOUT_S
        while time.time() < deadline:
            req = urllib.request.Request(
                url, method="GET", headers={API_KEY_HEADER: self._api_key}
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                    meta = _json_body(resp)
            except urllib.error.HTTPError as e:
                raise RuntimeError(classify_http_error(e.code, _read_err_body(e))) from e
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                raise RuntimeError(
                    f"Could not check uploaded-file status: {getattr(e, 'reason', e)}"
                ) from e
            state = meta.get("state")
            if state == "ACTIVE":
                return
            if state == "FAILED":
                raise RuntimeError("Google could not process the uploaded audio.")
            time.sleep(2.0)
        raise RuntimeError(
            "Timed out waiting for Google to process the uploaded audio."
        )

    # -- Files API delete (privacy: don't leave audio on Google) ----------

    def _delete_file(
        self,
        file_name: str | None,
        log_cb: Callable[[str], None] | None = None,
    ) -> bool:
        """Best-effort DELETE of an uploaded Files-API blob.

        Removes the user's audio from Google's servers as soon as the
        chunk is transcribed. Never raises: a failed cleanup must not
        abort an otherwise-successful transcription (Google also expires
        Files-API blobs automatically after ~48 h, so this is the
        primary, not the only, line of defence). ``file_name`` is the
        ``files/<id>`` resource id from the upload response.

        Returns True when the blob is gone (or there was nothing to do),
        False when the delete failed. A failure is surfaced via ``log_cb``
        (like the GCS backend's cleanup warning) as well as ``logger``, so
        the user is told their audio is still on Google instead of the
        failure being hidden at debug level.
        """
        if not file_name or not self._api_key:
            return True
        url = f"{API_HOST}/{API_VERSION}/{file_name}"
        req = urllib.request.Request(
            url, method="DELETE", headers={API_KEY_HEADER: self._api_key}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
            return True
        except Exception as e:  # noqa: BLE001 - cleanup is best-effort
            logger.warning(
                "Could not delete uploaded Gemini file %s: %s", file_name, e
            )
            if log_cb:
                log_cb(
                    f"Note: could not delete the audio uploaded to Google "
                    f"({file_name}): {e}. It will be removed automatically "
                    "within ~48 hours."
                )
            return False

    # -- POST + JSON helper ------------------------------------------------

    def _post_json(
        self, url: str, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                API_KEY_HEADER: self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return _json_body(resp)
        except urllib.error.HTTPError as e:
            raise RuntimeError(classify_http_error(e.code, _read_err_body(e))) from e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise RuntimeError(
                "Could not reach Google for transcription (offline or "
                f"blocked): {getattr(e, 'reason', e)}"
            ) from e


# ---------------------------------------------------------------- helpers


def _read_err_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _json_body(resp: Any) -> dict[str, Any]:
    """Read + decode a JSON response body into a dict.

    Converts a truncated read (``IncompleteRead``), a stalled/reset
    connection during the body read (``TimeoutError`` / ``OSError`` — the
    socket timeout behind ``urlopen`` surfaces those raw, not wrapped in
    ``URLError``), or a non-JSON 200 body
    (typically a captive portal / corporate proxy answering with HTML) into
    a clear RuntimeError instead of a raw
    ``http.client.IncompleteRead`` / ``TimeoutError`` / ``json.JSONDecodeError``
    traceback — every other failure on these requests is already classified
    into a user-facing message.
    """
    try:
        raw = resp.read()
    except (http.client.HTTPException, OSError) as e:
        raise RuntimeError(
            "Google closed the connection before sending a complete "
            "response. Check your network or proxy and try again."
        ) from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise RuntimeError(
            "Google returned a response that was not valid JSON (often a "
            "captive portal or proxy intercepting the connection). Check "
            "your network or proxy and try again."
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError("Google returned an unexpected JSON response.")
    return data


def probe_flac_slice(path: str) -> bool | None:
    """Probe an encoded chunk FLAC for audio: True / False / None (untrusted).

    A byte-size check alone cannot detect a slice that starts past the end
    of the source file: ffmpeg still writes a complete FLAC container
    (streaminfo + VORBIS_COMMENT + padding — measured ~8 KiB for this
    module's encode command) with zero audio frames. ffprobe reports
    ``N/A`` duration for such a container, which is the ``False`` signal
    used here.

    ``None`` means the probe could not be TRUSTED — ffprobe missing /
    broken, a non-zero exit, empty or unparseable output. Callers on the
    unknown-duration EOF-stop path must treat ``None`` as "stop the paid
    loop" (fail-closed) so a missing/broken ffprobe cannot make the loop
    fire its whole worst-case chunk plan at the API. Callers that must
    never truncate a multi-chunk transcript can use
    :func:`flac_slice_has_audio`, which maps ``None`` to True.
    """
    from ..paths import bundled_binary

    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        # A wedged ffprobe on a pathological file must not hang the loop
        # forever (mirrors core.transcriber.get_duration).
        "timeout": 30,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            [bundled_binary("ffprobe"), "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        return None
    if raw.upper().startswith("N/A"):
        # "N/A" — a valid container with no audio frames (past EOF).
        return False
    try:
        return float(raw) > 0.0
    except ValueError:
        # Some other unexpected non-numeric output: untrusted.
        return None


def flac_slice_has_audio(path: str) -> bool:
    """True unless the probe POSITIVELY proves the slice has no audio.

    Fail-open by design, kept for callers that must never truncate a
    transcript: an untrusted probe counts as "has audio". The
    unknown-duration EOF-stop must NOT use this helper — it must use
    :func:`probe_flac_slice` and stop unless the result is exactly True,
    otherwise a missing/broken ffprobe makes every past-EOF slice look like
    real audio and the full worst-case chunk plan gets billed.
    """
    return probe_flac_slice(path) is not False


def ffprobe_is_usable() -> bool:
    """True when the bundled ``ffprobe`` binary actually runs.

    Guards the unknown-duration chunk loop: that loop's early EOF-stop
    depends on ffprobe (see :func:`probe_flac_slice`), so if ffprobe is
    missing or broken the loop cannot be bounded by anything but its
    worst-case chunk cap — sized for many hours of real audio. Detecting a
    dead probe up front (the same failure ``get_duration`` already reports)
    lets the caller abort with a clear message instead of firing that plan
    at the paid API for a short file. Never raises. Mirrors the missing-
    ffmpeg handling in ``_encode_chunk_flac``: a required binary that does
    not work is a clear, recoverable error, not a silent fallback.
    """
    from ..paths import bundled_binary

    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 30,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            [bundled_binary("ffprobe"), "-version"], **kwargs
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _encode_chunk_flac(
    audio_path: str, start_seconds: float, end_seconds: float
) -> str:
    """Decode ``audio_path[start:end]`` to a temp 16 kHz mono FLAC file.

    Uses the bundled ffmpeg (same approach as the parakeet backend) so
    the cloud backend accepts every format the Whisper backend does, and
    so the upload is compact (16 kHz mono FLAC is ~1/10th of the source
    bitrate for typical speech). Returns the temp file path; the caller
    deletes it. ``end_seconds <= start_seconds`` means "to end of file".

    The ffmpeg call is bounded by ``ENCODE_TIMEOUT_S``: a source file on a
    disconnected network share can block the process forever, and unlike
    the HTTP calls there is no other timeout covering this step. A timeout
    is reported the same way as any other ffmpeg failure — a clear,
    recoverable RuntimeError.
    """
    import tempfile
    from ..paths import bundled_binary

    fd, out_path = tempfile.mkstemp(prefix="cloudstt-", suffix=CHUNK_EXT)
    os.close(fd)

    ffmpeg = bundled_binary("ffmpeg")
    cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-y"]
    if start_seconds > 0:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    cmd += ["-i", audio_path]
    if end_seconds > start_seconds:
        cmd += ["-t", f"{end_seconds - start_seconds:.3f}"]
    cmd += ["-ac", "1", "-ar", "16000", "-c:a", "flac", out_path]

    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": True,
        "timeout": ENCODE_TIMEOUT_S,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.run(cmd, **kwargs)
    except (FileNotFoundError, OSError) as e:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise RuntimeError(
            "ffmpeg is required to prepare audio for the cloud backend but "
            "was not found. Use the default engine, or install ffmpeg."
        ) from e
    except subprocess.TimeoutExpired as e:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise RuntimeError(
            "ffmpeg timed out preparing this file for the cloud backend "
            "(the source file may be on a slow or disconnected drive). "
            "Check the file location and try again."
        ) from e
    except subprocess.CalledProcessError as e:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[-400:]
        raise RuntimeError(
            "ffmpeg could not prepare this file for the cloud backend "
            f"(it may be corrupt or an unsupported format): "
            f"{detail or 'no error output'}"
        ) from e
    return out_path
