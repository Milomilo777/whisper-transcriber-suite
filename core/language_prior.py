"""Aggregate language evidence and verify ambiguous choices through injected callables."""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol


VERIFY_MARGIN = 0.15
PREFLIGHT_SECONDS = 180.0


class PreflightCancelled(Exception):
    """The existing task cancellation flag was set during preflight."""


class WindowReadError(Exception):
    """An unreadable audio window may be skipped; detector failures may not."""


class ScoredSegment(Protocol):
    tokens: list[int]
    avg_logprob: float


@dataclass(frozen=True)
class LanguageDecision:
    language: str | None
    probability: float
    reason: str
    window_count: int
    shares: dict[str, float]
    scores: dict[str, float] = field(default_factory=dict)
    error: Exception | None = field(default=None, compare=False)


def sample_windows(duration: float) -> list[tuple[float, float]]:
    """One window below 60 s, three below 150 s, otherwise five centered windows."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Audio duration must be finite and positive")
    if duration < 60.0:
        return [(0.0, min(30.0, duration))]
    positions = (0.1, 0.5, 0.9) if duration < 150.0 else (0.1, 0.3, 0.5, 0.7, 0.9)
    return [(min(max(0.0, duration * p - 15.0), duration - 30.0), 30.0)
            for p in positions]


def choose_language(
    windows: Iterable[Mapping[str, float]], plausible: Iterable[str],
    verify: Callable[[str], float] | None = None,
) -> LanguageDecision:
    """Use raw shares for clear cases; require independent decode evidence otherwise."""
    mass: dict[str, float] = {}
    count = 0
    for window in windows:
        if not window:
            raise ValueError("Detector returned no language probabilities")
        for language, probability in sorted(window.items()):
            if not language or not math.isfinite(probability) or probability < 0:
                raise ValueError("Invalid language probability")
            mass[language] = mass.get(language, 0.0) + probability
        count += 1
    total = math.fsum(mass.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Detector returned no positive language mass")
    # Alphabetical tie breaking is independent of mapping/set iteration order.
    ranked = sorted(mass, key=lambda code: (-mass[code], code))
    shares = {code: mass[code] / total for code in ranked}
    winner = ranked[0]
    plausible_set = set(plausible) | {"en"}
    candidate = next((code for code in ranked if code in plausible_set), None)
    if winner in plausible_set or candidate is None or shares[candidate] < 0.05:
        return LanguageDecision(winner, shares[winner], "winner", count, shares)
    scores: dict[str, float] = {}
    if verify is None:
        return LanguageDecision(None, 0.0, "inconclusive", count, shares)
    try:
        for language in (winner, candidate):
            score = verify(language)
            if not math.isfinite(score):
                raise ValueError("Verification returned a non-finite score")
            scores[language] = score
    except PreflightCancelled:
        raise
    except Exception as exc:
        return LanguageDecision(None, 0.0, "fallback", count, shares, scores, exc)
    if scores[candidate] - scores[winner] >= VERIFY_MARGIN:
        return LanguageDecision(candidate, shares[candidate], "verified_override", count, shares, scores)
    if scores[winner] - scores[candidate] >= VERIFY_MARGIN:
        return LanguageDecision(winner, shares[winner], "verified_winner", count, shares, scores)
    return LanguageDecision(None, 0.0, "inconclusive", count, shares, scores)


def detect_with_prior(
    duration: float,
    plausible: Iterable[str],
    detect_window: Callable[[float, float], Mapping[str, float]],
    decode_window: Callable[[float, float, str], Iterable[ScoredSegment]],
    *,
    check: Callable[[], None] = lambda: None,
    on_skip: Callable[[Exception], None] = lambda exc: None,
) -> LanguageDecision:
    """Sample once, then perform at most four forced decodes of valid cached windows."""
    valid: list[tuple[float, float]] = []
    probabilities: list[Mapping[str, float]] = []
    for start, length in sample_windows(duration):
        check()
        try:
            row = detect_window(start, length)
        except WindowReadError as exc:
            on_skip(exc)
            check()
            continue
        check()
        valid.append((start, length))
        probabilities.append(row)
    if len(valid) < (1 if duration < 150.0 else 3):
        return LanguageDecision(None, 0.0, "fallback", len(valid), {},
                                error=ValueError("Too few valid language windows"))

    # Prefer the 30% and 70% samples; if either failed, use the nearest distinct
    # valid window. Short inputs may have only one valid sample.
    remaining = list(valid)
    verification_windows: list[tuple[float, float]] = []
    for position in (0.3, 0.7):
        if remaining:
            window = min(remaining, key=lambda w: (abs(w[0] + w[1] / 2 - duration * position), w))
            verification_windows.append(window)
            remaining.remove(window)

    def verify(language: str) -> float:
        weighted = 0.0
        token_count = 0
        for start, length in verification_windows:
            check()
            segments = decode_window(start, length, language)
            check()
            for segment in segments:
                check()
                count = len(segment.tokens)
                score = float(segment.avg_logprob)
                if not math.isfinite(score):
                    raise ValueError("Segment has a non-finite avg_logprob")
                weighted += count * score
                token_count += count
            check()
        if not token_count:
            raise ValueError("Verification returned no scored tokens")
        return weighted / token_count

    decision = choose_language(probabilities, plausible, verify)
    check()
    return decision
