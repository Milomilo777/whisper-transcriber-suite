"""The Clone Your Voice / Text to Voice tab.

Completely independent feature: record or load a few short reference
samples of a voice, type text, generate that text spoken back in the
cloned voice. Off by default (see ``core.hub.voice_clone_tab_enabled``);
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
    "The speech model downloads to this computer the first time you "
    "continue (about 2GB total, one-time). This needs an internet "
    "connection and can take anywhere from a few minutes to over an "
    "hour depending on your connection speed -- after that, generation "
    "runs fully offline.\n\n"
    "Continue?"
)

_DOWNLOAD_NOTE = (
    "Engine: OmniVoice (Apache-2.0, k2-fsa), runs locally. The first "
    "generation downloads about 2GB of software and model files -- this "
    "needs an internet connection and can take from a few minutes to "
    "over an hour depending on your connection. After that one-time "
    "download, generation runs fully offline."
)


def _sweep_scratch_dirs() -> None:
    from core.voice_clone import sweep_old_session_dirs
    sweep_old_session_dirs()


def build_voice_clone_tab(app: Any, parent: Any) -> None:
    """Construct the Clone Your Voice tab onto ``parent`` and wire it to ``app``."""
    app.vc_samples = []
    app.vc_worker = None
    app.vc_last_output = None
    app.vc_recorder = None
    app.vc_cancel_event = None
    app.vc_recording_after_id = None
    app.vc_status_var = tk.StringVar(value="Idle.")

    # Best-effort sweep of aged-out scratch dirs (past reference
    # recordings + generated output under session_work_dir()) from
    # earlier sessions -- mirrors the app's own aged-out-partials sweep
    # for the transcription queue. Delayed so it never competes with
    # this tab's own first paint.
    app.after(2000, _sweep_scratch_dirs)

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)

    # ── Reference voice ─────────────────────────────────────────────────
    ref = section_labelframe(
        parent, "Reference voice",
        "Record or load 1-3 short clips (3-10 seconds each) of the voice "
        "to clone. More than one clip generally improves similarity.",
    )
    ref.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 6))
    ref.columnconfigure(0, weight=1)

    app.vc_samples_listbox = tk.Listbox(ref, height=4)
    app.vc_samples_listbox.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

    ref_btns = ttk.Frame(ref)
    ref_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
    app.vc_record_btn = ttk.Button(
        ref_btns, text=f"Record sample ({_SAMPLE_SECONDS}s)",
        command=lambda: _record_sample(app),
    )
    app.vc_record_btn.pack(side="left")
    ttk.Button(
        ref_btns, text="Load audio file...",
        command=lambda: _load_sample(app),
    ).pack(side="left", padx=(8, 0))
    ttk.Button(
        ref_btns, text="Remove selected",
        command=lambda: _remove_sample(app),
    ).pack(side="left", padx=(8, 0))

    # ── Text to speak ────────────────────────────────────────────────────
    from core.voice_clone import MAX_TEXT_CHARS

    txt = section_labelframe(
        parent, "Text to speak",
        f"Up to {MAX_TEXT_CHARS} characters per generation.",
    )
    txt.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 6))
    txt.columnconfigure(0, weight=1)
    app.vc_text = tk.Text(txt, wrap="word", height=5)
    app.vc_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

    # ── Controls / result ────────────────────────────────────────────────
    out = section_labelframe(
        parent, "Generate",
        "Generation runs entirely on this computer. Without a compatible "
        "GPU this is slow -- the status line shows an estimate before it "
        "starts.",
    )
    out.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 6))
    out.columnconfigure(0, weight=1)

    ttk.Label(
        out, text=_DOWNLOAD_NOTE, foreground="#666", wraplength=640, justify="left",
    ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))

    ctl = ttk.Frame(out)
    ctl.grid(row=1, column=0, sticky="w", padx=8, pady=8)
    app.vc_generate_btn = ttk.Button(
        ctl, text="Generate", command=lambda: _generate(app),
    )
    app.vc_generate_btn.pack(side="left")
    app.vc_cancel_btn = ttk.Button(
        ctl, text="Cancel", command=lambda: _cancel_generate(app), state="disabled",
    )
    app.vc_cancel_btn.pack(side="left", padx=(8, 0))
    app.vc_play_btn = ttk.Button(
        ctl, text="Play result", command=lambda: _play(app), state="disabled",
    )
    app.vc_play_btn.pack(side="left", padx=(8, 0))
    app.vc_save_btn = ttk.Button(
        ctl, text="Save As...", command=lambda: _save(app), state="disabled",
    )
    app.vc_save_btn.pack(side="left", padx=(8, 0))

    ttk.Label(out, textvariable=app.vc_status_var, foreground="#666").grid(
        row=2, column=0, sticky="w", padx=8, pady=(0, 8)
    )

    ttk.Label(
        parent,
        text=("AI-generated audio. Only clone voices you have the right "
              "to use -- see the confirmation shown before your first "
              "generation."),
        foreground="#666",
    ).grid(row=3, column=0, sticky="w", padx=15, pady=(0, 15))


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


def _generate(app: Any) -> None:
    if not app.vc_samples:
        show_error(app, "No reference voice", "Record or load at least one reference clip first.")
        return
    text = app.vc_text.get("1.0", "end").strip()
    if not text:
        show_error(app, "No text", "Type the text you want spoken.")
        return

    from core import voice_clone

    if len(text) > voice_clone.MAX_TEXT_CHARS:
        show_error(
            app, "Text too long",
            f"Text is {len(text)} characters; the limit for one "
            f"generation is {voice_clone.MAX_TEXT_CHARS}.",
        )
        return
    if not _consent_accepted(app):
        return

    app.vc_generate_btn.configure(state="disabled")
    app.vc_cancel_btn.configure(state="normal")
    cancel_event = threading.Event()
    app.vc_cancel_event = cancel_event
    app.vc_status_var.set("Preparing...")

    def worker() -> None:
        try:
            if not voice_clone.is_available():
                app.post_to_main(
                    lambda: app.vc_status_var.set(
                        "Downloading the speech model software (one-time, "
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

            # The Cancel button only stops an in-flight install or an
            # already-running worker (see _cancel_generate) -- nothing
            # re-checks cancel_event between here and the actual generate()
            # call below, so a Cancel click landing in this gap (e.g.
            # during the first-time `import torch` that default_device()
            # below can trigger, which takes several seconds) would
            # otherwise be silently ignored and the generation would run
            # to completion anyway. Check explicitly.
            if cancel_event.is_set():
                app.post_to_main(lambda: _generate_cancelled(app))
                return

            device = voice_clone.default_device()
            est = "a few minutes" if device == "cuda" else \
                f"roughly {_estimate_minutes(text)} minutes on this CPU"
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

            out_dir = voice_clone.session_work_dir()
            output_path = os.path.join(out_dir, "output.wav")

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
                text, list(app.vc_samples), output_path,
                consent_accepted=True, device=device, on_model_loading=_on_model_loading,
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
                # 3110), which happens before post_to_main's queued lambda
                # ever runs on the Tk thread -- a lambda closing over `e`
                # directly raises NameError there instead of calling
                # _generate_failed, silently wedging the tab on every
                # failure (Generate stays disabled, no error dialog shown).
                message = str(e)
                app.post_to_main(lambda: _generate_failed(app, message))

    from core._threads import safe_thread
    safe_thread(worker, name="voice-clone-generate")


def _estimate_minutes(text: str) -> int:
    # Rough: ~2.5 words/second of natural speech, ~5.5 chars/word average.
    approx_seconds = len(text) / 5.5 / 2.5
    minutes = (approx_seconds * _MEASURED_CPU_RTF) / 60.0
    return max(1, round(minutes))


def _generate_done(app: Any, result: dict[str, Any]) -> None:
    app.vc_generate_btn.configure(state="normal")
    app.vc_cancel_btn.configure(state="disabled")
    app.vc_cancel_event = None
    app.vc_last_output = result.get("output_path") or None
    if app.vc_last_output:
        app.vc_play_btn.configure(state="normal")
        app.vc_save_btn.configure(state="normal")
    elapsed = result.get("elapsed_seconds") or 0.0
    app.vc_status_var.set(f"Done in {elapsed:.0f}s.")
    app.log(f"Voice-clone generation finished: {app.vc_last_output}")


def _generate_failed(app: Any, message: str) -> None:
    app.vc_generate_btn.configure(state="normal")
    app.vc_cancel_btn.configure(state="disabled")
    app.vc_cancel_event = None
    app.vc_status_var.set("Failed.")
    show_error(
        app, "Generation failed", message,
        detail=(
            "If this looks like a network or download problem, check your "
            "internet connection, then click Generate again to retry."
        ),
    )


def _generate_cancelled(app: Any) -> None:
    app.vc_generate_btn.configure(state="normal")
    app.vc_cancel_btn.configure(state="disabled")
    app.vc_cancel_event = None
    app.vc_status_var.set("Cancelled.")


def _cancel_generate(app: Any) -> None:
    cancel_event = getattr(app, "vc_cancel_event", None)
    if cancel_event is not None:
        cancel_event.set()
    app.vc_cancel_btn.configure(state="disabled")
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
