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


_MODEL_AUTO = "Automatic (fast enough for this computer)"
_MODEL_MAIN = "Same as the Transcribe tab"

_MISSING_FG = "#8a8a8a"
_MODEL_MISSING_STYLE = "LiveModelMissing.TMenubutton"
_MODEL_READY_STYLE = "LiveModelReady.TMenubutton"


def _live_model_choices(app: Any) -> list[tuple[str, str]]:
    """``[(label, live_model value), ...]`` for the Model picker."""
    out = [(_MODEL_AUTO, "auto"), (_MODEL_MAIN, "main")]
    try:
        from core.model_manager import catalog_models

        out += [(label, slug) for slug, label in catalog_models(app.app_config)]
    except Exception:  # noqa: BLE001
        logger.debug("Could not list models for the Live tab", exc_info=True)
    return out


def _selected_live_value(app: Any) -> str:
    return dict(_live_model_choices(app)).get(app.live_model_var.get(), "auto")


def _is_catalog_slug(value: str) -> bool:
    from core.live_model import LIVE_AUTO, LIVE_MAIN

    return value not in (LIVE_AUTO, LIVE_MAIN)


def _slug_downloaded(app: Any, slug: str) -> bool:
    try:
        from core.model_manager import model_downloaded

        return model_downloaded(app.app_config, slug)
    except Exception:  # noqa: BLE001
        return False


def _rebuild_model_menu(app: Any) -> None:
    """Refill the Model menu: downloaded models bold, missing ones greyed.

    A native Tk menu (not a Combobox) because only a menu can style each
    entry on its own -- that per-entry styling is how "already on this
    computer" shows at a glance.
    """
    import tkinter.font as tkfont

    menu = app.live_model_menu
    menu.delete(0, "end")
    bold = tkfont.nametofont("TkMenuFont").copy()
    bold.configure(weight="bold")
    app._live_model_bold_font = bold  # keep a reference; Tk fonts are GC'd
    for label, value in _live_model_choices(app):
        kwargs: dict[str, Any] = {}
        shown = label
        if _is_catalog_slug(value):
            if _slug_downloaded(app, value):
                kwargs["font"] = bold
            else:
                kwargs["foreground"] = _MISSING_FG
                shown = f"{label}   (not downloaded)"
        menu.add_radiobutton(
            label=shown, value=label, variable=app.live_model_var,
            command=lambda: _on_live_model_selected(app), **kwargs,
        )
        if value == "main":
            menu.add_separator()


def _refresh_model_status(app: Any) -> None:
    """Grey the picker + show "Download" only for a model not on disk."""
    value = _selected_live_value(app)
    missing = _is_catalog_slug(value) and not _slug_downloaded(app, value)
    try:
        app.live_model_btn.configure(
            text=app.live_model_var.get(),
            style=(_MODEL_MISSING_STYLE if missing else _MODEL_READY_STYLE),
        )
        if missing or getattr(app, "_live_model_downloading", False):
            app.live_model_dl_btn.grid()
        else:
            app.live_model_dl_btn.grid_remove()
            app.live_model_dl_var.set("")
    except Exception:  # noqa: BLE001
        logger.debug("Could not refresh the live model status", exc_info=True)


def _download_live_model(app: Any) -> None:
    """Download the selected catalog model from the tab (worker thread)."""
    value = _selected_live_value(app)
    if not _is_catalog_slug(value) or getattr(app, "_live_model_downloading", False):
        return
    from core import live_model as _lm

    model_cfg = _lm.live_model_config(app.app_config, value)
    if model_cfg is None:
        return
    app._live_model_downloading = True
    app.live_model_dl_btn.configure(state="disabled", text="Downloading\u2026")
    app.live_model_dl_var.set("Starting\u2026")
    app.live_start_btn.configure(state="disabled")

    def progress(payload: dict[str, Any]) -> None:
        pct = payload.get("percent")
        detail = payload.get("detail") or payload.get("status") or ""
        text = f"{pct}% \u2014 {detail}" if isinstance(pct, int) and pct else str(detail)
        app.post_to_main(lambda: app.live_model_dl_var.set(text))

    def worker() -> None:
        error: str | None = None
        try:
            from core.model_manager import ensure_model

            ensure_model(model_cfg, progress_cb=progress)
        except Exception as e:  # noqa: BLE001
            logger.exception("Live model download failed")
            error = str(e)
        app.post_to_main(lambda: _download_finished(app, value, error))

    import threading

    threading.Thread(target=worker, name="live-model-download", daemon=True).start()


def _download_finished(app: Any, slug: str, error: str | None) -> None:
    app._live_model_downloading = False
    try:
        app.live_model_dl_btn.configure(state="normal", text="Download")
        if getattr(app, "live_session", None) is None:
            app.live_start_btn.configure(state="normal")
    except Exception:  # noqa: BLE001
        logger.debug("Could not reset the download button", exc_info=True)
    if error is not None:
        app.live_model_dl_var.set("Download failed.")
        show_error(app, "Could not download the model",
                   f"The '{slug}' model could not be downloaded.", detail=error)
    else:
        app.log(f"Live: downloaded the '{slug}' model.")
    _rebuild_model_menu(app)
    _refresh_model_status(app)


def _on_live_model_selected(app: Any) -> None:
    _refresh_model_status(app)
    value = _selected_live_value(app)
    if app.app_config.get("live_model") == value:
        return
    app.app_config["live_model"] = value
    from core.config import save_config

    try:
        save_config(app.app_config)
    except Exception:  # noqa: BLE001
        logger.exception("Could not save the Live tab model choice")


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
    # English by default (owner request): naming the language is faster
    # and more reliable than auto-detect on short live chunks.
    app.live_lang_var = tk.StringVar(value="English")
    app.live_status_var = tk.StringVar(value="Idle.")
    _choices = _live_model_choices(app)
    from core.live_model import LIVE_DEFAULT

    _saved = str(app.app_config.get("live_model") or LIVE_DEFAULT)
    app.live_model_var = tk.StringVar(value=next(
        (label for label, value in _choices if value == _saved),
        next((label for label, value in _choices if value == LIVE_DEFAULT), _MODEL_AUTO),
    ))
    app.live_model_dl_var = tk.StringVar(value="")
    app._live_model_downloading = False

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

    ttk.Label(src, text="Model:").grid(row=3, column=0, sticky="e", padx=8, pady=6)
    style = ttk.Style(src)
    style.configure(_MODEL_MISSING_STYLE, foreground=_MISSING_FG)
    import tkinter.font as tkfont

    try:  # sv_ttk's body font, so the bold label matches the comboboxes
        app._live_model_btn_font = tkfont.nametofont("SunValleyBodyFont").copy()
    except tk.TclError:
        app._live_model_btn_font = tkfont.nametofont("TkTextFont").copy()
    app._live_model_btn_font.configure(weight="bold")
    style.configure(_MODEL_READY_STYLE, font=app._live_model_btn_font)
    model_row = ttk.Frame(src)
    model_row.grid(row=3, column=1, sticky="ew", padx=8, pady=6)
    model_row.columnconfigure(0, weight=1)
    app.live_model_btn = ttk.Menubutton(model_row, style=_MODEL_READY_STYLE)
    app.live_model_menu = tk.Menu(app.live_model_btn, tearoff=0)
    app.live_model_btn.configure(menu=app.live_model_menu)
    app.live_model_btn.grid(row=0, column=0, sticky="ew")
    app.live_model_dl_btn = ttk.Button(
        model_row, text="Download", command=lambda: _download_live_model(app),
    )
    app.live_model_dl_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
    ttk.Label(model_row, textvariable=app.live_model_dl_var, foreground="#666").grid(
        row=1, column=0, columnspan=2, sticky="w"
    )
    _rebuild_model_menu(app)
    _refresh_model_status(app)
    help_icon(
        src,
        "Live text only keeps up if the model transcribes faster than you "
        "speak. Tiny (the default) keeps up on any computer; bigger models "
        "are more accurate but several times too slow on a computer without "
        "a supported graphics card. Models already on this computer are "
        "shown in bold; greyed ones still need a one-time download -- use "
        "the Download button next to the picker.",
    ).grid(row=3, column=2, sticky="w", padx=(0, 8), pady=6)

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
    # Siri-style sine waves ported from SiriWave (MIT; see
    # app/widgets/audio_visualizer.py). Fed by the recorder's capture
    # thread via LiveSession.on_meter; drawing stays on Tk.
    from app.widgets.audio_visualizer import AudioVisualizer

    lvl = section_labelframe(
        parent, "Input level",
        "Live audio level while listening. The wave moves with the sound "
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
        app.live_model_btn.configure(state=("disabled" if running else "normal"))
        app.live_model_dl_btn.configure(state=(
            "disabled" if running or getattr(app, "_live_model_downloading", False)
            else "normal"
        ))
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
            model_slug = _prepare_live_model(app, language)
            transcriber = LiveTranscriber(
                app.entry_file, language=language, log=app.log,
                model_slug=model_slug,
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


def _prepare_live_model(app: Any, language: str | None) -> str | None:
    """Pick the live model and download it if needed (worker thread).

    Returns the catalog slug for the live worker, or None to load the
    main model. A failed download falls back to the main model rather
    than refusing to start.
    """
    from core import live_model as _lm
    from core.hardware import detect_device_for

    try:
        device, _ct = detect_device_for(app.app_config)
    except Exception:  # noqa: BLE001
        device = "cpu"
    slug = _lm.resolve_live_slug(app.app_config, language, device)
    if not slug:
        return None
    model_cfg = _lm.live_model_config(app.app_config, slug)
    if model_cfg is None:
        app.post_to_main(lambda: app.log(
            f"Live: unknown model '{slug}'; using the Transcribe tab's model."
        ))
        return None
    if not _lm.is_downloaded(model_cfg):
        app.post_to_main(lambda: app.live_status_var.set(
            f"Downloading the live model ({slug}) — one time only…"
        ))
        try:
            from core.model_manager import ensure_model

            ensure_model(model_cfg)
        except Exception as e:  # noqa: BLE001
            logger.exception("Live model download failed")
            msg = f"Live: could not download '{slug}' ({e}); using the Transcribe tab's model."
            app.post_to_main(lambda: app.log(msg))
            return None
        app.post_to_main(lambda: app.live_status_var.set("Loading the speech model…"))
    app.post_to_main(lambda: app.log(f"Live: using the '{slug}' model."))
    return slug


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
    if getattr(app, "_live_draining", False):
        _discard_rest(app, session, transcriber)
        return
    # First press: the microphone stops now, but every chunk already
    # captured still gets transcribed -- a slow model used to lose its
    # whole backlog here to a fixed 10 s join timeout. The button turns
    # into "Discard rest" for anyone who does not want to wait.
    app._live_draining = True
    try:
        viz = getattr(app, "live_visualizer", None)
        if viz is not None:
            viz.set_active(False)
    except Exception:  # noqa: BLE001
        logger.debug("Could not deactivate visualizer", exc_info=True)
    try:
        app.live_stop_btn.configure(text="Discard rest")
    except Exception:  # noqa: BLE001
        logger.debug("Could not update live controls", exc_info=True)
    app.live_status_var.set("Microphone off — transcribing what was already said…")

    def worker() -> None:
        try:
            session.stop_capture()
            session.wait_drained()
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


def _discard_rest(app: Any, session: Any, transcriber: Any) -> None:
    """Second Stop press while draining: drop the backlog and end now."""
    try:
        app.live_stop_btn.configure(state="disabled")
    except Exception:  # noqa: BLE001
        logger.debug("Could not update live controls", exc_info=True)
    app.live_status_var.set("Discarding the rest…")

    def worker() -> None:
        try:
            dropped = session.discard_pending()
            if dropped:
                app.post_to_main(
                    lambda: app.log(f"Live: discarded {dropped} untranscribed chunk(s).")
                )
        except Exception:  # noqa: BLE001
            logger.exception("Discarding live chunks failed")
        try:
            # Interrupts the chunk being transcribed right now; the drain
            # worker started by the first press then finishes promptly.
            if transcriber is not None:
                transcriber.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Stopping the live worker failed")

    import threading

    threading.Thread(target=worker, name="live-discard", daemon=True).start()


def _stopped(app: Any) -> None:
    # Drain whatever the tail produced before dropping the session.
    _poll_once(app)
    app.live_session = None
    app.live_transcriber = None
    app._live_draining = False
    try:
        app.live_stop_btn.configure(text="Stop")
    except Exception:  # noqa: BLE001
        logger.debug("Could not update live controls", exc_info=True)
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
    if getattr(app, "_live_draining", False):
        try:
            left = int(session.pending_chunks())
        except Exception:  # noqa: BLE001
            left = 0
        if left > 0:
            app.live_status_var.set(
                f"Microphone off — transcribing {left} remaining "
                f"part{'s' if left != 1 else ''}… (Discard rest to skip)"
            )


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
