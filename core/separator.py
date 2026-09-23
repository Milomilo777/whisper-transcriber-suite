"""Vocal separation pre-process — Demucs htdemucs (v0.8 Phase 2).

Some audio (noisy podcasts, songs with thick instrumentation,
phone-quality field recordings) hallucinates Whisper. Running
Demucs over the file first and feeding Whisper just the vocals
stem drops WER significantly on those inputs. Reference:
dev.to/codesugar 2026 benchmark.

Integration shape:

  * :func:`separate_vocals` takes an input audio path, runs Demucs
    if installed + enabled in config, and returns a path to the
    separated vocals WAV. If Demucs isn't installed OR the toggle
    is off, returns the input path unchanged — callers don't need
    a special "Demucs missing" code path.
  * Outputs go to ``user_cache_dir() / "demucs"`` so repeat
    transcriptions of the same source don't re-run separation.
  * Cache hit by file mtime + size + chosen model; cleared by the
    "Clear demucs cache" button in Advanced (future work).

Demucs is a heavy dependency (~150 MB model + torch ≥ 2.0). The
function is a no-op when the package isn't installed; tests
verify that fall-through.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from ._gc_import_guard import gc_disabled_import
from ._liveness_tick import liveness_tick
from .config import user_cache_dir

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "htdemucs"

#: A vocals stem at or below this many bytes cannot be a usable render
#: (demucs wrote nothing, the disk filled up, ...).  Used both when
#: accepting a cache hit and before publishing a fresh stem.
_MIN_STEM_BYTES = 1024


class SeparatorUnavailable(RuntimeError):
    """Raised when the demucs package isn't installed."""


def is_available() -> bool:
    """demucs pulls in torch, a heavy C-extension package -- see
    core/_gc_import_guard.py for why the import runs under a shared,
    process-wide GC-disable guard.

    A missing package is the documented "not installed" case, but a
    *broken* install is not: torch can fail to load a DLL (``OSError``)
    or abort initialisation (``RuntimeError``) at import time.  Those
    must degrade to "unavailable" too, otherwise ``separate_vocals``
    raises instead of handing the caller the original audio.
    """
    try:
        with gc_disabled_import():
            import demucs  # type: ignore[import-not-found] # noqa: F401
    except Exception as e:  # noqa: BLE001
        logger.debug("demucs unavailable: %s", e)
        return False
    return True


def availability_reason() -> str:
    if is_available():
        return ""
    return (
        "demucs not installed — `pip install demucs` to enable "
        "vocal-separation pre-processing."
    )


# ---------------------------------------------------------------- cache key


def _cache_key(audio_path: str, model: str) -> str:
    """Stable cache key from file size + mtime + model name.

    Hashing the file content would be correct-but-slow on multi-GB
    inputs. Size + mtime catches the common edit-then-re-transcribe
    case without paying the hash cost.
    """
    try:
        st = os.stat(audio_path)
        token = f"{audio_path}|{st.st_size}|{int(st.st_mtime)}|{model}"
    except OSError:
        token = f"{audio_path}|missing|{model}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]


def cache_dir() -> Path:
    return user_cache_dir() / "demucs"


def _cached_vocals_path(audio_path: str, model: str) -> Path:
    return cache_dir() / f"{_cache_key(audio_path, model)}_vocals.wav"


# Default cap on the demucs vocals cache. Each stem is roughly the size
# of the source audio and the cache key includes the absolute path +
# mtime, so re-encoding / moving a file makes a NEW entry — without a cap
# the cache grows to gigabytes forever. Overridable via the
# ``demucs_cache_mb`` config key (0 disables eviction).
_DEFAULT_CACHE_BUDGET_MB = 2048

# A stem written / used this recently may be mid-read by another
# concurrent worker process (the app can run several transcription
# workers at once), so it is never evicted even when the budget is
# exceeded. Cache hits refresh mtime, making this a use-based grace.
_CACHE_IN_USE_GRACE_S = 300


def _cache_budget_mb() -> int:
    try:
        from .config import load_config
        return max(0, int(load_config().get("demucs_cache_mb", _DEFAULT_CACHE_BUDGET_MB)))
    except Exception:  # noqa: BLE001
        return _DEFAULT_CACHE_BUDGET_MB


def prune_cache(budget_mb: int | None = None, *, keep: str | None = None) -> int:
    """Evict oldest ``*_vocals.wav`` until the cache is under the byte budget.

    Returns the number of files removed. ``keep`` is a path that must
    never be evicted (the stem we just wrote). Stems written or used
    within the last ``_CACHE_IN_USE_GRACE_S`` seconds are kept too --
    another worker may be mid-read. A budget <= 0 disables eviction.
    Never raises — a sweep failure must not break separation.
    """
    budget = _cache_budget_mb() if budget_mb is None else max(0, budget_mb)
    if budget <= 0:
        return 0
    try:
        # Resolving the directory can itself fail (user_cache_dir() on a
        # read-only / unresolvable home — the exact trigger fixed at the
        # entry points), so it must sit inside the same guard as the glob
        # it feeds: the docstring promises this sweep never raises.
        d = cache_dir()
        files = [p for p in d.glob("*_vocals.wav") if p.is_file()]
    except Exception:  # noqa: BLE001
        return 0
    def _mtime_or_zero(p: Path) -> float:
        # A concurrent worker may delete a stem mid-sort; a single
        # vanishing file must not abort the whole sweep.
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    try:
        files.sort(key=_mtime_or_zero, reverse=True)  # newest first
    except OSError:
        return 0
    budget_bytes = budget * 1024 * 1024
    keep_norm = os.path.normcase(os.path.abspath(keep)) if keep else None
    now = time.time()
    total = 0
    removed = 0
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        size = st.st_size
        is_keeper = bool(keep_norm) and os.path.normcase(os.path.abspath(str(p))) == keep_norm
        in_use = (now - st.st_mtime) < _CACHE_IN_USE_GRACE_S
        if total + size <= budget_bytes or is_keeper or in_use:
            total += size
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def clear_cache() -> None:
    """Remove the entire demucs cache directory. Never raises."""
    try:
        # ignore_errors covers rmtree's own failures, not cache_dir()
        # raising before the call — an unresolvable user_cache_dir()
        # must not escape this contract either.
        shutil.rmtree(cache_dir(), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- entry point


def _notify(log: Callable[[str], None] | None, message: str) -> None:
    """Deliver ``message`` without letting a dead callback escape.

    ``separate_vocals`` promises never to raise so the caller still gets
    a transcript; a UI callback that dies (widget torn down, queue full)
    at either chokepoint -- the demucs-unavailable log before the
    fallback wrapper, or the wrapper's own fallback log -- would break
    that promise, so those two calls are guarded.  Every other log call
    sits inside the wrapper and is absorbed by this same guard.
    """
    if not log:
        return
    try:
        log(message)
    except Exception:  # noqa: BLE001
        logger.exception("separator log callback failed")


def separate_vocals(
    audio_path: str,
    *,
    model: str = DEFAULT_MODEL,
    enabled: bool = True,
    log: Callable[[str], None] | None = None,
) -> str:
    """Return path to a vocals-only WAV for the input.

    Behaviour matrix:
      * ``enabled=False``                       → return ``audio_path``
      * ``demucs`` not installed                → return ``audio_path``
        + log a one-line "skipped: demucs missing" warning
      * cache hit                               → return cached path
      * cache miss → run demucs → return new   → return separated path

    Never raises on demucs-runtime issues; falls back to the
    untouched input so the user still gets a transcript.
    """
    if not enabled:
        return audio_path
    if not is_available():
        _notify(log, f"Demucs skipped: {availability_reason()}")
        return audio_path
    try:
        return _separate_vocals_inner(audio_path, model=model, log=log)
    except Exception as e:  # noqa: BLE001
        # Belt and braces, mirroring denoise_audio(): a filesystem error
        # before or during the cache work -- a full / read-only cache
        # volume, or a user_cache_dir() that cannot resolve (it is hit
        # first, inside _cached_vocals_path) -- must not take the
        # caller's transcription down with it.
        logger.exception("Demucs pre-process failed: %s", e)
        _notify(log, f"Demucs failed ({e}); falling back to original audio.")
        return audio_path


def _separate_vocals_inner(
    audio_path: str,
    *,
    model: str,
    log: Callable[[str], None] | None,
) -> str:
    """Separate + cache. Raises on runtime failure; the caller falls back."""
    cached = _cached_vocals_path(audio_path, model)
    hit = False
    try:
        hit = cached.exists() and cached.stat().st_size > _MIN_STEM_BYTES
    except OSError:
        # A concurrent prune removed the stem between exists() and
        # stat() -- treat as a miss and regenerate it.
        hit = False
    if hit:
        # Count the hit as use: refresh mtime so LRU eviction and
        # the in-use grace period treat this stem as active.
        try:
            os.utime(cached, None)
        except OSError:
            pass
        if log:
            log(f"Demucs cache hit → {cached}")
        return str(cached)

    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        out_dir = Path(tempfile.mkdtemp(prefix="demucs_", dir=str(cache_dir())))
    except OSError as e:
        # Stems are roughly the size of the source, so a full or read-only
        # cache volume is a realistic failure.  This setup used to run
        # before the guard below, letting its OSError escape the
        # documented "always hand the caller the original audio" fallback
        # and take the transcription down with it.
        logger.exception("Demucs cache setup failed: %s — using original audio", e)
        if log:
            log(f"Demucs failed ({e}); falling back to original audio.")
        return audio_path

    # Wrap the whole post-mkdtemp section in try/finally so the
    # temp out_dir tree (htdemucs/<stem>/{vocals,no_vocals}.wav) is
    # always removed on the success path too — previously only the
    # one vocals.wav was moved into the cache and the rest of the
    # tree (~30-50 MB per run) leaked under the cache dir forever.
    try:
        try:
            _run_demucs_cli(audio_path, out_dir, model=model, log=log)
        except Exception as e:  # noqa: BLE001
            logger.exception("Demucs run failed: %s — using original audio", e)
            if log:
                log(f"Demucs failed ({e}); falling back to original audio.")
            return audio_path

        # Demucs writes to ``{out_dir}/{model}/{stem_name}/vocals.wav`` —
        # locate it. Some Demucs versions vary the layout; recursively
        # search for a vocals.wav inside out_dir as a robust fallback.
        found = _find_vocals_in(out_dir)
        if found is None:
            if log:
                log("Demucs produced no vocals.wav; using original audio.")
            return audio_path

        # demucs can exit 0 having written a truncated/empty stem (disk
        # full, killed decode).  The cache-hit path already rejects such
        # files; reject them here too instead of publishing a degenerate
        # stem this run and handing its path to the transcriber.
        try:
            stem_size = found.stat().st_size
        except OSError:
            stem_size = 0
        if stem_size <= _MIN_STEM_BYTES:
            if log:
                log("Demucs produced a degenerate vocals stem; "
                    "using original audio.")
            return audio_path

        try:
            os.replace(str(found), str(cached))
        except OSError:
            # Cross-drive replace can fail; fall back to copy+remove --
            # but copy into a staging file and rename into place.
            # copyfile() writes non-atomically, and a truncated file
            # left on the published cache path would satisfy the
            # size-only cache-hit check on every future run, serving a
            # corrupt stem to the transcriber until the cache happened
            # to evict it (denoise's staging pattern, same reason).
            staging: str | None = None
            try:
                fd, staging = tempfile.mkstemp(
                    prefix="demucs_stem_", suffix=".part",
                    dir=str(cache_dir()),
                )
                os.close(fd)
                shutil.copyfile(str(found), staging)
                os.replace(staging, str(cached))
                staging = None
            except OSError as e:
                if log:
                    log(f"Could not cache vocals stem: {e}")
                # Caller needs the stem on disk, but finally: sweeps
                # out_dir -- move a copy out of the tree first. If
                # even that fails, hand back the untouched input
                # (module contract) rather than a path inside the
                # tree the finally: below is about to delete.
                # Keyed per-source orphan name (not bare "vocals.wav"):
                # unique across concurrent sources, and matches the
                # "*_vocals.wav" prune glob so it is evicted normally
                # instead of leaking in the cache dir forever.
                survivor = cache_dir() / f"{_cache_key(audio_path, model)}_orphan_vocals.wav"
                try:
                    shutil.copyfile(str(found), str(survivor))
                except OSError:
                    if log:
                        log("Could not keep vocals stem; using original audio.")
                    return audio_path
                return str(survivor)
            finally:
                # After a successful publish the staging path is gone
                # and this is a no-op; after a mid-copy failure it is
                # the only remnant, and it never matches the hit path.
                if staging is not None:
                    try:
                        os.unlink(staging)
                    except OSError:
                        pass
        if log:
            log(f"Demucs vocals → {cached}")
        # Bound the cache: evict oldest stems beyond the budget, never
        # the one we just wrote.
        try:
            evicted = prune_cache(keep=str(cached))
            if evicted and log:
                log(f"Demucs cache pruned: removed {evicted} old stem(s).")
        except Exception:  # noqa: BLE001
            pass
        return str(cached)
    finally:
        # Always sweep the temp tree, success or failure. Cache
        # itself keeps the moved vocals.wav (P1-5).
        shutil.rmtree(out_dir, ignore_errors=True)


def _find_vocals_in(directory: Path) -> Path | None:
    for p in directory.rglob("vocals.wav"):
        return p
    return None


def _run_demucs_cli(
    audio_path: str,
    out_dir: Path,
    *,
    model: str,
    log: Callable[[str], None] | None = None,
) -> None:
    """Invoke demucs via its CLI entry point.

    The Python API also works but the CLI is simpler to call and
    is stable across demucs releases.
    """
    cmd = [
        # sys.executable, not bare "python": the frozen/embed build has no
        # "python" on PATH, so the bare name raised FileNotFoundError and
        # silently killed vocal separation.
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", model,
        "-o", str(out_dir),
        audio_path,
    ]
    if log:
        log(f"Running demucs: {' '.join(cmd)}")
    kwargs: dict[str, object] = {
        "check": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 600,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    # The demucs CLI emits its own progress bar to stderr but we
    # capture stderr (PIPE) so the worker stdout sees nothing until
    # demucs exits. Wrap the blocking subprocess.run in a liveness
    # tick so the parent watchdog stays quiet on multi-minute
    # separations on slow CPUs.
    with liveness_tick(log, "Demucs separation"):
        subprocess.run(cmd, **kwargs)  # type: ignore[arg-type]
