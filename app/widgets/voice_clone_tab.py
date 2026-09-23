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

CPU generation measured ~50-57x slower than real-time in
pre-implementation testing (see docs/SESSION_HANDOFF_NEXT.md, 2026-09-12
entry) -- the status label always shows a concrete time estimate before
a run starts, never a bare "please wait".
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from app.widgets.error_dialog import show_error
from app.widgets.tooltip import section_labelframe

logger = logging.getLogger(__name__)

_SAMPLE_SECONDS = 6
# Measured on a representative consumer CPU (8 logical cores, no GPU) --
# see docs/SESSION_HANDOFF_NEXT.md. Used only to word the estimate the
# UI shows before a run; the real number depends on the machine and the
# text length, so this is deliberately described as approximate.
_MEASURED_CPU_RTF = 55.0

_CONSENT_TEXT = (
    "This feature clones a voice from a short recording and can make it "
    "say anything you type.\n\n"
    "Only use it with a voice you own, or that you have the speaker's "
    "clear permission to clone. Do not use it to impersonate someone "
    "without their consent, or to create misleading audio of real "
    "people.\n\n"
    "The OmniVoice model downloads to this computer the first time you "
    "continue (about 2GB total, one-time). This needs an internet "
    "connection and can take anywhere from a few minutes to over an "
    "hour depending on your connection speed -- after that, generation "
    "runs fully offline.\n\n"
    "Continue?"
)

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
    from core import tts_kokoro
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
        f"Up to {_vc.MAX_TEXT_CHARS} characters. Long text is split into "
        "sentences and joined back into one audio file.",
    )
    txt.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 6))
    txt.columnconfigure(0, weight=1)
    txt.rowconfigure(0, weight=1)
    app.vc_text = tk.Text(txt, wrap="word", height=6, undo=True)
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
    ttk.Label(opts, text="Speed:").pack(side="left")
    ttk.Scale(opts, from_=0.5, to=2.0, variable=app.vc_speed_var, length=140,
              command=lambda _v: app.vc_speed_label.configure(
                  text=f"{app.vc_speed_var.get():.2f}x")).pack(side="left", padx=6)
    app.vc_speed_label = ttk.Label(opts, text="1.00x", width=6)
    app.vc_speed_label.pack(side="left")
    ttk.Label(opts, textvariable=app.vc_count_var, foreground="#666").pack(side="right")

    # ── Generate ──────────────────────────────────────────────────────
    out = ttk.Frame(parent)
    out.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 4))
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
        row=4, column=0, sticky="w", padx=15, pady=(0, 2))
    ttk.Label(
        parent,
        text=("AI-generated audio. Only clone voices you have the right "
              "to use -- see the confirmation shown before your first clone."),
        foreground="#666",
    ).grid(row=5, column=0, sticky="w", padx=15, pady=(0, 12))

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
    _save_prefs(app)


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
    from core.voice_clone import MAX_TEXT_CHARS

    try:
        app.vc_text.edit_modified(False)
        n = len(app.vc_text.get("1.0", "end-1c"))
    except Exception:  # noqa: BLE001
        return
    app.vc_count_var.set(f"{n:,} / {MAX_TEXT_CHARS:,} characters")


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
    app.vc_status_var.set(f"{len(app.vc_samples)} reference sample(s).")


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
    app.vc_status_var.set(f"{len(app.vc_samples)} reference sample(s).")


# --------------------------------------------------------------- consent


def _consent_accepted(app: Any) -> bool:
    cfg = app.app_config.setdefault("voice_clone", {})
    if cfg.get("consent_accepted"):
        return True
    accepted = messagebox.askyesno(
        "Clone Your Voice / Text to Voice", _CONSENT_TEXT,
        icon="warning", parent=app,
    )
    if accepted:
        cfg["consent_accepted"] = True
        from core.config import save_config
        try:
            save_config(app.app_config)
        except Exception:  # noqa: BLE001
            logger.exception("Could not persist voice-clone consent")
    return bool(accepted)


# --------------------------------------------------------------- generate


def _set_busy(app: Any, busy: bool) -> None:
    app.vc_generate_btn.configure(state="disabled" if busy else "normal")
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
    _generate_kokoro(app, _PREVIEW_TEXT.get(voice.language, _PREVIEW_TEXT["US English"]),
                     play_when_done=True)


def _generate(app: Any) -> None:
    from core import voice_clone

    text = app.vc_text.get("1.0", "end").strip()
    if not text:
        show_error(app, "No text", "Type the text you want spoken.")
        return
    if len(text) > voice_clone.MAX_TEXT_CHARS:
        show_error(
            app, "Text too long",
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {voice_clone.MAX_TEXT_CHARS}.",
        )
        return
    if _is_kokoro(app):
        _generate_kokoro(app, text)
    else:
        _generate_omnivoice(app, text)


def _generate_kokoro(app: Any, text: str, play_when_done: bool = False) -> None:
    from core import tts_kokoro, voice_clone

    voice = _selected_voice(app)
    speed = float(app.vc_speed_var.get() or 1.0)
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
            app.post_to_main(lambda: app.vc_status_var.set(
                f"Speaking as {voice.label}..."))
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

    mode = app.vc_mode_var.get()
    if mode == _MODE_CLONE:
        if not app.vc_samples:
            show_error(app, "No reference voice",
                       "Record or load at least one reference clip first, or "
                       "choose \"Design a voice\" / \"Let the model choose\".")
            return
        if not _consent_accepted(app):
            return
    samples = list(app.vc_samples) if mode == _MODE_CLONE else []
    instruct = _design_instruct(app) if mode == _MODE_DESIGN else ""
    language = _language_code(app)
    speed = float(app.vc_speed_var.get() or 1.0)

    _set_busy(app, True)
    app.vc_progress.configure(mode="indeterminate")
    app.vc_progress.start(20)
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set("Preparing...")

    def worker() -> None:
        try:
            if not voice_clone.is_available():
                app.post_to_main(
                    lambda: app.vc_status_var.set(
                        "Downloading the OmniVoice software (one-time, "
                        "~2GB -- needs internet, can take a while)..."
                    )
                )
                ok = voice_clone.ensure_installed(
                    log_cb=app.log_threadsafe, cancel_event=cancel_event
                )
                if not ok:
                    if cancel_event.is_set():
                        app.post_to_main(lambda: _generate_cancelled(app))
                    else:
                        app.post_to_main(lambda: _generate_failed(
                            app, "Could not download the speech model software."
                        ))
                    return

            # Nothing else re-checks cancel_event before generate() below
            # (e.g. during the first `import torch` in default_device()).
            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app))
                return

            device = voice_clone.default_device()
            minutes = _estimate_minutes(text)
            est = "a few minutes" if device == "cuda" else \
                f"roughly {minutes} minutes on this CPU"
            app.post_to_main(
                lambda: app.vc_status_var.set(f"Generating... estimated {est}.")
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
                consent_accepted=bool(samples), device=device,
                on_model_loading=_on_model_loading,
                instruct=instruct, language=language, speed=speed,
                # Generous: 3x the CPU estimate, never below the default.
                timeout_s=minutes * 60.0 * 3,
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


def _estimate_minutes(text: str) -> int:
    # Rough: ~2.5 words/second of natural speech, ~5.5 chars/word average.
    approx_seconds = len(text) / 5.5 / 2.5
    minutes = (approx_seconds * _MEASURED_CPU_RTF) / 60.0
    return max(1, round(minutes))


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
    app.vc_status_var.set(
        f"Done: {audio:.0f}s of speech in {elapsed:.0f}s." if audio else f"Done in {elapsed:.0f}s.")
    app.log(f"Text to voice finished: {app.vc_last_output}")
    if play:
        _play(app)


def _generate_failed(app: Any, message: str) -> None:
    _finish(app)
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
    app.vc_status_var.set("Cancelled.")


def _cancel_generate(app: Any) -> None:
    cancel_event = getattr(app, "vc_cancel_event", None)
    if cancel_event is not None:
        cancel_event.set()
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
