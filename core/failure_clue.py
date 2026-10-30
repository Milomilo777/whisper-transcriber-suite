"""Privacy-preserving, best-effort clues for failed usage-statistics rows."""
from __future__ import annotations

import errno
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def registry() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("telemetry_registry.json").read_text(encoding="utf-8"))


# Module and function names are fixed, and the most specific innermost frame wins.
# None for the function means any function in that exact module.
SITE_FRAMES: dict[tuple[str, str | None], str] = {
    ("faster_whisper.audio", "decode_audio"): "worker.decode",
    ("av.container.input", None): "worker.decode",
    ("faster_whisper.vad", None): "worker.vad",
    ("core.vad_window", None): "worker.vad",
    ("faster_whisper.feature_extractor", None): "worker.features",
    ("core.mel_blocks", None): "worker.features",
    ("faster_whisper.transcribe", "detect_language"): "worker.language",
    ("faster_whisper.transcribe", "generate_segments"): "worker.segments",
    ("core.loop_guard", None): "worker.postprocess",
    ("core.transcriber", "_run_post_pipeline"): "worker.postprocess",
    ("core.transcriber", "_rescue_collapsed"): "worker.postprocess",
    ("core.transcriber", "_write_outputs"): "worker.output",
    ("core.transcriber", "get_duration"): "worker.prepare",
    ("core.transcriber", "require_audio_stream"): "worker.prepare",
    ("core.transcriber", "_slice_audio_from"): "worker.prepare",
    ("core.transcriber", "_maybe_denoise"): "worker.prepare",
    ("core.transcriber", "_ensure_default_backend_loaded"): "worker.model",
    ("core.transcriber", "_get_alt_backend"): "worker.model",
    ("core.transcriber", "load_existing_model"): "worker.model",
}


def phase(task: Any, site: str) -> None:
    """Mark the currently observed phase without ever interrupting a job."""
    try:
        task._failure_site = site
    except Exception:  # noqa: BLE001
        logger.debug("Could not mark failure phase", exc_info=True)


def site_from_traceback(tb: TracebackType | None, fallback: str = "other") -> str:
    site = fallback
    while tb is not None:
        frame = tb.tb_frame
        module = frame.f_globals.get("__name__", "")
        function = frame.f_code.co_name
        # These wrappers also surround the engine. A deeper, unrelated fault
        # is not evidence that the wrapper itself failed.
        if not (tb.tb_next is not None and (module, function) in {
            ("core.loop_guard", "guard_repeats"), ("core.vad_window", "windowed_vad"),
        }):
            site = SITE_FRAMES.get((module, function), SITE_FRAMES.get((module, None), site))
        tb = tb.tb_next
    return site


def _has_frame(tb: TracebackType | None, module: str, function: str) -> bool:
    while tb is not None:
        if tb.tb_frame.f_globals.get("__name__") == module and tb.tb_frame.f_code.co_name == function:
            return True
        tb = tb.tb_next
    return False


def _library_frame(tb: TracebackType | None, code: str) -> bool:
    prefixes = ("numpy", "core.mel_blocks") if code == "numpy_alloc_failed" else ("ctranslate2", "faster_whisper")
    while tb is not None:
        name = tb.tb_frame.f_globals.get("__name__", "")
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            return True
        tb = tb.tb_next
    return False


def exception_family(exc: BaseException) -> str:
    if type(exc).__module__ == "av.error" and type(exc).__name__ == "InvalidDataError":
        return "av.InvalidDataError"
    for cls, name in ((subprocess.TimeoutExpired, "subprocess.TimeoutExpired"),
                      (subprocess.CalledProcessError, "subprocess.CalledProcessError")):
        if isinstance(exc, cls):
            return name
    for cls in (MemoryError, PermissionError, FileNotFoundError, TimeoutError, OSError,
                RuntimeError, UnicodeError, ValueError, TypeError, KeyError, IndexError, AssertionError):
        if isinstance(exc, cls):
            return cls.__name__
    return "other"


def os_error(exc: BaseException) -> int:
    if not isinstance(exc, OSError):
        return 0
    n = getattr(exc, "winerror", None) or exc.errno or 0
    return n if isinstance(n, int) and 0 <= n <= 0xFFFFFFFF else 0


# These patterns cover complete library messages, not substrings or arbitrary paths.
_PATTERNS = (
    ("numpy_alloc_failed", re.compile(r"Unable to allocate [0-9.]+ (?:bytes|KiB|MiB|GiB|TiB) for an array with shape \([0-9, ]*\) and data type [A-Za-z0-9_<>|]+")),
    ("ct2_bad_alloc", re.compile(r"(?:std::bad_alloc|bad allocation)")),
    ("cuda_out_of_memory", re.compile(r"CUDA failed with error out of memory")),
    ("cublas_missing", re.compile(r"Library cublas(?:64_[0-9]+\.dll|\.so(?:\.[0-9]+)*) is not found or cannot be loaded")),
    ("cudnn_missing", re.compile(r"Library cudnn(?:64_[0-9]+\.dll|\.so(?:\.[0-9]+)*) is not found or cannot be loaded")),
)


def observed_code(exc: BaseException) -> str:
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 112 or exc.errno == errno.ENOSPC:
            return "disk_full"
        if getattr(exc, "winerror", None) == 5 or exc.errno == errno.EACCES:
            return "access_denied"
        if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
            return "file_not_found"
    if exception_family(exc) == "av.InvalidDataError":
        return "av_invalid_data"
    if isinstance(exc, RuntimeError) and _has_frame(exc.__traceback__, "core.transcriber", "require_audio_stream"):
        if str(exc).endswith(" has no audio track, so there is nothing to transcribe."):
            return "no_audio_stream"
    if (isinstance(exc, RuntimeError) and isinstance(exc.__cause__, subprocess.TimeoutExpired)
            and _has_frame(exc.__traceback__, "core.transcriber", "get_duration")):
        return "probe_timeout"
    if isinstance(exc, (RuntimeError, MemoryError)):
        message = str(exc)
        for code, pattern in _PATTERNS:
            if pattern.fullmatch(message) and _library_frame(exc.__traceback__, code):
                return code
    return "none"


def peak_memory_mb(pid: int | None = None) -> int:
    """Windows peak private commit, bucketed; 0 where psutil cannot observe it."""
    try:
        import psutil
        info = psutil.Process(pid).memory_info()
        peak = getattr(info, "peak_pagefile", 0)
        mb = (int(peak) + 128 * 1024 * 1024) // (256 * 1024 * 1024) * 256
        return mb if 0 <= mb <= 16777216 else 0
    except Exception:  # noqa: BLE001
        logger.debug("Peak memory unavailable", exc_info=True)
        return 0


def normalise_exit_code(value: Any, platform: str | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    if (platform or sys.platform) == "win32" and value < 0:
        value &= 0xFFFFFFFF
    return value if -2147483648 <= value <= 4294967295 else 0


def sanitise_clue(clue: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Only registered values can cross the form-POST boundary."""
    fields = registry()["fields"]
    source = clue or {}
    defaults: dict[str, Any] = {"failure_site": "other", "exception_family": "other",
                                "observed_code": "none", "classifier_version": "1",
                                "device": "unknown"}
    result: dict[str, str] = {}
    for name, spec in fields.items():
        value = source.get(name, defaults.get(name, 0))
        if spec["type"] == "enum":
            value = str(value)
            if value not in spec["values"]:
                value = defaults[name]
        else:
            try:
                value = int(value)
            except (ValueError, TypeError, OverflowError):
                value = 0
            if not spec["min"] <= value <= spec["max"] or value % spec.get("step", 1):
                value = 0
        result[name] = str(value)
    if result["failure_site"] != "parent.worker_exit":
        result["exit_code"] = "0"
    return result


def worker_clue(exc: BaseException, task: Any = None, *, site: str | None = None,
                device: str = "unknown") -> dict[str, str]:
    return sanitise_clue({
        "failure_site": site or site_from_traceback(exc.__traceback__, getattr(task, "_failure_site", "other")),
        "exception_family": exception_family(exc), "observed_code": observed_code(exc),
        "os_error": os_error(exc), "device": device, "peak_mem_mb": peak_memory_mb(),
    })


def parent_clue(site: str, *, device: str = "unknown", exit_code: Any = 0,
                pid: int | None = None) -> dict[str, str]:
    return sanitise_clue({"failure_site": site, "device": device,
                          "exit_code": normalise_exit_code(exit_code),
                          "peak_mem_mb": peak_memory_mb(pid) if pid is not None else 0})
