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
#: OmniVoice limit -- ours, to keep a single request from turning into a
#: many-minutes generation with no way to know how long it'll take. The
#: UI should chunk longer text into several calls if it ever needs to.
MAX_TEXT_CHARS = 500


def session_work_dir() -> str:
    """Per-run scratch dir for recorded reference samples and generated
    output. Mirrors ``core.live.session_work_dir``'s convention."""
    from .config import user_cache_dir

    base = user_cache_dir() / "voice_clone" / time.strftime("%Y%m%d-%H%M%S")
    return str(base)


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


def validate_reference_sample(path: str) -> "ReferenceIssue | None":
    """Check one reference clip against OmniVoice's own guidance.

    Returns None when the clip looks usable, or a :class:`ReferenceIssue`
    describing what's wrong. Never raises -- an unreadable file is
    reported as an issue, not an exception, so the tab can list several
    samples' problems at once instead of crashing on the first bad one.
    """
    if not path or not os.path.isfile(path):
        return ReferenceIssue(path, "File not found.")
    try:
        duration = get_duration(path)
    except Exception as e:  # noqa: BLE001
        return ReferenceIssue(path, f"Could not read this audio file: {e}")
    if duration <= 0:
        return ReferenceIssue(path, "Could not determine the clip's length.")
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
        )
    return None


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
) -> GenerateResult:
    """Run one zero-shot cloning generation against an already-loaded
    *model* (see :func:`load_model`). Blocking; call off the Tk thread
    (this is what ``core.voice_clone_worker`` does).

    ``reference_paths`` -- OmniVoice's own API takes a single reference
    clip; when more than one sample was recorded we concatenate them
    into a single temp WAV first (more reference speech generally helps
    similarity) rather than only ever using the first one.

    Raises whatever OmniVoice / torch raises on a real failure -- the
    worker wraps this call and turns exceptions into an ``error`` event
    rather than crashing silently.
    """
    if not text or not text.strip():
        raise ValueError("No text to speak.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {MAX_TEXT_CHARS}."
        )
    if not reference_paths:
        raise ValueError("No reference voice sample provided.")

    import soundfile as sf  # type: ignore[import-not-found] # noqa: PLC0415

    ref_path = reference_paths[0]
    if len(reference_paths) > 1:
        ref_path = _concat_references(reference_paths)

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
    t0 = time.time()
    audio = model.generate(text=text, ref_audio=ref_path, ref_text="")  # type: ignore[attr-defined]
    elapsed = time.time() - t0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio[0], 24000)
    audio_seconds = len(audio[0]) / 24000
    logger.info(
        "voice_clone generate: %.2fs audio in %.1fs (RTF=%.2f)",
        audio_seconds, elapsed, elapsed / max(audio_seconds, 0.01),
    )
    return GenerateResult(output_path=output_path, audio_seconds=audio_seconds, elapsed_seconds=elapsed)


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
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"Could not combine reference clips: {result.stderr}")
    return out_path
