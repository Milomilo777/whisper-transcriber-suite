"""Validated assistant controls shared by both MCP transports."""
from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from pathlib import Path
from typing import Any

from core import config
from core.server.mcp import _ToolError, _check_keys, _schema, _tool_result

SAFE_KEYS = frozenset({"whisper_model", "language", "device", "compute_type",
                       "output_formats", "batch_size", "vad_enabled",
                       "word_timestamps", "diarization_enabled",
                       "gpu_temperature_limit_enabled", "gpu_temperature_limit_c"})
NAMES = frozenset({"transcribe_file", "get_settings", "set_settings",
                   "system_status", "list_models"})


def definitions() -> list[dict[str, Any]]:
    return [
        {"name": "transcribe_file", "description": "Transcribe local media in an explicitly allowed folder. Local connections only.",
         "inputSchema": _schema({"path": {"type": "string"},
                                  "language": {"type": ["string", "null"]},
                                  "formats": {"type": "array", "items": {"type": "string"}}}, ["path"])},
        {"name": "get_settings", "description": "Read safe transcription settings only.", "inputSchema": _schema({})},
        {"name": "set_settings", "description": "Save safe transcription settings for subsequent jobs. Restart an already running HTTP server to load a changed model.",
         "inputSchema": _schema({"settings": {"type": "object"}}, ["settings"])},
        {"name": "system_status", "description": "Read device, GPU memory, temperature, installed models and versions.", "inputSchema": _schema({})},
        {"name": "list_models", "description": "List the model catalogue and installed weights, without local paths.", "inputSchema": _schema({})},
    ]


def safe_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    # Only validated values leave the process, even with a hand-edited config.
    result: dict[str, Any] = {}
    for key in sorted(SAFE_KEYS):
        value = cfg.get("mcp_language", "") if key == "language" else cfg.get(key, config.DEFAULT_CONFIG.get(key))
        try:
            validate_settings({key: value}, cfg)
        except _ToolError:
            continue
        result[key] = value
    return result


def validate_settings(values: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    from core.model_manager import catalog_models
    from core.server.httpd import WEB_LANGUAGE_CODES
    from core.writers import supported_formats

    if not isinstance(values, dict) or not values:
        raise _ToolError("settings must be a non-empty object")
    if any(key not in SAFE_KEYS for key in values):
        raise _ToolError("settings contains a key outside the safe whitelist")
    enums = {"device": {"auto", "cpu", "cuda"},
             "compute_type": {"default", "auto", "int8", "int8_float16", "int8_float32", "float16", "float32", "bfloat16"},
             "language": set(WEB_LANGUAGE_CODES),
             "whisper_model": {slug for slug, _label in catalog_models(cfg)}}
    for key, value in values.items():
        if key in enums:
            if not isinstance(value, str) or value not in enums[key]:
                raise _ToolError(f"unsupported value for {key}")
        elif key == "output_formats":
            if (not isinstance(value, list) or not value
                    or any(not isinstance(v, str) or v not in supported_formats() for v in value)):
                raise _ToolError("output_formats must contain supported format names")
        elif key == "batch_size":
            if type(value) is not int or not 1 <= value <= 256:
                raise _ToolError("batch_size must be an integer from 1 to 256")
        elif key == "gpu_temperature_limit_c":
            if type(value) is not int or not 60 <= value <= 90:
                raise _ToolError("gpu_temperature_limit_c must be an integer from 60 to 90")
        elif type(value) is not bool:
            raise _ToolError(f"{key} must be a boolean")
    project = {k: v for k, v in values.items() if k in config.PROJECT_ALLOWED_KEYS}
    if config._validate_overrides(project, Path("assistant settings")) != project:
        raise _ToolError("invalid transcription settings")
    return dict(values)


def allowed_file(raw: Any, cfg: dict[str, Any]) -> tuple[Path, Path]:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise _ToolError("path must be an absolute media file path")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise _ToolError("path must be absolute and contain no '..' components")
    folders = cfg.get("mcp_allowed_folders", [])
    if not isinstance(folders, list) or not folders:
        raise _ToolError("Add a trusted folder to mcp_allowed_folders in the app configuration, then retry")
    try:
        physical = path.resolve(strict=True)
        if not physical.is_file() or physical.suffix.lower() not in {
                ".wav", ".mp3", ".mp4", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".webm", ".mkv", ".mov", ".avi"}:
            raise _ToolError("path must be an existing regular audio or video file")
        # Windows alternate data streams and device namespace paths are not media.
        if ":" in physical.name or raw.startswith(("\\\\?\\", "\\\\.\\")):
            raise _ToolError("special device paths are refused")
        for folder in folders:
            if not isinstance(folder, str) or not Path(folder).is_absolute():
                continue
            root = Path(folder).resolve(strict=True)
            if root.is_dir() and physical.is_relative_to(root):
                return physical, root
    except (OSError, ValueError, RuntimeError):
        raise _ToolError("local media path is unavailable") from None
    raise _ToolError("file is outside mcp_allowed_folders")


def models(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from core.model_manager import catalog_models, model_downloaded
    return [{"id": slug, "installed": model_downloaded(cfg, slug)}
            for slug, _label in catalog_models(cfg)]


def _celsius(value: str) -> int | None:
    """nvidia-smi temperature: recent drivers print decimals (59.81); "[N/A]" and the like mean unknown."""
    try:
        number = float(value)
    except ValueError:
        return None
    return round(number) if 0 <= number < 200 else None


def system_status(cfg: dict[str, Any]) -> dict[str, Any]:
    versions = {"python": platform.python_version()}
    for name in ("faster-whisper", "ctranslate2"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    gpus = []
    try:
        from core._proc import new_session_kwargs
        result = subprocess.run([
            "nvidia-smi", "--query-gpu=name,memory.free,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits"], capture_output=True, text=True,
            timeout=3, **new_session_kwargs())
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                name, free, total, temperature = [v.strip() for v in line.split(",")]
                gpus.append({"name": name, "free_vram_mib": int(free),
                             "total_vram_mib": int(total),
                             "temperature_c": _celsius(temperature)})
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"device": safe_settings(cfg).get("device", "auto"), "gpus": gpus,
            "models": models(cfg), "versions": versions}


def call(name: str, args: dict[str, Any], manager: Any, peer: str) -> dict[str, Any]:
    if name == "transcribe_file":
        if peer not in {"stdio", "127.0.0.1"}:
            raise _ToolError("local files require stdio or a connection from 127.0.0.1")
        _check_keys(args, ("path", "language", "formats"))
        cfg = config.load_config()
        path, root = allowed_file(args.get("path"), cfg)
        from core.server.mcp import validate_transcribe_args
        _url, formats, language, _start, _end = validate_transcribe_args({
            "url": "https://example.com/media", "language": args.get("language", cfg.get("mcp_language", "")),
            "formats": args.get("formats", cfg.get("output_formats", ["txt"]))})
        options = {k: v for k, v in safe_settings(cfg).items() if k in config.PROJECT_ALLOWED_KEYS}
        return _tool_result({"job_id": manager.submit_local(str(path), str(root), formats, language, options=options)})
    _check_keys(args, ("settings",) if name == "set_settings" else ())
    cfg = config.load_config()
    if name == "get_settings":
        return _tool_result({"settings": safe_settings(cfg)})
    if name == "set_settings":
        values = validate_settings(args.get("settings"), cfg)
        if "whisper_model" in values:
            from core.model_manager import catalog_resolve_entry
            entry = catalog_resolve_entry(cfg, values["whisper_model"])
            if entry is None:
                raise _ToolError("unknown model")
            cfg["model"] = {"name": entry["name"], "hf_repo": entry["hf_repo"]}
            cfg["model_path"] = ""
        cfg.update({("mcp_language" if k == "language" else k): v for k, v in values.items()})
        config.save_config(cfg)
        return _tool_result({"settings": safe_settings(cfg)})
    if name == "list_models":
        return _tool_result({"models": models(cfg)})
    return _tool_result(system_status(cfg))
