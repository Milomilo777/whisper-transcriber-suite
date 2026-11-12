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
open-source project. Apache-2.0 on both code and
weights, ~0.6B params, CPU-capable but slow: on a 4-core / 8-thread
desktop CPU a pass of 5-10 s of speech took 18-21x its length, and no
pass took less than about 80 s, however short the text — callers MUST
show a time estimate before generating (``core.tts_plan``), never a bare
progress spinner.

This module is Tk-free and subprocess-free: it does the actual model
work. ``core.voice_clone_worker`` wraps it in the stdin/stdout JSON
protocol a background process speaks; ``app.services.voice_clone_service``
is the parent-side client of that worker.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from . import optional_deps, synthetic_audio
from .transcriber import get_duration, require_audio_stream
# The length limits shared by both engines; MAX_TEXT_CHARS is re-exported
# under its old name. One generate() call is one pass (MAX_PASS_CHARS).
from .tts_plan import MAX_PASS_CHARS as MAX_PASS_CHARS
from .tts_plan import MAX_TEXT_CHARS as MAX_TEXT_CHARS

logger = logging.getLogger(__name__)

FEATURE = "voice_clone"

#: OmniVoice's own recommended reference-clip length. Outside this range
#: the model still runs, but quality/speed may degrade (too short: not enough
#: voice to clone; too long: a less predictable reference prompt).
MIN_REFERENCE_SECONDS = 3.0
MAX_REFERENCE_SECONDS = 10.0
MAX_REFERENCE_SAMPLES = 3

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
    import tempfile

    from .config import user_cache_dir

    # A new folder for every call: two runs in the same second (two
    # windows, or Record and Generate) never share one output.wav. The
    # sweep below goes by the folder's age, not its name.
    root = user_cache_dir() / "voice_clone"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S") + "-", dir=root)


#: Session scratch dirs (see session_work_dir above) older than this are
#: swept on tab build -- mirrors the app's own aged-out partials sweep
#: for the transcription queue. Generous on purpose: a bound on
#: unattended growth, not a "your last take is gone" trap for someone
#: who steps away and comes back the next day.
SCRATCH_MAX_AGE_DAYS = 7.0

# Original sessions had only a timestamp; mkdtemp adds eight random characters.
_SCRATCH_DIR_NAME = re.compile(
    r"(?:[0-9]{8}-[0-9]{6}(?:-[a-z0-9_]{8})?|job-[0-9a-f]{16}|\.sweep-[0-9a-f]{32})"
)


def _scratch_dir_stat(path: Path) -> os.stat_result | None:
    """Inspect the entry itself, never a symlink or Windows reparse point."""
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        return None
    return info


def sweep_old_session_dirs(max_age_days: float = SCRATCH_MAX_AGE_DAYS) -> None:
    """Remove voice_clone scratch dirs (see :func:`session_work_dir`)
    older than *max_age_days*. Best-effort; never raises -- nothing else
    in this feature ever cleans these up, so every recorded reference
    clip and generated output would otherwise accumulate forever.

    The folder of an unfinished long job (``core.tts_job``) is kept for
    ``tts_job.UNFINISHED_MAX_AGE_DAYS`` after its last finished piece, so
    a job someone continues now and then is never swept from under them.
    Only recognised scratch names are eligible; held job locks, symlinks
    and Windows junctions are left alone. Cleanup retains the stable lock file
    and its directory. Legacy folders receive a lock and a full retention
    period before deletion is attempted.
    """
    import shutil

    from . import tts_job
    from .config import user_cache_dir

    root = user_cache_dir() / "voice_clone"
    try:
        if _scratch_dir_stat(root) is None:
            return
        entries = list(root.iterdir())
    except OSError:
        return
    now = time.time()
    cutoff = now - max_age_days * 86400
    unfinished_cutoff = now - max(max_age_days, tts_job.UNFINISHED_MAX_AGE_DAYS) * 86400
    for entry in entries:
        try:
            if _SCRATCH_DIR_NAME.fullmatch(entry.name) is None:
                continue
            info = _scratch_dir_stat(entry)
            if info is None:
                continue
            last = info.st_mtime
            limit = cutoff
            if tts_job.is_unfinished_job_dir(entry):
                progress = entry / tts_job.PARTS_DIR / tts_job.PROGRESS_FILE
                last = max(last, progress.stat().st_mtime)
                limit = unfinished_cutoff
            if last >= limit:
                continue
            # Share the job's OS lock before touching any saved work.
            lock_path = entry / tts_job.LOCK_FILE
            try:
                lock_info = lock_path.lstat()
            except FileNotFoundError:
                # Establish a stable lock inode, but never delete work on the
                # pass that creates it: its mtime cannot distinguish our own
                # creation from another process refreshing the folder.
                lock = tts_job._JobLock(lock_path)
                try:
                    lock.acquire()
                except tts_job.JobBusy:
                    continue
                lock.release()
                continue
            if (not stat.S_ISREG(lock_info.st_mode)
                    or getattr(lock_info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or lock_info.st_mtime >= limit):
                continue
            lock = tts_job._JobLock(lock_path)
            try:
                lock.acquire()
            except tts_job.JobBusy:
                continue
            try:
                # Recheck the entry and progress after obtaining exclusive use.
                current_info = _scratch_dir_stat(entry)
                if (current_info is None or current_info.st_ino != info.st_ino
                        or current_info.st_dev != info.st_dev):
                    continue
                if current_info.st_mtime >= limit:
                    continue
                if tts_job.is_unfinished_job_dir(entry):
                    progress = entry / tts_job.PARTS_DIR / tts_job.PROGRESS_FILE
                    if progress.stat().st_mtime >= unfinished_cutoff:
                        continue
                # Check descendants without following reparse points. Recent
                # file writes need not update the session directory's mtime.
                children = []
                pending = [entry]
                safe = True
                while pending and safe:
                    for child in pending.pop().iterdir():
                        child_info = child.lstat()
                        if (stat.S_ISLNK(child_info.st_mode) or
                                getattr(child_info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                            safe = False
                            break
                        if child_info.st_mtime >= limit:
                            safe = False
                            break
                        if child.parent == entry and child != lock_path:
                            children.append(child)
                        if stat.S_ISDIR(child_info.st_mode):
                            pending.append(child)
                if not safe:
                    continue
                # Delete only while holding the job's stable lock. Never
                # unlink it or rename the directory, even after release.
                for child in children:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            finally:
                lock.release()
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
        try:
            require_audio_stream(path)
        except RuntimeError:
            return ReferenceIssue(
                path, "This reference file has no audio track.", blocking=True,
            )
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
            f"{MAX_REFERENCE_SECONDS:.0f}s exceed the recommended reference "
            "length; trim it for more predictable speed and quality.",
            too_long=True,
        )
    return None


def trim_reference_sample(
    path: str, output_path: str, max_seconds: float = MAX_REFERENCE_SECONDS,
) -> None:
    """Cut *path* down to its first *max_seconds* seconds via the bundled
    ffmpeg, writing decoded PCM audio to a WAV *output_path*.

    The optional UI trim makes the cut explicit and predictable (always
    the START of the clip). Generation preserves the supplied reference
    clips, including their full combined length. Raises ``RuntimeError``
    on ffmpeg failure; never leaves a partial ``output_path`` on failure.
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
    # Decode reference audio: stream-copy retains whole packets past the limit
    # and can put compressed audio inside the .wav that the tab expects.
    cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-t", str(max_seconds), "-c:a", "pcm_s16le", tmp_out]
    kwargs: dict = {
        **_UTF8, "stdin": subprocess.DEVNULL, "capture_output": True, "text": True, "timeout": 60,
    }
    kwargs.update(_proc.new_session_kwargs())
    try:
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0 or not os.path.isfile(tmp_out):
            raise RuntimeError(f"Could not trim reference clip: {result.stderr}")
        from core import _checkpoint
        with open(tmp_out, "r+b") as f:
            _checkpoint._flush_to_disk(f)
        os.replace(tmp_out, output_path)
    except Exception:
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        raise


#: ffmpeg writes UTF-8; the locale default (cp1252 on Windows) fails on
#: the bytes of a Persian file name and loses the whole error text.
_UTF8 = {"encoding": "utf-8", "errors": "replace"}

#: OmniVoice's output rate when the model does not say (its README: 24 kHz).
DEFAULT_SAMPLE_RATE = 24000


@dataclass
class GenerateResult:
    output_path: str
    audio_seconds: float
    elapsed_seconds: float
    #: Non-fatal problem to show the user ("" = none), e.g. the local
    #: consent record could not be written.
    warning: str = ""


# Process-local cache: loading OmniVoice takes minutes (mostly the
# first-run download + weight deserialisation), so a worker process that
# generates several clips in one session must not pay that cost again
# for every call. Keyed by device so a "cpu" and a "cuda:0" load can
# coexist if a caller ever switches mid-session (not expected in
# practice, but cheap to allow correctly rather than silently ignore).
_model_cache: dict[str, object] = {}

# Keep only text, never an ASR/model object or reference file. Hash the frozen
# audio bytes so overwriting a recorded sample cannot reuse its old transcript.
_reference_text_cache: dict[str, str] = {}
_REFERENCE_TEXT_CACHE_SIZE = 8


@dataclass(frozen=True)
class PreparedReference:
    path: str
    text: str
    source_paths: tuple[str, ...]


def release_models() -> None:
    """Drop worker-owned OmniVoice models before reference ASR allocation.

    Callers must first release their own model references. The worker keeps
    models only in this cache between commands, including failed commands.
    """
    import gc

    _model_cache.clear()
    gc.collect()


def _local_reference_models(settings: dict[str, Any]) -> Iterator[str]:
    """Find complete local candidates without resolving/downloading Hub IDs."""
    from . import hub, model_manager

    catalog = [slug for slug, _ in model_manager.catalog_models(settings)]
    selected = settings.get("model") or {}
    name = selected.get("name", "") if isinstance(selected, dict) else ""
    selected_slug = str(name)
    for slug in catalog:
        entry = model_manager.catalog_resolve_entry(settings, slug)
        if entry and name in (slug, entry["name"]):
            selected_slug = slug
            break
    candidates: list[Path] = []
    configured = settings.get("model_path")
    if configured and model_manager.is_english_only(settings, selected_slug) is not True:
        # A custom name is not evidence of multilingual support. The loaded
        # CTranslate2 model's own flag is checked before transcription below.
        candidates.append(Path(str(configured)))
    hub_folder = settings.get("hub_folder") or str(hub.default_hub_folder())
    preferred = ["small", "base", "tiny",
                 model_manager.multilingual_counterpart(settings, selected_slug)]
    for slug in [selected_slug, *preferred, *catalog]:
        if model_manager.is_english_only(settings, slug) is not False:
            continue
        entry = model_manager.catalog_resolve_entry(settings, slug)
        if entry:
            candidates.append(hub.model_folder_for(hub_folder, entry["name"]))
    seen: set[str] = set()
    for path in candidates:
        identity = os.path.normcase(os.path.abspath(path))
        if identity in seen:
            continue
        seen.add(identity)
        try:
            complete = hub.model_weights_present(path) and all(
                (path / filename).is_file() and (path / filename).stat().st_size > 0
                for filename in ("config.json", "tokenizer.json")
            )
        except OSError:
            complete = False
        if complete:
            yield str(path.resolve())


def _transcribe_reference(path: str) -> str:
    """Consume local multilingual faster-whisper completely, then release it."""
    import gc

    from .config import load_config

    candidates = list(_local_reference_models(load_config(fetch_online=False)))
    missing = (
        "Voice cloning needs an already installed local multilingual Whisper "
        "model, including its config and tokenizer. Select an existing local "
        "multilingual model in Settings or install one in Models, then retry. "
        "Reference preparation never downloads a model."
    )
    if not candidates:
        raise RuntimeError(missing)
    from faster_whisper import WhisperModel  # noqa: PLC0415

    failures: list[str] = []
    for candidate in candidates:
        model = None
        segments = None
        text = None
        try:
            # Supplying a complete local directory also avoids the tokenizer's
            # pretrained-name fallback, which otherwise can access the network.
            model = WhisperModel(candidate, device="cpu", compute_type="int8", local_files_only=True)
            if getattr(model.model, "is_multilingual", None) is not True:
                raise RuntimeError("The local reference ASR model is not multilingual.")
            segments, _ = model.transcribe(
                path, language=None, task="transcribe", beam_size=5,
                vad_filter=True, condition_on_previous_text=False,
            )
            # faster-whisper returns a lazy iterator; decoding and its possible
            # errors occur here, while the ASR model is still alive.
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:  # noqa: BLE001 -- try another already-local model
            failures.append(str(error))
        finally:
            segments = None
            model = None
            gc.collect()
        if text is not None:
            if not text:
                # No speech is an input failure, not a reason to try every model.
                raise RuntimeError("No speech was recognized in the reference audio. Record clear speech and retry.")
            return text
    raise RuntimeError(f"{missing} Local model error: {'; '.join(failures)}")


@contextmanager
def prepare_reference(
    reference_paths: list[str], *, consent_accepted: bool,
    scratch_dir: str | None = None,
) -> Iterator[PreparedReference | None]:
    """Freeze ordered audio and obtain its text BEFORE loading OmniVoice.

    The returned reference is valid only inside this context. A new reference
    unloads cached TTS before ASR; unchanged audio reuses a bounded text cache.
    No-reference/design requests never inspect config or allocate an ASR model.
    """
    if not reference_paths:
        yield None
        return
    if not consent_accepted:
        raise ValueError("Consent not accepted; refusing to generate.")
    from . import tts_job
    from .config import user_cache_dir

    sources = reference_paths[:MAX_REFERENCE_SAMPLES]
    folder = Path(scratch_dir if scratch_dir is not None else session_work_dir())
    root = user_cache_dir() / "voice_clone"
    if (folder.parent.resolve() != root.resolve()
            or _SCRATCH_DIR_NAME.fullmatch(folder.name) is None
            or _scratch_dir_stat(root) is None or _scratch_dir_stat(folder) is None):
        raise ValueError("Reference scratch must be an owned voice-clone session directory.")
    # The sweeper shares this stable OS lock. A killed worker releases it,
    # leaving its PCM eligible for the same retention policy as recordings.
    lock = tts_job._JobLock(folder / tts_job.LOCK_FILE)
    lock.acquire()
    path = None
    try:
        path = _concat_references(sources, directory=str(folder))
        hasher = hashlib.sha256()
        with open(path, "rb") as audio:
            for chunk in iter(lambda: audio.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        text = _reference_text_cache.get(digest)
        if text is None:
            release_models()
            text = _transcribe_reference(path)
            if not text.strip():
                raise RuntimeError("No speech was recognized in the reference audio.")
            if len(_reference_text_cache) >= _REFERENCE_TEXT_CACHE_SIZE:
                del _reference_text_cache[next(iter(_reference_text_cache))]
            _reference_text_cache[digest] = text
        yield PreparedReference(path, text, tuple(sources))
    finally:
        try:
            if path is not None:
                os.remove(path)
        except OSError:
            pass
        finally:
            lock.release()


def load_model(device: str = "cpu") -> object:
    """Load (or return the cached) OmniVoice model for *device*.

    Call once per worker process; :func:`generate` takes the result so
    repeated calls in the same process reuse it. Raises whatever
    OmniVoice / torch raises on a real failure.
    """
    cached = _model_cache.get(device)
    if cached is not None:
        return cached
    # Start and end are logged so a slow load is visible in the worker log:
    # the load reads ~3 GB of weights, and a busy disk can stretch it from
    # seconds to many minutes with nothing else written in between.
    logger.info("voice_clone load_model: loading OmniVoice on %s", device)
    t0 = time.time()
    optional_deps.activate()
    import torch  # type: ignore[import-not-found] # noqa: PLC0415
    from omnivoice import OmniVoice  # type: ignore[import-not-found] # noqa: PLC0415

    imports_s = time.time() - t0
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice", device_map=device, dtype=torch.float32,
    )
    _model_cache[device] = model
    logger.info(
        "voice_clone load_model: OmniVoice ready on %s in %.1fs (imports %.1fs)",
        device, time.time() - t0, imports_s,
    )
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
    consent_record: bool = True,
    prepared_reference: PreparedReference | None = None,
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
    clip. For cloning, enter :func:`prepare_reference` before loading the
    model, and pass its result as ``prepared_reference``. This freezes the
    ordered reference and transcribes it without overlapping ASR and TTS
    allocations. Direct calls with an already-loaded model never allocate ASR.

    The finished WAV is tagged as AI-generated
    (:func:`core.synthetic_audio.tag_wav`), and a cloning run appends its
    local consent record (:func:`core.synthetic_audio.append_consent_record`).
    ``consent_record=False`` skips that record: a piece of a long job
    (``core.tts_job``) is not the file the user gets, so the caller writes
    one record for the joined file instead.

    Raises whatever OmniVoice / torch raises on a real failure -- the
    worker wraps this call and turns exceptions into an ``error`` event
    rather than crashing silently.
    """
    if reference_paths and not consent_accepted:
        raise ValueError("Consent not accepted; refusing to generate.")
    if not text or not text.strip():
        raise ValueError("No text to speak.")
    if len(text) > MAX_PASS_CHARS:
        raise ValueError(
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {MAX_PASS_CHARS}."
        )
    if reference_paths and (
        prepared_reference is None
        or prepared_reference.source_paths != tuple(reference_paths[:MAX_REFERENCE_SAMPLES])
        or not prepared_reference.text.strip()
        or not os.path.isfile(prepared_reference.path)
    ):
        raise ValueError("Enter prepare_reference before loading the voice model and pass its prepared_reference.")
    import soundfile as sf  # type: ignore[import-not-found] # noqa: PLC0415

    options: dict[str, object] = {}
    if language:
        options["language"] = language
    if speed and abs(speed - 1.0) > 1e-3:
        options["speed"] = float(speed)

    ref_path = prepared_reference.path if reference_paths and prepared_reference else None
    t0 = time.time()
    if ref_path is not None and prepared_reference is not None:
        audio = model.generate(text=text, ref_audio=ref_path, ref_text=prepared_reference.text, **options)  # type: ignore[attr-defined]
    elif instruct:
        audio = model.generate(text=text, instruct=instruct, **options)  # type: ignore[attr-defined]
    else:
        audio = model.generate(text=text, **options)  # type: ignore[attr-defined]
    elapsed = time.time() - t0
    rate = int(getattr(model, "sampling_rate", 0) or DEFAULT_SAMPLE_RATE)
    if len(audio[0]) == 0:
        # Never a 0-second file that the tab would report as done.
        raise RuntimeError("OmniVoice produced no audio for this text.")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio[0], rate)
    synthetic_audio.tag_wav(output_path)
    warning = ""
    if reference_paths and consent_record:
        try:
            # The clips actually fed to the model (_concat_references
            # takes at most MAX_REFERENCE_SAMPLES).
            synthetic_audio.append_consent_record(
                output_path, reference_paths[:MAX_REFERENCE_SAMPLES],
                consent_accepted=consent_accepted, engine="omnivoice",
            )
        except OSError as e:
            # The clip is finished and tagged; failing the whole run
            # (possibly an hour of CPU time) over a local log line
            # would discard it, so report it as a warning instead.
            logger.exception("Could not write the voice-clone consent record")
            warning = f"The local consent record could not be saved: {e}"
    audio_seconds = len(audio[0]) / rate
    logger.info(
        "voice_clone generate: %.2fs audio in %.1fs (RTF=%.2f)",
        audio_seconds, elapsed, elapsed / max(audio_seconds, 0.01),
    )
    return GenerateResult(output_path=output_path, audio_seconds=audio_seconds,
                          elapsed_seconds=elapsed, warning=warning)



def _concat_references(paths: "list[str]", *, directory: str | None = None) -> str:
    """Concatenate up to MAX_REFERENCE_SAMPLES reference clips into one
    temp WAV via the bundled ffmpeg, so OmniVoice's single-reference API
    gets the benefit of every sample the user recorded."""
    import tempfile

    from .paths import bundled_binary  # noqa: PLC0415
    from . import _proc  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    ffmpeg = bundled_binary("ffmpeg")
    fd, out_path = tempfile.mkstemp(
        suffix=".wav", prefix="voice_clone_ref_",
        dir=directory if directory is not None else session_work_dir(),
    )
    os.close(fd)
    cmd = [ffmpeg, "-y", "-v", "error"]
    for p in paths[:MAX_REFERENCE_SAMPLES]:
        cmd += ["-i", p]
    n = min(len(paths), MAX_REFERENCE_SAMPLES)
    cmd += ["-filter_complex", f"concat=n={n}:v=0:a=1", "-c:a", "pcm_s16le", out_path]
    kwargs: dict = {
        **_UTF8, "stdin": subprocess.DEVNULL, "capture_output": True, "text": True, "timeout": 60,
    }
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
