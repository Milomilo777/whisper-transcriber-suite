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

import errno
import hashlib
import json
import logging
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .config import user_data_dir

logger = logging.getLogger(__name__)


def _flush_to_disk(f: Any) -> None:
    """Flush and fsync a file, tolerating only fsync failures.

    Certain network shares, FUSE systems, or USB filesystems return
    EINVAL/ENOTSUP for fsync. A failed durability sync must never discard
    a transcript that was written successfully — but a failed FLUSH means
    the data never reached the OS at all (a full disk raises ENOSPC at
    flush time, not at write time, once the 8 KB text buffer spills), so
    that error propagates and the caller counts the write as failed
    instead of publishing an empty or truncated file.
    """
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError as e:
        logger.warning("Could not fsync file: %s", e)


# Wire-format version. Bump only on a breaking change to the on-disk
# schema (renamed/removed field, type change). Add-only field changes
# do NOT require a bump; the loader tolerates unknown keys.
SCHEMA_VERSION = 1

# How long write_checkpoint keeps retrying a PermissionError at the final
# os.replace (a concurrent writer for the same source holds the target).
# Kept short: a target that stays locked or read-only fails every periodic
# write the same way, so each failed write must stall the transcribe loop
# only briefly (the caller also stops periodic writes after repeated failures).
_REPLACE_RETRY_SECONDS = 1.0

# Write scratch as write_checkpoint() names it: mkstemp(prefix="<sha1>.json.",
# suffix=".tmp"). Anchored on the 40-hex key so an unrelated file such as
# "report.json.notes.tmp" is never swept.
_SCRATCH_NAME = re.compile(r"^[0-9a-f]{40}\.json\..+\.tmp$")

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

# Keys a fresh profile's config does not store while a run fills them in for its own
# duration (core.transcriber._RUNTIME_OVERRIDE_DEFAULTS). Like the VAD window below, such a
# key joins the hash only when it is not the default: absent and default hash alike, or a
# checkpoint written outside that fill-in would read as "config changed" on resume.
_FINGERPRINT_DEFAULTS: dict[str, Any] = {"alignment": "none"}
_UNSET = object()


def partials_dir() -> Path:
    """Folder where checkpoint JSONs live. Created on demand, best effort.

    The mkdir is best-effort so the READ paths (``has_checkpoint``,
    ``load_checkpoint``, the startup sweep) degrade to "no checkpoint"
    on a read-only profile or a file occupying the path instead of
    raising into the resume menu; a WRITE that needs the dir then fails
    naturally at its own I/O.
    """
    p = user_data_dir() / "partials"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("Could not create partials dir %s: %s", p, e)
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

    ``surrogatepass`` keeps a path with lone surrogates (an unpaired UTF-16
    unit on Windows, an undecodable name byte on POSIX) from raising; for
    every other path the encoded bytes, and so the key, are unchanged.
    """
    norm = os.path.normcase(os.path.abspath(source_path))
    return hashlib.sha1(
        norm.encode("utf-8", "surrogatepass"), usedforsecurity=False
    ).hexdigest()


def checkpoint_path(source_path: str) -> Path:
    return partials_dir() / f"{source_key(source_path)}.json"


def config_fingerprint(
    cfg: dict[str, Any], whisper_task: str = "transcribe", *, _keep_defaults: bool = False,
) -> str:
    """Stable sha1 over the transcription-affecting config keys.

    Only the keys in ``_CONFIG_FINGERPRINT_KEYS`` are included; the
    user changing e.g. ``theme`` between cancel and resume must not
    invalidate the partial. Nested dicts (``model``) are serialised
    with ``sort_keys=True`` so dict-iteration order doesn't change
    the fingerprint either.

    ``whisper_task`` joins the hash only for ``"translate"``, so the
    fingerprint of a normal transcription (and every checkpoint written
    before the translate option existed) stays unchanged.
    """
    extracted: dict[str, Any] = {}
    for key in _CONFIG_FINGERPRINT_KEYS:
        if key in cfg and (_keep_defaults or cfg[key] != _FINGERPRINT_DEFAULTS.get(key, _UNSET)):
            extracted[key] = cfg[key]
    if whisper_task == "translate":
        extracted["whisper_task"] = whisper_task
    # The VAD window and the loop guard change which segments a run keeps.
    # They join the hash only when their EFFECTIVE value is not the default,
    # so every checkpoint written with defaults stays resumable.
    from . import loop_guard, vad_window

    window = vad_window.window_seconds(cfg)
    if window != vad_window.DEFAULT_WINDOW_S:
        extracted["vad_window_s"] = window
    repeats = loop_guard.repeat_limit(cfg)
    if repeats != loop_guard.DEFAULT_REPEATS:
        extracted["loop_guard_repeats"] = repeats
    blob = json.dumps(extracted, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8"), usedforsecurity=False).hexdigest()


def accepted_fingerprints(cfg: dict[str, Any], whisper_task: str = "transcribe") -> tuple[str, ...]:
    """Fingerprints a resume accepts for ``cfg``: today's and the earlier spelling.

    Builds before the default-omitting rule hashed an explicit ``alignment: "none"`` (a run
    fills it in); a partial they wrote must stay resumable.
    """
    current = config_fingerprint(cfg, whisper_task)
    earlier = config_fingerprint(cfg, whisper_task, _keep_defaults=True)
    return (current,) if earlier == current else (current, earlier)


# Source identity (size, mtime) of the media each run started on, keyed by
# absolute path. A later stat blip must not replace it with "unknown": the
# checkpoint then still says which media the saved segments came from.
_RUN_IDENTITY: dict[str, tuple[int, float]] = {}

# Prefix of every validate_checkpoint reason that means "the media identity
# cannot be verified". The checkpoint is KEPT (quarantined) for those, never
# deleted and never auto-resumed.
UNVERIFIABLE_PREFIX = "checkpoint identity cannot be verified"


def note_source_identity(source_path: str) -> None:
    """Remember the size and mtime of the media a run starts on.

    Call once at run start, before the first checkpoint write. The note is
    authoritative for the whole run: :func:`write_checkpoint` never replaces
    it, so media swapped in mid-run cannot relabel segments that came from
    the original. A failed stat DROPS any earlier note: it may belong to a
    previous run on different media, and trusting it would stamp this run's
    segments with the wrong identity. Without a note, the first checkpoint
    write stats the file and records what it sees.
    """
    abs_path = os.path.abspath(source_path)
    try:
        st = os.stat(abs_path)
        _RUN_IDENTITY[abs_path] = (int(st.st_size), float(st.st_mtime))
    except OSError:
        _RUN_IDENTITY.pop(abs_path, None)


def _previous_identity(abs_path: str) -> tuple[int, float] | None:
    """Numeric identity stored in the checkpoint now on disk, if usable."""
    prev = load_checkpoint(abs_path)
    if not prev:
        return None
    size, mtime = prev.get("source_size"), prev.get("source_mtime")
    if isinstance(size, bool) or isinstance(mtime, bool):
        return None
    if not isinstance(size, int) or not isinstance(mtime, (int, float)):
        return None
    if size == 0 and mtime == 0:
        return None  # the old poison pair is not an identity
    return size, float(mtime)


class CheckpointNotKeptError(RuntimeError):
    """The saved checkpoint could be neither moved nor copied aside.

    It is still in place and a fresh run would overwrite or delete it, so the
    caller must not start one.
    """


# fsync errors that only mean "this file system cannot sync a file". Every
# other OSError (EIO, ENOSPC, ...) means the bytes may not be on disk.
_FSYNC_UNSUPPORTED = frozenset(
    code
    for code in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if code is not None
)


def _strict_sync(f: Any) -> None:
    """Flush and fsync ``f``; only "fsync unsupported" is tolerated.

    The best-effort :func:`_flush_to_disk` is right for ordinary checkpoint
    writes (the next write retries). A copy that authorises a fresh run to
    replace the original must really be durable, so any other error raises.
    """
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError as e:
        if e.errno in _FSYNC_UNSUPPORTED:
            logger.warning("File system cannot fsync (%s); keeping the copy anyway", e)
            return
        raise


# Prefixes of validate_checkpoint reasons that mean "the saved text may be the
# only copy and the media it came from is gone, changed or unverifiable": the
# checkpoint is kept aside (never deleted) and a fresh run starts. Other
# reasons (config, model, backend, schema, segments) keep the old behaviour of
# discarding the partial, because the media is still there and can be
# transcribed again.
KEEP_ASIDE_PREFIXES: tuple[str, ...] = (
    UNVERIFIABLE_PREFIX,
    "source file no longer exists",
    "source file size has changed",
    "source file mtime has changed",
    "could not stat source",
    "checkpoint missing source_size",
    "checkpoint missing source_mtime",
    "checkpoint source_size is not a number",
    "checkpoint source_mtime is not a number",
)


def keeps_text(reason: str) -> bool:
    """True if a validate_checkpoint ``reason`` must keep the checkpoint aside."""
    return reason.startswith(KEEP_ASIDE_PREFIXES)


def _segment_stamp(start: Any) -> str:
    """``HH:MM:SS`` for a segment start, ``??:??:??`` for anything unusable."""
    if isinstance(start, bool) or not isinstance(start, (int, float)):
        return "??:??:??"
    try:
        if not math.isfinite(start) or start < 0 or start > 1e9:
            return "??:??:??"
        total = int(start)
    except (ValueError, OverflowError):
        return "??:??:??"
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _segment_line(seg: Any) -> str | None:
    """One readable line for a saved segment (None = not a segment)."""
    if not isinstance(seg, dict):
        return None
    try:
        text = str(seg.get("text", "")).strip()
    except Exception:  # noqa: BLE001 - a hostile value must not hide the others
        text = "(text could not be read)"
    return f"[{_segment_stamp(seg.get('start'))}] {text}\n"


def recovery_text_path(kept: Path) -> Path:
    """Where the readable copy of the kept-aside checkpoint ``kept`` lives.

    ``<sha1>.json.unverified-<tag>`` pairs with ``<sha1>.unverified-<tag>.txt``
    (no ``.json`` in the name, so nothing that looks for kept checkpoints by
    their ``.json.unverified-`` name takes the text file for one).
    """
    return kept.with_name(kept.name.replace(".json.unverified-", ".unverified-", 1) + ".txt")


def _write_recovery_sidecar(kept: Path, source_path: str, reason: str) -> None:
    """Write the readable text copy of a quarantined checkpoint. Never raises.

    Lines go to the file one by one, so a very large transcript is not also
    built as one big string (the JSON itself still has to be loaded).
    """
    import time as _time

    sidecar: Path | None = None
    try:
        sidecar = recovery_text_path(kept)
        try:
            with open(kept, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        segs = data.get("segments") if isinstance(data, dict) else None
        # errors="replace": a lone surrogate in a Windows path cannot be
        # encoded; lose that character, not the whole sidecar.
        with open(sidecar, "w", encoding="utf-8", newline="\n", errors="replace") as f:
            f.write("Kept-aside transcript (safe to delete once you no longer need it).\n")
            f.write(f"Source file: {source_path}\n")
            f.write(f"Kept aside at: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Reason: {reason or 'not recorded'}\n\n")
            wrote = False
            if isinstance(segs, list):
                for seg in segs:
                    line = _segment_line(seg)
                    if line is not None:
                        f.write(line)
                        wrote = True
            if not wrote:
                f.write("(no readable segments in the saved checkpoint)\n")
            _flush_to_disk(f)
    except Exception as e:  # noqa: BLE001 - the sidecar is a courtesy, never a failure
        logger.warning("Could not write the readable copy %s: %s", sidecar, e)


def _kept_name(path: Path) -> Path:
    """A kept-aside name no other attempt (or process) can also pick."""
    import secrets
    import time as _time

    return path.with_name(
        f"{path.name}.unverified-{int(_time.time())}-{os.getpid()}-{secrets.token_hex(4)}"
    )


def _copy_aside(path: Path, why: OSError) -> Path | None:
    """Preserve the bytes of ``path`` in a new kept file; never touch ``path``.

    The bytes are read once, written to a file created exclusively (so no
    existing file can be overwritten), synced strictly and read back for
    comparison. On failure only a file THIS call created is removed. Returns
    None when ``path`` no longer exists (someone else kept it aside already).
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise CheckpointNotKeptError(
            f"the saved checkpoint {path} could not be kept aside ({why}; read: {e}); "
            "it was left as it is"
        ) from e
    last: OSError = why
    for _ in range(8):
        target = _kept_name(path)
        created = False
        try:
            with open(target, "xb") as f:
                created = True
                f.write(data)
                _strict_sync(f)
            if target.read_bytes() != data:
                raise OSError("the copy does not match the checkpoint it was made from")
            return target
        except FileExistsError as e:
            last = e  # not ours: leave it alone and pick another name
            continue
        except OSError as e:
            last = e
            if created:
                try:
                    target.unlink()
                except OSError:
                    pass
            break
    raise CheckpointNotKeptError(
        f"the saved checkpoint {path} could not be kept aside ({why}; copy: {last}); "
        "it was left as it is"
    ) from last


def quarantine_checkpoint(source_path: str, reason: str = "") -> Path | None:
    """Keep the checkpoint aside; return the kept path (None = nothing to keep).

    The kept name does not end in ``.json``, so the resume path no longer
    sees it and the age sweep never reaps it. Next to it a ``.txt`` file
    holds the saved text, readable without the app. A fresh run can then
    start without touching the saved segments.

    The file is renamed to a unique name (checked free first; ``os.rename``
    also refuses an existing target on Windows). If the rename fails its
    bytes are copied (:func:`_copy_aside`); this never deletes the original,
    a fresh run replaces it later. If the text cannot be kept either way
    (the checkpoint may be the only copy) this raises
    :class:`CheckpointNotKeptError` and the caller must not start that run.
    Returns None when the checkpoint is already gone (another process kept it).
    """
    path = checkpoint_path(source_path)
    if not path.exists():
        return None
    target: Path | None = None
    rename_error: OSError | None = None
    for _ in range(8):
        candidate = _kept_name(path)
        if candidate.exists():
            continue
        try:
            os.rename(path, candidate)
            target = candidate
        except FileNotFoundError as e:
            if not path.exists():
                return None  # kept aside by someone else in the meantime
            rename_error = e
        except OSError as e:
            rename_error = e
        break
    else:
        rename_error = FileExistsError("no free kept-aside name")
    if target is None:
        assert rename_error is not None
        logger.warning(
            "Could not move checkpoint %s aside (%s); copying it", path, rename_error
        )
        target = _copy_aside(path, rename_error)
        if target is None:
            return None
    logger.warning("Checkpoint %s kept aside as %s", path, target)
    _write_recovery_sidecar(target, os.path.abspath(source_path), reason)
    return target


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
    whisper_task: str = "transcribe",
    transcription_completed: bool = False,
    languages: list[str] | None = None,
) -> Path:
    """Atomically persist a checkpoint.

    Stat the source file once at write time so the resume path can
    detect a moved/edited source. Errors are propagated — callers
    log/swallow them.
    """
    import time as _time

    abs_path = os.path.abspath(source_path)
    # The identity noted at run start is authoritative: a later stat would
    # describe whatever sits at the path NOW, and media replaced mid-run
    # would then be recorded for segments that came from the original.
    identity: tuple[int, float] | None = _RUN_IDENTITY.get(abs_path)
    if identity is None:
        try:
            st = os.stat(abs_path)
            identity = (int(st.st_size), float(st.st_mtime))
            _RUN_IDENTITY[abs_path] = identity
        except OSError:
            # A transient stat blip (USB/SMB hiccup) must not blank the
            # identity: use the one on the checkpoint already on disk. Only
            # when that is missing too are the fields stored as null, and
            # then validate_checkpoint refuses the checkpoint (kept, never
            # auto-resumed) because the media cannot be verified.
            identity = _previous_identity(abs_path)
    size: int | None = identity[0] if identity else None
    mtime: float | None = identity[1] if identity else None

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
        # Add-only field: "translate" or "transcribe". A resume reuses it, so
        # a resumed job never switches task halfway through a transcript.
        "whisper_task": whisper_task,
        # Add-only field: the two languages of a mixed-language run (None =
        # one language), so a resume keeps detecting per stretch.
        "languages": list(languages) if languages else None,
        "last_end_time": float(last_end_time),
        "segment_count": len(segments),
        "segments": segments,
        "checkpoint_time": float(checkpoint_time or _time.time()),
        "transcription_completed": transcription_completed,
    }

    path = checkpoint_path(abs_path)
    # A fixed ".tmp" name let two writers for the same source (two app
    # instances resuming the same interrupted transcription) race: one
    # writer's truncate/write could land on the same inode the other was
    # mid-write into, right before its own os.replace -- producing a
    # torn final file despite the atomic rename. mkstemp's own O_EXCL
    # guarantees a name unique to this call, so concurrent writers never
    # share an inode.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            # ensure_ascii=True: a Windows path can carry lone UTF-16
            # surrogates, which UTF-8 encoding rejects — with
            # ensure_ascii=False every checkpoint write of such a run
            # raised and the transcriber disabled checkpoints for it.
            # JSON \udXXX escapes round-trip through json.load, so the
            # resume sees the same string; the file is machine-read only.
            json.dump(payload, f, ensure_ascii=True)
            _flush_to_disk(f)
        # Two writers can still legitimately race AT the rename itself
        # (two app instances resuming the same source at nearly the same
        # moment): on Windows a destination mid-replace by one thread can
        # make a concurrent os.replace() targeting the SAME path raise
        # PermissionError (WinError 5) rather than silently ordering —
        # POSIX rename has no such window. Retry a few times with a
        # short backoff before giving up; each retry's own os.replace is
        # still atomic, so the eventual winner still leaves a whole file.
        # The wait is bounded by time, not by a fixed attempt count: five
        # attempts spanning ~0.2 s ran out on a busy machine (8 racing
        # writers raised PermissionError about once in 100 rounds).
        deadline = _time.monotonic() + _REPLACE_RETRY_SECONDS
        delay = 0.005
        while True:
            try:
                os.replace(tmp, path)
                replaced = True
                break
            except PermissionError:
                if _time.monotonic() >= deadline:
                    raise
                _time.sleep(delay)
                delay = min(delay * 2, 0.1)
    finally:
        # Any exception type (a TypeError from bad segment data, a
        # KeyboardInterrupt) must leave no scratch file behind.
        if not replaced:
            try:
                os.unlink(tmp)
            except OSError:
                pass
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
    _RUN_IDENTITY.pop(os.path.abspath(source_path), None)
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
    write scratch (``<sha1>.json.<random>.tmp`` as :func:`write_checkpoint`
    names it with ``mkstemp``, and the older fixed ``*.json.tmp``) older
    than the same short window — a
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
            if name.endswith(".json.tmp") or _SCRATCH_NAME.match(name):
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
    cfg_fingerprint: str | tuple[str, ...],
) -> str:
    """Return "" if the checkpoint is usable, else a human reason.

    ``cfg_fingerprint`` is one fingerprint or the tuple of accepted ones
    (:func:`accepted_fingerprints`).

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
    # A checkpoint written during a stat blip with no known earlier identity
    # carries the verification fields as null. Matching backend/model says
    # nothing about WHICH media is at the path, so such a checkpoint is
    # refused with the unverifiable reason: the caller keeps it aside and
    # runs fresh instead of resuming onto possibly different media. A field
    # that is absent outright, or non-numeric, is refused as well.
    if "source_size" not in data:
        return "checkpoint missing source_size"
    if "source_mtime" not in data:
        return "checkpoint missing source_mtime"
    # The OLD write_checkpoint's stat-failure output was size=0/mtime=0.0 --
    # a poison pair no real file carries (a genuine 0-byte source has its
    # real mtime). It must keep refusing so an old poisoned checkpoint on
    # disk can never validate a 0-byte source.
    if data.get("source_size") == 0 and data.get("source_mtime") == 0.0:
        return f"{UNVERIFIABLE_PREFIX} (stat-failure sentinel, source_size 0)"
    if data["source_size"] is None or data["source_mtime"] is None:
        return f"{UNVERIFIABLE_PREFIX} (source size or mtime was not recorded)"
    saved_size = data["source_size"]
    try:
        if int(saved_size) != int(st.st_size):
            return "source file size has changed since checkpoint"
    except (TypeError, ValueError):
        return f"checkpoint source_size is not a number: {saved_size!r}"
    saved_mtime = data["source_mtime"]
    try:
        # Allow 1 ms slop -- filesystem mtime granularity on some
        # volumes is coarser than Python's float repr suggests.
        if abs(float(saved_mtime) - float(st.st_mtime)) > 0.001:
            return "source file mtime has changed since checkpoint"
    except (TypeError, ValueError):
        return f"checkpoint source_mtime is not a number: {saved_mtime!r}"
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
    accepted = (cfg_fingerprint,) if isinstance(cfg_fingerprint, str) else cfg_fingerprint
    if str(data.get("config_fingerprint") or "") not in accepted:
        return "transcription config changed since checkpoint"
    segs = data.get("segments")
    if not isinstance(segs, list):
        return "checkpoint segments field is not a list"
    return ""
