"""Offline speaker diarization via sherpa-onnx.

Wraps the sherpa-onnx pipeline (pyannote-segmentation-3.0 +
3D-Speaker CAMPlus EN embedding) into a single ``diarize(audio_path)``
call that returns a list of ``{start, end, speaker}`` dicts.

Why sherpa-onnx and not pyannote.audio directly:
  - No HuggingFace token required.
  - No PyTorch dependency. We already ship onnxruntime for Silero
    VAD; this just reuses it.
  - Two small ONNX files (6.6 MB + 28 MB).

The two model files live alongside ffmpeg/ffprobe/yt-dlp under
``bin/diarization/``:

  bin/diarization/segmentation.onnx
  bin/diarization/embedding.onnx

The PyInstaller specs bundle the whole ``bin/`` tree, so the files
land in ``sys._MEIPASS/bin/diarization/`` in onefile mode and
beside the exe in onedir mode.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from ._gc_import_guard import gc_disabled_import
from .paths import bin_dir, bundled_binary

logger = logging.getLogger(__name__)

SEGMENTATION_MODEL = "segmentation.onnx"
EMBEDDING_MODEL = "embedding.onnx"
DIARIZATION_SUBDIR = "diarization"


class DiarizationUnavailable(RuntimeError):
    """Raised when diarization is requested but cannot run on this install."""


def _model_path(filename: str) -> str:
    """Return the absolute path to a diarization ONNX model file."""
    return os.path.join(bin_dir(), DIARIZATION_SUBDIR, filename)


def _sherpa_onnx_importable() -> bool:
    """sherpa-onnx wraps native ONNX-runtime bindings, a heavy C-extension
    package -- see core/_gc_import_guard.py for why the import runs under
    a shared, process-wide GC-disable guard. Shared by is_available() and
    availability_reason() (the latter needs its own import too, to tell a
    missing-package reason apart from a missing-model-file reason)."""
    with gc_disabled_import():
        try:
            import sherpa_onnx  # type: ignore[import-untyped] # noqa: F401
        except Exception:  # noqa: BLE001 — wrong-arch / missing native DLL
            # can raise OSError/RuntimeError, not ImportError (VLC bug class).
            return False
        else:
            return True


def is_available() -> bool:
    """True iff sherpa-onnx + both ONNX files are present.

    Cheap to call; doesn't actually load the models. Used by the UI
    to decide whether to enable the Diarization checkbox.
    """
    if not _sherpa_onnx_importable():
        return False
    return all(
        os.path.isfile(_model_path(f)) for f in (SEGMENTATION_MODEL, EMBEDDING_MODEL)
    )


def availability_reason() -> str:
    """Human-readable reason diarization isn't available, or ``""`` if it is."""
    if not _sherpa_onnx_importable():
        return "sherpa-onnx Python package not installed"
    for f in (SEGMENTATION_MODEL, EMBEDDING_MODEL):
        if not os.path.isfile(_model_path(f)):
            return f"missing model: {_model_path(f)}"
    return ""


@dataclass(frozen=True)
class DiarSegment:
    start: float
    end: float
    speaker: str


def _prepare_audio_16k_mono(audio_path: str) -> tuple[Any, int]:
    """Return (float32 mono ndarray, sample_rate=16000) for sherpa-onnx.

    sherpa-onnx's diarization API needs the audio at a specific
    sample rate (the segmentation model's expected 16 kHz) and as
    a 1-D float32 array. We use the bundled ffmpeg to resample
    rather than depending on ``soundfile``/``librosa`` — those drag
    in libsndfile + numpy bindings that aren't strictly needed
    elsewhere in the project.
    """
    import numpy as np  # bundled with faster-whisper

    ffmpeg = bundled_binary("ffmpeg")
    cmd = [
        ffmpeg,
        "-loglevel", "error",
        "-i", audio_path,
        "-ac", "1",
        "-ar", "16000",
        "-f", "f32le",
        "-",
    ]
    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, check=True, timeout=600, **kwargs)
    except subprocess.CalledProcessError as e:
        raise DiarizationUnavailable(
            f"ffmpeg failed to decode audio: {(e.stderr or b'').decode('utf-8', 'replace')[:300]}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise DiarizationUnavailable("ffmpeg timed out while decoding audio") from e
    except (FileNotFoundError, OSError) as e:
        # ffmpeg.exe missing from bin/ tree — subprocess.run raises
        # FileNotFoundError BEFORE check= can fire. The docstring
        # promises DiarizationUnavailable; the old code let the
        # OS error escape and crashed the worker.
        raise DiarizationUnavailable(
            f"ffmpeg binary not available: {e}"
        ) from e
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if samples.size == 0:
        # A valid container with no audio frames (or a header-only
        # WAV) decodes to nothing with ffmpeg exit code 0. sherpa's
        # native process() cannot take an empty array and raises /
        # crashes outside Python; surface the documented exception.
        raise DiarizationUnavailable(
            "decoded audio is empty — no samples for diarization"
        )
    return samples, 16000


def diarize(
    audio_path: str,
    *,
    num_speakers: int = -1,
    cluster_threshold: float = 0.5,
    progress_cb: Callable[[float], None] | None = None,
) -> list[DiarSegment]:
    """Run offline speaker diarization on ``audio_path``.

    Parameters:
        audio_path: any file ffmpeg can read.
        num_speakers: pass a positive int to force a known speaker
            count; ``-1`` lets the clusterer decide based on
            ``cluster_threshold``.
        cluster_threshold: lower = more clusters (more speakers).
            Default 0.5 is sherpa-onnx's recommended starting value.
        progress_cb: optional callback receiving 0.0–1.0 fractions.

    Returns:
        List of ``DiarSegment(start, end, speaker)`` sorted by
        start time. Speaker IDs are stable across the file ("Speaker
        00", "Speaker 01", …) but not across files.

    Raises:
        DiarizationUnavailable if the package or models are missing,
        or if the audio file cannot be decoded.
    """
    reason = availability_reason()
    if reason:
        raise DiarizationUnavailable(reason)

    import sherpa_onnx  # type: ignore[import-untyped]

    seg_path = _model_path(SEGMENTATION_MODEL)
    emb_path = _model_path(EMBEDDING_MODEL)

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=seg_path
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=emb_path),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=int(num_speakers), threshold=float(cluster_threshold)
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise DiarizationUnavailable(
            "sherpa-onnx diarization config rejected the model paths"
        )

    sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    samples, _sr = _prepare_audio_16k_mono(audio_path)

    def _on_progress(processed: int, total: int) -> int:
        if progress_cb and total > 0:
            try:
                progress_cb(min(1.0, processed / total))
            except Exception:  # noqa: BLE001
                pass
        return 0  # don't cancel

    result = sd.process(samples, callback=_on_progress).sort_by_start_time()
    return [
        DiarSegment(
            start=float(r.start),
            end=float(r.end),
            speaker=f"Speaker {int(r.speaker):02d}",
        )
        for r in result
    ]


def assign_speakers_to_segments(
    transcript_segments: list[dict],
    diar_segments: list[DiarSegment],
) -> list[dict]:
    """Mutate each transcript segment in place to carry a ``speaker`` field.

    Strategy: for each transcript segment, find the diarisation
    window whose [start, end] overlaps the most. If no diarisation
    window overlaps the segment at all, the segment is left without
    a speaker label (downstream writers will skip the speaker
    prefix). Stable, deterministic, no ML in the matcher.

    Returns the same list (mutated) for caller convenience.
    """
    if not diar_segments:
        return transcript_segments
    for seg in transcript_segments:
        try:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", s))
        except (TypeError, ValueError):
            continue
        if e <= s:
            continue
        best_overlap = 0.0
        best_speaker: str | None = None
        for d in diar_segments:
            if d.end <= s or d.start >= e:
                continue
            overlap = max(0.0, min(d.end, e) - max(d.start, s))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = d.speaker
        if best_speaker is not None:
            seg["speaker"] = best_speaker
    return transcript_segments
