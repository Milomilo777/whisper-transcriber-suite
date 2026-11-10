"""Preset application must persist successfully before changing the GUI or workers."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.dialogs import presets


def host():
    config = {"device": "cuda", "webhook_url": "private", "whisper_model": "tiny",
              "model_path": "local-model", "vad_enabled": True}
    variables = {name: Mock() for name in (
        "word_timestamps_var", "translate_var", "diarization_var", "vad_enabled_var",
        "hotwords_var", "diarization_speakers_var", "transcribe_lang_var")}
    return SimpleNamespace(app_config=config, **variables,
        transcription_service=SimpleNamespace(active_workers=lambda: [], stop_all=Mock()),
        _engine_uses_whisper_model=lambda: True, _sync_diarization_speakers_option=Mock(),
        _refresh_model_selector=Mock(), _refresh_language_model_hint=Mock(),
        _sync_translate_option=Mock(), _refresh_accuracy_row=Mock())


def test_apply_preserves_machine_settings_and_language_is_session_only(monkeypatch):
    app = host()
    saved = []
    monkeypatch.setattr(presets, "save_config", lambda cfg: saved.append(dict(cfg)))
    presets.apply_settings(app, {"vad_enabled": False, "language": "English",
                                 "device": "cpu", "webhook_url": "untrusted"})
    assert saved[0]["vad_enabled"] is False
    assert saved[0]["device"] == "cuda"
    assert saved[0]["webhook_url"] == "private"
    assert saved[0]["model_path"] == "local-model"
    assert "language" not in saved[0]
    app.transcribe_lang_var.set.assert_called_once_with("English")
    app.transcription_service.stop_all.assert_called_once()
    app._sync_translate_option.assert_called_once()
    app._refresh_accuracy_row.assert_called_once()


def test_save_failure_leaves_runtime_unchanged(monkeypatch):
    app = host()
    monkeypatch.setattr(presets, "save_config", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        presets.apply_settings(app, {"vad_enabled": False, "language": "English"})
    assert app.app_config["vad_enabled"] is True
    app.vad_enabled_var.set.assert_not_called()
    app.transcription_service.stop_all.assert_not_called()


def test_running_task_prevents_change(monkeypatch):
    app = host()
    app.transcription_service.active_workers = lambda: [{"task": object()}]
    save = Mock()
    monkeypatch.setattr(presets, "save_config", save)
    with pytest.raises(ValueError, match="Wait"):
        presets.apply_settings(app, {"vad_enabled": False})
    save.assert_not_called()


def test_model_resolved_from_local_catalog_and_backend_preserved(monkeypatch):
    app = host()
    app.app_config["transcribe_backend"] = "faster_whisper"
    monkeypatch.setattr(presets, "catalog_resolve_entry", lambda cfg, slug: {"name": "small"})
    monkeypatch.setattr(presets, "save_config", Mock())
    presets.apply_settings(app, {"whisper_model": "small"})
    assert app.app_config["model"] == {"name": "small"}
    assert app.app_config["model_path"] == ""
    assert app.app_config["transcribe_backend"] == "faster_whisper"


def test_incompatible_engine_rejects_model_bundle(monkeypatch):
    app = host()
    app._engine_uses_whisper_model = lambda: False
    save = Mock()
    monkeypatch.setattr(presets, "save_config", save)
    with pytest.raises(ValueError, match="compatible"):
        presets.apply_settings(app, {"whisper_model": "small", "vad_enabled": False})
    save.assert_not_called()


def test_explicit_catalog_choice_replaces_custom_path_even_for_same_slug(monkeypatch):
    app = host()
    monkeypatch.setattr(presets, "catalog_resolve_entry", lambda cfg, slug: {"name": "tiny"})
    monkeypatch.setattr(presets, "save_config", Mock())
    presets.apply_settings(app, {"whisper_model": "tiny"})
    assert app.app_config["model_path"] == ""
    assert app.app_config["model"] == {"name": "tiny"}


def test_concurrent_privacy_change_survives_apply_and_next_gui_save(monkeypatch, tmp_path):
    import copy
    from core.config import DEFAULT_CONFIG, LoadedConfig, config_path, save_config
    import json
    from pathlib import Path

    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    initial = copy.deepcopy(DEFAULT_CONFIG)
    initial["telemetry_opt_in"] = True
    initial["vad_enabled"] = True
    save_config(initial)
    app = host()
    app.app_config = LoadedConfig(copy.deepcopy(initial), copy.deepcopy(initial))
    other = LoadedConfig(copy.deepcopy(initial), copy.deepcopy(initial))
    other["telemetry_opt_in"] = False
    save_config(other)
    presets.apply_settings(app, {"vad_enabled": False})
    assert json.loads(Path(config_path()).read_text())["telemetry_opt_in"] is False
    app.app_config["word_timestamps"] = False
    save_config(app.app_config)
    assert json.loads(Path(config_path()).read_text())["telemetry_opt_in"] is False


def test_capture_catalog_model_with_derived_path_but_not_custom_path(tmp_path):
    from core import hub
    app = host()
    app.app_config.update({"model": {"name": "faster-whisper-tiny"},
                           "hub_folder": str(tmp_path)})
    app.app_config["model_path"] = str(hub.model_folder_for(str(tmp_path), "faster-whisper-tiny"))
    assert presets.current_settings(app)["whisper_model"] == "tiny"
    app.app_config["model_path"] = str(tmp_path / "custom")
    assert "whisper_model" not in presets.current_settings(app)


def test_real_tk_app_model_accuracy_and_translate_controls_refresh(monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    from types import MethodType
    from app.app import App

    app = host()
    root = tk.Tk()
    try:
        app.transcribe_model_var = tk.StringVar(root)
        app.transcribe_accuracy_var = tk.StringVar(root)
        app.transcribe_accuracy_note_var = tk.StringVar(root)
        app.transcribe_accuracy_combo = ttk.Combobox(root, textvariable=app.transcribe_accuracy_var)
        app.translate_check = ttk.Checkbutton(root)
        app._transcribe_accuracy_label_to_level = {"Fast": "fast", "Balanced": "balanced", "Best": "best"}
        app._selected_transcribe_language = lambda: "en"
        app._sync_model_picker_for_engine = Mock()
        app._refresh_model_selector = MethodType(App._refresh_model_selector, app)
        app._refresh_accuracy_row = MethodType(App._refresh_accuracy_row, app)
        app._sync_translate_option = MethodType(App._sync_translate_option, app)
        app._translate_unsupported_reason = MethodType(App._translate_unsupported_reason, app)
        app.app_config.update({"transcribe_backend": "faster_whisper"})
        monkeypatch.setattr(presets, "save_config", Mock())
        presets.apply_settings(app, {"whisper_model": "large-v3-turbo"})
        root.update_idletasks()
        assert "turbo" in app.transcribe_model_var.get().lower()
        assert "turbo" in app.transcribe_accuracy_note_var.get().lower()
        assert "disabled" in app.translate_check.state()
        assert app.transcribe_accuracy_var.get()
    finally:
        root.destroy()


def test_queued_snapshot_uses_applied_options_and_resume_keeps_original(monkeypatch):
    from core import task_settings
    app = host()
    pending = SimpleNamespace(language="fa", task_type="transcribe")
    resumed = SimpleNamespace(language="fa", task_settings={"vad_enabled": True})
    app.queue = [pending, resumed]
    monkeypatch.setattr(presets, "save_config", Mock())
    monkeypatch.setattr(task_settings, "_no_ui_from_disk", lambda: {})
    presets.apply_settings(app, {"vad_enabled": False, "language": "English"})
    assert pending.language == "fa"
    assert task_settings.stamp(pending, app.app_config)["vad_enabled"] is False
    assert task_settings.stamp(resumed, app.app_config)["vad_enabled"] is True
