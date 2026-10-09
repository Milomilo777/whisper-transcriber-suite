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
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable

from app.dpi import scaled
from app.theme import script_fonts, tokens
from app.widgets.error_dialog import show_error
from app.widgets.tooltip import help_icon, section_labelframe

logger = logging.getLogger(__name__)

_POLL_MS = 200

_SOURCE_MIC = "Microphone"
_SOURCE_SYSTEM = "System audio (what you hear)"

# Keys that never modify text -- letting these through even while the
# transcript is "read-only" keeps navigation and selection-extend working
# (Ctrl+arrow / Ctrl+Home too: the modifier does not matter for these).
# Not Tab: the Text class binding inserts a tab character.
_NAV_KEYSYMS = frozenset((
    "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Meta_L", "Meta_R", "Super_L", "Super_R", "Escape",
))
# With a copy modifier held, only these pass: copy (C, Insert) and select
# all (A, slash). A blanket "any Ctrl combo" let Ctrl+V paste, Ctrl+X cut
# and the Text class's Ctrl+H / Ctrl+D / Ctrl+K / Ctrl+T / Ctrl+O edits in.
_COPY_KEYSYMS = frozenset(("c", "C", "a", "A", "Insert", "slash"))
_CONTROL_MASK = 0x4  # Tk Event.state bit for the Control modifier
# Command on macOS (Tk aqua reports it as Mod1). On Windows and X11 this
# bit is Num Lock / Alt, so it only counts as a copy modifier on macOS.
_COMMAND_MASK = 0x8
# Text-changing virtual events (menus, Shift+Insert, Shift+Delete, ...).
_EDIT_VIRTUAL_EVENTS = ("<<Paste>>", "<<PasteSelection>>", "<<Cut>>",
                        "<<Clear>>", "<<Undo>>", "<<Redo>>")


# Windows virtual-key codes of A, C and Insert. With a non-Latin keyboard
# layout (Persian, Russian, ...) Tk reports the layout's letter as the
# keysym, so Ctrl+C is recognised by the physical key instead.
_WIN_COPY_KEYCODES = frozenset((65, 67, 45))


def _blocks_edit(keysym: str, state: "int | str",
                 platform: str | None = None, keycode: int = 0) -> bool:
    """True if a keypress with this keysym/modifier-state should be
    swallowed to stop it from typing into a "read-only but selectable"
    Text widget. Navigation keys, copy and select-all pass through
    (Ctrl, or Command on macOS); everything else is blocked.
    """
    if keysym in _NAV_KEYSYMS:
        return False
    if isinstance(state, int):
        plat = platform or sys.platform
        mask = _CONTROL_MASK
        if plat == "darwin":
            mask |= _COMMAND_MASK
        if state & mask:
            if keysym in _COPY_KEYSYMS:
                return False
            if plat == "win32" and keycode in _WIN_COPY_KEYCODES:
                return False
    return True


def _make_readonly_but_selectable(text: tk.Text) -> None:
    """Keep *text* mouse-selectable and copyable without letting the user
    type into it -- a plain ``state="disabled"`` Text widget blocks mouse
    drag-selection entirely, not just editing, which was a real reported
    complaint (a transcript a user cannot select-and-copy by dragging).
    Programmatic ``insert``/``delete`` (this module's own ``_append``/
    ``_clear``) are unaffected; only user keystrokes are filtered.
    """
    def _filter_key(event: "tk.Event[tk.Text]") -> str | None:
        keycode = event.keycode if isinstance(event.keycode, int) else 0
        return "break" if _blocks_edit(event.keysym, event.state,
                                       keycode=keycode) else None

    text.bind("<Key>", _filter_key)
    for virtual in _EDIT_VIRTUAL_EVENTS:
        text.bind(virtual, lambda _e: "break")


_MODEL_AUTO = "Automatic (fast enough for this computer)"
_MODEL_MAIN = "Same as the Transcribe tab"

_MISSING_FG = tokens.TEXT_MISSING
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
    from core.model_manager import is_english_only

    for label, value in _live_model_choices(app):
        kwargs: dict[str, Any] = {}
        shown = label
        if _is_catalog_slug(value):
            if is_english_only(app.app_config, value) and "English-only" not in label:
                shown = f"{label}   (English-only)"
            if _slug_downloaded(app, value):
                kwargs["font"] = bold
            else:
                kwargs["foreground"] = tokens.themed(_MISSING_FG)
                shown = f"{shown}   (not downloaded)"
        menu.add_radiobutton(
            label=shown, value=label, variable=app.live_model_var,
            command=lambda: _on_live_model_selected(app), **kwargs,
        )
        if value == "main":
            menu.add_separator()


def _configure_model_styles(app: Any, widget: tk.Misc) -> None:
    """The model picker's two styles. ttk styles belong to a theme, so this runs again after
    every theme switch (``apply_theme``)."""
    import tkinter.font as tkfont

    style = ttk.Style(widget)
    style.configure(_MODEL_MISSING_STYLE, foreground=tokens.themed(_MISSING_FG))
    try:  # sv_ttk's body font, so the bold label matches the comboboxes
        app._live_model_btn_font = tkfont.nametofont("SunValleyBodyFont").copy()
    except tk.TclError:
        app._live_model_btn_font = tkfont.nametofont("TkTextFont").copy()
    app._live_model_btn_font.configure(weight="bold")
    style.configure(_MODEL_READY_STYLE, font=app._live_model_btn_font)


def apply_theme(app: Any) -> None:
    """After a theme switch: the picker's styles for the new theme and its menu entries in the
    new theme's colours (menu entries are not widgets, the theme walker does not reach them)."""
    _configure_model_styles(app, app.live_model_btn)
    _rebuild_model_menu(app)


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


def _on_keep_toggled(app: Any) -> None:
    value = bool(app.live_keep_var.get())
    if bool(app.app_config.get("live_keep_recording", False)) == value:
        return
    app.app_config["live_keep_recording"] = value
    from core.config import save_config

    try:
        save_config(app.app_config)
    except Exception:  # noqa: BLE001
        logger.exception("Could not save the Live tab keep-audio choice")


def _keep_recording(app: Any) -> bool:
    try:
        return bool(app.live_keep_var.get())
    except Exception:  # noqa: BLE001
        return bool(app.app_config.get("live_keep_recording", False))


def _live_log(app: Any) -> Callable[[str], None]:
    """A log callable that is safe from any thread.

    The live worker's reader thread logs (language lock, worker output),
    and ``app.log`` writes a Tk Text widget, which only the Tk thread may
    touch.
    """
    threadsafe = getattr(app, "log_threadsafe", None)

    def post(msg: str) -> None:
        if callable(threadsafe):
            threadsafe(msg)
        else:
            app.post_to_main(lambda: app.log(msg))

    return post


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
    _confirm_model_language(app, on_start=False)


# ------------------------------------------- English-only model guard


def _live_device(app: Any) -> str:
    try:
        from core.hardware import detect_device_for

        device, _ct = detect_device_for(app.app_config)
        return str(device or "cpu")
    except Exception:  # noqa: BLE001
        return "cpu"


def _english_only_pair(
    app: Any, language: str | None
) -> tuple[str, str, str, str] | None:
    """``(model, alternative live_model value, alternative slug, device)`` when the
    Live tab would run an English-only model on speech that may not be
    English; None when the pair is fine or the user already kept it.

    The device is only probed when it matters (Automatic, or a
    recommendation to make), so a fine pair costs no CUDA probe.
    """
    from core import live_model as _lm
    from core.model_manager import english_only_mismatch, is_english_only

    if (language or "").strip().lower() == "en":
        return None
    config = app.app_config
    choice = str(config.get("live_model") or _lm.LIVE_DEFAULT).strip()
    if choice == _lm.LIVE_AUTO:
        # Automatic picks a multilingual model for other languages on a
        # CPU; only on a GPU does it run the main model, maybe English-only.
        main = _lm.effective_live_slug(config, language, "cuda")
        if is_english_only(config, main) is not True:
            return None
    device = _live_device(app) if choice == _lm.LIVE_AUTO else ""
    slug = _lm.effective_live_slug(config, language, device or "cpu")
    if not english_only_mismatch(config, slug, language):
        return None
    if (slug, language or "") in getattr(app, "_live_en_only_kept", set()):
        return None
    device = device or _live_device(app)
    alt_value, alt_slug = _lm.live_alternative(config, language, device, slug)
    return slug, alt_value, alt_slug, device


def _english_only_prompt(
    app: Any, slug: str, alt_value: str, alt_slug: str, device: str
) -> Any:
    from app.dialogs.english_only_model import EnglishOnlyPrompt
    from core.live_model import LIVE_MAIN
    from core.model_manager import approx_download_size_text

    name = (app.live_lang_var.get() or "").strip()
    language = "" if name.lower() == "auto" else name
    understands = language or "other languages"
    if alt_value == LIVE_MAIN:
        reason = (f"It is the Transcribe tab's model: it understands {understands}, "
                  "and your graphics card runs it fast enough for live text.")
    elif device == "cpu":
        reason = (f"It understands {understands} and still keeps up with live "
                  "speech on this computer.")
    else:
        reason = f"About the same size and speed, and it understands {understands}."
    return EnglishOnlyPrompt(
        model=slug, language=language, alternative=alt_slug, reason=reason,
        size_text=approx_download_size_text(app.app_config, alt_slug),
        downloaded=_slug_downloaded(app, alt_slug),
    )


def _switch_live_model(app: Any, value: str) -> bool:
    label = next((lbl for lbl, v in _live_model_choices(app) if v == value), None)
    if label is None:
        return False
    app.live_model_var.set(label)
    _on_live_model_selected(app)
    return True


def _open_model_menu(app: Any) -> None:
    btn = app.live_model_btn
    try:
        app.live_model_menu.post(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
    except tk.TclError:
        logger.debug("Could not open the Live model menu", exc_info=True)


def _confirm_model_language(app: Any, *, on_start: bool) -> bool:
    """Guide the user away from an English-only model + another language.

    Returns True when listening may go ahead (``on_start``), False when
    the user cancelled or went to pick another model. Never switches
    without asking: the dialog offers the switch, a free choice, or
    keeping the model (remembered for this session).
    """
    if getattr(app, "_live_en_only_asking", False):
        return False
    language = _selected_language_code(app)
    pair = _english_only_pair(app, language)
    if pair is None:
        return True
    slug, alt_value, alt_slug, device = pair
    from app.dialogs import english_only_model as dlg

    prompt = _english_only_prompt(app, slug, alt_value, alt_slug, device)
    app._live_en_only_asking = True
    try:
        choice = dlg.ask_english_only(app, prompt)
    finally:
        app._live_en_only_asking = False
    if choice == dlg.CHOICE_SWITCH:
        if not _switch_live_model(app, alt_value):
            return False
        app.log(f"Live: switched from '{slug}' (English only) to '{alt_slug}'.")
        if not on_start and not _slug_downloaded(app, alt_slug) and alt_value == alt_slug:
            _download_live_model(app)
        return True
    if choice == dlg.CHOICE_KEEP:
        if not hasattr(app, "_live_en_only_kept"):
            app._live_en_only_kept = set()
        app._live_en_only_kept.add((slug, language or ""))
        return True
    if choice == dlg.CHOICE_CHOOSE:
        app.after(50, lambda: _open_model_menu(app))
    return False


def build_live_tab(app: Any, parent: Any) -> None:
    """Construct the Live tab onto ``parent`` and wire it to ``app``."""
    from core import live as _live

    app.live_session = None
    app.live_transcriber = None
    app.live_lines = []
    #: len(live_lines) at the last save; more lines = unsaved text.
    app._live_saved_count = 0
    app._live_poll_scheduled = False
    app._live_cancel_pending = False
    app._live_stop_reason = ""
    app._live_signal_hint = False

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
    app.live_lang_combo.bind(
        "<<ComboboxSelected>>",
        lambda _e: _confirm_model_language(app, on_start=False),
    )
    help_icon(
        src,
        "Naming the language is more reliable than auto-detect for live "
        "audio: each chunk is short, and detection on a few seconds of "
        "speech can guess wrong and switch mid-session.",
    ).grid(row=2, column=2, sticky="w", padx=(0, 8), pady=6)

    ttk.Label(src, text="Model:").grid(row=3, column=0, sticky="e", padx=8, pady=6)
    _configure_model_styles(app, src)
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
    ttk.Label(model_row, textvariable=app.live_model_dl_var, foreground=tokens.themed(tokens.TEXT_MUTED)).grid(
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
    app.live_keep_var = tk.BooleanVar(
        value=bool(app.app_config.get("live_keep_recording", False))
    )
    app.live_keep_check = ttk.Checkbutton(
        ctl, text="Keep the audio", variable=app.live_keep_var,
        command=lambda: _on_keep_toggled(app),
    )
    app.live_keep_check.pack(side="left", padx=(16, 0))
    help_icon(
        ctl,
        "Off: the session's audio recording is deleted when you stop "
        "(it takes 100-350 MB per hour). On: it is kept, and the log says "
        "where the file is.",
    ).pack(side="left", padx=(4, 0))
    ttk.Label(ctl, textvariable=app.live_status_var, foreground=tokens.themed(tokens.TEXT_MUTED)).pack(
        side="left", padx=(16, 0)
    )

    # ── Level meter ───────────────────────────────────────────────────
    # iOS 9 Siri waves ported from SiriWave (MIT) plus a peak meter (see
    # app/widgets/audio_visualizer.py). Fed by the recorder's capture
    # thread via LiveSession.on_meter; drawing stays on Tk.
    from app.widgets.audio_visualizer import AudioVisualizer

    lvl = section_labelframe(
        parent, "Input level",
        "Live audio level while listening. The waves move with the sound "
        "coming in; the bar underneath is a peak meter (green = normal "
        "speech, yellow = loud, red = close to clipping) with the level in "
        "dB at the top right. When nothing moves, nothing is being "
        "captured.",
    )
    lvl.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 6))
    lvl.columnconfigure(0, weight=1)
    app.live_visualizer = AudioVisualizer(lvl, height=scaled(lvl, 130))
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
    script_fonts.use_text_font(app.live_text)
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
        foreground=tokens.themed(tokens.TEXT_MUTED),
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
    if not _confirm_model_language(app, on_start=True):
        return

    app.live_status_var.set("Loading the speech model…")
    app._live_cancel_pending = False
    app._live_stop_reason = ""
    app._live_signal_hint = False
    _set_running(app, True)
    worker_log = _live_log(app)

    language = _selected_language_code(app)
    device_index = _selected_device_index(app) if mode == "mic" else None
    work_dir = _live.session_work_dir()
    keep = _keep_recording(app)
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
        session = None
        try:
            model_slug = _prepare_live_model(app, language)
            transcriber = LiveTranscriber(
                app.entry_file, language=language, log=worker_log,
                model_slug=model_slug,
            )
            transcriber.start()
            session = _live.LiveSession(
                transcribe_chunk=transcriber.transcribe_chunk,
                work_dir=work_dir,
                mode=mode,
                device_index=device_index,
                language=language,
                keep_recording=keep,
                on_meter=_meter,
            )
            session.start()
        except Exception as e:  # noqa: BLE001
            logger.exception("Live session failed to start: %s", e)
            if session is not None:
                _finish_recording(session, False)  # the empty session folder
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


def _check_main_fallback(app: Any, language: str | None, why: str) -> None:
    """Refuse to fall back to an English-only main model for other speech.

    The fallback keeps listening possible when the live model is missing,
    but onto an English-only model it would bring back the silent wrong
    English text the English-only dialog exists to prevent.
    """
    from core.model_manager import DEFAULT_MODEL_SLUG, english_only_mismatch

    main = str(app.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG).strip()
    if english_only_mismatch(app.app_config, main, language):
        raise RuntimeError(
            f"{why} The Transcribe tab's model ({main}) understands English only, "
            "so it cannot stand in for it. Check the internet connection and press "
            "Start again, or pick another model in the Model list."
        )


def _prepare_live_model(app: Any, language: str | None) -> str | None:
    """Pick the live model and download it if needed (worker thread).

    Returns the catalog slug for the live worker, or None to load the
    main model. A failed download falls back to the main model rather
    than refusing to start, unless the main model understands English
    only and the language is not English (then this raises).
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
        _check_main_fallback(app, language, f"The live model '{slug}' is not in the model list.")
        app.post_to_main(lambda: app.log(
            f"Live: unknown model '{slug}'; using the Transcribe tab's model."
        ))
        return None
    if not _lm.is_downloaded(model_cfg):
        app.post_to_main(lambda: app.live_status_var.set(
            f"Downloading the live model ({slug}) — one time only…"
        ))
        def progress(payload: dict[str, Any]) -> None:
            pct = payload.get("percent")
            if isinstance(pct, int) and pct:
                text = f"Downloading the live model ({slug}) — {pct}%, one time only…"
                app.post_to_main(lambda: app.live_status_var.set(text))

        try:
            from core.model_manager import ensure_model

            ensure_model(model_cfg, progress_cb=progress)
        except Exception as e:  # noqa: BLE001
            logger.exception("Live model download failed")
            _check_main_fallback(app, language, f"Could not download the '{slug}' model ({e}).")
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
        keep = _keep_recording(app)

        def worker() -> None:
            try:
                session.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Stopping the just-started live session failed")
            try:
                transcriber.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Stopping the live worker failed")
            kept = _finish_recording(session, keep)
            app.post_to_main(lambda: _stopped(app, kept))

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
    keep = _keep_recording(app)

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
        kept = _finish_recording(session, keep)
        app.post_to_main(lambda: _stopped(app, kept))

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


def _finish_recording(session: Any, keep: bool) -> str:
    """Delete the session's audio unless kept; returns the kept path."""
    try:
        session.keep_recording = keep
        return str(session.finish_recording() or "")
    except Exception:  # noqa: BLE001
        logger.exception("Cleaning up the live recording failed")
        return ""


def _stopped(app: Any, kept: str = "") -> None:
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
    reason = getattr(app, "_live_stop_reason", "")
    app.live_status_var.set(f"Stopped: {reason}" if reason else "Stopped.")
    app.log("Live transcription stopped.")
    if kept:
        app.log(f"Live: the session audio was kept at {kept}")
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
        # Text the tail produced during that wait belongs in the transcript.
        _poll_once(app)
    if transcriber is not None:
        try:
            transcriber.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Live worker teardown failed")
    # Save the words first: the recording is deleted unless kept, and it is the
    # only other copy of them. When the words cannot be saved (disk full, no
    # permission) the recording is kept instead of being deleted too.
    keep = _keep_recording(app)
    forced = False
    if not getattr(app, "_live_exit_discard", False):
        unsaved = has_unsaved_transcript(app)
        saved = autosave_unsaved_transcript(app)
        forced = bool(unsaved and not saved and not keep)
        keep = keep or forced
    if session is not None:
        kept = _finish_recording(session, keep)
        if forced and kept:
            try:
                app.log(f"The transcript could not be saved; the session audio was kept at {kept}")
            except Exception:  # noqa: BLE001 - the window may already be going away
                logger.debug("Could not log the kept recording", exc_info=True)
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
    try:
        _poll_once(app)
        _check_health(app)
    except Exception:  # noqa: BLE001
        logger.exception("Live poll failed")
    finally:
        # Always re-arm: one bad event must not stop the transcript from
        # updating for the rest of the session.
        if app.live_session is not None and not getattr(app, "_closing", False):
            _schedule_poll(app)


_NO_AUDIO_HINT = ("Listening… no sound arrives from this device. "
                  "Check that it is connected and selected.")
_SILENT_HINT = ("Listening… the device sends only silence. Check that it is "
                "not muted and that this app may use the microphone.")


def _check_health(app: Any) -> None:
    """Notice a dead microphone or worker while the tab says Listening."""
    session = app.live_session
    if session is None or getattr(app, "_live_draining", False):
        return
    reason = ""
    try:
        reason = str(session.capture_error() or "")
    except Exception:  # noqa: BLE001
        logger.debug("Could not read the capture state", exc_info=True)
    transcriber = getattr(app, "live_transcriber", None)
    if not reason and transcriber is not None:
        try:
            if not transcriber.is_running():
                reason = "The speech model process stopped unexpectedly."
        except Exception:  # noqa: BLE001
            logger.debug("Could not read the worker state", exc_info=True)
    if reason:
        _fail_live(app, reason)
        return
    try:
        state = str(session.input_signal_state())
    except Exception:  # noqa: BLE001
        state = "ok"
    if state in ("no_audio", "silent"):
        app._live_signal_hint = True
        app.live_status_var.set(_NO_AUDIO_HINT if state == "no_audio" else _SILENT_HINT)
    elif getattr(app, "_live_signal_hint", False):
        app._live_signal_hint = False
        app.live_status_var.set("Listening…")


def _fail_live(app: Any, reason: str) -> None:
    """Stop a session that can no longer work and say why, once.

    Goes through the normal Stop path, so chunks already captured are
    still transcribed and nothing in the transcript is lost.
    """
    if (getattr(app, "_live_stop_reason", "") or app.live_session is None
            or getattr(app, "_closing", False)):
        return  # already handled, or the app is exiting (teardown stops it)
    app._live_stop_reason = reason
    app.log(f"Live error: {reason}")
    if getattr(app, "_live_draining", False):
        return  # already stopping; _stopped shows the reason
    _stop(app)
    app.live_status_var.set(f"Stopped listening: {reason}")
    # After the poll returns: a modal dialog inside the poll would hold
    # the transcript updates until it is closed.
    app.after(0, lambda: show_error(
        app, "Live transcription stopped",
        "Listening stopped because of a problem with the audio source or "
        "the speech model. The text so far is kept.",
        detail=reason,
    ))


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
        elif ev.kind == "fatal":
            _fail_live(app, f"Transcription keeps failing: {ev.detail}")
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
        start = widget.index("end-1c")
        # Widget stays state="normal" (see _make_readonly_but_selectable);
        # only the <Key> filter keeps the user from typing into it, so
        # this insert needs no enable/disable dance around it.
        widget.insert("end", text + "\n")
        script_fonts.tag_script_lines(widget, start, "end",
                                      language=_selected_language_code(app))
        # Only follow the tail when the user has not scrolled up to read
        # something earlier — yanking the view is worse than lagging it.
        if at_bottom:
            widget.see("end")
    except Exception:  # noqa: BLE001
        logger.debug("Could not append live text", exc_info=True)


# --------------------------------------------------------------- actions


def _transcript_text(app: Any) -> str:
    return "\n".join(getattr(app, "live_lines", []) or []).strip()


def has_unsaved_transcript(app: Any) -> bool:
    """True when the Live tab holds text added since the last save."""
    lines = getattr(app, "live_lines", None) or []
    return bool(_transcript_text(app)) and len(lines) > int(
        getattr(app, "_live_saved_count", 0) or 0
    )


def _save(app: Any) -> bool:
    """Ask for a file and save the transcript. True once it is on disk."""
    body = _transcript_text(app)
    # Counted with the body, before the dialog: a running session can add
    # lines while it is open, and those must stay "unsaved".
    count = len(getattr(app, "live_lines", []) or [])
    if not body:
        show_error(app, "Nothing to save",
                   "The live transcript is empty.")
        return False
    path = filedialog.asksaveasfilename(
        parent=app, title="Save live transcript",
        defaultextension=".txt",
        filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
        initialfile="live-transcript.txt",
    )
    if not path:
        return False
    try:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(body + "\n")
    except OSError as e:
        show_error(app, "Could not save the transcript",
                   f"Writing {os.path.basename(path)} failed.", detail=str(e))
        return False
    app._live_saved_count = count
    app.log(f"Live transcript saved to {path}")
    return True


def save_before_exit(app: Any) -> bool:
    """Exit hook: offer to save unsaved live text. False = cancel the exit.

    The transcript lives only in the widget, and closing the window or
    the tray's Exit used to drop it without a word.
    """
    app._live_exit_discard = False
    if not has_unsaved_transcript(app):
        return True
    from tkinter import messagebox

    answer = messagebox.askyesnocancel(
        "Unsaved live transcript",
        "The Live tab has a transcript that was not saved.\n\n"
        "Save it before exiting?",
        parent=app,
    )
    if answer is None:
        return False
    if answer is False:
        app._live_exit_discard = True
        return True
    return _save(app)


def autosave_unsaved_transcript(app: Any) -> str:
    """Write unsaved live text to a file without asking; returns its path.

    The last line of defence at exit: lines that arrived after the exit
    question (the tail of a running session) or an exit path that never
    asked. Goes to the download folder when one is set, else to the
    app's data folder, and the path is logged.
    """
    if not has_unsaved_transcript(app):
        return ""
    body = _transcript_text(app)
    folder = str(app.app_config.get("download_folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        from core.config import user_data_dir

        folder = str(user_data_dir() / "live-transcripts")
    stem = f"live-transcript-{time.strftime('%Y%m%d-%H%M%S')}"
    path = ""
    try:
        os.makedirs(folder, exist_ok=True)
        for n in range(1, 100):
            candidate = os.path.join(folder, stem + (f"-{n}" if n > 1 else "") + ".txt")
            try:
                # "x": never overwrite a file that already has this name.
                with open(candidate, "x", encoding="utf-8") as fp:
                    fp.write(body + "\n")
            except FileExistsError:
                continue
            path = candidate
            break
    except OSError:
        logger.exception("Autosaving the live transcript failed")
        return ""
    if not path:
        logger.error("Autosaving the live transcript failed: no free file name")
        return ""
    app._live_saved_count = len(getattr(app, "live_lines", []) or [])
    logger.info("Live transcript autosaved to %s", path)
    try:
        app.log(f"Live transcript autosaved to {path}")
    except Exception:  # noqa: BLE001
        logger.debug("Could not log the autosave", exc_info=True)
    return path


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
    app._live_saved_count = 0
    try:
        app.live_text.delete("1.0", "end")
    except Exception:  # noqa: BLE001
        logger.debug("Could not clear the live transcript", exc_info=True)
