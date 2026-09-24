"""Tab construction extracted from App.

Each ``build_*_tab`` function attaches widgets onto the App and returns
nothing. The App class stays slim while the widget code lives next to its
sibling components.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from app.domain.languages import SUBTITLE_LANGUAGES
from app.widgets.tooltip import bind_tooltip, help_icon, section_labelframe

if TYPE_CHECKING:
    from app.app import App
    from app.domain.tasks import TranscriptionTask, VideoDownloadTask


# --- shared UX helpers -----------------------------------------------------


class _AutoScrollbar(ttk.Scrollbar):
    """A scrollbar that hides itself when the whole view already fits.

    Gives the queue lists a vertical scrollbar that appears only when the
    list grows past the visible area. Must be managed by grid — it
    grid_remove()s itself when not needed and grid()s back when it is.
    """

    def set(self, first: float | str, last: float | str) -> None:
        try:
            if float(first) <= 0.0 and float(last) >= 1.0:
                self.grid_remove()
            else:
                self.grid()
        except (ValueError, tk.TclError):
            pass
        super().set(first, last)


# Glanceable status icons for both Treeviews. Plain Unicode so they
# render without an embedded image set, and so they survive the
# packaging mode that ships no icon assets.
STATUS_ICON = {
    "waiting":      "⋯ ",
    "running":      "▶ ",
    "paused":       "⏸ ",
    "transcribing": "✍ ",
    "finished":     "✓ ",
    "error":        "✗ ",
    "cancelled":    "⊘ ",
}


def _fmt_bytes(n: int) -> str:
    """Compact filesize formatter for the Last Result card."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def status_label(status: str) -> str:
    """Friendly status text for the Treeview's status column."""
    return STATUS_ICON.get(status, "") + status


_PROGRESS_SEGMENTS = 10


def progress_cell(percent: float | int) -> str:
    """Render progress as a text bar + number for a Treeview cell.

    A Treeview cell can't host a real ttk.Progressbar, so we draw a
    fixed-width block bar (█ filled / ░ empty) and append the exact
    percentage — a glanceable graphical trend *and* the number in one
    column.
    """
    try:
        pct = int(round(float(percent)))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(round(inf)) on a non-finite percent.
        pct = 0
    pct = max(0, min(100, pct))
    filled = (pct * _PROGRESS_SEGMENTS + 50) // 100
    bar = "█" * filled + "░" * (_PROGRESS_SEGMENTS - filled)
    return f"{bar} {pct:>3d}%"


def marquee_cell(frame: int, percent: float | int = 0) -> str:
    """An indeterminate "working" bar that STILL shows the percentage.

    A 3-cell shaded window slides across the track so the user sees that
    something is happening (e.g. while the model loads, before the first
    segment), while the real number is still appended — so the percentage
    is never hidden, just animated until determinate progress takes over.
    """
    track = ["░"] * _PROGRESS_SEGMENTS
    head = frame % _PROGRESS_SEGMENTS
    for i in range(3):
        track[(head + i) % _PROGRESS_SEGMENTS] = "▓"
    try:
        pct = max(0, min(100, int(round(float(percent)))))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(round(inf)) on a non-finite percent.
        pct = 0
    return "".join(track) + f" {pct:>3d}%"


# Transcription action keys surfaced by the per-row action bar AND the
# right-click context menu. Keep this list in sync with the buttons built
# in build_queue_tab so a status with no valid action disables them all.
QUEUE_ACTION_KEYS = ("pause", "resume", "cancel", "rerun", "remove")


def button_states_for_status(
    status: str, has_checkpoint: bool = False
) -> dict[str, bool]:
    """Which transcription actions are valid for a task in ``status``.

    The single source of truth shared by the Queue action bar and the
    right-click ``menu_row`` so the two can never drift. Returns a dict
    mapping each key in :data:`QUEUE_ACTION_KEYS` to whether that action
    should be ENABLED for a task in this state. Pure (no Tk), so it is
    unit-testable without a Tk root.

    Mirrors ``App.menu_row``:
      * waiting  -> Cancel
      * running  -> Pause, Cancel
      * paused   -> Resume, Cancel
      * terminal (finished / cancelled / error) -> Re-run, Remove
        (cancelled also offers Resume when a resumable checkpoint exists)

    ``has_checkpoint`` only matters for the ``cancelled`` state — it maps
    to the "Resume" entry ``menu_row`` adds above "Re-run".
    """
    states = {k: False for k in QUEUE_ACTION_KEYS}
    if status == "waiting":
        states["cancel"] = True
    elif status == "running":
        states["pause"] = True
        states["cancel"] = True
    elif status == "paused":
        states["resume"] = True
        states["cancel"] = True
    elif status in ("finished", "cancelled", "error"):
        states["rerun"] = True
        states["remove"] = True
        if status == "cancelled" and has_checkpoint:
            states["resume"] = True
    return states


# Download action keys for the per-row Download action bar.
DOWNLOAD_ACTION_KEYS = ("pause", "resume", "cancel", "rerun", "remove", "open")


def download_button_states_for_status(
    status: str, *, is_smtv: bool = False, has_saved_file: bool = False
) -> dict[str, bool]:
    """Which download actions are valid for a task in ``status``.

    Single source of truth for the Download action bar (Phase 2). Pure (no
    Tk) so it is unit-testable without a Tk root. Mirrors download_menu_row:
      * waiting / running / transcribing -> Cancel  (and Pause for a running
        non-SMTV download — yt-dlp can stop-and-continue; SMTV cannot)
      * running paused                   -> Resume, Cancel
      * terminal (finished/cancelled/error) -> Re-run, Remove (and Open when
        a saved file exists on disk)

    ``is_smtv`` disables Pause (SMTV CDN has no HTTP Range resume point).
    ``has_saved_file`` gates Open to a finished download with a real file.
    """
    states = {k: False for k in DOWNLOAD_ACTION_KEYS}
    if status in ("waiting", "running", "transcribing"):
        states["cancel"] = True
        if status == "running" and not is_smtv:
            states["pause"] = True
    elif status == "paused":
        states["resume"] = True
        states["cancel"] = True
    elif status in ("finished", "cancelled", "error"):
        states["rerun"] = True
        states["remove"] = True
        if status == "finished" and has_saved_file:
            states["open"] = True
    return states


def build_transcribe_tab(app: "App", parent: ttk.Frame) -> None:
    """Beginner-friendly Transcribe tab.

    Layout philosophy comes from researching MacWhisper / Aiko / Vibe /
    OpenWhispr / Buzz / WhisperUI in May 2026 (see
    ``docs/V08_FEATURE_RESEARCH.md`` for the citations). The pattern
    every well-loved offline app converges on is:

      1. A *hero drop-zone* takes the visual centre of the tab — it's
         both the empty state and the primary affordance.
      2. *Three* visible controls beneath: language picker, two
         feature toggles (identify speakers + per-word timestamps).
      3. *One* prominent primary CTA — sv_ttk's ``Accent.TButton``
         style + ``ipady`` so it's ~2× the visual weight of Browse.
      4. *Everything else hidden* behind an "Advanced settings…"
         button: VAD knobs, device / compute backend, hotwords,
         output formats, watched folder, telemetry, etc. None of
         these strings (``VAD``, ``compute``, ``device``, ``hotwords``)
         appear on the main canvas — the research's #1 anti-pattern.

    Note for maintainers: every ``*_var`` that lived in the old layout
    is still created here so the config save path + the hermetic test
    suite don't need to know the UI was rebuilt. Vars without a
    matching widget are simply not packed.
    """
    from app.domain.languages import SUBTITLE_LANGUAGES as _LANGS

    # ── all vars created up-front (some have no UI surface; they're
    #     still referenced by config save + test suite + Advanced
    #     dialog, so we initialise them either way) ───────────────────
    app.fv = tk.StringVar()
    app.vad_enabled_var = tk.BooleanVar(
        value=bool(app.app_config.get("vad_enabled", True))
    )
    app.word_timestamps_var = tk.BooleanVar(
        value=bool(app.app_config.get("word_timestamps", False))
    )
    try:
        from core import diarization as _diar  # type: ignore[import-not-found]
        _diar_available = _diar.is_available()
        _diar_reason = _diar.availability_reason() if not _diar_available else ""
    except Exception:  # noqa: BLE001
        _diar_available = False
        _diar_reason = "sherpa-onnx not present"
    app.diarization_var = tk.BooleanVar(
        value=bool(_diar_available) and bool(app.app_config.get("diarization_enabled", False))
    )
    # Always start at "Auto" — the language is deliberately NOT restored
    # from config (user request: every launch defaults to auto-detect).
    app.transcribe_lang_var = tk.StringVar(value="Auto")
    app.device_var = tk.StringVar(value=str(app.app_config.get("device", "auto")))
    app.compute_type_var = tk.StringVar(
        value=str(app.app_config.get("compute_type", "int8"))
    )
    app.hotwords_var = tk.StringVar(value=str(app.app_config.get("hotwords", "")))

    # ── Row 0: hero drop zone ─────────────────────────────────────────
    drop_zone = ttk.LabelFrame(parent, text="", padding=24)
    drop_zone.grid(
        row=0, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(15, 6),
    )
    ttk.Label(
        drop_zone,
        text="🎵    Drop an audio or video file here",
        font=("TkDefaultFont", 14, "bold"),
        anchor="center",
        justify="center",
    ).pack(fill="x")
    ttk.Label(
        drop_zone,
        text="or use the Browse button below",
        foreground="#888",
        anchor="center",
        justify="center",
    ).pack(fill="x", pady=(2, 12))
    browse_row = ttk.Frame(drop_zone)
    browse_row.pack()
    ttk.Button(browse_row, text="Browse files...", command=app.browse).pack(side="left")
    help_icon(
        browse_row,
        "Pick an audio or video file to transcribe locally (mp3, wav, mp4, "
        "mkv, and most other common formats). The file is processed on "
        "this machine and never leaves it unless you pick a cloud Engine "
        "below.",
    ).pack(side="left", padx=(6, 0))

    # ── Row 1: file path display (always visible — shows what's selected) ─
    file_row = ttk.Frame(parent)
    file_row.grid(
        row=1, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(2, 8),
    )
    ttk.Label(file_row, text="Selected file:").pack(side="left")
    ttk.Entry(file_row, textvariable=app.fv).pack(
        side="left", fill="x", expand=True, padx=(8, 0)
    )

    # ── Row 2: engine + model pickers — let the user choose the
    #     transcription engine AND (for Faster-Whisper) which model size
    #     right here, without digging through the crowded Advanced dialog.
    #     Two stacked lines in one gridded frame (same split-line trick as
    #     quick_opts below) so neither line's help icons overflow the app's
    #     default 960px width. Short status lines show whether the chosen
    #     engine is ready / model already downloaded, and an engine that
    #     can't run until the user sets it up (missing key, missing package)
    #     is marked "⚠ unavailable" in the dropdown itself — ttk.Combobox
    #     can't grey one entry, so the marker + the status line + the hover
    #     help below carry the reason instead. ────────────────────────────
    from core.backends import availability as _eng
    from core.model_manager import DEFAULT_MODEL_SLUG, catalog_models

    engine_frame = ttk.Frame(parent)
    engine_frame.grid(
        row=2, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 8),
    )
    engine_row = ttk.Frame(engine_frame)
    engine_row.pack(fill="x")
    model_row = ttk.Frame(engine_frame)
    model_row.pack(fill="x", pady=(6, 0))

    ttk.Label(engine_row, text="Engine:").pack(side="left")
    # Cheap readiness only (no heavy backend imports on the UI thread); a
    # deep probe of the current pick refines this shortly after startup.
    _engine_options = _eng.engine_options(app.app_config, deep=False)
    _current_engine_value = _eng.normalise_engine(
        app.app_config.get("transcribe_backend")
    )
    _current_engine_label = next(
        (
            opt.display_label
            for opt in _engine_options
            if opt.value == _current_engine_value
        ),
        _engine_options[0].display_label,
    )
    app.transcribe_engine_var = tk.StringVar(value=_current_engine_label)
    engine_combo = ttk.Combobox(
        engine_row,
        textvariable=app.transcribe_engine_var,
        values=[opt.display_label for opt in _engine_options],
        state="readonly",
        width=44,
    )
    engine_combo.pack(side="left", padx=(6, 8))
    app.transcribe_engine_combo = engine_combo
    if not any(opt.ready for opt in _engine_options):
        # No engine has any usable path — the documented fallback for a
        # combobox whose entries can't be disabled individually.
        engine_combo.configure(state="disabled")
    help_icon(
        engine_row,
        lambda: (
            "Which transcription engine to use. Offline engines "
            "(Faster-Whisper, whisper.cpp, NVIDIA Parakeet) run entirely on "
            "this machine; the two cloud engines upload your audio to "
            "Google. Set up keys/models for each in Advanced settings.\n\n"
            + _eng.engine_status_summary(
                app.app_config,
                deep=False,
                statuses=getattr(app, "_engine_deep_statuses", None),
            )
        ),
    ).pack(side="left", padx=(0, 8))
    engine_combo.bind("<<ComboboxSelected>>", lambda _e: app._on_engine_selected())
    app.engine_status_var = tk.StringVar(value="")
    app.engine_status_label = ttk.Label(
        engine_row, textvariable=app.engine_status_var, foreground="#888",
    )
    app.engine_status_label.pack(side="left")
    # Cheap readiness probe for the initial selection (no heavy import).
    app._refresh_engine_status()

    # Model picker — which Whisper model size the Faster-Whisper engine
    # above loads (tiny/base/.../large-v3/turbo/...). Same catalog + slug
    # as Advanced settings' "Whisper model" picker; either one can change
    # it and both stay in sync (see App._refresh_model_selector).
    ttk.Label(model_row, text="Model:").pack(side="left")
    _model_labeled = catalog_models(app.app_config)
    app._transcribe_model_label_to_slug = {slug_lbl[1]: slug_lbl[0] for slug_lbl in _model_labeled}
    _model_slug_to_label = {slug: lbl for slug, lbl in _model_labeled}
    _current_model_slug = str(
        app.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG
    )
    app.transcribe_model_var = tk.StringVar(
        value=_model_slug_to_label.get(
            _current_model_slug, _model_labeled[0][1] if _model_labeled else ""
        )
    )
    model_combo = ttk.Combobox(
        model_row,
        textvariable=app.transcribe_model_var,
        values=[lbl for _slug, lbl in _model_labeled],
        state="readonly",
        width=44,
    )
    model_combo.pack(side="left", padx=(6, 8))
    app.transcribe_model_combo = model_combo
    # A disabled combobox still fires Enter/Leave, so this hover text is the
    # reason the picker is greyed out whenever the engine doesn't use it.
    bind_tooltip(model_combo, app._model_picker_disabled_reason)
    help_icon(
        model_row,
        "Which Whisper model size the Faster-Whisper engine loads — bigger "
        "models are more accurate but slower and use more RAM/VRAM. Not "
        "used by the cloud engines or NVIDIA Parakeet, which have their "
        "own model. Same picker as 'Whisper model' in Advanced settings.",
    ).pack(side="left", padx=(0, 8))
    model_combo.bind("<<ComboboxSelected>>", lambda _e: app._on_model_selected())
    app.model_status_var = tk.StringVar(value="")
    app.model_status_label = ttk.Label(
        model_row, textvariable=app.model_status_var, foreground="#888",
    )
    app.model_status_label.pack(side="left")
    # Cheap on-disk existence check only (no heavy import) — safe to run
    # synchronously, unlike _refresh_engine_status's background probe.
    app._refresh_model_status()
    # Grey the picker out entirely while a non-Faster-Whisper engine is
    # picked (those engines use their own model).
    app._sync_model_picker_for_engine()

    # ── Row 3: quick options, split across two lines so a full row of
    #     help icons doesn't overflow the app's default 960px width
    #     (pack(side="left") never wraps — it silently clips instead).
    #     Line 1: language + the two feature toggles. Line 2: the
    #     optional time-slice, which reads better on its own line
    #     anyway (it's conceptually separate from the toggles above).
    quick_opts = ttk.Frame(parent)
    quick_opts.grid(
        row=3, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 8),
    )
    opts_line1 = ttk.Frame(quick_opts)
    opts_line1.pack(fill="x")
    opts_line2 = ttk.Frame(quick_opts)
    opts_line2.pack(fill="x", pady=(6, 0))

    ttk.Label(opts_line1, text="Language:").pack(side="left")
    lang_values = ["Auto"] + [name for name, _ in _LANGS]
    lang_combo = ttk.Combobox(
        opts_line1,
        textvariable=app.transcribe_lang_var,
        values=lang_values,
        state="readonly",
        width=14,
    )
    lang_combo.pack(side="left", padx=(6, 4))
    help_icon(
        opts_line1,
        "Spoken language in the file. Auto detects it from the first few "
        "seconds of audio; picking it explicitly is faster and can be more "
        "accurate for short or noisy clips.",
    ).pack(side="left", padx=(0, 20))
    lang_combo.bind("<<ComboboxSelected>>", lambda _e: app._save_transcribe_prefs())

    # Feature toggles — friendly phrasing instead of "diarization" /
    # "Word timestamps". The research's vocabulary mapping: Aiko ships
    # "Produce timestamps" and "Skip silent parts"; speaker-detection
    # is universally framed as "Identify / detect speakers".
    diar_label = (
        "Identify speakers"
        if _diar_available
        else f"Identify speakers (unavailable — {_diar_reason})"
    )
    diar_check = ttk.Checkbutton(
        opts_line1,
        text=diar_label,
        variable=app.diarization_var,
        command=app._save_transcribe_prefs,
    )
    if not _diar_available:
        diar_check.state(["disabled"])
    diar_check.pack(side="left", padx=(0, 4))
    help_icon(
        opts_line1,
        "Splits the transcript by who is speaking (SPEAKER_00, SPEAKER_01, "
        "...). Adds processing time and needs the optional sherpa-onnx "
        "component to be installed.",
    ).pack(side="left", padx=(0, 20))

    ttk.Checkbutton(
        opts_line1,
        text="Per-word timestamps",
        variable=app.word_timestamps_var,
        command=app._save_transcribe_prefs,
    ).pack(side="left")
    help_icon(
        opts_line1,
        "Stores a start/end time for every individual word instead of only "
        "per sentence. Useful for karaoke-style captions or precise "
        "editing; makes the output file larger.",
    ).pack(side="left", padx=(4, 0))

    # Optional time-slice — transcribe only a portion of a long file
    # (e.g. 5 minutes out of a 10-hour recording). 0:00:00 on a side means
    # "unset"; leaving both at 0:00:00 transcribes the whole file.
    ttk.Label(opts_line2, text="Time range:").pack(side="left")
    app.transcribe_start_time_var = tk.StringVar(value="0:00:00")
    ttk.Entry(opts_line2, textvariable=app.transcribe_start_time_var, width=9).pack(
        side="left", padx=(6, 2)
    )
    ttk.Label(opts_line2, text="to").pack(side="left")
    app.transcribe_end_time_var = tk.StringVar(value="0:00:00")
    ttk.Entry(opts_line2, textvariable=app.transcribe_end_time_var, width=9).pack(
        side="left", padx=(2, 0)
    )
    help_icon(
        opts_line2,
        "Transcribe only this portion of the file (format H:MM:SS). Leave "
        "both at 0:00:00 to transcribe the whole file.",
    ).pack(side="left", padx=(4, 0))

    # ── Row 4: the big accent Transcribe CTA + tiny Advanced link ────
    cta_row = ttk.Frame(parent)
    cta_row.grid(
        row=4, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(4, 4),
    )
    transcribe_btn = ttk.Button(
        cta_row,
        text="▶    Transcribe",
        command=app.add,
        style="Accent.TButton",
    )
    # ipady doubles the button height; ipadx widens it. Together they
    # give the primary CTA a clear ~2× visual weight over Browse,
    # matching the hero-CTA pattern across MacWhisper / OpenWhispr /
    # WhisperUI.
    transcribe_btn.pack(side="left", ipadx=24, ipady=8)

    ttk.Button(
        cta_row, text="Advanced settings…",
        command=app.open_advanced_dialog,
    ).pack(side="right")

    # R3: GPU/CPU device badge — primary placement, next to the CTA so users
    # see it where they start a job. Driven by app.device_badge_var (set in
    # TranscriptionService.update_model_state). Registers with the App so
    # apply_device_badge can recolour it + attach the hover tooltip.
    device_badge = ttk.Label(
        cta_row, textvariable=app.device_badge_var, anchor="center",
    )
    device_badge.pack(side="right", padx=(0, 16))
    app.register_device_badge_label(
        device_badge, tier_label="Open the Hardware wizard for accelerator details."
    )

    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=1)
    parent.columnconfigure(2, weight=1)

    # ── Last Result card (hidden until first transcription completes) ─
    ttk.Separator(parent, orient="horizontal").grid(
        row=5, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(8, 6),
    )
    app.last_result_frame = section_labelframe(
        parent, "Last result",
        "The output files from the most recently finished transcription, "
        "with quick Open/Reveal actions. Stays empty until a job "
        "completes; see the Transcription Queue tab for jobs in progress.",
        padding=10,
    )
    app.last_result_frame.grid(
        row=6, column=0, columnspan=3, sticky="ew",
        padx=15, pady=(0, 12),
    )
    # The card sizes to its content instead of greedily filling the whole
    # lower half of the tab (it previously expanded via rowconfigure
    # weight=1, which dominated the window).
    app.last_result_empty_var = tk.StringVar(
        value="No transcription finished yet. Drop a file above and click Transcribe."
    )
    app.last_result_empty_label = ttk.Label(
        app.last_result_frame,
        textvariable=app.last_result_empty_var,
        foreground="#888",
    )
    app.last_result_empty_label.pack(anchor="w")
    app.last_result_body = ttk.Frame(app.last_result_frame)
    app.last_result_title_var = tk.StringVar(value="")
    app.last_result_files_frame = ttk.Frame(app.last_result_body)


def build_queue_tab(app: "App", parent: ttk.Frame) -> None:
    top_row = ttk.Frame(parent)
    top_row.pack(fill="x", padx=10, pady=6)
    help_icon(
        top_row,
        "Every transcription job you start is tracked here. Use the "
        "buttons below the list (or right-click a row) to pause, resume, "
        "cancel, re-run, or remove it; double-click a finished row to "
        "open its output folder.",
    ).pack(side="left")
    ttk.Button(top_row, text="Clear completed", command=app.clear_completed).pack(
        side="right"
    )

    cols = ("file", "status", "progress", "language", "time")
    tree_frame = ttk.Frame(parent)
    tree_frame.pack(fill="both", expand=True, padx=10)
    tree_frame.rowconfigure(0, weight=1)
    tree_frame.columnconfigure(0, weight=1)
    app.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
    headings = {
        "file": "File",
        "status": "Status",
        "progress": "Progress",
        "language": "Language",
        "time": "Elapsed",
    }
    for c in cols:
        app.tree.heading(c, text=headings[c])
    app.tree.column("language", width=140)
    app.tree.column("progress", width=150, anchor="w")
    app.tree.column("time", width=80, anchor="center")
    app.tree.column("status", width=120)
    _vsb = _AutoScrollbar(tree_frame, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=_vsb.set)
    app.tree.grid(row=0, column=0, sticky="nsew")
    _vsb.grid(row=0, column=1, sticky="ns")

    # Empty-state hint shown on top of the Treeview when there are no
    # rows yet. App.refresh hides it as soon as a task is enqueued.
    app.queue_empty_var = tk.StringVar(
        value="Queue is empty.  Go to the Transcribe tab and pick a file to add one."
    )
    app.queue_empty_label = ttk.Label(
        parent, textvariable=app.queue_empty_var, foreground="#888", anchor="center"
    )
    app.queue_empty_label.pack(fill="x", pady=(2, 0))

    app.pb = ttk.Progressbar(parent, length=400)
    app.pb.pack(fill="x", padx=10, pady=10)

    status_line = ttk.Frame(parent)
    status_line.pack()
    ttk.Label(status_line, textvariable=app.status_var).pack(side="left")
    # R3: mirror the GPU/CPU device badge next to the queue status line.
    queue_device_badge = ttk.Label(
        status_line, textvariable=app.device_badge_var,
    )
    queue_device_badge.pack(side="left", padx=(12, 0))
    app.register_device_badge_label(queue_device_badge)
    app.tree.bind("<Button-3>", app.menu_row)
    if sys.platform == "darwin":
        # macOS Tk generates Button-2 for a right-click (Button-3 is
        # the rarely-used third button there).
        app.tree.bind("<Button-2>", app.menu_row)
    # Double-click on a finished row -> open the file's containing
    # folder. Discoverable shortcut for the right-click menu entry.
    app.tree.bind("<Double-Button-1>", app.queue_row_double_click)
    app.row_map = {}

    # R2 — always-visible per-task action bar. The right-click context
    # menu is not discoverable for a non-technical operator, so mirror its
    # actions as plain buttons that operate on the selected row(s). Enabled
    # state is recomputed from the selected task's status (the same logic
    # menu_row uses, via button_states_for_status) on every selection change
    # AND inside App.refresh (which rebuilds the tree each tick).
    action_bar = ttk.Frame(parent)
    action_bar.pack(fill="x", padx=10, pady=(0, 6))
    app.queue_action_buttons = {
        "pause": ttk.Button(
            action_bar, text="Pause",
            command=lambda: app._action_bar_apply(app.pause, active_only=True),
        ),
        "resume": ttk.Button(
            action_bar, text="Resume",
            command=app._action_bar_resume,
        ),
        "cancel": ttk.Button(
            action_bar, text="Cancel",
            command=lambda: app._action_bar_apply(app.cancel, active_only=True),
        ),
        "rerun": ttk.Button(
            action_bar, text="Re-run",
            command=lambda: app._action_bar_apply(app._rerun_task, active_only=False),
        ),
        "remove": ttk.Button(
            action_bar, text="Remove",
            command=lambda: app._action_bar_apply(app.remove_task, active_only=False),
        ),
    }
    for key in ("pause", "resume", "cancel", "rerun", "remove"):
        app.queue_action_buttons[key].pack(side="left", padx=(0, 6))
        app.queue_action_buttons[key].state(["disabled"])
    # A single-click on a running/paused row's status or progress cell
    # toggles pause/resume — a discoverable shortcut on top of the menu.
    app.tree.bind("<Button-1>", app.queue_status_cell_click, add="+")
    app.tree.bind("<<TreeviewSelect>>", lambda _e: app._update_queue_action_bar())


def build_download_tab(app: "App", parent: ttk.Frame) -> None:
    top = ttk.Frame(parent, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text="URL").grid(row=0, column=0, sticky="w")
    app.download_url_var = tk.StringVar()
    app.download_url_var.trace_add("write", lambda *_: app.format_service.schedule_lookup())
    ttk.Entry(top, textvariable=app.download_url_var, width=80).grid(
        row=0, column=1, columnspan=2, sticky="ew", padx=(6, 0)
    )
    help_icon(
        top,
        "Paste a link from YouTube or any other yt-dlp-supported site. "
        "Available formats and subtitles are looked up automatically as "
        "soon as you paste it.",
    ).grid(row=0, column=3, sticky="w", padx=(6, 0))

    ttk.Label(top, text="Folder").grid(row=1, column=0, sticky="w", pady=(8, 0))
    app.download_folder_var = tk.StringVar(value=app.app_config.get("download_folder", ""))
    ttk.Entry(top, textvariable=app.download_folder_var, width=70).grid(
        row=1, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
    )
    ttk.Button(top, text="Browse", command=app.browse_download_folder).grid(
        row=1, column=2, sticky="ew", padx=(6, 0), pady=(8, 0)
    )
    help_icon(
        top,
        "Where the downloaded file is saved. Defaults to the folder "
        "you last used; Browse to change it.",
    ).grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text="Mode").grid(row=2, column=0, sticky="w", pady=(8, 0))
    app.download_mode_var = tk.StringVar(value="Audio and video")
    app.download_mode_combo = ttk.Combobox(
        top,
        textvariable=app.download_mode_var,
        state="readonly",
        values=("Audio and video", "Audio"),
        width=24,
    )
    app.download_mode_combo.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
    app.download_mode_combo.bind("<<ComboboxSelected>>", lambda _e: app.update_download_mode())
    help_icon(
        top,
        "'Audio and video' downloads a normal video file. 'Audio' "
        "extracts just the audio track — smaller and faster if you only "
        "need the sound or plan to transcribe it.",
    ).grid(row=2, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text="Audio").grid(row=3, column=0, sticky="w", pady=(8, 0))
    app.audio_format_var = tk.StringVar()
    app.audio_format_combo = ttk.Combobox(
        top, textvariable=app.audio_format_var, state="readonly", width=76
    )
    app.audio_format_combo.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        "Audio-only quality/codec choice, filled in once the URL is "
        "looked up. Higher bitrate means a larger file and better "
        "quality.",
    ).grid(row=3, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text="Video").grid(row=4, column=0, sticky="w", pady=(8, 0))
    app.video_format_var = tk.StringVar()
    app.video_format_combo = ttk.Combobox(
        top, textvariable=app.video_format_var, state="readonly", width=76
    )
    app.video_format_combo.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        "Video quality/resolution choice, filled in once the URL is "
        "looked up. Only used in 'Audio and video' mode.",
    ).grid(row=4, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    ttk.Label(top, text="Output").grid(row=5, column=0, sticky="w", pady=(8, 0))
    app.output_format_var = tk.StringVar(value="mp4")
    app.output_format_combo = ttk.Combobox(
        top, textvariable=app.output_format_var, state="readonly", width=20
    )
    app.output_format_combo.grid(row=5, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
    help_icon(
        top,
        "Container format for the saved file (e.g. mp4). Changing it may "
        "re-encode the file instead of just repackaging it, which takes "
        "longer.",
    ).grid(row=5, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    # --- Optional time-range slice (v1.0.3) -------------------------------
    # Two short Entry widgets inside a LabelFrame, plus a tiny hint label
    # below. Pre-filled with "0:00:00" so the user edits a real value
    # instead of an empty box (per request). The download service treats a
    # zero/blank bound as "unset", so leaving both = the full video.
    app.download_start_time_var = tk.StringVar(value="0:00:00")
    app.download_end_time_var = tk.StringVar(value="0:00:00")
    trim_frame = section_labelframe(
        top, "Time range (optional)",
        "Download (and optionally transcribe) only this portion of the "
        "video instead of the whole thing. Leave both at 0:00:00 for the "
        "full length.",
        padding=(8, 4),
    )
    trim_frame.grid(
        row=5, column=2, sticky="ew", padx=(12, 0), pady=(8, 0)
    )
    ttk.Label(trim_frame, text="Start").grid(row=0, column=0, sticky="w")
    start_entry = ttk.Entry(
        trim_frame, textvariable=app.download_start_time_var, width=12
    )
    start_entry.grid(row=0, column=1, sticky="w", padx=(4, 8))
    ttk.Label(trim_frame, text="End").grid(row=1, column=0, sticky="w", pady=(2, 0))
    end_entry = ttk.Entry(
        trim_frame, textvariable=app.download_end_time_var, width=12
    )
    end_entry.grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(2, 0))
    # Keep the position sliders in sync when Start/End is typed directly
    # instead of dragged -- see App._sync_download_scale_from_text for why
    # this matters (a stale slider position silently overwrites a typed
    # value the next time either knob moves).
    app.download_start_time_var.trace_add(
        "write", lambda *_a: app._sync_download_scale_from_text("start")
    )
    app.download_end_time_var.trace_add(
        "write", lambda *_a: app._sync_download_scale_from_text("end")
    )
    # Position sliders (0 .. video length) that fill the Start/End fields by
    # dragging. Disabled until a video is probed — the format probe calls
    # app.set_download_duration() with the real length (0 = live/unknown).
    trim_frame.columnconfigure(2, weight=1)
    app.download_start_scale = ttk.Scale(
        trim_frame, from_=0.0, to=1.0, orient="horizontal", length=180,
        command=lambda v: app._on_download_scale("start", v),
    )
    app.download_start_scale.state(["disabled"])
    app.download_start_scale.grid(row=0, column=2, sticky="ew", padx=(8, 0))
    app.download_end_scale = ttk.Scale(
        trim_frame, from_=0.0, to=1.0, orient="horizontal", length=180,
        command=lambda v: app._on_download_scale("end", v),
    )
    app.download_end_scale.state(["disabled"])
    app.download_end_scale.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(2, 0))
    ttk.Label(
        trim_frame,
        text="format H:MM:SS — e.g. 0:00:51 to 0:01:25; leave at 0:00:00 for full video",
        foreground="#888",
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
    app.download_duration_var = tk.StringVar(value="")
    ttk.Label(trim_frame, textvariable=app.download_duration_var, foreground="#888").grid(
        row=3, column=0, columnspan=3, sticky="w"
    )

    ttk.Label(top, text="Subtitles").grid(row=6, column=0, sticky="w", pady=(8, 0))
    sub_frame = ttk.Frame(top)
    sub_frame.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))
    saved_sub_enabled = bool(app.app_config.get("download_subtitles_enabled", False))
    app.download_subtitles_var = tk.BooleanVar(value=saved_sub_enabled)
    ttk.Checkbutton(
        sub_frame,
        text="Download subtitles (auto + manual when present)",
        variable=app.download_subtitles_var,
        command=app.update_subtitle_state,
    ).pack(side="left")
    saved_sub_lang = app.app_config.get("download_subtitle_lang") or SUBTITLE_LANGUAGES[0][0]
    if saved_sub_lang not in [name for name, _ in SUBTITLE_LANGUAGES]:
        saved_sub_lang = SUBTITLE_LANGUAGES[0][0]
    app.subtitle_lang_var = tk.StringVar(value=saved_sub_lang)
    app.subtitle_lang_combo = ttk.Combobox(
        sub_frame,
        textvariable=app.subtitle_lang_var,
        state="disabled",
        values=[name for name, _ in SUBTITLE_LANGUAGES],
        width=24,
    )
    app.subtitle_lang_combo.pack(side="left", padx=(10, 0))
    app.subtitle_status_var = tk.StringVar(value="")
    ttk.Label(sub_frame, textvariable=app.subtitle_status_var, foreground="#666").pack(
        side="left", padx=(10, 0)
    )
    help_icon(
        top,
        "Downloads the video's existing subtitles/captions (auto-"
        "generated or manual) in the chosen language, instead of "
        "transcribing the audio yourself. Only available when the site "
        "provides them.",
    ).grid(row=6, column=3, sticky="w", padx=(6, 0), pady=(8, 0))
    app.subtitle_lang_combo.bind(
        "<<ComboboxSelected>>", lambda _e: app.update_caption_shortcut_state()
    )

    # "Use captions instead" shortcut — a distinct action from the
    # "Download subtitles" checkbox above (which fetches subtitles ALONGSIDE
    # the media). This one skips the media download and transcription
    # entirely. Hidden by default; App.update_caption_shortcut_state shows
    # it only once a format lookup finds a caption track in the resolved
    # language (see app/services/format_service.py::caption_lang_map).
    caption_shortcut_frame = ttk.Frame(top)
    caption_shortcut_frame.grid(
        row=7, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(4, 0)
    )
    app.caption_shortcut_status_var = tk.StringVar(value="")
    ttk.Label(
        caption_shortcut_frame,
        textvariable=app.caption_shortcut_status_var,
        foreground="#2a7", wraplength=460, justify="left",
    ).pack(side="left")
    app.caption_shortcut_button = ttk.Button(
        caption_shortcut_frame,
        text="Use captions instead",
        command=app.download_service.enqueue_caption_only_from_form,
    )
    # Not packed here — update_caption_shortcut_state packs/unpacks it on
    # demand so it stays invisible for the common case (no captions, or
    # not in the requested language).

    app.auto_transcribe_var = tk.BooleanVar(
        value=bool(app.app_config.get("auto_transcribe_after_download", False))
    )
    ttk.Checkbutton(
        top,
        text="Transcribe after download",
        variable=app.auto_transcribe_var,
        command=app._save_auto_transcribe_pref,
    ).grid(row=8, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(4, 0))
    help_icon(
        top,
        "Automatically queues the downloaded file for transcription as "
        "soon as the download finishes, using the settings in the "
        "Transcribe tab.",
    ).grid(row=8, column=3, sticky="w", padx=(6, 0), pady=(4, 0))

    # SMTV "all parts" toggle. Built always, shown only when an SMTV
    # episode with >=1 sibling parts is detected. format_service sets
    # visibility via app._smtv_series_toggle().
    app.smtv_download_all_parts_var = tk.BooleanVar(value=True)
    smtv_frame = ttk.Frame(top)
    smtv_check = ttk.Checkbutton(
        smtv_frame,
        text="Download all parts of this series (SMTV)",
        variable=app.smtv_download_all_parts_var,
    )
    smtv_check.pack(side="left")
    help_icon(
        smtv_frame,
        "This episode has multiple parts on the source site. Checking "
        "this queues every part, not just the one you pasted.",
    ).pack(side="left", padx=(6, 0))

    def _toggle(*, visible: bool) -> None:
        if visible:
            smtv_frame.grid(row=9, column=1, columnspan=2, sticky="w",
                            padx=(6, 0), pady=(4, 0))
        else:
            smtv_frame.grid_remove()

    _toggle(visible=False)
    app._smtv_series_toggle = _toggle  # type: ignore[attr-defined]

    app.format_status_var = tk.StringVar(value="Enter a URL to load available formats")
    app.format_lookup_error = ""
    ttk.Label(top, textvariable=app.format_status_var).grid(
        row=9, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(4, 0)
    )

    # Primary CTA for the Download tab — same Accent style + larger
    # ipadx/ipady as the Transcribe button on the other tab, so the
    # user has a single visual rule for "this is the main action".
    # Spans the full row (columnspan=3) and sits at the bottom of the
    # form so it's the natural last step after filling URL + format.
    download_btn = ttk.Button(
        top, text="⬇    Download",
        command=app.add_download,
        style="Accent.TButton",
    )
    download_btn.grid(
        row=10, column=0, columnspan=3, sticky="e",
        padx=(0, 0), pady=(12, 0), ipadx=24, ipady=8,
    )

    top.columnconfigure(1, weight=1)

    bottom = ttk.Frame(parent, padding=(10, 0, 10, 10))
    bottom.pack(fill="both", expand=True)

    cols = ("name", "url", "format", "status", "progress", "time")
    bottom.rowconfigure(0, weight=1)
    bottom.columnconfigure(0, weight=1)
    app.download_tree = ttk.Treeview(bottom, columns=cols, show="headings", height=8)
    for c in cols:
        app.download_tree.heading(c, text=c)
    app.download_tree.column("name", width=220)
    app.download_tree.column("url", width=420)
    app.download_tree.column("format", width=180)
    app.download_tree.column("status", width=100)
    app.download_tree.column("progress", width=150, anchor="w")
    app.download_tree.column("time", width=80)
    _dvsb = _AutoScrollbar(bottom, orient="vertical", command=app.download_tree.yview)
    app.download_tree.configure(yscrollcommand=_dvsb.set)
    app.download_tree.grid(row=0, column=0, sticky="nsew")
    _dvsb.grid(row=0, column=1, sticky="ns")
    app.download_tree.bind("<Button-3>", app.download_menu_row)
    if sys.platform == "darwin":
        # See the Queue-tab tree binding above: macOS right-click is
        # Button-2, not Button-3.
        app.download_tree.bind("<Button-2>", app.download_menu_row)
    # See `app.row_map` above — annotation belongs on the class.
    app.download_row_map = {}

    # R2 — Download action bar mirroring the Queue tab. Pause is the
    # stop-and-continue semantics (tooltip below); SMTV downloads disable it.
    dl_action_bar = ttk.Frame(parent, padding=(10, 0, 10, 4))
    dl_action_bar.pack(fill="x")
    app.download_action_buttons = {
        "pause": ttk.Button(
            dl_action_bar, text="Pause",
            command=lambda: app._download_action_apply(app.pause_download),
        ),
        "resume": ttk.Button(
            dl_action_bar, text="Resume",
            command=lambda: app._download_action_apply(app.resume_download),
        ),
        "cancel": ttk.Button(
            dl_action_bar, text="Cancel",
            command=lambda: app._download_action_apply(app.cancel_download),
        ),
        "rerun": ttk.Button(
            dl_action_bar, text="Re-run",
            command=lambda: app._download_action_apply(app._rerun_download),
        ),
        "remove": ttk.Button(
            dl_action_bar, text="Remove",
            command=lambda: app._download_action_apply(app.remove_download),
        ),
        "open": ttk.Button(
            dl_action_bar, text="Open",
            command=app._download_action_open,
        ),
    }
    for key in ("pause", "resume", "cancel", "rerun", "remove", "open"):
        app.download_action_buttons[key].pack(side="left", padx=(0, 6))
        app.download_action_buttons[key].state(["disabled"])
    # Global list action (not tied to a selection), so it lives on the
    # right like the Queue tab's own "Clear completed" -- mirrors that
    # button, which this tab was missing.
    ttk.Button(
        dl_action_bar, text="Clear completed", command=app.clear_completed_downloads,
    ).pack(side="right")
    ttk.Label(
        dl_action_bar,
        text="(Pause stops the download but keeps the partial file; "
             "Resume continues it)",
        foreground="#888",
    ).pack(side="left", padx=(8, 0))
    app.download_tree.bind(
        "<<TreeviewSelect>>", lambda _e: app._update_download_action_bar()
    )

    app.update_download_mode()
    app.update_subtitle_state()
    app.after(200, app.format_service.poll)
    app.after(300, app.download_service.poll)


def build_tiling_tab(app: "App", parent: ttk.Frame) -> None:
    """Video Tiling: fill the screen(s) with an N×N grid of one live stream."""
    from core.tiling import QUALITY_CHOICES, ffplay_available

    cfg = app.app_config
    frame = ttk.Frame(parent, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame, text="Video Tiling", font=("TkDefaultFont", 13, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Play one live stream as a full-screen N×N grid (a video wall), "
            "optionally across several monitors. Paste a stream URL (YouTube, "
            "X / Twitter, and the other yt-dlp sites), pick the grid size, and "
            "Start. Press Q or Esc in the video window — or the Stop button — "
            "to end it. Reconnect is automatic with backoff."
        ),
        wraplength=620, justify="left", foreground="#666",
    ).pack(anchor="w", pady=(4, 10))

    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 8))
    ttk.Label(row, text="Stream URL:").pack(side="left")
    # Locked to the single approved stream: shown greyed-out, not editable.
    from core.tiling import ALLOWED_TILING_URLS
    app.tiling_url_var = tk.StringVar(value=ALLOWED_TILING_URLS[0])
    ttk.Entry(
        row, textvariable=app.tiling_url_var, state="disabled"
    ).pack(
        side="left", fill="x", expand=True, padx=(8, 0)
    )

    row2 = ttk.Frame(frame)
    row2.pack(fill="x", pady=(0, 8))
    ttk.Label(row2, text="Grid (N×N):").pack(side="left")
    from core.tiling import clamp_divisions
    app.tiling_divisions_var = tk.IntVar(
        value=clamp_divisions(app.app_config.get("tiling_divisions", 3))
    )
    ttk.Spinbox(
        row2, from_=1, to=64, width=5, textvariable=app.tiling_divisions_var,
    ).pack(side="left", padx=(8, 0))
    help_icon(
        row2,
        "How many tiles per side. 3 makes a 3×3 grid — 9 copies of the "
        "same stream filling the screen(s).",
    ).pack(side="left", padx=(4, 0))

    ttk.Label(row2, text="Quality:").pack(side="left", padx=(16, 0))
    saved_quality = cfg.get("tiling_quality", "Auto")
    if saved_quality not in QUALITY_CHOICES:
        saved_quality = "Auto"
    app.tiling_quality_var = tk.StringVar(value=saved_quality)
    quality_combo = ttk.Combobox(
        row2, textvariable=app.tiling_quality_var, state="readonly",
        values=QUALITY_CHOICES, width=8,
    )
    quality_combo.pack(side="left", padx=(8, 0))
    quality_combo.bind(
        "<<ComboboxSelected>>", lambda _e: app._save_tiling_prefs()
    )
    help_icon(
        row2,
        "Video quality for each tile. Auto picks a resolution based on "
        "the grid size and available bandwidth/CPU; a lower fixed "
        "quality reduces load with a large grid.",
    ).pack(side="left", padx=(4, 0))

    ttk.Button(row2, text="Start tiling", command=app.start_tiling).pack(
        side="left", padx=(16, 4)
    )
    ttk.Button(row2, text="Stop", command=app.stop_tiling).pack(side="left")

    # Options row: Mute, Multi-monitor, Auto-restart, Monitors chooser.
    row3 = ttk.Frame(frame)
    row3.pack(fill="x", pady=(0, 8))
    app.tiling_mute_var = tk.BooleanVar(value=bool(cfg.get("tiling_mute", False)))
    ttk.Checkbutton(
        row3, text="Mute", variable=app.tiling_mute_var,
        command=app._save_tiling_prefs,
    ).pack(side="left")
    app.tiling_multi_monitor_var = tk.BooleanVar(
        value=bool(cfg.get("tiling_multi_monitor", False))
    )
    ttk.Checkbutton(
        row3, text="Multi-monitor", variable=app.tiling_multi_monitor_var,
        command=app._save_tiling_prefs,
    ).pack(side="left", padx=(16, 0))
    app.tiling_auto_restart_var = tk.BooleanVar(
        value=bool(cfg.get("tiling_auto_restart", True))
    )
    ttk.Checkbutton(
        row3, text="Auto-restart", variable=app.tiling_auto_restart_var,
        command=app._save_tiling_prefs,
    ).pack(side="left", padx=(16, 0))
    ttk.Button(
        row3, text="Monitors…", command=app.choose_tiling_monitors,
    ).pack(side="left", padx=(16, 0))
    help_icon(
        row3,
        "Multi-monitor spreads the grid across every monitor picked in "
        "'Monitors…'. Auto-restart reconnects automatically if the "
        "stream drops.",
    ).pack(side="left", padx=(10, 0))

    # Restore the saved monitor selection (spatial indices from core.monitors).
    saved_sel = cfg.get("tiling_selected_monitors") or []
    app.tiling_selected_monitors = [
        int(i) for i in saved_sel if isinstance(i, (int, str))
    ]

    app.tiling_monitors_info_var = tk.StringVar(value="")
    ttk.Label(
        frame, textvariable=app.tiling_monitors_info_var, foreground="#888",
    ).pack(anchor="w", pady=(2, 0))
    app.refresh_tiling_monitor_info()

    app.tiling_status_var = tk.StringVar(value="")
    # Keep a handle on the label so _tiling_status can recolour it to match
    # the engine's state colour (green Playing / orange Reconnecting / grey
    # Stopped). Without the handle the colour the engine emits is discarded
    # and the line stays a fixed grey.
    app.tiling_status_label = ttk.Label(
        frame, textvariable=app.tiling_status_var, foreground="#666",
    )
    app.tiling_status_label.pack(anchor="w", pady=(6, 0))

    # ffplay presence: keep a handle on the notice frame so the Download
    # button can hide it once ffplay lands. When a download URL is configured
    # we offer a one-click "Download ffplay"; otherwise we keep the existing
    # "drop ffplay in bin" guidance.
    from core.tiling import select_ffplay_url

    app.tiling_ffplay_notice = ttk.Frame(frame)
    app.tiling_ffplay_notice.pack(anchor="w", pady=(10, 0), fill="x")
    if not ffplay_available():
        ffplay_name = "ffplay.exe" if os.name == "nt" else "ffplay"
        has_url = bool(select_ffplay_url(cfg.get("ffplay_downloads")))
        if has_url:
            ttk.Label(
                app.tiling_ffplay_notice,
                text=(
                    "Video Tiling needs ffplay, which isn't bundled. "
                    "Click below to download it automatically."
                ),
                wraplength=620, justify="left", foreground="#b5651a",
            ).pack(anchor="w")
            app.tiling_download_ffplay_btn = ttk.Button(
                app.tiling_ffplay_notice, text="Download ffplay",
                command=app.download_ffplay,
            )
            app.tiling_download_ffplay_btn.pack(anchor="w", pady=(6, 0))
        else:
            ttk.Label(
                app.tiling_ffplay_notice,
                text=(
                    f"Note: Video Tiling needs ffplay, which isn't bundled. Put "
                    f"{ffplay_name} in the app's bin folder (it comes with the "
                    f"full ffmpeg build) or install ffmpeg so ffplay is on PATH."
                ),
                wraplength=620, justify="left", foreground="#b5651a",
            ).pack(anchor="w")


def build_server_tab(app: "App", parent: ttk.Frame) -> None:
    """Web / LAN access: a one-click toggle to let a browser transcribe.

    Turning this on starts a small web page (served by this app) so you —
    or other people on your network — can drop a file or paste a link in a
    browser and get subtitles back, without installing anything. One
    obvious Start/Stop button; everything else has a plain-language note.
    """
    cfg = app.app_config
    frame = ttk.Frame(parent, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame, text="Web / LAN access", font=("TkDefaultFont", 13, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Turn this on to open a simple web page that uses this app to "
            "transcribe. Open it in a browser on this computer, or share it "
            "with phones and other PCs on your network. It stays off until "
            "you start it, and there is nothing to install on the other "
            "devices."
        ),
        wraplength=620, justify="left", foreground="#888",
    ).pack(anchor="w", pady=(4, 12))

    # --- the one obvious control: Start / Stop -------------------------------
    toggle_row = ttk.Frame(frame)
    toggle_row.pack(fill="x", pady=(0, 6))
    app.server_toggle_btn = ttk.Button(
        toggle_row, text="Start web access", command=app.toggle_server,
    )
    app.server_toggle_btn.pack(side="left")
    app.server_open_btn = ttk.Button(
        toggle_row, text="Open in browser",
        command=app.open_server_in_browser, state="disabled",
    )
    app.server_open_btn.pack(side="left", padx=(8, 0))

    # Status line ("Off" / "Running...").
    app.server_status_var = tk.StringVar(value="Off")
    ttk.Label(
        frame, textvariable=app.server_status_var,
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w", pady=(2, 0))

    # The reachable address(es) — shown so the user can type them on a
    # phone or another PC. Selectable so they can copy it.
    app.server_url_var = tk.StringVar(value="")
    url_label = ttk.Label(
        frame, textvariable=app.server_url_var, foreground="#3a7bd5",
        justify="left",
    )
    url_label.pack(anchor="w", pady=(2, 12))

    # --- options -------------------------------------------------------------
    opts = section_labelframe(
        frame, "Options",
        "Port, network sharing, and an optional access password for the "
        "web page this tab starts. Each field also has its own note "
        "below it.",
        padding=12,
    )
    opts.pack(fill="x", pady=(0, 8))

    # Port.
    port_row = ttk.Frame(opts)
    port_row.pack(fill="x", pady=(0, 8))
    ttk.Label(port_row, text="Port:").pack(side="left")
    saved_port = cfg.get("server_port", 8765)
    try:
        saved_port = int(saved_port)
    except (TypeError, ValueError):
        saved_port = 8765
    if not 1 <= saved_port <= 65535:
        saved_port = 8765
    app.server_port_var = tk.IntVar(value=saved_port)
    ttk.Spinbox(
        port_row, from_=1, to=65535, width=8,
        textvariable=app.server_port_var,
        command=app._save_server_prefs,
    ).pack(side="left", padx=(8, 0))
    ttk.Label(
        port_row,
        text="(the number after the address; leave the default if unsure)",
        foreground="#888",
    ).pack(side="left", padx=(8, 0))

    # Share on local network.
    app.server_share_lan_var = tk.BooleanVar(
        value=bool(cfg.get("server_share_lan", False))
    )
    ttk.Checkbutton(
        opts, text="Share on local network (other devices can use it)",
        variable=app.server_share_lan_var,
        command=app._save_server_prefs,
    ).pack(anchor="w")
    ttk.Label(
        opts,
        text=(
            "Off: only this computer can use it (no firewall prompt).\n"
            "On: Windows may ask to allow it through the firewall — click "
            "Allow. Anyone on your network will be able to use it."
        ),
        wraplength=560, justify="left", foreground="#888",
    ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

    # Optional access password (the --token mechanism).
    pw_row = ttk.Frame(opts)
    pw_row.pack(fill="x")
    ttk.Label(pw_row, text="Access password (optional):").pack(side="left")
    app.server_token_var = tk.StringVar(value=str(cfg.get("server_token", "")))
    pw_entry = ttk.Entry(
        pw_row, textvariable=app.server_token_var, width=24, show="•",
    )
    pw_entry.pack(side="left", padx=(8, 0))
    pw_entry.bind("<FocusOut>", lambda _e: app._save_server_prefs())
    ttk.Label(
        opts,
        text=(
            "Leave blank for no password. If you set one, share it with the "
            "people you want to let in — they will need to add it to the "
            "address as  ?token=YOURPASSWORD"
        ),
        wraplength=560, justify="left", foreground="#888",
    ).pack(anchor="w", padx=(0, 0), pady=(4, 0))

    # HTTPS (self-signed certificate).
    app.server_https_enabled_var = tk.BooleanVar(
        value=bool(cfg.get("server_https_enabled", False))
    )
    ttk.Checkbutton(
        opts, text="Use HTTPS (self-signed certificate)",
        variable=app.server_https_enabled_var,
        command=app._save_server_prefs,
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(
        opts,
        text=(
            "Off by default. When on, the address starts with https:// and "
            "the browser will warn that the certificate is not trusted the "
            "first time — that is expected; accept it once."
        ),
        wraplength=560, justify="left", foreground="#888",
    ).pack(anchor="w", padx=(22, 0), pady=(0, 8))

    # Completion webhook.
    hook_row = ttk.Frame(opts)
    hook_row.pack(fill="x")
    ttk.Label(hook_row, text="Webhook URL (optional):").pack(side="left")
    app.server_webhook_url_var = tk.StringVar(
        value=str(cfg.get("server_webhook_url", ""))
    )
    hook_entry = ttk.Entry(
        hook_row, textvariable=app.server_webhook_url_var, width=32,
    )
    hook_entry.pack(side="left", padx=(8, 0))
    hook_entry.bind("<FocusOut>", lambda _e: app._save_server_prefs())
    ttk.Label(
        opts,
        text=(
            "Leave blank for none. When set, the server POSTs a small JSON "
            "summary to this URL each time a job finishes (or fails). "
            "Loopback and private cloud-metadata addresses are refused."
        ),
        wraplength=560, justify="left", foreground="#888",
    ).pack(anchor="w", padx=(0, 0), pady=(4, 0))

    # --- safety note ---------------------------------------------------------
    ttk.Label(
        frame,
        text=(
            "Use this only on a network you trust (your home or office "
            "Wi-Fi). It has no accounts, and unless you turn on HTTPS above "
            "it is not encrypted — anyone who can reach the address (and "
            "knows the password, if you set one) can use it. The first time "
            "you turn it on it may need to download the speech model; jobs "
            "will wait for that."
        ),
        wraplength=620, justify="left", foreground="#b5651a",
    ).pack(anchor="w", pady=(10, 0))
