"""Aggregate raw language shares and apply a weighted prior, without app or model imports."""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass


# Downweight unfamiliar languages while preserving strong evidence for a new language.
# Accepted trade-off: a first-time language with substantial English content may be
# overridden (ja=0.75/en=0.25 chooses en); the existing override log makes this visible.
IMPLAUSIBLE_WEIGHT = 0.15


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    probability: float
    reason: str
    window_count: int
    shares: dict[str, float]


def sample_windows(duration: float) -> list[tuple[float, float]]:
    """Bounded windows centered at 10/30/50/70/90 percent; short audio starts at zero."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Audio duration must be finite and positive")
    if duration < 150.0:
        return [(0.0, min(30.0, duration))]
    return [(min(max(0.0, duration * p - 15.0), duration - 30.0), 30.0)
            for p in (0.1, 0.3, 0.5, 0.7, 0.9)]


def choose_language(
    windows: Iterable[Mapping[str, float]], plausible: Iterable[str],
) -> LanguageDecision:
    """Choose by prior-weighted shares, reporting the chosen language's raw share."""
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
    chosen = min(shares, key=lambda code: (
        -shares[code] * (1.0 if code in plausible_set else IMPLAUSIBLE_WEIGHT), code))
    reason = "prior_override" if chosen != winner else "winner"
    return LanguageDecision(chosen, shares[chosen], reason, count, shares)


def detect_with_prior(
    duration: float,
    plausible: Iterable[str],
    detect_window: Callable[[float, float], Mapping[str, float]],
) -> LanguageDecision:
    """Apply the policy to an injected detector; I/O and failure recovery belong to the caller."""
    return choose_language((detect_window(start, length)
                            for start, length in sample_windows(duration)), plausible)
