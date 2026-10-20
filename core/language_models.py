"""Models trained for one spoken language, suggested on the Transcribe tab (ADR 0015).

Each row is one model per language that, by its publisher's own published comparison, beats
stock Whisper (or the earlier best open model) for that language, has a permissive (or
OpenMDW) licence, needs no Hugging Face login, and loads as published: CTranslate2 files at
the repo root for the ``faster_whisper`` engine, or a transformers model for the local
``nvidia_asr`` engine. ``claim`` repeats the publisher's figures on the publisher's test sets;
this project has not re-measured them, and the UI says so.

Choosing a row never happens on its own: the Transcribe tab offers it, and "Use it" calls
:func:`apply_language_model`, which also remembers the engine and model it replaced so
:func:`restore_previous` can switch back.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_manager import DEFAULT_MODEL_SLUG

ENGINE_WHISPER = "faster_whisper"
ENGINE_TRANSFORMERS = "nvidia_asr"

#: Config key holding the engine/model in use before "Use it" switched to a language model.
PREVIOUS_KEY = "language_model_previous"


@dataclass(frozen=True)
class LanguageModel:
    language: str  # Whisper language code
    name: str      # short display name
    engine: str    # ENGINE_WHISPER (``model`` = registry slug) or ENGINE_TRANSFORMERS (``model`` = HF repo id)
    model: str
    size_gb: float
    licence: str
    claim: str     # the publisher's own comparison, one sentence
    source: str    # where the claim is published


LANGUAGE_MODELS: dict[str, LanguageModel] = {
    "fa": LanguageModel(
        language="fa",
        name="Nemotron ASR Persian",
        engine=ENGINE_TRANSFORMERS,
        model="mehdi-hf/nemotron-asr-streaming-farsi",
        size_gb=2.5,
        licence="OpenMDW-1.1",
        claim=("8.8% word errors on FLEURS Persian against 24.2% for NVIDIA's earlier Persian model, "
               "and 26.0% against 54.4% on conversational speech (films, YouTube)"),
        source="https://huggingface.co/mehdi-hf/nemotron-asr-streaming-farsi",
    ),
    "zh": LanguageModel(
        language="zh",
        name="Belle Whisper Large v3 Turbo Chinese",
        engine=ENGINE_WHISPER,
        model="belle-large-v3-turbo-zh",
        size_gb=1.62,
        licence="Apache-2.0",
        claim="3.1% character errors on AISHELL-1 against 8.1% for Whisper Large v3",
        source="https://huggingface.co/BELLE-2/Belle-whisper-large-v3-turbo-zh",
    ),
    "ja": LanguageModel(
        language="ja",
        name="Kotoba-Whisper v2.0",
        engine=ENGINE_WHISPER,
        model="kotoba-whisper-v2.0",
        size_gb=1.52,
        licence="MIT",
        claim=("11.6% character errors on ReazonSpeech against 14.9% for Whisper Large v3, "
               "about 6x faster"),
        source="https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0",
    ),
    "de": LanguageModel(
        language="de",
        name="Whisper Large v3 Turbo German (primeline)",
        engine=ENGINE_WHISPER,
        model="primeline-large-v3-turbo-de",
        size_gb=1.62,
        licence="Apache-2.0",
        claim="2.6% word errors over its German test sets against 3.3% for Whisper Large v3",
        source="https://huggingface.co/primeline/whisper-large-v3-turbo-german",
    ),
    "th": LanguageModel(
        language="th",
        name="Thonburian Whisper Large v3 Thai",
        engine=ENGINE_WHISPER,
        model="thonburian-large-v3-th",
        size_gb=3.09,
        licence="MIT",
        claim="13.9% word errors on FLEURS Thai against 24.1% for Whisper Large v3",
        source="https://huggingface.co/nectec/Pathumma-whisper-th-large-v3",
    ),
    "sv": LanguageModel(
        language="sv",
        name="KB-Whisper Large (National Library of Sweden)",
        engine=ENGINE_WHISPER,
        model="kb-whisper-large-sv",
        size_gb=3.09,
        licence="Apache-2.0",
        claim=("4.1% word errors on Common Voice Swedish against 9.5% for Whisper Large v3 "
               "(FLEURS: 5.4% against 7.8%)"),
        source="https://huggingface.co/KBLab/kb-whisper-large",
    ),
    "he": LanguageModel(
        language="he",
        name="ivrit.ai Whisper Large v3 Turbo Hebrew",
        engine=ENGINE_WHISPER,
        model="ivrit-large-v3-turbo-he",
        size_gb=1.62,
        licence="Apache-2.0",
        claim="18.1% word errors on FLEURS Hebrew against 26.2% for Whisper Large v3 (ivrit.ai's leaderboard)",
        source="https://huggingface.co/spaces/ivrit-ai/hebrew-transcription-leaderboard",
    ),
}


_ALIASES = {"iw": "he", "jw": "jv"}  # legacy codes in the app's language list


def normalize(code: str | None) -> str:
    """The language subtag of a picker code: ``"zh-Hans,zh-CN"`` -> ``"zh"``, ``"pt-BR"`` ->
    ``"pt"``, ``"iw"`` -> ``"he"``; ``""`` for Auto / empty. (The transcriber has a fuller
    version; this one avoids importing it.)"""
    first = (code or "").strip().lower().replace("_", "-").split(",", 1)[0]
    language = first.split("-", 1)[0].strip()
    return _ALIASES.get(language, language)


def for_language(language: str | None) -> LanguageModel | None:
    """The row for a picker or Whisper language code (``"fa"``, ``"zh-Hans,zh-CN"``), or None
    (also for Auto / empty)."""
    return LANGUAGE_MODELS.get(normalize(language))


def active(cfg: dict[str, Any]) -> LanguageModel | None:
    """The row whose model the config runs now, or None when a general model is in use."""
    engine = str(cfg.get("transcribe_backend") or ENGINE_WHISPER).strip().lower()
    for row in LANGUAGE_MODELS.values():
        if row.engine != engine:
            continue
        if engine == ENGINE_WHISPER and str(cfg.get("whisper_model") or "") == row.model:
            return row
        if engine == ENGINE_TRANSFORMERS and str(cfg.get("nvidia_asr_model_id") or "").strip().lower() == row.model.lower():
            return row
    return None


def suggestion(cfg: dict[str, Any], language: str | None) -> tuple[str, LanguageModel] | None:
    """What the Transcribe tab should offer for the picked ``language``.

    ``("offer", row)``: a model for this language exists and is not in use (also when
    another language's model is active: "Use it" then switches straight to this one).
    ``("leave", row)``: ``row`` is in use but the picked language has no model of its own
    (or is Auto), so it would write everything in ``row.language``; offer the way back.
    None: nothing to say.
    """
    current = active(cfg)
    wanted = for_language(language)
    if wanted is not None:
        return None if wanted == current else ("offer", wanted)
    if current is not None:
        return "leave", current
    return None


def apply_language_model(cfg: dict[str, Any], row: LanguageModel) -> dict[str, Any]:
    """Switch ``cfg`` (in place) to ``row``; returns ``cfg``.

    Remembers the engine and models in use before, unless a language model was already
    active (then the remembered general setup stays the one to go back to).
    """
    remembered = cfg.get(PREVIOUS_KEY)
    if active(cfg) is not None and isinstance(remembered, dict):
        # From one language model to another: go back to the general setup first, so the
        # first model's key on the other engine (a Persian nvidia_asr_model_id under a Chinese
        # Whisper model, or the reverse) does not linger; then keep the same memory.
        restore_previous(cfg)
        cfg[PREVIOUS_KEY] = remembered
    elif active(cfg) is None:
        cfg[PREVIOUS_KEY] = {
            "transcribe_backend": str(cfg.get("transcribe_backend") or ENGINE_WHISPER),
            "whisper_model": str(cfg.get("whisper_model") or DEFAULT_MODEL_SLUG),
            "model": cfg.get("model"),
            "model_path": str(cfg.get("model_path") or ""),  # a model folder the user picked
            "nvidia_asr_model_id": str(cfg.get("nvidia_asr_model_id") or ""),
        }
    cfg["transcribe_backend"] = row.engine
    if row.engine == ENGINE_WHISPER:
        _set_whisper_model(cfg, row.model)
    else:
        cfg["nvidia_asr_model_id"] = row.model
    return cfg


def restore_previous(cfg: dict[str, Any]) -> dict[str, Any]:
    """Undo :func:`apply_language_model` (in place): back to the remembered engine and models,
    or to Whisper with the default model when nothing usable was remembered. Returns ``cfg``."""
    prev = cfg.pop(PREVIOUS_KEY, None)
    prev = prev if isinstance(prev, dict) else {}
    engine = str(prev.get("transcribe_backend") or ENGINE_WHISPER)
    slug = str(prev.get("whisper_model") or DEFAULT_MODEL_SLUG)
    nvidia_id = str(prev.get("nvidia_asr_model_id") or "")
    remembered = {"transcribe_backend": engine, "whisper_model": slug, "nvidia_asr_model_id": nvidia_id}
    if active(remembered) is not None:
        # The remembered setup is itself a language model (hand-edited or an older build):
        # never go "back" to one; Whisper with the default model instead.
        engine, slug, nvidia_id, prev = ENGINE_WHISPER, DEFAULT_MODEL_SLUG, "", {}
    if any(r.engine == ENGINE_WHISPER and r.model == slug for r in LANGUAGE_MODELS.values()):
        slug = DEFAULT_MODEL_SLUG  # the remembered Whisper model is a one-language one
    if any(r.engine == ENGINE_TRANSFORMERS and r.model.lower() == nvidia_id.lower() for r in LANGUAGE_MODELS.values()):
        nvidia_id = ""
    cfg["transcribe_backend"] = engine
    _set_whisper_model(cfg, slug)
    if prev.get("model") and str(prev.get("whisper_model") or "") == slug:
        cfg["model"] = prev["model"]  # exactly the entry there was before (an online-catalog one too)
    if prev.get("model_path"):
        cfg["model_path"] = str(prev["model_path"])  # a model folder the user picked
    if nvidia_id:
        cfg["nvidia_asr_model_id"] = nvidia_id
    else:
        cfg.pop("nvidia_asr_model_id", None)  # the config default (Parakeet) applies again
    return cfg


def _set_whisper_model(cfg: dict[str, Any], slug: str) -> None:
    """The three keys the model picker writes for a registry slug (see ``App._on_model_selected``)."""
    from .model_manager import catalog_resolve_entry

    cfg["whisper_model"] = slug
    entry = catalog_resolve_entry(cfg, slug)
    if entry:
        cfg["model"] = entry
    cfg["model_path"] = ""


def whisper_model_folder(cfg: dict[str, Any] | None, row: LanguageModel) -> str:
    """The folder a Whisper-engine row's CTranslate2 files live in under the configured model
    folder (ADR 0018), or "" for a transformers row or an unknown slug."""
    if row.engine != ENGINE_WHISPER:
        return ""
    from .hub import default_hub_folder, model_folder_for
    from .model_manager import catalog_resolve_entry

    entry = catalog_resolve_entry(cfg, row.model)
    if not entry:
        return ""
    hub_folder = str((cfg or {}).get("hub_folder") or "").strip() or str(default_hub_folder())
    return str(model_folder_for(hub_folder, entry["name"]))


def installed_here(row: LanguageModel, cfg: dict[str, Any] | None = None) -> bool:
    """True when ``row`` can run on this computer without a download (web/LAN jobs, ADR 0016/0018).

    A Whisper-engine row: its ``model.bin`` is in its folder under the configured model folder.
    A transformers-engine row: the engine's libraries are installed in versions that fit their pins
    (an older copy would be upgraded on load, a download) and the model's files are in the Hugging
    Face cache (config plus weights). Never downloads, never raises.
    """
    if row.engine == ENGINE_WHISPER:
        try:
            from pathlib import Path

            from .hub import model_weights_present
            from .model_manager import _hf_download_unfinished

            folder = whisper_model_folder(cfg, row)
            # model.bin can be complete while a tokenizer file of the same download is not.
            return model_weights_present(folder or None) and not _hf_download_unfinished(Path(folder))
        except Exception:  # noqa: BLE001 - a probe must never break a request
            return False
    try:
        from pathlib import Path

        from huggingface_hub import try_to_load_from_cache

        from . import optional_deps
        from .backends.nvidia_asr import _deps_available

        if not _deps_available() or optional_deps.outdated(ENGINE_TRANSFORMERS):
            return False
        config_file = try_to_load_from_cache(row.model, "config.json")
        if not isinstance(config_file, str):
            return False
        snapshot = Path(config_file).parent
        # A download still running (or cut off) parks its files as blobs/<hash>.incomplete.
        if any((snapshot.parent.parent / "blobs").glob("*.incomplete")):
            return False
        return any(snapshot.glob("*.safetensors")) or any(snapshot.glob("*.bin"))
    except Exception:  # noqa: BLE001 - a probe must never break a request
        return False


def web_job_model(cfg: dict[str, Any], language: str | None, second_language: str = "") -> LanguageModel | None:
    """The language model a web/LAN job in ``language`` should run on, or None (ADR 0016, 0018).

    None for auto-detect, a mixed-language pair, a language without a row, a model not installed
    here, a server already running that model as its general one (no switch needed), or a server
    not on the Whisper engine: on the transformers engine the server keeps its own model in the
    engine cache, and a second one would break the one-model rule.
    """
    row = for_language(language)
    if row is None or second_language:
        return None
    engine = str(cfg.get("transcribe_backend") or ENGINE_WHISPER).strip().lower()
    if engine != ENGINE_WHISPER or active(cfg) == row:
        return None
    return row if installed_here(row, cfg) else None


def by_model(model_id: str) -> LanguageModel | None:
    """The row whose ``model`` is ``model_id`` (a registry slug or a Hugging Face repo id)."""
    wanted = (model_id or "").strip().lower()
    return next((r for r in LANGUAGE_MODELS.values() if r.model.lower() == wanted), None) if wanted else None

