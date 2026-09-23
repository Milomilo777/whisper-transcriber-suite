"""Which Whisper model the Live tab uses.

The Live tab transcribes a few seconds of audio at a time, so the model
must finish each chunk faster than the chunk lasts or text falls further
and further behind. Whisper's encoder always processes a 30 s window, so a
short chunk costs almost as much as a long one, and on a CPU the big
models simply cannot keep up. Measured on a 4-core/8-thread i7-6700
(int8, language named, one 8 s chunk of real speech):

    large-v3        ~19 s     large-v3-turbo  ~17 s
    medium          ~12 s     small           ~4 s      base   ~1.6 s

The default is ``tiny`` (owner request, 2026-09-23): it keeps up on any
machine and downloads in seconds. "auto" keeps the main model on a GPU
and picks a small model sized to the machine on a CPU. The user can
pick any model from the catalog; the choice is stored as ``live_model``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

#: ``live_model`` values that are not catalog slugs.
LIVE_AUTO = "auto"
LIVE_MAIN = "main"

#: ``live_model`` when the config has none.
LIVE_DEFAULT = "tiny"

#: Environment variable the Live tab sets on its worker subprocess.
LIVE_MODEL_ENV = "WHISPER_LIVE_MODEL"


def recommended_cpu_slug(language: str | None, cpu_count: int | None = None) -> str:
    """Fastest model that still transcribes ``language`` usefully on a CPU.

    English has dedicated ``.en`` models, more accurate than multilingual
    ones of the same size. For every other language ``base`` is too weak
    to be worth showing, so ``small`` is the floor.
    """
    threads = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
    if (language or "").lower() == "en":
        return "small.en" if threads >= 8 else "base.en"
    return "small"


def resolve_live_slug(
    config: dict[str, Any], language: str | None, device: str
) -> str | None:
    """Catalog slug the live worker should load, or None for the main model."""
    choice = str(config.get("live_model") or LIVE_DEFAULT).strip()
    if choice == LIVE_MAIN:
        return None
    if choice == LIVE_AUTO:
        if device and device != "cpu":
            return None
        return recommended_cpu_slug(language)
    return choice


def live_model_config(config: dict[str, Any], slug: str) -> dict[str, Any] | None:
    """A copy of ``config`` pointed at ``slug`` (for ensure_model / the worker).

    Returns None when ``slug`` is not in the merged model catalog.
    """
    from .hub import default_hub_folder, model_folder_for
    from .model_manager import catalog_resolve_entry

    entry = catalog_resolve_entry(config, slug)
    if entry is None:
        return None
    hub = str(config.get("hub_folder") or "").strip() or str(default_hub_folder())
    out = dict(config)
    out["model"] = entry
    out["whisper_model"] = slug
    out["model_path"] = str(model_folder_for(hub, entry["name"]))
    out["transcribe_backend"] = "faster_whisper"
    return out


def is_downloaded(model_config: dict[str, Any]) -> bool:
    return (Path(str(model_config.get("model_path") or "")) / "model.bin").exists()


def apply_env_override(config: dict[str, Any]) -> str | None:
    """Worker side: repoint ``config`` in place at the model named in the env.

    Only the live worker's environment carries :data:`LIVE_MODEL_ENV`.
    Returns the slug applied, or None when unset / unknown / not on disk
    (the worker then loads its normal model instead of failing).
    """
    slug = os.environ.get(LIVE_MODEL_ENV, "").strip()
    if not slug:
        return None
    patched = live_model_config(config, slug)
    if patched is None or not is_downloaded(patched):
        return None
    for key in ("model", "whisper_model", "model_path", "transcribe_backend"):
        config[key] = patched[key]
    return slug
