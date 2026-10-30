"""Gather the speech-only audio in one copy instead of one copy per speech chunk.

faster-whisper (checked on 1.2.1) builds the speech-only audio for the plain
(CPU) path in ``vad.collect_chunks`` with an unlimited ``max_duration`` by
growing one array: ``current = np.concatenate((current, audio[start:end]))``
for every speech region the VAD found. Each step copies everything gathered
so far, so the work grows with the square of the file length: a long lecture
has thousands of speech regions, and the copies add up to hundreds of GB for a
multi-hour file. Measured before language detection with ``small`` on a 4-core
laptop: 20 s for 1 hour of audio, 57 s for 2 hours, 110 s for 3 hours.

:func:`install` routes ``collect_chunks`` (in ``faster_whisper.vad`` and the
name ``faster_whisper.transcribe`` imported from it) through a version that,
for ``max_duration == inf``, joins all regions with ONE ``np.concatenate`` and
returns the same list and metadata as upstream. Finite ``max_duration`` calls
(the batched GPU pipeline) take upstream's code unchanged. :func:`install`
checks the fast path against upstream first and leaves faster-whisper alone if
they differ.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable

logger = logging.getLogger(__name__)

_MARKER = "_wts_speech_collect"


def gather_speech(audio: Any, chunks: list[dict], sampling_rate: int = 16000) -> tuple[list, list]:
    """``collect_chunks(audio, chunks, sampling_rate, max_duration=inf)`` in one copy."""
    import numpy as np

    pieces = [np.array([], dtype=np.float32)]
    pieces.extend(audio[chunk["start"]:chunk["end"]] for chunk in chunks)
    duration = sum(chunk["end"] - chunk["start"] for chunk in chunks)
    metadata = {
        "offset": 0 / sampling_rate,
        "duration": duration / sampling_rate,
        "segments": list(chunks),
    }
    return [np.concatenate(pieces)], [metadata]


def _make_collect(original: Callable[..., Any]) -> Callable[..., Any]:
    def collect_chunks(audio: Any, chunks: list[dict], sampling_rate: int = 16000,
                       max_duration: float = float("inf"), *args: Any, **kwargs: Any) -> Any:
        if args or kwargs or not chunks or not (
                isinstance(max_duration, float) and math.isinf(max_duration)
                and max_duration > 0):
            # Arguments a later faster-whisper may add: only upstream knows them.
            return original(audio, chunks, sampling_rate, max_duration, *args, **kwargs)
        return gather_speech(audio, chunks, sampling_rate)

    setattr(collect_chunks, _MARKER, True)
    setattr(collect_chunks, "__wrapped__", original)
    return collect_chunks


def _matches_upstream(original: Callable[..., Any]) -> bool:
    import numpy as np

    audio = np.arange(4000, dtype=np.float32) / 4000
    chunks = [{"start": 10, "end": 500}, {"start": 500, "end": 510},
              {"start": 900, "end": 900}, {"start": 1200, "end": 3999}]
    want_audio, want_meta = original(audio, [dict(c) for c in chunks], 16000)
    got_audio, got_meta = gather_speech(audio, [dict(c) for c in chunks], 16000)
    if len(want_audio) != 1 or len(got_audio) != 1:
        return False
    return (want_audio[0].dtype == got_audio[0].dtype
            and np.array_equal(want_audio[0], got_audio[0])
            and want_meta == got_meta)


def install() -> bool:
    """Route faster-whisper's ``collect_chunks`` through the one-copy version.

    Idempotent. Returns False and changes nothing when faster-whisper's VAD
    module has another shape or its result differs from the fast path.
    """
    try:
        from faster_whisper import transcribe as fw_transcribe
        from faster_whisper import vad as fw_vad
    except Exception as e:  # noqa: BLE001 - optional engine, any import error
        logger.warning("speech gather unavailable (faster_whisper: %s)", e)
        return False
    current = getattr(fw_vad, "collect_chunks", None)
    if current is None or not callable(current):
        logger.warning("speech gather unavailable: faster_whisper.vad.collect_chunks missing")
        return False
    if not getattr(current, _MARKER, False):
        try:
            ok = _matches_upstream(current)
        except Exception as e:  # noqa: BLE001 - any upstream difference: keep upstream
            logger.warning("speech gather not used: self-check failed (%s: %s)",
                           type(e).__name__, e)
            return False
        if not ok:
            logger.warning("speech gather not used: this faster-whisper collects differently")
            return False
        current = _make_collect(current)
        fw_vad.collect_chunks = current
    # transcribe.py imported the name at its own import time.
    if getattr(fw_transcribe, "collect_chunks", None) is not current:
        imported = getattr(fw_transcribe, "collect_chunks", None)
        if imported is getattr(current, "__wrapped__", None):
            fw_transcribe.collect_chunks = current
        elif imported is not None and not getattr(imported, _MARKER, False):
            logger.warning("speech gather: faster_whisper.transcribe holds another collect_chunks")
            return False
    return True
