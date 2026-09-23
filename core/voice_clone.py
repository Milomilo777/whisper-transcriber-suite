"""Clone Your Voice / Text to Voice — zero-shot voice cloning TTS.

Fully independent of the transcription pipeline: no other module in
``core/`` or ``app/`` imports this one, and nothing here is imported by
the transcription path. The feature is off by default (see
``core.hub.voice_clone_tab_enabled``) and its model is downloaded on
demand (see ``core.optional_deps``, feature ``"voice_clone"``) the
first time it is actually used — never bundled, never fetched just
because the tab exists.

Engine: OmniVoice (k2-fsa), chosen after evaluating it against
Chatterbox Multilingual and the flagship engines of a comparable
open-source project (see docs/SESSION_HANDOFF_NEXT.md, 2026-09-12
entry, for the full evaluation and why). Apache-2.0 on both code and
weights, ~0.6B params, CPU-capable but slow (measured ~50-57x slower
than real-time on a representative consumer CPU) — callers MUST show a
time estimate before generating, never a bare progress spinner.

This module is Tk-free and subprocess-free: it does the actual model
work. ``core.voice_clone_worker`` wraps it in the stdin/stdout JSON
protocol a background process speaks; ``app.services.voice_clone_service``
is the parent-side client of that worker.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import optional_deps
from .transcriber import get_duration

logger = logging.getLogger(__name__)

FEATURE = "voice_clone"

#: OmniVoice's own recommended reference-clip length. Outside this range
#: the model still runs, but quality degrades (too short: not enough
#: voice to clone; too long: the model truncates it anyway).
MIN_REFERENCE_SECONDS = 3.0
MAX_REFERENCE_SECONDS = 10.0
MAX_REFERENCE_SAMPLES = 3

#: Sanity cap on how much text one generation call accepts. Not an
#: OmniVoice limit: OmniVoice splits long text into ~15 s chunks itself
#: (``audio_chunk_duration``) and cross-fades them. Raised from 500
#: (owner request, 2026-09-23); the tab shows a time estimate first,
#: since on a CPU this much text takes hours.
MAX_TEXT_CHARS = 5000

#: OmniVoice voice-design attributes (omnivoice/utils/voice_design.py).
#: One value per group, all optional; joined with ", " into ``instruct``.
DESIGN_GENDERS = ("male", "female")
DESIGN_AGES = ("child", "teenager", "young adult", "middle-aged", "elderly")
DESIGN_PITCHES = ("very low pitch", "low pitch", "moderate pitch", "high pitch",
                  "very high pitch")
DESIGN_ACCENTS = ("american accent", "british accent", "australian accent",
                  "canadian accent", "indian accent", "chinese accent",
                  "korean accent", "japanese accent", "portuguese accent",
                  "russian accent")


def build_instruct(*parts: "str | None", whisper: bool = False) -> str:
    """Voice-design instruct from the picked attributes ("" = none)."""
    tags = [p for p in parts if p]
    if whisper:
        tags.append("whisper")
    return ", ".join(tags)


def session_work_dir() -> str:
    """Per-run scratch dir for recorded reference samples and generated
    output. Mirrors ``core.live.session_work_dir``'s convention."""
    from .config import user_cache_dir

    base = user_cache_dir() / "voice_clone" / time.strftime("%Y%m%d-%H%M%S")
    return str(base)


#: Session scratch dirs (see session_work_dir above) older than this are
#: swept on tab build -- mirrors the app's own aged-out partials sweep
#: for the transcription queue. Generous on purpose: a bound on
#: unattended growth, not a "your last take is gone" trap for someone
#: who steps away and comes back the next day.
SCRATCH_MAX_AGE_DAYS = 7.0


def sweep_old_session_dirs(max_age_days: float = SCRATCH_MAX_AGE_DAYS) -> None:
    """Remove voice_clone scratch dirs (see :func:`session_work_dir`)
    older than *max_age_days*. Best-effort; never raises -- nothing else
    in this feature ever cleans these up, so every recorded reference
    clip and generated output would otherwise accumulate forever.
    """
    import shutil

    from .config import user_cache_dir

    root = user_cache_dir() / "voice_clone"
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    cutoff = time.time() - max_age_days * 86400
    for entry in entries:
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def default_device() -> str:
    """Best-effort "cuda" when a usable NVIDIA GPU is visible to torch,
    else "cpu". Independent of ``core.hardware``'s CUDA probes -- those
    are ctranslate2-specific (the Whisper backend's own runtime), a
    different binding with different requirements than plain torch.
    Never raises; only meaningful once the feature is installed
    (before that, torch may not even be importable, so this returns
    "cpu" -- callers should still check :func:`is_available` first).
    """
    try:
        import torch  # type: ignore[import-not-found] # noqa: PLC0415
        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def is_available() -> bool:
    """True iff the OmniVoice package is importable (bundled or already
    installed on demand). Never raises."""
    return optional_deps.is_available(FEATURE)


def ensure_installed(
    log_cb: "Callable[[str], None] | None" = None,
    cancel_event: object | None = None,
) -> bool:
    """Install OmniVoice + deps on demand if not already available.

    Thin wrapper over ``optional_deps.install`` so callers (the tab, the
    worker) don't need to know the feature key. Returns True once the
    package actually imports.
    """
    if is_available():
        return True
    return optional_deps.install(FEATURE, log_cb=log_cb, cancel_event=cancel_event)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ReferenceIssue:
    path: str
    message: str
    blocking: bool = False
    #: True only for the "too long" case -- the one issue this module
    #: knows how to fix automatically (see :func:`trim_reference_sample`).
    #: "Too short" has no such fix (nothing to invent), so it stays False.
    too_long: bool = False


def validate_reference_sample(path: str) -> "ReferenceIssue | None":
    """Check one reference clip against OmniVoice's own guidance.

    Returns None when the clip looks usable, or a :class:`ReferenceIssue`
    describing what's wrong. Never raises -- an unreadable file is
    reported as an issue, not an exception, so the tab can list several
    samples' problems at once instead of crashing on the first bad one.
    """
    if not path or not os.path.isfile(path):
        return ReferenceIssue(path, "File not found.", blocking=True)
    try:
        duration = get_duration(path)
    except Exception as e:  # noqa: BLE001
        return ReferenceIssue(path, f"Could not read this audio file: {e}", blocking=True)
    if duration <= 0:
        return ReferenceIssue(path, "Could not determine the clip's length.", blocking=True)
    if duration < MIN_REFERENCE_SECONDS:
        return ReferenceIssue(
            path,
            f"Too short ({duration:.1f}s) -- OmniVoice wants at least "
            f"{MIN_REFERENCE_SECONDS:.0f}s of clear speech.",
        )
    if duration > MAX_REFERENCE_SECONDS:
        return ReferenceIssue(
            path,
            f"Too long ({duration:.1f}s) -- clips over "
            f"{MAX_REFERENCE_SECONDS:.0f}s are truncated by the model "
            "anyway; trim it for a more predictable result.",
            too_long=True,
        )
    return None


def trim_reference_sample(
    path: str, output_path: str, max_seconds: float = MAX_REFERENCE_SECONDS,
) -> None:
    """Cut *path* down to its first *max_seconds* seconds via the bundled
    ffmpeg, writing the result to *output_path*.

    Used instead of relying on OmniVoice's own undocumented internal
    truncation for an over-length reference clip: this makes the cut
    explicit and predictable (always the START of the clip) rather than
    leaving it up to whatever the model does internally with the excess
    audio. Raises ``RuntimeError`` on ffmpeg failure; never leaves a
    partial ``output_path`` behind on failure.
    """
    import subprocess
    import tempfile

    from . import _proc
    from .paths import bundled_binary

    ffmpeg = bundled_binary("ffmpeg")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_out = tempfile.mkstemp(
        suffix=os.path.splitext(output_path)[1] or ".wav",
        dir=os.path.dirname(output_path) or None,
    )
    os.close(fd)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-t", str(max_seconds), "-c", "copy", tmp_out]
    kwargs: dict = {"capture_output": True, "text": True, "timeout": 60}
    kwargs.update(_proc.new_session_kwargs())
    try:
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0 or not os.path.isfile(tmp_out):
            raise RuntimeError(f"Could not trim reference clip: {result.stderr}")
        os.replace(tmp_out, output_path)
    except Exception:
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        raise


@dataclass
class GenerateResult:
    output_path: str
    audio_seconds: float
    elapsed_seconds: float


# Process-local cache: loading OmniVoice takes minutes (mostly the
# first-run download + weight deserialisation), so a worker process that
# generates several clips in one session must not pay that cost again
# for every call. Keyed by device so a "cpu" and a "cuda:0" load can
# coexist if a caller ever switches mid-session (not expected in
# practice, but cheap to allow correctly rather than silently ignore).
_model_cache: dict[str, object] = {}


def load_model(device: str = "cpu") -> object:
    """Load (or return the cached) OmniVoice model for *device*.

    Call once per worker process; :func:`generate` takes the result so
    repeated calls in the same process reuse it. Raises whatever
    OmniVoice / torch raises on a real failure.
    """
    cached = _model_cache.get(device)
    if cached is not None:
        return cached
    optional_deps.activate()
    import torch  # type: ignore[import-not-found] # noqa: PLC0415
    from omnivoice import OmniVoice  # type: ignore[import-not-found] # noqa: PLC0415

    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice", device_map=device, dtype=torch.float32,
    )
    _model_cache[device] = model
    return model


def generate(
    model: object,
    text: str,
    reference_paths: "list[str]",
    output_path: str,
    *,
    consent_accepted: bool,
    instruct: "str | None" = None,
    language: "str | None" = None,
    speed: "float | None" = None,
) -> GenerateResult:
    """Run one generation against an already-loaded *model* (see
    :func:`load_model`). Blocking; call off the Tk thread (this is what
    ``core.voice_clone_worker`` does).

    OmniVoice's three modes: with ``reference_paths`` it clones that
    voice (consent required); otherwise ``instruct`` designs a voice from
    attributes (see :func:`build_instruct`), and with neither the model
    picks a voice itself. ``language`` (name or code) and ``speed`` are
    optional in every mode.

    ``reference_paths`` -- OmniVoice's own API takes a single reference
    clip; when more than one sample was recorded we concatenate them
    into a single temp WAV first (more reference speech generally helps
    similarity) rather than only ever using the first one.

    Raises whatever OmniVoice / torch raises on a real failure -- the
    worker wraps this call and turns exceptions into an ``error`` event
    rather than crashing silently.
    """
    if reference_paths and not consent_accepted:
        raise ValueError("Consent not accepted; refusing to generate.")
    if not text or not text.strip():
        raise ValueError("No text to speak.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {MAX_TEXT_CHARS}."
        )
    import soundfile as sf  # type: ignore[import-not-found] # noqa: PLC0415

    options: dict[str, object] = {}
    if language:
        options["language"] = language
    if speed and abs(speed - 1.0) > 1e-3:
        options["speed"] = float(speed)

    ref_path = reference_paths[0] if reference_paths else None
    cleanup_ref_path: str | None = None
    if len(reference_paths) > 1:
        ref_path = _concat_references(reference_paths)
        cleanup_ref_path = ref_path

    # ref_text="" opts out of OmniVoice's own auto-transcription of the
    # reference clip (an internal, separate transformers-based Whisper
    # model it would otherwise load just for this). We don't have a real
    # transcript of the reference audio to offer instead -- reusing this
    # app's own configured model would mean loading a SECOND heavy model
    # in this same process, working against the memory problem rather
    # than solving it. Cuts a real, measured OOM risk on a representative
    # 17GB machine (see docs/SESSION_HANDOFF_NEXT.md, 2026-09-12 entry)
    # at some cost to cloning quality; revisit if that trade proves wrong
    # in practice.
    try:
        t0 = time.time()
        if ref_path is not None:
            audio = model.generate(text=text, ref_audio=ref_path, ref_text="", **options)  # type: ignore[attr-defined]
        elif instruct:
            audio = model.generate(text=text, instruct=instruct, **options)  # type: ignore[attr-defined]
        else:
            audio = model.generate(text=text, **options)  # type: ignore[attr-defined]
        elapsed = time.time() - t0

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, audio[0], 24000)
        audio_seconds = len(audio[0]) / 24000
        logger.info(
            "voice_clone generate: %.2fs audio in %.1fs (RTF=%.2f)",
            audio_seconds, elapsed, elapsed / max(audio_seconds, 0.01),
        )
        return GenerateResult(output_path=output_path, audio_seconds=audio_seconds, elapsed_seconds=elapsed)
    finally:
        if cleanup_ref_path is not None:
            try:
                os.remove(cleanup_ref_path)
            except OSError:
                pass


def _concat_references(paths: "list[str]") -> str:
    """Concatenate up to MAX_REFERENCE_SAMPLES reference clips into one
    temp WAV via the bundled ffmpeg, so OmniVoice's single-reference API
    gets the benefit of every sample the user recorded."""
    import tempfile

    from .paths import bundled_binary  # noqa: PLC0415
    from . import _proc  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    ffmpeg = bundled_binary("ffmpeg")
    fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="voice_clone_ref_")
    os.close(fd)
    cmd = [ffmpeg, "-y", "-v", "error"]
    for p in paths[:MAX_REFERENCE_SAMPLES]:
        cmd += ["-i", p]
    n = min(len(paths), MAX_REFERENCE_SAMPLES)
    cmd += ["-filter_complex", f"concat=n={n}:v=0:a=1", out_path]
    kwargs: dict = {"capture_output": True, "text": True, "timeout": 60}
    kwargs.update(_proc.new_session_kwargs())
    try:
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0 or not os.path.isfile(out_path):
            raise RuntimeError(f"Could not combine reference clips: {result.stderr}")
    except Exception:
        # mkstemp already created out_path on disk before ffmpeg ever ran;
        # generate()'s own cleanup only knows about a path this function
        # RETURNS, so a failure here (non-zero ffmpeg exit, or the 60s
        # subprocess timeout above) would otherwise leak that temp file.
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    return out_path
