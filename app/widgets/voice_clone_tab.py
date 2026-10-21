"""The Clone Your Voice / Text to Voice tab.

Completely independent feature, two models: Kokoro (``core.tts_kokoro``)
speaks typed text in one of 53 ready-made voices; OmniVoice
(``core.voice_clone``) clones a voice from a few short recordings,
designs one from attributes, or picks one itself. Off by default (see ``core.hub.voice_clone_tab_enabled``);
its speech model downloads on demand the first time "Generate" is
actually used, never at tab-build time.

Kept out of ``tabs.py`` and modeled after ``live_tab.py``'s contract:
``build_voice_clone_tab(app, parent)`` assigns its widgets and vars onto
the ``App`` instance. Threading follows the same shape as the Live tab:
Start/Generate do subprocess work (spawning a worker, loading a ~2GB
model) so they run off the Tk thread; results come back through
``app.post_to_main``.

OmniVoice on a CPU takes many times the length of the speech it makes, so
Generate first plans the job (``core.tts_plan``): a long text gets a
confirm step with the time range on this computer, the speech length, the
file size and a free-disk check before anything runs, and the status label
always shows a concrete time estimate, never a bare "please wait".

A text longer than one piece is spoken piece by piece (``core.tts_job``):
every finished piece is kept on disk, the status shows the time left from
the speed measured so far, and Cancel, a crash or a power cut lose at most
the piece in progress. The next Generate with the same text, voice and speed
offers to continue the unfinished job.
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from app import rtl_layout
from app.dpi import px
from app.i18n import N_, _, ngettext, pgettext, translate
from app.theme import script_fonts
from app.widgets.error_dialog import show_error
from app.widgets.platform import open_async
from app.widgets.tabs import translated_choice_var
from app.widgets.tooltip import section_labelframe
from app.theme import tokens
from app.theme.bidi_display import ltr_base
from core import offline

logger = logging.getLogger(__name__)

_SAMPLE_SECONDS = 6

# Always visible on the tab: the rules replace the old one-time
# confirmation dialog, and consent is the per-voice tick below.
_RULES_TEXT = N_(
    "AI-generated audio. Clone only your own voice, or a voice whose speaker "
    "has given you clear permission. Do not impersonate anyone, and do not "
    "make misleading audio of real people."
)
_CONSENT_TICK_TEXT = N_("I have the speaker's permission to clone this voice (or it is my own)")

# Shown when the OmniVoice install actually starts (the first Generate).
_OMNI_INSTALL_STATUS = N_(
    "Downloading OmniVoice (about 2 GB, one time; needs internet, a few "
    "minutes to over an hour depending on the connection). After that it "
    "runs offline..."
)

_KOKORO_DOWNLOAD_LINE = N_("The Kokoro voice model downloads first (about 350 MB, one time).")
_OMNI_DOWNLOAD_LINE = N_("OmniVoice downloads first (about 2 GB, one time).")

# The model picker shows these (translated); the config stores "kokoro" / "omnivoice".
_ENGINE_KOKORO = N_("Kokoro — 53 ready-made voices, 9 languages (fast; ~350 MB download)")
_ENGINE_OMNI = N_("OmniVoice — clone any voice, or design one (slow on CPU; ~2 GB download)")

_MODE_CLONE = "clone"
_MODE_DESIGN = "design"
_MODE_AUTO = "auto"

# Voice-design attributes: the model takes the English value (core.voice_clone.DESIGN_*),
# the picker shows the label. A value missing here is shown capitalised, in English.
_DESIGN_LABELS = {
    "male": N_("Male"),
    "female": N_("Female"),
    "child": N_("Child"),
    "teenager": N_("Teenager"),
    "young adult": N_("Young adult"),
    "middle-aged": N_("Middle-aged"),
    "elderly": N_("Elderly"),
    "very low pitch": N_("Very low pitch"),
    "low pitch": N_("Low pitch"),
    "moderate pitch": N_("Moderate pitch"),
    "high pitch": N_("High pitch"),
    "very high pitch": N_("Very high pitch"),
    "american accent": N_("American accent"),
    "british accent": N_("British accent"),
    "australian accent": N_("Australian accent"),
    "canadian accent": N_("Canadian accent"),
    "indian accent": N_("Indian accent"),
    "chinese accent": N_("Chinese accent"),
    "korean accent": N_("Korean accent"),
    "japanese accent": N_("Japanese accent"),
    "portuguese accent": N_("Portuguese accent"),
    "russian accent": N_("Russian accent"),
}


def _any_label() -> str:
    """The "no preference" entry of each voice-design picker."""
    return pgettext("voice design", "Any")


def _auto_lang_label() -> str:
    """The language picker's first entry: OmniVoice detects the language itself."""
    return _("Auto-detect")


def _design_label(value: str) -> str:
    """What the design picker shows for the model's attribute ``value``."""
    label = _DESIGN_LABELS.get(value)
    return translate(label) if label is not None else value[:1].upper() + value[1:]


def _engine_label(kokoro: bool) -> str:
    return translate(_ENGINE_KOKORO if kokoro else _ENGINE_OMNI)


def _engine_labels() -> dict[str, str]:
    """The engine picker: stored value ("kokoro" / "omnivoice") -> label shown, in order."""
    return {"kokoro": _engine_label(True), "omnivoice": _engine_label(False)}


def _language_labels() -> dict[str, str]:
    """The language picker: stored value ("" = auto-detect, else the English name of
    ``SUBTITLE_LANGUAGES``) -> label shown, in order."""
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    from app.domain.languages import subtitle_language_label

    labels = {"": _auto_lang_label()}
    labels.update((n, subtitle_language_label(n)) for n, c in _LANGS if c)
    return labels

_PREVIEW_TEXT = {
    "US English": "Hello! This is how I sound. I can read any text you type.",
    "UK English": "Hello! This is how I sound. I can read any text you type.",
    "Spanish": "¡Hola! Así es como sueno. Puedo leer cualquier texto.",
    "French": "Bonjour ! Voici ma voix. Je peux lire n'importe quel texte.",
    "Hindi": "नमस्ते! मेरी आवाज़ ऐसी है।",
    "Italian": "Ciao! Questa è la mia voce. Posso leggere qualsiasi testo.",
    "Japanese": "こんにちは。これが私の声です。",
    "Portuguese": "Olá! Esta é a minha voz. Posso ler qualquer texto.",
    "Chinese": "你好！这就是我的声音。",
}


@dataclass
class _JobPlan:
    """One Generate press, planned before it starts (see ``core.tts_plan``)."""
    engine: str            # "kokoro" or "omnivoice"
    text: str
    speed: float
    device: str
    version: str
    hardware: str
    installed: bool        # model (Kokoro) / package (OmniVoice) already on disk
    calibration: Any       # core.tts_plan.Calibration | None
    estimate: Any          # core.tts_plan.Estimate
    disk: Any              # core.tts_plan.DiskCheck
    measure_failed: bool = False
    #: Voice settings that identify a piece-by-piece job (None: one pass).
    voice: "dict[str, Any] | None" = None
    job: Any = None        # core.tts_job.Job | None
    resume_done: int = 0   # pieces an earlier run of this job finished
    #: The voice controls as they were at Generate (voice, mode, clips,
    #: language, design, consent): the job is spoken with these, whatever
    #: the controls show by the time Start is pressed.
    settings: "dict[str, Any] | None" = None


def _sweep_scratch_dirs() -> None:
    from core.voice_clone import sweep_old_session_dirs
    sweep_old_session_dirs()


def _start_sweep() -> None:
    """The sweep deletes whole folders (up to gigabytes): never on the Tk thread."""
    from core._threads import safe_thread
    safe_thread(_sweep_scratch_dirs, name="voice-clone-sweep")


def _combo(parent: Any, var: Any, values: "list[str]", width: int = 22) -> ttk.Combobox:
    return ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=width)


def build_voice_clone_tab(app: Any, parent: Any) -> None:
    """Construct the Clone Your Voice / Text to Voice tab onto ``parent``.

    Layout follows the reference UIs of the two engines it wraps -- the
    Kokoro-82M demo (voice picker + speed + one Generate button) and
    OmniVoice's own demo (Voice Clone / Voice Design / Auto modes, design
    attributes as dropdowns, language + speed) -- so the controls look
    like what users of those models already know.
    """
    from core import tts_kokoro, tts_plan
    from core import voice_clone as _vc

    app.vc_samples = []
    app.vc_worker = None
    app.vc_last_output = None
    app.vc_recorder = None
    app.vc_cancel_event = None
    app.vc_recording_after_id = None
    app.vc_status_var = tk.StringVar(value=_("Idle."))
    cfg = app.app_config.setdefault("voice_clone", {})
    # The *_value_var variables keep stable values ("kokoro", an English language name); the
    # pickers show translated labels through translated_choice_var.
    app.vc_engine_value_var = tk.StringVar(
        value="omnivoice" if cfg.get("engine") == "omnivoice" else "kokoro")
    app.vc_engine_var = translated_choice_var(parent, app.vc_engine_value_var, _engine_labels())
    app.vc_mode_var = tk.StringVar(value=cfg.get("mode") or _MODE_CLONE)
    voice_labels = [v.label for v in tts_kokoro.VOICES]
    saved_voice = tts_kokoro.voice_by_key(str(cfg.get("kokoro_voice") or tts_kokoro.DEFAULT_VOICE))
    app.vc_voice_var = tk.StringVar(value=saved_voice.label)
    app.vc_gender_var = tk.StringVar(value=_any_label())
    app.vc_age_var = tk.StringVar(value=_any_label())
    app.vc_pitch_var = tk.StringVar(value=_any_label())
    app.vc_accent_var = tk.StringVar(value=_any_label())
    app.vc_whisper_var = tk.BooleanVar(value=False)
    app.vc_lang_value_var = tk.StringVar(value="")
    app.vc_lang_var = translated_choice_var(parent, app.vc_lang_value_var, _language_labels())
    app.vc_speed_var = tk.DoubleVar(value=1.0)
    app.vc_count_var = tk.StringVar(value="")
    # Never restored from the config: every session (and every change of
    # the reference clips) starts unticked.
    app.vc_consent_var = tk.BooleanVar(value=False)
    app.vc_busy = False
    app.vc_plan = None
    app.vc_planning = False
    app.vc_confirm_open = False
    app.vc_measuring = False
    app.vc_confirm_var = tk.StringVar(value="")

    # Best-effort sweep of aged-out scratch dirs from earlier sessions.
    app.after(2000, _start_sweep)

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)

    # ── Model ───────────────────────────────────────────────────────────
    eng = section_labelframe(
        parent, pgettext("speech model", "Model"),
        _("Kokoro speaks in one of 53 ready-made voices and is fast on any "
          "computer. OmniVoice can clone a voice from a short recording, or "
          "design a new one from a description (gender, age, pitch, accent); "
          "it is much slower without a supported graphics card. Each model "
          "downloads once, the first time it is used."),
    )
    eng.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 6))
    eng.columnconfigure(1, weight=1)
    ttk.Label(eng, text=pgettext("speech model", "Model:")).grid(
        row=0, column=0, sticky="e", padx=8, pady=6)
    # Index 0 is Kokoro, 1 OmniVoice; _is_kokoro reads the stored value, not the label.
    app.vc_engine_combo = _combo(eng, app.vc_engine_var, list(_engine_labels().values()), 70)
    app.vc_engine_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
    app.vc_engine_combo.bind("<<ComboboxSelected>>", lambda _e: _sync_engine(app))
    app.vc_engine_state = ttk.Label(eng, foreground=tokens.themed(tokens.TEXT_MUTED))
    app.vc_engine_state.grid(row=1, column=1, sticky="w", padx=8, pady=(0, 6))

    # ── Voice ───────────────────────────────────────────────────────────
    voice = section_labelframe(
        parent, _("Voice"),
        _("Kokoro: pick a ready-made voice and press Preview to hear it. "
          "OmniVoice: clone a voice from 1-3 short recordings (3-10 seconds "
          "each), design one from its attributes, or let the model choose."),
    )
    voice.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 6))
    voice.columnconfigure(0, weight=1)

    # Kokoro: ready-made voices.
    app.vc_kokoro_frame = ttk.Frame(voice)
    app.vc_kokoro_frame.columnconfigure(1, weight=1)
    ttk.Label(app.vc_kokoro_frame, text=_("Voice:")).grid(
        row=0, column=0, sticky="e", padx=8, pady=6)
    app.vc_voice_combo = _combo(app.vc_kokoro_frame, app.vc_voice_var, voice_labels, 44)
    app.vc_voice_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
    app.vc_voice_combo.bind("<<ComboboxSelected>>", lambda _e: _save_prefs(app))
    app.vc_preview_btn = ttk.Button(
        app.vc_kokoro_frame, text=_("▶ Preview"), command=lambda: _preview(app))
    app.vc_preview_btn.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=6)

    # OmniVoice: mode switch + one panel per mode.
    app.vc_omni_frame = ttk.Frame(voice)
    app.vc_omni_frame.columnconfigure(0, weight=1)
    modes = ttk.Frame(app.vc_omni_frame)
    modes.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    app.vc_mode_radios = []
    for text, value in ((_("Clone my voice / a recording"), _MODE_CLONE),
                        (_("Design a voice"), _MODE_DESIGN),
                        (_("Let the model choose"), _MODE_AUTO)):
        radio = ttk.Radiobutton(modes, text=text, value=value, variable=app.vc_mode_var,
                                command=lambda: _sync_engine(app))
        radio.pack(side="left", padx=(0, 16))
        app.vc_mode_radios.append(radio)

    app.vc_clone_frame = ttk.Frame(app.vc_omni_frame)
    app.vc_clone_frame.columnconfigure(0, weight=1)
    app.vc_samples_listbox = tk.Listbox(app.vc_clone_frame, height=3)
    app.vc_samples_listbox.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 4))
    ref_btns = ttk.Frame(app.vc_clone_frame)
    ref_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
    app.vc_record_btn = ttk.Button(
        ref_btns, text=_("● Record sample ({seconds}s)", seconds=_SAMPLE_SECONDS),
        command=lambda: _record_sample(app),
    )
    app.vc_record_btn.pack(side="left")
    app.vc_load_btn = ttk.Button(ref_btns, text=_("Load audio file..."),
                                 command=lambda: _load_sample(app))
    app.vc_load_btn.pack(side="left", padx=(8, 0))
    app.vc_remove_btn = ttk.Button(ref_btns, text=_("Remove selected"),
                                   command=lambda: _remove_sample(app))
    app.vc_remove_btn.pack(side="left", padx=(8, 0))
    app.vc_consent_check = ttk.Checkbutton(
        app.vc_clone_frame, text=translate(_CONSENT_TICK_TEXT), variable=app.vc_consent_var,
        command=lambda: _sync_generate_state(app))
    app.vc_consent_check.grid(row=2, column=0, sticky="w", padx=8, pady=(0, 6))

    app.vc_design_frame = ttk.Frame(app.vc_omni_frame)
    app.vc_design_widgets = []
    for col, (label, var, values) in enumerate((
        (_("Gender"), app.vc_gender_var, _vc.DESIGN_GENDERS),
        (_("Age"), app.vc_age_var, _vc.DESIGN_AGES),
        (_("Pitch"), app.vc_pitch_var, _vc.DESIGN_PITCHES),
        (_("Accent (English)"), app.vc_accent_var, _vc.DESIGN_ACCENTS),
    )):
        ttk.Label(app.vc_design_frame, text=label).grid(row=0, column=col, sticky="w", padx=8)
        combo = _combo(app.vc_design_frame, var,
                       [_any_label()] + [_design_label(v) for v in values], 17)
        combo.grid(row=1, column=col, sticky="w", padx=8, pady=(0, 6))
        app.vc_design_widgets.append(combo)
    whisper = ttk.Checkbutton(app.vc_design_frame, text=pgettext("voice style", "Whisper"),
                              variable=app.vc_whisper_var)
    whisper.grid(row=1, column=4, sticky="w", padx=8, pady=(0, 6))
    app.vc_design_widgets.append(whisper)

    app.vc_auto_label = ttk.Label(
        app.vc_omni_frame, foreground=tokens.themed(tokens.TEXT_MUTED),
        text=_("OmniVoice picks a natural voice by itself -- no recording needed."))

    # ── Text ───────────────────────────────────────────────────────────
    txt = section_labelframe(
        parent, _("Text to speak"),
        _("Up to {count} characters (about 90 minutes of "
          "speech; Advanced settings can lift the limit). Before a long text "
          "starts, the tab shows how long it takes on this computer, how big "
          "the file gets and whether the disk has room. A long text is spoken "
          "piece by piece and joined into one audio file at the end: Cancel "
          "keeps the finished pieces, and pressing Generate again with the same "
          "text and voice continues the job.", count=f"{tts_plan.MAX_TEXT_CHARS:,}"),
    )
    txt.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 6))
    txt.columnconfigure(0, weight=1)
    txt.rowconfigure(0, weight=1)
    app.vc_text = tk.Text(txt, wrap="word", height=6, undo=True)
    script_fonts.use_text_font(app.vc_text)
    app.vc_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=(8, 4))
    bar = ttk.Scrollbar(txt, orient="vertical", command=app.vc_text.yview)
    bar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=(8, 4))
    app.vc_text.configure(yscrollcommand=bar.set)
    app.vc_text.bind("<<Modified>>", lambda _e: _on_text_modified(app))

    opts = ttk.Frame(txt)
    opts.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
    app.vc_lang_label = ttk.Label(opts, text=_("Language:"))
    app.vc_lang_label.pack(side="left")
    app.vc_lang_combo = _combo(opts, app.vc_lang_var, list(_language_labels().values()), 18)
    app.vc_lang_combo.pack(side="left", padx=(6, 18))
    # The language picks the font of Han lines: retag when it changes, not only on the next edit.
    # The trace sits on the stored value: Tcl runs the newest trace first, so one on the shown
    # label would read the value before translated_choice_var has copied it.
    app.vc_lang_value_var.trace_add("write", lambda *_a: _retag_text(app))
    ttk.Label(opts, text=_("Speed:")).pack(side="left")
    app.vc_speed_scale = ttk.Scale(
        opts, from_=0.5, to=2.0, variable=app.vc_speed_var, length=px(140),
        command=lambda _v: app.vc_speed_label.configure(
            text=_speed_text(app.vc_speed_var.get())))
    app.vc_speed_scale.pack(side="left", padx=6)
    app.vc_speed_label = ttk.Label(opts, text=_speed_text(1.0), width=6)
    app.vc_speed_label.pack(side="left")
    ttk.Label(opts, textvariable=app.vc_count_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(side="right")

    # ── Confirm step (long texts only; hidden until a plan needs it) ────
    app.vc_confirm_frame = ttk.Labelframe(parent, text=_("Long text: check before starting"))
    app.vc_confirm_frame.columnconfigure(0, weight=1)
    app.vc_confirm_label = ttk.Label(
        app.vc_confirm_frame, textvariable=app.vc_confirm_var, justify="left", wraplength=px(760))
    app.vc_confirm_label.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 4))
    confirm_btns = ttk.Frame(app.vc_confirm_frame)
    confirm_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
    app.vc_confirm_start_btn = ttk.Button(
        confirm_btns, text=_("Start"), style="Accent.TButton", command=lambda: _confirm_start(app))
    app.vc_confirm_measure_btn = ttk.Button(
        confirm_btns, text=_("Measure this computer's speed"), style="Accent.TButton",
        command=lambda: _measure_speed(app))
    app.vc_confirm_restart_btn = ttk.Button(
        confirm_btns, text=_("Start over"), command=lambda: _confirm_restart(app))
    app.vc_confirm_cancel_btn = ttk.Button(
        confirm_btns, text=_("Cancel"), command=lambda: _cancel_generate(app))
    app.vc_confirm_start_btn.pack(side="left")
    app.vc_confirm_measure_btn.pack(side="left")
    app.vc_confirm_cancel_btn.pack(side="left", padx=(8, 0))
    app.vc_confirm_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 6))
    app.vc_confirm_frame.grid_remove()

    # ── Generate ──────────────────────────────────────────────────────
    out = ttk.Frame(parent)
    out.grid(row=4, column=0, sticky="ew", padx=15, pady=(0, 4))
    out.columnconfigure(5, weight=1)
    app.vc_generate_btn = ttk.Button(
        out, text=_("Generate speech"), style="Accent.TButton", command=lambda: _generate(app))
    app.vc_generate_btn.grid(row=0, column=0, sticky="w")
    app.vc_cancel_btn = ttk.Button(
        out, text=_("Cancel"), command=lambda: _cancel_generate(app), state="disabled")
    app.vc_cancel_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
    app.vc_play_btn = ttk.Button(
        out, text=_("▶ Play"), command=lambda: _play(app), state="disabled")
    app.vc_play_btn.grid(row=0, column=2, sticky="w", padx=(8, 0))
    app.vc_save_btn = ttk.Button(
        out, text=_("Save As..."), command=lambda: _save(app), state="disabled")
    app.vc_save_btn.grid(row=0, column=3, sticky="w", padx=(8, 0))
    app.vc_progress = ttk.Progressbar(out, mode="determinate", maximum=100, length=px(180))
    app.vc_progress.grid(row=0, column=4, sticky="w", padx=(16, 0))
    ttk.Label(parent, textvariable=app.vc_status_var, foreground=tokens.themed(tokens.TEXT_MUTED)).grid(
        row=5, column=0, sticky="w", padx=15, pady=(0, 2))
    app.vc_rules_label = ttk.Label(parent, text=translate(_RULES_TEXT), foreground=tokens.themed(tokens.TEXT_MUTED), wraplength=px(760))
    app.vc_rules_label.grid(row=6, column=0, sticky="w", padx=15, pady=(0, 12))

    _sync_engine(app)
    _on_text_modified(app)


def _speed_text(speed: float) -> str:
    return _("{speed}x", speed=f"{speed:.2f}")


def _is_kokoro(app: Any) -> bool:
    # The stored value, never the label: the label depends on the interface language.
    return app.vc_engine_value_var.get() == "kokoro"


def _sync_engine(app: Any) -> None:
    """Show only the controls the selected model/mode uses."""
    from core import tts_kokoro

    kokoro = _is_kokoro(app)
    if kokoro:
        app.vc_omni_frame.grid_remove()
        app.vc_kokoro_frame.grid(row=0, column=0, sticky="ew")
        app.vc_engine_state.configure(
            text=_("Kokoro-82M (Apache-2.0), runs locally -- downloaded.")
            if tts_kokoro.is_downloaded()
            else _("Kokoro-82M (Apache-2.0), runs locally -- not downloaded yet "
                   "(~{size} MB, downloads on first use).",
                   size=tts_kokoro.APPROX_DOWNLOAD_MB))
    else:
        from core import voice_clone as _vc

        app.vc_kokoro_frame.grid_remove()
        app.vc_omni_frame.grid(row=0, column=0, sticky="ew")
        mode = app.vc_mode_var.get()
        for frame, m in ((app.vc_clone_frame, _MODE_CLONE),
                         (app.vc_design_frame, _MODE_DESIGN),
                         (app.vc_auto_label, _MODE_AUTO)):
            if mode == m:
                frame.grid(row=1, column=0, sticky="ew" if m != _MODE_AUTO else "w",
                           padx=(0 if m != _MODE_AUTO else 8), pady=(0, 6))
            else:
                frame.grid_remove()
        app.vc_engine_state.configure(
            text=_("OmniVoice (Apache-2.0, k2-fsa), runs locally -- installed.")
            if _vc.is_available()
            else _("OmniVoice (Apache-2.0, k2-fsa), runs locally -- not downloaded yet "
                   "(~2 GB, downloads on first use)."))
    _sync_lock(app)
    _sync_generate_state(app)
    _save_prefs(app)


def _sync_lock(app: Any) -> None:
    """The voice controls (clips, consent, mode, voice, language, design)
    are locked while a job is planned, confirmed or running: the job is
    spoken with the settings taken at Generate, so the controls must keep
    showing them. Kokoro's voice decides the language, so OmniVoice's
    language picker is off for Kokoro."""
    locked = bool(app.vc_busy or app.vc_confirm_open)
    plain = "disabled" if locked else "normal"
    picker = "disabled" if locked else "readonly"
    for widget in (app.vc_load_btn, app.vc_remove_btn, app.vc_consent_check,
                   *app.vc_mode_radios):
        widget.configure(state=plain)
    for widget in app.vc_design_widgets:
        widget.configure(state=picker if isinstance(widget, ttk.Combobox) else plain)
    app.vc_voice_combo.configure(state=picker)
    app.vc_lang_combo.configure(state="disabled" if _is_kokoro(app) else picker)
    # A recording in progress keeps its own button off.
    app.vc_record_btn.configure(
        state="disabled" if locked or app.vc_recorder is not None else "normal")


def _consent_required(app: Any) -> bool:
    """True when Generate would clone from reference audio (OmniVoice, clone mode)."""
    return not _is_kokoro(app) and app.vc_mode_var.get() == _MODE_CLONE


def _sync_generate_state(app: Any) -> None:
    """Generate is off during a run, and while a clone lacks the permission tick.
    Voice design, the model's own voice and Kokoro need no tick."""
    blocked = app.vc_busy or (_consent_required(app) and not app.vc_consent_var.get())
    app.vc_generate_btn.configure(state="disabled" if blocked else "normal")


def _reset_consent(app: Any) -> bool:
    """Untick the permission box (the reference clips changed, so the tick no
    longer covers them). Returns True when it was ticked."""
    was_ticked = bool(app.vc_consent_var.get())
    app.vc_consent_var.set(False)
    _sync_generate_state(app)
    return was_ticked


def _samples_changed_status(app: Any, untick: bool) -> str:
    count = len(app.vc_samples)
    # Both English forms keep the old "(s)" text; other languages get real plural forms.
    status = ngettext("{n} reference sample(s).", "{n} reference sample(s).", count)
    if untick:
        status += " " + _("The clips changed: tick the permission box again.")
    return status


def _save_prefs(app: Any) -> None:
    cfg = app.app_config.setdefault("voice_clone", {})
    new = {
        "engine": "kokoro" if _is_kokoro(app) else "omnivoice",
        "mode": app.vc_mode_var.get(),
        "kokoro_voice": _selected_voice(app).key,
    }
    if all(cfg.get(k) == v for k, v in new.items()):
        return
    cfg.update(new)
    from core.config import save_config
    try:
        save_config(app.app_config)
    except Exception:  # noqa: BLE001
        logger.exception("Could not save the voice tab preferences")


def _selected_voice(app: Any) -> Any:
    from core import tts_kokoro

    label = app.vc_voice_var.get()
    return next((v for v in tts_kokoro.VOICES if v.label == label),
                tts_kokoro.voice_by_key(tts_kokoro.DEFAULT_VOICE))


def _text_limit(app: Any) -> "int | None":
    from core import tts_plan

    return tts_plan.text_limit(getattr(app, "app_config", None))


def _on_text_modified(app: Any) -> None:
    try:
        app.vc_text.edit_modified(False)
        n = len(app.vc_text.get("1.0", "end-1c"))
    except Exception:  # noqa: BLE001
        return
    limit = _text_limit(app)
    # Both English forms are the same text as before; other languages get real plural forms.
    app.vc_count_var.set(
        ngettext("{count} characters", "{count} characters", n, count=f"{n:,}")
        if limit is None
        else ngettext("{count} / {limit} characters", "{count} / {limit} characters", limit,
                      count=f"{n:,}", limit=f"{limit:,}"))
    _schedule_retag(app)


# Re-tagging the whole box takes about 0.3 s for 100k characters of Myanmar text, so while the
# user types it runs once per pause rather than on every keystroke.
_RETAG_DELAY_MS = 150


def _schedule_retag(app: Any) -> None:
    pending = getattr(app, "_vc_retag_after", None)
    if pending is not None:
        try:
            app.vc_text.after_cancel(pending)
        except Exception:  # noqa: BLE001 - already ran
            pass

    def _run() -> None:
        app._vc_retag_after = None
        try:
            _retag_text(app)
        except tk.TclError:
            pass  # the text box was closed in the meantime

    app._vc_retag_after = app.vc_text.after(_RETAG_DELAY_MS, _run)


def _retag_text(app: Any) -> None:
    script_fonts.tag_script_lines(app.vc_text, language=_language_code(app))


def _design_instruct(app: Any) -> str:
    from core.voice_clone import build_instruct

    from core import voice_clone as _vc

    def val(var: Any, values: "tuple[str, ...]") -> "str | None":
        """The model's English value for the label the picker shows."""
        label = var.get()
        if label == _any_label():
            return None
        return next((v for v in values if _design_label(v) == label), label.lower())

    return build_instruct(val(app.vc_gender_var, _vc.DESIGN_GENDERS),
                          val(app.vc_age_var, _vc.DESIGN_AGES),
                          val(app.vc_pitch_var, _vc.DESIGN_PITCHES),
                          val(app.vc_accent_var, _vc.DESIGN_ACCENTS),
                          whisper=bool(app.vc_whisper_var.get()))


def _language_code(app: Any) -> str:
    """The picked language's codes as the language list holds them
    ("zh-Hans,zh-CN" for Chinese); the font tagging reads them all."""
    name = app.vc_lang_value_var.get()  # the English name; "" = auto-detect
    if not name:
        return ""
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    return next((c for n, c in _LANGS if n == name), "")


def _omni_language(app: Any) -> str:
    """One plain language code for OmniVoice ("zh" for "zh-Hans,zh-CN"):
    it takes a language, not the list of script and region variants."""
    codes = _language_code(app)
    return codes.split(",")[0].strip().split("-")[0].lower()


# --------------------------------------------------------------- samples


def _refresh_samples_listbox(app: Any) -> None:
    app.vc_samples_listbox.delete(0, "end")
    for path in app.vc_samples:
        app.vc_samples_listbox.insert("end", ltr_base(os.path.basename(path)))


def _validate_and_add_sample(app: Any, path: str) -> None:
    """Validate *path* off the Tk thread, then apply the result on it.

    ``validate_reference_sample`` shells out to ffprobe with up to a 60s
    timeout (see ``get_duration``'s own comment) -- a file picked from a
    stalled network mount would otherwise freeze the whole UI for that
    long. The cheap sample-count check still runs synchronously here so
    an over-limit click doesn't even spawn a thread.
    """
    from core.voice_clone import MAX_REFERENCE_SAMPLES, validate_reference_sample

    if len(app.vc_samples) >= MAX_REFERENCE_SAMPLES:
        show_error(
            app, _("Sample limit reached"),
            _("You can use up to {count} reference clips. "
              "Remove one before adding another.", count=MAX_REFERENCE_SAMPLES),
        )
        return

    def worker() -> None:
        issue = validate_reference_sample(path)
        use_path = path
        if issue is not None and issue.too_long:
            from core.voice_clone import session_work_dir, trim_reference_sample

            trimmed_path = os.path.join(
                session_work_dir(), "trimmed_" + os.path.basename(path)
            )
            try:
                trim_reference_sample(path, trimmed_path)
                use_path = trimmed_path
                issue = None  # trimmed clip is within range -- nothing left to warn about
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Voice-clone reference trim failed; using the untrimmed clip"
                )
                # Fall through with the original clip + its "too long"
                # warning, same as before this auto-trim existed.
        app.post_to_main(lambda: _finish_adding_sample(app, use_path, issue))

    from core._threads import safe_thread
    safe_thread(worker, name="voice-clone-validate-sample")


def _finish_adding_sample(app: Any, path: str, issue: "Any") -> None:
    from core.voice_clone import MAX_REFERENCE_SAMPLES

    # Re-check the limit here (not just in _validate_and_add_sample): two
    # validations can be in flight at once (e.g. a Record in progress and
    # a Load dialog started while it runs), and this is the only point
    # where the actual append happens -- always on the Tk thread, so this
    # check-then-append is race-free even if both validations land here.
    if len(app.vc_samples) >= MAX_REFERENCE_SAMPLES:
        show_error(
            app, _("Sample limit reached"),
            _("You can use up to {count} reference clips. "
              "Remove one before adding another.", count=MAX_REFERENCE_SAMPLES),
        )
        return
    if issue is not None:
        title = _("Could not use this clip") if issue.blocking else _("This clip may not work well")
        show_error(app, title, issue.message)
        if issue.blocking:
            return
        # Still added -- the user may know better than the heuristic
        # (e.g. a clip a hair under/over the recommended range).
    app.vc_samples.append(path)
    _refresh_samples_listbox(app)
    app.vc_status_var.set(_samples_changed_status(app, _reset_consent(app)))


def _record_sample(app: Any) -> None:
    from core.recorder import Recorder, mic_availability_reason, mic_available
    from core.voice_clone import MAX_REFERENCE_SAMPLES, session_work_dir

    if not mic_available():
        show_error(
            app, _("Cannot record"), _("This computer cannot capture microphone audio yet."),
            detail=mic_availability_reason(),
        )
        return
    if len(app.vc_samples) >= MAX_REFERENCE_SAMPLES:
        show_error(
            app, _("Sample limit reached"),
            _("You can use up to {count} reference clips.", count=MAX_REFERENCE_SAMPLES),
        )
        return

    out_path = os.path.join(
        session_work_dir(), f"sample_{len(app.vc_samples) + 1}.wav"
    )
    recorder = Recorder(output_path=out_path, mode="mic")
    try:
        recorder.start()
    except Exception as e:  # noqa: BLE001
        show_error(app, _("Could not start recording"), str(e))
        return
    app.vc_recorder = recorder
    app.vc_record_btn.configure(state="disabled")
    _tick_recording(app, _SAMPLE_SECONDS)


def _tick_recording(app: Any, seconds_left: int) -> None:
    app.vc_status_var.set(_("Recording... {seconds}s", seconds=seconds_left))
    if seconds_left <= 0:
        app.vc_recording_after_id = None
        _finish_recording(app)
        return
    app.vc_recording_after_id = app.after(
        1000, lambda: _tick_recording(app, seconds_left - 1)
    )


def _finish_recording(app: Any) -> None:
    recorder = app.vc_recorder
    app.vc_recorder = None
    _sync_lock(app)  # stays off when a job started while this was recording
    if recorder is None:
        return
    try:
        path = recorder.stop()
    except Exception as e:  # noqa: BLE001
        show_error(app, _("Recording failed"), str(e))
        app.vc_status_var.set(_("Idle."))
        return
    _validate_and_add_sample(app, path)


def _load_sample(app: Any) -> None:
    path = filedialog.askopenfilename(
        parent=app, title=_("Load reference voice clip"),
        filetypes=[(_("Audio"), "*.wav *.mp3 *.m4a *.flac *.ogg"), (_("All files"), "*.*")],
    )
    if not path:
        return
    _validate_and_add_sample(app, path)


def _remove_sample(app: Any) -> None:
    sel = app.vc_samples_listbox.curselection()
    if not sel:
        return
    idx = sel[0]
    del app.vc_samples[idx]
    _refresh_samples_listbox(app)
    app.vc_status_var.set(_samples_changed_status(app, _reset_consent(app)))


# --------------------------------------------------------------- generate


def _set_busy(app: Any, busy: bool) -> None:
    app.vc_busy = busy
    _sync_generate_state(app)
    app.vc_preview_btn.configure(state="disabled" if busy else "normal")
    app.vc_cancel_btn.configure(state="normal" if busy else "disabled")
    app.vc_engine_combo.configure(state="disabled" if busy else "readonly")
    _sync_lock(app)
    if busy:
        app.vc_progress.configure(value=0)


def _set_progress(app: Any, fraction: float) -> None:
    app.post_to_main(lambda: app.vc_progress.configure(value=max(0.0, min(1.0, fraction)) * 100))


def _preview(app: Any) -> None:
    """Speak a short sample sentence in the selected Kokoro voice."""
    voice = _selected_voice(app)
    app.vc_plan = None  # a preview is not a job: no plan, no speed measurement
    _generate_kokoro(app, _PREVIEW_TEXT.get(voice.language, _PREVIEW_TEXT["US English"]),
                     play_when_done=True)


def _omni_refused(app: Any) -> bool:
    """True (and the reason shown) when an OmniVoice clone cannot start yet."""
    if app.vc_mode_var.get() != _MODE_CLONE:
        return False
    if not app.vc_samples:
        show_error(app, _("No reference voice"),
                   _('Record or load at least one reference clip first, or '
                     'choose "{design}" / "{auto}".',
                     design=_("Design a voice"), auto=_("Let the model choose")))
        return True
    if not app.vc_consent_var.get():
        # Generate is disabled until the tick; this guards other callers.
        app.vc_status_var.set(_("Tick the permission box under the reference clips first."))
        return True
    return False


def _kokoro_refused(app: Any, text: str) -> bool:
    """True (and the reason shown) when the text is mostly in a script no
    Kokoro voice reads: Kokoro would make no usable speech, after a 350 MB
    download the first time."""
    from core import tts_kokoro

    script = tts_kokoro.unsupported_script(text)
    if script is None:
        return False
    show_error(
        app, _("Kokoro has no voice for this text"),
        _("Most of this text is in the {script} script. Kokoro's voices speak "
          "{languages}. Choose OmniVoice under Model for this language.",
          script=script, languages=tts_kokoro.LANGUAGE_NAMES),
    )
    return True


def _offer_kept_clips(app: Any, text: str, speed: float) -> bool:
    """A clone with no clips in the list: when an earlier job for this exact
    text kept its reference clips (``core.tts_job.Job.keep_references``),
    put them back in the list for the user to tick, and return True (this
    press only offers them). The list is not saved between sessions and a
    recorded clip's scratch folder is swept, so this is how an unfinished
    clone job continues after a restart."""
    from core import tts_job

    if app.vc_mode_var.get() != _MODE_CLONE or app.vc_samples:
        return False
    found = tts_job.find_kept_references(
        "omnivoice", text, {"mode": _MODE_CLONE, "language": _omni_language(app)}, speed)
    if found is None:
        return False
    clips, finished = found
    app.vc_samples[:] = clips
    _refresh_samples_listbox(app)
    _reset_consent(app)
    app.vc_status_var.set(
        _("The reference clips kept with the finished job for this text are back in the "
          "list: tick the permission box, then press Generate again.") if finished
        else _("The reference clips kept with the unfinished job for this text are back in the "
               "list: tick the permission box, then press Generate again."))
    return True


def _generate(app: Any) -> None:
    """Generate pressed: check the text, then plan the job off the Tk thread
    (the OmniVoice device check imports torch). A short job starts at once;
    a long one gets the confirm step first."""
    from core import tts_plan

    text = app.vc_text.get("1.0", "end").strip()
    if not text:
        show_error(app, _("No text"), _("Type the text you want spoken."))
        return
    limit = _text_limit(app)
    if limit is not None and len(text) > limit:
        show_error(
            app, _("Text too long"),
            _("Text is {count} characters; the limit for one job is "
              "{limit} (about 90 minutes of speech). Split the text, or turn "
              'on "No text length limit" under Advanced settings > App behaviour.',
              count=f"{len(text):,}", limit=f"{limit:,}"),
        )
        return
    kokoro = _is_kokoro(app)
    if kokoro and _kokoro_refused(app, text):
        return
    speed = float(app.vc_speed_var.get() or 1.0)
    if not kokoro and _offer_kept_clips(app, text, speed):
        return
    if not kokoro and _omni_refused(app):
        return
    if (not kokoro and app.vc_mode_var.get() != _MODE_CLONE
            and len(text) > tts_plan.MAX_PASS_CHARS):
        show_error(
            app, _("Text too long for this voice"),
            _("Text is {count} characters. A designed voice and the "
              "model's own voice speak at most {limit} "
              "characters in one go: each piece of a longer text would get a "
              "different voice. Clone a voice from a recording, or use Kokoro, "
              "for longer texts.",
              count=f"{len(text):,}", limit=f"{tts_plan.MAX_PASS_CHARS:,}"),
        )
        return
    engine = "kokoro" if kokoro else "omnivoice"
    settings = _voice_settings(app, engine)
    voice = _job_voice(engine, settings)
    _set_busy(app, True)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_planning = True
    app.vc_status_var.set(_("Estimating the time..."))

    def worker() -> None:
        try:
            plan = _make_plan(engine, text, speed, voice)
            plan.settings = settings
        except Exception as e:  # noqa: BLE001
            logger.exception("Could not plan the text-to-voice job")
            message = str(e)

            def failed() -> None:
                app.vc_planning = False
                _generate_failed(app, message)
            app.post_to_main(failed)
            return
        app.post_to_main(lambda: _on_plan(app, plan, cancel_event))

    from core._threads import safe_thread
    safe_thread(worker, name="voice-plan")


def _voice_settings(app: Any, engine: str) -> "dict[str, Any]":
    """The voice controls at Generate (see ``_JobPlan.settings``)."""
    if engine == "kokoro":
        return {"voice_key": _selected_voice(app).key}
    mode = app.vc_mode_var.get()
    return {"mode": mode,
            "samples": list(app.vc_samples) if mode == _MODE_CLONE else [],
            "instruct": _design_instruct(app) if mode == _MODE_DESIGN else "",
            "language": _omni_language(app),
            "consent": mode == _MODE_CLONE and bool(app.vc_consent_var.get())}


def _job_voice(engine: str, settings: "dict[str, Any]") -> "dict[str, Any] | None":
    """What makes the voice of a piece-by-piece job, or None when the job
    runs in one pass (OmniVoice's designed and own voices change with every
    pass, so they are never split)."""
    if engine == "kokoro":
        return {"voice": settings["voice_key"]}
    if settings["mode"] != _MODE_CLONE:
        return None
    return {"mode": _MODE_CLONE, "language": settings["language"],
            "references": list(settings["samples"])}


def _make_plan(engine: str, text: str, speed: float,
               voice: "dict[str, Any] | None" = None) -> _JobPlan:
    """Device, stored speed figure, estimate and disk check for one job, and
    the piece-by-piece job when the text is longer than one piece. Runs off
    the Tk thread; never downloads or loads a model."""
    from core import tts_job, tts_kokoro, voice_clone
    from core.synthetic_audio import sha256_file

    if engine == "kokoro":
        installed = tts_kokoro.is_downloaded()
        device = "cpu"  # sherpa-onnx runs Kokoro on the CPU
    else:
        installed = voice_clone.is_available()
        device = voice_clone.default_device() if installed else "cpu"
    plan = _JobPlan(engine=engine, text=text, speed=speed, device=device,
                    version="", hardware="", installed=installed,
                    calibration=None, estimate=None, disk=None, voice=voice)
    if voice is not None and len(tts_job.split_text(text, tts_job.PIECE_CHARS[engine])) > 1:
        identity = dict(voice)
        if "references" in identity:
            # The clips' contents, not their paths, identify the voice.
            identity["references"] = [sha256_file(p) for p in identity["references"]]
        plan.job = tts_job.open_job(engine, text, identity, speed)
        plan.resume_done = len(plan.job.done)
    _replan(plan)
    return plan


def _replan(plan: _JobPlan) -> None:
    """(Re)compute everything in *plan* that depends on the device and the
    stored speed figure."""
    from core import tts_plan

    plan.version = tts_plan.engine_version(plan.engine)
    plan.hardware = tts_plan.hardware_fingerprint(plan.device)
    plan.calibration = tts_plan.load_calibration(
        plan.engine, plan.device, plan.version, plan.hardware)
    plan.estimate = tts_plan.estimate(
        plan.text, plan.engine, plan.device, plan.calibration, plan.speed)
    _check_disk(plan)


def _check_disk(plan: _JobPlan) -> None:
    """Free space for the job; a piece-by-piece job needs room for the
    pieces still to write plus the joined file."""
    from core import tts_plan

    need = None
    job = plan.job
    if _finished(plan):
        need = 0  # the file is already there: nothing new to write
    elif job is not None:
        need = tts_plan.piece_job_need_bytes(plan.estimate, _left_share(plan))
    plan.disk = tts_plan.check_disk(plan.estimate, need_bytes=need)


def _finished(plan: _JobPlan) -> bool:
    """True when an earlier run already joined this job's file."""
    return plan.job is not None and bool(plan.job.finished)


def _left_share(plan: _JobPlan) -> float:
    """Share of the job's speech still to speak (1.0 for a new job)."""
    job = plan.job
    if job is None or not job.total_units:
        return 1.0
    return max(0.0, 1.0 - job.done_units / job.total_units)


def _too_big(plan: _JobPlan) -> bool:
    """True when the speech could outgrow one WAV file (4 GB)."""
    from core import tts_plan

    return plan.estimate.size_high > tts_plan.MAX_WAV_BYTES


def _can_start(plan: _JobPlan) -> bool:
    return plan.disk.ok and not _too_big(plan)


def _on_plan(app: Any, plan: _JobPlan, cancel_event: threading.Event) -> None:
    from core import tts_plan

    app.vc_planning = False
    if cancel_event.is_set():
        _generate_cancelled(app)
        return
    app.vc_plan = plan
    # A job that cannot start (no disk space, too big) always gets the
    # confirm step, which says why: it never starts on its own.
    if (tts_plan.needs_confirm(plan.estimate) or plan.resume_done or _finished(plan)
            or not _can_start(plan)):
        _show_confirm(app)
    else:
        _start(app)


def _can_measure(plan: _JobPlan) -> bool:
    """Only Kokoro has a measuring run (a few seconds); OmniVoice's first real
    job is its measurement (one pass takes over a minute on a CPU)."""
    return (plan.engine == "kokoro" and plan.installed and not plan.resume_done
            and not _finished(plan)
            and plan.calibration is None and not plan.measure_failed)


def _time_hint(plan: _JobPlan) -> str:
    """'about 12–18 minutes on this computer' or similar ('' = no figure)."""
    from core import tts_plan

    est = plan.estimate
    if est is None or est.time_high is None:
        return ""
    span = tts_plan.format_duration_range(est.time_low, est.time_high)
    if est.measured:
        return _("{time} on this computer", time=span)
    return _("{time} (estimated, not measured on this computer yet)", time=span)


def _time_line(plan: _JobPlan, resumed: bool) -> str:
    """The confirm step's time line: the whole job, or the pieces a continued job has left.

    Every case is one whole sentence for translators; the "pieces left" forms are plurals
    (both English forms are the same text as before)."""
    from core import tts_plan

    est = plan.estimate
    seconds = f"{tts_plan.min_calibration_audio(plan.engine):.0f}"
    left = len(plan.job.pending()) if resumed and plan.job is not None else 0
    if est.time_high is None:
        if resumed:
            return ngettext(
                "Time left for the {n} unfinished pieces: not known yet for this device; "
                "the first run with at least {seconds} seconds of speech measures this "
                "computer.",
                "Time left for the {n} unfinished pieces: not known yet for this device; "
                "the first run with at least {seconds} seconds of speech measures this "
                "computer.", left, seconds=seconds)
        return _("Time: not known yet for this device; the first run with at least "
                 "{seconds} seconds of speech measures this computer.", seconds=seconds)
    share = _left_share(plan) if resumed else 1.0
    span = tts_plan.format_duration_range(est.time_low * share, est.time_high * share)
    if est.measured:
        if resumed:
            return ngettext(
                "Time left for the {n} unfinished pieces on this computer: {time} "
                "(measured on this computer).",
                "Time left for the {n} unfinished pieces on this computer: {time} "
                "(measured on this computer).", left, time=span)
        return _("Time on this computer: {time} (measured on this computer).", time=span)
    if _can_measure(plan) and not resumed:  # a continued job is never offered the measuring run
        return _("Time: {time} on a typical computer. Measure this computer's speed first "
                 "(about 10 seconds, done once) for its own range.", time=span)
    if resumed:
        return ngettext(
            "Time left for the {n} unfinished pieces: {time}, estimated from a reference "
            "computer; the first run with at least {seconds} seconds of speech measures this "
            "computer.",
            "Time left for the {n} unfinished pieces: {time}, estimated from a reference "
            "computer; the first run with at least {seconds} seconds of speech measures this "
            "computer.", left, time=span, seconds=seconds)
    return _("Time: {time}, estimated from a reference computer; the first run with at "
             "least {seconds} seconds of speech measures this computer.",
             time=span, seconds=seconds)


def _confirm_text(plan: _JobPlan) -> str:
    from core import tts_plan

    est, disk = plan.estimate, plan.disk
    lines = []
    job = plan.job
    if job is not None and _finished(plan):
        speech = tts_plan.format_duration_range(job.finished_audio_seconds,
                                                job.finished_audio_seconds)
        return _("This text was already spoken with this voice and speed ({speech} of "
                 "speech, finished earlier). Use that file, or start over to speak it "
                 "again.", speech=speech)
    resumed = bool(job is not None and plan.resume_done)
    if job is not None and resumed:
        total = len(job.spoken())
        lines.append(ngettext(
            "Unfinished job found for this text and voice: {done} of {n} pieces are done. "
            "Continue it, or start over.",
            "Unfinished job found for this text and voice: {done} of {n} pieces are done. "
            "Continue it, or start over.", total, done=plan.resume_done))
    # A continued job speaks only the pieces left: its time is their share.
    lines.append(_time_line(plan, resumed))
    lines.append(_("Speech: {speech}. File: {size} (WAV).",
                   speech=tts_plan.format_duration_range(est.audio_low, est.audio_high),
                   size=tts_plan.format_size_range(est.size_low, est.size_high)))
    if not plan.installed:
        lines.append(translate(_KOKORO_DOWNLOAD_LINE if plan.engine == "kokoro"
                               else _OMNI_DOWNLOAD_LINE))
    drive = Path(disk.folder).anchor or disk.folder
    if _too_big(plan):
        lines.append(_(
            "This text is too long for one audio file: a WAV file holds at most "
            "4 GB (about 24 hours of speech). Split the text into parts."))
    elif disk.ok:
        lines.append(_("Free disk space: {free} on {drive}",
                       free=tts_plan.format_size(disk.free_bytes), drive=drive))
    else:
        lines.append(_(
            "Not enough free disk space: this needs about {need} plus {margin} kept free "
            "on {drive} and only {free} is free. Free some space, then try again.",
            need=tts_plan.format_size(disk.need_bytes),
            margin=tts_plan.format_size(disk.margin_bytes), drive=drive,
            free=tts_plan.format_size(disk.free_bytes)))
    return "\n".join(lines)


def _show_confirm(app: Any) -> None:
    """Show (or refresh) the confirm step for ``app.vc_plan``."""
    plan = app.vc_plan
    app.vc_confirm_var.set(_confirm_text(plan))
    measure = _can_measure(plan)
    for btn in (app.vc_confirm_start_btn, app.vc_confirm_measure_btn,
                app.vc_confirm_restart_btn):
        btn.pack_forget()
    finished = _finished(plan)
    app.vc_confirm_start_btn.configure(
        text=_("Use the finished file") if finished
        else _("Continue the unfinished job") if plan.resume_done else _("Start"))
    shown = app.vc_confirm_measure_btn if measure else app.vc_confirm_start_btn
    shown.pack(**rtl_layout.pack_kw(shown, side="left", before=app.vc_confirm_cancel_btn))
    shown.configure(state="normal" if finished or _can_start(plan) else "disabled")
    if plan.resume_done or finished:
        app.vc_confirm_restart_btn.pack(side="left", padx=(8, 0),
                                        before=app.vc_confirm_cancel_btn)
        app.vc_confirm_restart_btn.configure(
            state="normal" if _can_start(plan) else "disabled")
    app.vc_confirm_cancel_btn.configure(state="normal")
    app.vc_confirm_frame.grid()
    # The plan is for this exact text and speed.
    app.vc_text.configure(state="disabled")
    app.vc_speed_scale.state(["disabled"])
    app.vc_confirm_open = True
    _sync_lock(app)
    if _finished(plan):
        app.vc_status_var.set(_("This text was already spoken with this voice."))
    elif _too_big(plan):
        app.vc_status_var.set(_("This text is too long for one audio file."))
    elif not plan.disk.ok:
        app.vc_status_var.set(_("Not enough free disk space for this text."))
    elif measure:
        app.vc_status_var.set(_("Long text: measure this computer's speed, or Cancel."))
    else:
        app.vc_status_var.set(_("Long text: check the estimate, then Start or Cancel."))


def _close_confirm(app: Any) -> None:
    app.vc_confirm_frame.grid_remove()
    app.vc_text.configure(state="normal")
    app.vc_speed_scale.state(["!disabled"])
    app.vc_confirm_open = False
    app.vc_measuring = False
    _sync_lock(app)


def _confirm_start(app: Any) -> None:
    plan = app.vc_plan
    if app.vc_confirm_open and plan is not None and _finished(plan):
        _close_confirm(app)
        _use_finished(app, plan)
        return
    if not app.vc_confirm_open or plan is None or not _can_start(plan):
        return
    # The panel may have been open for a while: check the space again.
    _check_disk(plan)
    if not plan.disk.ok:
        _show_confirm(app)
        return
    _close_confirm(app)
    _start(app)


def _use_finished(app: Any, plan: _JobPlan) -> None:
    """Show the file an earlier run of this job made; nothing is spoken."""
    _finish(app)
    app.vc_plan = None
    app.vc_progress.configure(value=100)
    app.vc_last_output = str(plan.job.output_path)
    app.vc_play_btn.configure(state="normal")
    app.vc_save_btn.configure(state="normal")
    app.vc_status_var.set(
        _("Done: {audio}s of speech, finished earlier for "
          "this text and voice (nothing was spoken again).",
          audio=f"{plan.job.finished_audio_seconds:.0f}"))


def _confirm_restart(app: Any) -> None:
    """Start over: forget the unfinished job's pieces (or the finished
    file's marker), then start."""
    from core import tts_job, tts_plan

    plan = app.vc_plan
    if (not app.vc_confirm_open or plan is None or plan.job is None
            or not (plan.resume_done or _finished(plan))):
        return
    # Check the space for the whole job first (the old pieces' space counts
    # as free once they are gone): never delete pieces for a job that then
    # cannot start.
    held = sum(p.stat().st_size for p in plan.job.parts_dir.glob("piece-*.wav"))
    need = tts_plan.piece_job_need_bytes(plan.estimate) - held
    if _too_big(plan) or not tts_plan.check_disk(plan.estimate, need_bytes=need).ok:
        app.vc_status_var.set(_("Not enough free disk space to start over; the finished "
                                "work is kept."))
        return
    try:
        plan.job.discard()
    except tts_job.JobBusy as e:
        app.vc_status_var.set(_("{error} The finished pieces are kept.", error=e))
        return
    plan.resume_done = 0
    _confirm_start(app)


def _confirm_cancelled(app: Any) -> None:
    _close_confirm(app)
    app.vc_plan = None
    _generate_cancelled(app)


def _measure_speed(app: Any) -> None:
    """Run Kokoro's short measuring run, store it, then refresh the estimate."""
    from core import tts_kokoro, tts_plan

    plan = app.vc_plan
    if not app.vc_confirm_open or plan is None or not _can_measure(plan) or not plan.disk.ok:
        return
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_measuring = True
    app.vc_confirm_measure_btn.configure(state="disabled")
    app.vc_status_var.set(_("Measuring this computer's speed (one time, about 10 seconds)..."))

    def worker() -> None:
        try:
            result = tts_kokoro.measure_speed(cancel_event=cancel_event)
            cal = tts_plan.record_measurement(
                plan.engine, plan.device, plan.version, plan.hardware,
                units=tts_plan.speech_units(tts_plan.CALIBRATION_TEXT),
                audio_seconds=result.audio_seconds,
                compute_seconds=result.elapsed_seconds, source="check")
        except Exception as e:  # noqa: BLE001
            if cancel_event.is_set():
                app.post_to_main(lambda: _confirm_cancelled(app))
                return
            logger.exception("Measuring the Kokoro speed failed")
            message = str(e)
            app.post_to_main(lambda: _measure_failed(app, plan, message, cancel_event))
            return
        app.post_to_main(lambda: _on_measured(app, plan, cal, cancel_event))

    from core._threads import safe_thread
    safe_thread(worker, name="kokoro-measure")


def _on_measured(app: Any, plan: _JobPlan, cal: Any, cancel_event: threading.Event) -> None:
    from core import tts_plan

    if app.vc_plan is not plan or not app.vc_confirm_open:
        return  # closed meanwhile
    if cancel_event.is_set():  # Cancel pressed as the run finished: still stored, not started
        _confirm_cancelled(app)
        return
    if cal is None:
        _measure_failed(app, plan, _("the check produced too little speech to measure"),
                        cancel_event)
        return
    app.vc_measuring = False
    app.vc_cancel_event = None
    plan.calibration = cal
    plan.estimate = tts_plan.estimate(plan.text, plan.engine, plan.device, cal, plan.speed)
    _check_disk(plan)
    _show_confirm(app)


def _measure_failed(app: Any, plan: _JobPlan, message: str,
                    cancel_event: threading.Event) -> None:
    """Keep the confirm step open with the reference estimate and Start."""
    if app.vc_plan is not plan or not app.vc_confirm_open:
        return
    if cancel_event.is_set():  # Cancel pressed as the run failed
        _confirm_cancelled(app)
        return
    app.vc_measuring = False
    app.vc_cancel_event = None
    plan.measure_failed = True
    _show_confirm(app)
    app.vc_status_var.set(_("Could not measure this computer's speed ({error}); "
                            "the estimate is from a reference computer.", error=message))


def _start(app: Any) -> None:
    plan = app.vc_plan
    if plan.engine == "kokoro":
        _generate_kokoro(app, plan.text)
    else:
        _generate_omnivoice(app, plan.text)


def _record_speed(app: Any, result: "dict[str, Any]") -> None:
    """A finished job is the best measurement of this computer: store it as
    the speed figure for its engine and device (runs too short to measure
    are skipped by ``core.tts_plan.record_measurement``)."""
    from core import tts_plan

    plan, app.vc_plan = app.vc_plan, None
    if plan is None:
        return
    # A piece-by-piece run reports what THIS run spoke (a continued job
    # skipped the pieces an earlier run finished).
    units = result.get("units_run", plan.estimate.units)
    audio = result.get("audio_seconds_run", result.get("audio_seconds"))
    try:
        tts_plan.record_measurement(
            plan.engine, plan.device, plan.version, plan.hardware,
            units=float(units or 0.0),
            audio_seconds=float(audio or 0.0),
            compute_seconds=float(result.get("elapsed_seconds") or 0.0),
            speed=plan.speed, source="run")
    except (OSError, TypeError, ValueError):
        logger.exception("Could not store the measured text-to-voice speed")


def _piece_status(voice: "str | None", current: int, total: int,
                  seconds_left: "float | None") -> str:
    """The status line while a job is spoken piece by piece: with ``voice`` (a Kokoro
    voice's name) "Speaking as ...", without it (OmniVoice) "Generating". Whole sentences
    for translators; plural forms by the piece count (both English forms are the same)."""
    from core import tts_plan

    if seconds_left is None:
        if voice is None:
            return ngettext("Generating: piece {current} of {n}...",
                            "Generating: piece {current} of {n}...", total, current=current)
        return ngettext("Speaking as {voice}: piece {current} of {n}...",
                        "Speaking as {voice}: piece {current} of {n}...", total,
                        voice=voice, current=current)
    left = tts_plan.format_duration_range(seconds_left, seconds_left)
    if voice is None:
        return ngettext("Generating: piece {current} of {n}, {time} left...",
                        "Generating: piece {current} of {n}, {time} left...", total,
                        current=current, time=left)
    return ngettext("Speaking as {voice}: piece {current} of {n}, {time} left...",
                    "Speaking as {voice}: piece {current} of {n}, {time} left...", total,
                    voice=voice, current=current, time=left)


def _run_job(app: Any, plan: _JobPlan, speak: Any, cancel_event: threading.Event,
             voice: "str | None", on_joined: Any = None) -> "dict[str, Any]":
    """Speak the unfinished pieces of ``plan.job`` (worker thread) with the
    progress bar and the time left on the status line (``voice``: see
    :func:`_piece_status`); returns the payload for :func:`_generate_done`.
    Raises like ``core.tts_job.run``."""
    from core import tts_job

    job = plan.job
    est = plan.estimate
    # Until the first piece of this job is done: the plan's own figure.
    fallback = None
    if est is not None and est.time_high is not None and est.units > 0:
        fallback = (est.time_low + est.time_high) / 2.0 / est.units

    def on_progress(p: Any) -> None:
        current = min(p.pieces_done + 1, p.pieces_total)
        status = _piece_status(voice, current, p.pieces_total, p.seconds_left)

        def show() -> None:
            app.vc_progress.configure(value=p.fraction * 100)
            app.vc_status_var.set(status)
        app.post_to_main(show)

    result = tts_job.run(job, speak, cancel_event=cancel_event,
                         on_progress=on_progress, fallback_per_unit=fallback,
                         on_joined=on_joined)
    return {"output_path": result.output_path, "audio_seconds": result.audio_seconds,
            "elapsed_seconds": result.compute_seconds_run,
            "units_run": result.units_run, "audio_seconds_run": result.audio_seconds_run,
            "pieces": len(job.pieces)}


def _kept(plan: "_JobPlan | None") -> "tuple[int, int] | None":
    """(finished, total) pieces of a piece-by-piece job, else None."""
    if plan is None or plan.job is None:
        return None
    return len(plan.job.done), len(plan.job.spoken())


def _generate_kokoro(app: Any, text: str, play_when_done: bool = False) -> None:
    from core import tts_kokoro, voice_clone

    plan = app.vc_plan
    voice = (tts_kokoro.voice_by_key(plan.settings["voice_key"])
             if plan is not None and plan.settings else _selected_voice(app))
    speed = plan.speed if plan is not None else float(app.vc_speed_var.get() or 1.0)
    _set_busy(app, True)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set(_("Preparing..."))

    def worker() -> None:
        try:
            if not tts_kokoro.is_downloaded():
                def dl(done: int, total: int) -> None:
                    frac = done / total if total else 0.0
                    _set_progress(app, frac)
                    status = _("Downloading the Kokoro voice model (one time): "
                               "{done} / {total} MB",
                               done=f"{done / 1e6:.0f}", total=f"{total / 1e6:.0f}")
                    app.post_to_main(lambda: app.vc_status_var.set(status))
                tts_kokoro.download(progress_cb=dl, cancel_event=cancel_event)
                app.post_to_main(lambda: _sync_engine(app))
            if plan is not None and plan.job is not None:
                def speak(piece: str, path: str, on_fraction: Any) -> float:
                    return tts_kokoro.generate(
                        piece, voice.key, path, speed=speed, progress_cb=on_fraction,
                        cancel_event=cancel_event).elapsed_seconds

                payload = _run_job(app, plan, speak, cancel_event, voice.label)
                app.post_to_main(lambda: _generate_done(app, payload))
                return
            hint = _time_hint(plan) if plan is not None else ""
            status = _("Speaking as {voice}... {time}", voice=voice.label, time=hint).rstrip()
            app.post_to_main(lambda: app.vc_status_var.set(status))
            _set_progress(app, 0.0)
            out = os.path.join(voice_clone.session_work_dir(),
                               "preview.wav" if play_when_done else "output.wav")
            result = tts_kokoro.generate(
                text, voice.key, out, speed=speed,
                progress_cb=lambda f: _set_progress(app, f), cancel_event=cancel_event)
            payload = {"output_path": result.output_path,
                       "elapsed_seconds": result.elapsed_seconds,
                       "audio_seconds": result.audio_seconds}
            app.post_to_main(lambda: _generate_done(app, payload, play=play_when_done))
        except Exception as e:  # noqa: BLE001
            kept = _kept(plan)
            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app, kept))
            else:
                logger.exception("Kokoro generation failed")
                message = str(e)  # `e` is unbound once this block exits
                busy = _is_job_busy(e)
                app.post_to_main(lambda: _generate_failed(app, message, kept, busy))

    from core._threads import safe_thread
    safe_thread(worker, name="kokoro-generate")


def _generate_omnivoice(app: Any, text: str) -> None:
    from core import voice_clone

    plan = app.vc_plan
    if plan is None or not plan.settings:
        # Not planned (no Generate press): check the controls as they are now.
        if _omni_refused(app):
            _finish(app)
            app.vc_plan = None
            return
        settings = _voice_settings(app, "omnivoice")
    else:
        settings = plan.settings  # checked by _omni_refused at Generate
    mode = settings["mode"]
    consent = bool(settings["consent"])
    samples = list(settings["samples"])
    instruct = settings["instruct"]
    language = settings["language"]
    speed = plan.speed if plan is not None else float(app.vc_speed_var.get() or 1.0)

    _set_busy(app, True)
    if plan is None or plan.job is None:
        # One pass has no progress to show; a job moves the bar per piece.
        app.vc_progress.configure(mode="indeterminate")
        app.vc_progress.start(20)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set(_("Preparing..."))

    def worker() -> None:
        try:
            if not voice_clone.is_available():
                install_status = translate(_OMNI_INSTALL_STATUS)
                app.post_to_main(lambda: app.vc_status_var.set(install_status))
                ok = voice_clone.ensure_installed(
                    log_cb=app.log_threadsafe, cancel_event=cancel_event
                )
                if not ok:
                    if cancel_event.is_set():
                        app.post_to_main(lambda: _generate_cancelled(app))
                    else:
                        reason = (
                            offline.message("downloading the speech model software")
                            if offline.is_offline()
                            else _("Could not download the speech model software.")
                        )
                        app.post_to_main(lambda: _generate_failed(app, reason))
                    return

            # Nothing else re-checks cancel_event before generate() below
            # (e.g. during the first `import torch` in default_device()).
            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app))
                return

            device = voice_clone.default_device()
            time_high = None
            if plan is not None:
                if not plan.installed or device != plan.device:
                    # Installed just now, or another device than planned:
                    # versions, fingerprint and speed figure change with it.
                    plan.installed = True
                    plan.device = device
                    _replan(plan)
                time_high = plan.estimate.time_high
            hint = (_time_hint(plan) if plan is not None else "") or _("time not known yet")
            generating = _("Generating... {time}.", time=hint)
            app.post_to_main(lambda: app.vc_status_var.set(generating))

            _ensure_worker(app)

            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app, _kept(plan)))
                return

            loading = _("Loading the speech model (first time this session; "
                        "this may also download ~2GB of model weights -- "
                        "needs internet; a few minutes to over an hour on "
                        "a slow connection)...")

            def _on_model_loading() -> None:
                app.post_to_main(lambda: app.vc_status_var.set(loading))

            if plan is not None and plan.job is not None:
                payload = _run_omnivoice_job(
                    app, plan, samples, consent, device, _on_model_loading,
                    instruct, language, speed, cancel_event)
                app.post_to_main(lambda: _generate_done(app, payload))
                return

            output_path = os.path.join(voice_clone.session_work_dir(), "output.wav")
            result = app.vc_worker.generate(
                text, samples, output_path,
                consent_accepted=consent, device=device,
                on_model_loading=_on_model_loading,
                instruct=instruct, language=language, speed=speed,
                # Generous: 3x the high estimate, never below the default.
                timeout_s=(time_high or 0.0) * 3,
            )
            app.post_to_main(lambda: _generate_done(app, result))
        except Exception as e:  # noqa: BLE001
            kept = _kept(plan)
            if cancel_event.is_set():
                logger.info("Voice-clone generation cancelled")
                app.post_to_main(lambda: _generate_cancelled(app, kept))
            else:
                logger.exception("Voice-clone generation failed")
                # Capture the message now, not `e` itself: Python deletes
                # the `except ... as e` name when this block exits (PEP
                # 3110), before post_to_main's queued lambda runs.
                message = str(e)
                busy = _is_job_busy(e)
                app.post_to_main(lambda: _generate_failed(app, message, kept, busy))

    from core._threads import safe_thread
    safe_thread(worker, name="voice-clone-generate")


def _run_omnivoice_job(app: Any, plan: _JobPlan, samples: "list[str]", consent: bool,
                       device: str, on_model_loading: Any, instruct: str, language: str,
                       speed: float, cancel_event: threading.Event) -> "dict[str, Any]":
    """One worker call per piece (worker thread). The voice comes from the
    same reference clips in every piece; the consent record is written once,
    for the joined file the user gets, not for each piece. The clips are
    copied into the job's folder first and used from there, so a later run
    (after a restart, or once the originals are moved or swept) continues
    with exactly the same voice, and the consent record names files that
    still exist."""
    from core import synthetic_audio, tts_plan, voice_clone

    samples = plan.job.keep_references(samples)

    def speak(piece: str, path: str, _on_fraction: Any) -> float:
        est = tts_plan.estimate(piece, plan.engine, plan.device, plan.calibration, speed)
        result = app.vc_worker.generate(
            piece, samples, path, consent_accepted=consent, device=device,
            on_model_loading=on_model_loading, instruct=instruct,
            language=language, speed=speed,
            # Generous: 3x the piece's high estimate, never below the default.
            timeout_s=(est.time_high or 0.0) * 3, consent_record=False)
        return float(result.get("elapsed_seconds") or 0.0)

    warning: list[str] = []

    def record_consent(output: Path) -> None:
        # Before the job is marked finished: a crash here leaves the job
        # unfinished, so the next run joins again and writes the record.
        try:
            synthetic_audio.append_consent_record(
                output, samples[:voice_clone.MAX_REFERENCE_SAMPLES],
                consent_accepted=consent, engine="omnivoice")
        except OSError as e:
            # The joined file is finished and tagged; report, never discard it.
            logger.exception("Could not write the voice-clone consent record")
            warning.append(f"The local consent record could not be saved: {e}")

    payload = _run_job(app, plan, speak, cancel_event, None,
                       on_joined=record_consent if samples else None)
    if warning:
        payload["warning"] = warning[0]
    return payload


def _ensure_worker(app: Any) -> None:
    """Start a voice-clone worker unless one is running (generate thread).

    A worker that was just cancelled may still be dying: Generate is enabled
    again at once, but its process lives until it obeys the shutdown or is
    killed. Wait for it first so two speech models never sit in memory side
    by side.
    """
    old = app.vc_worker
    if old is not None and old.is_running():
        return
    if old is not None and not old.wait_for_exit():
        from app.services.voice_clone_service import VoiceCloneWorkerError
        raise VoiceCloneWorkerError(
            _("The previous voice-clone worker is still stopping; try again in a moment."))
    from app.services.voice_clone_service import VoiceCloneWorker
    app.vc_worker = VoiceCloneWorker(app.entry_file, log=app.log_threadsafe)
    app.vc_worker.start()


def _finish(app: Any) -> None:
    _set_busy(app, False)
    app.vc_cancel_event = None
    try:
        app.vc_progress.stop()
        app.vc_progress.configure(mode="determinate")
    except Exception:  # noqa: BLE001
        pass


def _generate_done(app: Any, result: dict[str, Any], play: bool = False) -> None:
    _finish(app)
    app.vc_progress.configure(value=100)
    app.vc_last_output = result.get("output_path") or None
    if app.vc_last_output:
        app.vc_play_btn.configure(state="normal")
        app.vc_save_btn.configure(state="normal")
    elapsed = result.get("elapsed_seconds") or 0.0
    audio = result.get("audio_seconds") or 0.0
    audio_s, elapsed_s = f"{audio:.0f}", f"{elapsed:.0f}"
    if "units_run" in result:  # piece by piece: a continued job spoke only part of it now
        status = _("Done: {audio}s of speech; this run took {elapsed}s.",
                   audio=audio_s, elapsed=elapsed_s)
    else:
        status = (_("Done: {audio}s of speech in {elapsed}s.", audio=audio_s, elapsed=elapsed_s)
                  if audio else _("Done in {elapsed}s.", elapsed=elapsed_s))
    warning = result.get("warning") or ""
    if warning:
        status += " " + _("Warning: the consent record was not saved (see the log).")
    app.vc_status_var.set(status)
    app.log(f"Text to voice finished: {app.vc_last_output}")
    if warning:
        app.log(warning)
    _record_speed(app, result)
    if play:
        _play(app)


def _kept_text(kept: "tuple[int, int] | None") -> str:
    if not kept or not kept[0]:
        return ""
    # Both English forms are the same text as before; other languages get real plural forms.
    return " " + ngettext(
        "{done} of {n} pieces are kept: press Generate with the same text and voice to continue.",
        "{done} of {n} pieces are kept: press Generate with the same text and voice to continue.",
        kept[1], done=kept[0])


def _is_job_busy(e: BaseException) -> bool:
    from core import tts_job
    return isinstance(e, tts_job.JobBusy)


def _generate_failed(app: Any, message: str,
                     kept: "tuple[int, int] | None" = None, busy: bool = False) -> None:
    _finish(app)
    app.vc_plan = None
    if busy:  # another app window runs this job: nothing failed here
        app.vc_status_var.set(_("Not started: {error}", error=message))
        show_error(app, _("Running in another window"), message)
        return
    app.vc_status_var.set(_("Failed.") + _kept_text(kept))
    show_error(
        app, _("Generation failed"), message,
        detail=(
            _("If this looks like a network or download problem, check your "
              "internet connection, then click Generate again to retry.")
            + (" " + _("The finished pieces are kept; the same text and voice "
                       "continue from there.") if kept and kept[0] else "")
        ),
    )


def _generate_cancelled(app: Any, kept: "tuple[int, int] | None" = None) -> None:
    _finish(app)
    app.vc_plan = None
    app.vc_status_var.set(_("Cancelled.") + _kept_text(kept))


def _cancel_generate(app: Any) -> None:
    cancel_event = getattr(app, "vc_cancel_event", None)
    if cancel_event is not None:
        cancel_event.set()
    if getattr(app, "vc_planning", False):
        # Nothing runs yet; the plan sees the event and cancels. A loaded
        # OmniVoice worker from an earlier job stays loaded for the next one.
        app.vc_cancel_btn.configure(state="disabled")
        return
    if getattr(app, "vc_confirm_open", False):
        if app.vc_measuring:
            # The measuring run stops at its next sentence, then closes the step.
            app.vc_confirm_cancel_btn.configure(state="disabled")
            app.vc_cancel_btn.configure(state="disabled")
        else:
            _confirm_cancelled(app)
        return
    app.vc_cancel_btn.configure(state="disabled")
    if _is_kokoro(app):
        return  # the in-process Kokoro run stops at its next sentence
    worker = getattr(app, "vc_worker", None)
    if worker is None or not worker.is_running():
        return

    def worker_stop() -> None:
        try:
            worker.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Voice-clone generation stop failed")

    threading.Thread(target=worker_stop, name="voice-clone-stop", daemon=True).start()


def _play(app: Any) -> None:
    path = app.vc_last_output
    if not path or not os.path.isfile(path):
        return
    def done(error: BaseException | None) -> None:
        if error is not None:
            show_error(app, _("Could not play the result"), str(error))

    open_async(path, app, done)


def _save(app: Any) -> None:
    path = app.vc_last_output
    if not path or not os.path.isfile(path):
        return
    dest = filedialog.asksaveasfilename(
        parent=app, title=_("Save generated speech"),
        defaultextension=".wav",
        filetypes=[(_("WAV audio"), "*.wav"), (_("All files"), "*.*")],
        initialfile="cloned-voice.wav",
    )
    if not dest:
        return
    try:
        import shutil
        shutil.copyfile(path, dest)
    except OSError as e:
        show_error(app, _("Could not save the file"), str(e))
        return
    app.log(f"Voice-clone result saved to {dest}")


def stop_voice_clone_worker(app: Any) -> None:
    """Tear the worker down on app exit or tab teardown. Safe when
    nothing is running. Mirrors ``live_tab.stop_live_session``."""
    after_id = getattr(app, "vc_recording_after_id", None)
    if after_id is not None:
        try:
            app.after_cancel(after_id)
        except Exception:  # noqa: BLE001
            pass
        app.vc_recording_after_id = None
    # An in-flight on-demand install (~2GB) is cooperatively cancellable
    # via this event (see core.optional_deps.install), but it runs as a
    # plain subprocess inside the generate worker THREAD above, not the
    # VoiceCloneWorker subprocess below -- signal it here too so closing
    # mid-install has a chance to abort the pip subprocess and clean up
    # its staging dir, instead of leaving it running unobserved.
    cancel_event = getattr(app, "vc_cancel_event", None)
    if cancel_event is not None:
        cancel_event.set()
    worker = getattr(app, "vc_worker", None)
    if worker is not None:
        try:
            worker.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Voice-clone worker teardown failed")
    app.vc_worker = None
    recorder = getattr(app, "vc_recorder", None)
    if recorder is not None:
        try:
            recorder.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Voice-clone recorder teardown failed")
    app.vc_recorder = None
