"""``whisper.cpp`` backend via pywhispercpp.

Quantised ggml models (e.g. ``ggml-large-v3-q5_0.bin`` ≈ 1.1 GB) are
much smaller than the faster-whisper download (~3 GB) and run on weak
CPUs that struggle with the float16 path. The trade-off is slightly
worse accuracy on edge cases.

The model file lives at ``user_cache_dir() / "whisper_cpp" /
ggml-large-v3-q5_0.bin`` and is downloaded on demand via
:func:`download_default_model`.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .._gc_import_guard import gc_disabled_import
from .._liveness_tick import liveness_tick
from ..config import user_cache_dir
from .base import Backend, LanguageInfo

logger = logging.getLogger(__name__)


DEFAULT_MODEL_NAME = "ggml-large-v3-q5_0.bin"
DEFAULT_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    f"{DEFAULT_MODEL_NAME}"
)


def model_dir() -> Path:
    return user_cache_dir() / "whisper_cpp"


def default_model_path() -> Path:
    return model_dir() / DEFAULT_MODEL_NAME


def is_available() -> bool:
    """True iff pywhispercpp imports cleanly. Doesn't check the model file.

    pywhispercpp wraps native ggml bindings, a heavy C-extension package --
    see core/_gc_import_guard.py for why the import runs under a shared,
    process-wide GC-disable guard. Not cached -- an on-demand install must
    still be picked up by the next call.
    """
    with gc_disabled_import():
        try:
            import pywhispercpp  # type: ignore[import-not-found] # noqa: F401
        except Exception:  # noqa: BLE001 — a wrong-arch / missing native DLL
            # raises OSError/RuntimeError at import, not ImportError; a probe
            # must degrade to "unavailable", never crash.
            return False
        else:
            return True


def availability_reason() -> str:
    if is_available():
        return ""
    return "pywhispercpp Python package not installed"


def download_default_model(
    *,
    log: Callable[[str], None] | None = None,
    url: str = DEFAULT_MODEL_URL,
    dest: Path | None = None,
    chunk_size: int = 1 << 20,
) -> str:
    """Download the default ggml model to ``model_dir()``.

    Atomic: writes to ``<dest>.part`` and renames on success. If the
    final file already exists with the expected non-zero size, the
    download is skipped. Returns the absolute path on disk.
    """
    dest = dest if dest is not None else default_model_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000_000:  # ~100 MB sanity
        if log:
            log(f"whisper.cpp model already present at {dest}")
        return str(dest)
    part = dest.with_suffix(dest.suffix + ".part")
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass

    if log:
        log(f"Downloading {url} → {dest}")

    try:
        # timeout= on urlopen bounds each blocking socket operation, so a
        # stalled connection fails instead of hanging the download thread
        # forever (mirrors core/llm.py's download).
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 — known URL
            total = int(resp.getheader("Content-Length") or 0)
            downloaded = 0
            last_pct = -1
            with open(part, "wb") as fp:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if total and log:
                        pct = int((downloaded / total) * 100)
                        if pct != last_pct and pct % 5 == 0:
                            log(f"  {pct}% ({downloaded // (1 << 20)} / "
                                f"{total // (1 << 20)} MB)")
                            last_pct = pct
    except Exception:
        # Network drop / timeout / HTTP error: never leave the ~1.1 GB
        # partial file behind. The file handles are closed by the `with`
        # blocks before this runs (Windows refuses to unlink open handles).
        try:
            part.unlink()
        except OSError:
            pass
        raise
    # Completeness check: a server that closes the stream cleanly after
    # sending fewer bytes than Content-Length would otherwise promote a
    # truncated .part to the final model — which then fails to load deep
    # inside pywhispercpp with a cryptic ggml parse error and is never
    # re-fetched (the only later gate is exists() && size > 100 MB, which
    # a half-finished ~1 GB file passes). Refuse the short read instead.
    if total and downloaded != total:
        try:
            part.unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"whisper.cpp model download truncated: got {downloaded} of "
            f"{total} bytes. Check your connection and try again."
        )
    shutil.move(str(part), str(dest))
    if log:
        log(f"Done: {dest}")
    return str(dest)


class WhisperCppBackend(Backend):
    """Wraps a ``pywhispercpp.Model`` instance."""

    name = "whisper_cpp"

    def __init__(self) -> None:
        self._model: Any = None
        self._ready = False
        self._error: str | None = None

    def is_ready(self) -> bool:
        return self._ready

    def get_error(self) -> str | None:
        return self._error

    def load(
        self,
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self._ready = False
        self._error = None
        if not is_available():
            self._error = availability_reason()
            if status_cb:
                status_cb(f"whisper.cpp unavailable: {self._error}")
            return False

        model_path = default_model_path()
        if not model_path.exists():
            self._error = (
                f"whisper.cpp model missing at {model_path}. "
                "Use the Advanced dialog to download it."
            )
            if status_cb:
                status_cb(self._error)
            return False

        try:
            from pywhispercpp.model import Model  # type: ignore[import-not-found]
        except ImportError as e:
            self._error = f"pywhispercpp import failed: {e}"
            if status_cb:
                status_cb(self._error)
            return False

        if status_cb:
            status_cb("Loading whisper.cpp model...")
        try:
            # pywhispercpp resolves named models via download itself,
            # but we pass an absolute path so we control the cache.
            self._model = Model(str(model_path), print_progress=False)
        except Exception as e:  # noqa: BLE001
            self._error = f"whisper.cpp load failed: {e}"
            if status_cb:
                status_cb(self._error)
            return False

        self._ready = True
        if status_cb:
            status_cb("whisper.cpp model loaded")
        if progress_cb:
            progress_cb({
                "phase": "loaded", "status": "Model loaded",
                "percent": 100, "detail": "Ready (whisper.cpp)",
            })
        return True

    def unload(self) -> None:
        self._model = None
        self._ready = False

    def transcribe_to_segments(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        want_words: bool = False,
        vad_parameters: dict[str, Any] | None = None,
        initial_prompt: str | None = None,
        hotwords: str | None = None,
        batch_size: int = 16,
        progress_cb: Callable[[int], None] | None = None,
        log_cb: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        paused: Callable[[], bool] | None = None,
        duration: float = 0.0,
    ) -> tuple[list[dict[str, Any]], LanguageInfo]:
        if not self._ready or self._model is None:
            raise RuntimeError(self._error or "whisper_cpp backend not loaded")

        kwargs: dict[str, Any] = {}
        if language:
            kwargs["language"] = language
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        # pywhispercpp's `transcribe` accepts a path or numpy array. It
        # returns a list of Segment(start, end, text) — start/end are
        # in centiseconds in some versions, milliseconds in others.
        # We normalise via the .t0_to_seconds helper if present, and
        # fall back to dividing by 100 (centisecond default).
        #
        # The call is a single blocking C invocation that returns only
        # once the whole file is decoded — no events emitted while it
        # runs. Wrap it in a liveness tick so the parent watchdog
        # sees a heartbeat at least every 10 s on slow CPUs.
        with liveness_tick(log_cb, "whisper.cpp transcribe"):
            segments = self._model.transcribe(audio_path, **kwargs)

        segments_data: list[dict[str, Any]] = []
        n = len(segments) if hasattr(segments, "__len__") else 0
        for idx, seg in enumerate(segments):
            if cancelled and cancelled():
                if log_cb:
                    log_cb("Task cancelled")
                break
            while paused and paused() and not (cancelled and cancelled()):
                time.sleep(0.2)

            # pywhispercpp ships two segment shapes depending on
            # version. The C-style binding exposes ``t0``/``t1`` in
            # centiseconds (10 ms ticks); the Python wrapper exposes
            # ``start``/``end`` already in seconds. We pick whichever
            # the segment exposes — the attribute name unambiguously
            # tells us the unit.
            if hasattr(seg, "start") and seg.start is not None:
                start_s = float(seg.start)
                end_s = float(seg.end)
            else:
                start_s = float(getattr(seg, "t0", 0) or 0) / 100.0
                end_s = float(getattr(seg, "t1", 0) or 0) / 100.0
            text = getattr(seg, "text", "") or ""

            if log_cb:
                log_cb(f"[{start_s:.2f} --> {end_s:.2f}] {text.strip()}")
            if progress_cb:
                if duration > 0:
                    pct = min(100, int((end_s / duration) * 100))
                elif n:
                    pct = min(100, int(((idx + 1) / max(n, 1)) * 100))
                else:
                    pct = 0
                progress_cb(pct)

            payload: dict[str, Any] = {
                "start": start_s,
                "end": end_s,
                "text": text.strip(),
            }
            if want_words:
                # pywhispercpp doesn't expose word-level timestamps
                # in the public API; surface an empty list rather
                # than crashing downstream writers.
                payload["words"] = []
            segments_data.append(payload)

        # pywhispercpp exposes a detected language on the Model
        # instance after transcribe. Fall back to the forced language
        # when it isn't reported.
        detected = ""
        for attr in ("detected_language", "lang", "language"):
            v = getattr(self._model, attr, None)
            if isinstance(v, str) and v:
                detected = v
                break
        if not detected and language:
            detected = language
        return segments_data, LanguageInfo(language=detected, probability=1.0 if detected else 0.0)


_ = os  # keep "os" import alive for static checkers that warn on unused stdlib
