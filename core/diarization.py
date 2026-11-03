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
import gc
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from ._gc_import_guard import gc_disabled_import
from .paths import bin_dir, bundled_binary

logger = logging.getLogger(__name__)


def _log_relabel_failure(stage: str, error: Exception) -> None:
    # A retained LogRecord with exc_info would retain extractor traceback
    # frames, including the entire decoded audio and window vector arrays.
    try:
        detail = str(error)[:500]
    except Exception:  # noqa: BLE001 - broken exception formatting is optional too
        detail = "exception details unavailable"
    logger.warning("%s failed (%s: %s); retaining existing speaker labels",
                   stage, type(error).__name__, detail)


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
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        # communicate() accumulates pipe chunks then joins them, temporarily
        # holding two full decoded buffers. Spool to disk and allocate just
        # one owned float32 array; keep run()'s timeout and pipe draining.
        with tempfile.TemporaryFile() as decoded:
            subprocess.run(cmd, stdout=decoded, check=True, timeout=600, **kwargs)
            decoded.seek(0)
            samples = np.fromfile(decoded, dtype=np.float32)
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
    if samples.size == 0:
        # A valid container with no audio frames (or a header-only
        # WAV) decodes to nothing with ffmpeg exit code 0. sherpa's
        # native process() cannot take an empty array and raises /
        # crashes outside Python; surface the documented exception.
        raise DiarizationUnavailable(
            "decoded audio is empty — no samples for diarization"
        )
    return samples, 16000


# Diarisation runs in its own process (core/diarization_worker.py): sherpa-onnx
# loads onnxruntime.dll, and when the process already holds an older copy
# (issue #7: a foreign ORT 1.17.1 on Windows) the native code crashes the whole
# process. A fresh child keeps the transcription worker, and the finished
# transcript it holds, alive whatever happens there.
WORKER_STALL_TIMEOUT_S = 300.0  # no event from the worker for this long -> hung
WORKER_MIN_TIMEOUT_S = 600.0  # overall limit floor
WORKER_TIMEOUT_PER_AUDIO_S = 4.0  # overall limit: this many seconds per audio second
# sherpa-onnx reports nothing during its segmentation pass, so until the
# first real progress event a periodic 0.0 heartbeat goes out through
# progress_cb. Later heartbeats repeat the latest real fraction. Heartbeats
# keep the parent's watchdog fed, but must not reset our worker stall clock.
SEGMENTATION_HEARTBEAT_S = 15.0
WORKER_THREADS = 2
_CANCEL_POLL_S = 0.1


def _worker_command() -> list[str]:
    import sys

    if getattr(sys, "frozen", False):
        return [sys.executable, "--diarize-worker"]
    return [sys.executable, "-u", "-m", "core.diarization_worker"]


def _crash_reason(returncode: int | None, stderr_lines: list[str]) -> str:
    """Readable reason for a worker that exited without a result."""
    text = " ".join(stderr_lines)
    rc = returncode if returncode is not None else -1
    # Negative: killed by a POSIX signal. >= 0xC0000000: a Windows NTSTATUS
    # error such as 0xC0000005 (access violation).
    if rc < 0 or rc >= 0xC0000000:
        reason = f"Speaker detection crashed (exit code {rc})"
        if "requested API version" in text:
            reason += (": an older onnxruntime.dll was already loaded in the process "
                       "(another program's copy); the bundled one could not be used")
        return reason
    reason = f"Speaker detection worker exited with code {rc}"
    if text:
        reason += f": {text[-300:]}"
    return reason


def diarize(
    audio_path: str,
    *,
    num_speakers: int = -1,
    cluster_threshold: float = 0.5,
    progress_cb: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[DiarSegment]:
    """Run offline speaker diarization on ``audio_path`` in a worker process.

    Parameters:
        audio_path: any file ffmpeg can read.
        num_speakers: pass a positive int to force a known speaker
            count; ``-1`` lets the clusterer decide based on
            ``cluster_threshold``.
        cluster_threshold: lower = more clusters (more speakers).
            Default 0.5 is sherpa-onnx's recommended starting value.
        progress_cb: optional callback receiving 0.0–1.0 fractions.
        cancelled: polled while the worker runs; when it returns True the
            worker is stopped and ``[]`` is returned.

    Returns:
        List of ``DiarSegment(start, end, speaker)`` sorted by
        start time. Speaker IDs are stable across the file ("Speaker
        00", "Speaker 01", …) but not across files.

    Raises:
        DiarizationUnavailable if the package or models are missing, the
        audio cannot be decoded, or the worker crashes, hangs or times out.
    """
    import collections
    import json
    import queue
    import threading
    import time

    from ._proc import kill_process_tree, new_session_kwargs

    reason = availability_reason()
    if reason:
        raise DiarizationUnavailable(reason)

    try:
        from .transcriber import get_duration

        duration = float(get_duration(audio_path))
    except Exception:  # noqa: BLE001 - only sizes the time limit
        duration = 0.0
    overall_timeout_s = max(WORKER_MIN_TIMEOUT_S, duration * WORKER_TIMEOUT_PER_AUDIO_S)

    kwargs: dict[str, Any] = {
        "cwd": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        # Set before the child imports native libraries; do not change the
        # server's environment or its ASR thread settings.
        "env": {**os.environ, **{name: str(WORKER_THREADS) for name in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        )}},
    }
    kwargs.update(new_session_kwargs())
    try:
        process = subprocess.Popen(_worker_command(), **kwargs)
    except OSError as e:
        raise DiarizationUnavailable(f"could not start the speaker detection worker: {e}") from e

    events: queue.Queue[dict[str, Any]] = queue.Queue()
    stderr_tail: collections.deque[str] = collections.deque(maxlen=50)

    def _read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                # Native libraries may print to stdout; only JSON lines are events.
                logger.debug("diarization worker stdout: %s", line.strip()[:200])
                continue
            if isinstance(ev, dict):
                events.put(ev)

    def _read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            if line.strip():
                stderr_tail.append(line.strip())

    readers = [threading.Thread(target=_read_stdout, daemon=True),
               threading.Thread(target=_read_stderr, daemon=True)]
    for t in readers:
        t.start()

    def _stop(force: bool) -> None:
        kill_process_tree(process, force=force)
        try:
            process.wait(timeout=5.0)
        except Exception:  # noqa: BLE001
            kill_process_tree(process, force=True)

    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps({
            "audio_path": audio_path,
            "num_speakers": num_speakers,
            "cluster_threshold": cluster_threshold,
        }) + "\n")
        process.stdin.flush()
        process.stdin.close()
    except (OSError, ValueError) as e:
        # The worker died before reading the request; its exit code and
        # stderr below say why.
        logger.debug("diarization worker did not take the request: %s", e)

    start = last_event = last_heartbeat = time.monotonic()
    segments: list[dict[str, Any]] | None = None
    fallback: list[dict[str, Any]] | None = None
    exited = False
    # sherpa-onnx reports nothing during its segmentation pass, which takes
    # minutes on long audio (first progress after ~100 s for 12 min on a
    # desktop CPU), so the stall limit only starts with the first progress;
    # before that the overall limit, which grows with the audio, applies.
    progressed = False
    last_fraction = 0.0

    def _retain_fallback(reason: str) -> bool:
        nonlocal segments
        if fallback is None:
            return False
        logger.warning("%s; retaining existing speaker labels", reason)
        segments = fallback
        return True

    try:
        while segments is None:
            if cancelled is not None and cancelled():
                _stop(force=False)
                return []
            now = time.monotonic()
            if (
                progress_cb is not None
                and now - last_heartbeat >= SEGMENTATION_HEARTBEAT_S
            ):
                progress_cb(last_fraction)
                last_heartbeat = now
            if now - start > overall_timeout_s:
                _stop(force=True)
                reason = f"speaker detection took longer than {overall_timeout_s:.0f} s and was stopped"
                if _retain_fallback(reason):
                    break
                raise DiarizationUnavailable(reason)
            if progressed and now - last_event > WORKER_STALL_TIMEOUT_S:
                _stop(force=True)
                reason = f"speaker detection made no progress for {WORKER_STALL_TIMEOUT_S:.0f} s and was stopped"
                if _retain_fallback(reason):
                    break
                raise DiarizationUnavailable(reason)
            try:
                ev = events.get(timeout=_CANCEL_POLL_S)
            except queue.Empty:
                if exited:
                    break  # exited and every event it printed has been handled
                if process.poll() is not None:
                    # Let the reader hand over what the worker printed last.
                    readers[0].join(timeout=2.0)
                    exited = True
                continue
            last_event = time.monotonic()
            kind = ev.get("event")
            if kind == "progress":
                progressed = True
                last_fraction = float(ev.get("fraction", 0.0))
                last_heartbeat = last_event
                if progress_cb is not None:
                    progress_cb(last_fraction)
            elif kind == "done":
                segments = list(ev.get("segments") or [])
            elif kind == "fallback":
                # Sent before optional window extraction. A native crash or
                # allocation failure after this cannot discard the good turns.
                fallback = list(ev.get("segments") or [])
            elif kind == "error":
                _stop(force=True)
                reason = str(ev.get("error") or "unknown error")
                if _retain_fallback(reason):
                    break
                raise DiarizationUnavailable(reason)

        if segments is None:
            readers[1].join(timeout=2.0)
            reason = _crash_reason(process.returncode, list(stderr_tail))
            if not _retain_fallback(reason):
                raise DiarizationUnavailable(reason)
        assert segments is not None
        try:
            process.wait(timeout=10.0)
        except Exception:  # noqa: BLE001 - the result is already in hand
            _stop(force=True)
        return [
            DiarSegment(start=float(s["start"]), end=float(s["end"]), speaker=str(s["speaker"]))
            for s in segments
        ]
    except Exception as error:  # noqa: BLE001 - optional relabelling/delivery cannot lose good turns
        if fallback is None:
            raise
        if cancelled is not None and cancelled():
            return []
        _log_relabel_failure("Speaker relabelling delivery", error)
        return [DiarSegment(float(s["start"]), float(s["end"]), str(s["speaker"]))
                for s in fallback]
    finally:
        # Whatever left the loop (a raising progress callback, a malformed
        # result, an interrupt), the worker must not outlive this call.
        if process.poll() is None:
            _stop(force=True)


def _diarize_impl(
    audio_path: str,
    *,
    num_speakers: int = -1,
    cluster_threshold: float = 0.5,
    progress_cb: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    fallback_cb: Callable[[list[DiarSegment]], None] | None = None,
) -> list[DiarSegment]:
    """Diarize ``audio_path`` in THIS process (the worker's side of ``diarize``).

    Call ``diarize`` instead: loading sherpa-onnx here can crash the caller
    (issue #7). Same parameters and result as ``diarize``.

    Parameters:
        audio_path: any file ffmpeg can read.
        num_speakers: pass a positive int to force a known speaker
            count; ``-1`` lets the clusterer decide based on
            ``cluster_threshold``.
        cluster_threshold: lower = more clusters (more speakers).
            Default 0.5 is sherpa-onnx's recommended starting value.
        progress_cb: optional callback receiving 0.0–1.0 fractions.
        cancelled: optional cooperative check, including between voice windows.
            The public caller also polls cancellation and stops this process.
        fallback_cb: publish legacy labels before optional native extraction,
            so the parent can retain them even if this process crashes.

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
    import threading

    if cancelled is not None and cancelled():
        return []

    progress_lock = threading.Lock()
    last_fraction = 0.0

    def _report(fraction: float) -> None:
        nonlocal last_fraction
        with progress_lock:
            last_fraction = max(last_fraction, min(1.0, fraction))
            if progress_cb is not None:
                try:
                    progress_cb(last_fraction)
                except Exception:  # noqa: BLE001 - progress cannot discard labels
                    pass

    seg_path = _model_path(SEGMENTATION_MODEL)
    emb_path = _model_path(EMBEDDING_MODEL)

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=seg_path
            ),
            num_threads=WORKER_THREADS,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=emb_path, num_threads=WORKER_THREADS,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=int(num_speakers), threshold=float(cluster_threshold)
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    # sherpa-onnx 1.13 checks the paths with a narrow-char file test on Windows, so a model
    # folder with non-ASCII letters (a Portable copy under a Turkish user name) "does not exist"
    # although the files load fine. availability_reason() has already checked them in Python;
    # only an ASCII path still trusts validate().
    if not config.validate() and (seg_path + emb_path).isascii():
        raise DiarizationUnavailable(
            "sherpa-onnx diarization config rejected the model paths"
        )

    sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    samples, _sr = _prepare_audio_16k_mono(audio_path)

    def _on_progress(processed: int, total: int) -> int:
        if total > 0:
            # Explicit counts keep the native clustering path. Unknown counts
            # reserve the final quarter for window embeddings and clustering.
            _report((1.0 if num_speakers > 0 else 0.75) * processed / total)
        return int(cancelled is not None and cancelled())

    try:
        result = sd.process(samples, callback=_on_progress)
        if cancelled is not None and cancelled():
            return []
        segments = [
            DiarSegment(
                start=float(r.start),
                end=float(r.end),
                speaker=f"Speaker {int(r.speaker):02d}",
            )
            for r in result.sort_by_start_time()
        ]
        # Release the first model/extractor before creating the window extractor.
        del result, sd, config
        if num_speakers > 0 or not segments:
            return merge_small_speakers(segments, num_speakers=num_speakers)

        # Keep the full legacy result ready before doing any optional work.
        # A failed window N must not expose a partially relabelled transcript.
        fallback = merge_small_speakers(segments)
        stop: threading.Event | None = None
        heartbeat: threading.Thread | None = None
        try:
            if fallback_cb is not None:
                fallback_cb(fallback)
            stop = threading.Event()

            def _heartbeat() -> None:
                assert stop is not None
                while not stop.wait(SEGMENTATION_HEARTBEAT_S):
                    _report(last_fraction)

            heartbeat = threading.Thread(
                target=_heartbeat, name="speaker-cluster-heartbeat", daemon=True,
            )
            heartbeat.start()
            _report(0.75)
            labelled = _recluster_speakers(
                samples, _sr, segments, emb_path,
                progress_cb=_report, cancelled=cancelled,
            )
        except Exception as error:  # noqa: BLE001 - optional, including allocation failures
            if cancelled is not None and cancelled():
                return []
            _log_relabel_failure("Window speaker clustering", error)
            labelled = fallback
        finally:
            if stop is not None:
                stop.set()
            if heartbeat is not None and heartbeat.ident is not None:
                heartbeat.join(timeout=1.0)
        _report(1.0)
        # Spectral clusters have already been selected by the eigengap. The
        # temporal small-cluster merge adds no benefit on the replay data and
        # can erase a genuine speaker with little speech. Keep it for fallback.
        return labelled
    finally:
        del samples
        gc.collect()


def _recluster_speakers(
    samples: Any, sample_rate: int, segments: list[DiarSegment], model_path: str,
    *, progress_cb: Callable[[float], None], cancelled: Callable[[], bool] | None,
) -> list[DiarSegment]:
    """Extract fixed-size voice windows, then replace labels atomically.

    Called only in the isolated diarization worker, after the caller has saved
    its completed transcription checkpoint. Exceptions retain legacy labels.
    """
    import numpy as np
    import sherpa_onnx  # type: ignore[import-untyped]

    from . import speaker_cluster as cluster

    def _check_cancelled() -> None:
        if cancelled is not None and cancelled():
            raise cluster.ClusteringCancelled("speaker window extraction cancelled")

    _check_cancelled()
    turns = [(s.start, s.end) for s in segments]
    windows = list(cluster.windows_from_turns(turns))
    if not windows:
        raise ValueError("no speech windows for speaker embeddings")
    # The model might have disappeared since availability_reason(). Avoid
    # handing a missing path to native code after a good diarization result.
    if not os.path.isfile(model_path):
        raise FileNotFoundError("speaker embedding model is missing")
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=model_path, num_threads=WORKER_THREADS,
    )
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    vectors, spans, turn_ids = [], [], []
    minimum_samples = int(cluster.MIN_PIECE_SECONDS * sample_rate)
    window_samples = int(cluster.WINDOW_SECONDS * sample_rate)
    for index, window in enumerate(windows):
        _check_cancelled()
        piece = samples[int(window.start * sample_rate):int(window.end * sample_rate)]
        if len(piece) >= minimum_samples:
            if len(piece) < window_samples:
                # Adapted from 3D-Speaker (https://github.com/modelscope/3D-Speaker) — circular voice padding.
                piece = np.resize(piece, window_samples)  # circular padding
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate, piece)
            stream.input_finished()
            vectors.append(np.asarray(extractor.compute(stream), dtype=np.float32))
            spans.append((window.start, window.end))
            turn_ids.append(window.turn_id)
        progress_cb(0.75 + 0.20 * (index + 1) / len(windows))
        _check_cancelled()
    del extractor, config
    if not vectors:
        raise ValueError("no decoded speech windows for speaker embeddings")
    labels = cluster.cluster_turns(
        turns, np.vstack(vectors), np.asarray(spans), np.asarray(turn_ids),
        cancelled=cancelled, progress_cb=lambda fraction: progress_cb(0.95 + 0.04 * fraction),
    )
    _check_cancelled()
    return [DiarSegment(s.start, s.end, f"Speaker {label:02d}")
            for s, label in zip(segments, labels, strict=True)]


def _speaker_gap(left: list[DiarSegment], right: list[DiarSegment]) -> float:
    """Minimum interval gap in linear time and constant auxiliary memory.

    Inputs are sorted by start. No pairwise turn-distance matrix is needed.
    """
    i = j = 0
    best = math.inf
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        ae, be = max(a.start, a.end), max(b.start, b.end)
        best = min(best, max(0.0, a.start - be, b.start - ae))
        if best == 0.0:
            return best
        if ae <= be:
            i += 1
        else:
            j += 1
    return best


def merge_small_speakers(
    segments: list[DiarSegment],
    *,
    centroids: dict[str, list[float]] | None = None,
    num_speakers: int = -1,
) -> list[DiarSegment]:
    """Merge whole small clusters repeatedly; preserve explicit counts and times.

    Prefer embedding distance when available, otherwise use nearest turns.
    Centroids are duration-weighted after a merge. Ties use speaker labels
    so results do not depend on set iteration order. Inputs are not mutated.
    """
    if num_speakers > 0 or not segments:
        return segments
    turns: dict[str, list[DiarSegment]] = {}
    totals: dict[str, float] = {}
    for seg in sorted(segments, key=lambda s: s.start):
        turns.setdefault(seg.speaker, []).append(seg)
        totals[seg.speaker] = totals.get(seg.speaker, 0.0) + max(0.0, seg.end - seg.start)
    threshold = max(10.0, 0.03 * sum(totals.values()))
    vectors = {k: list(v) for k, v in (centroids or {}).items() if k in totals}
    labels = {s: s for s in totals}
    while len(totals) > 1:
        small = min(totals, key=lambda s: (totals[s], s))
        if totals[small] >= threshold:
            break
        others = [s for s in totals if s != small]
        available = [s for s in others if s in vectors] if small in vectors else []
        if available:
            target = min(available, key=lambda s: (math.dist(vectors[small], vectors[s]), s))
        else:
            target = min(others, key=lambda s: (_speaker_gap(turns[small], turns[s]), s))
        combined = totals[target] + totals[small]
        if target in vectors and small in vectors:
            weight = totals[small] / combined if combined else 0.5
            vectors[target] = [a * (1.0 - weight) + b * weight
                               for a, b in zip(vectors[target], vectors[small])]
        # A partial centroid would misrepresent a merged cluster.
        elif target in vectors:
            del vectors[target]
        vectors.pop(small, None)
        totals[target] = combined
        del totals[small]
        turns[target] = sorted(turns[target] + turns.pop(small), key=lambda s: s.start)
        for original, current in labels.items():
            if current == small:
                labels[original] = target
    return [DiarSegment(s.start, s.end, labels[s.speaker]) for s in segments]


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
