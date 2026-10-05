"""Recommended Whisper model per spoken language, measured by the multilingual benchmark.

Source: ``docs/evaluations/benchmark-v1/`` (Google FLEURS read speech, five utterances per
language, CPU int8). ``"best"`` is the model with the lowest measured error rate (a tie goes
to the faster model); ``"fast"`` is the most accurate model with a download of at most
0.5 GB (tiny, base, small). ``tests/test_benchmark_results.py`` recomputes both picks from
the published CSV, so this table cannot drift from it. A language that was not measured
keeps the app's default model.
"""
from __future__ import annotations

from .model_manager import DEFAULT_MODEL_SLUG

MODES = ("fast", "best")

MODEL_BY_LANGUAGE: dict[str, dict[str, str]] = {
    "fa": {"fast": "small", "best": "large-v3"},
    "ar": {"fast": "small", "best": "large-v3-turbo"},
    "zh": {"fast": "small", "best": "large-v3-turbo"},
    "ja": {"fast": "small", "best": "large-v3"},
    "ru": {"fast": "small", "best": "large-v3-turbo"},
    "hi": {"fast": "small", "best": "large-v3"},
    "es": {"fast": "small", "best": "large-v3-turbo"},
    "tr": {"fast": "small", "best": "large-v3"},
}


def recommended_model(language: str | None, mode: str = "best") -> str:
    """Registry slug to suggest for ``language`` (a Whisper code such as ``"fa"``).

    ``mode`` is ``"fast"`` or ``"best"``. A language that is empty, ``"auto"`` or not in
    the table gets :data:`~core.model_manager.DEFAULT_MODEL_SLUG` in both modes.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be 'fast' or 'best', not {mode!r}")
    row = MODEL_BY_LANGUAGE.get((language or "").strip().lower())
    return row[mode] if row else DEFAULT_MODEL_SLUG
