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
import math
import os
import threading
import time
from collections import deque
from contextlib import nullcontext
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..hardware import DeviceSelection

from faster_whisper import WhisperModel as _WhisperModel

try:  # 1.0.3+ ships this; older wheels do not
    from faster_whisper import BatchedInferencePipeline as _BatchedInferencePipeline  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    _BatchedInferencePipeline = None  # type: ignore[assignment]

from .. import gpu_temperature, loop_guard, speech_collect, vad_window
from ..config import load_config
from ..model_manager import DownloadCancelled, ensure_model
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)

# Chunk metadata uses the same speech-only timeline as batched alignment;
# upstream restores VAD gaps afterwards. Keep the exact duration local to this
# forward call without mutating the shared model or upstream rounded frames.
_batch_alignment: ContextVar[Any] = ContextVar("batch_alignment", default=None)
_batch_window_ends: ContextVar[deque[float | None] | None] = ContextVar(
    "batch_window_ends", default=None,
)


if _BatchedInferencePipeline is not None:
    class BatchedInferencePipeline(_BatchedInferencePipeline):
        """Pass exact chunk bounds to fallback without altering valid alignment."""

        def transcribe(self, audio, *args, **kwargs):
            with speech_collect.batch_source_bounds():
                return super().transcribe(audio, *args, **kwargs)

        def forward(self, features, tokenizer, chunks_metadata, options):
            token = _batch_alignment.set((self.model, chunks_metadata))
            try:
                groups = super().forward(features, tokenizer, chunks_metadata, options)
            finally:
                _batch_alignment.reset(token)
            bounds = _batch_window_ends.get()
            if bounds is not None:
                for group, chunk in zip(groups, chunks_metadata):
                    # The source sample bounds survive VAD timestamp remapping.
                    end = chunk.get("_wts_source_end")
                    pieces = chunk.get("segments")
                    if end is None and pieces:
                        # Explicit clips bypass collect_chunks.
                        end = pieces[-1]["end"] / self.model.feature_extractor.sampling_rate
                    bounds.extend([end] * len(group))
            return groups

        def _batched_segments_generator(
            self, features, tokenizer, chunks_metadata, batch_size, options, log_progress,
        ):
            # Associate bounds in yield order because nearby chunks can share a
            # rounded seek. Scope the queue to each next() for interleaved decodes.
            bounds: deque[float | None] = deque()
            segments = super()._batched_segments_generator(
                features, tokenizer, chunks_metadata, batch_size, options, log_progress,
            )
            try:
                while True:
                    token = _batch_window_ends.set(bounds)
                    try:
                        segment = next(segments)
                    except StopIteration:
                        return
                    finally:
                        _batch_window_ends.reset(token)
                    end = bounds.popleft() if bounds else None
                    if end is not None and hasattr(segment, "__dict__"):
                        setattr(segment, "_decode_window_end", end)
                    yield segment
            finally:
                segments.close()
else:  # pragma: no cover - compatibility with older faster-whisper wheels
    BatchedInferencePipeline = None  # type: ignore[assignment]


def _chunk_window(chunk):
    start, duration = chunk.get("offset"), chunk.get("duration")
    if any(isinstance(value, bool) for value in (start, duration)):
        return None
    try:
        start, duration = float(start), float(duration)
    except (TypeError, ValueError, OverflowError):
        return None
    end = start + duration
    if (not all(math.isfinite(value) for value in (start, duration, end))
            or start < 0 or duration <= 0 or end <= start):
        return None
    return start, end


def segment_decode_end(seg: Any, cue_end: float, offset: float = 0.0) -> float:
    """Bound accepted progress by the audio window that could produce the cue."""
    window_end = getattr(seg, "_decode_window_end", None)
    return min(cue_end, window_end + offset) if window_end is not None else cue_end


def _alignment_window(original, frames, frames_per_second):
    """Return the encoded frame window when its group metadata is usable."""
    # Adapted from faster-whisper (https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) - use the decode-window seek and frame count.
    if not original:
        return None
    seek = original[0][0].get("seek")
    if any(segment.get("seek") != seek for segment, _, _ in original):
        return None
    if any(isinstance(value, bool) for value in (seek, frames, frames_per_second)):
        return None
    try:
        seek, frames, rate = float(seek), float(frames), float(frames_per_second)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not all(math.isfinite(value) for value in (seek, frames, rate))
            or seek < 0 or frames <= 0 or rate <= 0):
        return None
    start, end = seek / rate, (seek + frames) / rate
    return (start, end) if math.isfinite(end) and end > start else None


class WhisperModel(_WhisperModel):
    """Keep decoded text when optional alignment cannot provide usable bounds.

    The sequential and batched upstream paths both call this seam before
    publishing segments. Tokens remain authoritative; word times are optional.
    """

    # Adapted from faster-whisper (https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) — guard the alignment mutation seam.
    def add_word_timestamps(
        self, segments, tokenizer, encoder_output, num_frames,
        prepend_punctuations, append_punctuations, last_speech_timestamp,
    ):
        raw = [[(segment, segment["start"], segment["end"])
                for segment in group] for group in segments]
        failed = False
        try:
            result = super().add_word_timestamps(
                segments, tokenizer, encoder_output, num_frames,
                prepend_punctuations, append_punctuations, last_speech_timestamp,
            )
        except IndexError:
            # Empty/truncated alignment output can fail in find_alignment or
            # its consumer. Restore the whole call, including earlier groups.
            logger.warning("Word alignment index error; retaining decoded text with raw segment bounds.",
                           exc_info=True)
            failed = True
            result = last_speech_timestamp
        frame_counts = num_frames if isinstance(num_frames, (list, tuple)) else [num_frames] * len(raw)
        batch = _batch_alignment.get()
        for index, (group, original) in enumerate(zip(segments, raw)):
            unusable = failed or any(s["end"] <= s["start"] for s, _, _ in original)
            # Sequential get_end prefers earlier aligned words to a later
            # raw segment. Only text the caller will emit can require recovery.
            text_tail = (next((i for i in range(len(group) - 1, -1, -1)
                               if tokenizer.decode(group[i]["tokens"]).strip()), -1)
                         if (not unusable and batch is None
                             and any(segment.get("words") for segment in group)
                             and any(not segment.get("words") for segment in group)) else -1)
            unaligned_tail = (text_tail >= 0 and not group[text_tail].get("words")
                              and any(segment.get("words") for segment in group[:text_tail]))
            if not (unusable or unaligned_tail):
                continue
            # Restore the whole decode group. Upstream get_end searches words
            # across the group before falling back to the last segment end;
            # keeping earlier aligned words would seek back into emitted audio.
            logger.warning("Word alignment unusable; retaining the decode group with fallback bounds.")
            if unaligned_tail and text_tail + 1 < len(original):
                # Fold non-emitting suffix tokens into the last spoken segment
                # without advancing seek through their unused raw interval.
                tail = original[text_tail][0]
                tail["tokens"] = (list(tail["tokens"])
                                  + [token for segment, _, _ in original[text_tail + 1:]
                                     for token in segment["tokens"]])
                original = original[:text_tail + 1]
            window = (_alignment_window(original, frame_counts[index],
                                        getattr(self, "frames_per_second", None))
                      if len(frame_counts) == len(raw) else None)
            if batch is not None and batch[0] is self and len(batch[1]) == len(raw):
                # Batched frame counts ceil(duration) to whole seconds. Only
                # exact metadata can bound a short chunk or sub-frame offset.
                window = _chunk_window(batch[1][index])
            restored = []
            pending = []
            for segment, start, end in original:
                if end < start:
                    raise RuntimeError("Cannot preserve decoded text: invalid raw segment bounds")
                if window is not None:
                    if start >= window[1]:
                        pending.extend(segment["tokens"])
                        continue
                    end = min(end, window[1])
                segment.update(start=start, end=end, words=[])
                if end == start:
                    pending.extend(segment["tokens"])
                    continue
                segment["tokens"] = pending + segment["tokens"]
                pending = []
                if restored and start < restored[-1]["end"]:
                    restored[-1]["tokens"].extend(segment["tokens"])
                    restored[-1]["end"] = max(restored[-1]["end"], end)
                else:
                    restored.append(segment)
            if (not restored and pending and window is not None
                    and any(end > start for _, start, end in original)):
                # All predicted intervals can overshoot a short final window.
                # Its actual encoded frames give a coarse segment bound;
                # optional word timestamps remain unavailable.
                segment = original[0][0]
                segment.update(start=window[0], end=window[1], words=[], tokens=pending)
                restored.append(segment)
                pending = []
            if not restored and pending:
                raise RuntimeError("Cannot preserve decoded text: no positive raw segment bounds")
            if pending:
                restored[-1]["tokens"].extend(pending)
                if window is not None:
                    # get_end controls the sequential decoder's next seek.
                    # Late text already belongs to this completed window.
                    restored[-1]["end"] = window[1]
            # Batched forward has decoded text before this seam; sequential
            # generation decodes afterwards. Keep both representations equal.
            for segment in restored:
                if "text" in segment:
                    segment["text"] = tokenizer.decode(segment["tokens"])
            group[:] = restored
        return result


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
        temperature: Callable[[Any], gpu_temperature.TemperatureController | None] | None = None,
    ) -> None:
        self.audio_offset = 0.0
        self.language_offset = 0.0
        self._runner = runner
        self._is_cuda = is_cuda
        self._recover = recover
        self._window_s = window_s
        self._temperature = temperature
        self.before_retry: Callable[[], None] = lambda: None
        self.retry_enabled = True

    def detect_language(self, **kwargs: Any) -> Any:
        while True:
            try:
                runner = self._runner({})
                factory = self._temperature
                control = factory(runner) if factory is not None else None
                if control is None:
                    return runner.detect_language(**kwargs)

                def detect() -> Any:
                    yield runner.detect_language(**kwargs)

                # Include language-ID work in the same cooling/cancel contract
                # as decoding, including its final cooling gap before return.
                results = list(control.pace(detect()))
                if not results:
                    raise RuntimeError("Language detection cancelled")
                return results[0]
            except RuntimeError as exc:
                failure = _cuda_failure(exc)
                if not self.retry_enabled or not self._is_cuda() or not failure:
                    raise
            self.before_retry()
            self._recover({}, failure == "out_of_memory")

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        options = dict(kwargs)
        vad_options = options.get("vad_parameters")
        padding_ms = (vad_options.get("speech_pad_ms", 400) if isinstance(vad_options, dict)
                      else getattr(vad_options, "speech_pad_ms", 400))

        def start(source: Any, source_offset: float = 0.0) -> tuple[Any, Any]:
            self.audio_offset = source_offset
            while True:
                try:
                    with (
                        vad_window.windowed_vad(self._window_s) if self._window_s is not None else nullcontext(),
                        vad_window.clamp_vad_cue_bounds(padding_ms if options.get("vad_filter") else 0),
                    ):
                        runner = self._runner(options)
                        factory = self._temperature
                        control = factory(runner) if factory is not None else None
                        if control is not None:
                            control.before_step()
                        segments, info = runner.transcribe(source, **options)
                        return (control.pace(segments) if control is not None else segments), info
                except RuntimeError as exc:
                    failure = _cuda_failure(exc)
                    if not self.retry_enabled or not self._is_cuda() or not failure:
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
                            cursor = max(cursor, segment_decode_end(
                                seg, float(getattr(seg, "end", 0.0) or 0.0),
                            ))
                            yield seg
                        return
                    except RuntimeError as exc:
                        failure = _cuda_failure(exc)
                        oom = failure == "out_of_memory"
                        if not self.retry_enabled or not self._is_cuda() or not failure:
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
                        clips = kwargs.get("clip_timestamps")
                        if clips is not None and not (isinstance(clips, (str, list)) and len(clips) == 0):
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
                    iterator, _ = start(source, cursor)
            finally:
                _close_iterator_quietly(iterator)
                for path in temporary:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        return iterate(), info


def _detect_device(config: dict[str, Any]) -> DeviceSelection:
    """Delegate to the canonical detector in ``core.hardware``.

    Kept as a module-level alias so existing call sites + tests that
    import ``_detect_device`` from this module don't need to move.
    """
    from ..hardware import resolve_device_for
    return resolve_device_for(config)


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
        self._preflight_fallback_reason: str | None = None
        self._fallback_reason = ""
        # Long-file safeguards read from config at load time (see
        # core.vad_window and core.loop_guard).
        self._vad_window_s = vad_window.DEFAULT_WINDOW_S
        self._loop_guard_repeats = loop_guard.DEFAULT_REPEATS
        self._decode_batch_size = 0
        self._model_path = ""
        self._temperature_config: dict[str, Any] = {}

    def _read_safeguards(self, config: dict[str, Any]) -> None:
        self._temperature_config = dict(config)
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
    def fallback_reason(self) -> str:
        return self._fallback_reason if self._downgraded else ""

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
            if self._preflight_fallback_reason and self._device == "cpu":
                self._requested_device = "auto"
                self._downgraded = True
                self._fallback_reason = self._preflight_fallback_reason
                message = f"GPU unavailable ({self._preflight_fallback_reason}); falling back to CPU (slower)."
                logger.warning(message)
                if status_cb:
                    try:
                        status_cb(message)
                    except Exception:
                        logger.debug("CPU fallback notification failed", exc_info=True)
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
        self._fallback_reason = f"{error} {reason}"

    def load_existing(self, status_cb: Callable[[str], None] | None = None) -> bool:
        config = load_config(fetch_online=False)  # worker path: local keys only
        self._read_safeguards(config)
        model_path = Path(config["model_path"])
        if str(model_path) != self._model_path:
            self.unload()
        self._select_device(config)
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
            self._select_device(config)
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

    def _select_device(self, config: dict[str, Any]) -> None:
        configured = str(config.get("device") or "auto").strip().lower()
        if (not self._downgraded or self._requested_device == "auto"
                or (configured != "auto" and configured != self._requested_device)):
            selection = _detect_device(config)
            self._device, self._compute_type = selection.device, selection.compute_type
            self._requested_device = self._device
            self._preflight_fallback_reason = selection.fallback_reason
            self._fallback_reason = ""
            self._downgraded = False

    def unload(self) -> None:
        self._model = None
        self._pipeline = None
        self._ready = False
        self._downgraded = False
        self._preflight_fallback_reason = None
        self._fallback_reason = ""
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
            self._decode_batch_size = options["batch_size"] = max(1, int(options["batch_size"]) // 2)
            message = f"CUDA ran out of memory; retrying the remaining audio with batch size {self._decode_batch_size}."
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

        control = None

        def temperature(_runner: Any) -> gpu_temperature.TemperatureController | None:
            nonlocal control
            if self._device.split(":")[0] != "cuda":
                return None
            if control is None:
                control = gpu_temperature.for_model(
                    self._model, self._temperature_config, log=log_cb or logger.info,
                    cancelled=cancelled, paused=paused)
            return control

        runner = WhisperDecode(
            self._decode_runner, lambda: self._device.split(":")[0] == "cuda",
            lambda options, oom: self._recover_decode(options, oom, log_cb), self._vad_window_s,
            temperature=temperature,
        )
        if self._pipeline is not None:
            if self._decode_batch_size:
                batch_size = min(batch_size, self._decode_batch_size)
            if self._device.split(":")[0] == "cuda":
                from ..hardware import cuda_batch_size
                batch_size = cuda_batch_size(
                    int(batch_size), self._model, model_path=self._model_path)
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
