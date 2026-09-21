"""Periodic checkpoint for in-progress transcriptions.

The transcribe loop writes a JSON checkpoint to disk every N segments
or every X seconds (whichever fires first). On a cancel/pause/crash
that checkpoint is the only thing standing between the user and a
re-run from scratch.

Layout:
  ``user_data_dir() / "partials" / "<sha1(abs_source_path)>.json"``

Atomic writes go through ``<path>.tmp`` + ``os.replace`` so a torn
file is never observable to the resume path.

This module is intentionally tiny and self-contained: it imports
nothing from ``core.transcriber`` to keep the dependency direction
one-way (transcriber -> _checkpoint), and it uses no third-party
modules so tests can exercise it without faster_whisper installed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from .config import user_data_dir

logger = logging.getLogger(__name__)

# Wire-format version. Bump only on a breaking change to the on-disk
# schema (renamed/removed field, type change). Add-only field changes
# do NOT require a bump; the loader tolerates unknown keys.
SCHEMA_VERSION = 1

# Keys from the runtime ``config`` dict that materially affect what
# Whisper produces. A change in any of these between checkpoint write
# and resume means the new segments would be inconsistent with the
# already-captured ones, so the resume must refuse and the user must
# re-transcribe. Order is intentionally deterministic — the
# fingerprint is a sha1 over a sorted JSON representation, so a
# different key ordering in ``config`` won't cause a false mismatch.
_CONFIG_FINGERPRINT_KEYS: tuple[str, ...] = (
    "alignment",
    "backend",  # alias seen in some configs; tolerated below
    "batch_size",
    "compute_type",
    # Pre-processing changes the audio the model sees, so resuming with
    # a different setting would splice two differently-conditioned halves
    # into one transcript. ``demucs_enabled`` had the same hole and is
    # fixed here alongside the denoise keys.
    "demucs_enabled",
    "denoise_enabled",
    "denoise_level",
    "device",
    "hotwords",
    "initial_prompt",
    "model",
    "transcribe_backend",
    "vad_enabled",
    "vad_min_silence_ms",
    "vad_speech_pad_ms",
    "vad_threshold",
    "whisper_model",
    "word_timestamps",
)


def partials_dir() -> Path:
    """Folder where checkpoint JSONs live. Created on demand."""
    p = user_data_dir() / "partials"
    p.mkdir(parents=True, exist_ok=True)
    return p


def source_key(source_path: str) -> str:
    """Stable sha1 of the absolute source path.

    The path is run through ``os.path.normcase`` so the key matches the
    filesystem's own case semantics: on Windows it lowercases the drive
    letter / path (and normalises slashes), so a checkpoint written for
    ``C:\\Foo.mp4`` is still found when the same file is reopened as
    ``c:\\foo.mp4`` — otherwise the differing-case path hashed to a
    different key and the resume silently fell back to a full re-run.
    On case-sensitive POSIX, ``normcase`` is a no-op, so two genuinely
    distinct files differing only in case keep distinct keys.
    """
    norm = os.path.normcase(os.path.abspath(source_path))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def checkpoint_path(source_path: str) -> Path:
    return partials_dir() / f"{source_key(source_path)}.json"


def config_fingerprint(cfg: dict[str, Any]) -> str:
    """Stable sha1 over the transcription-affecting config keys.

    Only the keys in ``_CONFIG_FINGERPRINT_KEYS`` are included; the
    user changing e.g. ``theme`` between cancel and resume must not
    invalidate the partial. Nested dicts (``model``) are serialised
    with ``sort_keys=True`` so dict-iteration order doesn't change
    the fingerprint either.
    """
    extracted: dict[str, Any] = {}
    for key in _CONFIG_FINGERPRINT_KEYS:
        if key in cfg:
            extracted[key] = cfg[key]
    blob = json.dumps(extracted, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def write_checkpoint(
    source_path: str,
    *,
    backend: str,
    model_name: str,
    language: str,
    language_probability: float,
    cfg_fingerprint: str,
    last_end_time: float,
    segments: list[dict[str, Any]],
    checkpoint_time: float,
) -> Path:
    """Atomically persist a checkpoint.

    Stat the source file once at write time so the resume path can
    detect a moved/edited source. Errors are propagated — callers
    log/swallow them.
    """
    import time as _time

    abs_path = os.path.abspath(source_path)
    try:
        st = os.stat(abs_path)
        size = int(st.st_size)
        mtime = float(st.st_mtime)
    except OSError:
        # If we can't stat the source at write time, store zeros — the
        # resume path will refuse on mismatch anyway. Keep going so
        # the segments aren't lost.
        size = 0
        mtime = 0.0

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_path": abs_path,
        "source_size": size,
        "source_mtime": mtime,
        "model_name": model_name,
        "backend": backend,
        "language": language or "",
        "language_probability": float(language_probability or 0.0),
        "config_fingerprint": cfg_fingerprint,
        "last_end_time": float(last_end_time),
        "segment_count": len(segments),
        "segments": segments,
        "checkpoint_time": float(checkpoint_time or _time.time()),
    }

    path = checkpoint_path(abs_path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_checkpoint(source_path: str) -> dict[str, Any] | None:
    """Return the on-disk checkpoint dict, or None if missing/corrupt.

    Catches ``ValueError`` (not just ``json.JSONDecodeError``) because a
    checkpoint file that is not valid UTF-8 raises ``UnicodeDecodeError``
    from the read itself — still "corrupt", and the resume path's
    contract is a silent fallback to a full re-transcribe, never an
    exception out of the worker.
    """
    path = checkpoint_path(source_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("Corrupt checkpoint at %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    return data


def delete_checkpoint(source_path: str) -> None:
    """Remove the checkpoint file for ``source_path``, if any."""
    path = checkpoint_path(source_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not delete checkpoint %s: %s", path, e)


def has_checkpoint(source_path: str) -> bool:
    """True iff a checkpoint JSON exists for the given source path."""
    return checkpoint_path(source_path).exists()


def sweep_partials(
    *, max_age_days: float = 14.0, slice_max_age_minutes: float = 10.0
) -> int:
    """Best-effort cleanup of the ``partials/`` dir. Returns files removed.

    Removes (a) any ``*.slice.wav`` older than ``slice_max_age_minutes`` —
    a resume slice is disposable and a live resume holds a fresh one, so an
    older one is always an orphan from a killed worker; (b) checkpoint
    ``*.json.tmp`` write scratch older than the same short window — a
    worker killed mid-write leaves one behind, and it would otherwise never
    be reclaimed (only ``*.json``/``*.slice.wav`` were swept before); and
    (c) checkpoint ``*.json`` older than ``max_age_days`` — a
    cancelled-but-never-resumed or crashed-then-declined partial that would
    otherwise live (and hold its full captured-segments list, potentially
    MBs) on disk forever.

    Intended to run once at startup. Never raises — a sweep failure must
    never block launch. ``max_age_days`` is generous so a partial the user
    might still want to resume isn't reaped prematurely.
    """
    import time as _time

    try:
        d = partials_dir()
        entries = list(d.iterdir())
    except OSError:
        return 0
    now = _time.time()
    json_cutoff = now - max(0.0, max_age_days) * 86400.0
    slice_cutoff = now - max(0.0, slice_max_age_minutes) * 60.0
    removed = 0
    for p in entries:
        try:
            name = p.name
            if name.endswith(".json.tmp"):
                # Scratch from an interrupted checkpoint write. Only ever
                # visible for the duration of one json.dump + os.replace,
                # so anything this old is a dead worker's leftover.
                if p.stat().st_mtime < slice_cutoff:
                    p.unlink()
                    removed += 1
            elif name.endswith(".slice.wav"):
                if p.stat().st_mtime < slice_cutoff:
                    p.unlink()
                    removed += 1
            elif name.endswith(".json"):
                if p.stat().st_mtime < json_cutoff:
                    p.unlink()
                    removed += 1
        except OSError:
            continue
    return removed


def validate_checkpoint(
    data: dict[str, Any],
    *,
    backend: str,
    model_name: str,
    cfg_fingerprint: str,
) -> str:
    """Return "" if the checkpoint is usable, else a human reason.

    Caller is responsible for deleting the stale partial when the
    return value is non-empty.
    """
    if not isinstance(data, dict):
        return "checkpoint payload is not a dict"
    schema = data.get("schema_version")
    if schema != SCHEMA_VERSION:
        return f"checkpoint schema_version {schema!r} != expected {SCHEMA_VERSION}"
    src = data.get("source_path")
    if not isinstance(src, str) or not src:
        return "checkpoint missing source_path"
    if not os.path.isfile(src):
        return f"source file no longer exists: {src}"
    try:
        st = os.stat(src)
    except OSError as e:
        return f"could not stat source: {e}"
    if int(data.get("source_size") or -1) != int(st.st_size):
        return "source file size has changed since checkpoint"
    saved_mtime = float(data.get("source_mtime") or 0.0)
    # Allow 1 ms slop — filesystem mtime granularity on some volumes
    # is coarser than Python's float repr suggests.
    if abs(saved_mtime - float(st.st_mtime)) > 0.001:
        return "source file mtime has changed since checkpoint"
    if str(data.get("backend") or "") != backend:
        return (
            f"backend changed: checkpoint={data.get('backend')!r} "
            f"current={backend!r}"
        )
    if str(data.get("model_name") or "") != model_name:
        return (
            f"model changed: checkpoint={data.get('model_name')!r} "
            f"current={model_name!r}"
        )
    if str(data.get("config_fingerprint") or "") != cfg_fingerprint:
        return "transcription config changed since checkpoint"
    segs = data.get("segments")
    if not isinstance(segs, list):
        return "checkpoint segments field is not a list"
    return ""
