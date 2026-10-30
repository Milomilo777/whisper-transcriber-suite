"""Apple-silicon engine: Whisper on the Mac's GPU through Apple's MLX (``mlx-whisper``).

Available ONLY on macOS running natively on arm64 (an M-series Mac) with the
``mlx_whisper`` package importable; on every other system the probes say
"unavailable" and nothing here is imported by the rest of the app. The engine
reads the same Whisper model choice as faster-whisper (the catalog slug, for
example ``large-v3-turbo``) and maps it to the matching ``mlx-community``
repository on the Hugging Face Hub (:data:`MODEL_REPOS`); a slug without an MLX
twin (language fine-tunes, ``large-v1``) keeps the app on faster-whisper.

Models are never fetched silently: :func:`ensure_mlx_model` is called from
``core.model_manager.ensure_model`` after the app's "Whisper model required"
question, and :meth:`MlxWhisperBackend.load` only loads what is on disk.

Audio is decoded with PyAV (``faster_whisper.audio.decode_audio``, already
bundled) and handed to MLX as a 16 kHz float array, so no ffmpeg on PATH is
needed. The segments have the shape every writer expects: ``start``, ``end``,
``text`` and, with word timestamps, ``words`` of ``{start, end, word,
probability}``.
"""
from __future__ import annotations

import importlib.util
import logging
import math
import platform
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from .. import offline
from .._gc_import_guard import gc_disabled_import
from .._liveness_tick import liveness_tick
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)

ENGINE_NAME = "mlx_whisper"
PACKAGE_NAME = "mlx_whisper"

# Catalog slug -> (Hugging Face repo, approximate download bytes). Sizes are the
# repo file sizes read from the Hub on 2026-10-27; every repo holds config.json
# plus one weights file (``weights.npz`` or ``weights.safetensors``).
_MB = 1_000_000
MODEL_REPOS: dict[str, tuple[str, int]] = {
    "tiny": ("mlx-community/whisper-tiny-mlx", 74 * _MB),
    "tiny.en": ("mlx-community/whisper-tiny.en-mlx", 74 * _MB),
    "base": ("mlx-community/whisper-base-mlx", 144 * _MB),
    "base.en": ("mlx-community/whisper-base.en-mlx", 144 * _MB),
    "small": ("mlx-community/whisper-small-mlx", 481 * _MB),
    "small.en": ("mlx-community/whisper-small.en-mlx", 481 * _MB),
    "medium": ("mlx-community/whisper-medium-mlx", 1525 * _MB),
    "medium.en": ("mlx-community/whisper-medium.en-mlx", 1525 * _MB),
    "large-v2": ("mlx-community/whisper-large-v2-mlx", 3083 * _MB),
    "large-v3": ("mlx-community/whisper-large-v3-mlx", 3084 * _MB),
    "large-v3-turbo": ("mlx-community/whisper-large-v3-turbo", 1614 * _MB),
    "distil-large-v3": ("mlx-community/distil-whisper-large-v3", 1509 * _MB),
    "distil-medium.en": ("mlx-community/distil-whisper-medium.en", 786 * _MB),
}

_WEIGHT_FILES = ("weights.safetensors", "weights.npz")
_DOWNLOAD_PATTERNS = ["config.json", *_WEIGHT_FILES]


# ------------------------------------------------------------------ probes


def is_apple_silicon(system: str | None = None, machine: str | None = None) -> bool:
    """True on macOS running natively on arm64 (not Intel, not under Rosetta)."""
    sysname = platform.system() if system is None else system
    arch = platform.machine() if machine is None else machine
    return sysname == "Darwin" and arch == "arm64"


def package_installed() -> bool:
    """The ``mlx_whisper`` files are on disk (no import: startup-safe)."""
    try:
        return importlib.util.find_spec(PACKAGE_NAME) is not None
    except Exception:  # noqa: BLE001 -- find_spec can raise on a broken install
        return False


def package_importable() -> bool:
    """``mlx_whisper`` imports cleanly (a native-library problem reads as False)."""
    if not package_installed():
        return False
    with gc_disabled_import():
        try:
            import mlx_whisper  # type: ignore[import-not-found]  # noqa: F401
        except Exception:  # noqa: BLE001 -- OSError / RuntimeError from a bad dylib
            return False
    return True


def is_available() -> bool:
    """Apple silicon AND the package imports. Does not look at the model files."""
    return is_apple_silicon() and package_importable()


def availability_reason() -> str:
    if not is_apple_silicon():
        return "needs a Mac with Apple silicon"
    if not package_installed():
        return "mlx-whisper Python package not installed"
    if not package_importable():
        return "mlx-whisper could not be loaded"
    return ""


def usable_for(cfg: Mapping[str, Any]) -> bool:
    """Cheap check (no import of the heavy package) that this engine can run the config.

    Apple silicon, the package on disk, and a model with an MLX twin. The real
    import check happens when the engine loads.
    """
    return is_apple_silicon() and package_installed() and supports_model(cfg)


def auto_selected(cfg: Mapping[str, Any]) -> bool:
    """True when the engine is the automatic default for this config."""
    return bool(cfg.get("apple_silicon_engine", True)) and usable_for(cfg)


def resolve_engine_choice(merged: dict[str, Any], baseline: dict[str, Any] | None = None) -> None:
    """Settle ``transcribe_backend`` of a freshly loaded config, in place.

    * On an M-series Mac with the engine usable and the opt-out ``apple_silicon_engine``
      not switched off, the Faster-Whisper default becomes ``mlx_whisper``. A cloud or
      whisper.cpp pick is never replaced. ``baseline`` follows, so the automatic pick is
      never saved as if the user had chosen it.
    * A saved ``mlx_whisper`` that cannot run here (a config.json copied from a Mac, a
      model without an MLX twin, the package missing) or that the opt-out switched off
      reads as Faster-Whisper. (Picking an engine in the list sets the opt-out: off for Faster-Whisper, on for this one.)
    Nothing changes on Windows, Linux or an Intel Mac.
    """
    backend = str(merged.get("transcribe_backend") or "").strip().lower()
    if backend == ENGINE_NAME:
        if not auto_selected(merged):
            merged["transcribe_backend"] = "faster_whisper"
        return
    if backend in ("", "faster_whisper") and auto_selected(merged):
        merged["transcribe_backend"] = ENGINE_NAME
        if baseline is not None:
            baseline["transcribe_backend"] = ENGINE_NAME


# ------------------------------------------------------------------ models


def slug_for(cfg: Mapping[str, Any]) -> str:
    """The catalog slug the config asks for (falls back to the app default)."""
    slug = str(cfg.get("whisper_model") or "").strip()
    if slug:
        return slug
    from ..model_manager import DEFAULT_MODEL_SLUG

    return DEFAULT_MODEL_SLUG


def supports_model(cfg: Mapping[str, Any]) -> bool:
    """True when the chosen Whisper model has an MLX twin."""
    return slug_for(cfg) in MODEL_REPOS


def repo_for(cfg: Mapping[str, Any]) -> str:
    entry = MODEL_REPOS.get(slug_for(cfg))
    return entry[0] if entry else ""


def approx_bytes_for(cfg: Mapping[str, Any]) -> int:
    entry = MODEL_REPOS.get(slug_for(cfg))
    return entry[1] if entry else 0


def model_folder(cfg: Mapping[str, Any]) -> Path:
    """Where this model lives: ``<model folder>/mlx-whisper/<slug>``."""
    from ..hub import default_hub_folder

    hub = str(cfg.get("hub_folder") or "").strip()
    base = Path(hub) if hub else Path(default_hub_folder())
    return base / "mlx-whisper" / slug_for(cfg)


def model_present(cfg: Mapping[str, Any]) -> bool:
    """config.json and a non-empty weights file are on disk, no unfinished blob."""
    try:
        folder = model_folder(cfg)
        if not (folder / "config.json").is_file():
            return False
        if not any(
            (folder / name).is_file() and (folder / name).stat().st_size > 0
            for name in _WEIGHT_FILES
        ):
            return False
        from ..model_manager import _hf_download_unfinished

        return not _hf_download_unfinished(folder)
    except Exception:  # noqa: BLE001 -- a probe never raises
        return False


def ensure_mlx_model(
    config: Mapping[str, Any],
    status_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Make sure the MLX model is on disk; return its folder.

    Called only after the user agreed to the download (the app's "Whisper model
    required" question). An installed model is never touched; a killed download
    resumes in place. Raises the same errors as ``ensure_model``.
    """
    from .. import model_manager as mm

    folder = model_folder(config)
    repo = repo_for(config)
    if not repo:
        raise RuntimeError(
            f"The Apple-silicon engine has no model for '{slug_for(config)}'. "
            "Pick another model or the Faster-Whisper engine."
        )
    if model_present(config):
        if status_cb:
            status_cb("Model already installed")
        mm._notify(progress_cb, phase="installed", status="Model already installed", percent=100)
        return str(folder)

    offline.require_online(f"downloading the model {repo}")
    approx = approx_bytes_for(config)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if mm._is_permission_error(e):
            raise mm.ModelDestinationNotWritable(folder.parent) from e
        raise
    mm._require_free_space(folder.parent, max(0, approx - mm._tree_size(folder)), "the model download")
    if cancel_event is not None and cancel_event.is_set():
        raise mm.DownloadCancelled("cancelled")

    if status_cb:
        status_cb(f"Downloading '{repo}' from huggingface.co ...")
    mm._notify(progress_cb, phase="download", status=f"Downloading {repo} from Hugging Face...",
               percent=0, detail="huggingface.co")
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

        with mm._progress_feed(folder, approx, progress_cb):
            snapshot_download(
                repo_id=repo, local_dir=str(folder), allow_patterns=_DOWNLOAD_PATTERNS,
            )
    except Exception as e:  # noqa: BLE001 -- turned into the app's own error types
        if cancel_event is not None and cancel_event.is_set():
            raise mm.DownloadCancelled("cancelled") from e
        if isinstance(e, OSError) and mm._is_permission_error(e) and not mm._is_disk_full(e):
            raise mm.ModelDestinationNotWritable(folder) from e
        raise mm.HuggingFaceDownloadError(
            mm._describe_download_error(e, folder.parent, "huggingface.co")
        ) from e
    if cancel_event is not None and cancel_event.is_set():
        raise mm.DownloadCancelled("cancelled")
    if not model_present(config):
        raise mm.HuggingFaceDownloadError(
            f"the download of {repo} finished but its weights are not in {folder}"
        )
    if status_cb:
        status_cb("Model ready")
    mm._notify(progress_cb, phase="ready", status="Model ready", percent=100,
               detail="Download complete (Hugging Face)")
    return str(folder)


# ------------------------------------------------------------- the backend


def map_result(
    result: Mapping[str, Any], *, want_words: bool,
) -> tuple[list[dict[str, Any]], str]:
    """Turn an ``mlx_whisper.transcribe`` result into writer segments + language."""
    segments: list[dict[str, Any]] = []
    for seg in result.get("segments") or []:
        text = str(seg.get("text") or "").strip()
        payload: dict[str, Any] = {
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "text": text,
        }
        if want_words:
            words: list[dict[str, Any]] = []
            for w in seg.get("words") or []:
                words.append({
                    "start": float(w.get("start") or 0.0),
                    "end": float(w.get("end") or 0.0),
                    "word": str(w.get("word") or ""),
                    "probability": float(w.get("probability") or 0.0),
                })
            payload["words"] = words
        segments.append(payload)
    return segments, str(result.get("language") or "")


def _decode_audio(path: str) -> Any:
    """16 kHz mono float32 samples, decoded by PyAV (bundled with faster-whisper)."""
    from faster_whisper.audio import decode_audio  # type: ignore[import-not-found]

    return decode_audio(path, sampling_rate=16000)


class MlxWhisperBackend(Backend):
    """Runs Whisper on the Apple GPU. One model per worker process."""

    name = ENGINE_NAME

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config = config
        self._model_dir = ""
        self._ready = False
        self._error: str | None = None

    def _cfg(self) -> Mapping[str, Any]:
        if self._config is not None:
            return self._config
        from ..config import load_config

        return load_config(fetch_online=False)

    def is_ready(self) -> bool:
        return self._ready

    @property
    def device(self) -> str:
        return "mlx" if self._ready else "unknown"

    def get_error(self) -> str | None:
        return self._error

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self._ready = False
        self._error = None
        if not is_available():
            self._error = f"Apple-silicon engine unavailable: {availability_reason()}"
            if status_cb:
                status_cb(self._error)
            return False
        cfg = self._cfg()
        if not supports_model(cfg):
            self._error = (
                f"The Apple-silicon engine has no model for '{slug_for(cfg)}'. "
                "Pick another model or the Faster-Whisper engine."
            )
            if status_cb:
                status_cb(self._error)
            return False
        if not model_present(cfg):
            # Never a silent download: the app asks first and ensure_model fetches.
            self._error = (
                f"The Apple-silicon model is not downloaded yet ({model_folder(cfg)}). "
                "Start a transcription from the app to download it."
            )
            if status_cb:
                status_cb(self._error)
            return False
        self._model_dir = str(model_folder(cfg))
        if status_cb:
            status_cb("Loading Apple-silicon model...")
        try:
            self._warm_up(self._model_dir)
        except Exception as e:  # noqa: BLE001 -- surfaced as the engine error
            self._error = f"Apple-silicon model load failed: {e}"
            if status_cb:
                status_cb(self._error)
            return False
        self._ready = True
        if status_cb:
            status_cb("Apple-silicon model loaded")
        if progress_cb:
            progress_cb({"phase": "loaded", "status": "Model loaded", "percent": 100,
                         "detail": "Ready (Apple silicon)"})
        return True

    @staticmethod
    def _warm_up(model_dir: str) -> None:
        """Load the weights into MLX's one-model holder so the first job starts at once."""
        import mlx.core as mx  # type: ignore[import-not-found]
        from mlx_whisper.transcribe import ModelHolder  # type: ignore[import-not-found]

        ModelHolder.get_model(model_dir, mx.float16)

    def unload(self) -> None:
        self._ready = False
        self._model_dir = ""
        try:
            from mlx_whisper.transcribe import ModelHolder  # type: ignore[import-not-found]

            ModelHolder.model = None
            ModelHolder.model_path = None
        except Exception:  # noqa: BLE001 -- package absent or already gone
            pass

    def transcribe_to_segments(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        want_words: bool = False,
        vad_parameters: dict[str, Any] | None = None,
        initial_prompt: str | None = None,
        hotwords: str | None = None,
        batch_size: int = 16,
        progress_cb: Callable[[int], None] | None = None,
        log_cb: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        paused: Callable[[], bool] | None = None,
        duration: float = 0.0,
    ) -> tuple[list[dict[str, Any]], LanguageInfo]:
        if not self._ready or not self._model_dir:
            raise RuntimeError(self._error or "mlx_whisper backend not loaded")
        if not math.isfinite(duration):
            duration = 0.0

        import mlx_whisper  # type: ignore[import-not-found]

        audio = _decode_audio(audio_path)
        kwargs: dict[str, Any] = {
            "path_or_hf_repo": self._model_dir,
            "word_timestamps": bool(want_words),
            "verbose": None,
        }
        if language:
            kwargs["language"] = language
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        # One blocking call that returns when the whole file is done: no events
        # meanwhile, so the liveness tick keeps the parent's watchdog quiet. A Stop
        # during the call is honoured right after it returns.
        if log_cb:
            log_cb("Apple-silicon engine: transcribing (no per-segment progress)")
        if progress_cb:
            progress_cb(0)
        with liveness_tick(log_cb, "Apple-silicon transcribe"):
            result = mlx_whisper.transcribe(audio, **kwargs)
        if cancelled and cancelled():
            if log_cb:
                log_cb("Task cancelled")
            return [], LanguageInfo(language=language or "", probability=0.0)

        segments, detected = map_result(result, want_words=want_words)
        if log_cb:
            for seg in segments:
                log_cb(f"[{seg['start']:.2f} --> {seg['end']:.2f}] {seg['text']}")
        if progress_cb:
            progress_cb(100)
        detected = detected or (language or "")
        return segments, LanguageInfo(language=detected, probability=1.0 if detected else 0.0)
