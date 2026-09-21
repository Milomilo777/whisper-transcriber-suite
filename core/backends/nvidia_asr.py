"""Local, offline transcription via a Hugging Face transformers ASR model.

Default model: ``nvidia/parakeet-tdt-0.6b-v3`` — NVIDIA's transformers-native
multilingual FastConformer-TDT model. Configurable to ANY transformers
``automatic-speech-recognition`` model (a Hugging Face repo id OR a local
directory) via the ``nvidia_asr_model_id`` config key.

Everything runs ON THIS MACHINE — no audio leaves the device. This follows the
approach in the colleague's ``transcribe_nemotron.py``: a transformers
``pipeline("automatic-speech-recognition", …)`` call whose output is turned into
subtitle-sized segments.

Timestamps
----------
Some transformers ASR models return per-word timestamps for
``return_timestamps="word"``; others (parakeet-tdt-0.6b-v3 in transformers 5.x
included) raise on that path and only return plain text. So this backend
transcribes WINDOW BY WINDOW (``nvidia_asr_chunk_seconds``, default 30 s): it
tries word timestamps once and, if the model doesn't support them, falls back to
emitting one segment per window timed to the window bounds. Smaller windows ->
finer subtitle granularity in the text-only fallback.

Note on "Nemotron 3.5 ASR"
--------------------------
NVIDIA's exact ``nemotron-3.5-asr-streaming-0.6b`` repo ships ONLY a NeMo
``.nemo`` checkpoint (``library_name: nemo``, no transformers config/weights), so
the transformers pipeline cannot load it — running that precise model needs the
heavy NeMo toolkit. ``parakeet-tdt-0.6b-v3`` is its transformers-native
FastConformer sibling (same architecture family, multilingual) and is the
default here.

Dependencies
------------
``transformers`` + ``torch`` + ``librosa`` (the ParakeetFeatureExtractor needs
librosa for its mel front-end) are heavy and NOT bundled in the slim build; they
install on first use via :mod:`core.optional_deps`, mirroring the openai-whisper
backend. Model weights download from the Hugging Face Hub on first use and are
cached for later runs.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable

from .._liveness_tick import liveness_tick
from ..config import load_config
from .base import Backend, LanguageInfo
from .cloud_stt import offset_segments, plan_chunks

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- constants

DEFAULT_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"
#: Window length (seconds) per pipeline call. Also the segment granularity when
#: the model returns text only (no word timestamps). Kept modest so the
#: text-only fallback still yields usable subtitle-sized segments and so cancel /
#: progress stay responsive.
DEFAULT_CHUNK_SECONDS = 30.0
#: Long-form sub-chunk length used only in the (optional) word-timestamp call.
PIPELINE_CHUNK_LENGTH_S = 30
#: Group word tokens into one segment once it spans this many seconds (used only
#: when the model DOES return word timestamps).
MAX_SEGMENT_SECONDS = 10.0
TARGET_SR = 16000
#: A past-EOF window decodes to ~no audio; fewer than this many samples = EOF.
#: 1024 samples = 64 ms at 16 kHz; a real window is hundreds of thousands+.
_EMPTY_PCM_SAMPLES = 1024


# ---------------------------------------------------------------- pure seams
# Everything below is import-light and unit-testable without torch/transformers.


def resolve_device(device_cfg: Any, cuda_available: bool) -> str:
    """Map the ``nvidia_asr_device`` config to a concrete device string.

    ``"auto"`` (or empty) picks ``"cuda"`` when a GPU is usable, else ``"cpu"``.
    Any explicit value (``"cpu"`` / ``"cuda"`` / ``"cuda:1"``) passes through.
    """
    d = str(device_cfg or "auto").strip().lower()
    if d in ("", "auto"):
        return "cuda" if cuda_available else "cpu"
    return d


def resolve_dtype(dtype_cfg: Any, device: str) -> str:
    """Map the ``nvidia_asr_dtype`` config to ``"float16"`` / ``"float32"``.

    ``"auto"`` uses float16 on CUDA (faster, smaller) and float32 on CPU
    (float16 matmul is slow / unsupported on most CPUs).
    """
    t = str(dtype_cfg or "auto").strip().lower()
    if t in ("", "auto"):
        return "float16" if str(device).startswith("cuda") else "float32"
    return t


def _clean_word(text: Any) -> str:
    """Normalise a transformers word token (which often has a leading space)."""
    return str(text or "").strip()


def chunks_to_segments(
    chunks: Any, max_segment_seconds: float = MAX_SEGMENT_SECONDS
) -> list[dict[str, Any]]:
    """Group transformers word chunks into subtitle-sized segment dicts.

    ``chunks`` is the ``result["chunks"]`` list a transformers ASR pipeline
    returns for ``return_timestamps="word"`` — each entry a dict with
    ``"text"`` and ``"timestamp": (start, end)`` (seconds). A ``None`` in the
    timestamp tuple (the pipeline can't always time the final token) skips that
    word. Returns ``[{start, end, text, words:[{word,start,end,probability}]}]``;
    an empty list when there are no usable timed words. Pure — no model needed.
    """
    segments: list[dict[str, Any]] = []
    if not chunks:
        return segments
    current: list[dict[str, Any]] = []
    seg_start: float | None = None
    for ch in chunks:
        if not isinstance(ch, dict):
            continue
        ts = ch.get("timestamp")
        if not ts or len(ts) < 2 or ts[0] is None or ts[1] is None:
            continue
        start = float(ts[0])
        end = float(ts[1])
        word = _clean_word(ch.get("text"))
        current.append({
            "word": word,
            "start": start,
            "end": end,
            "probability": 1.0,
        })
        if seg_start is None:
            seg_start = start
        if end - seg_start >= max_segment_seconds:
            segments.append(_make_segment(current, seg_start, end))
            current = []
            seg_start = None
    if current:
        segments.append(
            _make_segment(current, current[0]["start"], current[-1]["end"])
        )
    return segments


def _make_segment(
    words: list[dict[str, Any]], start: float, end: float
) -> dict[str, Any]:
    text = " ".join(w["word"] for w in words if w["word"])
    text = " ".join(text.split())  # collapse any double spaces
    return {
        "start": float(start),
        "end": float(end),
        "text": text,
        "words": [dict(w) for w in words],
    }


def text_to_segment(text: Any, start: float, end: float) -> list[dict[str, Any]]:
    """Wrap a window's plain text into a single timed segment (no word timings).

    Used when the model returns text only. Returns ``[]`` for empty text so a
    silent / music-only window contributes nothing.
    """
    clean = " ".join(str(text or "").split())
    if not clean:
        return []
    return [{
        "start": float(start),
        "end": float(max(end, start)),
        "text": clean,
        "words": [],
    }]


def friendly_load_error(exc: Any) -> str:
    """Turn a model-load exception into a clear, user-facing message."""
    msg = str(exc)
    low = msg.lower()
    if "does not recognize this architecture" in low:
        return (
            "This model needs a newer 'transformers' package than the one "
            "installed (e.g. nvidia/nemotron-3.5-asr-streaming-0.6b needs "
            "transformers >= 5.14). Update it: pip install -U transformers "
            f"— then try again. [{msg[:200]}]"
        )
    if "tokenizers" in low and "is required for a normal functioning" in low:
        return (
            "This app has a dependency clash: 'transformers' needs a "
            "'tokenizers' version this build does not have. Use a "
            "different engine for now (Advanced > Backend). Check for an "
            "app update — it may already fix this. If you run this from "
            "source code, try this command: pip install -U transformers "
            f"— then try again. [{msg[:200]}]"
        )
    if "librosa" in low:
        return (
            "The local NVIDIA ASR model needs the 'librosa' package, which "
            "did not install. Try again, or install it manually: "
            f"pip install librosa. [{msg[:200]}]"
        )
    if any(k in low for k in ("not a local folder", "is not a valid", "404", "repository not found")):
        return (
            "Could not find the model. Set 'nvidia_asr_model_id' in Advanced > "
            "Backend to a valid Hugging Face id or a local folder, and make "
            f"sure you are online for the first download. [{msg[:200]}]"
        )
    return f"Could not load the local NVIDIA ASR model: {msg[:300]}"


# ---------------------------------------------------------------- backend


class NvidiaAsrBackend(Backend):
    """Local transformers ASR backend (default: NVIDIA Parakeet TDT v3).

    Loads a Hugging Face ``automatic-speech-recognition`` pipeline once per
    worker and transcribes each file by decoding it to 16 kHz mono PCM (bundled
    ffmpeg), running the pipeline window-by-window for progress + cancel,
    building segments (word timestamps when the model supports them, else one
    segment per window), and stitching them onto the global timeline. No audio
    leaves the machine.
    """

    name = "nvidia_asr"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config
        self._model_id: str = DEFAULT_MODEL_ID
        self._device_cfg: str = "auto"
        self._dtype_cfg: str = "auto"
        self._chunk_seconds: float = DEFAULT_CHUNK_SECONDS
        self._device: str = "cpu"
        self._error: str | None = None
        self._ready = False
        self._lock = threading.Lock()
        self._pipe: Any = None
        #: None = not probed yet; True/False = does the model return word
        #: timestamps. Probed once on the first window, then reused.
        self._supports_word_ts: bool | None = None

    # -- lifecycle -----------------------------------------------------------

    def _cfg(self) -> dict[str, Any]:
        return self._config if self._config is not None else load_config()

    def _read_config(self) -> None:
        cfg = self._cfg()
        self._model_id = (
            str(cfg.get("nvidia_asr_model_id") or "").strip() or DEFAULT_MODEL_ID
        )
        self._device_cfg = str(cfg.get("nvidia_asr_device") or "auto").strip() or "auto"
        self._dtype_cfg = str(cfg.get("nvidia_asr_dtype") or "auto").strip() or "auto"
        try:
            self._chunk_seconds = float(
                cfg.get("nvidia_asr_chunk_seconds") or DEFAULT_CHUNK_SECONDS
            )
        except (TypeError, ValueError):
            self._chunk_seconds = DEFAULT_CHUNK_SECONDS
        if self._chunk_seconds <= 0:
            self._chunk_seconds = DEFAULT_CHUNK_SECONDS

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self._ready = False
        self._error = None
        self._pipe = None
        self._supports_word_ts = None
        self._read_config()

        # Ensure transformers/torch/librosa are importable; install on demand
        # (mirrors the openai-whisper / google_cloud_stt on-demand pattern).
        if not _deps_available():
            if status_cb:
                status_cb(
                    "Installing local NVIDIA ASR engine (transformers + torch + "
                    "librosa) — one-time, this can take several minutes…"
                )
            try:
                from .. import optional_deps

                # optional_deps.install()'s own short-circuit probes only
                # ``transformers``, so a half-present environment (transformers
                # there, torch / librosa missing) must force the (re)install —
                # otherwise install() returns True having done nothing and the
                # next re-check fails. Same present-but-incomplete pattern as
                # google_cloud_stt.load().
                partially_installed = optional_deps.is_available("nvidia_asr")
                optional_deps.install(
                    "nvidia_asr", status_cb, cancel_event,
                    force=partially_installed,
                )
            except Exception as e:  # noqa: BLE001
                self._error = (
                    "Could not install the local NVIDIA ASR dependencies "
                    f"(transformers + torch + librosa): {e}"
                )
                if status_cb:
                    status_cb(self._error)
                return False
            if not _deps_available():
                self._error = (
                    "The local NVIDIA ASR dependencies did not import after "
                    "installation. Install manually: pip install transformers "
                    "torch librosa."
                )
                if status_cb:
                    status_cb(self._error)
                return False

        try:
            torch, pipeline = _import_torch_and_transformers()
        except Exception as e:  # noqa: BLE001
            self._error = friendly_load_error(e)
            if status_cb:
                status_cb(self._error)
            return False

        cuda = False
        try:
            cuda = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            cuda = False
        self._device = resolve_device(self._device_cfg, cuda)
        dtype_name = resolve_dtype(self._dtype_cfg, self._device)
        # getattr avoids pyright's "float16 is not exported from torch" and is
        # robust if a future torch renames a dtype.
        torch_dtype = getattr(torch, dtype_name, None)
        device_arg = 0 if self._device.startswith("cuda") else -1

        if status_cb:
            status_cb(
                f"Loading {self._model_id} on {self._device} "
                "(first run downloads the model)…"
            )
        try:
            self._pipe = _build_pipeline(
                pipeline, self._model_id, device_arg, torch_dtype
            )
        except Exception as e:  # noqa: BLE001
            self._error = friendly_load_error(e)
            if status_cb:
                status_cb(self._error)
            return False

        self._ready = True
        if status_cb:
            status_cb(f"NVIDIA Parakeet ready ({self._model_id}, {self._device}).")
        if progress_cb:
            progress_cb({
                "phase": "loaded",
                "status": "NVIDIA Parakeet ready",
                "percent": 100,
                "detail": self._model_id,
            })
        return True

    def is_ready(self) -> bool:
        return self._ready

    def get_error(self) -> str | None:
        return self._error

    def unload(self) -> None:
        self._pipe = None
        self._ready = False

    # -- transcription -------------------------------------------------------

    def _run_pipe(self, audio: Any) -> tuple[Any, bool]:
        """Run the pipeline on one window's audio array.

        Returns ``(result, has_word_chunks)``. Tries word timestamps once; if
        the model doesn't support them (many transducer models raise), caches
        that and uses the plain-text call for the rest of the file.
        """
        if self._supports_word_ts is not False:
            try:
                res = self._pipe(
                    {"raw": audio, "sampling_rate": TARGET_SR},
                    return_timestamps="word",
                    chunk_length_s=PIPELINE_CHUNK_LENGTH_S,
                )
                has = bool(isinstance(res, dict) and res.get("chunks"))
                self._supports_word_ts = has
                if has:
                    return res, True
            except Exception:  # noqa: BLE001 — model lacks word-timestamp path
                self._supports_word_ts = False
        # Build a FRESH input dict: the transformers ASR pipeline consumes /
        # mutates the dict it is handed during preprocess, so the fallback call
        # must not reuse one a prior (failed word-timestamp) call already
        # touched — that previously raised "dict needs a 'raw' key".
        return self._pipe({"raw": audio, "sampling_rate": TARGET_SR}), False

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
                raise RuntimeError(self._error or "NVIDIA Parakeet backend not ready")
        if self._pipe is None:
            raise RuntimeError(self._error or "NVIDIA Parakeet model not loaded")

        effective_duration = duration
        if effective_duration <= 0:
            try:
                from ..transcriber import get_duration

                effective_duration = float(get_duration(audio_path) or 0.0)
            except Exception:  # noqa: BLE001
                effective_duration = 0.0

        chunks = plan_chunks(
            effective_duration, self._chunk_seconds, chunk_when_unknown=True
        )
        total = len(chunks)
        duration_unknown = effective_duration <= 0
        if log_cb:
            log_cb(
                f"NVIDIA Parakeet: transcribing {total} window(s) locally "
                f"({self._model_id}, {self._device})."
            )

        all_segments: list[dict[str, Any]] = []
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            if cancelled and cancelled():
                if log_cb:
                    log_cb("Task cancelled")
                break
            while paused and paused() and not (cancelled and cancelled()):
                time.sleep(0.2)

            audio = _decode_window(audio_path, chunk_start, chunk_end)
            # Unknown-length: a slice past EOF decodes to ~nothing -> stop.
            if duration_unknown and idx > 0 and audio.size < _EMPTY_PCM_SAMPLES:
                if log_cb:
                    log_cb(
                        f"NVIDIA Parakeet: reached end of file after {idx} window(s)."
                    )
                break
            if audio.size == 0:
                continue

            win_len = float(audio.size) / TARGET_SR
            try:
                with liveness_tick(
                    log_cb, f"NVIDIA Parakeet window {idx + 1}/{total}"
                ):
                    result, has_words = self._run_pipe(audio)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(
                    f"NVIDIA Parakeet transcription failed: {e}"
                ) from e

            if has_words and isinstance(result, dict):
                seg = chunks_to_segments(result.get("chunks"))
            else:
                text = result.get("text") if isinstance(result, dict) else result
                seg = text_to_segment(text, 0.0, win_len)
            seg = offset_segments(seg, chunk_start)
            all_segments.extend(seg)

            if progress_cb:
                progress_cb(min(100, int(((idx + 1) / max(total, 1)) * 100)))
            if log_cb:
                log_cb(
                    f"NVIDIA Parakeet: window {idx + 1}/{total} -> "
                    f"{len(seg)} segment(s)."
                )

        if want_words:
            for s in all_segments:
                s.setdefault("words", [])

        # Parakeet returns no language-ID signal; report the forced hint when
        # given, else leave it blank (handled gracefully downstream).
        detected = language or ""
        return all_segments, LanguageInfo(
            language=detected, probability=1.0 if detected else 0.0
        )


# ---------------------------------------------------------------- helpers


#: The imports this backend needs at runtime, all of which come as one
#: on-demand install (``optional_deps`` feature ``nvidia_asr``).
_REQUIRED_MODULES = ("transformers", "torch", "librosa")


def _deps_available() -> bool:
    """True iff transformers + torch + librosa can all be imported.

    A ``transformers`` install does NOT guarantee torch (transformers treats
    torch as an optional backend) or librosa (needed by the Parakeet mel
    front-end). Probing only ``transformers`` would skip the on-demand
    install and then die with a cryptic "No module named 'torch'" at load
    time — this way that half-present case routes into the installer. Uses
    ``find_spec`` only (never imports the heavy modules) and is not cached,
    so a fresh on-demand install is picked up immediately. Activates the
    on-demand extras dir first (mirrors ``optional_deps.is_available``) so an
    install from an earlier session is seen as present, not force-reinstalled.
    Never raises.
    """
    try:
        from .. import optional_deps

        optional_deps.activate()
        import importlib.util

        return all(
            importlib.util.find_spec(name) is not None
            for name in _REQUIRED_MODULES
        )
    except Exception:  # noqa: BLE001
        return False


def _import_torch_and_transformers() -> tuple[Any, Any]:
    """The real (possibly-failing) import, isolated so tests can monkeypatch
    this one seam instead of faking a torch/transformers install. A
    tokenizers/transformers version clash raises here, not at find_spec
    time — see the ``friendly_load_error`` branch that reads this
    exception's text."""
    import torch  # type: ignore
    from transformers import pipeline  # type: ignore

    return torch, pipeline


def _build_pipeline(
    pipeline: Any, model_id: str, device_arg: int, torch_dtype: Any
) -> Any:
    """Build the ASR pipeline, tolerating the transformers dtype-kwarg rename.

    transformers 5.x renamed ``torch_dtype`` -> ``dtype`` (the old name is
    deprecated). Try the new name first, fall back to the old one so the
    backend works across versions. ``torch_dtype`` None lets the pipeline pick.
    """
    kwargs: dict[str, Any] = {"model": model_id, "device": device_arg}
    if torch_dtype is not None:
        try:
            return pipeline(
                "automatic-speech-recognition", dtype=torch_dtype, **kwargs
            )
        except TypeError:
            return pipeline(
                "automatic-speech-recognition", torch_dtype=torch_dtype, **kwargs
            )
    return pipeline("automatic-speech-recognition", **kwargs)


def _decode_window(audio_path: str, start_seconds: float, end_seconds: float) -> Any:
    """Decode ``audio_path[start:end]`` to a 16 kHz mono float32 numpy array.

    Uses the bundled ffmpeg, streaming raw PCM via a pipe (no temp file). An
    ``end <= start`` window means "to end of file"; a window past EOF decodes to
    an empty array. Returns a numpy float32 array in [-1, 1].
    """
    import numpy as np  # type: ignore

    from ..paths import bundled_binary

    ffmpeg = bundled_binary("ffmpeg")
    cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-y"]
    if start_seconds > 0:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    cmd += ["-i", audio_path]
    if end_seconds > start_seconds:
        cmd += ["-t", f"{end_seconds - start_seconds:.3f}"]
    cmd += [
        "-ac", "1", "-ar", str(TARGET_SR),
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]

    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, **kwargs)
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(
            "ffmpeg is required to prepare audio for the NVIDIA Parakeet "
            "backend but was not found. Use the default engine, or install "
            "ffmpeg."
        ) from e

    pcm = proc.stdout or b""
    if proc.returncode != 0 and not pcm:
        # A slice that starts past EOF often returns non-zero with no output —
        # treat that as an empty window rather than an error.
        return np.frombuffer(b"", dtype=np.int16).astype(np.float32)
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-400:]
        raise RuntimeError(
            "ffmpeg could not prepare this file for the NVIDIA Parakeet "
            f"backend (it may be corrupt or an unsupported format): "
            f"{detail or 'no error output'}"
        )
    # int16 little-endian PCM -> float32 in [-1, 1].
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
