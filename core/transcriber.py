"""Whisper model lifecycle + the transcribe loop.

The module keeps a single ``MODEL`` global so worker subprocesses don't load
twice. Phase 2a additions:

* VAD via ``vad_filter=True`` (default ON), tunable via config keys
* Word-level timestamps when ``word_timestamps`` is True
* Language detection captured from ``info.language`` / ``info.language_probability``
  and posted via ``language_cb``
* Multi-format output through :mod:`core.writers`
* :class:`faster_whisper.BatchedInferencePipeline` on CUDA
* Optional ``initial_prompt`` and ``hotwords`` (forwarded if supported)
"""
from __future__ import annotations

import copy
import logging
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from faster_whisper import WhisperModel

try:  # 1.0.3+ ships this; older wheels do not
    from faster_whisper import BatchedInferencePipeline  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    BatchedInferencePipeline = None  # type: ignore[assignment]

from . import _checkpoint
from ._proc import new_session_kwargs
from .config import load_config
from .model_manager import DownloadCancelled, ensure_model
from .paths import bundled_binary
from .task import TranscriptionTask
from .writers import get_binary_writer, get_writer, is_binary, supported_formats

# Periodic checkpoint cadence. Writing after every segment is wasteful
# on long files (1 fsync per ~5 s of audio); waiting until completion
# defeats the point. N+timer-or together so very short segments (busy
# dialogue) still checkpoint at a steady wall-clock rate.
_CHECKPOINT_EVERY_N_SEGMENTS = 10
_CHECKPOINT_EVERY_N_SECONDS = 20.0

# faster-whisper accepts ISO-639-1 (+ a few special) codes only — never a
# BCP-47 region tag like "en-US" / "pt-BR". Passing one makes transcribe()
# raise, which silently produced NO output when an auto-transcribe carried
# a download's "en-US" subtitle language (seen on a YouTube Short).
_WHISPER_LANGS = frozenset({
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh", "yue",
})


# Codes some sources/UI tables still emit that Whisper only accepts under
# their modern / alternate spelling. The app's own language picker table
# (app/domain/languages.py) ships "iw" for Hebrew and "jv" for Javanese;
# yt-dlp subtitle metadata can carry "in"/"ji"/"nb"/"cmn". Without this map
# those hints were dropped to auto-detect, silently ignoring an explicit
# user choice (and for a downloaded file, its own language metadata).
_LANG_ALIASES: dict[str, str] = {
    "iw": "he",   # deprecated ISO 639-1 Hebrew
    "in": "id",   # deprecated ISO 639-1 Indonesian
    "ji": "yi",   # deprecated ISO 639-1 Yiddish
    "jv": "jw",   # ISO 639-1 Javanese; Whisper uses the older "jw"
    "nb": "no",   # Norwegian Bokmål -> Whisper's "no"
    "cmn": "zh",  # Mandarin -> Whisper's "zh"
}


def _normalize_language(code: str | None) -> str | None:
    """Coerce a UI/download language hint into a Whisper-accepted code.

    Returns a valid code, or None for auto-detect. Strips a BCP-47
    region/script suffix ("en-US" -> "en", "zh-Hans" -> "zh") and drops
    anything Whisper doesn't recognise rather than letting transcribe()
    raise (which produced a silent no-output failure).
    """
    if not code:
        return None
    # Comma/space separated values (a yt-dlp multi-value code like
    # "zh-Hans,zh-CN" or "pt,pt-BR,pt-PT") are in the source's own
    # preference order; each value is one BCP-47 tag whose ONLY language
    # subtag is its first "-" component ("en" of "en-US", "zh" of
    # "zh-Hans"). Later components are regions/scripts — treating them as
    # languages would turn a rejected "xx-BR" into Breton. Return the
    # first tag Whisper accepts, aliases included; an unrecognised leading
    # tag (a legacy "iw,he" pair, an experimental "xx,en") must not
    # shadow a valid later alternative.
    normalized = code.strip().lower().replace("_", "-").replace(" ", ",")
    for value in normalized.split(","):
        language = value.split("-", 1)[0]
        if not language:
            continue
        candidate = _LANG_ALIASES.get(language, language)
        if candidate in _WHISPER_LANGS:
            return candidate
    return None


logger = logging.getLogger(__name__)

# Skip the online-config fetch on this import-time read: transcriber.py is
# imported inside the hot worker subprocess where a network stall on spawn is
# harmful, and none of the online app-level keys (model catalog / stats /
# ffplay links) are needed here. The parent App passes the effective config
# (already online-merged) per task; this module-global is only the bootstrap
# snapshot. See core.config.load_config(fetch_online=...).
config = load_config(fetch_online=False)

MODEL: Any = None
PIPELINE: Any = None  # BatchedInferencePipeline wrapper when device == "cuda"
MODEL_READY = False
MODEL_ERROR: str | None = None

# R3: effective-device tracking. ``device`` / ``compute_type`` (assigned just
# below) are what we *requested*. After a load we read back what CTranslate2
# actually ran on and stash it here so the worker can report it to the UI.
# _DEVICE_DOWNGRADED flips True when a requested CUDA load failed and we
# self-healed onto CPU int8 (instead of the old hard crash + bogus
# "re-download the model" prompt).
_DEVICE_DOWNGRADED = False
_REQUESTED_DEVICE = ""
_EFFECTIVE_DEVICE = ""
_EFFECTIVE_COMPUTE_TYPE = ""

# Pluggable backend instance for non-default engines (e.g. whisper.cpp).
# The default faster_whisper path keeps using MODEL/PIPELINE globals so
# every existing test that monkeypatches transcriber.config keeps
# working. Backends other than faster_whisper are routed via
# _ALT_BACKEND when ``config["transcribe_backend"]`` is set.
_ALT_BACKEND: Any = None
_ALT_BACKEND_NAME: str = ""


def log(msg: str, cb: Callable[[str], None] | None = None) -> None:
    if cb:
        cb(msg)
    else:
        logger.info(msg)


def _with_task_prefix(
    cb: Callable[[str], None] | None,
    task: "TranscriptionTask",
) -> Callable[[str], None] | None:
    """Wrap a log callback to prefix every line with ``[task=…]``.

    Audit B6 (QW-12): with ``parallel_workers > 1`` the UI console
    interleaves messages from two workers and the user cannot tell
    which file each line belongs to. Wrapping the callback once
    inside transcribe() adds the prefix everywhere downstream.

    The prefix is the source file's basename (not full path — too
    long for a console column) and the integer ``history_id`` when
    set (matches the history.db row id for cross-reference).
    """
    if cb is None:
        return None
    base = os.path.basename(task.file_path or "")
    hid = getattr(task, "history_id", 0) or 0
    prefix = f"[task={hid} file={base}] " if hid else f"[file={base}] "

    def _wrapped(msg: str) -> None:
        try:
            cb(prefix + msg)
        except Exception:
            logger.exception("log callback raised; prefix=%r msg=%r", prefix, msg)
    return _wrapped


def detect_device() -> tuple[str, str]:
    """Pick (device, compute_type) using the module-level config.

    Thin shim around :func:`core.hardware.detect_device_for` so the
    legacy call sites + tests that monkeypatch ``transcriber.config``
    keep working. New code should call ``hardware.detect_device_for``
    with an explicit config dict.
    """
    from . import hardware as _hw
    return _hw.detect_device_for(config)


device, compute_type = detect_device()


def is_model_ready() -> bool:
    return MODEL_READY


def get_model_error() -> str | None:
    return MODEL_ERROR


def _wrap_for_batched(model: Any) -> Any:
    """Wrap with BatchedInferencePipeline on CUDA if available."""
    if device != "cuda" or BatchedInferencePipeline is None:
        return None
    try:
        return BatchedInferencePipeline(model=model)
    except Exception as e:  # noqa: BLE001
        logger.info("BatchedInferencePipeline unavailable: %s", e)
        return None


@dataclass(frozen=True)
class EffectiveDevice:
    """What the model actually loaded onto, vs. what was requested.

    ``downgraded`` is True when a requested ``cuda`` load failed and we
    self-healed onto CPU int8. ``device`` / ``compute_type`` are read back
    from the underlying CTranslate2 object after a successful load (falling
    back to the requested values when those attributes aren't exposed).
    """
    device: str
    compute_type: str
    requested_device: str
    downgraded: bool


def get_effective_device() -> EffectiveDevice:
    """Return the device the loaded model is actually running on.

    Safe to call before any load — reports the requested values with
    ``downgraded=False`` until a load populates the effective state. When a
    non-default backend is active (``_ALT_BACKEND``), prefer its self-reported
    device info if it exposes the R3 accessors; otherwise fall back to its
    plain ``device`` (other backends don't track a downgrade).
    """
    if _ALT_BACKEND is not None:
        bdev = str(getattr(_ALT_BACKEND, "device", "") or "") or device
        bcompute = str(getattr(_ALT_BACKEND, "compute_type", "") or "") or compute_type
        breq = str(getattr(_ALT_BACKEND, "requested_device", "") or "") or bdev
        bdown = bool(getattr(_ALT_BACKEND, "downgraded", False))
        return EffectiveDevice(
            device=bdev,
            compute_type=bcompute,
            requested_device=breq,
            downgraded=bdown,
        )
    return EffectiveDevice(
        device=_EFFECTIVE_DEVICE or device,
        compute_type=_EFFECTIVE_COMPUTE_TYPE or compute_type,
        requested_device=_REQUESTED_DEVICE or device,
        downgraded=_DEVICE_DOWNGRADED,
    )


# CPU self-heal target — what we retry with when a CUDA load fails. int8 is the
# universal CPU fallback used everywhere else in the hardware tiering.
_CPU_FALLBACK = ("cpu", "int8")


def _capture_effective_device(model: Any, req_device: str, req_compute: str) -> None:
    """Record what the loaded model actually runs on (getattr-guarded).

    The underlying ``model.model`` is a dynamically-typed CTranslate2 object;
    its ``device`` / ``compute_type`` attributes are read defensively so a
    wheel that doesn't expose them can't break the load. Keeps the module
    ``device`` / ``compute_type`` globals in sync with reality so
    ``_wrap_for_batched`` (which reads the global ``device``) and the worker's
    UI report agree.
    """
    global device, compute_type, _EFFECTIVE_DEVICE, _EFFECTIVE_COMPUTE_TYPE
    ct2 = getattr(model, "model", None)
    eff_device = str(getattr(ct2, "device", "") or "") or req_device
    eff_compute = str(getattr(ct2, "compute_type", "") or "") or req_compute
    _EFFECTIVE_DEVICE = eff_device
    _EFFECTIVE_COMPUTE_TYPE = eff_compute
    # Keep the module globals authoritative so the batched-pipeline wrap and
    # any later detect_device() readers see the device we truly loaded on.
    device = eff_device
    compute_type = eff_compute


def _load_whisper_model_self_healing(
    model_path: str,
    req_device: str,
    req_compute: str,
    status_cb: Callable[[str], None] | None = None,
) -> Any:
    """Construct a WhisperModel, self-healing a failed CUDA load onto CPU.

    Returns the loaded model. On a CUDA construction failure (the classic
    missing-cuDNN/cuBLAS RuntimeError) this logs the real reason, flips the
    module-level downgrade flag, and RETRIES with ("cpu", "int8") instead of
    propagating — turning a hard crash + bogus re-download prompt into a
    visible, graceful downgrade. A CPU load that fails still raises (nothing to
    fall back to).
    """
    global device, compute_type, _DEVICE_DOWNGRADED, _REQUESTED_DEVICE
    _REQUESTED_DEVICE = req_device
    _DEVICE_DOWNGRADED = False
    try:
        model = WhisperModel(model_path, device=req_device, compute_type=req_compute)
        _capture_effective_device(model, req_device, req_compute)
        return model
    except Exception as e:
        if req_device != "cuda":
            raise
        cpu_device, cpu_compute = _CPU_FALLBACK
        from .hardware import cuda_load_failure_reason
        logger.warning(
            "CUDA model load failed (%s); downgrading to %s/%s. %s",
            e, cpu_device, cpu_compute, cuda_load_failure_reason(str(e)),
        )
        if status_cb:
            status_cb(
                f"GPU unavailable ({e}); falling back to CPU (slower)."
            )
        model = WhisperModel(model_path, device=cpu_device, compute_type=cpu_compute)
        # Reflect the downgrade in the module globals so _wrap_for_batched
        # does NOT try to wrap a CPU model in a CUDA batched pipeline.
        device = cpu_device
        compute_type = cpu_compute
        _DEVICE_DOWNGRADED = True
        _capture_effective_device(model, cpu_device, cpu_compute)
        return model


def load_existing_model(status_cb: Callable[[str], None] | None = None) -> bool:
    """Load the model for the configured backend.

    For the default faster_whisper backend, this populates the legacy
    module-level ``MODEL`` / ``PIPELINE`` globals so the rest of the
    code (and the unit tests) keep working. For non-default backends
    it loads via the backend interface and flips ``MODEL_READY`` so
    the transcribe loop's "wait until ready" check passes.
    """
    global MODEL, PIPELINE, MODEL_READY, MODEL_ERROR, _ALT_BACKEND, _ALT_BACKEND_NAME

    backend_name = (
        str(config.get("transcribe_backend") or "faster_whisper").strip().lower()
    )
    MODEL_READY = False
    MODEL_ERROR = None

    if backend_name and backend_name != "faster_whisper":
        try:
            from .backends import get_backend
            backend = get_backend(backend_name)
        except Exception as e:  # noqa: BLE001
            MODEL_ERROR = f"Backend {backend_name} not available: {e}"
            if status_cb:
                status_cb(MODEL_ERROR)
            return False
        ok = False
        try:
            ok = backend.load(status_cb)
        except Exception as e:  # noqa: BLE001
            MODEL_ERROR = f"{backend_name} load failed: {e}"
            if status_cb:
                status_cb(MODEL_ERROR)
            return False
        if not ok:
            MODEL_ERROR = backend.get_error() or f"{backend_name} load returned False"
            if status_cb:
                status_cb(MODEL_ERROR)
            return False
        _ALT_BACKEND = backend
        _ALT_BACKEND_NAME = backend_name
        MODEL_READY = True
        if status_cb:
            status_cb("Model loaded")
        return True

    model_path = Path(config["model_path"])

    if not model_path.exists():
        MODEL_ERROR = f"Model folder missing: {model_path}"
        if status_cb:
            status_cb(MODEL_ERROR)
        return False

    try:
        if status_cb:
            status_cb("Loading existing Whisper model...")
        logger.info(
            "model_load backend=faster_whisper model_path=%s "
            "device=%s compute_type=%s",
            model_path, device, compute_type,
        )
        MODEL = _load_whisper_model_self_healing(
            str(model_path), device, compute_type, status_cb
        )
        PIPELINE = _wrap_for_batched(MODEL)
        MODEL_READY = True
        if status_cb:
            status_cb("Model loaded")
        return True
    except Exception as e:
        MODEL_ERROR = str(e)
        if status_cb:
            status_cb(f"Existing model failed to load: {e}")
        return False


def load_model(
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    global MODEL, PIPELINE, MODEL_READY, MODEL_ERROR
    MODEL_READY = False
    MODEL_ERROR = None
    try:
        model_path = ensure_model(config, status_cb, progress_cb, cancel_event)
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelled("Model download cancelled")
        if status_cb:
            status_cb("Loading Whisper model...")
        if progress_cb:
            progress_cb({"phase": "load", "status": "Loading Whisper model...",
                         "percent": 100, "detail": "Preparing model for transcription"})
        MODEL = _load_whisper_model_self_healing(
            model_path, device, compute_type, status_cb
        )
        PIPELINE = _wrap_for_batched(MODEL)
        MODEL_READY = True
        if status_cb:
            status_cb("Model loaded")
        if progress_cb:
            progress_cb({"phase": "loaded", "status": "Model loaded",
                         "percent": 100, "detail": "Ready"})
        return True
    except DownloadCancelled as e:
        MODEL_ERROR = None
        if status_cb:
            status_cb(str(e))
        return False
    except Exception as e:
        MODEL_ERROR = str(e)
        if status_cb:
            status_cb(f"ERROR: {e}")
        raise


def load_model_async(
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    try:
        load_model(status_cb, progress_cb, cancel_event)
    except Exception as e:  # noqa: BLE001
        # Don't propagate (background thread); but logging matters —
        # silently swallowing this hid a real model-corruption case for a
        # whole session in the field.
        logger.exception("Async model load failed: %s", e)
        if status_cb:
            try:
                status_cb(f"ERROR: {e}")
            except Exception:  # noqa: BLE001
                pass


def start_background_model_load(status_cb: Callable[[str], None] | None = None) -> None:
    threading.Thread(target=load_model_async, args=(status_cb,), daemon=True).start()


def get_duration(path: str) -> float:
    ffprobe = bundled_binary("ffprobe")
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        # If the user feeds in something pathological (broken container,
        # network mount that stalls), don't block transcription forever.
        "timeout": 60,
    }
    if os.name == "nt":
        # Without this, ffprobe pops a black console window every time the
        # transcriber starts a new file. Invisible in dev (we run from a
        # terminal); user-visible from the windowed exe.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            **kwargs,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out for {path}") from e
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(
            f"ffprobe failed (exit={r.returncode}) for {path}: "
            f"{r.stderr.strip() or 'no output'}"
        )
    raw = r.stdout.strip()
    try:
        duration = float(raw)
    except ValueError:
        # A corrupt-but-readable container can make ffprobe exit 0 and print
        # "N/A". Treat as unknown duration (0.0) so transcription still runs
        # — faster-whisper decodes the audio independently; only the
        # progress %% is unavailable — instead of crashing with a raw
        # "could not convert string to float: 'N/A'".
        logger.warning("get_duration: non-numeric ffprobe output %r for %s", raw, path)
        return 0.0
    return duration if duration > 0 else 0.0


def fmt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02}:{m:02}:{s:02}"


def _vad_parameters() -> dict[str, Any] | None:
    """Build the VAD options dict from config — None when VAD disabled."""
    if not config.get("vad_enabled", True):
        return None
    return {
        "min_silence_duration_ms": int(config.get("vad_min_silence_ms", 500)),
        "threshold": float(config.get("vad_threshold", 0.5)),
        "speech_pad_ms": int(config.get("vad_speech_pad_ms", 400)),
    }


def _segment_to_dict(seg: Any, want_words: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "start": float(seg.start),
        "end": float(seg.end),
        "text": (seg.text or "").strip(),
    }
    if want_words:
        words = getattr(seg, "words", None) or []
        payload["words"] = [
            {
                "start": float(w.start),
                "end": float(w.end),
                "word": (w.word or "").strip(),
                "probability": float(getattr(w, "probability", 0.0)),
            }
            for w in words
        ]
    return payload


def _record_transcript_stats(
    task: Any, segments_data: list[dict[str, Any]]
) -> None:
    """Attach ``word_count`` / ``audio_duration`` to *task* from the
    in-memory segments, so the worker's "done" event can report them.

    The parent app previously re-parsed a produced output file for these
    numbers, which fails whenever the selected formats include no
    machine-readable transcript (txt/docx/pdf/smtv_docx only) — those runs
    always recorded ``word_count=0``. Best-effort: never raises.
    """
    try:
        from .stats import audio_duration_from_segments, count_words_in_segments

        task.word_count = count_words_in_segments(segments_data)
        task.audio_duration = audio_duration_from_segments(segments_data)
    except Exception:  # noqa: BLE001 — stats must never fail a transcription
        pass


def _offset_segments(segments_data: list[dict[str, Any]], offset: float) -> None:
    """Shift every segment (and its words) by ``offset`` seconds, in place.

    Moves slice-relative timestamps (a clip transcribed from a temp WAV
    that starts at 0 s) back onto the original file's timeline.
    """
    if not offset:
        return
    for d in segments_data:
        try:
            d["start"] = float(d.get("start", 0.0)) + offset
            d["end"] = float(d.get("end", 0.0)) + offset
        except (TypeError, ValueError):
            continue
        words = d.get("words")
        if isinstance(words, list):
            for w in words:
                try:
                    w["start"] = float(w.get("start", 0.0)) + offset
                    w["end"] = float(w.get("end", 0.0)) + offset
                except (TypeError, ValueError):
                    continue


def _current_backend_and_model() -> tuple[str, str]:
    """Snapshot the (backend, model_name) pair the checkpoint records.

    Reads the module-level ``config`` (which honours runtime overrides
    via ``_runtime_overrides_scope``). Centralised so the periodic
    writer and the resume validator agree on what "the current
    backend / model" means.
    """
    backend = (
        str(config.get("transcribe_backend") or "faster_whisper").strip().lower()
    )
    model_info = config.get("model") or {}
    model_name = ""
    if isinstance(model_info, dict):
        model_name = str(model_info.get("name") or "")
    if not model_name:
        # Fallback to the model slug if the dict form isn't populated.
        model_name = str(config.get("whisper_model") or "")
    return backend, model_name


def _write_periodic_checkpoint(
    task: "TranscriptionTask",
    segments_data: list[dict[str, Any]],
    last_end_time: float,
    detected_language: str,
    language_probability: float,
    log_cb: Callable[[str], None] | None,
) -> None:
    """Persist a partial checkpoint; never raises — logs and moves on.

    The periodic writer must not interrupt transcription on any error:
    a full disk or a permissions glitch should not kill a 2-hour run.
    """
    backend, model_name = _current_backend_and_model()
    try:
        _checkpoint.write_checkpoint(
            task.file_path,
            backend=backend,
            model_name=model_name,
            language=detected_language or "",
            language_probability=float(language_probability or 0.0),
            cfg_fingerprint=_checkpoint.config_fingerprint(config),
            last_end_time=float(last_end_time),
            segments=segments_data,
            checkpoint_time=time.time(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Periodic checkpoint write failed: %s", e)
        log(f"WARN: could not write partial checkpoint: {e}", log_cb)


def has_resumable_checkpoint(source_path: str) -> bool:
    """Public helper for the UI: is there a partial on disk for this file?

    Only checks existence; the resume path does the full
    backend/model/mtime validation later. The UI uses this just to
    decide whether to surface a "Resume" right-click entry.
    """
    return _checkpoint.has_checkpoint(source_path)


def _render_filename_template(
    template: str,
    *,
    base: str,
    ext: str,
    lang: str = "",
    speaker_count: int = 0,
    date: str | None = None,
) -> str:
    """Expand the ``output_filename_template`` config string.

    Tokens supported: ``{base}``, ``{ext}``, ``{lang}``, ``{date}``,
    ``{speaker_count}``. Missing tokens silently render as empty. Any
    other ``{name}`` token is preserved verbatim so a typo doesn't
    yield a confusing FileNotFound at write time.

    Safety:
      * Positional ``{0}`` (or any IndexError-raising shape) falls
        back to the legacy ``"{base}.{ext}"`` layout.
      * Malformed templates (unbalanced braces, attribute access)
        fall back to the legacy layout — a corrupt config never
        blocks a write.
      * Path-traversal is rejected after render: the resolved
        absolute path must stay under the directory of ``base``.
        ``../etc/passwd.srt`` and similar escapes fall back to the
        legacy layout.

    ``base`` is the input-file stem *with* its directory prefix. That
    keeps writes next to the source media by default; the user can
    still pull files into a sibling folder by prefixing with e.g.
    ``"transcripts/{base}.{ext}"`` — split paths are honoured by the
    later ``os.makedirs(dirname, exist_ok=True)``.
    """
    import datetime as _dt

    fields: dict[str, str] = {
        "base": base,
        "ext": ext,
        "lang": (lang or "").strip(),
        "speaker_count": str(int(speaker_count)) if speaker_count else "",
        "date": date if date is not None else _dt.date.today().isoformat(),
    }

    class _Fmt(dict):
        def __missing__(self, key: str) -> str:
            # Preserve unknown tokens verbatim so the user can see the
            # typo rather than getting a silent ENOENT.
            return "{" + key + "}"

    legacy = f"{base}.{ext}"
    try:
        rendered = template.format_map(_Fmt(fields))
    except (IndexError, KeyError, ValueError, TypeError, AttributeError):
        # Malformed template (unbalanced braces, positional `{0}`,
        # attribute access in a token, etc.). Fall back to the safe
        # legacy layout so a corrupt config never blocks a write.
        return legacy

    # Path-traversal guard. ``base`` always has a directory prefix
    # (the source media's folder); a rendered path that resolves
    # outside that root means the template tried to escape via
    # ``../`` segments. Reject and fall back rather than write into
    # an unintended location.
    try:
        base_dir = os.path.dirname(os.path.abspath(base)) or os.path.abspath(".")
        rendered_abs = os.path.abspath(rendered)
        # On Windows os.path.commonpath rejects mixed-drive args; in
        # that case the template is clearly escaping (different drive
        # letter than base) — fall back.
        try:
            common = os.path.commonpath([base_dir, rendered_abs])
        except ValueError:
            return legacy
        if os.path.normcase(common) != os.path.normcase(base_dir):
            return legacy
    except (OSError, ValueError):
        return legacy

    return rendered


def _indexed_path(path: str, index: int) -> str:
    """Insert a `` (N)`` suffix before the extension for de-duplication.

    ``index <= 0`` returns ``path`` unchanged (the first, normal write).
    Otherwise: ``video.srt`` -> ``video (1).srt`` -> ``video (2).srt`` …
    so a re-run never overwrites a previous output.
    """
    if index <= 0:
        return path
    root, ext = os.path.splitext(path)
    return f"{root} ({index}){ext}"


# Registry-key -> on-disk extension overrides. A format whose name is
# not a valid file extension (or that a tool can't open under its raw
# name) needs an entry here; everything else uses its own name.
#   * json      -> json (historical: the key already equalled the ext,
#                   listed for documentation symmetry)
#   * smtv_docx -> docx (a ".smtv_docx" file is not a Word document)
_FMT_EXTENSIONS: dict[str, str] = {
    "json": "json",
    "smtv_docx": "docx",
}


def _smtv_output_path(base: str, lang: str) -> str:
    """Path for the SMTV team file: a fixed, recognisable filename.

    ``<work title> -Transcription in <language> – Translation in
    English.docx`` next to the source media. ``base`` carries the source
    directory + stem; the language name comes from the core-side ISO map
    (falls back to the raw code, or ``...`` when unknown — matching the
    template's own placeholder). Filesystem-illegal characters in the
    language label are stripped so the name is always writable.
    """
    from .writers.smtv_docx_writer import language_name

    directory = os.path.dirname(base)
    stem = os.path.basename(base)
    label = language_name(lang) or "..."
    # Strip characters Windows forbids in filenames from the language
    # label (the stem is reused verbatim from the existing source name,
    # so it is already a legal filename).
    for bad in '<>:"/\\|?*':
        label = label.replace(bad, "")
    label = label.strip() or "..."
    # en-dash (U+2013) matches the template title exactly.
    filename = f"{stem} -Transcription in {label} – Translation in English.docx"
    return os.path.join(directory, filename) if directory else filename


def _write_outputs(
    base: str,
    segments_data: list[dict[str, Any]],
    audio_path: str,
    formats: list[str] | None = None,
    *,
    lang: str = "",
    speaker_count: int = 0,
    chapters: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Write each requested format atomically.

    Each writer runs to a ``<path>.part`` first, then os.replace's onto
    the final name. If anything raises mid-write — disk full, encoding
    crash, the process dying — the user is left with either the
    previous (intact) version of the file or nothing, never a half-
    written SRT that some downstream tool will reject. The .part file
    is cleaned up on the raise path.

    When *chapters* is non-empty the auto-chapter sidecar is written as
    part of the same set and shares the outputs' one collision index
    (``name (1).chapters.json`` next to ``name (1).srt``). The
    transcript viewer derives the sidecar path from the JSON it opened,
    so without the shared index a re-run's chapters were invisible from
    the newly indexed transcript (and its sidecar overwrote the previous
    run's file at the un-indexed name).

    Text formats go through ``open(..., "w", encoding="utf-8")``;
    binary formats (``docx``) go through ``open(..., "wb")`` with
    bytes payload from ``get_binary_writer``.

    The final path is composed by expanding the
    ``output_filename_template`` config key (default ``"{base}.{ext}"``).
    """
    template = str(config.get("output_filename_template") or "{base}.{ext}")
    written: list[str] = []
    write_errors: list[str] = []
    available = supported_formats()
    # Not list()-ed: a malformed override must reach the TypeError guard
    # below instead of raising here, so the value stays typed as Any.
    fmts: Any = formats or config.get("output_formats") or ["srt", "json"]
    # Catch the "user asked for formats but every name we got is
    # unknown" case up front — otherwise the function silently
    # returns [] and the caller reports "Done in 0.02s, Wrote 0
    # output file(s)". Treat it as a hard error so the user knows
    # their config is broken.
    #
    # F5 class at the consumption point: a raw-JSON project override (or a
    # hand-edited app config) can make this a non-iterable (``5`` /
    # ``true``) or hold unhashable members (``[["srt"]]``), so the registry
    # membership test below would raise a raw ``TypeError`` after the
    # transcription already ran instead of the module's clear per-file
    # error. _apply_runtime_overrides' coercion table deliberately covers
    # only scalar keys, so the guard lives here, where the value is
    # actually used; a task-provided formats list is never reinterpreted.
    try:
        requested_known: list[str] = [f for f in fmts if f in available]
    except TypeError as e:
        raise RuntimeError(
            f"Invalid 'output_formats' value: {fmts!r} "
            f"(expected a list of format names): {e}"
        ) from e
    if fmts and not requested_known:
        raise RuntimeError(
            f"None of the requested output formats are known: "
            f"{fmts!r}. Supported: {sorted(available)!r}."
        )
    # Render every requested format's path up front, then pick ONE
    # shared index so re-running a transcription never overwrites the
    # previous output: name.srt + name.json become name (1).srt +
    # name (1).json together (a consistent set, not mismatched indices).
    planned: list[tuple[str, str]] = []
    for fmt_name in requested_known:
        if fmt_name not in available:
            continue
        # Map the registry key to the on-disk extension. Most formats
        # use their own name; a couple need an override so the file is
        # one a downstream tool can actually open. ``json`` already used
        # this; ``smtv_docx`` MUST become ``.docx`` (a ".smtv_docx" file
        # is not a Word document).
        ext = _FMT_EXTENSIONS.get(fmt_name, fmt_name)
        if fmt_name == "smtv_docx":
            # The transcription team's file uses a fixed, recognisable
            # name rather than the user's output_filename_template, so
            # it never collides with a normal ".docx" export.
            rendered = _smtv_output_path(base, lang)
        else:
            rendered = _render_filename_template(
                template, base=base, ext=ext, lang=lang, speaker_count=speaker_count,
            )
        planned.append((fmt_name, rendered))
    # smtv_docx is excluded from the shared index: it is a fixed,
    # recognisable filename (see _smtv_output_path), not part of the
    # re-run-safety numbering the other formats share. Including it here
    # was a real bug -- an unrelated pre-existing .srt/.json from an
    # earlier run bumped the shared index, so a transcription's SMTV
    # file could get an unexpected " (1)" suffix on its very first write,
    # even though no smtv_docx file had ever been written for this
    # source before. The team relies on the exact fixed name to find it.
    indexed_planned = [(f, p) for f, p in planned if f != "smtv_docx"]
    # A chapter sidecar belongs to the same numbered set as the transcript
    # outputs, so it takes part in the collision probe too: a re-run must
    # not leave its chapters at the previous run's name while the
    # transcripts move to " (1)".
    want_sidecar = bool(chapters)
    index = 0
    while index < 10000 and (
        any(os.path.exists(_indexed_path(p, index)) for _, p in indexed_planned)
        or (want_sidecar and os.path.exists(_indexed_sidecar_path(base, index)))
    ):
        index += 1

    for fmt_name, rendered in planned:
        path = rendered if fmt_name == "smtv_docx" else _indexed_path(rendered, index)
        # Honour template-supplied subdirectories. Defensive: only
        # makedirs when the dirname is non-empty and differs from the
        # source folder we're already writing into.
        out_dir = os.path.dirname(path)
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError:
                pass
        # Unique .part suffix per pid + thread so two parallel
        # workers transcribing the SAME source file don't race-write
        # to the same .part path (Windows treats the second open as
        # PermissionError because the first writer still holds the
        # handle). os.replace onto the final path remains atomic;
        # the last writer wins for the final file, which matches the
        # POSIX "last writer wins" semantic that callers already
        # expect for redundant parallel transcriptions.
        part_path = (
            f"{path}.{os.getpid()}-{threading.get_ident()}.part"
        )
        try:
            if fmt_name == "smtv_docx":
                # Special case: the SMTV writer needs the detected
                # language + work title beyond the frozen 2-arg writer
                # contract, so call it directly (the registry's 2-arg
                # adapter raises). work_title = source stem; language =
                # the ISO code threaded in via ``lang``.
                from .writers import smtv_docx_writer
                payload_b = smtv_docx_writer.write_bytes(
                    segments_data,
                    audio_path,
                    language=lang,
                    work_title=os.path.basename(base),
                )
                with open(part_path, "wb") as fb:
                    fb.write(payload_b)
            elif is_binary(fmt_name):
                payload_b = get_binary_writer(fmt_name)(segments_data, audio_path)
                with open(part_path, "wb") as fb:
                    fb.write(payload_b)
            else:
                payload_s = get_writer(fmt_name)(segments_data, audio_path)
                with open(part_path, "w", encoding="utf-8", newline="\n") as fs:
                    fs.write(payload_s)
            os.replace(part_path, path)
        except Exception as e:  # noqa: BLE001
            try:
                os.unlink(part_path)
            except OSError:
                pass
            # Isolate per-format failures: one broken writer (a missing
            # optional dependency, or a single format's encoding bug) must
            # NOT discard the formats that wrote fine. Each format is
            # already atomic (os.replace) and indexed (never overwrites a
            # prior run), so there's nothing to roll back — log and move
            # on to the next format.
            logger.warning("output format %r failed: %s", fmt_name, e)
            write_errors.append(f"{fmt_name}: {e}")
            continue
        written.append(path)
    # Requested known formats, but every writer failed (disk full, all
    # writers broken) — surface it so the task doesn't report a silent
    # "wrote 0 files" success.
    if planned and not written:
        raise RuntimeError(
            "All output writers failed; last error: "
            + (write_errors[-1] if write_errors else "unknown")
        )
    # Auto-chapter sidecar: same set, same index. A sidecar failure is
    # non-fatal (chapters are an optional extra, never worth failing the
    # transcript over) — _write_chapter_sidecar returns None on error.
    if want_sidecar:
        sidecar_path = _write_chapter_sidecar(
            _indexed_sidecar_path(base, index), chapters or []
        )
        if sidecar_path:
            written.append(sidecar_path)
    return written


_ALT_BACKEND_LOCK = threading.Lock()
_DEFAULT_BACKEND_LOCK = threading.Lock()


def _deep_merge_dict(dest: dict[str, Any], src: dict[str, Any]) -> None:
    """Recursively merge ``src`` into ``dest`` in place.

    Unlike ``dict.update``, nested dicts are walked depth-first so a
    user override of `{"model": {"name": "tiny"}}` keeps any other
    keys under ``model`` (e.g. ``url``, ``md5``) intact.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dest.get(k), dict):
            _deep_merge_dict(dest[k], v)
        else:
            dest[k] = v


def _get_alt_backend(
    name: str, status_cb: Callable[[str], None] | None = None
) -> Any:
    """Lazy-construct (and load) the alt backend for ``name``.

    Worker processes only need one backend per run, so we cache the
    instance here. The Advanced dialog's "Download model..." button is
    expected to have populated the model file before the user picks
    the matching backend in config. ``status_cb`` surfaces load-time
    progress (e.g. an on-demand cloud-library install) in the worker log.

    Thread-safe: guarded by ``_ALT_BACKEND_LOCK`` so two concurrent
    ``transcribe()`` calls don't both load (and one overwrite the
    other) on first use.
    """
    global _ALT_BACKEND, _ALT_BACKEND_NAME
    with _ALT_BACKEND_LOCK:
        if _ALT_BACKEND is not None and _ALT_BACKEND_NAME == name:
            return _ALT_BACKEND
        from .backends import get_backend
        try:
            backend = get_backend(name)
        except Exception as e:  # noqa: BLE001
            # Mirror load_existing_model's graceful message instead of
            # letting a raw ValueError/KeyError escape transcribe().
            raise RuntimeError(f"Backend {name} not available: {e}") from e
        try:
            loaded = backend.load(status_cb)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{name} load failed: {e}") from e
        if not loaded:
            err = backend.get_error() or f"failed to load {name} backend"
            raise RuntimeError(err)
        _ALT_BACKEND = backend
        _ALT_BACKEND_NAME = name
        return backend


def _ensure_default_backend_loaded(
    status_cb: Callable[[str], None] | None = None,
) -> None:
    """Lazy-load the default faster-whisper model when per-file dispatch needs it.

    ``load_existing_model()`` loads only the STARTUP backend: when the worker
    started on an alt backend, ``MODEL``/``PIPELINE`` stay None while
    ``MODEL_READY`` is True. ``transcribe()``/``resume_transcription()`` then
    re-resolve the backend PER FILE (a project file can override
    ``transcribe_backend``). If that resolves to the default backend, the old
    code sailed through the ``MODEL_READY`` wait and hit
    ``assert MODEL is not None`` (or a None-AttributeError under ``-O``).

    This mirrors ``_get_alt_backend`` for the opposite direction: when the
    default path is taken but ``MODEL`` was never loaded, load it now using
    the same self-healing constructor ``load_existing_model`` uses. Raises
    ``RuntimeError`` with a clear message when the model cannot be loaded.
    Thread-safe via ``_DEFAULT_BACKEND_LOCK`` with double-checked ``MODEL``.
    """
    global MODEL, PIPELINE, MODEL_READY, MODEL_ERROR
    if MODEL is not None:
        return
    with _DEFAULT_BACKEND_LOCK:
        if MODEL is not None:
            return
        # Match load_existing_model()/load_model(): a fresh attempt resets
        # the previous attempt's error, and any failure records a new one.
        # Without this a successful lazy load after a failed one left the
        # stale message visible via get_model_error() (and a RuntimeError
        # from the loader was re-raised without recording anything at all).
        MODEL_ERROR = None
        try:
            model_path = Path(config["model_path"])
        except Exception as e:  # noqa: BLE001
            MODEL_ERROR = f"Model path misconfigured: {e}"
            if status_cb:
                try:
                    status_cb(MODEL_ERROR)
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(MODEL_ERROR) from e
        if not model_path.exists():
            MODEL_ERROR = f"Model folder missing: {model_path}"
            if status_cb:
                try:
                    status_cb(MODEL_ERROR)
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(MODEL_ERROR)
        try:
            if status_cb:
                try:
                    status_cb("Loading existing Whisper model (per-file backend)...")
                except Exception:  # noqa: BLE001
                    pass
            logger.info(
                "model_load backend=faster_whisper model_path=%s "
                "device=%s compute_type=%s (lazy per-file)",
                model_path, device, compute_type,
            )
            MODEL = _load_whisper_model_self_healing(
                str(model_path), device, compute_type, status_cb
            )
            PIPELINE = _wrap_for_batched(MODEL)
            MODEL_READY = True
            if status_cb:
                try:
                    status_cb("Model loaded")
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            MODEL_ERROR = str(e)
            if status_cb:
                try:
                    status_cb(f"Existing model failed to load: {e}")
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(MODEL_ERROR) from e


def _run_post_pipeline(
    task: TranscriptionTask,
    segments_data: list[dict[str, Any]],
    detected_lang: str,
    log_cb: Callable[[str], None] | None,
    progress_cb: Callable[[int], None] | None = None,
) -> int:
    """Diarisation + alignment + speaker_count for the writer.

    Returns the number of distinct speakers detected (0 if
    diarisation is disabled / unavailable / failed). Mutates
    ``segments_data`` in place with speaker labels.
    """
    speaker_count = 0
    if config.get("diarization_enabled", False) and not task.cancelled:
        try:
            from . import diarization as _diar

            if _diar.is_available():
                log("Diarising speakers...", log_cb)
                num_speakers = int(config.get("diarization_num_speakers", -1))
                threshold = float(config.get("diarization_cluster_threshold", 0.5))

                def _diar_progress(fraction: float) -> None:
                    if progress_cb:
                        # Diarisation runs after Whisper inference. Map its 0..1
                        # progress to the 90..99 percent slot so the bar keeps
                        # moving AND the parent's liveness watchdog sees regular
                        # events during this otherwise-silent long-running C call.
                        progress_cb(90 + int(fraction * 9))

                diar_segments = _diar.diarize(
                    task.file_path,
                    num_speakers=num_speakers,
                    cluster_threshold=threshold,
                    progress_cb=_diar_progress,
                )
                _diar.assign_speakers_to_segments(segments_data, diar_segments)
                speakers = sorted({s.speaker for s in diar_segments})
                speaker_count = len(speakers)
                log(f"Diarisation: {len(speakers)} speaker(s) — {', '.join(speakers)}",
                    log_cb)
            else:
                log(f"Diarisation skipped: {_diar.availability_reason()}", log_cb)
        except Exception as e:  # noqa: BLE001
            log(f"Diarisation failed (continuing without speakers): {e}", log_cb)

    # Word-level alignment refinement via stable-ts (opt-in).
    if config.get("alignment", "none") == "stable_ts":
        try:
            from . import alignment as _align
            if _align.is_available():
                log("Refining word timestamps via stable-ts...", log_cb)
                ok = _align.refine_word_timestamps_in_place(
                    task.file_path,
                    segments_data,
                    language=detected_lang or None,
                    log_cb=log_cb,
                )
                if ok:
                    log("Word alignment refined.", log_cb)
                else:
                    # Surfaced as a WARN-style line — alignment was
                    # requested but produced no refinement (most
                    # commonly a tokenizer / language mismatch). The
                    # user sees this in the console; previous code
                    # silently swallowed the skip.
                    log(
                        "WARN: Word alignment requested but stable-ts "
                        "returned no refined words. Keeping original "
                        "word timestamps.",
                        log_cb,
                    )
            else:
                log(
                    f"WARN: Alignment skipped — {_align.availability_reason()}. "
                    "Install stable-ts to enable.",
                    log_cb,
                )
        except Exception as e:  # noqa: BLE001
            log(f"WARN: Alignment failed (continuing without refinement): {e}", log_cb)

    # Hallucination detector (opt-in, default ON). Runs last so it
    # sees the final diarised/aligned text. Any flagged segments get
    # ``suspect=True`` + ``suspect_reason``; the JSON writer carries
    # both fields through to disk (core/writers/json_writer.py) and the
    # transcript viewer renders those segments as red rows.
    if config.get("hallucination_detect_enabled", True):
        try:
            from . import hallucination as _hall
            flagged = _hall.annotate_segments(segments_data)
            if flagged:
                log(
                    f"Hallucination detector flagged {flagged} segment(s) "
                    "as suspect — open the transcript viewer to review.",
                    log_cb,
                )
        except Exception as e:  # noqa: BLE001
            log(f"Hallucination detector failed (continuing): {e}", log_cb)

    # Auto-chapter detection (v0.8 Phase 3). Pure heuristic by
    # default; if the LLM is enabled + loaded, chapter titles are
    # LLM-generated. Chapters land in a sidecar JSON next to the
    # other writer outputs (``<base>.chapters.json``) so existing
    # writers (SRT / VTT / TXT / JSON) keep their shape and the
    # viewer / external tools can read chapters independently.
    task._chapters_for_writer = []  # type: ignore[attr-defined]
    if config.get("auto_chapters_enabled", True) and not task.cancelled:
        try:
            from contextlib import nullcontext

            from . import chapters as _chap
            runner = _maybe_get_llm_runner()
            # LLM chapter-title generation is a silent, GIL-holding C call
            # (llama-cpp). Unlike Demucs / alignment / whisper.cpp it emitted
            # no periodic event, so a slow generation on weak hardware could
            # exceed the parent's 120 s liveness watchdog and get the worker
            # restarted mid-chapter. Tick while the LLM runs (audit P2-32);
            # the pure-heuristic path (runner is None) is fast — no tick.
            from ._liveness_tick import liveness_tick
            tick = (
                liveness_tick(log_cb, "chapter titles")
                if runner is not None
                else nullcontext()
            )
            with tick:
                chapter_list = _chap.build_chapters(
                    segments_data,
                    runner=runner,
                    min_chapter_seconds=float(config.get("chapter_min_seconds", 60.0)),
                    gap_seconds=float(config.get("chapter_gap_seconds", 2.5)),
                )
            if chapter_list:
                task._chapters_for_writer = chapter_list  # type: ignore[attr-defined]
                log(
                    f"Detected {len(chapter_list)} chapter(s) in the transcript.",
                    log_cb,
                )
        except Exception as e:  # noqa: BLE001
            log(f"Auto-chapter detection failed (continuing): {e}", log_cb)

    return speaker_count


def _maybe_get_llm_runner() -> Any | None:
    """Return a loaded LLM runner when the AI Layer is on, else None.

    Delegates to core.llm.build_runner_from_config, which also honours
    ``llm_provider`` ("local" Qwen vs. a "remote" OpenAI-compatible
    endpoint) — so a chapter-titling pass benefits from whichever
    provider the user configured, the same as the transcript viewer's
    AI panel. Wraps every failure mode (dep missing, model file
    missing, load error) so a broken LLM never blocks transcription.
    """
    try:
        from . import llm as _llm
        return _llm.build_runner_from_config(config)
    except Exception:  # noqa: BLE001
        return None


def _indexed_sidecar_path(base: str, index: int) -> str:
    """Path for a ``<base>.chapters.json`` sidecar at the shared index.

    Built by appending ``" (N)"`` to the base — NOT by feeding the full
    ``<base>.chapters.json`` name through :func:`_indexed_path`, which
    splits on the last dot and would produce ``.chapters (1).json``
    instead of ``(1).chapters.json``. ``index <= 0`` is the first,
    unsuffixed write.
    """
    suffix = f" ({index})" if index > 0 else ""
    return f"{base}{suffix}.chapters.json"


def _write_chapter_sidecar(path: str, chapters: list[dict[str, Any]]) -> str | None:
    """Write the auto-chapter sidecar atomically. Returns *path* or None.

    *path* is the full target (``<base>.chapters.json`` or the shared
    index's ``<base> (N).chapters.json`` — see
    :func:`_indexed_sidecar_path`) so the sidecar can travel with the
    transcript outputs' collision index.
    """
    if not chapters:
        return None
    import json as _json
    part = f"{path}.{os.getpid()}-{threading.get_ident()}.part"
    try:
        with open(part, "w", encoding="utf-8", newline="\n") as f:
            _json.dump(chapters, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(part, path)
    except Exception:
        try:
            os.unlink(part)
        except OSError:
            pass
        return None
    return path


# Keys ``_apply_runtime_overrides`` unconditionally fills into the shared
# module ``config`` when absent. _runtime_overrides_scope MUST snapshot
# these too (not just the override's own keys) or they leak into every
# later file the long-lived worker handles (audit P2-29 / the residual of
# P0-6): a file processed after one whose project file enabled diarisation
# could inherit diarisation defaults materialised during that run.
_RUNTIME_OVERRIDE_DEFAULTS: tuple[tuple[str, Any], ...] = (
    ("diarization_enabled", False),
    ("diarization_num_speakers", -1),
    ("diarization_cluster_threshold", 0.5),
    ("alignment", "none"),
)


def _coerce_bool_value(value: Any) -> bool:
    """Parse a config override into bool without the ``bool("false")`` trap.

    ``bool("false")`` is True in Python, so a project file setting
    ``"diarization_enabled": "false"`` (string) would silently ENABLE the
    feature. Accept common string spellings explicitly; raise ValueError
    for unrecognised strings so the caller can report a clear per-file
    error instead of guessing.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "y", "on", "enabled"):
            return True
        if text in ("0", "false", "no", "n", "off", "disabled", ""):
            return False
        raise ValueError(f"cannot interpret {value!r} as bool")
    if isinstance(value, (list, dict)):
        raise ValueError(f"cannot interpret {value!r} as bool")
    return bool(value)


# Remaining scalar (bool/int/float) config keys the transcriber reads later
# in the per-file path with bare int()/float()/`bool()`/truthiness. A
# project override arrives as raw JSON, so a typo like
# ``"batch_size": "big"`` previously raised a raw builtin exception deep
# inside transcribe(), and ``"vad_enabled": "false"`` / ``"demucs_enabled":
# "false"`` silently inverted the setting (bool("false") is True). The F5
# fix closed the diarisation/alignment coercions in
# _apply_runtime_overrides; this closes the same class for the remaining
# scalar keys, at the same choke point, so a bad override fails as a clear
# per-file RuntimeError before any work starts.
_OVERRIDE_SCALAR_COERCIONS: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("batch_size", "int", int),
    ("vad_min_silence_ms", "int", int),
    ("vad_speech_pad_ms", "int", int),
    ("vad_threshold", "float", float),
    ("vad_enabled", "bool", _coerce_bool_value),
    ("word_timestamps", "bool", _coerce_bool_value),
    ("demucs_enabled", "bool", _coerce_bool_value),
    ("denoise_enabled", "bool", _coerce_bool_value),
    ("auto_chapters_enabled", "bool", _coerce_bool_value),
    ("hallucination_detect_enabled", "bool", _coerce_bool_value),
)


def _apply_runtime_overrides(task: "TranscriptionTask") -> dict[str, Any]:
    """Apply per-folder overrides + refresh diarisation defaults.

    Mutates the module-level ``config`` dict in place (existing
    contract). Returns the freshly-loaded ``runtime_cfg`` so callers
    that need it (backend-name resolution) don't have to call
    ``load_config()`` twice.

    Extracted from ``transcribe()`` (audit A6 / MR-03). Keeping the
    side-effects on ``config`` preserves backwards compat with
    tests that monkeypatch ``transcriber.config``.
    """
    runtime_cfg = load_config()
    project_overrides: dict[str, Any] = {}
    try:
        from .config import load_project_overrides
        project_overrides = load_project_overrides(task.file_path)
        for k, v in project_overrides.items():
            if isinstance(v, dict) and isinstance(config.get(k), dict):
                _deep_merge_dict(config[k], v)
            else:
                config[k] = v
    except Exception:
        logger.exception("project-overrides load raised for %s", task.file_path)

    for key, default in _RUNTIME_OVERRIDE_DEFAULTS:
        if key not in config:
            config[key] = runtime_cfg.get(key, default)
    # Project overrides arrive as raw JSON: a value like
    # "diarization_num_speakers": "auto" would previously raise a bare
    # ValueError out of transcribe(), failing the worker call with a raw
    # traceback. Wrap each coercion so an invalid value becomes a clear,
    # per-file RuntimeError (recoverable: the worker marks this file failed
    # and continues) instead of a raw int()/float() exception.
    try:
        config["diarization_enabled"] = _coerce_bool_value(
            config["diarization_enabled"]
        )
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            f"Invalid project override for 'diarization_enabled': "
            f"{config.get('diarization_enabled')!r} (expected bool): {e}"
        ) from e
    try:
        config["diarization_num_speakers"] = int(
            config["diarization_num_speakers"]  # type: ignore[arg-type]
        )
    # OverflowError too: JSON's ``1e999`` parses to float('inf'), and
    # int(inf) raises it. The R2 scalar table already catches OverflowError;
    # this original coercion predates that and was the last hole (R2's
    # self-critique declined it believing JSON could not express it).
    except (ValueError, TypeError, OverflowError) as e:
        raise RuntimeError(
            f"Invalid project override for 'diarization_num_speakers': "
            f"{config.get('diarization_num_speakers')!r} (expected int): {e}"
        ) from e
    try:
        config["diarization_cluster_threshold"] = float(
            config["diarization_cluster_threshold"]  # type: ignore[arg-type]
        )
    # OverflowError too: a huge integer JSON literal parses to an
    # arbitrary-precision int, and float(huge_int) raises it.
    except (ValueError, TypeError, OverflowError) as e:
        raise RuntimeError(
            f"Invalid project override for 'diarization_cluster_threshold': "
            f"{config.get('diarization_cluster_threshold')!r} (expected float): {e}"
        ) from e
    try:
        config["alignment"] = str(config["alignment"])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Invalid project override for 'alignment': "
            f"{config.get('alignment')!r} (expected str): {e}"
        ) from e
    # Scalar keys consumed later with bare int()/float()/truthiness (see
    # _OVERRIDE_SCALAR_COERCIONS). Only keys the project file actually set
    # are validated: the F5 threat model is raw-JSON project overrides, and
    # the app-level config is typed by the settings UI. A successful
    # coercion is restored by _runtime_overrides_scope like any other
    # override key.
    if isinstance(project_overrides, dict):
        for key, expected, caster in _OVERRIDE_SCALAR_COERCIONS:
            if key not in project_overrides:
                continue
            try:
                config[key] = caster(config.get(key))
            except (ValueError, TypeError, OverflowError) as e:
                raise RuntimeError(
                    f"Invalid project override for '{key}': "
                    f"{config.get(key)!r} (expected {expected}): {e}"
                ) from e
    return runtime_cfg


@contextmanager
def _runtime_overrides_scope(
    task: "TranscriptionTask",
) -> Iterator[dict[str, Any]]:
    """Apply per-folder ``.whisperproject.json`` overrides for one
    file, then restore ``config`` to its pre-override state.

    The worker subprocess is long-lived: it transcribes many files
    in sequence reusing the module-level ``config`` dict. Before
    this scope existed, ``_apply_runtime_overrides`` would mutate
    ``config`` in place with the keys from a file's nearest project
    file — and those mutations leaked into every later file the
    worker handled. Example: file A in ``/A`` sets
    ``diarization_enabled=true`` via its project file; file B in
    ``/B`` (no project file) then inherited diarisation silently.
    Same shape for any other key an override can set
    (``output_formats``, ``transcribe_language``, ``whisper_model``,
    …) — audit P0-6.

    The fix: snapshot exactly the keys the override is about to
    write (read from disk before applying), then on exit put each
    one back to its pre-override value. Keys that didn't exist in
    ``config`` before the override are removed on exit. We snapshot
    ONLY the keys the override touches — not the whole ``config`` —
    so the restore is precise and doesn't fight with the
    unconditional diarisation-default block at the tail of
    ``_apply_runtime_overrides``.

    Yields the freshly-loaded ``runtime_cfg`` so callers don't have
    to call ``load_config()`` a second time.
    """
    from .config import load_project_overrides

    snapshot: dict[str, Any] = {}
    added_keys: set[str] = set()
    try:
        try:
            overrides = load_project_overrides(task.file_path)
        except Exception:  # noqa: BLE001
            # ``_apply_runtime_overrides`` has its own try/except for
            # the same call; mirror it so a corrupt project file never
            # blocks a transcription. Empty overrides means no
            # snapshot and no restore needed.
            logger.exception(
                "project-overrides snapshot raised for %s", task.file_path,
            )
            overrides = {}

        # Raw-JSON guard (F5 class): a corrupt project file can decode to
        # valid JSON that is not a dict (`null`, `5`, `[...]`). The load
        # above only catches *raised* errors, and `_apply_runtime_overrides`
        # already treats a non-dict as "no overrides" (its `.items()` call
        # fails into the logged except). Mirror that here: without this,
        # `set(None)` / `set(5)` / `set([[...]])` raise a raw TypeError out
        # of the per-file path before any work starts.
        if not isinstance(overrides, dict):
            logger.warning(
                "project-overrides for %s is not a dict (%s); ignoring",
                task.file_path, repr(overrides)[:200],
            )
            overrides = {}

        # Track the override's own keys AND the diarisation/alignment keys
        # _apply_runtime_overrides unconditionally fills — both must be
        # restored on exit or they leak into the next file (audit P2-29).
        keys_to_track = set(overrides) | {k for k, _ in _RUNTIME_OVERRIDE_DEFAULTS}
        for key in keys_to_track:
            if key in config:
                value = config[key]
                if isinstance(value, dict):
                    # Deep-copy nested dicts so a later
                    # ``_deep_merge_dict`` on ``config[key]`` doesn't
                    # also mutate our snapshot value (same dict id).
                    snapshot[key] = copy.deepcopy(value)
                else:
                    snapshot[key] = value
            else:
                added_keys.add(key)

        runtime_cfg = _apply_runtime_overrides(task)
        yield runtime_cfg
    finally:
        for key, value in snapshot.items():
            config[key] = value
        for key in added_keys:
            config.pop(key, None)


def _build_transcribe_kwargs(task: "TranscriptionTask") -> dict[str, Any]:
    """Assemble the kwargs dict passed to WhisperModel.transcribe.

    Reads from the module-level ``config`` so monkeypatched tests
    continue to drive behaviour. Pure-ish: never raises, never
    mutates ``config``.
    """
    want_words = bool(config.get("word_timestamps", False))
    kwargs: dict[str, Any] = {
        "vad_filter": _vad_parameters() is not None,
        "word_timestamps": want_words,
    }
    if kwargs["vad_filter"]:
        kwargs["vad_parameters"] = _vad_parameters()
    # Normalise here: this is the central kwargs builder for the default
    # faster-whisper path. The language picker / a download's detected
    # language can carry BCP-47 region tags or multi-value yt-dlp codes
    # ("en-US", "zh-Hans,zh-CN", "pt,pt-BR,pt-PT") that faster-whisper
    # rejects with a ValueError (silent no-output). Coerce to a single
    # accepted ISO code, or None (auto-detect).
    forced_lang = _normalize_language(getattr(task, "language", None))
    if forced_lang:
        kwargs["language"] = forced_lang
    initial_prompt = config.get("initial_prompt") or None
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    hotwords = config.get("hotwords") or None
    if hotwords:
        kwargs["hotwords"] = hotwords
    return kwargs


def transcribe_chunk_to_text(
    audio_path: str,
    *,
    language: str | None = None,
    timeout_wait_model_s: float = 120.0,
) -> dict[str, Any]:
    """Transcribe one short chunk and return its text — nothing else.

    The Live tab's hot path. Deliberately NOT :func:`transcribe`: that
    writes up to 13 output files, takes a resume checkpoint, and runs the
    post-pipeline (diarisation, alignment, chapters). Doing all that
    every few seconds for a 6-second chunk would be wasteful, would spray
    files across the disk, and — if the user happens to have diarisation
    enabled — would make live transcription unusably slow.

    Returns ``{"text", "segments", "language", "language_probability"}``.
    ``segments`` are chunk-relative (the caller shifts them onto the
    session timeline; the chunk has no idea when it was recorded).

    Raises ``RuntimeError`` if the model never becomes ready — the caller
    surfaces that once rather than per chunk.
    """
    deadline = time.time() + max(0.0, timeout_wait_model_s)
    while not MODEL_READY:
        if MODEL_ERROR:
            raise RuntimeError(MODEL_ERROR)
        if time.time() >= deadline:
            raise RuntimeError("Model is still loading; live transcription "
                               "cannot start yet.")
        time.sleep(0.1)
    if MODEL is None:
        raise RuntimeError("Model is not loaded.")

    task = TranscriptionTask(audio_path)
    if language:
        task.language = language
    kwargs = _build_transcribe_kwargs(task)
    # A live chunk is already a bounded utterance; word timestamps and
    # batching only add latency here.
    kwargs.pop("batch_size", None)
    kwargs["word_timestamps"] = False

    segments_iter, info = MODEL.transcribe(audio_path, **kwargs)
    out: list[dict[str, Any]] = []
    parts: list[str] = []
    for seg in segments_iter:
        text = str(getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(getattr(seg, "start", 0.0) or 0.0),
            "end": float(getattr(seg, "end", 0.0) or 0.0),
            "text": text,
        })
        parts.append(text)
    return {
        "text": " ".join(parts).strip(),
        "segments": out,
        "language": str(getattr(info, "language", "") or ""),
        "language_probability": float(
            getattr(info, "language_probability", 0.0) or 0.0
        ),
    }


def _clip_timestamps_arg(task: TranscriptionTask) -> str | None:
    """Clip marker for a Transcribe-tab time slice, or None for the whole file.

    Returns "start,end" (process only that span) or "start" (from start to
    the end of the file). Despite the historical name, the value is NOT
    passed to faster-whisper as ``clip_timestamps`` (that decodes the whole
    file and hung on multi-hour input) — it only marks a clipped task so
    the run pre-slices the span with ffmpeg (see ``_clip_slice_path``
    below). A zero/blank bound means "unset" on that side, so
    leaving both = the whole file (None).
    """
    start = getattr(task, "clip_start", None)
    end = getattr(task, "clip_end", None)
    start_s = float(start) if start else 0.0
    end_s = float(end) if end else 0.0
    if start_s <= 0.0 and end_s <= 0.0:
        return None
    if end_s > start_s:
        return f"{start_s},{end_s}"
    return f"{start_s}"


def _shift_segments(segments: Any, offset: float) -> Any:
    """Yield faster-whisper segments shifted by ``+offset`` seconds.

    Used by the time-range path: we transcribe a PRE-SLICED span (whose times
    start at 0) and shift the results back onto the ORIGINAL file timeline by
    ``clip_start``. faster_whisper segments are NamedTuples, so we ``_replace``
    start/end (and each word's start/end) without mutating the engine's objects.
    """
    for s in segments:
        words = getattr(s, "words", None)
        if words:
            try:
                words = [
                    w._replace(start=w.start + offset, end=w.end + offset)
                    for w in words
                ]
            except Exception:  # noqa: BLE001 — best-effort word shift
                pass
        try:
            yield s._replace(start=s.start + offset, end=s.end + offset, words=words)
        except Exception:  # noqa: BLE001 — non-NamedTuple fallback
            try:
                s.start = s.start + offset
                s.end = s.end + offset
            except Exception:  # noqa: BLE001
                pass
            yield s


def transcribe(
    task: TranscriptionTask,
    progress_cb: Callable[[int], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
    language_cb: Callable[[str, float], None] | None = None,
) -> None:
    # QW-12 / audit B6: prefix every log message with the source
    # file basename so parallel-worker output stays attributable.
    # We wrap log_cb at the top of transcribe so every downstream
    # call (including the alt-backend dispatcher) inherits the
    # prefix without each call site having to manage it.
    log_cb = _with_task_prefix(log_cb, task)
    # Wrap the per-file work in ``_runtime_overrides_scope`` so any
    # ``.whisperproject.json`` mutation of the module-level ``config``
    # is reverted before the next file runs (audit P0-6). The scope
    # also returns the freshly-loaded ``runtime_cfg`` so the backend
    # dispatch below can read it without a second ``load_config``.
    with _runtime_overrides_scope(task) as runtime_cfg:
        # Backend dispatch — when the user has chosen a non-default
        # engine via config["transcribe_backend"], delegate to a backend
        # implementation. The original faster_whisper code below remains
        # the default path so the existing unit + smoke tests keep
        # working without monkeypatch churn.
        backend_name = (
            str(config.get("transcribe_backend")
                or runtime_cfg.get("transcribe_backend")
                or "faster_whisper").strip().lower()
        )
        logger.info(
            "transcribe_backend=%s file=%s",
            backend_name, task.file_path,
        )
        if backend_name and backend_name != "faster_whisper":
            _transcribe_via_alt_backend(
                backend_name, task, progress_cb, log_cb, language_cb
            )
            return

        global MODEL
        while not MODEL_READY:
            if MODEL_ERROR:
                raise RuntimeError(MODEL_ERROR)
            time.sleep(0.5)

        # Per-file backend re-resolution above can select the default
        # backend even when the worker started on an alt backend (in which
        # case MODEL is still None but MODEL_READY is True). Lazy-load the
        # default model now instead of crashing on `assert MODEL is not None`.
        _ensure_default_backend_loaded(log_cb)

        # Optional Demucs vocal-separation pre-process (v0.8 Phase 2).
        # Returns the input path unchanged when demucs isn't installed or
        # the feature is off, so this is safe to always call.
        audio_path = task.file_path
        if config.get("demucs_enabled", False):
            try:
                from . import separator as _sep
                audio_path = _sep.separate_vocals(
                    task.file_path,
                    enabled=True,
                    log=log_cb,
                )
            except Exception as e:  # noqa: BLE001
                log(f"Demucs separation failed (using original audio): {e}", log_cb)
                audio_path = task.file_path

        duration = get_duration(audio_path)
        start = time.time()
        log(f"Processing: {audio_path}", log_cb)

        assert MODEL is not None
        want_words = bool(config.get("word_timestamps", False))

        transcribe_kwargs = _build_transcribe_kwargs(task)
        # Optional time-slice (Transcribe-tab time range): process only
        # [clip_start, clip_end]. The string below is just a clip-present
        # marker (the actual span is pre-sliced with ffmpeg further down,
        # never passed as clip_timestamps). The batched pipeline can't be
        # used for a clipped task, so it falls back to the plain model
        # (still fast for a short slice).
        clip = _clip_timestamps_arg(task)
        use_batched = PIPELINE is not None and clip is None
        runner: Any = PIPELINE if use_batched else MODEL
        if use_batched:
            transcribe_kwargs["batch_size"] = int(config.get("batch_size", 16))
        # NOTE: a time range is NOT passed as clip_timestamps (that makes
        # faster-whisper decode the WHOLE file — it hung on a multi-hour
        # input). It is handled by pre-slicing just below; see _clip_slice_path.

        # Progress is measured against the clip span — segment timestamps
        # stay on the original timeline, so without this the bar would
        # barely move when slicing a few minutes out of a long file.
        _clip_start_s = float(getattr(task, "clip_start", None) or 0.0)
        _clip_end_v = getattr(task, "clip_end", None)
        progress_span = (
            float(_clip_end_v) - _clip_start_s
            if (_clip_end_v and float(_clip_end_v) > _clip_start_s)
            else duration
        )

        # Time range: pre-slice the [clip_start, clip_end] span with a fast
        # ffmpeg -ss seek and transcribe ONLY that slice — not clip_timestamps,
        # which decodes the whole file (it hung on a multi-hour input). The
        # slice is only read during runner.transcribe(); delete it right after.
        # Results are shifted back by +clip_start to stay on the original
        # timeline, and outputs keep the original file's base name.
        _ts_offset = 0.0
        _clip_slice_path = ""
        if clip is not None:
            # Guard: a start at/after the media duration would slice nothing —
            # surface a clear error instead of silently writing an empty output.
            if duration and _clip_start_s >= float(duration):
                raise RuntimeError(
                    f"Time range start ({_clip_start_s:.0f}s) is at or beyond "
                    f"the media length ({float(duration):.0f}s) — nothing to "
                    "transcribe. Pick an earlier start."
                )
            _clip_end_arg = (
                float(_clip_end_v)
                if (_clip_end_v and float(_clip_end_v) > _clip_start_s)
                else None
            )
            _clip_slice_path = _slice_audio_from(
                audio_path, _clip_start_s, _checkpoint.partials_dir(),
                end_seconds=_clip_end_arg,
            )
            audio_path = _clip_slice_path
            _ts_offset = _clip_start_s

        # Adaptive denoise, after any clip slice so a time range only pays
        # for the span it actually transcribes. A clipped run denoises the
        # slice (transient, uncached); a full run denoises + caches the file.
        audio_path, _denoise_tmp = _maybe_denoise(
            audio_path,
            duration=progress_span or duration,
            transient=bool(_clip_slice_path),
            log_cb=log_cb,
        )

        try:
            segments, info = runner.transcribe(audio_path, **transcribe_kwargs)
        except BaseException:
            # If the backend fails before returning its lazy segment iterator,
            # the temporary inputs are still ours to clean up immediately.
            for _tmp in (_clip_slice_path, _denoise_tmp):
                if not _tmp:
                    continue
                try:
                    os.remove(_tmp)
                except OSError:
                    pass
            raise
        if _ts_offset:
            segments = _shift_segments(segments, _ts_offset)

        if getattr(info, "language", None):
            lang_code = str(info.language)
            lang_prob = float(getattr(info, "language_probability", 0.0))
            # Audit B10: warn the user when language detection was a
            # low-confidence guess. Whisper has been known to return
            # "Welsh" at 5 % confidence for ambient noise; downstream
            # tools then tag the SRT with the wrong language code.
            if lang_prob < 0.5:
                log(
                    f"WARN: detected language={lang_code} with low confidence "
                    f"({lang_prob:.0%}). The output language tag may be wrong.",
                    log_cb,
                )
                logger.warning(
                    "language_detection_low_confidence file=%s language=%s "
                    "probability=%.3f",
                    task.file_path, lang_code, lang_prob,
                )
            if language_cb:
                try:
                    language_cb(lang_code, lang_prob)
                except Exception:
                    logger.exception("language_cb raised")
            if hasattr(task, "detected_language"):
                task.detected_language = lang_code
                task.language_probability = lang_prob

        base = os.path.splitext(task.file_path)[0]

        # Resume support: periodic checkpoint cadence. Track the
        # wall-clock time of the last write and the segment count
        # since the last write; whichever threshold fires first
        # triggers a new write. See module constants for the values.
        last_checkpoint_time = time.time()
        segments_since_checkpoint = 0
        detected_lang_so_far = str(getattr(info, "language", "") or "")
        lang_prob_so_far = float(getattr(info, "language_probability", 0.0) or 0.0)

        segments_data: list[dict[str, Any]] = []

        def _handle_cancelled() -> bool:
            if not task.cancelled:
                return False
            # A cancellation can arrive after the final segment, or an empty
            # iterator can finish after cancellation. Preserve resumable work
            # and never turn that request into a successful empty output.
            if segments_data and clip is None:
                _write_periodic_checkpoint(
                    task,
                    segments_data,
                    float(segments_data[-1].get("end", 0.0)),
                    detected_lang_so_far,
                    lang_prob_so_far,
                    log_cb,
                )
            log("Task cancelled", log_cb)
            return True

        try:
            # faster-whisper returns a lazy generator. Keep the slice alive
            # until iteration finishes, not merely until transcribe() returns.
            for seg in segments:
                if _handle_cancelled():
                    return
                while task.paused and not task.cancelled:
                    time.sleep(0.2)
                if _handle_cancelled():
                    return

                percent = (
                    min(100, max(0, int(((seg.end - _clip_start_s) / progress_span) * 100)))
                    if progress_span else 0
                )
                msg = f"[{percent}%] {fmt(seg.start)} --> {fmt(seg.end)} | {(seg.text or '').strip()}"
                log(msg, log_cb)

                if progress_cb:
                    progress_cb(percent)

                segments_data.append(_segment_to_dict(seg, want_words))
                segments_since_checkpoint += 1

                now = time.time()
                # No checkpoints for a clipped run: the checkpoint is keyed to
                # the whole file with no clip marker, so a later resume would
                # transcribe past clip_end. Clips are short — no resume needed.
                if clip is None and (
                    segments_since_checkpoint >= _CHECKPOINT_EVERY_N_SEGMENTS
                    or (now - last_checkpoint_time) >= _CHECKPOINT_EVERY_N_SECONDS
                ):
                    _write_periodic_checkpoint(
                        task,
                        segments_data,
                        float(seg.end),
                        detected_lang_so_far,
                        lang_prob_so_far,
                        log_cb,
                    )
                    last_checkpoint_time = now
                    segments_since_checkpoint = 0
        finally:
            # The iterator may perform the real decode during iteration, so
            # remove the temporary inputs only after the loop is finished (or
            # if iteration/cancellation raises).
            _close_iterator_quietly(segments)
            for _tmp in (_clip_slice_path, _denoise_tmp):
                if not _tmp:
                    continue
                try:
                    os.remove(_tmp)
                except OSError:
                    pass

        if _handle_cancelled():
            return

        # Speaker diarization (opt-in) + word-level alignment (opt-in).
        detected_lang = str(getattr(info, "language", "") or "")
        speaker_count = _run_post_pipeline(task, segments_data, detected_lang, log_cb, progress_cb)

        if _handle_cancelled():
            return

        written = _write_outputs(
            base,
            segments_data,
            task.file_path,
            getattr(task, "output_formats", None),
            lang=detected_lang,
            speaker_count=speaker_count,
            chapters=getattr(task, "_chapters_for_writer", None) or [],
        )
        # Hand the real written paths to the UI (history + Last-result
        # card) so it never has to re-derive names from config — that
        # missed docx/pdf and the de-duped "name (1).srt" form.
        task.output_paths = list(written)
        _record_transcript_stats(task, segments_data)
        log(f"Wrote {len(written)} output file(s): {', '.join(os.path.basename(p) for p in written)}",
            log_cb)

        # On success the partial is no longer useful — delete it so
        # the next "Re-run" doesn't accidentally resume from a stale
        # checkpoint of the previous (now-complete) run. Only for a
        # whole-file run: a clipped run never writes a checkpoint (keyed
        # to the whole file with no clip marker), so deleting here would
        # wipe an unrelated partial from a cancelled whole-file job.
        if clip is None:
            _checkpoint.delete_checkpoint(task.file_path)

        if progress_cb:
            progress_cb(100)

        elapsed = time.time() - start
        log(f"Done in {elapsed:.2f}s", log_cb)


def _transcribe_via_alt_backend(
    backend_name: str,
    task: TranscriptionTask,
    progress_cb: Callable[[int], None] | None,
    log_cb: Callable[[str], None] | None,
    language_cb: Callable[[str, float], None] | None,
) -> None:
    """Drive a non-default backend through the same writers + diarisation."""
    backend = _get_alt_backend(backend_name, log_cb)

    # Demucs vocal separation — mirror the default faster-whisper path
    # (transcribe() lines 1761-1771). Without this, an alt-backend run
    # with demucs_enabled=true silently transcribes the raw mix while
    # the config fingerprint records demucs as enabled, producing the
    # same conditioning-mismatch class as F4's resume bug.
    audio_path = task.file_path
    if config.get("demucs_enabled", False):
        try:
            from . import separator as _sep
            audio_path = _sep.separate_vocals(
                task.file_path,
                enabled=True,
                log=log_cb,
            )
        except Exception as e:  # noqa: BLE001
            log(f"Demucs separation failed (using original audio): {e}", log_cb)
            audio_path = task.file_path

    duration = get_duration(audio_path)
    start = time.time()
    log(f"Processing ({backend_name}): {task.file_path}", log_cb)

    want_words = bool(config.get("word_timestamps", False))
    vad_params = _vad_parameters()

    # Optional Transcribe-tab time range. Alt backends have no
    # clip_timestamps parameter (see core/backends/base.py), so honour a
    # clip by transcribing a sliced temp WAV and shifting the returned
    # segments back onto the original timeline (mirrors the resume path).
    # Without this a clipped alt-backend run silently transcribed AND
    # wrote the WHOLE file. A clipped run takes no checkpoint — the
    # checkpoint is keyed to the whole file with no clip marker.
    clip_start_s = float(getattr(task, "clip_start", None) or 0.0)
    _clip_end_v = getattr(task, "clip_end", None)
    clip_end_s = float(_clip_end_v) if _clip_end_v else 0.0
    is_clipped = clip_start_s > 0.0 or clip_end_s > 0.0
    # Same guard as the faster-whisper path: a start at/after the media
    # duration would slice an empty temp WAV, and the backend would then
    # "succeed" with zero segments and write empty output files. Fail
    # loudly instead (duration is still the SOURCE's — it is remapped to
    # the slice just below).
    if is_clipped and duration and clip_start_s >= float(duration):
        raise RuntimeError(
            f"Time range start ({clip_start_s:.0f}s) is at or beyond "
            f"the media length ({float(duration):.0f}s) — nothing to "
            "transcribe. Pick an earlier start."
        )
    transcribe_path = audio_path
    slice_to_clean: str | None = None
    if is_clipped:
        try:
            slice_to_clean = _slice_audio_from(
                audio_path,
                clip_start_s,
                _checkpoint.partials_dir(),
                end_seconds=(clip_end_s if clip_end_s > clip_start_s else None),
            )
        except RuntimeError as e:
            raise RuntimeError(
                f"Could not extract the selected time range for the "
                f"{backend_name} backend: {e}"
            ) from e
        transcribe_path = slice_to_clean
        # Progress + duration now measure the slice, not the whole file.
        duration = (
            clip_end_s - clip_start_s
            if clip_end_s > clip_start_s
            else max(0.0, duration - clip_start_s)
        )

    # Noise hurts every engine, not just faster-whisper — whisper.cpp and
    # the cloud backends get the same pre-process.
    transcribe_path, denoise_to_clean = _maybe_denoise(
        transcribe_path,
        duration=duration,
        transient=bool(slice_to_clean),
        log_cb=log_cb,
    )

    try:
        segments_data, lang_info = backend.transcribe_to_segments(
            transcribe_path,
            language=_normalize_language(getattr(task, "language", None)),
            want_words=want_words,
            vad_parameters=vad_params,
            initial_prompt=config.get("initial_prompt") or None,
            hotwords=config.get("hotwords") or None,
            batch_size=int(config.get("batch_size", 16)),
            progress_cb=progress_cb,
            log_cb=log_cb,
            cancelled=lambda: bool(task.cancelled),
            paused=lambda: bool(task.paused),
            duration=duration,
        )
        # Shift slice-relative timestamps back onto the original timeline.
        if is_clipped:
            _offset_segments(segments_data, clip_start_s)
    finally:
        for _tmp in (slice_to_clean, denoise_to_clean):
            if not _tmp:
                continue
            try:
                os.unlink(_tmp)
            except OSError:
                pass

    if lang_info.language:
        if language_cb:
            try:
                language_cb(lang_info.language, lang_info.probability)
            except Exception:  # noqa: BLE001
                pass
        if hasattr(task, "detected_language"):
            task.detected_language = lang_info.language
            task.language_probability = lang_info.probability

    if task.cancelled:
        # Alt-backend gives us the segments list as a single return —
        # if it returned a partial on cancellation, persist what we
        # got so the user can resume. Same shape as the main path's
        # final-flush. Skipped for a clipped run (no resumable
        # checkpoint — it would be keyed to the whole file).
        if segments_data and not is_clipped:
            _write_periodic_checkpoint(
                task,
                segments_data,
                float(segments_data[-1].get("end", 0.0)),
                str(lang_info.language or ""),
                float(getattr(lang_info, "probability", 0.0) or 0.0),
                log_cb,
            )
        log("Task cancelled", log_cb)
        return

    # Single checkpoint right after the backend returns — covers a
    # crash during the post-pipeline (diarisation can run for
    # minutes on long files). Skipped for a clipped run.
    if segments_data and not is_clipped:
        _write_periodic_checkpoint(
            task,
            segments_data,
            float(segments_data[-1].get("end", 0.0)),
            str(lang_info.language or ""),
            float(getattr(lang_info, "probability", 0.0) or 0.0),
            log_cb,
        )

    base = os.path.splitext(task.file_path)[0]
    # Defensive str cast: backends may emit None for language when
    # they couldn't detect. The faster_whisper path already
    # normalises via str(getattr(info, "language", "") or "")
    # at the call site — mirror that defensive style here so
    # downstream consumers (writer template, post-pipeline) never
    # see "None" as a stringified language code.
    detected_lang = str(lang_info.language or "")
    speaker_count = _run_post_pipeline(task, segments_data, detected_lang, log_cb, progress_cb)

    # Cancellation can arrive while the post-pipeline runs — diarisation on
    # a long file takes minutes, which is exactly why a checkpoint is
    # written above before it starts. Mirror transcribe() and
    # resume_transcription(): a cancelled run must not write successful
    # outputs or delete the checkpoint that still holds its partial work.
    # (The checkpoint write above already persisted the whole-file partial;
    # a clipped run never has one.)
    if task.cancelled:
        log("Task cancelled", log_cb)
        return

    written = _write_outputs(
        base,
        segments_data,
        task.file_path,
        getattr(task, "output_formats", None),
        lang=detected_lang,
        speaker_count=speaker_count,
        chapters=getattr(task, "_chapters_for_writer", None) or [],
    )
    task.output_paths = list(written)
    _record_transcript_stats(task, segments_data)
    log(
        f"Wrote {len(written)} output file(s): "
        f"{', '.join(os.path.basename(p) for p in written)}",
        log_cb,
    )
    # Success — drop the partial. Only for a whole-file run: a clipped
    # run never writes a checkpoint, so deleting would wipe an unrelated
    # whole-file partial (same key, no clip marker).
    if not is_clipped:
        _checkpoint.delete_checkpoint(task.file_path)
    # Cloud backend only: accumulate the transcribed minutes locally so
    # the Advanced dialog can show usage. The dollar free-credit balance
    # is NOT readable from an API key, so this local minute counter is
    # the only usage signal we can offer. Never touches the
    # faster_whisper path's counters.
    if backend_name == "cloud_stt":
        _accumulate_cloud_minutes(duration, log_cb)
    if progress_cb:
        progress_cb(100)
    elapsed = time.time() - start
    log(f"Done in {elapsed:.2f}s", log_cb)


def _accumulate_cloud_minutes(
    duration_seconds: float, log_cb: Callable[[str], None] | None
) -> None:
    """Add ``duration_seconds`` to ``cloud_stt_minutes_used`` and persist.

    Re-reads config from disk before writing so a concurrent worker /
    UI save isn't clobbered, then updates the in-memory module config too
    so a follow-up read in this process sees the new total. Best-effort:
    a persistence error is logged, never raised (it must not fail a
    successful transcription).
    """
    if duration_seconds <= 0:
        return
    minutes = duration_seconds / 60.0
    try:
        from .config import load_config as _load, save_config as _save
        disk_cfg = _load()
        prior = float(disk_cfg.get("cloud_stt_minutes_used") or 0.0)
        new_total = round(prior + minutes, 4)
        disk_cfg["cloud_stt_minutes_used"] = new_total
        _save(disk_cfg)
        config["cloud_stt_minutes_used"] = new_total
        log(f"Cloud minutes used this file: {minutes:.2f} "
            f"(total {new_total:.1f}).", log_cb)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not persist cloud_stt_minutes_used: %s", e)


def _maybe_denoise(
    audio_path: str,
    *,
    duration: float = 0.0,
    transient: bool = False,
    log_cb: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Optional adaptive denoise pre-process. Returns ``(path, temp_to_delete)``.

    ``core.denoise`` measures the audio first and returns the input
    untouched whenever denoising would not help (already clean) or could
    not be verified as safe, so this is safe to call unconditionally.

    ``transient=True`` is for an input that is itself a temp file (a
    pre-sliced clip / resume tail): caching a render keyed to a path
    that will not exist next run is pure waste, so the render is written
    beside the slice and handed back as the second element for the
    caller to delete.

    The second element is ``""`` whenever nothing needs cleaning up —
    including the cached case, where the cache owns the file.
    """
    if not config.get("denoise_enabled", False):
        return audio_path, ""
    try:
        from . import denoise as _dn

        out = _dn.denoise_audio(
            audio_path,
            enabled=True,
            level=str(config.get("denoise_level", "auto") or "auto"),
            duration_s=duration,
            cache=not transient,
            work_dir=_checkpoint.partials_dir() if transient else None,
            log=log_cb,
        )
    except Exception as e:  # noqa: BLE001
        log(f"Denoise pre-process failed (using original audio): {e}", log_cb)
        return audio_path, ""
    if out == audio_path:
        return audio_path, ""
    return out, (out if transient else "")


def _remove_quietly(path: str) -> None:
    """Best-effort unlink; never raises (temp-file hygiene only)."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _close_iterator_quietly(iterator: Any) -> None:
    """Close a lazy decoder before its temporary input is unlinked."""
    close = getattr(iterator, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:  # noqa: BLE001
        pass


def _slice_audio_from(
    source_path: str,
    start_seconds: float,
    out_dir: Path,
    end_seconds: float | None = None,
) -> str:
    """Cut ``source_path[start_seconds:end]`` to a temp file via ffmpeg.

    ``-ss`` is placed BEFORE ``-i`` for fast seeking (ffmpeg jumps to
    the nearest keyframe without decoding everything before). We
    re-encode to WAV PCM 16 kHz mono so Whisper receives a format it
    handles consistently regardless of the source container; this
    matches the resampling pattern ``_prepare_audio_16k_mono`` in
    ``core/diarization`` already uses with the bundled ffmpeg.

    When ``end_seconds`` is given (and greater than ``start_seconds``)
    the slice is bounded to ``[start_seconds, end_seconds]`` via ``-t``
    (output-duration limit, unambiguous with the pre-input ``-ss``).
    ``None`` (the resume path) slices from ``start_seconds`` to EOF.

    Returns the path to the slice on disk. Raises ``RuntimeError`` on
    ffmpeg failure (the caller treats that as "fall back to full
    re-run"). ffmpeg opens the output with ``-y`` before it knows the
    input is decodable, so every failure path removes the partial
    ``.slice.wav`` it may have created — the callers only clean up the
    path on success, and a leaked partial accumulates in ``partials/``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = _checkpoint.source_key(source_path)
    # Include pid + thread so two concurrent resume attempts on the
    # same file don't clobber each other's slice.
    slice_path = out_dir / f"{sha}.{os.getpid()}-{threading.get_ident()}.slice.wav"

    ffmpeg = bundled_binary("ffmpeg")
    cmd = [
        ffmpeg,
        "-loglevel", "error",
        "-ss", f"{float(start_seconds):.3f}",
        "-i", source_path,
    ]
    if end_seconds is not None and float(end_seconds) > float(start_seconds):
        # -t after -i bounds the OUTPUT duration; combined with the
        # pre-input -ss this yields exactly [start_seconds, end_seconds].
        cmd += ["-t", f"{float(end_seconds) - float(start_seconds):.3f}"]
    cmd += [
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        "-y",
        str(slice_path),
    ]
    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    # CREATE_NO_WINDOW on Windows; start_new_session=True on POSIX so
    # kill_process_tree can killpg this ffmpeg's OWN group if needed.
    kwargs.update(new_session_kwargs())
    try:
        result = subprocess.run(cmd, timeout=600, **kwargs)
    except subprocess.TimeoutExpired as e:
        # subprocess.run kills the process, but ffmpeg's already-open
        # output file survives the kill on disk.
        _remove_quietly(str(slice_path))
        raise RuntimeError(
            f"ffmpeg timed out slicing {source_path} from {start_seconds}s"
        ) from e
    except (FileNotFoundError, OSError) as e:
        _remove_quietly(str(slice_path))
        raise RuntimeError(f"ffmpeg binary not available: {e}") from e
    if result.returncode != 0:
        _remove_quietly(str(slice_path))
        err = (result.stderr or b"").decode("utf-8", "replace").strip()[:400]
        raise RuntimeError(
            f"ffmpeg slice failed (exit={result.returncode}): {err or 'no output'}"
        )
    return str(slice_path)


def resume_transcription(
    task: TranscriptionTask,
    progress_cb: Callable[[int], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
    language_cb: Callable[[str, float], None] | None = None,
) -> bool:
    """Resume a previously-cancelled / paused / crashed transcription.

    Returns True if the resume completed (final outputs written),
    False if the checkpoint was invalid / stale and a full re-run is
    required instead. Caller (the worker) handles the False case by
    falling back to a fresh ``transcribe(task)``.

    Only the default ``faster_whisper`` backend supports resume —
    alt backends return False so the worker re-runs from scratch.
    The slicing strategy assumes the WhisperModel.transcribe API
    surface; backends that don't share it would need their own slicer.
    """
    log_cb = _with_task_prefix(log_cb, task)
    with _runtime_overrides_scope(task) as runtime_cfg:
        # A checkpoint is keyed to the whole file with no clip marker, and
        # clipped runs never write one. Resuming a clipped task from a
        # whole-file partial would transcribe past clip_end (prior segments
        # + tail to EOF), silently ignoring the requested range. Refuse the
        # resume path so the caller falls through to a normal clipped
        # transcribe() run. Do NOT delete the checkpoint: it still belongs
        # to a different, still-relevant whole-file job.
        if _clip_timestamps_arg(task) is not None:
            log(
                "Resume: clipped time-range request cannot resume a "
                "whole-file checkpoint; falling back to full clipped run.",
                log_cb,
            )
            return False

        data = _checkpoint.load_checkpoint(task.file_path)
        if data is None:
            log("Resume: no checkpoint on disk; falling back to full re-run.", log_cb)
            return False

        backend, model_name = _current_backend_and_model()
        # Resume currently supports only the faster_whisper path; alt
        # backends would need a per-backend slicer. Fall back to a
        # full re-run rather than guess. Do NOT delete the checkpoint:
        # it may be a valid faster_whisper partial (a cancelled
        # whole-file run) that this refusal never consumed — the same
        # F1/F3 rule as the clip refusal above. The fallback fresh run
        # supersedes it naturally (its success path deletes, its own
        # checkpoint writes overwrite the same key), and a future
        # faster_whisper run of this file can still resume it if the
        # fallback crashes before writing anything.
        backend_for_check = backend
        if backend and backend != "faster_whisper":
            log(
                f"Resume: backend={backend!r} does not support resume; "
                "falling back to full re-run.",
                log_cb,
            )
            return False

        cfg_fp = _checkpoint.config_fingerprint(config)
        reason = _checkpoint.validate_checkpoint(
            data,
            backend=backend_for_check,
            model_name=model_name,
            cfg_fingerprint=cfg_fp,
        )
        if reason:
            log(f"Resume: checkpoint invalid ({reason}); deleting partial.", log_cb)
            _checkpoint.delete_checkpoint(task.file_path)
            return False

        last_end_time = float(data.get("last_end_time") or 0.0)
        prior_segments = list(data.get("segments") or [])
        cp_language = str(data.get("language") or "")
        cp_lang_prob = float(data.get("language_probability") or 0.0)
        log(
            f"Resume: continuing from {last_end_time:.2f}s "
            f"({len(prior_segments)} segment(s) already captured).",
            log_cb,
        )

        # Re-announce the detected language so the UI label stays
        # accurate after the resume.
        if cp_language and language_cb:
            try:
                language_cb(cp_language, cp_lang_prob)
            except Exception:
                logger.exception("language_cb raised on resume")
        if cp_language and hasattr(task, "detected_language"):
            task.detected_language = cp_language
            task.language_probability = cp_lang_prob

        # Make sure the model is loaded — same wait as transcribe().
        global MODEL
        while not MODEL_READY:
            if MODEL_ERROR:
                raise RuntimeError(MODEL_ERROR)
            time.sleep(0.5)

        # Same per-file lazy-load as transcribe(): the worker may have
        # started on an alt backend (MODEL None, MODEL_READY True) while
        # this file resolves to the default backend.
        _ensure_default_backend_loaded(log_cb)

        # Slice the source audio from last_end_time to end. Slices live
        # under ``user_data_dir()/partials/`` next to the checkpoint
        # JSON so a stray temp file is easy to garbage-collect later.
        slice_dir = _checkpoint.partials_dir()
        try:
            slice_path = _slice_audio_from(
                task.file_path, last_end_time, slice_dir
            )
        except RuntimeError as e:
            log(
                f"Resume: could not slice source audio ({e}); "
                "falling back to full re-run.",
                log_cb,
            )
            # Don't delete the checkpoint — the slicer is the failure
            # mode, not the checkpoint, and the fresh transcribe will
            # overwrite the partial as it progresses anyway.
            return False

        # Demucs vocal separation must match the first half: checkpointed
        # segments were decoded from separated vocals when demucs was on,
        # so the tail must be separated too or one transcript mixes two
        # conditioning regimes across the seam. Mirrors the transcribe()
        # pre-process (same call, same fallback). The separated tail is an
        # intermediate like the slice itself — the slice cleanup below still
        # removes the raw slice; the separated output is left alone exactly
        # like transcribe() leaves its separated file (separator-owned/cache).
        demucs_tail_path = slice_path
        if config.get("demucs_enabled", False):
            try:
                from . import separator as _sep
                demucs_tail_path = _sep.separate_vocals(
                    slice_path,
                    enabled=True,
                    log=log_cb,
                )
            except Exception as e:  # noqa: BLE001
                log(f"Demucs separation failed (using original audio): {e}", log_cb)
                demucs_tail_path = slice_path

        # Denoise the tail exactly like the first half was denoised, or
        # the two halves of one transcript come from differently
        # conditioned audio. The checkpoint fingerprint covers the
        # denoise settings, so a mid-job settings change invalidates the
        # partial instead of producing a mismatched merge.
        #
        # NOTE: kept in its own variable — rebinding ``slice_path`` would
        # make the cleanup below unlink the denoised copy and leak the
        # original slice.
        try:
            _tail_dur = max(0.0, get_duration(task.file_path) - last_end_time)
        except Exception:  # noqa: BLE001
            _tail_dur = 0.0
        transcribe_slice, denoise_tmp = _maybe_denoise(
            demucs_tail_path,
            duration=_tail_dur,
            transient=True,
            log_cb=log_cb,
        )

        start = time.time()
        log(f"Resume: transcribing tail slice {transcribe_slice}", log_cb)

        new_segments_iter: Any = None
        try:
            assert MODEL is not None
            want_words = bool(config.get("word_timestamps", False))

            # Reuse the standard kwarg builder so VAD / hotwords /
            # word_timestamps all match the original run. Force the
            # language so the slice doesn't re-run language detection
            # (which on a short tail can produce a low-confidence
            # wrong answer).
            transcribe_kwargs = _build_transcribe_kwargs(task)
            if cp_language:
                transcribe_kwargs["language"] = cp_language

            runner = PIPELINE if PIPELINE is not None else MODEL
            if PIPELINE is not None:
                transcribe_kwargs["batch_size"] = int(config.get("batch_size", 16))

            new_segments_iter, info = runner.transcribe(
                transcribe_slice, **transcribe_kwargs
            )

            # Offset each new segment back into the original timeline
            # before merging with the prior segments. The slice starts
            # at 0 s; we shift to ``last_end_time``.
            # Original duration for an honest progress %: each segment's
            # d["end"] below is already shifted onto the original timeline,
            # so dividing by the whole-file duration makes the bar climb
            # last_end_time→100 instead of pinning at a constant 99 (P2-25).
            try:
                total_dur = get_duration(task.file_path)
            except Exception:  # noqa: BLE001
                total_dur = 0.0
            new_segments_data: list[dict[str, Any]] = []

            def _handle_resume_cancelled() -> bool:
                if not task.cancelled:
                    return False
                # Keep the existing checkpoint when cancellation arrives
                # before the tail yields anything; replace it with the merged
                # progress when some new tail segments were captured.
                merged_so_far = prior_segments + new_segments_data
                if merged_so_far:
                    _write_periodic_checkpoint(
                        task,
                        merged_so_far,
                        float(merged_so_far[-1].get("end", last_end_time)),
                        cp_language,
                        cp_lang_prob,
                        log_cb,
                    )
                log("Task cancelled during resume.", log_cb)
                return True

            for seg in new_segments_iter:
                if _handle_resume_cancelled():
                    return True  # We "handled" the cancel cleanly.
                while task.paused and not task.cancelled:
                    time.sleep(0.2)
                if _handle_resume_cancelled():
                    return True

                d = _segment_to_dict(seg, want_words)
                d["start"] = float(d.get("start", 0.0)) + last_end_time
                d["end"] = float(d.get("end", 0.0)) + last_end_time
                if want_words and isinstance(d.get("words"), list):
                    for w in d["words"]:
                        try:
                            w["start"] = float(w.get("start", 0.0)) + last_end_time
                            w["end"] = float(w.get("end", 0.0)) + last_end_time
                        except (TypeError, ValueError):
                            continue
                new_segments_data.append(d)

                if progress_cb:
                    # d["end"] is on the original timeline; scale against the
                    # whole-file duration so the bar advances through the
                    # resumed tail. Fall back to a flat 99 only if duration
                    # is unknown (ffprobe failed).
                    if total_dur > 0.0:
                        progress_cb(min(99, int(d["end"] / total_dur * 100)))
                    else:
                        progress_cb(99)
        finally:
            # Always clean the slice file — the resume either
            # succeeded (final outputs written) or fell back, in both
            # cases the slice is disposable. Same for any denoised copy
            # of it (empty string when denoise was off / reverted).
            _close_iterator_quietly(new_segments_iter)
            for _tmp in (slice_path, denoise_tmp):
                if not _tmp:
                    continue
                try:
                    os.unlink(_tmp)
                except OSError:
                    pass

        final_segments = prior_segments + new_segments_data
        detected_lang = cp_language or str(getattr(info, "language", "") or "")

        # Post-pipeline must see the full ORIGINAL audio (diarisation,
        # alignment, chapters all need the whole file). Reuse the
        # existing helper unchanged.
        speaker_count = _run_post_pipeline(
            task, final_segments, detected_lang, log_cb, progress_cb
        )

        if _handle_resume_cancelled():
            return True

        base = os.path.splitext(task.file_path)[0]
        written = _write_outputs(
            base,
            final_segments,
            task.file_path,
            getattr(task, "output_formats", None),
            lang=detected_lang,
            speaker_count=speaker_count,
            chapters=getattr(task, "_chapters_for_writer", None) or [],
        )
        task.output_paths = list(written)
        _record_transcript_stats(task, final_segments)
        log(
            f"Resume: wrote {len(written)} output file(s): "
            f"{', '.join(os.path.basename(p) for p in written)}",
            log_cb,
        )

        _checkpoint.delete_checkpoint(task.file_path)
        if progress_cb:
            progress_cb(100)
        elapsed = time.time() - start
        log(f"Resume: done in {elapsed:.2f}s", log_cb)
        # runtime_cfg is used implicitly via the scope; reference it
        # to satisfy the linter without changing behaviour.
        _ = runtime_cfg
        return True
