"""The Transcribe tab's Accuracy levels: Fast, Balanced and Best as Whisper model slugs.

One level is a model pick for the spoken language (``core.language_defaults``) sized to this
computer's memory (``core.hardware.fit_model_to_ram``):

* ``fast``: the language's measured "fast" pick (Small, about 0.5 GB);
* ``best``: the language's measured "best" pick (Large v3, or Large v3 Turbo where it measured
  better);
* ``balanced``: Large v3 Turbo. Where Best already is Turbo (Arabic, Chinese, Russian,
  Spanish, or a computer too small for Large v3) the two levels name the same model: Medium
  would be both slower and less accurate than Turbo, so it is no level at all.

Pure functions, no Tk and no config writes: the tab maps a level to a slug and picks it the
way the model picker does, and shows the level whose slug the saved model equals. A saved
model that matches no level (an English-only twin, a model trained for one language, a
catalog model picked in Advanced settings) is "Custom" and is never rewritten.
"""
from __future__ import annotations

from .hardware import fit_model_to_ram
from .language_defaults import recommended_model

LEVELS: tuple[str, ...] = ("fast", "balanced", "best")

BALANCED_MODEL = "large-v3-turbo"


def models_by_level(language: str | None, ram_gb: float = 0.0) -> dict[str, str]:
    """``{level: slug}`` for ``language`` (a Whisper code, ``"auto"`` or empty) on a
    computer with ``ram_gb`` of memory (0 = unknown, no cap)."""
    fast = fit_model_to_ram(recommended_model(language, "fast"), ram_gb)
    best = fit_model_to_ram(recommended_model(language, "best"), ram_gb)
    balanced = fit_model_to_ram(BALANCED_MODEL, ram_gb)
    return {"fast": fast, "balanced": balanced, "best": best}


def model_for_level(language: str | None, level: str, ram_gb: float = 0.0) -> str:
    """The slug ``level`` stands for; ``ValueError`` for a level outside :data:`LEVELS`."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, not {level!r}")
    return models_by_level(language, ram_gb)[level]


def level_for_model(slug: str, language: str | None, ram_gb: float = 0.0) -> str | None:
    """The level whose model is ``slug`` (the first in :data:`LEVELS` when two levels share
    a model), or ``None`` when no level has it (a "Custom" pick)."""
    picks = models_by_level(language, ram_gb)
    return next((level for level in LEVELS if picks[level] == slug), None)
