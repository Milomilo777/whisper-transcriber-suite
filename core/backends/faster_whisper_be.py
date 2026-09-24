"""``faster_whisper`` backend — wraps the legacy module-level state.

This backend is a thin adapter around the loose globals
``MODEL``/``PIPELINE`` that ``core.transcriber`` used before backends
existed. Keeping the state in one place means the worker process loads
the model exactly once, and the existing smoke tests
(``tests/smoke/test_exe_real_e2e.py``) keep passing without changes.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from faster_whisper import WhisperModel

try:  # 1.0.3+ ships this; older wheels do not
    from faster_whisper import BatchedInferencePipeline  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    BatchedInferencePipeline = None  # type: ignore[assignment]

from ..config import load_config
from ..model_manager import DownloadCancelled, ensure_model
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)


def _detect_device(config: dict[str, Any]) -> tuple[str, str]:
    """Delegate to the canonical detector in ``core.hardware``.

    Kept as a module-level alias so existing call sites + tests that
    import ``_detect_device`` from this module don't need to move.
    """
    from ..hardware import detect_device_for
    return detect_device_for(config)


class FasterWhisperBackend(Backend):
    name = "faster_whisper"

    def __init__(self) -> None:
        self._model: Any = None
        self._pipeline: Any = None
        self._ready = False
        self._error: str | None = None
        self._device = "cpu"
        self._compute_type = "int8"
        # R3: requested vs. effective device. ``_device`` tracks the
        # effective device (downgraded to cpu if a CUDA load self-heals);
        # ``_requested_device`` preserves the original ask, and
        # ``_downgraded`` records that a fallback happened so the UI can warn.
        self._requested_device = "cpu"
        self._downgraded = False

    def is_ready(self) -> bool:
        return self._ready

    def get_error(self) -> str | None:
        return self._error

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    @property
    def requested_device(self) -> str:
        return self._requested_device

    @property
    def downgraded(self) -> bool:
        return self._downgraded

    @property
    def model(self) -> Any:
        return self._model

    @property
    def pipeline(self) -> Any:
        return self._pipeline

    def _wrap_for_batched(self) -> Any:
        if self._device != "cuda" or BatchedInferencePipeline is None:
            return None
        try:
            return BatchedInferencePipeline(model=self._model)
        except Exception as e:  # noqa: BLE001
            logger.info("BatchedInferencePipeline unavailable: %s", e)
            return None

    def _capture_effective_device(self, req_device: str, req_compute: str) -> None:
        """Read back what CTranslate2 actually loaded onto (getattr-guarded)."""
        ct2 = getattr(self._model, "model", None)
        self._device = str(getattr(ct2, "device", "") or "") or req_device
        self._compute_type = (
            str(getattr(ct2, "compute_type", "") or "") or req_compute
        )

    def _load_self_healing(
        self,
        model_path: str,
        status_cb: Callable[[str], None] | None,
    ) -> None:
        """Build ``self._model``, self-healing a failed CUDA load onto CPU.

        Mirrors ``core.transcriber._load_whisper_model_self_healing``: a CUDA
        failure at construction or in the GPU warm-up pass right after it
        (typically a missing cuBLAS runtime, or GPU code that cannot run on
        this GPU) logs the real reason, flips ``self._downgraded``, and
        retries with ("cpu", "int8") rather than crashing the worker.
        """
        req_device = self._requested_device
        req_compute = self._compute_type
        try:
            if req_device == "cuda":
                from ..hardware import prepare_cuda_runtime
                prepare_cuda_runtime()
            self._model = WhisperModel(
                model_path, device=req_device, compute_type=req_compute
            )
            if req_device == "cuda":
                from ..hardware import warm_up_cuda_model
                if status_cb:
                    status_cb("Checking the GPU with a short warm-up pass...")
                warm_up_cuda_model(self._model)
            self._capture_effective_device(req_device, req_compute)
            return
        except Exception as e:
            if req_device != "cuda":
                raise
            error = str(e)
        # CPU retry OUTSIDE the except block: while it is active the
        # traceback's frames keep the half-working CUDA model alive.
        self._model = None
        gc.collect()
        from ..hardware import cuda_load_failure_reason
        reason = cuda_load_failure_reason(error)
        logger.warning(
            "CUDA model load failed (%s); downgrading to cpu/int8. %s",
            error, reason,
        )
        if status_cb:
            status_cb(
                f"GPU unavailable ({error}); falling back to CPU (slower). {reason}"
            )
        self._device, self._compute_type = "cpu", "int8"
        self._model = WhisperModel(
            model_path, device="cpu", compute_type="int8"
        )
        self._downgraded = True
        self._capture_effective_device("cpu", "int8")

    def load_existing(self, status_cb: Callable[[str], None] | None = None) -> bool:
        config = load_config(fetch_online=False)  # worker path: local keys only
        self._device, self._compute_type = _detect_device(config)
        self._requested_device = self._device
        self._downgraded = False
        self._ready = False
        self._error = None
        model_path = Path(config["model_path"])
        if not model_path.exists():
            self._error = f"Model folder missing: {model_path}"
            if status_cb:
                status_cb(self._error)
            return False
        try:
            if status_cb:
                status_cb("Loading existing Whisper model...")
            self._load_self_healing(str(model_path), status_cb)
            self._pipeline = self._wrap_for_batched()
            self._ready = True
            if status_cb:
                status_cb("Model loaded")
            return True
        except Exception as e:  # noqa: BLE001
            self._error = str(e)
            if status_cb:
                status_cb(f"Existing model failed to load: {e}")
            return False

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        config = load_config(fetch_online=False)  # worker path: local keys only
        self._device, self._compute_type = _detect_device(config)
        self._requested_device = self._device
        self._downgraded = False
        self._ready = False
        self._error = None
        try:
            model_path = ensure_model(config, status_cb, progress_cb, cancel_event)
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Model download cancelled")
            if status_cb:
                status_cb("Loading Whisper model...")
            if progress_cb:
                progress_cb({
                    "phase": "load", "status": "Loading Whisper model...",
                    "percent": 100, "detail": "Preparing model for transcription",
                })
            self._load_self_healing(model_path, status_cb)
            self._pipeline = self._wrap_for_batched()
            self._ready = True
            if status_cb:
                status_cb("Model loaded")
            if progress_cb:
                progress_cb({
                    "phase": "loaded", "status": "Model loaded",
                    "percent": 100, "detail": "Ready",
                })
            return True
        except DownloadCancelled as e:
            self._error = None
            if status_cb:
                status_cb(str(e))
            return False
        except Exception as e:
            self._error = str(e)
            if status_cb:
                status_cb(f"ERROR: {e}")
            raise

    def unload(self) -> None:
        self._model = None
        self._pipeline = None
        self._ready = False

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
        if not self._ready or self._model is None:
            raise RuntimeError(self._error or "faster_whisper backend not loaded")

        transcribe_kwargs: dict[str, Any] = {
            "vad_filter": vad_parameters is not None,
            "word_timestamps": bool(want_words),
        }
        if vad_parameters is not None:
            transcribe_kwargs["vad_parameters"] = vad_parameters
        if language:
            transcribe_kwargs["language"] = language
        if initial_prompt:
            transcribe_kwargs["initial_prompt"] = initial_prompt
        if hotwords:
            transcribe_kwargs["hotwords"] = hotwords

        runner = self._pipeline if self._pipeline is not None else self._model
        if self._pipeline is not None:
            transcribe_kwargs["batch_size"] = int(batch_size)

        segments_iter, info = runner.transcribe(audio_path, **transcribe_kwargs)

        lang_info = LanguageInfo(
            language=str(getattr(info, "language", "") or ""),
            probability=float(getattr(info, "language_probability", 0.0) or 0.0),
        )

        segments_data: list[dict[str, Any]] = []
        for seg in segments_iter:
            if cancelled and cancelled():
                if log_cb:
                    log_cb("Task cancelled")
                return segments_data, lang_info
            while paused and paused() and not (cancelled and cancelled()):
                time.sleep(0.2)

            if duration > 0 and progress_cb:
                percent = min(100, int((seg.end / duration) * 100))
                progress_cb(percent)
            if log_cb:
                ts = f"{seg.start:.2f} --> {seg.end:.2f}"
                log_cb(f"[{ts}] {(seg.text or '').strip()}")

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
            segments_data.append(payload)
        return segments_data, lang_info
