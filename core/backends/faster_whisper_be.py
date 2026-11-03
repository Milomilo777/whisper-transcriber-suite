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
import os
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from faster_whisper import WhisperModel

try:  # 1.0.3+ ships this; older wheels do not
    from faster_whisper import BatchedInferencePipeline  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    BatchedInferencePipeline = None  # type: ignore[assignment]

from .. import loop_guard, vad_window
from ..config import load_config
from ..model_manager import DownloadCancelled, ensure_model
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)


def _cuda_failure(exc: RuntimeError) -> str:
    from ..hardware import classify_cuda_load_failure

    text = str(exc)
    kind = classify_cuda_load_failure(text)
    if kind in {"out_of_memory", "arch_unsupported"} or any(
        name in text.lower() for name in ("cuda", "cudnn", "cublas")
    ):
        return kind
    return ""


class WhisperDecode:
    """Retry a CUDA decode from its last yielded timestamp, including lazy errors.

    Getters retain no old model: close failed generators and leave their exception
    handlers before replacing weights, so a retry does not hold two GPU models.
    Shared by the desktop, live chunks, language models and the backend adapter.
    """

    def __init__(
        self,
        runner: Callable[[dict[str, Any]], Any],
        is_cuda: Callable[[], bool],
        recover: Callable[[dict[str, Any], bool], None],
        window_s: float | None,
    ) -> None:
        self._runner = runner
        self._is_cuda = is_cuda
        self._recover = recover
        self._window_s = window_s
        self.before_retry: Callable[[], None] = lambda: None

    def detect_language(self, **kwargs: Any) -> Any:
        while True:
            try:
                return self._runner({}).detect_language(**kwargs)
            except RuntimeError as exc:
                failure = _cuda_failure(exc)
                if not self._is_cuda() or not failure:
                    raise
            self.before_retry()
            self._recover({}, failure == "out_of_memory")

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        options = dict(kwargs)

        def start(source: Any) -> tuple[Any, Any]:
            while True:
                try:
                    with (vad_window.windowed_vad(self._window_s)
                          if self._window_s is not None else nullcontext()):
                        return self._runner(options).transcribe(source, **options)
                except RuntimeError as exc:
                    failure = _cuda_failure(exc)
                    if not self._is_cuda() or not failure:
                        raise
                    oom = failure == "out_of_memory"
                self.before_retry()
                self._recover(options, oom)

        first, info = start(audio)

        def iterate():
            nonlocal first
            # Import lazily: the legacy transcriber also uses this adapter.
            from ..transcriber import (
                _checkpoint, _close_iterator_quietly, _shift_segments, _slice_audio_from,
            )

            iterator: Any = first
            first = None
            cursor = offset = 0.0
            temporary: list[str] = []
            try:
                while True:
                    try:
                        for seg in _shift_segments(iterator, offset) if offset else iterator:
                            cursor = max(cursor, float(getattr(seg, "end", 0.0) or 0.0))
                            yield seg
                        return
                    except RuntimeError as exc:
                        failure = _cuda_failure(exc)
                        oom = failure == "out_of_memory"
                        if not self._is_cuda() or not failure:
                            raise
                    finally:
                        _close_iterator_quietly(iterator)
                    iterator = None
                    self.before_retry()
                    self._recover(options, oom)
                    # Pin the detected language for the remaining audio, unless
                    # mixed-language decoding deliberately detects each stretch.
                    if not options.get("language") and not options.get("multilingual"):
                        language = str(getattr(info, "language", "") or "")
                        if language:
                            options["language"] = language
                    source = audio
                    if cursor > 0:
                        if kwargs.get("clip_timestamps") is not None:
                            clips = kwargs["clip_timestamps"]
                            stamps = [float(t) for t in (clips.split(",") if isinstance(clips, str) else clips)]
                            relative = []
                            for i in range(0, len(stamps), 2):
                                end = stamps[i + 1] if i + 1 < len(stamps) else float("inf")
                                if end > cursor:
                                    relative.append(max(0.0, stamps[i] - cursor))
                                    if i + 1 < len(stamps):
                                        relative.append(end - cursor)
                            if not relative:
                                return
                            options["clip_timestamps"] = relative
                        if isinstance(audio, (str, os.PathLike)):
                            source = _slice_audio_from(str(audio), cursor, _checkpoint.partials_dir())
                            temporary.append(source)
                        else:
                            source = audio[round(cursor * 16000):]
                    offset = cursor
                    iterator, _ = start(source)
            finally:
                _close_iterator_quietly(iterator)
                for path in temporary:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        return iterate(), info


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
        # Long-file safeguards read from config at load time (see
        # core.vad_window and core.loop_guard).
        self._vad_window_s = vad_window.DEFAULT_WINDOW_S
        self._loop_guard_repeats = loop_guard.DEFAULT_REPEATS
        self._decode_batch_size = 0
        self._model_path = ""

    def _read_safeguards(self, config: dict[str, Any]) -> None:
        self._vad_window_s = vad_window.window_seconds(config)
        self._loop_guard_repeats = loop_guard.repeat_limit(config)

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
        req_device = self._device if self._downgraded else self._requested_device
        req_compute = self._compute_type
        self._model_path = model_path
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
        self._read_safeguards(config)
        model_path = Path(config["model_path"])
        if str(model_path) != self._model_path:
            self.unload()
        if not self._downgraded:
            self._device, self._compute_type = _detect_device(config)
            self._requested_device = self._device
        self._ready = False
        self._error = None
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
        self._read_safeguards(config)
        self._ready = False
        self._error = None
        try:
            model_path = ensure_model(config, status_cb, progress_cb, cancel_event)
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Model download cancelled")
            if model_path != self._model_path:
                self.unload()
            if not self._downgraded:
                self._device, self._compute_type = _detect_device(config)
                self._requested_device = self._device
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
        self._downgraded = False
        self._decode_batch_size = 0
        self._model_path = ""

    def _decode_runner(self, options: dict[str, Any]) -> Any:
        if self._pipeline is None:
            options.pop("batch_size", None)
            return self._model
        if self._decode_batch_size:
            options["batch_size"] = min(int(options.get("batch_size", 16)), self._decode_batch_size)
        return self._pipeline

    def _recover_decode(self, options: dict[str, Any], oom: bool, log_cb: Callable[[str], None] | None) -> None:
        if oom and int(options.get("batch_size", 1)) > 1:
            self._decode_batch_size = options["batch_size"] = 1
            message = "CUDA ran out of memory; retrying the remaining audio with batch size 1."
        else:
            target = "cuda" if oom and self._compute_type not in ("int8", "int8_float16") else "cpu"
            compute = "int8_float16" if target == "cuda" else "int8"
            self._device, self._compute_type, self._downgraded = target, compute, True
            self._ready = False
            self._pipeline = self._model = None
            gc.collect()
            try:
                self._model = WhisperModel(self._model_path, device=target, compute_type=compute)
            except RuntimeError:
                if target != "cuda":
                    raise
                target, compute = "cpu", "int8"
                self._device, self._compute_type = target, compute
            if self._model is None:
                self._model = WhisperModel(self._model_path, device=target, compute_type=compute)
            self._capture_effective_device(target, compute)
            self._pipeline = self._wrap_for_batched()
            self._ready = True
            self._downgraded = True
            message = f"CUDA decode failed; retrying the remaining audio on {target}/{compute}."
        if log_cb:
            log_cb(message)
        else:
            logger.warning(message)

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

        runner = WhisperDecode(
            self._decode_runner, lambda: self._device.split(":")[0] == "cuda",
            lambda options, oom: self._recover_decode(options, oom, log_cb), self._vad_window_s,
        )
        if self._pipeline is not None:
            transcribe_kwargs["batch_size"] = int(batch_size)

        with vad_window.windowed_vad(self._vad_window_s):
            segments_iter, info = runner.transcribe(audio_path, **transcribe_kwargs)
        # Drop runs of identical lines (no restart on this path).
        segments_iter = loop_guard.guard_repeats(
            segments_iter, limit=self._loop_guard_repeats, on_event=log_cb,
        )

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
