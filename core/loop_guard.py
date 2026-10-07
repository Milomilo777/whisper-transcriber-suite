"""Stop repetition loops while segments are still being decoded.

Whisper can fall into a loop on long files, above all over music: with
``condition_on_previous_text`` on, the previous window's text is fed back in
as the prompt and the model writes the same short line again and again (one
real run produced "so good" as 30 one-second segments in a row, and decoding
slowed to about 0.12x real time). The hallucination detector runs only after
decoding, and it looks for repeats inside one segment, so it never sees this.

Real speech repeats too (a prayer's "Amen." four times, a chant, a chorus),
so the text alone never decides. A loop also has a decoder's structure: the
copies come back to back. A copy is *tight* to the one before it when the gap
between them, read at the two decimals the timestamps carry, lies in
[``TIGHT_GAP_MIN``, ``TIGHT_GAP_MAX``) seconds and the copy lasts under
``TIGHT_MAX_DURATION`` seconds. Window scores (``avg_logprob``,
``compression_ratio``, ``no_speech_prob``) are shared by every copy in one
30 s decode window, so they are only logged, never used to decide.

:func:`guard_repeats` wraps the lazy segment iterator and counts a *streak*
of consecutive tight identical copies (the first, already yielded copy is the
*anchor* and counts as one):

* a streak of ``hard`` copies is a loop: the guard restarts decoding from the
  copy after the anchor through the caller's ``restart`` callback (the
  transcriber decodes again without the previous text as a prompt, which ends
  the self-feeding loop), once per file; otherwise, or once the restart was
  used, it drops the rest of the streak and keeps the anchor. A real pause or
  a different line ends the dropping;
* a streak that ends with ``limit`` <= n < ``hard`` copies is kept in full and
  every copy after the anchor is marked ``suspect`` ("repeated-line") through
  the stats object, for the consumer to copy into its output rows;
* anything shorter, or anything with real pauses, passes unchanged, delayed by
  at most ``hard - 2`` segments while the guard waits to see the streak end.

With ``ticks=True`` the guard yields a :class:`LoopGuardTick` for every copy it
drops, so a consumer can check cancel and pause and move the progress bar
while a long loop is being eaten.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

DEFAULT_REPEATS = 3
# Tight identical copies in a row (anchor included) that count as a decoder
# loop. Streaks from the configured limit up to one below this are kept and
# marked. PLAUSIBLE until calibrated on a recorded real loop.
HARD_REPEATS = 8
TIGHT_GAP_MIN = -0.2
TIGHT_GAP_MAX = 0.25
TIGHT_MAX_DURATION = 5.0
SUSPECT_REASON = "repeated-line"


@dataclass
class LoopGuardStats:
    restarts: int = 0
    dropped: int = 0
    marked: int = 0
    # id() of yielded segments the consumer should mark; see take_mark().
    marked_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class LoopGuardTick:
    """Stand-in yielded for a dropped copy when ``ticks=True``.

    Carries only the dropped copy's ``end`` on the guarded timeline. It is
    not a segment: consumers check cancel/pause and progress, nothing else.
    """

    end: float
    loop_guard_tick: bool = True


def take_mark(stats: LoopGuardStats, seg: Any) -> str | None:
    """The suspect reason for *seg* if the guard marked it, else None.

    Call once per yielded segment, right after it arrives: the mark is
    removed so a later object reusing the same ``id()`` is never mistaken
    for it. Works for frozen and tuple segments, which refuse ``setattr``.
    """
    try:
        stats.marked_ids.remove(id(seg))
    except KeyError:
        return None
    return SUSPECT_REASON


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


def _time(seg: Any, name: str) -> float | None:
    try:
        value = getattr(seg, name, None)
        return None if value is None else float(value)
    except Exception:  # noqa: BLE001 - a broken field only means "unknown"
        return None


def _is_tight(prev: Any, cur: Any) -> bool:
    """True when *cur* follows *prev* back to back, as a decoder loop does."""
    prev_end = _time(prev, "end")
    start = _time(cur, "start")
    end = _time(cur, "end")
    if prev_end is None or start is None or end is None:
        return False
    # Timestamps carry two decimals; plain float subtraction reads a 0.25 s
    # pause as 0.2499... and would call it tight.
    gap = round(start - prev_end, 2)
    return TIGHT_GAP_MIN <= gap < TIGHT_GAP_MAX and (end - start) < TIGHT_MAX_DURATION


def _scores(seg: Any) -> str:
    """The decode-window scores of *seg* for the log; never raises."""
    parts = []
    for name in ("avg_logprob", "compression_ratio", "no_speech_prob"):
        try:
            value = getattr(seg, name, None)
            if value is not None:
                parts.append(f"{name}={float(value):.2f}")
        except Exception:  # noqa: BLE001 - logging only
            continue
    return ", ".join(parts) or "no window scores"


def _shown(text: str) -> str:
    return text if len(text) <= 40 else text[:37] + "..."


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
    hard: int = HARD_REPEATS,
    restart: Callable[[float], Iterable[Any]] | None = None,
    on_event: Callable[[str], None] | None = None,
    stats: LoopGuardStats | None = None,
    previous_text: str = "",
    ticks: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[Any]:
    """Yield *segments* with decoder loops contained and real repeats kept.

    Segments need ``.text``, ``.start`` and ``.end`` (a segment without times
    is never tight, so it always passes). ``restart(at)`` must return a new
    iterator of segments that starts at *at* seconds on the same timeline; it
    is called at most once, and never once ``cancelled()`` is true (it blocks
    on an ffmpeg slice and a VAD pass). ``hard`` is clamped to at least
    ``limit``; ``limit`` < 2 switches the guard off. ``previous_text`` is the
    line written just before these segments (a resumed run); its times are on
    another timeline, so the first copy here is never tight to it.
    """
    stats = stats if stats is not None else LoopGuardStats()
    if limit < 2:
        yield from segments
        return
    hard = max(int(hard), limit)

    def event(msg: str) -> None:
        logger.warning(msg)
        if on_event is not None:
            on_event(msg)

    def release() -> Iterator[Any]:
        """Yield the held copies unchanged, marked when the streak is long."""
        nonlocal held
        copies, held = held, []
        n = 1 + len(copies)
        if copies and n >= limit:
            try:
                first = _time(copies[0], "start") or 0.0
                last = _time(copies[-1], "start") or 0.0
                gaps = [
                    round((_time(b, "start") or 0.0) - (_time(a, "end") or 0.0), 2)
                    for a, b in zip([anchor, *copies], copies)
                ]
                event(
                    f"Loop guard: kept {n} identical lines "
                    f"{_shown(anchor_text)!r} from {_fmt(first)} to {_fmt(last)} "
                    f"(largest gap {max(gaps):.2f} s; {_scores(copies[0])}); "
                    "marked them for review."
                )
            except Exception:  # noqa: BLE001 - a log line must never stop a run
                logger.debug("loop guard: could not describe a kept run", exc_info=True)
            for seg in copies:
                stats.marked_ids.add(id(seg))
            stats.marked += len(copies)
        yield from copies

    def end_drop() -> None:
        nonlocal drop_count
        if drop_count:
            event(
                f"Loop guard: dropped {drop_count} repeats of "
                f"{_shown(anchor_text)!r} from {_fmt(drop_first)} to {_fmt(drop_last)}."
            )
        drop_count = 0

    it: Iterator[Any] = iter(segments)
    anchor: Any = None  # last yielded segment; None at a resume seam
    anchor_key = repeat_key(previous_text)
    anchor_text = str(previous_text or "").strip()
    prev_copy: Any = None  # the copy tightness is measured against
    held: list[Any] = []
    dropping = False
    drop_count = 0
    drop_first = drop_last = 0.0
    can_restart = restart is not None
    try:
        while True:
            try:
                seg = next(it)
            except StopIteration:
                break
            text = str(getattr(seg, "text", "") or "").strip()
            key = repeat_key(text)
            tight = (
                bool(key) and key == anchor_key and prev_copy is not None
                and _is_tight(prev_copy, seg)
            )
            if tight:
                prev_copy = seg
                if dropping:
                    stats.dropped += 1
                    drop_count += 1
                    drop_last = _time(seg, "start") or drop_last
                    if ticks:
                        yield LoopGuardTick(_time(seg, "end") or 0.0)
                    continue
                if 1 + len(held) + 1 < hard:
                    held.append(seg)
                    continue
                # The streak (anchor included) reached `hard`: a decoder loop.
                at = _time(held[0] if held else seg, "start") or 0.0
                if (
                    can_restart and restart is not None
                    and not (cancelled is not None and cancelled())
                ):
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
                            f"Loop guard: {hard} identical lines "
                            f"{_shown(text)!r} back to back at {_fmt(at)}; "
                            "decoding again from there without the previous "
                            "text as a prompt."
                        )
                        _close(it)
                        it = iter(new_segments)
                        held = []
                        stats.restarts += 1
                        # Restarted copies are compared with the anchor.
                        prev_copy = anchor
                        continue
                dropped_now = [*held, seg]
                held = []
                stats.dropped += len(dropped_now)
                dropping = True
                drop_count = len(dropped_now)
                drop_first = at
                drop_last = _time(seg, "start") or at
                if ticks:
                    for copy in dropped_now:
                        yield LoopGuardTick(_time(copy, "end") or 0.0)
                continue
            if dropping:
                end_drop()
                dropping = False
            if held:
                yield from release()
            yield seg
            anchor = seg
            anchor_key = key
            anchor_text = text
            prev_copy = seg
        if dropping:
            end_drop()
        if held:
            yield from release()
    finally:
        _close(it)
