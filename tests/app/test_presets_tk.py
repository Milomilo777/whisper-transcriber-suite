"""Preset intent survives real Tcl variable traces and combobox events."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

import pytest

from app.dialogs import presets
from app import i18n
from core import config
from tests.core.test_presets_accuracy import host


@pytest.fixture
def tk_preset_host(host):
    previous_language = i18n.current_language()
    root = None
    callback_errors = []
    try:
        i18n.set_language("en")
        root = tk.Tk()
        root.title("WTS preset regression test")
        root.report_callback_exception = lambda *error: callback_errors.append(error)
        for name, old in list(vars(host).items()):
            if name.endswith("_var"):
                cls = tk.BooleanVar if isinstance(old.get(), bool) else tk.StringVar
                setattr(host, name, cls(root, value=old.get()))
        host.transcribe_accuracy_combo = ttk.Combobox(
            root, textvariable=host.transcribe_accuracy_var,
            values=("Fast", "Balanced", "Best"), state="readonly",
        )
        host.transcribe_accuracy_combo.pack()
        languages = ttk.Combobox(
            root, textvariable=host.transcribe_lang_var,
            values=("English", "French", "Arabic"), state="readonly",
        )
        languages.pack()
        host.transcribe_lang_var.trace_add(
            "write", lambda *_: host._refresh_accuracy_row(language_changed=True),
        )
        languages.bind(
            "<<ComboboxSelected>>", lambda _: host._refresh_accuracy_row(language_changed=True),
        )
        root.update()
        yield host, languages, root
    finally:
        if root is not None:
            root.destroy()
        i18n.set_language(previous_language)
    assert callback_errors == [], "Tk swallowed a callback exception"


@pytest.mark.parametrize("language, label", [
    ("French", "Best"), ("Arabic", "Custom (current setting)"),
])
def test_explicit_preset_model_survives_tk_language_callbacks(tk_preset_host, language, label):
    app, languages, root = tk_preset_host
    presets.apply_settings(app, {"whisper_model": "large-v3", "language": "English"})
    assert app.transcribe_accuracy_combo.get() == "Best"
    languages.current(list(languages.cget("values")).index(language))
    languages.event_generate("<<ComboboxSelected>>")
    root.update()
    app._switch_transcribe_model.assert_not_called()
    assert app.app_config["whisper_model"] == "large-v3"
    # Arabic's recommended Best is Turbo; the explicit Large-v3 stays Custom.
    assert app.transcribe_accuracy_combo.get() == label
    assert app.transcribe_lang_var.get() == language
    assert json.loads(Path(config.config_path()).read_text())["whisper_model"] == "large-v3"


def test_settings_only_preset_retains_tk_accuracy_choice(tk_preset_host):
    app, _languages, root = tk_preset_host
    presets.apply_settings(app, {"vad_enabled": False})
    root.update()
    assert app._accuracy_picked_level == "fast"
    assert app.transcribe_accuracy_combo.get() == "Fast"
    assert app.vad_enabled_var.get() is False


def test_failed_save_does_not_change_tk_controls(tk_preset_host, monkeypatch):
    app, _languages, root = tk_preset_host
    original = Path(config.config_path()).read_bytes()
    monkeypatch.setattr(presets, "save_config", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        presets.apply_settings(app, {"whisper_model": "large-v3", "language": "French"})
    root.update()
    assert app.transcribe_accuracy_combo.get() == "Fast"
    assert app.transcribe_lang_var.get() == "English"
    assert app._accuracy_picked_level == "fast"
    app.transcription_service.stop_all.assert_not_called()
    assert Path(config.config_path()).read_bytes() == original
