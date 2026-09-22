"""The Live tab — transcribe a microphone or the system audio as it plays.

Kept out of ``tabs.py`` (already ~1100 lines) but follows the same
contract: ``build_live_tab(app, parent)`` assigns its widgets and vars
onto the ``App`` instance.

Threading, which is the whole trick here:

  * ``core.live.LiveSession`` captures on the recorder's thread and
    transcribes on its own consumer thread. Neither touches a widget.
  * Everything reaches the UI through ``session.drain_events()``, polled
    from an ``after()`` loop on the Tk main thread — the same pattern the
    rest of this app uses for worker/download events.
  * Start/Stop do subprocess work (spawning a worker, loading a ~3 GB
    model), so they run off-thread and report back via
    ``app.post_to_main``. Doing them inline would freeze the window for
    the entire model load.
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any

from app.widgets.error_dialog import show_error
from app.widgets.tooltip import help_icon, section_labelframe

logger = logging.getLogger(__name__)

_POLL_MS = 200

_SOURCE_MIC = "Microphone"
_SOURCE_SYSTEM = "System audio (what you hear)"

# Keys that never modify text -- letting these through even while the
# transcript is "read-only" keeps navigation, selection-extend, and the
# Ctrl-combo shortcuts (checked via the modifier bit below) working.
_NAV_KEYSYMS = frozenset((
    "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Tab", "Escape",
))
_CONTROL_MASK = 0x4  # Tk Event.state bit for the Control modifier


def _blocks_edit(keysym: str, state: "int | str") -> bool:
    """True if a keypress with this keysym/modifier-state should be
    swallowed to stop it from typing into a "read-only but selectable"
    Text widget. Navigation keys and any Ctrl-combo (copy, select-all,
    ...) pass through; everything else is blocked.
    """
    if isinstance(state, int) and state & _CONTROL_MASK:
        return False
    return keysym not in _NAV_KEYSYMS


def _make_readonly_but_selectable(text: tk.Text) -> None:
    """Keep *text* mouse-selectable and copyable without letting the user
    type into it -- a plain ``state="disabled"`` Text widget blocks mouse
    drag-selection entirely, not just editing, which was a real reported
    complaint (a transcript a user cannot select-and-copy by dragging).
    Programmatic ``insert``/``delete`` (this module's own ``_append``/
    ``_clear``) are unaffected; only user keystrokes are filtered.
    """
    def _filter_key(event: "tk.Event[tk.Text]") -> str | None:
        return "break" if _blocks_edit(event.keysym, event.state) else None

    text.bind("<Key>", _filter_key)


def build_live_tab(app: Any, parent: Any) -> None:
    """Construct the Live tab onto ``parent`` and wire it to ``app``."""
    from core import live as _live

    app.live_session = None
    app.live_transcriber = None
    app.live_lines = []
    app._live_poll_scheduled = False
    app._live_cancel_pending = False

    app.live_source_var = tk.StringVar(value=_SOURCE_MIC)
    app.live_device_var = tk.StringVar(value="Default input device")
    app.live_lang_var = tk.StringVar(value="Auto")
    app.live_status_var = tk.StringVar(value="Idle.")

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(3, weight=1)

    # ── Source ────────────────────────────────────────────────────────
    src = section_labelframe(
        parent, "Audio source",
        "Choose what to listen to. 'Microphone' captures an input device; "
        "'System audio' captures whatever is currently playing on this "
        "computer — useful for a meeting, a video, or a call you are "
        "listening to.",
    )
    src.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 6))
    src.columnconfigure(1, weight=1)

    ttk.Label(src, text="Source:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
    sources = [_SOURCE_MIC]
    if _live.is_available("loopback"):
        sources.append(_SOURCE_SYSTEM)
    app.live_source_combo = ttk.Combobox(
        src, textvariable=app.live_source_var, values=sources,
        state="readonly", width=32,
    )
    app.live_source_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
    app.live_source_combo.bind(
        "<<ComboboxSelected>>", lambda _e: _sync_device_state(app)
    )

    ttk.Label(src, text="Device:").grid(row=1, column=0, sticky="e", padx=8, pady=6)
    app.live_device_combo = ttk.Combobox(
        src, textvariable=app.live_device_var, state="readonly", width=48,
    )
    app.live_device_combo.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
    ttk.Button(
        src, text="Refresh", command=lambda: _refresh_devices(app),
    ).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=6)

    ttk.Label(src, text="Language:").grid(row=2, column=0, sticky="e", padx=8, pady=6)
    # Same name->code table the Transcribe tab uses, so the two agree.
    # Entries with an empty code (yt-dlp's "Automatic") are dropped: they
    # mean auto-detect, which "Auto" above already covers, and listing
    # both makes the dropdown look like it offers two different things.
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    app.live_lang_combo = ttk.Combobox(
        src, textvariable=app.live_lang_var, state="readonly", width=32,
        values=["Auto"] + [name for name, code in _LANGS if code],
    )
    app.live_lang_combo.grid(row=2, column=1, sticky="w", padx=8, pady=6)
    help_icon(
        src,
        "Naming the language is more reliable than auto-detect for live "
        "audio: each chunk is short, and detection on a few seconds of "
        "speech can guess wrong and switch mid-session.",
    ).grid(row=2, column=2, sticky="w", padx=(0, 8), pady=6)

    # ── Controls ──────────────────────────────────────────────────────
    ctl = ttk.Frame(parent)
    ctl.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 6))
    app.live_start_btn = ttk.Button(
        ctl, text="Start listening", command=lambda: _start(app),
    )
    app.live_start_btn.pack(side="left")
    app.live_stop_btn = ttk.Button(
        ctl, text="Stop", command=lambda: _stop(app), state="disabled",
    )
    app.live_stop_btn.pack(side="left", padx=(8, 0))
    ttk.Label(ctl, textvariable=app.live_status_var, foreground="#666").pack(
        side="left", padx=(16, 0)
    )

    # ── Level meter ───────────────────────────────────────────────────
    # Independent Tk implementation inspired by TranscriptionSuite's
    # AudioVisualizer (see app/widgets/audio_visualizer.py for the
    # license note and the visible differences). Fed by the recorder's
    # capture thread via LiveSession.on_meter; drawing stays on Tk.
    from app.widgets.audio_visualizer import AudioVisualizer

    lvl = section_labelframe(
        parent, "Input level",
        "Live audio level while listening. Bars move with the sound "
        "coming in; when nothing moves, nothing is being captured.",
    )
    lvl.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 6))
    lvl.columnconfigure(0, weight=1)
    app.live_visualizer = AudioVisualizer(lvl, height=110)
    app.live_visualizer.frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

    # ── Transcript ────────────────────────────────────────────────────
    out = section_labelframe(
        parent, "Live transcript",
        "Text appears a few seconds behind the speech: the app waits for a "
        "natural pause before transcribing, so words are not cut in half.",
    )
    out.grid(row=3, column=0, sticky="nsew", padx=15, pady=(0, 6))
    out.columnconfigure(0, weight=1)
    out.rowconfigure(0, weight=1)

    app.live_text = tk.Text(out, wrap="word", height=14)
    _make_readonly_but_selectable(app.live_text)
    app.live_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
    bar = ttk.Scrollbar(out, orient="vertical", command=app.live_text.yview)
    bar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
    app.live_text.configure(yscrollcommand=bar.set)

    actions = ttk.Frame(parent)
    actions.grid(row=4, column=0, sticky="ew", padx=15, pady=(0, 15))
    ttk.Button(actions, text="Save transcript…",
               command=lambda: _save(app)).pack(side="left")
    ttk.Button(actions, text="Copy all",
               command=lambda: _copy(app)).pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="Clear",
               command=lambda: _clear(app)).pack(side="left", padx=(8, 0))
    ttk.Label(
        actions,
        text=("Uses its own copy of the speech model while listening, "
              "separate from the Transcribe queue."),
        foreground="#666",
    ).pack(side="right")

    _refresh_devices(app)
    _sync_device_state(app)


# ------------------------------------------------------------- devices


def _refresh_devices(app: Any) -> None:
    from core import live as _live

    names = ["Default input device"]
    app.live_device_map = {}
    try:
        for dev in _live.list_input_devices():
            label = f"{dev.index}: {dev.name}"
            names.append(label)
            app.live_device_map[label] = dev.index
    except Exception:  # noqa: BLE001
        logger.exception("Listing input devices failed")
    try:
        app.live_device_combo.configure(values=names)
        if app.live_device_var.get() not in names:
            app.live_device_var.set(names[0])
    except Exception:  # noqa: BLE001
        logger.debug("Could not refresh the device list", exc_info=True)


def _sync_device_state(app: Any) -> None:
    """The device picker only applies to microphone capture."""
    try:
        is_mic = app.live_source_var.get() == _SOURCE_MIC
        app.live_device_combo.configure(
            state=("readonly" if is_mic else "disabled")
        )
    except Exception:  # noqa: BLE001
        logger.debug("Could not sync the device picker", exc_info=True)


def _selected_device_index(app: Any) -> int | None:
    label = app.live_device_var.get()
    return getattr(app, "live_device_map", {}).get(label)


def _selected_language_code(app: Any) -> str | None:
    """Display name -> language code, or None for auto-detect.

    Mirrors ``App._apply_transcribe_options``: an unknown name or an
    empty code means "let the model decide" rather than forcing a bad
    code onto the engine.
    """
    name = (app.live_lang_var.get() or "").strip()
    if not name or name.lower() == "auto":
        return None
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS
    code = next((c for display, c in _LANGS if display == name), "")
    return code or None


# ------------------------------------------------------------ start/stop


def _set_running(app: Any, running: bool) -> None:
    try:
        app.live_start_btn.configure(state=("disabled" if running else "normal"))
        app.live_stop_btn.configure(state=("normal" if running else "disabled"))
        for widget in (app.live_source_combo, app.live_lang_combo):
            widget.configure(state=("disabled" if running else "readonly"))
        if not running:
            _sync_device_state(app)
        else:
            app.live_device_combo.configure(state="disabled")
    except Exception:  # noqa: BLE001
        logger.debug("Could not update live controls", exc_info=True)


def _start(app: Any) -> None:
    from core import live as _live

    mode = "loopback" if app.live_source_var.get() == _SOURCE_SYSTEM else "mic"
    if not _live.is_available(mode):
        show_error(
            app, "Cannot listen yet",
            "This computer cannot capture that audio source yet.",
            detail=_live.availability_reason(mode),
        )
        return

    app.live_status_var.set("Loading the speech model…")
    app._live_cancel_pending = False
    _set_running(app, True)

    language = _selected_language_code(app)
    device_index = _selected_device_index(app) if mode == "mic" else None
    work_dir = _live.session_work_dir()
    viz = getattr(app, "live_visualizer", None)

    def _meter(pcm: bytes, rate: int) -> None:
        # Runs on the recorder's capture thread: push_frames is
        # thread-safe (stores under a lock; drawing stays on Tk).
        try:
            if viz is not None and pcm:
                viz.push_frames(pcm, rate)
        except Exception:  # noqa: BLE001
            logger.debug("Live meter push failed", exc_info=True)

    def worker() -> None:
        # Spawning a worker and loading a ~3 GB model takes tens of
        # seconds; doing it on the Tk thread would freeze the window.
        from app.services.live_service import LiveTranscriber

        transcriber = None
        try:
            transcriber = LiveTranscriber(
                app.entry_file, language=language, log=app.log
            )
            transcriber.start()
            session = _live.LiveSession(
                transcribe_chunk=transcriber.transcribe_chunk,
                work_dir=work_dir,
                mode=mode,
                device_index=device_index,
                language=language,
                on_meter=_meter,
            )
            session.start()
        except Exception as e:  # noqa: BLE001
            logger.exception("Live session failed to start: %s", e)
            if transcriber is not None:
                try:
                    transcriber.stop()
                except Exception:  # noqa: BLE001
                    pass
            # Capture now, not `e` itself: Python deletes the `except ...
            # as e` name when this block exits (PEP 3110), which happens
            # before post_to_main's queued lambda ever runs on the Tk
            # thread -- a lambda closing over `e` directly raised
            # NameError there instead of calling _start_failed, leaving
            # the tab stuck showing "Loading the speech model..." with no
            # error and _set_running never reset to False (same bug class
            # fixed in app/widgets/voice_clone_tab.py, 2026-09-14).
            failure = e
            app.post_to_main(lambda: _start_failed(app, failure))
            return
        app.post_to_main(lambda: _started(app, transcriber, session))

    app.post_to_main  # touch attr early so a missing bridge fails loudly
    import threading

    threading.Thread(target=worker, name="live-start", daemon=True).start()


def _started(app: Any, transcriber: Any, session: Any) -> None:
    if getattr(app, "_live_cancel_pending", False):
        # The user hit Stop while the model was still loading (see
        # _stop). Tear this session down immediately instead of
        # activating it — it must never become a running-but-unreachable
        # orphan.
        app._live_cancel_pending = False
        app.live_transcriber = transcriber
        app.live_session = session
        app.log("Live transcription started then immediately stopped (cancelled during load).")

        def worker() -> None:
            try:
                session.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Stopping the just-started live session failed")
            try:
                transcriber.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Stopping the live worker failed")
            app.post_to_main(lambda: _stopped(app))

        import threading

        threading.Thread(target=worker, name="live-start-cancel", daemon=True).start()
        return

    app.live_transcriber = transcriber
    app.live_session = session
    app.live_status_var.set("Listening…")
    app.log("Live transcription started.")
    try:
        viz = getattr(app, "live_visualizer", None)
        if viz is not None:
            viz.set_active(True)
    except Exception:  # noqa: BLE001
        logger.debug("Could not activate visualizer", exc_info=True)
    _schedule_poll(app)


def _start_failed(app: Any, error: Exception) -> None:
    app._live_cancel_pending = False
    app.live_session = None
    app.live_transcriber = None
    _set_running(app, False)
    app.live_status_var.set("Idle.")
    try:
        viz = getattr(app, "live_visualizer", None)
        if viz is not None:
            viz.set_active(False)
    except Exception:  # noqa: BLE001
        logger.debug("Could not deactivate visualizer", exc_info=True)
    show_error(
        app, "Could not start listening",
        "The live session could not be started.", detail=str(error),
    )


def _stop(app: Any) -> None:
    session = app.live_session
    transcriber = app.live_transcriber
    if session is None:
        # The worker is still loading the model and hasn't reached
        # _started yet. Recording the cancellation (instead of just
        # resetting the buttons and returning) is what closes the
        # unstoppable-session gap: _started checks this flag and tears
        # the just-created session down immediately, rather than the
        # request being silently dropped and the session running on
        # with Start re-enabled and no way left to stop it.
        app._live_cancel_pending = True
        app.live_status_var.set("Will stop once loading finishes…")
        try:
            app.live_stop_btn.configure(state="disabled")
        except Exception:  # noqa: BLE001
            logger.debug("Could not update live controls", exc_info=True)
        return
    app.live_status_var.set("Finishing the last few seconds…")
    app.live_stop_btn.configure(state="disabled")

    def worker() -> None:
        try:
            session.stop()
        except Exception as e:  # noqa: BLE001
            logger.exception("Stopping the live session failed: %s", e)
        try:
            if transcriber is not None:
                transcriber.stop()
        except Exception as e:  # noqa: BLE001
            logger.exception("Stopping the live worker failed: %s", e)
        app.post_to_main(lambda: _stopped(app))

    import threading

    threading.Thread(target=worker, name="live-stop", daemon=True).start()


def _stopped(app: Any) -> None:
    # Drain whatever the tail produced before dropping the session.
    _poll_once(app)
    app.live_session = None
    app.live_transcriber = None
    _set_running(app, False)
    app.live_status_var.set("Stopped.")
    app.log("Live transcription stopped.")
    try:
        viz = getattr(app, "live_visualizer", None)
        if viz is not None:
            viz.set_active(False)
    except Exception:  # noqa: BLE001
        logger.debug("Could not deactivate visualizer", exc_info=True)


def stop_live_session(app: Any) -> None:
    """Tear the session down on app exit. Safe when nothing is running."""
    session = getattr(app, "live_session", None)
    transcriber = getattr(app, "live_transcriber", None)
    if session is not None:
        try:
            session.stop(timeout=3.0)
        except Exception:  # noqa: BLE001
            logger.exception("Live session teardown failed")
    if transcriber is not None:
        try:
            transcriber.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Live worker teardown failed")
    app.live_session = None
    app.live_transcriber = None
    try:
        viz = getattr(app, "live_visualizer", None)
        if viz is not None:
            viz.set_active(False)
    except Exception:  # noqa: BLE001
        logger.debug("Could not deactivate visualizer", exc_info=True)


# --------------------------------------------------------------- polling


def _schedule_poll(app: Any) -> None:
    if getattr(app, "_live_poll_scheduled", False):
        return
    app._live_poll_scheduled = True
    app.after(_POLL_MS, lambda: _poll(app))


def _poll(app: Any) -> None:
    app._live_poll_scheduled = False
    _poll_once(app)
    if app.live_session is not None and not getattr(app, "_closing", False):
        _schedule_poll(app)


def _poll_once(app: Any) -> None:
    session = app.live_session
    if session is None:
        return
    try:
        events = session.drain_events()
    except Exception:  # noqa: BLE001
        logger.exception("Draining live events failed")
        return
    for ev in events:
        if ev.kind == "text":
            _append_line(app, ev.text)
        elif ev.kind == "warning":
            app.live_status_var.set(ev.detail)
            app.log(f"Live: {ev.detail}")
        elif ev.kind == "error":
            app.log(f"Live error: {ev.detail}")
        elif ev.kind == "state" and ev.detail == "started":
            app.live_status_var.set("Listening…")


def _append_line(app: Any, text: str) -> None:
    if not text:
        return
    app.live_lines.append(text)
    try:
        widget = app.live_text
        at_bottom = widget.yview()[1] >= 0.999
        # Widget stays state="normal" (see _make_readonly_but_selectable);
        # only the <Key> filter keeps the user from typing into it, so
        # this insert needs no enable/disable dance around it.
        widget.insert("end", text + "\n")
        # Only follow the tail when the user has not scrolled up to read
        # something earlier — yanking the view is worse than lagging it.
        if at_bottom:
            widget.see("end")
    except Exception:  # noqa: BLE001
        logger.debug("Could not append live text", exc_info=True)


# --------------------------------------------------------------- actions


def _transcript_text(app: Any) -> str:
    return "\n".join(getattr(app, "live_lines", []) or []).strip()


def _save(app: Any) -> None:
    body = _transcript_text(app)
    if not body:
        show_error(app, "Nothing to save",
                   "The live transcript is empty.")
        return
    path = filedialog.asksaveasfilename(
        parent=app, title="Save live transcript",
        defaultextension=".txt",
        filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
        initialfile="live-transcript.txt",
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(body + "\n")
    except OSError as e:
        show_error(app, "Could not save the transcript",
                   f"Writing {os.path.basename(path)} failed.", detail=str(e))
        return
    app.log(f"Live transcript saved to {path}")


def _copy(app: Any) -> None:
    body = _transcript_text(app)
    if not body:
        return
    try:
        app.clipboard_clear()
        app.clipboard_append(body)
    except Exception:  # noqa: BLE001
        logger.debug("Clipboard copy failed", exc_info=True)


def _clear(app: Any) -> None:
    app.live_lines = []
    try:
        app.live_text.delete("1.0", "end")
    except Exception:  # noqa: BLE001
        logger.debug("Could not clear the live transcript", exc_info=True)
