"""Pluggable Whisper backends.

The transcriber-level dispatcher reads ``config["transcribe_backend"]``
and calls :func:`get_backend` to obtain a :class:`Backend` instance.
Each backend implements load/transcribe/unload against a common
interface so the rest of the pipeline (diarization, writers, queue)
doesn't have to know which model is running underneath.

Currently supported:

  * ``faster_whisper`` (default) — the existing CTranslate2 path.
    Loads ``faster-whisper-large-v3`` from ``config["model_path"]``
    and supports CUDA via ``BatchedInferencePipeline``.

  * ``whisper_cpp`` — pywhispercpp wrapper. Quantised ggml models
    are much smaller (e.g. ``ggml-large-v3-q5_0.bin`` ≈ 1.1 GB) and
    run on weak CPUs that struggle with the float16 faster-whisper
    build. Opt-in via the Advanced dialog.

  * ``mlx_whisper`` — Whisper on the GPU of an Apple-silicon Mac through
    Apple's MLX (``mlx-whisper``). Offered and auto-selected only on macOS
    arm64 when the package imports; every other system keeps faster-whisper.

  * ``cloud_stt`` — OPTIONAL cloud transcription via the Google Gemini
    API (uploads audio to Google; breaks the offline guarantee). Opt-in
    via the Advanced dialog with a pasted API key.

  * ``google_cloud_stt`` — OPTIONAL cloud transcription via the REAL
    Google **Cloud** Speech-to-Text v2 service (uploads audio to Google;
    breaks the offline guarantee). Authenticates with a service-account
    JSON file (NOT an API key); supports word timestamps + diarization
    and a cheaper GCS batch mode. Opt-in via the Advanced dialog.

  * ``nvidia_asr`` — OPTIONAL cloud transcription via NVIDIA Nemotron 3.5
    ASR (NVCF gRPC streaming endpoint). Uploads audio to NVIDIA; requires
    a free API key from build.nvidia.com. Supports ~40 BCP-47 locales and
    word-level timestamps. Opt-in via the Advanced dialog.
"""
from __future__ import annotations

from .base import Backend, LanguageInfo


def get_backend(name: str) -> Backend:
    """Return a :class:`Backend` instance for ``name``.

    Unknown names silently fall back to ``faster_whisper`` so a
    stale config never blocks the user from transcribing.
    """
    name = (name or "").strip().lower() or "faster_whisper"
    if name == "whisper_cpp":
        from .whisper_cpp import WhisperCppBackend
        return WhisperCppBackend()
    if name == "cloud_stt":
        from .cloud_stt import CloudSttBackend
        return CloudSttBackend()
    if name == "google_cloud_stt":
        from .google_cloud_stt import GoogleCloudSttBackend
        return GoogleCloudSttBackend()
    if name == "nvidia_asr":
        from .nvidia_asr import NvidiaAsrBackend
        return NvidiaAsrBackend()
    if name == "mlx_whisper":
        from .mlx_whisper_be import MlxWhisperBackend
        return MlxWhisperBackend()
    from .faster_whisper_be import FasterWhisperBackend
    return FasterWhisperBackend()


__all__ = ["Backend", "LanguageInfo", "get_backend"]
