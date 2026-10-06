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

from app.theme import script_fonts
from app.widgets.error_dialog import show_error
from app.widgets.tooltip import section_labelframe
from core import offline

logger = logging.getLogger(__name__)

_SAMPLE_SECONDS = 6

# Always visible on the tab: the rules replace the old one-time
# confirmation dialog, and consent is the per-voice tick below.
_RULES_TEXT = (
    "AI-generated audio. Clone only your own voice, or a voice whose speaker "
    "has given you clear permission. Do not impersonate anyone, and do not "
    "make misleading audio of real people."
)
_CONSENT_TICK_TEXT = "I have the speaker's permission to clone this voice (or it is my own)"

# Shown when the OmniVoice install actually starts (the first Generate).
_OMNI_INSTALL_STATUS = (
    "Downloading OmniVoice (about 2 GB, one time; needs internet, a few "
    "minutes to over an hour depending on the connection). After that it "
    "runs offline..."
)

_KOKORO_DOWNLOAD_LINE = "The Kokoro voice model downloads first (about 350 MB, one time)."
_OMNI_DOWNLOAD_LINE = "OmniVoice downloads first (about 2 GB, one time)."

_ENGINE_KOKORO = "Kokoro — 53 ready-made voices, 9 languages (fast; ~350 MB download)"
_ENGINE_OMNI = "OmniVoice — clone any voice, or design one (slow on CPU; ~2 GB download)"

_MODE_CLONE = "clone"
_MODE_DESIGN = "design"
_MODE_AUTO = "auto"

_ANY = "Any"
_AUTO_LANG = "Auto-detect"

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


def _sweep_scratch_dirs() -> None:
    from core.voice_clone import sweep_old_session_dirs
    sweep_old_session_dirs()


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
    app.vc_status_var = tk.StringVar(value="Idle.")
    cfg = app.app_config.setdefault("voice_clone", {})
    app.vc_engine_var = tk.StringVar(
        value=_ENGINE_OMNI if cfg.get("engine") == "omnivoice" else _ENGINE_KOKORO)
    app.vc_mode_var = tk.StringVar(value=cfg.get("mode") or _MODE_CLONE)
    voice_labels = [v.label for v in tts_kokoro.VOICES]
    saved_voice = tts_kokoro.voice_by_key(str(cfg.get("kokoro_voice") or tts_kokoro.DEFAULT_VOICE))
    app.vc_voice_var = tk.StringVar(value=saved_voice.label)
    app.vc_gender_var = tk.StringVar(value=_ANY)
    app.vc_age_var = tk.StringVar(value=_ANY)
    app.vc_pitch_var = tk.StringVar(value=_ANY)
    app.vc_accent_var = tk.StringVar(value=_ANY)
    app.vc_whisper_var = tk.BooleanVar(value=False)
    app.vc_lang_var = tk.StringVar(value=_AUTO_LANG)
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
    app.after(2000, _sweep_scratch_dirs)

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)

    # ── Model ───────────────────────────────────────────────────────────
    eng = section_labelframe(
        parent, "Model",
        "Kokoro speaks in one of 53 ready-made voices and is fast on any "
        "computer. OmniVoice can clone a voice from a short recording, or "
        "design a new one from a description (gender, age, pitch, accent); "
        "it is much slower without a supported graphics card. Each model "
        "downloads once, the first time it is used.",
    )
    eng.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 6))
    eng.columnconfigure(1, weight=1)
    ttk.Label(eng, text="Model:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
    app.vc_engine_combo = _combo(eng, app.vc_engine_var, [_ENGINE_KOKORO, _ENGINE_OMNI], 70)
    app.vc_engine_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
    app.vc_engine_combo.bind("<<ComboboxSelected>>", lambda _e: _sync_engine(app))
    app.vc_engine_state = ttk.Label(eng, foreground="#666")
    app.vc_engine_state.grid(row=1, column=1, sticky="w", padx=8, pady=(0, 6))

    # ── Voice ───────────────────────────────────────────────────────────
    voice = section_labelframe(
        parent, "Voice",
        "Kokoro: pick a ready-made voice and press Preview to hear it. "
        "OmniVoice: clone a voice from 1-3 short recordings (3-10 seconds "
        "each), design one from its attributes, or let the model choose.",
    )
    voice.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 6))
    voice.columnconfigure(0, weight=1)

    # Kokoro: ready-made voices.
    app.vc_kokoro_frame = ttk.Frame(voice)
    app.vc_kokoro_frame.columnconfigure(1, weight=1)
    ttk.Label(app.vc_kokoro_frame, text="Voice:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
    app.vc_voice_combo = _combo(app.vc_kokoro_frame, app.vc_voice_var, voice_labels, 44)
    app.vc_voice_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
    app.vc_voice_combo.bind("<<ComboboxSelected>>", lambda _e: _save_prefs(app))
    app.vc_preview_btn = ttk.Button(
        app.vc_kokoro_frame, text="▶ Preview", command=lambda: _preview(app))
    app.vc_preview_btn.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=6)

    # OmniVoice: mode switch + one panel per mode.
    app.vc_omni_frame = ttk.Frame(voice)
    app.vc_omni_frame.columnconfigure(0, weight=1)
    modes = ttk.Frame(app.vc_omni_frame)
    modes.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    for text, value in (("Clone my voice / a recording", _MODE_CLONE),
                        ("Design a voice", _MODE_DESIGN),
                        ("Let the model choose", _MODE_AUTO)):
        ttk.Radiobutton(modes, text=text, value=value, variable=app.vc_mode_var,
                        command=lambda: _sync_engine(app)).pack(side="left", padx=(0, 16))

    app.vc_clone_frame = ttk.Frame(app.vc_omni_frame)
    app.vc_clone_frame.columnconfigure(0, weight=1)
    app.vc_samples_listbox = tk.Listbox(app.vc_clone_frame, height=3)
    app.vc_samples_listbox.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 4))
    ref_btns = ttk.Frame(app.vc_clone_frame)
    ref_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
    app.vc_record_btn = ttk.Button(
        ref_btns, text=f"● Record sample ({_SAMPLE_SECONDS}s)",
        command=lambda: _record_sample(app),
    )
    app.vc_record_btn.pack(side="left")
    ttk.Button(ref_btns, text="Load audio file...",
               command=lambda: _load_sample(app)).pack(side="left", padx=(8, 0))
    ttk.Button(ref_btns, text="Remove selected",
               command=lambda: _remove_sample(app)).pack(side="left", padx=(8, 0))
    app.vc_consent_check = ttk.Checkbutton(
        app.vc_clone_frame, text=_CONSENT_TICK_TEXT, variable=app.vc_consent_var,
        command=lambda: _sync_generate_state(app))
    app.vc_consent_check.grid(row=2, column=0, sticky="w", padx=8, pady=(0, 6))

    app.vc_design_frame = ttk.Frame(app.vc_omni_frame)
    for col, (label, var, values) in enumerate((
        ("Gender", app.vc_gender_var, _vc.DESIGN_GENDERS),
        ("Age", app.vc_age_var, _vc.DESIGN_AGES),
        ("Pitch", app.vc_pitch_var, _vc.DESIGN_PITCHES),
        ("Accent (English)", app.vc_accent_var, _vc.DESIGN_ACCENTS),
    )):
        ttk.Label(app.vc_design_frame, text=label).grid(row=0, column=col, sticky="w", padx=8)
        _combo(app.vc_design_frame, var,
               [_ANY] + [v[:1].upper() + v[1:] for v in values], 17,
               ).grid(row=1, column=col, sticky="w", padx=8, pady=(0, 6))
    ttk.Checkbutton(app.vc_design_frame, text="Whisper", variable=app.vc_whisper_var).grid(
        row=1, column=4, sticky="w", padx=8, pady=(0, 6))

    app.vc_auto_label = ttk.Label(
        app.vc_omni_frame, foreground="#666",
        text="OmniVoice picks a natural voice by itself -- no recording needed.")

    # ── Text ───────────────────────────────────────────────────────────
    txt = section_labelframe(
        parent, "Text to speak",
        f"Up to {tts_plan.MAX_TEXT_CHARS:,} characters. Long text is split into "
        "sentences and joined back into one audio file. Before a long text "
        "starts, the tab shows how long it takes on this computer, how big "
        "the file gets and whether the disk has room.",
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
    app.vc_lang_label = ttk.Label(opts, text="Language:")
    app.vc_lang_label.pack(side="left")
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    app.vc_lang_combo = _combo(opts, app.vc_lang_var,
                               [_AUTO_LANG] + [n for n, c in _LANGS if c], 18)
    app.vc_lang_combo.pack(side="left", padx=(6, 18))
    # The language picks the font of Han lines: retag when it changes, not only on the next edit.
    app.vc_lang_var.trace_add("write", lambda *_a: _retag_text(app))
    ttk.Label(opts, text="Speed:").pack(side="left")
    app.vc_speed_scale = ttk.Scale(
        opts, from_=0.5, to=2.0, variable=app.vc_speed_var, length=140,
        command=lambda _v: app.vc_speed_label.configure(
            text=f"{app.vc_speed_var.get():.2f}x"))
    app.vc_speed_scale.pack(side="left", padx=6)
    app.vc_speed_label = ttk.Label(opts, text="1.00x", width=6)
    app.vc_speed_label.pack(side="left")
    ttk.Label(opts, textvariable=app.vc_count_var, foreground="#666").pack(side="right")

    # ── Confirm step (long texts only; hidden until a plan needs it) ────
    app.vc_confirm_frame = ttk.Labelframe(parent, text="Long text: check before starting")
    app.vc_confirm_frame.columnconfigure(0, weight=1)
    app.vc_confirm_label = ttk.Label(
        app.vc_confirm_frame, textvariable=app.vc_confirm_var, justify="left", wraplength=760)
    app.vc_confirm_label.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 4))
    confirm_btns = ttk.Frame(app.vc_confirm_frame)
    confirm_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
    app.vc_confirm_start_btn = ttk.Button(
        confirm_btns, text="Start", style="Accent.TButton", command=lambda: _confirm_start(app))
    app.vc_confirm_measure_btn = ttk.Button(
        confirm_btns, text="Measure this computer's speed", style="Accent.TButton",
        command=lambda: _measure_speed(app))
    app.vc_confirm_cancel_btn = ttk.Button(
        confirm_btns, text="Cancel", command=lambda: _cancel_generate(app))
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
        out, text="Generate speech", style="Accent.TButton", command=lambda: _generate(app))
    app.vc_generate_btn.grid(row=0, column=0, sticky="w")
    app.vc_cancel_btn = ttk.Button(
        out, text="Cancel", command=lambda: _cancel_generate(app), state="disabled")
    app.vc_cancel_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
    app.vc_play_btn = ttk.Button(
        out, text="▶ Play", command=lambda: _play(app), state="disabled")
    app.vc_play_btn.grid(row=0, column=2, sticky="w", padx=(8, 0))
    app.vc_save_btn = ttk.Button(
        out, text="Save As...", command=lambda: _save(app), state="disabled")
    app.vc_save_btn.grid(row=0, column=3, sticky="w", padx=(8, 0))
    app.vc_progress = ttk.Progressbar(out, mode="determinate", maximum=100, length=180)
    app.vc_progress.grid(row=0, column=4, sticky="w", padx=(16, 0))
    ttk.Label(parent, textvariable=app.vc_status_var, foreground="#666").grid(
        row=5, column=0, sticky="w", padx=15, pady=(0, 2))
    app.vc_rules_label = ttk.Label(parent, text=_RULES_TEXT, foreground="#666", wraplength=760)
    app.vc_rules_label.grid(row=6, column=0, sticky="w", padx=15, pady=(0, 12))

    _sync_engine(app)
    _on_text_modified(app)


def _is_kokoro(app: Any) -> bool:
    return app.vc_engine_var.get() == _ENGINE_KOKORO


def _sync_engine(app: Any) -> None:
    """Show only the controls the selected model/mode uses."""
    from core import tts_kokoro

    kokoro = _is_kokoro(app)
    if kokoro:
        app.vc_omni_frame.grid_remove()
        app.vc_kokoro_frame.grid(row=0, column=0, sticky="ew")
        state = ("downloaded" if tts_kokoro.is_downloaded()
                 else f"not downloaded yet (~{tts_kokoro.APPROX_DOWNLOAD_MB} MB, "
                      "downloads on first use)")
        app.vc_engine_state.configure(text=f"Kokoro-82M (Apache-2.0), runs locally -- {state}.")
        # The voice decides the language; OmniVoice's picker does not apply.
        app.vc_lang_combo.configure(state="disabled")
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
        state = ("installed" if _vc.is_available()
                 else "not downloaded yet (~2 GB, downloads on first use)")
        app.vc_engine_state.configure(text=f"OmniVoice (Apache-2.0, k2-fsa), runs locally -- {state}.")
        app.vc_lang_combo.configure(state="readonly")
    _sync_generate_state(app)
    _save_prefs(app)


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
    status = f"{len(app.vc_samples)} reference sample(s)."
    if untick:
        status += " The clips changed: tick the permission box again."
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


def _on_text_modified(app: Any) -> None:
    from core.tts_plan import MAX_TEXT_CHARS

    try:
        app.vc_text.edit_modified(False)
        n = len(app.vc_text.get("1.0", "end-1c"))
    except Exception:  # noqa: BLE001
        return
    app.vc_count_var.set(f"{n:,} / {MAX_TEXT_CHARS:,} characters")
    _retag_text(app)


def _retag_text(app: Any) -> None:
    script_fonts.tag_script_lines(app.vc_text, language=_language_code(app))


def _design_instruct(app: Any) -> str:
    from core.voice_clone import build_instruct

    def val(var: Any) -> "str | None":
        v = var.get()
        return None if v == _ANY else v.lower()

    return build_instruct(val(app.vc_gender_var), val(app.vc_age_var),
                          val(app.vc_pitch_var), val(app.vc_accent_var),
                          whisper=bool(app.vc_whisper_var.get()))


def _language_code(app: Any) -> str:
    name = app.vc_lang_var.get()
    if name == _AUTO_LANG:
        return ""
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    return next((c for n, c in _LANGS if n == name), "")


# --------------------------------------------------------------- samples


def _refresh_samples_listbox(app: Any) -> None:
    app.vc_samples_listbox.delete(0, "end")
    for path in app.vc_samples:
        app.vc_samples_listbox.insert("end", os.path.basename(path))


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
            app, "Sample limit reached",
            f"You can use up to {MAX_REFERENCE_SAMPLES} reference clips. "
            "Remove one before adding another.",
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
            app, "Sample limit reached",
            f"You can use up to {MAX_REFERENCE_SAMPLES} reference clips. "
            "Remove one before adding another.",
        )
        return
    if issue is not None:
        title = "Could not use this clip" if issue.blocking else "This clip may not work well"
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
            app, "Cannot record", "This computer cannot capture microphone audio yet.",
            detail=mic_availability_reason(),
        )
        return
    if len(app.vc_samples) >= MAX_REFERENCE_SAMPLES:
        show_error(
            app, "Sample limit reached",
            f"You can use up to {MAX_REFERENCE_SAMPLES} reference clips.",
        )
        return

    out_path = os.path.join(
        session_work_dir(), f"sample_{len(app.vc_samples) + 1}.wav"
    )
    recorder = Recorder(output_path=out_path, mode="mic")
    try:
        recorder.start()
    except Exception as e:  # noqa: BLE001
        show_error(app, "Could not start recording", str(e))
        return
    app.vc_recorder = recorder
    app.vc_record_btn.configure(state="disabled")
    _tick_recording(app, _SAMPLE_SECONDS)


def _tick_recording(app: Any, seconds_left: int) -> None:
    app.vc_status_var.set(f"Recording... {seconds_left}s")
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
    app.vc_record_btn.configure(state="normal")
    if recorder is None:
        return
    try:
        path = recorder.stop()
    except Exception as e:  # noqa: BLE001
        show_error(app, "Recording failed", str(e))
        app.vc_status_var.set("Idle.")
        return
    _validate_and_add_sample(app, path)


def _load_sample(app: Any) -> None:
    path = filedialog.askopenfilename(
        parent=app, title="Load reference voice clip",
        filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All files", "*.*")],
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
        show_error(app, "No reference voice",
                   "Record or load at least one reference clip first, or "
                   "choose \"Design a voice\" / \"Let the model choose\".")
        return True
    if not app.vc_consent_var.get():
        # Generate is disabled until the tick; this guards other callers.
        app.vc_status_var.set("Tick the permission box under the reference clips first.")
        return True
    return False


def _generate(app: Any) -> None:
    """Generate pressed: check the text, then plan the job off the Tk thread
    (the OmniVoice device check imports torch). A short job starts at once;
    a long one gets the confirm step first."""
    from core import tts_plan

    text = app.vc_text.get("1.0", "end").strip()
    if not text:
        show_error(app, "No text", "Type the text you want spoken.")
        return
    if len(text) > tts_plan.MAX_TEXT_CHARS:
        show_error(
            app, "Text too long",
            f"Text is {len(text):,} characters; the limit for one "
            f"generation is {tts_plan.MAX_TEXT_CHARS:,}.",
        )
        return
    kokoro = _is_kokoro(app)
    if not kokoro and _omni_refused(app):
        return
    engine = "kokoro" if kokoro else "omnivoice"
    speed = float(app.vc_speed_var.get() or 1.0)
    _set_busy(app, True)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_planning = True
    app.vc_status_var.set("Estimating the time...")

    def worker() -> None:
        try:
            plan = _make_plan(engine, text, speed)
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


def _make_plan(engine: str, text: str, speed: float) -> _JobPlan:
    """Device, stored speed figure, estimate and disk check for one job.
    Runs off the Tk thread; never downloads or loads a model."""
    from core import tts_kokoro, tts_plan, voice_clone

    if engine == "kokoro":
        installed = tts_kokoro.is_downloaded()
        device = "cpu"  # sherpa-onnx runs Kokoro on the CPU
    else:
        installed = voice_clone.is_available()
        device = voice_clone.default_device() if installed else "cpu"
    plan = _JobPlan(engine=engine, text=text, speed=speed, device=device,
                    version="", hardware="", installed=installed,
                    calibration=None, estimate=None, disk=None)
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
    plan.disk = tts_plan.check_disk(plan.estimate)


def _on_plan(app: Any, plan: _JobPlan, cancel_event: threading.Event) -> None:
    from core import tts_plan

    app.vc_planning = False
    if cancel_event.is_set():
        _generate_cancelled(app)
        return
    app.vc_plan = plan
    if tts_plan.needs_confirm(plan.estimate):
        _show_confirm(app)
    else:
        _start(app)


def _can_measure(plan: _JobPlan) -> bool:
    """Only Kokoro has a measuring run (a few seconds); OmniVoice's first real
    job is its measurement (one pass takes over a minute on a CPU)."""
    return (plan.engine == "kokoro" and plan.installed
            and plan.calibration is None and not plan.measure_failed)


def _time_hint(plan: _JobPlan) -> str:
    """'about 12–18 minutes on this computer' or similar ('' = no figure)."""
    from core import tts_plan

    est = plan.estimate
    if est is None or est.time_high is None:
        return ""
    span = tts_plan.format_duration_range(est.time_low, est.time_high)
    where = "on this computer" if est.measured else "(estimated, not measured on this computer yet)"
    return f"{span} {where}"


def _confirm_text(plan: _JobPlan) -> str:
    from core import tts_plan

    est, disk = plan.estimate, plan.disk
    first_run = (f"the first run with at least "
                 f"{tts_plan.min_calibration_audio(plan.engine):.0f} seconds of speech "
                 "measures this computer")
    lines = []
    if est.time_high is None:
        lines.append(f"Time: not known yet for this device; {first_run}.")
    else:
        span = tts_plan.format_duration_range(est.time_low, est.time_high)
        if est.measured:
            lines.append(f"Time on this computer: {span} (measured on this computer).")
        elif _can_measure(plan):
            lines.append(f"Time: {span} on a typical computer. Measure this computer's "
                         "speed first (about 10 seconds, done once) for its own range.")
        else:
            lines.append(f"Time: {span}, estimated from a reference computer; {first_run}.")
    lines.append(
        f"Speech: {tts_plan.format_duration_range(est.audio_low, est.audio_high)}. "
        f"File: {tts_plan.format_size_range(est.size_low, est.size_high)} (WAV).")
    if not plan.installed:
        lines.append(_KOKORO_DOWNLOAD_LINE if plan.engine == "kokoro" else _OMNI_DOWNLOAD_LINE)
    drive = Path(disk.folder).anchor or disk.folder
    if disk.ok:
        lines.append(f"Free disk space: {tts_plan.format_size(disk.free_bytes)} on {drive}")
    else:
        lines.append(
            f"Not enough free disk space: this needs about "
            f"{tts_plan.format_size(disk.need_bytes)} plus "
            f"{tts_plan.format_size(disk.margin_bytes)} kept free on {drive} and only "
            f"{tts_plan.format_size(disk.free_bytes)} is free. Free some space, then "
            "try again.")
    return "\n".join(lines)


def _show_confirm(app: Any) -> None:
    """Show (or refresh) the confirm step for ``app.vc_plan``."""
    plan = app.vc_plan
    app.vc_confirm_var.set(_confirm_text(plan))
    measure = _can_measure(plan)
    for btn in (app.vc_confirm_start_btn, app.vc_confirm_measure_btn):
        btn.pack_forget()
    shown = app.vc_confirm_measure_btn if measure else app.vc_confirm_start_btn
    shown.pack(side="left", before=app.vc_confirm_cancel_btn)
    shown.configure(state="normal" if plan.disk.ok else "disabled")
    app.vc_confirm_cancel_btn.configure(state="normal")
    app.vc_confirm_frame.grid()
    # The plan is for this exact text and speed.
    app.vc_text.configure(state="disabled")
    app.vc_speed_scale.state(["disabled"])
    app.vc_confirm_open = True
    if not plan.disk.ok:
        app.vc_status_var.set("Not enough free disk space for this text.")
    elif measure:
        app.vc_status_var.set("Long text: measure this computer's speed, or Cancel.")
    else:
        app.vc_status_var.set("Long text: check the estimate, then Start or Cancel.")


def _close_confirm(app: Any) -> None:
    app.vc_confirm_frame.grid_remove()
    app.vc_text.configure(state="normal")
    app.vc_speed_scale.state(["!disabled"])
    app.vc_confirm_open = False
    app.vc_measuring = False


def _confirm_start(app: Any) -> None:
    from core import tts_plan

    plan = app.vc_plan
    if not app.vc_confirm_open or plan is None or not plan.disk.ok:
        return
    # The panel may have been open for a while: check the space again.
    plan.disk = tts_plan.check_disk(plan.estimate)
    if not plan.disk.ok:
        _show_confirm(app)
        return
    _close_confirm(app)
    _start(app)


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
    app.vc_status_var.set("Measuring this computer's speed (one time, about 10 seconds)...")

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
        _measure_failed(app, plan, "the check produced too little speech to measure",
                        cancel_event)
        return
    app.vc_measuring = False
    app.vc_cancel_event = None
    plan.calibration = cal
    plan.estimate = tts_plan.estimate(plan.text, plan.engine, plan.device, cal, plan.speed)
    plan.disk = tts_plan.check_disk(plan.estimate)
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
    app.vc_status_var.set(f"Could not measure this computer's speed ({message}); "
                          "the estimate is from a reference computer.")


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
    try:
        tts_plan.record_measurement(
            plan.engine, plan.device, plan.version, plan.hardware,
            units=plan.estimate.units,
            audio_seconds=float(result.get("audio_seconds") or 0.0),
            compute_seconds=float(result.get("elapsed_seconds") or 0.0),
            speed=plan.speed, source="run")
    except (OSError, TypeError, ValueError):
        logger.exception("Could not store the measured text-to-voice speed")


def _generate_kokoro(app: Any, text: str, play_when_done: bool = False) -> None:
    from core import tts_kokoro, voice_clone

    voice = _selected_voice(app)
    plan = app.vc_plan
    speed = plan.speed if plan is not None else float(app.vc_speed_var.get() or 1.0)
    _set_busy(app, True)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set("Preparing...")

    def worker() -> None:
        try:
            if not tts_kokoro.is_downloaded():
                def dl(done: int, total: int) -> None:
                    frac = done / total if total else 0.0
                    _set_progress(app, frac)
                    app.post_to_main(lambda: app.vc_status_var.set(
                        f"Downloading the Kokoro voice model (one time): "
                        f"{done / 1e6:.0f} / {total / 1e6:.0f} MB"))
                tts_kokoro.download(progress_cb=dl, cancel_event=cancel_event)
                app.post_to_main(lambda: _sync_engine(app))
            hint = _time_hint(plan) if plan is not None else ""
            status = f"Speaking as {voice.label}... {hint}".rstrip()
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
            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app))
            else:
                logger.exception("Kokoro generation failed")
                message = str(e)  # `e` is unbound once this block exits
                app.post_to_main(lambda: _generate_failed(app, message))

    from core._threads import safe_thread
    safe_thread(worker, name="kokoro-generate")


def _generate_omnivoice(app: Any, text: str) -> None:
    from core import voice_clone

    if _omni_refused(app):
        _finish(app)
        app.vc_plan = None
        return
    mode = app.vc_mode_var.get()
    consent = mode == _MODE_CLONE and bool(app.vc_consent_var.get())
    plan = app.vc_plan
    samples = list(app.vc_samples) if mode == _MODE_CLONE else []
    instruct = _design_instruct(app) if mode == _MODE_DESIGN else ""
    language = _language_code(app)
    speed = plan.speed if plan is not None else float(app.vc_speed_var.get() or 1.0)

    _set_busy(app, True)
    app.vc_progress.configure(mode="indeterminate")
    app.vc_progress.start(20)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set("Preparing...")

    def worker() -> None:
        try:
            if not voice_clone.is_available():
                app.post_to_main(lambda: app.vc_status_var.set(_OMNI_INSTALL_STATUS))
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
                            else "Could not download the speech model software."
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
            hint = (_time_hint(plan) if plan is not None else "") or "time not known yet"
            app.post_to_main(
                lambda: app.vc_status_var.set(f"Generating... {hint}.")
            )

            if app.vc_worker is None or not app.vc_worker.is_running():
                from app.services.voice_clone_service import VoiceCloneWorker
                app.vc_worker = VoiceCloneWorker(app.entry_file, log=app.log_threadsafe)
                app.vc_worker.start()

            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app))
                return

            output_path = os.path.join(voice_clone.session_work_dir(), "output.wav")

            def _on_model_loading() -> None:
                app.post_to_main(
                    lambda: app.vc_status_var.set(
                        "Loading the speech model (first time this session; "
                        "this may also download ~2GB of model weights -- "
                        "needs internet; a few minutes to over an hour on "
                        "a slow connection)..."
                    )
                )

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
            if cancel_event.is_set():
                logger.info("Voice-clone generation cancelled")
                app.post_to_main(lambda: _generate_cancelled(app))
            else:
                logger.exception("Voice-clone generation failed")
                # Capture the message now, not `e` itself: Python deletes
                # the `except ... as e` name when this block exits (PEP
                # 3110), before post_to_main's queued lambda runs.
                message = str(e)
                app.post_to_main(lambda: _generate_failed(app, message))

    from core._threads import safe_thread
    safe_thread(worker, name="voice-clone-generate")


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
    status = f"Done: {audio:.0f}s of speech in {elapsed:.0f}s." if audio else f"Done in {elapsed:.0f}s."
    warning = result.get("warning") or ""
    if warning:
        status += " Warning: the consent record was not saved (see the log)."
    app.vc_status_var.set(status)
    app.log(f"Text to voice finished: {app.vc_last_output}")
    if warning:
        app.log(warning)
    _record_speed(app, result)
    if play:
        _play(app)


def _generate_failed(app: Any, message: str) -> None:
    _finish(app)
    app.vc_plan = None
    app.vc_status_var.set("Failed.")
    show_error(
        app, "Generation failed", message,
        detail=(
            "If this looks like a network or download problem, check your "
            "internet connection, then click Generate again to retry."
        ),
    )


def _generate_cancelled(app: Any) -> None:
    _finish(app)
    app.vc_plan = None
    app.vc_status_var.set("Cancelled.")


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
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        show_error(app, "Could not play the result", str(e))


def _save(app: Any) -> None:
    path = app.vc_last_output
    if not path or not os.path.isfile(path):
        return
    dest = filedialog.asksaveasfilename(
        parent=app, title="Save generated speech",
        defaultextension=".wav",
        filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        initialfile="cloned-voice.wav",
    )
    if not dest:
        return
    try:
        import shutil
        shutil.copyfile(path, dest)
    except OSError as e:
        show_error(app, "Could not save the file", str(e))
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
