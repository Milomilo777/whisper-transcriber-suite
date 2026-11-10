"""Save, apply and remove local transcription presets."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any

from app.dpi import place_over
from app.domain.languages import SUBTITLE_LANGUAGES
from app.i18n import _
from core.config import LoadedConfig, _persistable_model_path, save_config
from core.model_manager import catalog_resolve_entry
from core.presets import PresetStore, capture_settings, valid_name

if TYPE_CHECKING:
    from app.app import App


def current_settings(app: App) -> dict[str, Any]:
    settings = capture_settings(app.app_config)
    settings["language"] = app.transcribe_lang_var.get()
    # Visible controls are authoritative, including a choice just made this session.
    settings["word_timestamps"] = bool(app.word_timestamps_var.get())
    settings["translate_to_english"] = bool(app.translate_var.get())
    settings["diarization_enabled"] = bool(app.diarization_var.get())
    if not app._engine_uses_whisper_model() or _persistable_model_path(app.app_config):
        settings.pop("whisper_model", None)
    return settings


def apply_settings(app: App, settings: dict[str, Any]) -> None:
    """Save before changing visible state; do not interrupt an active transcription."""
    if any(worker.get("task") is not None for worker in app.transcription_service.active_workers()):
        raise ValueError(_("Wait for running transcriptions to finish before applying a preset."))
    cleaned = capture_settings(settings)
    language = cleaned.pop("language", None)
    if language is not None and language not in {"Auto", *(name for name, _code in SUBTITLE_LANGUAGES)}:
        raise ValueError(_("This preset has an unknown language."))
    candidate = app.app_config.copy()
    slug = cleaned.get("whisper_model")
    if slug is not None:
        if not app._engine_uses_whisper_model():
            raise ValueError(_("This preset includes a Whisper model. Select a compatible Whisper engine first."))
        entry = catalog_resolve_entry(candidate, slug)
        if entry is None:
            raise ValueError(_("The preset's Whisper model is no longer in the model catalog."))
        if slug != candidate.get("whisper_model") or _persistable_model_path(candidate):
            candidate["model"] = entry
            candidate["model_path"] = ""
    candidate.update(cleaned)
    save_config(candidate)
    app.app_config.update(candidate)
    if isinstance(app.app_config, LoadedConfig) and isinstance(candidate, LoadedConfig):
        app.app_config._config_baseline = candidate._config_baseline
    # Idle workers snapshot configuration at spawn. Retire them for the next run.
    app.transcription_service.stop_all()
    for key, variable in (
        ("word_timestamps", app.word_timestamps_var),
        ("translate_to_english", app.translate_var),
        ("diarization_enabled", app.diarization_var),
        ("vad_enabled", app.vad_enabled_var),
        ("hotwords", app.hotwords_var),
    ):
        if key in cleaned:
            variable.set(cleaned[key])
    if "diarization_num_speakers" in cleaned:
        count = cleaned["diarization_num_speakers"]
        app.diarization_speakers_var.set("Auto" if count == -1 else str(count))
    if language is not None:
        app.transcribe_lang_var.set(language)
    app._sync_diarization_speakers_option()
    app._refresh_model_selector()
    app._sync_translate_option()
    app._refresh_language_model_hint()
    app._refresh_accuracy_row()


class PresetsDialog(tk.Toplevel):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.store = PresetStore()
        self.title(_("Transcription presets"))
        self.transient(app)
        self.columnconfigure(0, weight=1)
        self.name_var = tk.StringVar(self)
        ttk.Label(self, text=_(
            "Save current transcription options, language and catalog Whisper model.\n"
            "Engine, hardware, folders, accounts and network settings stay as they are.\n"
            "Custom model paths are excluded. Prompts and hotwords are saved locally."
        ), wraplength=520, justify="left").grid(row=0, column=0, padx=16, pady=12, sticky="w")
        self.combo = ttk.Combobox(self, textvariable=self.name_var, width=45)
        self.combo.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        self.combo.bind("<<ComboboxSelected>>", self._show_details)
        self.details_var = tk.StringVar(self, value=_("Choose a preset to see its settings, or type a new name."))
        ttk.Label(self, textvariable=self.details_var, wraplength=520, justify="left").grid(
            row=2, column=0, padx=16, pady=8, sticky="w")
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, padx=16, pady=12, sticky="ew")
        for text, command in ((_("Apply"), self._apply), (_("Save current"), self._save),
                              (_("Delete"), self._delete), (_("Close"), self.destroy)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _event: self.destroy())
        self._refresh()
        self.grab_set()
        place_over(self, app)

    def _error(self, error: Exception) -> None:
        messagebox.showerror(_("Preset not changed"), str(error), parent=self)

    def _refresh(self) -> None:
        try:
            self.combo.configure(values=sorted(self.store.load(), key=str.casefold))
        except (ValueError, OSError) as error:
            self._error(error)

    def _show_details(self, _event: object = None) -> None:
        try:
            settings = self.store.load().get(self.name_var.get(), {})
            self.details_var.set(_(
                "Language: {language}\nWhisper model: {model}\nOutput formats: {formats}\n"
                "Saved transcription options: {count}",
                language=settings.get("language", _("Current")),
                model=settings.get("whisper_model", _("Current")),
                formats=", ".join(settings.get("output_formats", [])) or _("Current"),
                count=len(settings),
            ))
        except (ValueError, OSError) as error:
            self._error(error)

    def _save(self) -> None:
        try:
            name = valid_name(self.name_var.get())
            exists = name in self.store.load()
            if exists and not messagebox.askyesno(_("Replace preset?"),
                    _("Replace this preset with the current transcription settings?"), parent=self, default="no"):
                return
            self.store.save(name, current_settings(self.app), replace=exists)
            self.name_var.set(name)
            self._refresh()
            self._show_details()
        except (ValueError, OSError) as error:
            self._error(error)

    def _apply(self) -> None:
        try:
            settings = self.store.load().get(self.name_var.get())
            if settings is None:
                raise ValueError(_("Choose a saved preset first."))
            apply_settings(self.app, settings)
            self.destroy()
        except (ValueError, OSError) as error:
            self._error(error)

    def _delete(self) -> None:
        try:
            name = self.name_var.get()
            if name not in self.store.load():
                raise ValueError(_("Choose a saved preset first."))
            if not messagebox.askyesno(_("Delete preset?"), _("Delete this saved preset?"), parent=self, default="no"):
                return
            self.store.delete(name)
            self.name_var.set("")
            self._refresh()
            self.details_var.set(_("Preset deleted. Current transcription settings are unchanged."))
        except (ValueError, OSError) as error:
            self._error(error)
