"""Download a language model (ADR 0015) to this computer without switching to it (ADR 0018).

The web / LAN page may ask the computer to fetch the model trained for a language, so later web
jobs in that language run on it (ADR 0016). Only rows of :data:`core.language_models.LANGUAGE_MODELS`
can be fetched (fixed Hugging Face repositories, never a URL from the request), one download at a
time, and the desktop's own engine and model are never changed. A Whisper-engine row lands in its
folder under the model folder, as the model picker would put it; a transformers-engine row installs
the engine's libraries when they are missing or older than their pins, then puts the model files in
the Hugging Face cache, where the engine loads them from.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from . import language_models as lm

logger = logging.getLogger(__name__)

#: Model files the transformers engine never reads (the NeMo checkpoint duplicates the weights).
_SKIP_FILES = ["*.nemo", "assets/*"]
#: Room the transformers engine's libraries take when they are not installed yet.
_ENGINE_BYTES = 1_200 * 1024 * 1024

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}  # language -> {"state", "percent", "message"}


def status(language: str) -> dict[str, Any] | None:
    """A copy of the last download state for ``language`` ("downloading", "failed" or "done"),
    or None when no download was asked for since the app started."""
    with _LOCK:
        entry = _STATE.get(lm.normalize(language))
        return dict(entry) if entry else None


def busy() -> bool:
    with _LOCK:
        return any(e["state"] == "downloading" for e in _STATE.values())


def start(language: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """Start fetching the model for ``language`` in the background.

    Returns ``(outcome, message)``; outcome is "started", "installed" (nothing to do), "busy"
    (another download runs), "unknown" (no model for that language), or "refused" (offline, no
    room on the disk, or this build cannot install the engine). Never raises.
    """
    row = lm.for_language(language)
    if row is None:
        return "unknown", "No model trained for that language is offered."
    if lm.installed_here(row, cfg):
        return "installed", f"{row.name} is already on this computer."
    problem = _refusal(row, cfg)
    if problem:
        return "refused", problem
    with _LOCK:
        if any(e["state"] == "downloading" for e in _STATE.values()):
            return "busy", "Another model is downloading; try again when it has finished."
        _STATE[row.language] = {"state": "downloading", "percent": None, "message": "Starting…"}
    snapshot = dict(cfg)
    thread = threading.Thread(target=_run, args=(row, snapshot), name=f"lm-fetch-{row.language}",
                              daemon=True)
    try:
        thread.start()
    except Exception as e:
        # "can't start new thread" under thread exhaustion: without this,
        # the "downloading" state committed above never clears and busy()
        # refuses every later request until the app restarts.
        with _LOCK:
            if _STATE.get(row.language, {}).get("state") == "downloading":
                del _STATE[row.language]
        logger.warning("Could not start the %s model download thread: %s", row.name, e)
        return "refused", f"Could not start the download of {row.name}: {e}"
    logger.info("language model download started: %s (%s)", row.name, row.model)
    return "started", f"Downloading {row.name} (about {row.size_gb:.1f} GB) to this computer."


def _refusal(row: lm.LanguageModel, cfg: dict[str, Any]) -> str:
    """Why ``row`` cannot be fetched now, or ""."""
    from . import offline

    if offline.is_offline():
        return "This computer is set to Work offline."
    needed = int(row.size_gb * 1024 ** 3)
    if row.engine == lm.ENGINE_WHISPER:
        folder = lm.whisper_model_folder(cfg, row)
        if not folder:
            return f"{row.name} is not in this app version's model list."
        targets = [(Path(folder).parent, needed)]
    else:
        from . import optional_deps
        from .backends.nvidia_asr import _deps_available

        engine_missing = not _deps_available() or bool(optional_deps.outdated(lm.ENGINE_TRANSFORMERS))
        if engine_missing and not optional_deps.can_install():
            return optional_deps.FROZEN_INSTALL_MESSAGE
        targets = [(_hf_cache_root(), needed)]
        if engine_missing:
            targets.append((Path(optional_deps.extras_dir()), _ENGINE_BYTES))
    from .model_manager import InsufficientDiskSpace, _require_free_space

    try:
        for folder, size in targets:
            existing = _existing_parent(folder)
            if existing is not None:
                _require_free_space(existing, size, f"{row.name}")
    except InsufficientDiskSpace as e:
        return str(e)
    return ""


def _existing_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def _hf_cache_root() -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE)


def _set(language: str, **changes: Any) -> None:
    with _LOCK:
        _STATE.setdefault(language, {}).update(changes)


def _progress(language: str) -> Callable[[dict[str, Any]], None]:
    def _cb(info: dict[str, Any]) -> None:
        percent = info.get("percent")
        if info.get("phase") == "download" and isinstance(percent, (int, float)):
            _set(language, percent=int(percent), message="Downloading the model…")
    return _cb


def _run(row: lm.LanguageModel, cfg: dict[str, Any]) -> None:
    language = row.language

    def _status(text: str) -> None:
        _set(language, message=str(text)[:300])

    try:
        if row.engine == lm.ENGINE_WHISPER:
            _fetch_whisper(row, cfg, _status, _progress(language))
        else:
            _fetch_transformers(row, cfg, _status, _progress(language))
        if not lm.installed_here(row, cfg):
            raise RuntimeError("the files are not complete after the download")
    except Exception as e:  # noqa: BLE001 - reported to the page, never raised into a thread
        logger.warning("language model download failed: %s: %s", row.model, e)
        _set(language, state="failed", percent=None, message=str(e)[:300] or type(e).__name__)
        return
    except BaseException:
        # Anything else (a SystemExit from an installer) must not leave "downloading" behind:
        # every later request would be refused as busy until the app restarts.
        _set(language, state="failed", percent=None, message="the download stopped unexpectedly")
        raise
    logger.info("language model download finished: %s", row.model)
    _set(language, state="done", percent=100, message=f"{row.name} is on this computer.")


def _fetch_whisper(row: lm.LanguageModel, cfg: dict[str, Any], status_cb: Callable[[str], None],
                   progress_cb: Callable[[dict[str, Any]], None]) -> None:
    from .model_manager import catalog_resolve_entry, ensure_model

    entry = catalog_resolve_entry(cfg, row.model)
    if not entry:
        raise RuntimeError(f"{row.model} is not in the model list")
    ensure_model({**cfg, "model": entry, "model_path": lm.whisper_model_folder(cfg, row),
                  "whisper_model": row.model}, status_cb, progress_cb)


def _fetch_transformers(row: lm.LanguageModel, cfg: dict[str, Any], status_cb: Callable[[str], None],
                        progress_cb: Callable[[dict[str, Any]], None]) -> None:
    from huggingface_hub import snapshot_download

    from . import offline
    from .backends.nvidia_asr import NvidiaAsrBackend
    from .model_manager import _progress_feed

    engine = NvidiaAsrBackend(config={**cfg, "nvidia_asr_model_id": row.model})
    if not engine.prepare_engine(status_cb):
        raise RuntimeError(engine.get_error() or "the engine could not be installed")
    offline.require_online(f"downloading {row.name}")  # Work offline may have been turned on meanwhile
    status_cb("Downloading the model…")
    folder = _hf_cache_root() / ("models--" + row.model.replace("/", "--"))
    with _progress_feed(folder, int(row.size_gb * 1024 ** 3), progress_cb):
        snapshot_download(row.model, ignore_patterns=_SKIP_FILES)
