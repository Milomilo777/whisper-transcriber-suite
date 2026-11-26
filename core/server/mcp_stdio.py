"""Newline-delimited MCP transport; stdout belongs exclusively to JSON-RPC."""
from __future__ import annotations

import contextlib
import json
import logging
import sys
from typing import Any, TextIO

from core import __version__
from core.server import mcp

MAX_MESSAGE = 1024 * 1024


def _restore_windows_pipes() -> None:
    """Windowed frozen Python clears sys streams even with inherited pipes."""
    import os
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_handle = kernel.GetStdHandle
    get_handle.argtypes = [wintypes.DWORD]
    get_handle.restype = wintypes.HANDLE
    get_type = kernel.GetFileType
    get_type.argtypes = [wintypes.HANDLE]
    get_type.restype = wintypes.DWORD
    for name, number, mode, flags in (("stdin", -10, "r", os.O_RDONLY),
                                       ("stdout", -11, "w", os.O_WRONLY),
                                       ("stderr", -12, "w", os.O_WRONLY)):
        if getattr(sys, name) is not None:
            continue
        handle = get_handle(wintypes.DWORD(number))
        if get_type(handle) != 3:  # FILE_TYPE_PIPE; never attach a console or file.
            continue
        try:
            fd = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
            setattr(sys, name, os.fdopen(fd, mode, encoding="utf-8", newline="\n"))
        except OSError:
            continue


def serve(manager: Any, source: TextIO, output: TextIO) -> None:
    while True:
        try:
            line = source.readline(MAX_MESSAGE + 1)
        except UnicodeDecodeError:
            # TextIO may already have buffered later frames; terminate cleanly.
            output.write(json.dumps(mcp.error_response(None, mcp.PARSE_ERROR, "invalid UTF-8")) + "\n")
            output.flush()
            return
        if not line:
            return
        if len(line) > MAX_MESSAGE:
            # Drain this frame without allocating an unbounded line.
            while line and not line.endswith("\n"):
                line = source.readline(MAX_MESSAGE + 1)
            response = mcp.error_response(None, mcp.PARSE_ERROR, "message too large")
        else:
            try:
                message = json.loads(line)
            except (ValueError, RecursionError):
                response = mcp.error_response(None, mcp.PARSE_ERROR, "invalid JSON")
            else:
                with contextlib.redirect_stdout(sys.stderr):
                    response = mcp.handle(message, manager, app_version=__version__, client_address="stdio")
        if response is not None:
            output.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n")
            output.flush()


def _model_settings(cfg: dict[str, Any], target: tuple[str, str]) -> tuple[object, ...] | None:
    backend = str(cfg.get("transcribe_backend") or "faster_whisper").strip().lower()
    if backend == "faster_whisper":
        return (backend, *target, cfg.get("model_path"))
    if backend == "whisper_cpp":
        return (backend, *target)
    if backend == "mlx_whisper":
        from core.backends.mlx_whisper_be import model_folder

        return (backend, *target, model_folder(cfg))
    if backend == "nvidia_asr":
        return (backend, *target, cfg.get("nvidia_asr_model_id"), cfg.get("nvidia_asr_device"),
                cfg.get("nvidia_asr_dtype"), cfg.get("nvidia_asr_chunk_seconds"))
    # Cloud engines refresh their credentials and connection settings each job.
    return None


def main() -> int:
    _restore_windows_pipes()
    if sys.stdin is None or sys.stdout is None:
        return 2  # The client must supply readable stdin and writable stdout.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="strict", newline="\n")
    source, output = sys.stdin, sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        from core.server import _download_url, _real_transcribe
        from core.server.jobs import JobManager

        loaded_settings: tuple[object, ...] | None = None

        def transcribe(task: Any, progress_cb: Any = None, log_cb: Any = None,
                       language_cb: Any = None) -> None:
            nonlocal loaded_settings
            from core import config, transcriber
            from core.hardware import detect_device_for

            cfg = config.load_config()
            transcriber.config.update(cfg)
            target = detect_device_for(cfg)
            requested = _model_settings(cfg, target)
            if requested is None or requested != loaded_settings or not transcriber.is_model_ready():
                loaded_settings = None
                transcriber.release_language_model()
                transcriber.release_default_model()
                transcriber.release_alternate_backend()
                transcriber.device, transcriber.compute_type = target
                if not transcriber.load_existing_model(lambda text: logging.info("%s", text)):
                    raise RuntimeError("Configured model is unavailable; install it using the app")
                loaded_settings = requested
            _real_transcribe(task, progress_cb, log_cb, language_cb)

        manager = JobManager(transcribe, download_fn=_download_url)
        manager.start()
        try:
            serve(manager, source, output)
        except (KeyboardInterrupt, BrokenPipeError):
            pass
        finally:
            manager.stop()
    return 0
