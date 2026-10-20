"""Rescue speech that Whisper dropped: collapsed windows and silent-looking gaps (ADR 0017).

Whisper sometimes ends a 30-second window after a couple of words: the segment then spans the whole
window ("0:00 -> 0:30  two words") and the rest of its speech is gone. Measured on a real Persian
phone call with large-v3 on a CPU: the same two words in every setting tried (VAD on or off, previous
text as a prompt or not, one temperature). Reading that stretch again in pieces of at most 15 seconds,
cut at the quietest points, gave 47 words; 10-second pieces and very short pieces invited invented
text ("music" repeated), so pieces are short but not tiny.

This module finds the suspect stretches in a finished transcript (a long segment with almost no
words, or a long gap between segments), checks that there is speech in them, reads them again
through a caller-supplied ``transcribe_piece`` function, and replaces the stretch only when the new
text is clearly longer and is not a repetition loop. Everything outside a replaced stretch stays
exactly as it was. The detection and the splice are pure (no model, no audio) and unit-tested; the
engine wiring lives in ``core.transcriber``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .loop_guard import repeat_key
from .text_metrics import count_words
from .writers.base import coerce_seconds

SAMPLE_RATE = 16000
#: A segment at least this long with fewer than :data:`MAX_UNITS_PER_S` words per second is suspect.
MIN_COLLAPSED_S = 20.0
MAX_UNITS_PER_S = 0.25
#: A gap between segments (or before the first / after the last) at least this long is suspect.
MIN_GAP_S = 15.0
#: The stretch is read again only when Silero VAD hears at least this much speech in it.
MIN_SPEECH_S = 8.0
#: Pieces of the stretch: speech runs up to this long, grouped up to the same length.
PIECE_MAX_S = 15.0
#: Pieces shorter than this are joined to a neighbour (very short pieces invite invented text)
#: when the pause between them is at most MAX_JOIN_PAUSE_S; a lone piece under MIN_PIECE_KEEP_S is dropped.
PIECE_MIN_S = 3.0
MAX_JOIN_PAUSE_S = 2.0
MIN_PIECE_KEEP_S = 1.0
#: A stretch longer than this is not read again (a long gap is music or silence far more often).
MAX_SPAN_S = 600.0
#: A gap is filled only with at least this many words per second of heard speech.
MIN_GAP_UNITS_PER_SPEECH_S = 0.3
#: A rescue must add at least this many words and at least double the stretch's words.
MIN_GAINED_UNITS = 5
#: Upper bounds per file, so a long noisy recording cannot turn into a second full pass.
MAX_SPANS = 20
MAX_RESCUED_FRACTION = 0.3
#: ... but a short file may always have this much read again (one lost window of a phone call).
MIN_BUDGET_S = 120.0


@dataclass(frozen=True)
class Span:
    """A suspect stretch ``[start, end)`` seconds; ``first``/``last`` index the segments it replaces
    (``first == last`` for a gap: nothing is replaced, the new segments are inserted at ``first``)."""

    start: float
    end: float
    first: int
    last: int
    kind: str  # "collapsed" or "gap"


@dataclass
class Report:
    """What the rescue did, for the log."""

    found: int = 0
    rescued: list[tuple[float, float, int, int]] = field(default_factory=list)  # start, end, old, new words
    kept: list[tuple[float, float, str]] = field(default_factory=list)  # start, end, why the old text stayed

    def lines(self) -> list[str]:
        out = []
        for start, end, old, new in self.rescued:
            out.append(f"Read {_fmt(start)}-{_fmt(end)} again in shorter pieces: {old} -> {new} words")
        for start, end, why in self.kept:
            out.append(f"WARN: {_fmt(start)}-{_fmt(end)} may be missing speech ({why}); check it by ear")
        return out


def _fmt(seconds: float) -> str:
    m, s = divmod(int(max(0.0, seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _units(segments: Iterable[dict[str, Any]]) -> int:
    return sum(count_words(str(s.get("text") or "")) for s in segments)


def find_suspect_spans(segments: list[dict[str, Any]], duration: float) -> list[Span]:
    """The collapsed segments and long gaps of a finished transcript, in time order.

    ``segments`` are the transcript's dicts (``start``/``end``/``text``), sorted by start; a segment
    with an unusable time is skipped. ``duration`` is the media length (0 = unknown: no tail gap).
    """
    spans: list[Span] = []
    previous_end = 0.0
    for i, seg in enumerate(segments):
        start = coerce_seconds(seg.get("start"), float("nan"))
        end = coerce_seconds(seg.get("end"), float("nan"))
        if not (math.isfinite(start) and math.isfinite(end) and 0.0 <= start <= end):
            continue
        if start - previous_end >= MIN_GAP_S:
            spans.append(Span(previous_end, start, i, i, "gap"))
        length = end - start
        if length >= MIN_COLLAPSED_S and count_words(str(seg.get("text") or "")) < length * MAX_UNITS_PER_S:
            spans.append(Span(start, end, i, i + 1, "collapsed"))
        previous_end = max(previous_end, end)
    if duration > 0 and duration - previous_end >= MIN_GAP_S:
        spans.append(Span(previous_end, duration, len(segments), len(segments), "gap"))
    return spans


def group_pieces(speech: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Join speech runs (seconds, in order) into pieces of at most :data:`PIECE_MAX_S`, none shorter
    than :data:`PIECE_MIN_S` unless it is the only one."""
    runs: list[tuple[float, float]] = []
    for start, end in speech:
        if end <= start:
            continue
        # A run longer than a piece (no pause found in it) is cut into equal parts.
        parts = max(1, math.ceil((end - start) / PIECE_MAX_S - 1e-9))
        step = (end - start) / parts
        runs.extend((start + k * step, start + (k + 1) * step) for k in range(parts))
    pieces: list[list[float]] = []
    for start, end in runs:
        if pieces and end - pieces[-1][0] <= PIECE_MAX_S:
            pieces[-1][1] = end
        else:
            pieces.append([start, end])
    # A short piece joins a neighbour only when both stay within PIECE_MAX_S and the pause
    # between them is short; one that cannot join is kept if it holds a second of speech or more.
    merged: list[list[float]] = []
    for piece in pieces:
        if merged:
            last = merged[-1]
            short = piece[1] - piece[0] < PIECE_MIN_S or last[1] - last[0] < PIECE_MIN_S
            if short and piece[1] - last[0] <= PIECE_MAX_S and piece[0] - last[1] <= MAX_JOIN_PAUSE_S:
                last[1] = piece[1]
                continue
        merged.append(piece)
    return [(a, b) for a, b in merged if b - a >= MIN_PIECE_KEEP_S or len(merged) == 1]


def is_loop(segments: list[dict[str, Any]]) -> bool:
    """True when the new text is mostly one line said again and again (an invented-text loop)."""
    keys = [repeat_key(str(s.get("text") or "")) for s in segments]
    keys = [k for k in keys if k]
    if len(keys) < 3:
        return False
    most = max(keys.count(k) for k in set(keys))
    return most >= 3 and most * 2 >= len(keys)


def accept(old: list[dict[str, Any]], new: list[dict[str, Any]], *, kind: str = "collapsed",
           speech_s: float = 0.0) -> tuple[bool, str]:
    """Whether ``new`` should replace ``old`` for a stretch, and why not when it should not.

    A gap (nothing there before) also needs :data:`MIN_GAP_UNITS_PER_SPEECH_S` words per second
    of heard speech: a few words over a long noisy stretch are more likely invented than lost.
    """
    old_units, new_units = _units(old), _units(new)
    if is_loop(new):
        return False, "the second reading repeats itself"
    if new_units < MIN_GAINED_UNITS or new_units < 2 * max(1, old_units):
        return False, f"the second reading found only {new_units} words"
    if kind == "gap" and new_units < MIN_GAP_UNITS_PER_SPEECH_S * speech_s:
        return False, f"the second reading found only {new_units} words in {speech_s:.0f} s of sound"
    return True, ""


def splice(segments: list[dict[str, Any]], span: Span, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``segments`` with ``segments[span.first:span.last]`` replaced by ``new`` (kept in time order)."""
    return segments[: span.first] + sorted(new, key=lambda s: float(s.get("start", 0.0))) + segments[span.last:]


def rescue(
    segments: list[dict[str, Any]],
    duration: float,
    speech_in: Callable[[float, float], list[tuple[float, float]]],
    transcribe_piece: Callable[[float, float], list[dict[str, Any]]],
    cancelled: Callable[[], bool] = lambda: False,
    before_piece: Callable[[], None] = lambda: None,
) -> tuple[list[dict[str, Any]], Report]:
    """Read the suspect stretches again; returns the new segment list and a report.

    ``speech_in(start, end)`` returns the speech runs inside a stretch (absolute seconds);
    ``transcribe_piece(start, end)`` returns segment dicts on the file's timeline. Spans are
    processed from the last to the first so earlier indexes stay valid. ``before_piece`` runs
    before each piece is read (the caller waits there while the job is paused).
    """
    report = Report()
    spans = find_suspect_spans(segments, duration)
    report.found = len(spans)
    budget = max(MAX_RESCUED_FRACTION * duration, MIN_BUDGET_S) if duration > 0 else float("inf")
    used = 0.0
    # Pick in time order (only stretches with speech count against the budget), then read them
    # from the last to the first so the earlier segment indexes stay valid while splicing.
    chosen: list[tuple[Span, list[tuple[float, float]]]] = []
    for span in spans[:MAX_SPANS]:
        if cancelled():
            break
        length = span.end - span.start
        # Checked before any audio is decoded: a long gap is not read into memory.
        if length > MAX_SPAN_S or used + length > budget:
            if span.kind == "collapsed":
                report.kept.append((span.start, span.end, "too long to read again here"))
            continue
        speech = speech_in(span.start, span.end)
        if sum(b - a for a, b in speech) < MIN_SPEECH_S:
            continue  # music, silence or noise: nothing was lost
        used += length
        chosen.append((span, speech))
    result = list(segments)
    for span, speech in reversed(chosen):
        if cancelled():
            break
        new: list[dict[str, Any]] = []
        for start, end in group_pieces(speech):
            before_piece()
            if cancelled():
                break
            new.extend(s for s in transcribe_piece(start, end) if str(s.get("text") or "").strip())
        old = result[span.first:span.last]
        ok, why = accept(old, new, kind=span.kind, speech_s=sum(b - a for a, b in speech))
        if ok and span.kind == "gap":
            for s in new:  # nothing was there before: flag for review in the viewer
                s.setdefault("suspect", True)
                s.setdefault("suspect_reason", "read again: Whisper had skipped this stretch")
        if ok:
            report.rescued.append((span.start, span.end, _units(old), _units(new)))
            result = splice(result, span, new)
        else:
            report.kept.append((span.start, span.end, why))
    report.rescued.reverse()
    report.kept.reverse()
    return result, report
