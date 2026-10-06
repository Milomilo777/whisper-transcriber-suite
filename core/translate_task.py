"""Whisper's own "translate to English" task: which runs support it, and naming.

Whisper models can output English text straight from non-English speech
(``task="translate"``), in one pass and without any extra AI model. Only some
engines and models can do it, so the Transcribe tab and the transcriber both
ask :func:`unsupported_reason` before using it.
"""
from __future__ import annotations

import re
from typing import Any

TASK_TRANSCRIBE = "transcribe"
TASK_TRANSLATE = "translate"
VALID_TASKS = (TASK_TRANSCRIBE, TASK_TRANSLATE)

# Output files of a translate run: ``name.en-translated.srt`` (next to the
# source, as for a normal run). The suffix keeps them apart from a normal
# transcript of the same file.
TRANSLATED_SUFFIX = ".en-translated"

# Language tag of the output of a translate run.
TRANSLATED_LANGUAGE = "en"

CONFIG_KEY = "translate_to_english"


def normalise_task(value: Any) -> str:
    """Return ``"translate"`` or ``"transcribe"``; anything else is transcribe."""
    return TASK_TRANSLATE if str(value or "").strip().lower() == TASK_TRANSLATE else TASK_TRANSCRIBE


def _model_text(config: dict[str, Any]) -> str:
    model = config.get("model")
    parts: list[str] = [str(config.get("whisper_model") or "")]
    if isinstance(model, dict):
        parts.append(str(model.get("name") or ""))
        parts.append(str(model.get("hf_repo") or ""))
    return " ".join(parts).lower()


def unsupported_reason(config: dict[str, Any]) -> str:
    """One-line reason why translate cannot run with this setup, or "" when it can.

    * Only the faster-whisper engine passes the task to the model; the other
      engines (whisper.cpp wrapper, NVIDIA, cloud) have no such option here.
    * large-v3-turbo: the OpenAI Whisper README says "The `turbo` model is not
      trained for translation tasks" and that it "will return the original
      language even if `--task translate` is specified"
      (https://github.com/openai/whisper#available-models-and-languages).
    * English-only models (``.en``, distil-*) have nothing to translate into.
    """
    backend = str(config.get("transcribe_backend") or "faster_whisper").strip().lower()
    if backend != "faster_whisper":
        return "Only the Faster-Whisper engine can translate to English."
    text = _model_text(config)
    if "turbo" in text:
        return (
            "The turbo model was not trained for translation; pick another "
            "model (for example Small, Medium or Large-v3)."
        )
    if re.search(r"\.en(?![a-z0-9])", text) or "distil" in text:
        return "English-only models cannot translate; pick a multilingual model."
    return ""


def translated_base(base: str) -> str:
    """Insert the translate suffix into an output base path (``dir/name`` -> ``dir/name.en-translated``)."""
    return base + TRANSLATED_SUFFIX
