"""Privacy-preserving, best-effort clues for failed usage-statistics rows."""
from __future__ import annotations

import errno
from functools import lru_cache
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("telemetry_registry.json").read_text(encoding="utf-8"))


# Module and function names are fixed, and the most specific innermost frame wins.
# None for the function means any function in that exact module.
SITE_FRAMES: dict[tuple[str, str | None], str] = {
    ("faster_whisper.audio", "decode_audio"): "worker.decode",
    ("av.container.input", None): "worker.decode",
    ("faster_whisper.vad", None): "worker.vad",
    ("core.vad_window", None): "worker.vad",
    ("core.speech_collect", "collect_chunks"): "worker.vad",
    ("core.speech_collect", "gather_speech"): "worker.vad",
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
        task._telemetry_stage = _STAGES.get(site, "other")
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
    # NumPy's native concatenate can raise without a Python numpy frame.
    if code == "numpy_alloc_failed" and _has_frame(tb, "core.speech_collect", "gather_speech"):
        return True
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
    ("cublas_missing", re.compile(r"Library (?:cublas(?:Lt)?64_[0-9]+\.dll|(?:lib)?cublas(?:Lt)?\.so(?:\.[0-9]+)*) is not found or cannot be loaded")),
    ("cudnn_missing", re.compile(
        r"Library (?:cudnn(?:_(?:(?:ops|cnn|adv)(?:_infer|_train)?|graph|heuristic|engines_precompiled|engines_runtime_compiled))?64_[0-9]+\.dll"
        r"|(?:lib)?cudnn(?:_(?:(?:ops|cnn|adv)(?:_infer|_train)?|graph|heuristic|engines_precompiled|engines_runtime_compiled))?\.so(?:\.[0-9]+)*) is not found or cannot be loaded"
    )),
)
_TOKENIZER_PATTERN = re.compile(
    r"(?:Error while loading tokenizer|Unable to load tokenizer|Tokenizer vocabulary is invalid)"
)


def observed_code(exc: BaseException) -> str:
    if isinstance(exc, OSError):
        if exc.errno == errno.ECONNRESET or getattr(exc, "winerror", None) == 10054:
            return "network_reset"
        if getattr(exc, "winerror", None) == 112 or exc.errno == errno.ENOSPC:
            return "disk_full"
        if getattr(exc, "winerror", None) == 5 or exc.errno == errno.EACCES:
            return "access_denied"
        if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
            if (_has_frame(exc.__traceback__, "subprocess", "_execute_child") and
                    any(_has_frame(exc.__traceback__, "core.transcriber", name) for name in
                        ("get_duration", "require_audio_stream", "_slice_audio_from"))):
                return "ffmpeg_missing"
            return "file_not_found"
    if type(exc).__module__ == "av.error":
        if type(exc).__name__ in {"DecoderNotFoundError", "EncoderNotFoundError"}:
            return "codec_unsupported"
    if exception_family(exc) == "av.InvalidDataError":
        return "av_invalid_data"
    if isinstance(exc, RuntimeError) and _has_frame(exc.__traceback__, "core.transcriber", "require_audio_stream"):
        if str(exc).endswith(" has no audio track, so there is nothing to transcribe."):
            return "no_audio_stream"
    if (isinstance(exc, RuntimeError) and isinstance(exc.__cause__, subprocess.TimeoutExpired)
            and _has_frame(exc.__traceback__, "core.transcriber", "get_duration")):
        return "probe_timeout"
    if isinstance(exc, (RuntimeError, MemoryError)):
        message = _safe_message(exc)
        for code, pattern in _PATTERNS:
            if pattern.fullmatch(message) and _library_frame(exc.__traceback__, code):
                return code
        if _tokenizer_frame(exc.__traceback__) and _TOKENIZER_PATTERN.fullmatch(message):
            return "tokenizer_error"
    return "none"


def _tokenizer_frame(tb: TracebackType | None) -> bool:
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if isinstance(module, str) and (module == "tokenizers" or module.startswith("tokenizers.")
                                       or module == "faster_whisper.tokenizer"):
            return True
        tb = tb.tb_next
    return False


def _safe_message(exc: BaseException) -> str:
    try:
        return str(exc)[:32768]
    except Exception:  # noqa: BLE001 - even an exception's __str__ can fail
        return ""


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


BASE_FIELDS = frozenset("form_submitted model language audio_duration transcription_time status word_count "
                        "program_version country platform_system platform_release platform_version platform_machine "
                        "platform_processor cpu_count mem_total install_id".split())
LEGACY_FIELDS = frozenset("failure_site exception_family observed_code classifier_version os_error exit_code "
                          "device peak_mem_mb".split())
MAX_ROW_BYTES = 8192
MAX_ROW_KEYS = 64
_DEFAULTS: dict[str, str] = {"failure_site": "other", "exception_family": "other", "observed_code": "none",
                             "classifier_version": "2", "device": "unknown", "os_error": "0",
                             "exit_code": "0", "peak_mem_mb": "0"}


def _valid_value(name: str, value: Any, spec: Mapping[str, Any]) -> str | None:
    if isinstance(value, bool):
        value = ("true" if value else "false") if name in {"diarization", "vad"} else None
    if isinstance(value, int):
        # Avoid conversion of unbounded integers from a damaged worker record.
        value = str(value) if -2147483648 <= value <= 16777216 * 1024**3 else None
    if not isinstance(value, str) or len(value) > 256:
        return None
    kind = spec["type"]
    if kind == "enum":
        return value if value in spec["values"] else None
    if kind == "integer":
        if not re.fullmatch(r"-?[0-9]{1,12}", value):
            return None
        number = int(value)
        if spec["min"] <= number <= spec["max"] and number % spec.get("step", 1) == 0:
            return str(number)
    if kind == "hex":
        return value if re.fullmatch(r"[0-9a-f]{" + str(spec["length"]) + "}", value) else None
    if kind == "pattern" and len(value) <= spec["max_length"] and re.fullmatch(spec["pattern"], value):
        if name == "top_frame":
            module, function, _ = value.split(":")
            if module not in spec["modules"] or not re.fullmatch(spec["function_pattern"], function):
                return None
        return value
    return None


def sanitise_clue(clue: Mapping[str, Any] | None = None, *, status: str | None = None) -> dict[str, str]:
    """The single automatic-POST boundary: registered values, no extra keys or text.

    The original eight clue fields keep their safe defaults. New optional facts
    are absent when unobserved. The same validator covers the legacy usage row.
    """
    from urllib.parse import urlencode

    fields = registry()["fields"]
    # Retain the legacy terminal spelling accepted by usage-statistics callers.
    if status == "done":
        status = "finished"
    source = clue if isinstance(clue, Mapping) else {}
    result: dict[str, str] = {}
    for name, spec in fields.items():
        if status in {"finished", "cancelled"} and name not in BASE_FIELDS:
            if status == "cancelled" or name not in {"run_id", "recovered", "classifier_version"}:
                continue
        value = _valid_value(name, source.get(name), spec)
        if value is None:
            if name in _DEFAULTS and status not in {"finished", "cancelled"}:
                value = _DEFAULTS[name]
            elif source.get(name) is not None and "other" in spec.get("values", ()):
                value = "other"
            else:
                continue
        result[name] = value
    if "exit_code" in result and result.get("failure_site") != "parent.worker_exit":
        result["exit_code"] = "0"
    if result.get("gpu_vendor") == "none" and result.get("vram_bucket") not in {None, "none", "unknown"}:
        result["vram_bucket"] = "unknown"
    if status == "error" and result.get("recovered") not in {None, "none", "failed_after_recovery"}:
        result["recovered"] = "failed_after_recovery"
    if status == "finished" and result.get("recovered") in {None, "none", "failed_after_recovery"}:
        for name in ("run_id", "recovered", "classifier_version"):
            result.pop(name, None)
    if len(result) > MAX_ROW_KEYS or len(urlencode(result).encode("ascii")) > MAX_ROW_BYTES:
        return {}
    return result


def _module_for_file(filename: str) -> str | None:
    """Resolve only this installation's code files, never a suffix of a private path."""
    if not isinstance(filename, str) or len(filename) > 4096 or filename.startswith("<"):
        return None
    root = str(Path(__file__).resolve().parent.parent).replace("\\", "/")
    text = filename.replace("\\", "/")
    if os.path.isabs(text):
        # normcase is needed on Windows, where drive-letter case is not significant.
        if not os.path.normcase(text).startswith(os.path.normcase(root + "/")):
            return None
        text = text[len(root) + 1:]
    if ".." in text.split("/") or not text.endswith(".py"):
        return None
    module = text[:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module[:-9]
    return module if module in registry()["fields"]["top_frame"]["modules"] else None


def _code_frames(tb: TracebackType | None) -> list[str]:
    frames = []
    spec = registry()["fields"]["top_frame"]
    while tb is not None:
        code = tb.tb_frame.f_code
        module = _module_for_file(code.co_filename)
        if module:
            value = f"{module}:{code.co_name}:{tb.tb_lineno}"
            if _valid_value("top_frame", value, spec) is not None:
                frames.append(value)
        tb = tb.tb_next
    return frames[-3:]


def shape_hash(message: str) -> str:
    """Hash a closed template ID, or nothing; never extract words from free text."""
    template = ""
    # Reject oversized messages instead of turning a truncated prefix into a match.
    if len(message) <= 32768:
        for code, pattern in (*_PATTERNS, ("tokenizer_error", _TOKENIZER_PATTERN)):
            if pattern.fullmatch(message):
                template = code
                break
    # Even a fully matching message contributes no parameters (sizes, dtypes or DLL names).
    return hashlib.sha256(template.encode("ascii")).hexdigest()[:12]


def _fingerprint(row: Mapping[str, str], frames: list[str]) -> str:
    locations = [frame.rsplit(":", 1)[0] for frame in frames[-3:]]
    material = [row.get(key, "") for key in
                ("failure_site", "exception_family", "observed_code", "classifier_version", "os_error")]
    material.extend(locations)
    material.append(row.get("shape_hash", ""))
    return hashlib.sha256("|".join(material).encode("ascii")).hexdigest()[:12]


def log_memory_bucket(value: Any) -> int:
    """Upper powers of two in MB, minimum 256; zero means unavailable."""
    try:
        number = int(value)
        return max(256, 1 << (number - 1).bit_length()) if 0 < number <= 16777216 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _bucket(value: Any, limits: tuple[tuple[float, str], ...], last: str = "more") -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        return None
    return next((name for limit, name in limits if value < limit), last)


def _build_kind() -> str:
    root = Path(__file__).resolve().parent.parent
    if (root / "unins000.exe").is_file():
        return "installer"
    if getattr(sys, "frozen", False):
        return "onefile" if Path(getattr(sys, "_MEIPASS", "")).name.startswith("_MEI") else "other"
    if Path(sys.executable).parent == root / "python":
        return "portable"
    return "source"


def context_clue(task: Any = None, *, device: str = "unknown", probe: bool = True) -> dict[str, Any]:
    """Local facts only. Missing observations stay absent or explicitly unknown."""
    result: dict[str, Any] = {"gpu_vendor": "unknown", "vram_bucket": "unknown"}
    try:
        if probe:
            result["build_kind"] = _build_kind()
        if device in {"mps", "mlx"}:
            result["gpu_vendor"] = "apple"
        if task is None:
            return result
        result["run_id"] = getattr(task, "run_id", None)
        result["last_stage"] = getattr(task, "_telemetry_stage", None)
        progress = getattr(task, "progress", None)
        if isinstance(progress, (int, float)) and not isinstance(progress, bool) and math.isfinite(progress):
            result["progress_pct"] = int(max(0, min(100, progress))) // 10 * 10
        start = getattr(task, "start_time", None)
        if isinstance(start, (int, float)) and start > 0:
            result["elapsed_bucket"] = _bucket(time.time() - start, (
                (10, "lt10s"), (60, "lt1m"), (300, "lt5m"), (1800, "lt30m"), (7200, "lt2h")))
        result["recovered"] = getattr(task, "_telemetry_recovery", "none")
        result["compute_type"] = getattr(task, "_failure_compute_type", None)
        settings = getattr(task, "_telemetry_settings", None) or getattr(task, "task_settings", None) or {}
        for field, key in (("diarization", "diarization_enabled"), ("vad", "vad_enabled")):
            value = settings.get(key)
            if field == "vad" and value is None:
                value = settings.get("vad_filter")
            if isinstance(value, bool):
                result[field] = value
        result["language_mode"] = "fixed" if getattr(task, "language", None) or getattr(task, "languages", None) else "auto"
        result["input_kind"] = getattr(task, "_telemetry_input_kind", None) or (
            "download" if getattr(task, "source_download", None) is not None else "file")
        path = getattr(task, "file_path", None)
        if isinstance(path, str) and path:
            extension = Path(path).suffix.lower().lstrip(".")
            result["input_container"] = extension if extension in registry()["fields"]["input_container"]["values"] else "other"
            if probe:
                try:
                    size = Path(path).stat().st_size
                    result["input_size_bucket"] = "zero" if size == 0 else _bucket(size, (
                        (100 * 1024**2, "lt100mb"), (2 * 1024**3, "lt2gb")))
                except OSError:
                    pass
                try:
                    result["disk_free_bucket"] = _bucket(shutil.disk_usage(Path(path).parent).free, (
                        (1024**3, "lt1gb"), (4 * 1024**3, "lt4gb"), (16 * 1024**3, "lt16gb")))
                except OSError:
                    pass
        duration = getattr(task, "_input_duration", None)
        result["input_duration_bucket"] = _bucket(duration, (
            (60, "lt1m"), (600, "lt10m"), (3600, "lt1h"), (10800, "lt3h")))
        vendor = getattr(task, "_telemetry_gpu_vendor", "unknown")
        if vendor != "unknown":
            result["gpu_vendor"] = vendor
        vram = getattr(task, "_telemetry_vram_mb", None)
        if vram is not None:
            result["vram_bucket"] = "none" if vram == 0 else _bucket(vram, (
                (4096, "lt4gb"), (8192, "4_6gb"), (16384, "8_12gb"), (32768, "16_24gb")), "32gb_plus")
    except Exception:  # noqa: BLE001
        logger.debug("Run context unavailable", exc_info=True)
    if not probe:
        return result
    try:
        import psutil
        result["ram_free_bucket"] = _bucket(psutil.virtual_memory().available, (
            (1024**3, "lt1gb"), (4 * 1024**3, "lt4gb"), (16 * 1024**3, "lt16gb")))
    except Exception:  # noqa: BLE001
        logger.debug("Free memory unavailable", exc_info=True)
    return result


_STAGES = {"worker.decode": "decode", "worker.vad": "vad", "worker.features": "transcribe",
           "worker.language": "language", "worker.segments": "transcribe", "worker.postprocess": "other",
           "worker.output": "write", "worker.prepare": "decode", "worker.model": "other"}


def worker_clue(exc: BaseException, task: Any = None, *, site: str | None = None,
                device: str = "unknown") -> dict[str, str]:
    """Never let collection replace the failure it is meant to describe."""
    row: dict[str, Any] = {}
    try:
        failure_site = site or site_from_traceback(exc.__traceback__, getattr(task, "_failure_site", "other"))
        origin = exc
        if failure_site in {"worker.model", "worker.prepare"}:
            seen = {id(origin)}
            while origin.__cause__ is not None and id(origin.__cause__) not in seen and len(seen) < 16:
                origin = origin.__cause__
                seen.add(id(origin))
        code = observed_code(origin)
        if failure_site == "worker.prepare" and observed_code(exc) != "none":
            code = observed_code(exc)
        if (failure_site == "worker.model" and code == "none" and isinstance(origin, RuntimeError)
                and any(_has_frame(exc.__traceback__, "core.transcriber", name) for name in
                        ("_ensure_default_backend_loaded", "load_existing_model", "_get_alt_backend"))):
            code = "model_load_failed"
        frames = _code_frames(origin.__traceback__) or _code_frames(exc.__traceback__)
        row = {**context_clue(task, device=device), "failure_site": failure_site,
               "exception_family": exception_family(origin), "observed_code": code,
               "os_error": os_error(origin), "device": device,
               "peak_mem_mb": log_memory_bucket(peak_memory_mb()),
               "last_stage": getattr(task, "_telemetry_stage", None) or _STAGES.get(failure_site, "other"),
               "shape_hash": shape_hash("" if isinstance(origin, OSError) else _safe_message(origin))}
        if frames:
            row["top_frame"] = frames[-1]
        clean = sanitise_clue(row, status="error")
        clean["fingerprint"] = _fingerprint(clean, frames)
        return sanitise_clue(clean, status="error")
    except Exception:  # noqa: BLE001
        logger.debug("Failure clue unavailable", exc_info=True)
        try:
            return sanitise_clue({"exception_family": exception_family(exc)})
        except Exception:  # noqa: BLE001
            return dict(_DEFAULTS)


def exit_observed_code(value: Any) -> str:
    code = normalise_exit_code(value)
    windows = {0xC0000005: "native_access_violation", 0xC0000135: "dll_not_found",
               0xC0000139: "dll_not_found", 0xC000001D: "illegal_instruction",
               0xC00000FD: "stack_overflow", 0xC0000409: "stack_overflow"}
    if sys.platform == "win32" and code in windows:
        return windows[code]
    if sys.platform != "win32" and code < 0:
        return "illegal_instruction" if code == -4 else "killed_by_signal"
    return "worker_exit_unclassified"


def parent_clue(site: str, *, device: str = "unknown", exit_code: Any = 0,
                pid: int | None = None, event: Mapping[str, Any] | None = None) -> dict[str, str]:
    observed = sanitise_clue(event)
    row: dict[str, Any] = {"failure_site": site, "device": device,
                           "exit_code": normalise_exit_code(exit_code),
                           "peak_mem_mb": log_memory_bucket(peak_memory_mb(pid)) if pid is not None else 0}
    for name in ("exception_family", "observed_code", "os_error", "top_frame", "shape_hash", "fingerprint",
                 "last_stage", "recovered", "run_id"):
        if name in observed:
            row[name] = observed[name]
    if site == "parent.worker_exit":
        code = exit_observed_code(exit_code)
        if code != "worker_exit_unclassified" or row.get("observed_code") == "none":
            row["observed_code"] = code
            row.pop("fingerprint", None)
    clean = sanitise_clue(row, status="error")
    if "fingerprint" not in clean:
        clean["fingerprint"] = _fingerprint(clean, [clean["top_frame"]] if "top_frame" in clean else [])
    return sanitise_clue(clean, status="error")


# A real traceback prints up to three lines per frame; twelve lines would hide its header.
STDERR_TAIL_LINES = 64


def stderr_clue(lines: list[str]) -> dict[str, str]:
    """Classify a complete terminal traceback or exact native/ffmpeg tail only."""
    # Keep invalid lines as barriers; dropping one could stitch together a fake traceback.
    tail = [line.rstrip("\r\n") for line in lines[-STDERR_TAIL_LINES:]]
    if any(len(line) > 2048 for line in tail):
        tail = []
    result: dict[str, Any] = {"failure_site": "parent.worker_exit"}
    frames: list[str] = []
    families = {cls.__name__: cls for cls in (
        MemoryError, RuntimeError, PermissionError, FileNotFoundError, TimeoutError, OSError,
        UnicodeError, ValueError, TypeError, KeyError, IndexError, AssertionError,
    )}
    families.update(UnicodeEncodeError=UnicodeError, UnicodeDecodeError=UnicodeError)
    families["ConnectionResetError"] = ConnectionResetError
    start = next((i for i in range(len(tail) - 1, -1, -1)
                  if tail[i] == "Traceback (most recent call last):"), -1)
    if start >= 0 and len(tail) - start >= 3:
        matches: list[re.Match[str]] = []
        valid = True
        source = caret = False
        for line in tail[start + 1:-1]:
            match = re.fullmatch(
                r'  File "([^"\r\n]+)", line ([0-9]{1,6}), in ([A-Za-z_<][A-Za-z0-9_.<>]{0,40})', line
            )
            if match:
                matches.append(match)
                source, caret = True, False
            elif source and line.startswith("    ") and line.strip():
                source, caret = False, True
            elif caret and re.fullmatch(r"    [~^ ]+", line):
                caret = False
            else:
                valid = False
                break
        name, _, message = tail[-1].partition(": ")
        cls = families.get(name)
        if valid and matches and cls is not None:
            result.update(exception_family=exception_family(cls()),
                          shape_hash=shape_hash("" if issubclass(cls, OSError) else message))
            library = tokenizer = False
            for match in matches:
                path = match[1].replace("\\", "/")
                library |= bool(re.search(r'/(?:faster_whisper|ctranslate2|numpy)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py$', path))
                tokenizer |= bool(re.search(r'/tokenizers/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py$|/faster_whisper/tokenizer\.py$', path))
                module = _module_for_file(match[1])
                if module:
                    frame = f"{module}:{match[3]}:{match[2]}"
                    if _valid_value("top_frame", frame, registry()["fields"]["top_frame"]):
                        frames.append(frame)
            if issubclass(cls, (RuntimeError, MemoryError)):
                if library:
                    for code, pattern in _PATTERNS:
                        if pattern.fullmatch(message):
                            result["observed_code"] = code
                            break
                if tokenizer and _TOKENIZER_PATTERN.fullmatch(message):
                    result["observed_code"] = "tokenizer_error"
            if name == "ConnectionResetError":
                result["observed_code"] = "network_reset"
    terminal = tail[-1].strip() if tail else ""
    if terminal == "Invalid data found when processing input":
        result["observed_code"] = "corrupt_media"
    elif re.fullmatch(r"(?:Decoder|Encoder) \([A-Za-z0-9_]+\) not found", terminal):
        result["observed_code"] = "codec_unsupported"
    elif (len(tail) >= 2 and
          tail[-2].strip() == "terminate called after throwing an instance of 'std::bad_alloc'" and
          terminal == "what():  std::bad_alloc"):
        result.update(exception_family="RuntimeError", observed_code="ct2_bad_alloc")
    if frames:
        result["top_frame"] = frames[-1]
        module, function, _ = frames[-1].split(":")
        site = SITE_FRAMES.get((module, function), SITE_FRAMES.get((module, None), "other"))
        result["last_stage"] = _STAGES.get(site, "other")
    clean = sanitise_clue(result)
    clean["fingerprint"] = _fingerprint(clean, frames)
    return sanitise_clue(clean)
