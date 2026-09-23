"""Heuristic hallucination detection for Whisper output.

Three independent signals; any one is enough to flag a segment:

  * Bag-of-Hallucinations (BoH) — a curated list of phrases Whisper
    emits during silence or low-SNR audio (e.g. ``"Thanks for watching"``
    YouTube boilerplate that leaked in from the training set, ``"[Music]"``
    annotations, lone ``"."`` / ``"..."`` punctuation). Reference:
    arXiv 2501.11378.
  * Repetition — a token or short n-gram that repeats N+ times in a
    row inside a single segment (``"the the the the"``,
    ``"Thanks Thanks Thanks!"``). The classic Whisper long-silence
    loop pattern.
  * VAD disagreement — a segment whose ``[start, end]`` doesn't overlap
    any speech interval returned by the VAD pass. Caller-supplied;
    skipped when ``vad_segments`` is None.

When :func:`annotate_segments` flags a segment, it sets
``seg["suspect"] = True`` and ``seg["suspect_reason"] = "<which>"``
so writers + the viewer can surface the warning without re-running
detection.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Lower-case + collapse internal whitespace + strip ends."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


_BAG_OF_HALLUCINATIONS: tuple[str, ...] = (
    "thanks for watching",
    "thanks for watching!",
    "thanks for watching.",
    "thank you for watching",
    "thank you for watching.",
    "thank you for watching!",
    "thank you very much",
    "thank you so much",
    "thank you",
    "subscribe to my channel",
    "subscribe to the channel",
    "please subscribe",
    "like and subscribe",
    "don't forget to subscribe",
    "subtitles by",
    "subtitles by the amara.org community",
    "transcription by",
    "translation by",
    "music",
    "[music]",
    "(music)",
    "♪",
    "♪♪",
    "♪♪♪",
    "(silence)",
    "[silence]",
    "you",
    ".",
    "..",
    "...",
    "....",
    "bye",
    "bye bye",
    "okay",
    "ok",
    "hmm",
    "uh",
    "um",
)


_BOH_NORMALIZED: frozenset[str] = frozenset(
    _normalize(p) for p in _BAG_OF_HALLUCINATIONS
)


def detect_boh(text: str) -> bool:
    """Return True when the trimmed segment text matches a known
    hallucination phrase verbatim.

    Match is whole-segment (after :func:`_normalize`) so a legitimate
    "thanks for watching the video tonight" inside a longer sentence
    is not flagged.
    """
    return _normalize(text) in _BOH_NORMALIZED


_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)


def detect_repetition(text: str, *, min_repeats: int = 3) -> bool:
    """True when one token or short n-gram repeats ``min_repeats`` times in a row.

    Scans 1-/2-/3-gram windows. Longer n-grams are skipped because the
    false-positive rate grows fast (a song chorus or a list reading
    like "yes yes yes" can look like a hallucination otherwise).
    """
    if not text or min_repeats < 2:
        return False
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < min_repeats:
        return False

    streak = 1
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            streak += 1
            if streak >= min_repeats:
                return True
        else:
            streak = 1

    for n in (2, 3):
        if len(tokens) < n * min_repeats:
            continue
        for i in range(len(tokens) - n * min_repeats + 1):
            window = tokens[i:i + n]
            ok = True
            for r in range(1, min_repeats):
                if tokens[i + n * r:i + n * (r + 1)] != window:
                    ok = False
                    break
            if ok:
                return True
    return False


def detect_vad_disagreement(
    seg: dict[str, Any],
    vad_segments: Iterable[tuple[float, float]] | None,
) -> bool:
    """True when the segment lies entirely in a VAD-silence gap.

    ``vad_segments`` is the list of ``(start, end)`` speech intervals
    the VAD pass returned. A whisper-emitted segment that does not
    overlap any of them — yet still produced text — is a strong
    hallucination signature.

    Returns False when ``vad_segments`` is ``None`` so this signal
    becomes a no-op when the caller hasn't captured the VAD output.
    """
    if not vad_segments:
        return False
    try:
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s))
    except (TypeError, ValueError, OverflowError):
        # A malformed backend payload (None / "" / unparseable timestamp)
        # gives no evidence of disagreement; one bad segment must not
        # abort annotation of all the others.
        return False
    if not (math.isfinite(s) and math.isfinite(e)):
        # NaN / +-inf compare false against every interval, which would
        # turn a garbage timestamp into a "disagreement"; only a finite
        # interval can establish one.
        return False
    for vs, ve in vad_segments:
        if e >= vs and s <= ve:
            return False
    return True


def annotate_segments(
    segments: list[dict[str, Any]],
    *,
    vad_segments: Iterable[tuple[float, float]] | None = None,
) -> int:
    """Tag each suspect segment with ``suspect=True`` + ``suspect_reason``.

    Already-flagged segments are left alone so a downstream re-run is
    idempotent. Returns the number of newly flagged segments.
    """
    flagged = 0
    vad_list = list(vad_segments) if vad_segments else None
    for seg in segments:
        if seg.get("suspect"):
            continue
        raw_text = seg.get("text")
        if not isinstance(raw_text, str):
            # Non-string text (None, a number from a malformed
            # backend payload) carries no words to judge -- skip it
            # rather than crashing on .strip() below.
            continue
        text = raw_text.strip()
        if not text:
            continue
        reason: str | None = None
        if detect_boh(text):
            reason = "bag-of-hallucinations"
        elif detect_repetition(text):
            reason = "repetition"
        elif detect_vad_disagreement(seg, vad_list):
            reason = "vad-disagreement"
        if reason:
            seg["suspect"] = True
            seg["suspect_reason"] = reason
            flagged += 1
    return flagged
