"""Silero VAD with a fresh model state per fixed window (long-file fix).

faster-whisper (checked on 1.2.1) runs Silero VAD over the whole file in a
single pass and carries the model's LSTM state (``h``, ``c``) from the first
frame to the last. On a long recording with stretches of loud music that
state can stay in "not speech" for minutes: later speech is never detected,
Whisper never sees it, and the output shows minutes of audio as one-word
segments with no warning. Measured on a 62-minute lecture: one pass found
512 s of speech; the same model with a fresh state every 30 s found 1,615 s.
A 3-minute span with 57 s of speech yielded 0 s once just 30 s of the
preceding music was fed in first.

This module wraps faster-whisper's cached VAD model so that, inside
:func:`windowed_vad`, the speech probabilities are computed window by window
with a fresh state. faster-whisper's own ``get_speech_timestamps`` then runs
its usual start/end logic over the joined probabilities, so a speech region
that crosses a window boundary is not cut there. Audio shorter than one
window gives exactly the single-pass result. Outside the context (and in
other threads) the model behaves exactly as upstream.

The setting is the ``vad_window_s`` config key; ``0`` restores the
single-pass behaviour. Windowing needs faster-whisper 1.1+ (one whole-file
model call); on 1.0 :func:`install` leaves faster-whisper alone.
"""
from __future__ import annotations

import contextvars
import inspect
import logging
import math
from contextlib import contextmanager
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_S = 30.0
SAMPLE_RATE = 16000

# Window length (seconds) for VAD calls made in the current thread/context.
# 0 = upstream single-pass behaviour.
_WINDOW_S: contextvars.ContextVar[float] = contextvars.ContextVar(
    "wts_vad_window_s", default=0.0
)

_MARKER = "_wts_windowed_vad"


def window_seconds(cfg: dict[str, Any]) -> float:
    """``vad_window_s`` from *cfg* as a non-negative float.

    A missing key means the default; ``true`` means the default and
    ``false`` one pass; a value that is not a number, or is negative, means 0
    (single pass) so a broken setting never crashes a run.
    """
    raw = cfg.get("vad_window_s", DEFAULT_WINDOW_S)
    if isinstance(raw, bool):
        return DEFAULT_WINDOW_S if raw else 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("vad_window_s=%r is not a number; using one pass", raw)
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    return value


def _window_samples(seconds: float, frame: int) -> int:
    """Window length in samples, a whole number of *frame*-sample frames."""
    if seconds <= 0 or frame <= 0:
        return 0
    frames = int(seconds * SAMPLE_RATE) // frame
    return frames * frame


class WindowedVadModel:
    """Stand-in for faster-whisper's ``SileroVADModel`` that windows its input.

    faster-whisper 1.1+ calls the model once with the whole padded file:
    ``model(audio)`` with a 1-D array (1.2) or a ``(1, N)`` array (1.1), and
    each call starts from a zero state. Calling it once per window is what
    gives each window a fresh state. Any other call (faster-whisper 1.0's
    per-chunk ``model(chunk, state, context, sr)``) and every other attribute
    go to the real model unchanged.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __call__(self, audio: Any, *args: Any, **kwargs: Any) -> Any:
        import numpy as np

        num_samples = args[0] if args else kwargs.get("num_samples", 512)
        whole_file_call = (
            len(args) <= 2
            and all(isinstance(a, int) for a in args)
            and set(kwargs) <= {"num_samples", "context_size_samples"}
            and isinstance(num_samples, int)
        )
        ndim = getattr(audio, "ndim", 0)
        if not whole_file_call or not (
            ndim == 1 or (ndim == 2 and audio.shape[0] == 1)
        ):
            return self.inner(audio, *args, **kwargs)
        length = audio.shape[-1]
        window = _window_samples(_WINDOW_S.get(), num_samples)
        if window <= 0 or length <= window:
            return self.inner(audio, *args, **kwargs)
        # ``audio`` is a whole number of frames (faster-whisper pads it), and
        # so is ``window``, so every slice, the last one included, is too.
        # Copies: the model writes into its input (it zeroes the last frame's
        # context), which must not reach the caller's array.
        parts = [
            self.inner(audio[..., start:start + window].copy(), *args, **kwargs)
            for start in range(0, length, window)
        ]
        return np.concatenate(parts, axis=ndim - 1)


def _whole_file_model(model_cls: Any) -> bool:
    """True for the 1.1+ ``SileroVADModel.__call__(audio, num_samples, ...)``."""
    call = getattr(model_cls, "__call__", None)
    try:
        params = inspect.signature(call).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return "num_samples" in params and "context_size_samples" in params


def install() -> bool:
    """Route faster-whisper's VAD model lookup through :class:`WindowedVadModel`.

    Idempotent. Returns False (and leaves faster-whisper untouched) when its
    VAD module does not have the expected shape: faster-whisper 1.0 (a
    per-chunk model with explicit state), or a later release that reorganised
    the module. The run then uses faster-whisper's own VAD.
    """
    try:
        from faster_whisper import vad as fw_vad
    except Exception as e:  # noqa: BLE001 - optional engine, any import error
        logger.warning("windowed VAD unavailable (faster_whisper.vad: %s)", e)
        return False
    current = getattr(fw_vad, "get_vad_model", None)
    if current is None or not callable(current):
        logger.warning(
            "windowed VAD unavailable: faster_whisper.vad.get_vad_model missing"
        )
        return False
    if getattr(current, _MARKER, False):
        return True
    if not _whole_file_model(getattr(fw_vad, "SileroVADModel", None)):
        logger.info(
            "windowed VAD not used: this faster-whisper's VAD model is not the "
            "whole-file kind (1.1+)"
        )
        return False
    original: Callable[[], Any] = current

    def get_vad_model() -> WindowedVadModel:
        return WindowedVadModel(original())

    setattr(get_vad_model, _MARKER, True)
    setattr(get_vad_model, "__wrapped__", original)
    fw_vad.get_vad_model = get_vad_model
    return True


@contextmanager
def windowed_vad(seconds: float) -> Generator[None, None, None]:
    """Use a fresh VAD state every *seconds* for VAD calls in this context.

    faster-whisper runs the VAD inside ``transcribe()`` before it returns the
    lazy segment iterator, so wrapping that call is enough. ``seconds <= 0``
    keeps the single-pass behaviour.
    """
    if seconds > 0:
        install()
    token = _WINDOW_S.set(max(0.0, float(seconds)))
    try:
        yield
    finally:
        _WINDOW_S.reset(token)
