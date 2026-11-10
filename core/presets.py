"""Local named bundles of explicitly allowed transcription settings.

Never serialize the entire app configuration: it includes credentials and machine paths.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from core.config import (
    DEFAULT_CONFIG, _PROJECT_KEY_RANGES, _SAVE_LOCK, _config_file_lock,
    _write_text_atomic, user_config_dir,
)

# Deliberately independent of PROJECT_ALLOWED_KEYS: future project permissions must not
# silently expand what a preset can save or change. No paid AI actions or engine switches.
PRESET_KEYS = frozenset({
    "output_formats", "initial_prompt", "hotwords", "word_timestamps", "batch_size",
    "vad_enabled", "vad_threshold", "vad_min_silence_ms", "vad_speech_pad_ms",
    "vad_window_s", "hallucination_detect_enabled", "demucs_enabled", "denoise_enabled",
    "denoise_level", "diarization_enabled", "diarization_num_speakers",
    "diarization_cluster_threshold", "translate_to_english", "whisper_model",
})
MAX_BYTES = 1024 * 1024
_FORMATS = frozenset({"srt", "ass", "vtt", "tsv", "txt", "json", "lrc", "md",
                      "otr", "elan", "inqscribe", "express_scribe", "docx", "pdf", "smtv_docx"})


def valid_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Use a preset name of 1 to 80 characters without control characters.")
    return name


def capture_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    """Filter at both save and load; reject malformed values without logging contents."""
    result: dict[str, Any] = {}
    for key in PRESET_KEYS:
        if key not in config:
            continue
        value = config[key]
        if key == "whisper_model":
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
                result[key] = value
            continue
        default = DEFAULT_CONFIG.get(key)
        if type(value) is not type(default):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if key in _PROJECT_KEY_RANGES:
            low, high = _PROJECT_KEY_RANGES[key]
            if not low <= value <= high:
                continue
        if key == "output_formats" and (not isinstance(value, list) or not value or any(
                not isinstance(v, str) or v not in _FORMATS for v in value)):
            continue
        if key == "denoise_level" and value not in {"auto", "off", "light", "medium", "strong"}:
            continue
        if isinstance(value, str) and len(value) > 10_000:
            continue
        result[key] = copy.deepcopy(value)
    # Language is a session choice, never restored automatically on app launch.
    language = config.get("language")
    if isinstance(language, str) and len(language) <= 80 and not any(ord(c) < 32 for c in language):
        result["language"] = language
    return result


class PresetStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else user_config_dir() / "presets.json"

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return {}
        if len(raw) > MAX_BYTES:
            raise ValueError("The preset file is too large.")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("presets"), dict):
                raise ValueError()
            result = {}
            for name, settings in data["presets"].items():
                if not isinstance(name, str) or valid_name(name) != name or not isinstance(settings, dict):
                    raise ValueError()
                result[name] = capture_settings(settings)
            return result
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("The preset file is invalid; it has been left unchanged.") from exc

    def _write(self, presets: dict[str, dict[str, Any]]) -> None:
        body = json.dumps({"version": 1, "presets": presets}, ensure_ascii=False, indent=2)
        if len(body.encode("utf-8")) > MAX_BYTES:
            raise ValueError("The preset file is full; delete an unused preset first.")
        _write_text_atomic(self.path, body)

    def save(self, name: str, settings: Mapping[str, Any], *, replace: bool = False) -> None:
        name = valid_name(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Reuse the config writer's thread/process lock and atomic replacement discipline.
        with _SAVE_LOCK, _config_file_lock(str(self.path)):
            presets = self.load()
            if name in presets and not replace:
                raise ValueError("A preset with this name already exists.")
            presets[name] = capture_settings(settings)
            self._write(presets)

    def delete(self, name: str) -> None:
        with _SAVE_LOCK, _config_file_lock(str(self.path)):
            presets = self.load()
            if name not in presets:
                raise ValueError("This preset no longer exists.")
            del presets[name]
            self._write(presets)
