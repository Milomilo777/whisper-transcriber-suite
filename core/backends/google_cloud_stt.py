"""Optional REAL Google **Cloud** Speech-to-Text v2 backend.

This is distinct from ``core/backends/cloud_stt.py`` (the Gemini-API
"paste a free key" backend). This backend targets the production
``speech.googleapis.com`` v2 service, which:

  * Authenticates with a **service-account JSON file** (NOT a pasted API
    key). The user downloads it from the Google Cloud console
    (IAM & Admin > Service Accounts > Keys) and points the app at it.
  * Returns real word-level timestamps and (optionally) speaker
    diarization labels.

Like the Gemini backend it **uploads audio to Google** and therefore
breaks the project's offline guarantee — the UI makes that loud.

Two modes (config ``gcloud_stt_batch_mode``)
--------------------------------------------
* **STANDARD (online, default)** — ``client.recognize`` accepts inline
  audio only up to ~1 minute / ~10 MB per request, so we decode the file
  to 16 kHz mono FLAC with the bundled ffmpeg, split it into <=~55 s
  chunks, call ``recognize`` per chunk inline, offset each chunk's
  timestamps by the chunk start, and stitch. No Google Cloud Storage
  needed. (~$0.016/min)
* **BATCH (cheaper, slower)** — v2 ``batch_recognize`` only accepts a
  ``gs://`` URI, so this mode REQUIRES a user-configured GCS bucket
  (``gcloud_stt_bucket``). We upload the decoded audio, run a
  long-running batch op with ``ProcessingStrategy.DYNAMIC_BATCHING``
  (~75% cheaper, up to ~24 h turnaround), read the inline result, and
  delete the uploaded blob. Needs ``google-cloud-storage`` (on-demand).
  If no bucket is configured, batch is refused with a clear message.

Verified request shapes (Google Cloud STT v2 docs, fetched 2026-06-06)
----------------------------------------------------------------------
* Synchronous recognize (``SpeechClient.recognize``), the special
  ``recognizers/_`` inline recognizer path, ``RecognitionConfig`` with
  ``auto_decoding_config`` / ``explicit_decoding_config``,
  ``language_codes``, ``model``, ``features`` (word time offsets +
  ``SpeakerDiarizationConfig``):
  https://docs.cloud.google.com/speech-to-text/v2/docs/transcribe-client-libraries
* Batch recognize (``BatchRecognizeRequest`` with
  ``BatchRecognizeFileMetadata(uri="gs://...")``,
  ``RecognitionOutputConfig(inline_response_config=InlineOutputConfig())``,
  the long-running operation, and reading
  ``response.results[uri].transcript.results``):
  https://docs.cloud.google.com/speech-to-text/v2/docs/batch-recognize
* ``WordInfo`` fields (``word``, ``start_offset`` / ``end_offset`` are
  ``google.protobuf.duration_pb2.Duration``, exposed as
  ``datetime.timedelta`` at the proto-plus attribute level;
  ``confidence``, ``speaker_label``):
  https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v2.types.WordInfo
* Available models (``long`` is the long-form default; ``short``,
  ``chirp``, ``chirp_2``, ``telephony``…):
  https://docs.cloud.google.com/speech-to-text/v2/docs/speech-to-text-supported-languages

The heavy ``google-cloud-speech`` / ``google-cloud-storage`` libraries
are installed **on demand** via ``core.optional_deps`` (feature key
``google_cloud_stt``); they are NEVER bundled into the slim embed tree
(mirrors how ``alignment`` / ``whisper_backend`` pull torch on demand).
Audio is decoded + chunked to FLAC with the bundled ffmpeg.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Callable

from .._gc_import_guard import gc_disabled_import
from .._liveness_tick import liveness_tick
from ..config import load_config
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants

#: Default v2 model. A CONFIG value (``gcloud_stt_model``) overrides it so
#: a renamed / newer model needs no code change. ``chirp_2`` is chosen as
#: the default because the app's default Transcribe language is "Auto" and
#: ``chirp_2`` supports BOTH auto language detection (``["auto"]``) AND an
#: explicit BCP-47 code. The older ``long`` model does NOT accept ``auto``
#: (live-tested: ``400 ... "auto" is not supported by "long"``), so it would
#: break the default Auto job. ``chirp_2`` also returns excellent per-word
#: time offsets, which we always request for usable SRT/VTT timing.
DEFAULT_MODEL = "chirp_2"
#: Default location/region. ``chirp_2`` is a REGIONAL model — it does NOT
#: exist in ``global`` (live-tested: a ``global`` recognize for ``chirp_2``
#: 400s), so the default location must be a region. ``us-central1`` carries
#: ``chirp_2``. A config value (``gcloud_stt_location``) overrides this; the
#: client automatically targets the matching regional endpoint for any
#: non-``global`` location.
DEFAULT_LOCATION = "us-central1"
#: STANDARD (online) recognize caps inline audio at ~1 min / ~10 MB. Keep
#: chunks comfortably under the 1-minute wall so a chunk never gets
#: rejected for length. A config value (``gcloud_stt_chunk_seconds``)
#: overrides this.
DEFAULT_CHUNK_SECONDS = 55.0

#: FLAC is lossless, far smaller than WAV, and a v2-supported encoding the
#: ``auto_decoding_config`` recogniser detects without an explicit config.
CHUNK_MIME = "audio/flac"
CHUNK_EXT = ".flac"

#: A FLAC slice that starts past the real end of file decodes to ~no audio,
#: leaving only the container header (well under this). Used by the
#: unknown-duration STANDARD path to detect EOF and stop early. 1 s of 16 kHz
#: mono FLAC is several KB, so this never trips on a real (non-empty) chunk.
_EMPTY_FLAC_BYTES = 4096

#: Approximate published Google Cloud Speech-to-Text v2 prices (USD per
#: minute), used ONLY for the LOCAL cost estimate shown in the UI. The real
#: bill is on Google's side and is NOT readable from a service-account key,
#: so these are deliberately treated as round, honest estimates.
RATE_STANDARD_USD_PER_MIN = 0.016
RATE_BATCH_USD_PER_MIN = 0.004

#: Phrase re-segmentation thresholds (see ``group_words_into_phrases``). The
#: v2 service returns per-word offsets but only coarse result-level segments,
#: so we rebuild readable subtitle-sized phrases from the word stream.
#: Start a new phrase when the silent gap before a word exceeds this many
#: seconds (a natural pause / sentence break).
PHRASE_GAP_SECONDS = 0.6
#: ...or when the running phrase would exceed this many seconds (keeps a
#: subtitle cue from growing too long to read).
PHRASE_MAX_SECONDS = 12.0
#: The one-time new-customer credit Google grants ($300 / 90 days). Shown in
#: the UI as the denominator of the local cost estimate.
NEW_CUSTOMER_CREDIT_USD = 300.0


# ---------------------------------------------------------------- availability

# A REAL crash was observed here (2026-08-15, Python 3.14, protobuf/proto-plus
# as pulled by google-cloud-speech at the time): the first import of
# ``google.cloud.speech_v2`` faulted (Windows STATUS_BREAKPOINT) inside
# proto-plus's message-class creation (``proto/message.py`` ``__new__`` ->
# ``proto/_file_info.py`` ``ready()``) when a garbage-collection pass landed
# mid-construction — triggered by unrelated allocation pressure from other
# threads (a concurrent real faster-whisper transcription, in the observed
# case), not by two threads importing at once. Confirmed by instrumented
# reproduction: a SINGLE thread importing alone still faulted when GC fired
# during the import — disabling GC for the duration of the import is what
# actually stops it (verified by a clean full-suite rerun after adding it).
# See core/_gc_import_guard.py for why this must be a single, process-wide
# guard shared by every heavy-import call site, not a per-module lock.


def runtime_available() -> bool:
    """True iff the google-cloud-speech client imports cleanly.

    A wrong-arch / broken native dependency can raise something other
    than ImportError at import time (the VLC bug class), so we degrade to
    "unavailable" on ANY exception rather than crash the worker probe.
    """
    with gc_disabled_import():
        try:
            import google.cloud.speech_v2  # type: ignore[import-not-found]  # noqa: F401
            from google.oauth2 import service_account  # type: ignore[import-not-found]  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        else:
            return True


def storage_available() -> bool:
    """True iff google-cloud-storage imports (needed only for BATCH mode)."""
    with gc_disabled_import():
        try:
            import google.cloud.storage  # type: ignore[import-not-found]  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        else:
            return True


# ---------------------------------------------------------------- pure seams
# Everything in this block is network-free, google-lib-free, and
# unit-testable with canned data.


def bundled_credentials_path() -> str:
    """Path to a build-bundled service-account JSON, or ``""`` if none.

    A trusted-distribution build may drop a service-account key at
    ``creds/gcloud_stt.json`` next to the app (resolved via
    :func:`core.paths.resource_base`) so Google Cloud STT works out of the
    box without the user pasting a key. The file is NEVER committed to the
    repo — it only ever exists inside a build tree — so a normal source
    checkout returns ``""`` here and the backend keeps requiring an
    explicit key. Pure: only touches the filesystem, no google libs.
    """
    from ..paths import resource_base
    candidate = os.path.join(resource_base(), "creds", "gcloud_stt.json")
    return candidate if os.path.isfile(candidate) else ""


def read_project_id(credentials_json_path: str) -> str:
    """Read ``project_id`` out of a service-account JSON file.

    Raises a clear ``RuntimeError`` (never a raw traceback) when the file
    is missing, unreadable, not JSON, or lacks a ``project_id`` — the
    exact failures a non-technical user hits when they pick the wrong
    file. Pure: only touches the filesystem, no google libs.
    """
    path = (credentials_json_path or "").strip()
    if not path:
        raise RuntimeError(
            "Pick your Google Cloud service-account JSON file in "
            "Advanced > Backend."
        )
    if not os.path.isfile(path):
        raise RuntimeError(
            f"Service-account JSON file not found: {path}. Pick the file "
            "you downloaded from the Google Cloud console in "
            "Advanced > Backend."
        )
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise RuntimeError(
            f"Could not read the service-account JSON file ({path}). It may "
            f"be corrupt or not a real key file: {e}"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(
            "The selected file is not a valid service-account JSON key "
            "(expected a JSON object)."
        )
    project_id = data.get("project_id")
    if not project_id or not isinstance(project_id, str):
        raise RuntimeError(
            "The selected JSON file has no 'project_id' — it does not look "
            "like a Google Cloud service-account key. Download a key from "
            "IAM & Admin > Service Accounts in the Google Cloud console."
        )
    return project_id


def recognizer_path(project_id: str, location: str = DEFAULT_LOCATION) -> str:
    """Build the inline recognizer resource path.

    The special ``recognizers/_`` form means "no pre-created recognizer";
    the request carries its own inline ``config``. Pure.
    """
    loc = (location or DEFAULT_LOCATION).strip() or DEFAULT_LOCATION
    return f"projects/{project_id}/locations/{loc}/recognizers/_"


#: When the duration cannot be determined (corrupt header, streamed source,
#: ffprobe missing), STANDARD mode must STILL slice into inline-sized windows
#: rather than send the whole file as one request — a long file would blow
#: past the ~1 min / ~10 MB inline cap and Google rejects it. We plan this
#: many back-to-back ``chunk_seconds`` windows; the ffmpeg ``-ss/-t`` slicer
#: naturally returns empty FLAC for windows past EOF (-> 0 segments), so the
#: bound just caps wasted requests on a genuinely unknown-length file.
#: 1200 * 55s ~= 18 h, comfortably longer than any realistic input.
MAX_UNKNOWN_DURATION_CHUNKS = 1200


def plan_chunks(
    duration: float,
    chunk_seconds: float,
    *,
    chunk_when_unknown: bool = True,
) -> list[tuple[float, float]]:
    """Split ``[0, duration]`` into (start, end) windows of ``chunk_seconds``.

    Pure. With a known ``duration`` this slices ``[0, duration]`` into
    ``chunk_seconds`` windows. When the duration is unknown (``<= 0``) and
    ``chunk_when_unknown`` is True (the STANDARD-mode default), it returns a
    bounded run of fixed ``chunk_seconds`` windows so a long file with an
    unreadable header is still chunked under the inline cap — windows past
    the real end of file produce empty slices (0 segments). Batch mode passes
    ``chunk_when_unknown=False`` to keep the single whole-file ``(0.0, 0.0)``
    request (its ``-ss/-t``-free slice means "to end of file").
    """
    if chunk_seconds <= 0:
        chunk_seconds = DEFAULT_CHUNK_SECONDS
    if duration <= 0:
        if not chunk_when_unknown:
            return [(0.0, 0.0)]
        chunks: list[tuple[float, float]] = []
        start = 0.0
        for _ in range(MAX_UNKNOWN_DURATION_CHUNKS):
            chunks.append((start, start + chunk_seconds))
            start += chunk_seconds
        return chunks
    chunks = []
    start = 0.0
    while start < duration - 0.001:
        end = min(start + chunk_seconds, duration)
        chunks.append((start, end))
        start = end
    return chunks or [(0.0, duration)]


def offset_segments(
    segments: list[dict[str, Any]], offset_seconds: float
) -> list[dict[str, Any]]:
    """Return new segment dicts with start/end shifted by ``offset_seconds``.

    Places a chunk's chunk-relative timestamps onto the global file
    timeline. Pure — does not mutate the input. Any nested ``words`` list
    (start/end) is shifted too.
    """
    if not offset_seconds:
        return [dict(seg) for seg in segments]
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


def namespace_speaker_labels(
    segments: list[dict[str, Any]], chunk_index: int
) -> list[dict[str, Any]]:
    """Make per-chunk diarization speaker labels globally distinct. PURE.

    Google Cloud STT v2 assigns ``speaker_label`` values that are only
    consistent WITHIN a single ``recognize`` request. In STANDARD (online)
    mode we send each ~55 s chunk as an independent request, so "1" in chunk 0
    and "1" in chunk 1 are UNRELATED people — yet both reach the SRT/VTT/PDF
    writers verbatim, silently merging two physical speakers under one label
    (and splitting one speaker across labels at every chunk boundary).

    Cross-chunk speaker identity cannot be recovered without re-clustering the
    audio (which this online path does not do), so the honest, lossless fix is
    to NAMESPACE each chunk's labels with the chunk number. A label ``"1"`` in
    chunk index 2 becomes ``"C3-1"`` (1-based chunk number), so the transcript
    no longer falsely claims it is the same person as chunk 0's "1". Chunk 0
    (``chunk_index == 0``) is left untouched so a short single-chunk job keeps
    its clean ``"1" / "2"`` labels. Both the segment-level ``speaker`` and any
    per-word ``speaker`` are rewritten. Does not mutate the input.
    """
    if chunk_index <= 0:
        return [dict(seg) for seg in segments]
    prefix = f"C{chunk_index + 1}-"

    def _relabel(label: Any) -> str:
        text = str(label or "").strip()
        return f"{prefix}{text}" if text else text

    out: list[dict[str, Any]] = []
    for seg in segments:
        new_seg = dict(seg)
        if new_seg.get("speaker"):
            new_seg["speaker"] = _relabel(new_seg["speaker"])
        words = new_seg.get("words")
        if isinstance(words, list):
            new_words: list[dict[str, Any]] = []
            for w in words:
                if isinstance(w, dict):
                    nw = dict(w)
                    if nw.get("speaker"):
                        nw["speaker"] = _relabel(nw["speaker"])
                    new_words.append(nw)
                else:
                    new_words.append(w)
            new_seg["words"] = new_words
        out.append(new_seg)
    return out


def _offset_to_seconds(value: Any) -> float:
    """Convert a v2 word offset to float seconds.

    proto-plus exposes ``WordInfo.start_offset`` / ``end_offset`` (a
    protobuf ``Duration``) as a ``datetime.timedelta``; we also tolerate a
    raw ``Duration`` (``.seconds`` + ``.nanos``) and a plain number so the
    parser is robust across client-library versions and easy to unit-test
    with canned values. Returns 0.0 for None / unparseable.
    """
    if value is None:
        return 0.0
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    # Raw protobuf Duration (seconds + nanos).
    seconds = getattr(value, "seconds", None)
    nanos = getattr(value, "nanos", None)
    if seconds is not None or nanos is not None:
        return float(seconds or 0) + float(nanos or 0) / 1e9
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ends_sentence(word_text: str) -> bool:
    """True when ``word_text`` ends in sentence-final punctuation (. ? !).

    Trailing quotes / brackets after the punctuation are tolerated
    (``done."`` still counts). Pure.
    """
    stripped = (word_text or "").rstrip("\"')]}»”’ \t")
    return bool(stripped) and stripped[-1] in ".?!"


def group_words_into_phrases(
    words: list[dict[str, Any]],
    *,
    max_gap: float = PHRASE_GAP_SECONDS,
    max_duration: float = PHRASE_MAX_SECONDS,
    want_words: bool = False,
    want_speaker: bool = False,
) -> list[dict[str, Any]]:
    """Group a flat word list into readable phrase segments. PURE / testable.

    Input: a list of ``{"word", "start", "end"[, "speaker", "probability"]}``
    dicts (already on the global timeline). Output: a list of segment dicts
    ``{"start", "end", "text"}`` (plus ``"words"`` when ``want_words`` and
    ``"speaker"`` when ``want_speaker`` and a label is present).

    A new phrase begins when ANY of these hold relative to the running phrase:

      * the silent gap from the previous word's end to this word's start
        exceeds ``max_gap`` seconds, OR
      * adding this word would push the phrase past ``max_duration`` seconds,
        OR
      * the previous word ended a sentence (``.`` / ``?`` / ``!``), OR
      * the speaker label changed (so diarization keeps one speaker per cue).

    Empty / zero-length words are dropped, and any phrase that ends up with no
    text or zero duration is discarded (this is what removes the live
    ``30->30 "et"`` artifact). No network, no google import.
    """
    # Keep only words that carry a non-empty token (drop the degenerate
    # zero-text fragments outright).
    cleaned: list[dict[str, Any]] = []
    for w in words or []:
        if not isinstance(w, dict):
            continue
        token = str(w.get("word", "") or "").strip()
        if not token:
            continue
        cleaned.append(w)

    segments: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def _flush() -> None:
        if not cur:
            return
        text = " ".join(str(w.get("word", "")).strip() for w in cur).strip()
        seg_start = float(cur[0].get("start", 0.0) or 0.0)
        seg_end = max(float(w.get("end", 0.0) or 0.0) for w in cur)
        seg_end = max(seg_end, seg_start)
        # Drop empties / zero-length phrases (the "et" 30->30 artifact).
        if not text or seg_end <= seg_start:
            return
        seg: dict[str, Any] = {
            "start": seg_start,
            "end": seg_end,
            "text": text,
        }
        if want_words:
            seg["words"] = [dict(w) for w in cur]
        if want_speaker:
            for w in cur:
                sp = str(w.get("speaker", "") or "")
                if sp:
                    seg["speaker"] = sp
                    break
        segments.append(seg)

    prev_end: float | None = None
    prev_speaker: str | None = None
    prev_sentence_end = False
    for w in cleaned:
        w_start = float(w.get("start", 0.0) or 0.0)
        w_end = max(float(w.get("end", 0.0) or 0.0), w_start)
        w_speaker = str(w.get("speaker", "") or "") or None

        start_new = False
        if cur:
            if prev_sentence_end:
                start_new = True
            elif prev_end is not None and (w_start - prev_end) > max_gap:
                start_new = True
            elif w_speaker != prev_speaker:
                start_new = True
            else:
                phrase_start = float(cur[0].get("start", 0.0) or 0.0)
                if (w_end - phrase_start) > max_duration:
                    start_new = True

        if start_new:
            _flush()
            cur = []

        cur.append(w)
        prev_end = w_end
        prev_speaker = w_speaker
        prev_sentence_end = _ends_sentence(str(w.get("word", "")))

    _flush()
    return segments


def parse_recognize_results(
    results: Any,
    *,
    want_words: bool = False,
    want_speaker: bool = False,
) -> list[dict[str, Any]]:
    """Convert v2 ``response.results`` into Whisper-shaped segment dicts.

    The v2 service returns per-word offsets but groups them into only a
    couple of coarse, result-level blocks — feeding those straight to the
    SRT/VTT writer gives one giant 0->30s cue plus degenerate artifacts. So
    when per-word offsets ARE present we collect ALL words across ALL results
    and re-segment them into readable phrases via ``group_words_into_phrases``
    (gap / max-length / sentence-punctuation / speaker-change splits, with
    empty + zero-length phrases dropped).

    A result that carries NO words (only a ``transcript`` string — e.g. a run
    where the model returned no offsets) falls back to a single segment for
    that result using its ``result_end_offset`` for timing, so nothing is
    lost. Such a fallback segment also flushes the accumulated word stream
    first, preserving overall ordering.

    Accepts any iterable of duck-typed result objects (real proto objects
    OR simple namespaces in tests). Pure: no google lib import, no network.
    """
    segments: list[dict[str, Any]] = []
    pending_words: list[dict[str, Any]] = []
    prev_end = 0.0

    def _flush_words() -> None:
        nonlocal pending_words, prev_end
        if not pending_words:
            return
        phrases = group_words_into_phrases(
            pending_words,
            want_words=want_words,
            want_speaker=want_speaker,
        )
        for ph in phrases:
            segments.append(ph)
            prev_end = float(ph.get("end", prev_end) or prev_end)
        pending_words = []

    for result in results or []:
        alternatives = getattr(result, "alternatives", None) or []
        if not alternatives:
            continue
        top = alternatives[0]
        text = (getattr(top, "transcript", "") or "").strip()
        words_raw = list(getattr(top, "words", None) or [])

        word_dicts: list[dict[str, Any]] = []
        for w in words_raw:
            w_start = _offset_to_seconds(getattr(w, "start_offset", None))
            w_end = _offset_to_seconds(getattr(w, "end_offset", None))
            wd: dict[str, Any] = {
                "start": w_start,
                "end": max(w_end, w_start),
                "word": getattr(w, "word", "") or "",
                "probability": float(getattr(w, "confidence", 0.0) or 0.0),
            }
            speaker_label = getattr(w, "speaker_label", "") or ""
            if speaker_label:
                wd["speaker"] = speaker_label
            word_dicts.append(wd)

        if word_dicts:
            # Accumulate into the global word stream; phrase grouping happens
            # once, across results, on flush.
            pending_words.extend(word_dicts)
            continue

        # No word timings for this result — flush any accumulated words first
        # (to keep ordering), then emit one fallback segment from the
        # result-level end offset so the transcript text is not lost.
        if not text:
            continue
        _flush_words()
        seg_start = prev_end
        seg_end = _offset_to_seconds(getattr(result, "result_end_offset", None))
        if seg_end <= seg_start:
            seg_end = seg_start
        seg: dict[str, Any] = {
            "start": float(seg_start),
            "end": float(max(seg_end, seg_start)),
            "text": text,
        }
        if want_words:
            seg["words"] = []
        segments.append(seg)
        prev_end = seg["end"]

    _flush_words()
    return segments


#: Bare ISO-639 code -> a sensible BCP-47 default for the v2 API. The v2
#: service REJECTS bare ISO codes (live-tested: ``chirp_2`` and ``long`` both
#: ``400 The language "en" is not supported`` for bare ``"en"``); it requires
#: a full BCP-47 tag (``en-US``) or the literal ``"auto"``. This table covers
#: every language the app's Transcribe-language menu offers, plus a few common
#: extras. An unknown bare code is passed through as-is so Google surfaces a
#: clear error that ``classify_google_error`` turns into an actionable message.
_BCP47_DEFAULTS: dict[str, str] = {
    "en": "en-US",
    "fa": "fa-IR",
    "ar": "ar-XA",
    "ko": "ko-KR",
    "ja": "ja-JP",
    "zh": "cmn-Hans-CN",
    "vi": "vi-VN",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-BR",
    "ru": "ru-RU",
    "tr": "tr-TR",
    "hi": "hi-IN",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "id": "id-ID",
    "th": "th-TH",
    "uk": "uk-UA",
    # A few more common ones beyond the UI menu.
    "sv": "sv-SE",
    "da": "da-DK",
    "fi": "fi-FI",
    "no": "nb-NO",
    "nb": "nb-NO",
    "cs": "cs-CZ",
    "el": "el-GR",
    "he": "iw-IL",
    "iw": "iw-IL",
    "hu": "hu-HU",
    "ro": "ro-RO",
    "sk": "sk-SK",
    "bg": "bg-BG",
    "hr": "hr-HR",
    "ca": "ca-ES",
    "ms": "ms-MY",
    "fil": "fil-PH",
    "ta": "ta-IN",
    "te": "te-IN",
    "bn": "bn-IN",
    "ur": "ur-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
}


def _canonical_bcp47(code: str) -> str:
    """Return a hyphenated tag in canonical case: lang lower, region UPPER.

    ``en-us`` -> ``en-US``; ``cmn-hans-cn`` -> ``cmn-Hans-CN`` (the middle
    script subtag is Title-cased, a 4-letter ISO-15924 form). Pure.
    """
    parts = code.split("-")
    out: list[str] = []
    for i, part in enumerate(parts):
        if i == 0:
            out.append(part.lower())
        elif len(part) == 4:
            # Script subtag (ISO 15924) — Title case (e.g. "Hans").
            out.append(part[:1].upper() + part[1:].lower())
        else:
            # Region / variant subtag — upper case (e.g. "US", "CN").
            out.append(part.upper())
    return "-".join(out)


def normalize_language_code(code: str | None) -> str:
    """Map a Whisper-style code (``en`` / ``fa``) to a v2 ``language_codes``
    entry, or ``"auto"`` for auto-detect.

    The v2 API REJECTS bare ISO codes — it needs a full BCP-47 tag
    (``en-US``) or the literal ``"auto"`` (live-tested). So:

      * empty / None -> ``"auto"`` (the app's default Transcribe language);
      * an already-BCP-47 code (contains ``-``) is returned in canonical case
        (``en-us`` -> ``en-US``, ``cmn-hans-cn`` -> ``cmn-Hans-CN``);
      * the literal ``"auto"`` passes through;
      * a bare ISO code maps to a sensible BCP-47 default via ``_BCP47_DEFAULTS``;
      * an unknown bare code passes through as-is (best effort) so Google
        surfaces a clear error that ``classify_google_error`` makes actionable.

    Pure + unit-testable.
    """
    if not code:
        return "auto"
    raw = code.strip()
    if not raw:
        return "auto"
    if raw.lower() == "auto":
        return "auto"
    if "-" in raw:
        return _canonical_bcp47(raw)
    bare = raw.lower()
    mapped = _BCP47_DEFAULTS.get(bare)
    if mapped:
        return mapped
    # Unknown bare code — best effort, let Google surface a clear error.
    return bare


def build_recognition_config(
    cloud_speech: Any,
    *,
    language_code: str,
    model: str,
    want_words: bool,
    diarization: bool,
    min_speakers: int = 0,
    max_speakers: int = 0,
) -> Any:
    """Build a v2 ``RecognitionConfig`` for inline FLAC recognition.

    ``cloud_speech`` is the ``google.cloud.speech_v2.types.cloud_speech``
    module, injected so this builder stays import-free and unit-testable
    with a fake module exposing the same class names. Uses
    ``auto_decoding_config`` so the recogniser detects the FLAC encoding;
    enables word time offsets and (optionally) speaker diarization via
    ``RecognitionFeatures``.

    ``enable_word_time_offsets`` is ALWAYS on (not gated on ``want_words`` /
    diarization): per-word offsets are the only way to get usable SRT/VTT
    timing. A live Auto run without them returned a single 0->30s block
    plus a degenerate ``30->30`` fragment because only coarse result-level
    timing came back. ``enable_word_confidence`` stays gated on ``want_words``
    (only useful when callers actually consume per-word probabilities).
    """
    features_kwargs: dict[str, Any] = {
        # Always request word offsets — re-segmentation into phrases (and
        # therefore usable subtitle timing) depends on them.
        "enable_word_time_offsets": True,
        "enable_word_confidence": bool(want_words),
    }
    if diarization:
        # The UI exposes no min/max-speaker inputs, so both arrive as 0 when
        # diarization is on. A SpeakerDiarizationConfig() with no counts is
        # rejected by Google v2 (it needs a positive max). Default to a sane
        # 1..6 range so the feature actually works without UI plumbing.
        lo = int(min_speakers) if min_speakers > 0 else 1
        hi = int(max_speakers) if max_speakers > 0 else 6
        if hi < lo:
            hi = lo
        diar_kwargs: dict[str, Any] = {
            "min_speaker_count": lo,
            "max_speaker_count": hi,
        }
        features_kwargs["diarization_config"] = cloud_speech.SpeakerDiarizationConfig(
            **diar_kwargs
        )
    features = cloud_speech.RecognitionFeatures(**features_kwargs)
    return cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=[language_code],
        model=model,
        features=features,
    )


def classify_google_error(exc: Exception) -> str:
    """Map a google-api / client exception into a clear, user-facing message.

    Keeps the raw traceback out of the UI (mirrors parakeet / cloud_stt
    error-translation style). Pure — inspects the exception's class name +
    message string so it needs no google import at test time.
    """
    name = type(exc).__name__
    msg = str(exc) or name
    low = msg.lower()
    # Permission / API-not-enabled.
    if (
        "PermissionDenied" in name
        or "permission_denied" in low
        or "permission denied" in low
        or "serviceusage" in low
        or "service_disabled" in low
        or "has not been used" in low
        or "is disabled" in low
        or "api is not enabled" in low
    ):
        return (
            "Enable the Speech-to-Text API in your Google Cloud project "
            "(console.cloud.google.com > APIs & Services), and make sure "
            "the service account has the 'Cloud Speech-to-Text User' role. "
            f"[{name}] {msg[:300]}"
        )
    # Auth / bad credentials.
    if (
        "Unauthenticated" in name
        or "unauthenticated" in low
        or "invalid_grant" in low
        or "could not automatically determine credentials" in low
        or "default credentials" in low
        or "invalid jwt" in low
    ):
        return (
            "Google rejected the service-account credentials. Re-download a "
            "fresh JSON key from the Google Cloud console and pick it in "
            f"Advanced > Backend. [{name}] {msg[:300]}"
        )
    # Quota / rate limit. Match 429 as a standalone status token (\b429\b),
    # not any message merely CONTAINING the digits — a file name like
    # "clip_4290.mp4" or an offset "1429" must not be read as a rate limit.
    if (
        "ResourceExhausted" in name
        or "resource_exhausted" in low
        or "quota" in low
        or re.search(r"\b429\b", msg) is not None
        or "rate limit" in low
    ):
        return (
            "Google Cloud quota / rate limit reached for this project — "
            "check your quotas in the Cloud console, or wait and retry. "
            f"[{name}] {msg[:300]}"
        )
    # Bad argument (e.g. unknown model, bad language).
    if "InvalidArgument" in name or "invalid_argument" in low:
        return (
            "Google rejected the request (often an unknown model name or "
            "unsupported language). Check the model in Advanced > Backend. "
            f"[{name}] {msg[:300]}"
        )
    # Offline / transport.
    if (
        "ServiceUnavailable" in name
        or "unavailable" in low
        or "failed to connect" in low
        or "connection" in low
        or "getaddrinfo" in low
        or "dns" in low
    ):
        return (
            "Could not reach Google Cloud (offline or blocked). Check your "
            f"internet connection and retry. [{name}] {msg[:300]}"
        )
    return f"Google Cloud transcription failed [{name}]: {msg[:400]}"


# -- monthly-usage accumulator (pure, testable) ---------------------------


def month_marker(now: _dt.datetime | None = None) -> str:
    """Return the ``YYYY-MM`` marker for ``now`` (UTC default). Pure."""
    n = now or _dt.datetime.now(_dt.timezone.utc)
    return f"{n.year:04d}-{n.month:02d}"


def accumulate_minutes(
    prev_minutes: float,
    prev_month: str,
    added_minutes: float,
    *,
    now: _dt.datetime | None = None,
) -> tuple[float, str]:
    """Roll the local minutes-used counter forward, resetting on a new month.

    Returns ``(new_total_minutes, current_month_marker)``. When the stored
    month marker differs from the current month (or is empty), the counter
    resets to just the freshly-added minutes — the free tier (60 min/month)
    resets monthly and is NOT readable from a service-account key, so we
    track it locally. Pure (clock injectable for tests).
    """
    current = month_marker(now)
    added = max(0.0, float(added_minutes or 0.0))
    if (prev_month or "") != current:
        return added, current
    return max(0.0, float(prev_minutes or 0.0)) + added, current


def effective_minutes_this_month(
    minutes_used: float,
    month_stored: str,
    month_now: str,
) -> float:
    """Minutes counted toward the CURRENT month's free tier.

    When the stored month marker is empty or from a past month, the local
    counter has rolled over, so the effective figure is 0.0 (a new month
    starts fresh). Otherwise it is the stored value, clamped to >= 0. Pure.
    """
    if not month_stored or month_stored != month_now:
        return 0.0
    return max(0.0, float(minutes_used or 0.0))


def estimate_cost(minutes: float, batch: bool) -> float:
    """Estimate the USD cost for ``minutes`` of audio at the current rate.

    Standard mode bills ~$0.016/min; batch mode ~$0.004/min (~75% cheaper).
    This is a LOCAL estimate from a published rate — NOT the real bill,
    which lives on Google's side and is not readable from a service-account
    key. Pure; clamps negative input to 0.
    """
    rate = RATE_BATCH_USD_PER_MIN if batch else RATE_STANDARD_USD_PER_MIN
    return max(0.0, float(minutes or 0.0)) * rate


def format_usage(
    minutes_used: float,
    month_stored: str,
    month_now: str,
    cap: int,
    batch: bool,
) -> str:
    """Build the one-line usage/cost string shown in the Advanced dialog.

    Shows minutes used THIS month against the free-tier cap and a local
    dollar estimate against the new-customer credit. Resets the displayed
    minutes to 0 when the stored month is empty/stale (the monthly free
    tier reset). Pure — no clock, no I/O — so it is trivially unit-tested;
    the caller supplies ``month_now`` (usually ``month_marker()``).

    Example::

        This month: 12.5 / 60 free minutes  -  estimated cost
        ~ $0.20 of your $300 credit
    """
    effective = effective_minutes_this_month(minutes_used, month_stored, month_now)
    cap_int = int(cap) if cap and int(cap) > 0 else 60
    cost = estimate_cost(effective, batch)
    return (
        f"This month: {effective:.1f} / {cap_int} free minutes  -  "
        f"estimated cost ~ ${cost:.2f} of your "
        f"${int(NEW_CUSTOMER_CREDIT_USD)} credit "
        f"({'batch' if batch else 'standard'} rate)"
    )


# ---------------------------------------------------------------- backend


class GoogleCloudSttBackend(Backend):
    """Real Google Cloud Speech-to-Text v2 backend (service-account auth)."""

    name = "google_cloud_stt"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config
        self._error: str | None = None
        self._ready = False
        self._project_id: str = ""
        self._location: str = DEFAULT_LOCATION
        self._model: str = DEFAULT_MODEL
        self._credentials_path: str = ""
        self._batch_mode = False
        self._bucket: str = ""
        self._chunk_seconds: float = DEFAULT_CHUNK_SECONDS
        self._diarization = False
        self._client: Any = None
        self._lock = threading.Lock()
        # Per-run usage-accounting state, populated by _run_standard /
        # _run_batch and read by transcribe_to_segments: how many SECONDS of
        # audio Google actually transcribed, and whether the user cancelled.
        self._last_billable_seconds: float = 0.0
        self._last_was_cancelled: bool = False

    # -- lifecycle ---------------------------------------------------------

    def _cfg(self) -> dict[str, Any]:
        return self._config if self._config is not None else load_config()

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Validate the service-account file + read config. Cheap & offline.

        Deliberately does NOT make a network call (which could hang) — the
        client is built lazily on the first transcribe. Sets a clear
        ``_error`` and returns False on any misconfiguration.
        """
        self._ready = False
        self._error = None
        self._client = None
        cfg = self._cfg()

        if not runtime_available():
            # On-demand first-use install. The library is intentionally NOT
            # bundled (slim build), so install it into the user extras dir the
            # first time this engine actually runs — in the worker too, not
            # only via the Advanced "Test connection" path. Without this a
            # direct Transcribe on a fresh machine just failed with "library
            # not installed" and the job never appeared.
            if status_cb:
                status_cb(
                    "Installing the Google Cloud Speech library "
                    "(one-time setup, needs internet)..."
                )
            installed = False
            try:
                from core import optional_deps

                # find_spec can see a present-but-broken cache (e.g. a
                # grpcio native extension built for a different Python
                # version) that fails on the real import that
                # runtime_available() performs. Detect that case BEFORE
                # installing and force a clean reinstall to repair it —
                # otherwise install() would short-circuit on is_available()
                # and never touch the broken cache.
                broken = optional_deps.is_available("google_cloud_stt")
                if broken and status_cb:
                    status_cb(
                        "Repairing a broken Google Cloud library install "
                        "(rebuilding for this Python)..."
                    )

                installed = optional_deps.install(
                    "google_cloud_stt",
                    log_cb=status_cb,
                    cancel_event=cancel_event,
                    force=broken,
                )
                optional_deps.activate()
            except Exception as e:  # noqa: BLE001
                if status_cb:
                    status_cb(f"Google Cloud library install error: {e}")
                installed = False
            if not installed or not runtime_available():
                self._error = (
                    "The Google Cloud Speech library could not be installed "
                    "automatically (no internet?). Open Advanced > Backend to "
                    "install it, or switch to the offline engine."
                )
                if status_cb:
                    status_cb(self._error)
                return False
            if status_cb:
                status_cb("Google Cloud Speech library installed.")

        self._credentials_path = (
            str(cfg.get("gcloud_stt_credentials_json") or "").strip()
            or bundled_credentials_path()
        )
        self._location = str(cfg.get("gcloud_stt_location") or DEFAULT_LOCATION).strip() or DEFAULT_LOCATION
        self._model = str(cfg.get("gcloud_stt_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self._batch_mode = bool(cfg.get("gcloud_stt_batch_mode", False))
        self._bucket = str(cfg.get("gcloud_stt_bucket") or "").strip()
        self._diarization = bool(cfg.get("gcloud_stt_diarization", False))
        try:
            self._chunk_seconds = float(
                cfg.get("gcloud_stt_chunk_seconds") or DEFAULT_CHUNK_SECONDS
            )
        except (TypeError, ValueError):
            self._chunk_seconds = DEFAULT_CHUNK_SECONDS

        # Validate the service-account JSON (parses + has project_id). This
        # is the most common user error, so surface it precisely.
        try:
            self._project_id = read_project_id(self._credentials_path)
        except RuntimeError as e:
            self._error = str(e)
            if status_cb:
                status_cb(self._error)
            return False

        # Batch mode needs a bucket + the storage lib. Refuse cleanly here.
        if self._batch_mode and not self._bucket:
            self._error = (
                "Batch mode is on but no Google Cloud Storage bucket is set. "
                "Enter a bucket name in Advanced > Backend, or turn off batch "
                "mode to use the standard (online) path."
            )
            if status_cb:
                status_cb(self._error)
            return False

        self._ready = True
        if status_cb:
            mode = "batch" if self._batch_mode else "standard"
            status_cb(
                f"Google Cloud STT ready (project {self._project_id}, "
                f"model {self._model}, {mode} mode)."
            )
        if progress_cb:
            progress_cb({
                "phase": "loaded",
                "status": "Google Cloud backend ready",
                "percent": 100,
                "detail": f"{self._project_id} / {self._model}",
            })
        return True

    def is_ready(self) -> bool:
        return self._ready

    def get_error(self) -> str | None:
        return self._error

    # -- lazy client build -------------------------------------------------

    def _build_client(self) -> Any:
        """Build (and cache) the v2 ``SpeechClient`` from the JSON key.

        Lazy + guarded — any failure becomes a clean RuntimeError, never a
        raw traceback. Honours a custom ``api_endpoint`` for regional
        locations (e.g. ``europe-west4`` needs that regional endpoint).
        """
        if self._client is not None:
            return self._client
        try:
            from google.cloud.speech_v2 import SpeechClient  # type: ignore[import-not-found]
            from google.oauth2 import service_account  # type: ignore[import-not-found]
            from google.api_core import client_options as _co  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "The Google Cloud Speech library failed to import. Re-select "
                "this backend in Advanced > Backend to (re)install it."
            ) from e
        try:
            creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self._credentials_path
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(classify_google_error(e)) from e

        opts = None
        loc = (self._location or DEFAULT_LOCATION).strip()
        if loc and loc != "global":
            # Regional models must hit the regional endpoint.
            opts = _co.ClientOptions(  # type: ignore[no-untyped-call]
                api_endpoint=f"{loc}-speech.googleapis.com"
            )
        try:
            self._client = SpeechClient(credentials=creds, client_options=opts)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(classify_google_error(e)) from e
        return self._client

    def _cloud_speech_types(self) -> Any:
        from google.cloud.speech_v2.types import cloud_speech  # type: ignore[import-not-found]
        return cloud_speech

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
                raise RuntimeError(
                    self._error or "Google Cloud STT backend not ready"
                )

        language_code = normalize_language_code(language)
        # Diarization needs word offsets to carry the speaker label.
        effective_words = bool(want_words) or self._diarization

        # Reset the per-run accounting state these helpers populate. The run
        # methods record how many SECONDS of audio Google actually
        # transcribed and whether the user cancelled, so accounting bills
        # only the processed audio (not the full file) and is skipped on
        # cancel. Defaults are conservative: 0 billable, cancelled=True, so a
        # run method that raises before recording leaves nothing to count.
        self._last_billable_seconds = 0.0
        self._last_was_cancelled = True

        if self._batch_mode:
            segments = self._run_batch(
                audio_path, language_code, effective_words, duration,
                progress_cb, log_cb, cancelled,
            )
        else:
            segments = self._run_standard(
                audio_path, language_code, effective_words, duration,
                progress_cb, log_cb, cancelled, paused,
            )

        # Local monthly minute accounting (free tier is 60 min/month and NOT
        # readable from the key). Count ONLY the audio Google actually
        # transcribed (``_last_billable_seconds``), and SKIP accounting
        # entirely on a user cancel — billing the full file duration when the
        # user pressed Stop after one chunk (or the batch op was cancelled)
        # over-counts the free tier and the cost estimate for audio Google
        # never processed.
        if not self._last_was_cancelled:
            self._accumulate_usage(self._last_billable_seconds, log_cb)

        detected = language or ""
        return segments, LanguageInfo(
            language=detected, probability=1.0 if detected else 0.0
        )

    # -- STANDARD (online, chunked inline) --------------------------------

    def _run_standard(
        self,
        audio_path: str,
        language_code: str,
        want_words: bool,
        duration: float,
        progress_cb: Callable[[int], None] | None,
        log_cb: Callable[[str], None] | None,
        cancelled: Callable[[], bool] | None,
        paused: Callable[[], bool] | None,
    ) -> list[dict[str, Any]]:
        """Run the chunked online recognize, returning the stitched segments.

        Side effects for usage accounting (read by ``transcribe_to_segments``):
        sets ``self._last_billable_seconds`` to the SECONDS of audio actually
        sent to ``recognize`` (so a partial / cancelled run bills only what
        Google processed, never the full file length) and
        ``self._last_was_cancelled`` to whether the user pressed Stop.
        """
        client = self._build_client()
        cloud_speech = self._cloud_speech_types()
        recognizer = recognizer_path(self._project_id, self._location)
        config = build_recognition_config(
            cloud_speech,
            language_code=language_code,
            model=self._model,
            want_words=want_words,
            diarization=self._diarization,
            min_speakers=self._diar_min(),
            max_speakers=self._diar_max(),
        )

        # Resolve a real duration before planning chunks. A 0 / unknown
        # duration used to collapse STANDARD mode to ONE whole-file inline
        # request, which blows past the ~1 min / ~10 MB inline cap on any
        # non-trivial file. Probe with the bundled ffprobe first; only if
        # that still fails do we fall back to the bounded unknown-length
        # chunk plan (and stop early once we slice past EOF).
        effective_duration = duration
        if effective_duration <= 0:
            try:
                from ..transcriber import get_duration
                effective_duration = float(get_duration(audio_path) or 0.0)
            except Exception:  # noqa: BLE001 - probe failure is non-fatal
                effective_duration = 0.0
            if log_cb and effective_duration > 0:
                log_cb(
                    f"Google Cloud STT: probed duration "
                    f"{effective_duration:.0f}s for chunk planning."
                )

        duration_unknown = effective_duration <= 0
        chunks = plan_chunks(effective_duration, self._chunk_seconds)
        total = len(chunks)
        if log_cb:
            count_text = (
                "unknown length, chunking until end of file"
                if duration_unknown else f"{total} chunk(s)"
            )
            log_cb(
                f"Google Cloud STT: {count_text} to Google "
                f"(project {self._project_id}, model {self._model}). "
                "Audio leaves this machine."
            )

        all_segments: list[dict[str, Any]] = []
        transcribed_seconds = 0.0
        was_cancelled = False
        # A run that completes its planned chunks (or stops early at EOF) is a
        # SUCCESS; only an explicit Stop sets was_cancelled.
        self._last_was_cancelled = False
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            if cancelled and cancelled():
                was_cancelled = True
                if log_cb:
                    log_cb("Task cancelled")
                break
            while paused and paused() and not (cancelled and cancelled()):
                time.sleep(0.2)
            if cancelled and cancelled():
                was_cancelled = True
                if log_cb:
                    log_cb("Task cancelled")
                break

            flac_path = _encode_chunk_flac(audio_path, chunk_start, chunk_end)
            try:
                with open(flac_path, "rb") as fp:
                    content = fp.read()
                # Unknown-length path: once a slice starting past EOF comes
                # back essentially empty (just a FLAC header, no audio), we
                # have reached the end of the file — stop instead of firing
                # the rest of the bounded chunk plan at Google for nothing.
                if duration_unknown and idx > 0 and len(content) < _EMPTY_FLAC_BYTES:
                    if log_cb:
                        log_cb(
                            "Google Cloud STT: reached end of file "
                            f"after {idx} chunk(s)."
                        )
                    break
                request = cloud_speech.RecognizeRequest(
                    recognizer=recognizer,
                    config=config,
                    content=content,
                )
                try:
                    with liveness_tick(
                        log_cb, f"Google Cloud STT chunk {idx + 1}/{total}"
                    ):
                        # Bounded RPC deadline: liveness_tick would otherwise
                        # keep the parent watchdog from killing a worker wedged
                        # on a half-open connection. timeout= caps the hang.
                        response = client.recognize(
                            request=request, timeout=self._recognize_timeout()
                        )
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(classify_google_error(e)) from e
                # This chunk was actually sent to Google — count its audio
                # toward billing. When the duration is known, clamp the last
                # chunk to the real end of file so a window the slicer padded
                # past EOF is not over-counted; when unknown, the planned
                # window length is the best available estimate of audio sent
                # (a window past EOF would have tripped the empty-FLAC break
                # above before reaching here, so it is not counted).
                if duration_unknown:
                    transcribed_seconds += max(0.0, chunk_end - chunk_start)
                else:
                    upper = min(chunk_end, effective_duration)
                    transcribed_seconds += max(0.0, upper - chunk_start)
            finally:
                try:
                    os.unlink(flac_path)
                except OSError:
                    pass

            seg = parse_recognize_results(
                getattr(response, "results", None),
                want_words=want_words,
                want_speaker=self._diarization,
            )
            if self._diarization:
                # v2 speaker labels are only consistent within one recognize
                # request; namespace each chunk's labels so "1" in chunk 2 is
                # not silently merged with "1" in chunk 1 (see
                # namespace_speaker_labels). Chunk 0 is left untouched.
                seg = namespace_speaker_labels(seg, idx)
            seg = offset_segments(seg, chunk_start)
            all_segments.extend(seg)

            if progress_cb:
                progress_cb(min(100, int(((idx + 1) / max(total, 1)) * 100)))
            if log_cb:
                log_cb(
                    f"Google Cloud STT: chunk {idx + 1}/{total} -> "
                    f"{len(seg)} segment(s)."
                )
        self._last_billable_seconds = transcribed_seconds
        self._last_was_cancelled = was_cancelled
        return all_segments

    # -- BATCH (GCS upload + long-running op + inline result) -------------

    def _run_batch(
        self,
        audio_path: str,
        language_code: str,
        want_words: bool,
        duration: float,
        progress_cb: Callable[[int], None] | None,
        log_cb: Callable[[str], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> list[dict[str, Any]]:
        """Run the batch (GCS) recognize, returning the stitched segments.

        Side effects for usage accounting (read by ``transcribe_to_segments``):
        batch processes the WHOLE file, so on success ``_last_billable_seconds``
        is the full audio length and ``_last_was_cancelled`` is False; on a
        user cancel there is no partial result, so billable seconds is 0 and
        ``_last_was_cancelled`` is True (the caller then skips accounting).
        """
        if not self._bucket:
            raise RuntimeError(
                "Batch mode needs a Google Cloud Storage bucket. Set one in "
                "Advanced > Backend, or turn off batch mode."
            )
        if not storage_available():
            raise RuntimeError(
                "Batch mode needs the google-cloud-storage library. Re-select "
                "this backend in Advanced > Backend to install it, or turn "
                "off batch mode to use the standard (online) path."
            )

        client = self._build_client()
        cloud_speech = self._cloud_speech_types()
        recognizer = recognizer_path(self._project_id, self._location)
        config = build_recognition_config(
            cloud_speech,
            language_code=language_code,
            model=self._model,
            want_words=want_words,
            diarization=self._diarization,
            min_speakers=self._diar_min(),
            max_speakers=self._diar_max(),
        )

        # Decode the WHOLE file once (batch accepts up to 8 h; no chunking).
        flac_path = _encode_chunk_flac(audio_path, 0.0, 0.0)
        gcs_uri = ""
        blob_name = ""
        try:
            if log_cb:
                log_cb("Batch submitted (cheaper, may take a while)...")
            gcs_uri, blob_name = self._upload_to_gcs(flac_path, log_cb)
        finally:
            try:
                os.unlink(flac_path)
            except OSError:
                pass

        response: Any = None
        was_cancelled = False
        try:
            request = cloud_speech.BatchRecognizeRequest(
                recognizer=recognizer,
                config=config,
                files=[cloud_speech.BatchRecognizeFileMetadata(uri=gcs_uri)],
                recognition_output_config=cloud_speech.RecognitionOutputConfig(
                    inline_response_config=cloud_speech.InlineOutputConfig(),
                ),
                # Dynamic batching is ~75% cheaper (longer turnaround).
                processing_strategy=(
                    cloud_speech.BatchRecognizeRequest.ProcessingStrategy.DYNAMIC_BATCHING
                ),
            )
            try:
                with liveness_tick(log_cb, "Google Cloud STT batch"):
                    # Bound the SUBMIT RPC too — a network blackhole at submit
                    # time would otherwise hang the worker indefinitely.
                    operation = client.batch_recognize(
                        request=request, timeout=self._batch_submit_timeout()
                    )
                    response, was_cancelled = self._await_batch_with_cancel(
                        operation, cancelled, log_cb
                    )
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(classify_google_error(e)) from e
        finally:
            # Always delete the uploaded blob, success or failure.
            self._delete_gcs_blob(blob_name, log_cb)

        if was_cancelled:
            # User pressed Stop mid-batch. The standard path returns its
            # partial; batch has no partial, so return an empty list — the
            # caller sees task.cancelled and treats it as a clean cancel. No
            # billable audio (nothing transcribed) and _last_was_cancelled
            # stays True so the caller skips usage accounting.
            if log_cb:
                log_cb("Task cancelled")
            self._last_billable_seconds = 0.0
            self._last_was_cancelled = True
            return []

        segments = self._parse_batch_response(
            response, gcs_uri, want_words
        )
        if progress_cb:
            progress_cb(100)
        if log_cb:
            log_cb(f"Google Cloud STT (batch): {len(segments)} segment(s).")
        # Batch transcribed the whole file -> bill the full audio length.
        self._last_billable_seconds = _seconds_for(audio_path, duration)
        self._last_was_cancelled = False
        return segments

    def _await_batch_with_cancel(
        self,
        operation: Any,
        cancelled: Callable[[], bool] | None,
        log_cb: Callable[[str], None] | None,
    ) -> tuple[Any, bool]:
        """Wait for the batch LRO, polling so a user Stop is honored promptly.

        Repeatedly calls ``operation.result(timeout=<poll>)`` inside a try /
        except for the LRO's timeout error. Between polls it checks
        ``cancelled()``; on cancel it best-effort ``operation.cancel()``s the
        long-running op and returns ``(None, True)`` so the worker isn't wedged
        in ``result()`` for the whole (up to 1 h) batch turnaround. On normal
        completion it returns ``(response, False)``. A genuine batch deadline
        (no progress within ``_batch_timeout``) still raises.
        """
        import concurrent.futures as _futures

        poll = self._batch_poll_seconds()
        deadline = time.monotonic() + self._batch_timeout()
        while True:
            if cancelled and cancelled():
                try:
                    operation.cancel()
                except Exception:  # noqa: BLE001 - best effort
                    pass
                return None, True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Exhausted the overall batch budget — surface a clean timeout.
                raise _futures.TimeoutError(
                    "Google Cloud batch operation did not finish within the "
                    "configured timeout."
                )
            try:
                response = operation.result(timeout=min(poll, remaining))
                return response, False
            except _futures.TimeoutError:
                # Not done yet — loop to re-check the cancel flag.
                continue

    def _parse_batch_response(
        self, response: Any, gcs_uri: str, want_words: bool
    ) -> list[dict[str, Any]]:
        """Pull the inline transcript out of a BatchRecognizeResponse.

        ``response.results`` is a map keyed by the input ``gs://`` URI; each
        value's ``transcript`` is a ``BatchRecognizeResults`` whose
        ``.results`` mirror the synchronous shape. We look up our URI, and
        fall back to the single map value when the key doesn't match.
        """
        results_map = getattr(response, "results", None) or {}
        file_result = None
        try:
            file_result = results_map.get(gcs_uri)  # type: ignore[union-attr]
        except AttributeError:
            file_result = None
        if file_result is None:
            try:
                values = list(results_map.values())  # type: ignore[union-attr]
            except AttributeError:
                values = []
            if values:
                file_result = values[0]
        if file_result is None:
            raise RuntimeError(
                "Google returned no batch results for the uploaded audio."
            )
        transcript = getattr(file_result, "transcript", None)
        inner = getattr(transcript, "results", None)
        return parse_recognize_results(
            inner,
            want_words=want_words,
            want_speaker=self._diarization,
        )

    # -- GCS upload / delete ----------------------------------------------

    def _upload_to_gcs(
        self, local_path: str, log_cb: Callable[[str], None] | None
    ) -> tuple[str, str]:
        """Upload ``local_path`` to the configured bucket; return (uri, name)."""
        try:
            from google.cloud import storage  # type: ignore[import-not-found]
            from google.oauth2 import service_account  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "The google-cloud-storage library failed to import."
            ) from e
        try:
            creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self._credentials_path
            )
            storage_client = storage.Client(
                project=self._project_id, credentials=creds
            )
            bucket = storage_client.bucket(self._bucket)
            blob_name = f"whisper-transcriber-suite/{int(time.time())}-{os.path.basename(local_path)}"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(local_path, content_type=CHUNK_MIME)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(classify_google_error(e)) from e
        if log_cb:
            log_cb(f"Uploaded audio to gs://{self._bucket}/{blob_name}")
        return f"gs://{self._bucket}/{blob_name}", blob_name

    def _delete_gcs_blob(
        self, blob_name: str, log_cb: Callable[[str], None] | None
    ) -> None:
        if not blob_name:
            return
        try:
            from google.cloud import storage  # type: ignore[import-not-found]
            from google.oauth2 import service_account  # type: ignore[import-not-found]
            creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self._credentials_path
            )
            storage_client = storage.Client(
                project=self._project_id, credentials=creds
            )
            storage_client.bucket(self._bucket).blob(blob_name).delete()
            if log_cb:
                log_cb(f"Deleted uploaded audio gs://{self._bucket}/{blob_name}")
        except Exception as e:  # noqa: BLE001
            # Cleanup failure is non-fatal — the transcript already
            # succeeded. Warn so the user can prune the bucket manually.
            if log_cb:
                log_cb(
                    f"Note: could not delete uploaded audio "
                    f"gs://{self._bucket}/{blob_name}: {e}"
                )

    # -- usage accounting --------------------------------------------------

    def _accumulate_usage(
        self,
        billable_seconds: float,
        log_cb: Callable[[str], None] | None,
    ) -> None:
        """Add the actually-transcribed minutes to the local monthly counter.

        ``billable_seconds`` is the audio Google actually transcribed (the
        sum of windows sent in STANDARD mode, or the whole file in BATCH) —
        NOT necessarily the full input length, so a partial run is not
        over-counted. The caller skips this entirely on a user cancel.
        Persists via save_config so the UI can show "minutes used this
        month". Never raises — accounting must not break a successful
        transcription.
        """
        try:
            minutes = max(0.0, float(billable_seconds or 0.0) / 60.0)
            if minutes <= 0:
                return
            from ..config import save_config
            cfg = self._cfg()
            prev = float(cfg.get("gcloud_stt_minutes_used") or 0.0)
            prev_month = str(cfg.get("gcloud_stt_minutes_month") or "")
            new_total, marker = accumulate_minutes(prev, prev_month, minutes)
            cfg["gcloud_stt_minutes_used"] = round(new_total, 3)
            cfg["gcloud_stt_minutes_month"] = marker
            # When using a live config (the default), persist it so the UI
            # reads the updated counter. When a test injects a config dict,
            # we still update it in place but skip the disk write.
            if self._config is None:
                save_config(cfg)
            if log_cb:
                log_cb(
                    f"Google Cloud STT minutes this month ({marker}): "
                    f"{new_total:.1f}"
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("gcloud_stt usage accounting failed: %s", e)

    # -- small config readers ---------------------------------------------

    def _diar_min(self) -> int:
        try:
            return int(self._cfg().get("gcloud_stt_min_speakers") or 0)
        except (TypeError, ValueError):
            return 0

    def _diar_max(self) -> int:
        try:
            return int(self._cfg().get("gcloud_stt_max_speakers") or 0)
        except (TypeError, ValueError):
            return 0

    def _batch_timeout(self) -> float:
        try:
            return float(self._cfg().get("gcloud_stt_batch_timeout_s") or 3600.0)
        except (TypeError, ValueError):
            return 3600.0

    def _recognize_timeout(self) -> float:
        """Per-request RPC deadline for the synchronous ``recognize`` call.

        Without an application-level deadline a gRPC call wedged on a
        half-open TCP connection (VPN flap, firewall blackhole) blocks
        forever — and ``liveness_tick`` actively keeps the parent watchdog
        from killing the worker. A bounded deadline lets ``classify_google_error``
        surface a clean "could not reach Google" instead of an unkillable hang.
        """
        try:
            return float(
                self._cfg().get("gcloud_stt_recognize_timeout_s") or 300.0
            )
        except (TypeError, ValueError):
            return 300.0

    def _batch_submit_timeout(self) -> float:
        """RPC deadline for SUBMITTING the long-running batch op.

        The LRO *result* wait is bounded by ``_batch_timeout``; the initial
        ``batch_recognize`` submit RPC needs its own (shorter) deadline so a
        network blackhole at submit time cannot hang the worker forever.
        """
        try:
            return float(
                self._cfg().get("gcloud_stt_batch_submit_timeout_s") or 120.0
            )
        except (TypeError, ValueError):
            return 120.0

    def _batch_poll_seconds(self) -> float:
        """Per-iteration wait while polling the batch LRO for cancellation.

        Batch mode polls ``operation.result(timeout=<this>)`` in a loop so a
        user Stop is honored within ~this many seconds instead of blocking for
        the whole (up to 1 h) batch turnaround.
        """
        try:
            val = float(self._cfg().get("gcloud_stt_batch_poll_s") or 5.0)
        except (TypeError, ValueError):
            val = 5.0
        return val if val > 0 else 5.0


# ---------------------------------------------------------------- helpers


def _seconds_for(audio_path: str, duration: float = 0.0) -> float:
    """Return the audio length in SECONDS (uses ``duration`` when > 0).

    Pure-ish: falls back to ``core.transcriber.get_duration`` only when the
    caller didn't already know the length. Never raises — returns 0.0 on a
    probe failure so usage accounting degrades silently.
    """
    seconds = float(duration or 0.0)
    if seconds <= 0:
        try:
            from ..transcriber import get_duration
            seconds = float(get_duration(audio_path) or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0
    return max(0.0, seconds)


def _minutes_for(audio_path: str, duration: float = 0.0) -> float:
    """Return the audio length in MINUTES (uses ``duration`` when > 0).

    Thin wrapper over :func:`_seconds_for`. Never raises.
    """
    return _seconds_for(audio_path, duration) / 60.0


def _encode_chunk_flac(
    audio_path: str, start_seconds: float, end_seconds: float
) -> str:
    """Decode ``audio_path[start:end]`` to a temp 16 kHz mono FLAC file.

    Uses the bundled ffmpeg (same approach as the parakeet / cloud_stt
    backends). ``end_seconds <= start_seconds`` means "to end of file"
    (used by batch mode, which sends the whole file). Returns the temp
    path; the caller deletes it.
    """
    import tempfile
    from ..paths import bundled_binary

    fd, out_path = tempfile.mkstemp(prefix="gcloudstt-", suffix=CHUNK_EXT)
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
            "ffmpeg is required to prepare audio for the Google Cloud "
            "backend but was not found. Use the default engine, or install "
            "ffmpeg."
        ) from e
    except subprocess.CalledProcessError as e:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[-400:]
        raise RuntimeError(
            "ffmpeg could not prepare this file for the Google Cloud backend "
            f"(it may be corrupt or an unsupported format): "
            f"{detail or 'no error output'}"
        ) from e
    return out_path
