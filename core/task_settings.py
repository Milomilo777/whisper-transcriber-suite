"""Per-task settings: what a queued transcription carries to the worker.

The transcription worker is a long-lived process that loads ``config.json``
once, when it starts. The app never restarts it when the user changes a
setting, so any option read from that start-up copy stayed frozen until the
next app launch (an unticked "Identify speakers" kept labelling speakers).

The fix is structural rather than per key: when a task is dispatched the app
stamps a snapshot of every PER-TASK option on it (``snapshot``), the
``transcribe`` command carries it, and the worker applies it for that one
task and puts its own copy back afterwards
(``core.transcriber._runtime_overrides_scope``). A running task therefore
never changes mid-way, and the next task always sees the settings the UI
shows when it starts.

Key classes (``tests/core/test_task_settings.py`` scans the transcriber so
a new ``config.get("x")`` cannot be left unclassified):

* ``PER_TASK_KEYS``   -- re-read for every task; travel in the snapshot.
* ``LOAD_TIME_KEYS``  -- fixed by the model/engine the worker loaded; a change
  needs a fresh worker (the app already restarts it), never a snapshot.
* ``OTHER_KEYS``      -- carried by their own command field, or worker-owned.
* ``SECRET_KEYS``     -- per-task in effect, but never sent over the pipe.

Pure Python, no heavy imports: the app imports it in the Tk process.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Mapping
from urllib.parse import urlsplit

from .config import load_config

logger = logging.getLogger(__name__)

PER_TASK_KEYS: tuple[str, ...] = (
    # Voice-activity detection and decode guards.
    "vad_enabled",
    "vad_min_silence_ms",
    "vad_threshold",
    "vad_speech_pad_ms",
    "vad_window_s",
    "loop_guard_repeats",
    # Decoding.
    "word_timestamps",
    "initial_prompt",
    "hotwords",
    "batch_size",
    # Audio pre-processing.
    "demucs_enabled",
    "denoise_enabled",
    "denoise_level",
    # Post-processing.
    "diarization_enabled",
    "diarization_num_speakers",
    "diarization_cluster_threshold",
    "alignment",
    "hallucination_detect_enabled",
    "auto_chapters_enabled",
    "chapter_min_seconds",
    "chapter_gap_seconds",
    # AI layer used for chapter titles (the API key is a SECRET_KEY).
    "ai_enabled",
    "llm_provider",
    "llm_remote_base_url",
    "llm_remote_model",
    "ai_model_path",
    # Output file naming.
    "output_filename_template",
)

# Defaults for keys that may be missing from the app config (no DEFAULT_CONFIG
# entry), so "absent" still overrides a stale worker value.
FALLBACKS: dict[str, Any] = {"alignment": "none"}

LOAD_TIME_KEYS: tuple[str, ...] = (
    "transcribe_backend",
    "model",
    "model_path",
    "whisper_model",
    "device",
    "compute_type",
)

OTHER_KEYS: tuple[str, ...] = (
    # Rides the command as ``output_formats`` (add-only field, older than this).
    "output_formats",
    # A usage counter the worker itself increments and persists.
    "cloud_stt_minutes_used",
)

SECRET_KEYS: tuple[str, ...] = ("llm_remote_api_key",)

# Keys no UI control edits: users change them by hand in config.json while
# the app is open, which the in-memory app config never sees. They are merged
# from disk when a task is stamped (the UI keys keep the live value).
NO_UI_KEYS: tuple[str, ...] = (
    "chapter_min_seconds",
    "chapter_gap_seconds",
    "loop_guard_repeats",
    "vad_window_s",
    "output_filename_template",
    "batch_size",
)

# Read from config.json by the module that needs them, on every use: never
# stale, so they need no snapshot.
FRESH_READ_KEYS: tuple[str, ...] = ("denoise_cache_mb", "demucs_cache_mb")


def url_has_credentials(url: Any) -> bool:
    """True when ``url`` carries userinfo (``user:pw@host``) or a query string
    (``?api-key=...``): either can hold a secret, so it never crosses the pipe
    (the worker reads such a value fresh from config.json instead)."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parts = urlsplit(url)
        return bool(parts.query or "@" in parts.netloc)
    except ValueError:
        return True  # unparseable: treat as sensitive, do not send


def _jsonable(value: Any) -> Any:
    """``value`` with every path-like turned into ``str`` (lists/dicts too)."""
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def snapshot(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The per-task options of ``cfg``, detached and JSON-safe.

    Only ``PER_TASK_KEYS`` are copied: never a secret, never a load-time key.
    A value that cannot be sent as JSON is skipped (the worker then keeps its
    own value for that key) instead of failing the whole dispatch.
    """
    out: dict[str, Any] = {}
    for key in PER_TASK_KEYS:
        if key in cfg:
            value = cfg[key]
        elif key in FALLBACKS:
            value = FALLBACKS[key]
        else:
            continue
        if key == "llm_remote_base_url" and url_has_credentials(value):
            continue  # read fresh by the worker, like the API key
        value = _jsonable(value)
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            logger.warning(
                "task settings: %r (%s) cannot be sent to the worker; "
                "the worker keeps its own value for it",
                key, type(value).__name__,
            )
            continue
        out[key] = copy.deepcopy(value)
    return out


def _no_ui_from_disk() -> dict[str, Any]:
    """Current on-disk values of ``NO_UI_KEYS`` (cheap read, no online fetch).

    Empty when the file cannot be read: the live values then stand.
    """
    try:
        disk = load_config(fetch_online=False)
    except Exception as exc:  # noqa: BLE001 - never block a dispatch on this
        logger.warning("task settings: config.json not re-read (%s)", exc)
        return {}
    return {key: disk[key] for key in NO_UI_KEYS if key in disk}


def from_command(raw: Any) -> dict[str, Any] | None:
    """Worker side: the usable part of a command's ``settings`` field.

    ``None`` when absent or not an object (an older parent, a malformed
    line); otherwise only the known per-task keys, so a forged payload can
    neither switch the engine nor point the worker at another model.
    """
    if not isinstance(raw, dict):
        return None
    return {key: copy.deepcopy(raw[key]) for key in PER_TASK_KEYS if key in raw}


def stamp(task: Any, cfg: Mapping[str, Any]) -> dict[str, Any] | None:
    """Give ``task`` its snapshot once, at dispatch; return the snapshot.

    A task that already has one keeps it: the snapshot is what the task
    started with (a resume of it must continue with the same options).
    """
    existing = getattr(task, "task_settings", None)
    if isinstance(existing, dict):
        return existing
    snap = snapshot({**cfg, **_no_ui_from_disk()})
    try:
        task.task_settings = snap
    except Exception:  # noqa: BLE001 - frozen/tuple-like task objects
        pass
    return snap


def inherit(new_task: Any, old_task: Any) -> None:
    """Resume: continue ``old_task``'s run with the options it started with.

    The checkpoint fingerprint covers the options that shape the transcript,
    so a resume under changed settings would be refused (and re-run from
    scratch). A task that was never dispatched has no snapshot to hand over.
    """
    old = getattr(old_task, "task_settings", None)
    if isinstance(old, dict):
        new_task.task_settings = copy.deepcopy(old)
