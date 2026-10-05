"""Stop repetition loops while segments are still being decoded.

Whisper can fall into a loop on long files, above all over music: with
``condition_on_previous_text`` on, the previous window's text is fed back in
as the prompt and the model writes the same short line again and again (one
real run produced "so good" as 30 one-second segments in a row, and decoding
slowed to about 0.12x real time). The hallucination detector runs only after
decoding, and it looks for repeats inside one segment, so it never sees this.

:func:`guard_repeats` wraps the lazy segment iterator. When ``limit``
consecutive segments carry the same text (compared on letters and digits
only, case-folded), it keeps the first one and either

* restarts decoding from the start of the second one through the caller's
  ``restart`` callback (the transcriber decodes again without the previous
  text as a prompt, which ends the self-feeding loop), once per file; or
* when no restart is possible or the restart was already used, drops the
  repeats until a different line arrives (repeats also happen over music
  without conditioning).

Shorter runs pass through unchanged, delayed by at most ``limit - 1``
segments while the guard waits to see whether the run continues.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

DEFAULT_REPEATS = 3


@dataclass
class LoopGuardStats:
    restarts: int = 0
    dropped: int = 0


def repeat_limit(cfg: dict[str, Any]) -> int:
    """``loop_guard_repeats`` from *cfg*; values below 2 switch the guard off."""
    raw = cfg.get("loop_guard_repeats", DEFAULT_REPEATS)
    if isinstance(raw, bool):
        return 0 if not raw else DEFAULT_REPEATS
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "loop_guard_repeats=%r is not a whole number; using %d",
            raw, DEFAULT_REPEATS,
        )
        return DEFAULT_REPEATS
    return value if value >= 2 else 0


def repeat_key(text: str) -> str:
    """The comparison key: letters and digits only, NFKC, case-folded.

    "So good." and "so good" match; a line with no letters or digits (music
    notes, punctuation) gives "" and never counts as a repeat.
    """
    norm = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(ch for ch in norm if ch.isalnum())


def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02}:{(s % 3600) // 60:02}:{s % 60:02}"


def _close(iterator: Any) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 - best effort, the decode is abandoned
            logger.debug("closing a replaced segment iterator raised", exc_info=True)


def guard_repeats(
    segments: Iterable[Any],
    *,
    limit: int,
    restart: Callable[[float], Iterable[Any]] | None = None,
    on_event: Callable[[str], None] | None = None,
    stats: LoopGuardStats | None = None,
    previous_text: str = "",
) -> Iterator[Any]:
    """Yield *segments* with runs of ``limit`` identical lines contained.

    Segments need ``.text`` and ``.start``. ``restart(at)`` must return a new
    iterator of segments that starts at *at* seconds on the same timeline; it
    is called at most once. ``previous_text`` is the line written just before
    these segments (a resumed run), so a loop that crosses the seam is seen.
    """
    stats = stats if stats is not None else LoopGuardStats()
    if limit < 2:
        yield from segments
        return

    def event(msg: str) -> None:
        logger.warning(msg)
        if on_event is not None:
            on_event(msg)

    it: Iterator[Any] = iter(segments)
    prev_key = repeat_key(previous_text)
    held: list[Any] = []
    collapsing = False
    can_restart = restart is not None
    try:
        while True:
            try:
                seg = next(it)
            except StopIteration:
                break
            text = str(getattr(seg, "text", "") or "").strip()
            key = repeat_key(text)
            if key and key == prev_key:
                if collapsing:
                    stats.dropped += 1
                    continue
                held.append(seg)
                if len(held) + 1 < limit:
                    continue
                at = float(getattr(held[0], "start", 0.0) or 0.0)
                shown = text if len(text) <= 40 else text[:37] + "..."
                if can_restart and restart is not None:
                    can_restart = False
                    try:
                        new_segments = restart(at)
                    except Exception as e:  # noqa: BLE001 - fall back to dropping
                        event(
                            f"Loop guard: could not decode again from {_fmt(at)} "
                            f"({e}); dropping the repeats instead."
                        )
                    else:
                        event(
                            f"Loop guard: {limit} identical lines {shown!r} at "
                            f"{_fmt(at)}; decoding again from there without the "
                            "previous text as a prompt."
                        )
                        _close(it)
                        it = iter(new_segments)
                        held = []
                        stats.restarts += 1
                        continue
                event(
                    f"Loop guard: dropping repeats of {shown!r} from {_fmt(at)}."
                )
                stats.dropped += len(held)
                held = []
                collapsing = True
                continue
            collapsing = False
            if held:
                yield from held
                held = []
            yield seg
            prev_key = key
        if held:
            yield from held
    finally:
        _close(it)
