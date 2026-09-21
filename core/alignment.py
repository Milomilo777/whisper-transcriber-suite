"""Word-level alignment refinement via stable-ts (opt-in).

``stable_whisper`` (PyPI: ``stable-ts``) does dynamic-time-warping
on the cross-attention weights to lock down word start/end times to
± 50 ms accuracy, much better than Whisper's native word timestamps
which can wobble by 100–300 ms on short words.

We invoke it as a post-processor: after our segments are written we
build a ``stable_whisper.WhisperResult`` from them, call
``model.align(audio, result)``, and splice the refined word lists
back into the caller's segments. The model is a Whisper checkpoint
loaded via ``stable_whisper.load_model("tiny")`` — small enough
(~75 MB) to keep the alignment overhead minimal.

Previous versions of this module passed the segment dict list
directly to ``stable_whisper.align()`` which expected text + audio
+ ``original_split=True``; that signature mismatch silently aborted
every alignment run (the caller swallowed the resulting TypeError
in a broad ``except Exception``). The current implementation calls
the model's own ``.align()`` method which accepts a WhisperResult
shaped exactly like what the caller already has.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from ._gc_import_guard import gc_disabled_import
from ._liveness_tick import liveness_tick

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """True iff stable-ts imports cleanly.

    stable-ts pulls in torch, a heavy C-extension package -- see
    core/_gc_import_guard.py for why the import runs under a shared,
    process-wide GC-disable guard.
    """
    with gc_disabled_import():
        try:
            import stable_whisper  # type: ignore[import-not-found] # noqa: F401
        except ImportError:
            return False
        else:
            return True


def availability_reason() -> str:
    if is_available():
        return ""
    return "stable-ts Python package not installed"


def _build_whisper_result(stable_whisper_mod: Any, segments_data: list[dict[str, Any]],
                          language: str | None) -> Any:
    """Construct a ``WhisperResult`` from our segment dicts.

    stable-ts internally wants ``WhisperResult(dict)`` where the
    dict carries ``segments`` + ``language``. We build the minimal
    shape and let stable-ts fill word data on align.

    One payload entry per input segment, never fewer: the caller
    splices refined words back by index, so dropping a segment (the
    old ``if isinstance(text, str)`` filter) shifted every later
    segment's words onto the wrong segment. Non-string text is
    coerced to ``""`` instead of dropping the entry.
    """
    payload_segments = []
    for s in segments_data:
        text = s.get("text", "")
        payload_segments.append({
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("end", 0.0)),
            "text": text if isinstance(text, str) else "",
        })
    payload = {
        "segments": payload_segments,
        "language": (language or "en"),
    }
    return stable_whisper_mod.WhisperResult(payload)


def refine_word_timestamps_in_place(
    audio_path: str,
    segments_data: list[dict[str, Any]],
    *,
    language: str | None = None,
    model_name: str = "tiny",
    log_cb: Callable[[str], None] | None = None,
) -> bool:
    """Refine word timestamps in ``segments_data`` (in place).

    Each segment gets / replaces its ``words`` list with the DTW-
    refined timings. The segment ``start`` / ``end`` are not modified
    (we trust faster-whisper's segment-level timestamps); only the
    word grain inside each segment is updated.

    Returns True iff refinement actually happened (model loaded,
    align call produced non-empty refined segments, words spliced
    in). Returns False on graceful skip (empty input, alignment
    returned None — common when the language guess is wrong).

    Raises:
        RuntimeError if stable-ts is not installed.
        FileNotFoundError if audio_path doesn't exist.
    """
    if not is_available():
        raise RuntimeError(availability_reason())

    if not segments_data:
        return False

    if not audio_path or not os.path.isfile(audio_path):
        # Surface as FileNotFoundError so the caller can distinguish
        # "stable-ts is fine but the audio file vanished" from
        # "stable-ts itself crashed".
        raise FileNotFoundError(f"audio file not found: {audio_path!r}")

    import stable_whisper  # type: ignore[import-not-found]

    # ``model`` is typed by pyright as torch.Tensor (from
    # stable_whisper's loose annotations) but at runtime is a
    # WhisperModel-like instance with an .align method. The
    # type: ignore line silences the false-positive callable check.
    model: Any = stable_whisper.load_model(model_name)

    # Build a WhisperResult from the segments we already have, then
    # ask the loaded model to align it. The model's ``.align`` accepts
    # (audio, WhisperResult) and returns a refined WhisperResult.
    coarse_result = _build_whisper_result(stable_whisper, segments_data, language)

    try:
        # ``model.align`` is a single long-running C call (DTW on the
        # cross-attention weights) that emits nothing while it runs.
        # Wrap it in a liveness tick so the worker's parent watchdog
        # sees a heartbeat at least every 10 s on slow CPUs.
        with liveness_tick(log_cb, "stable-ts alignment"):
            refined = model.align(
                audio_path,
                coarse_result,
                language=language or coarse_result.language or "en",
            )
    except Exception as e:  # noqa: BLE001
        # stable-ts sometimes raises on a clip that's harder to align
        # than expected (very fast speech, music backdrop). Treat as
        # a soft failure — the caller falls back to the original
        # word timestamps.
        logger.exception("stable-ts align raised: %s", e)
        return False

    # stable-ts returns None when alignment fails internally (e.g.
    # tokenizer mismatch). Without this guard, the next attribute
    # access raised AttributeError on NoneType.
    if refined is None:
        logger.warning("stable-ts align returned None — refinement skipped")
        return False

    refined_segments = getattr(refined, "segments", None) or []
    if not refined_segments:
        return False

    # Splice the refined word lists into segments_data, matching by
    # index. stable-ts preserves order when aligning a sequence.
    n = min(len(refined_segments), len(segments_data))
    spliced_any = False
    for i in range(n):
        words = getattr(refined_segments[i], "words", None) or []
        seg_words: list[dict[str, Any]] = []
        for w in words:
            seg_words.append({
                "start": float(getattr(w, "start", 0.0)),
                "end": float(getattr(w, "end", 0.0)),
                "word": str(getattr(w, "word", "") or "").strip(),
                "probability": float(getattr(w, "probability", 1.0)),
            })
        if seg_words:
            segments_data[i]["words"] = seg_words
            spliced_any = True
    return spliced_any
