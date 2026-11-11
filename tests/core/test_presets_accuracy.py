"""An explicit preset model must replace a prior Accuracy-level intent."""
from __future__ import annotations

import json
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from app.app import App
from app.dialogs import presets
from core import config
from core.model_manager import catalog_resolve_entry


class _Var:
    def __init__(self, value):
        self.value = value
        self.on_set = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.on_set is not None:
            self.on_set()


class _Combo:
    def __init__(self):
        self.options = {"values": ("Fast", "Balanced", "Best"), "width": 10}

    def cget(self, key):
        return self.options[key]

    def configure(self, **kwargs):
        self.options.update(kwargs)


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    cfg = config.load_config(fetch_online=False)
    cfg.update({"whisper_model": "small", "model": catalog_resolve_entry(cfg, "small"),
                "model_path": "", "transcribe_backend": "faster_whisper",
                "work_offline": True, "telemetry_opt_in": False})
    config.save_config(cfg)
    variables = {name: _Var(value) for name, value in (
        ("word_timestamps_var", False), ("translate_var", False),
        ("diarization_var", False), ("vad_enabled_var", True),
        ("hotwords_var", ""), ("diarization_speakers_var", "Auto"),
        ("transcribe_lang_var", "English"), ("transcribe_accuracy_var", "Fast"),
        ("transcribe_accuracy_note_var", ""),
    )}
    app = SimpleNamespace(
        app_config=cfg, **variables, transcribe_accuracy_combo=_Combo(),
        transcription_service=SimpleNamespace(active_workers=lambda: [], stop_all=Mock()),
        _accuracy_choice="fast", _accuracy_picked_level="fast", _accuracy_ram_gb=32,
        _transcribe_accuracy_label_to_level={"Fast": "fast", "Balanced": "balanced", "Best": "best"},
        _engine_uses_whisper_model=lambda: True, _transcribing_now=lambda: False,
        _sync_diarization_speakers_option=Mock(), _refresh_model_selector=Mock(),
        _sync_translate_option=Mock(), _refresh_language_model_hint=Mock(),
        _switch_transcribe_model=Mock(return_value=True),
    )
    app._selected_transcribe_language = lambda: {"English": "en", "French": "fr", "Arabic": "ar"}.get(
        app.transcribe_lang_var.get())
    app._refresh_accuracy_row = MethodType(App._refresh_accuracy_row, app)
    return app


@pytest.mark.parametrize("language_trace", [False, True])
def test_explicit_preset_model_survives_later_language_selection(host, language_trace):
    if language_trace:
        host.transcribe_lang_var.on_set = lambda: host._refresh_accuracy_row(language_changed=True)
    presets.apply_settings(host, {"whisper_model": "large-v3", "language": "English"})
    assert host.app_config["whisper_model"] == "large-v3"
    assert host.transcribe_accuracy_var.get() == "Best"
    host.transcribe_lang_var.set("French")
    host._refresh_accuracy_row(language_changed=True)
    host._switch_transcribe_model.assert_not_called()
    assert json.loads(Path(config.config_path()).read_text())["whisper_model"] == "large-v3"


def test_preset_without_model_preserves_previously_picked_accuracy(host):
    presets.apply_settings(host, {"vad_enabled": False})
    assert host._accuracy_picked_level == "fast"
    assert host._accuracy_choice == "fast"
    assert host.app_config["whisper_model"] == "small"
    assert host.vad_enabled_var.get() is False


def test_explicit_same_model_preset_ends_old_level_intent(host):
    host.app_config.update({"whisper_model": "large-v3",
                            "model": catalog_resolve_entry(host.app_config, "large-v3")})
    config.save_config(host.app_config)
    host._accuracy_picked_level = host._accuracy_choice = "best"
    host._refresh_accuracy_row()
    presets.apply_settings(host, {"whisper_model": "large-v3"})
    host.transcribe_lang_var.set("Arabic")
    host._refresh_accuracy_row(language_changed=True)
    host._switch_transcribe_model.assert_not_called()
    assert host.app_config["whisper_model"] == "large-v3"


def test_failed_preset_save_preserves_accuracy_and_visible_choices(host, monkeypatch):
    before = Path(config.config_path()).read_bytes()
    monkeypatch.setattr(presets, "save_config", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        presets.apply_settings(host, {"whisper_model": "large-v3", "language": "French"})
    assert host._accuracy_picked_level == host._accuracy_choice == "fast"
    assert host.app_config["whisper_model"] == "small"
    assert host.transcribe_lang_var.get() == "English"
    host.transcription_service.stop_all.assert_not_called()
    assert Path(config.config_path()).read_bytes() == before
