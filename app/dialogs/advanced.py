"""Modal Advanced settings dialog.

Model/engine choice plus per-engine setup, output formats, silence & noise
handling, prompt/hotwords, the optional AI Layer, and app-wide preferences
(watched folder, downloads, tray/telemetry). A per-engine setup section, and
the LLM provider's own fields, only appear while that engine/provider is
picked, so the default view stays short.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from core.backends.availability import (
    ENGINE_CHOICES,
    EngineStatus,
    engine_options,
    engine_status,
    engine_value_for_label,
    format_engine_status,
)
from core.config import DEFAULT_CONFIG, NOISY_AUDIO_PRESET, save_config
from core.model_manager import (
    DEFAULT_MODEL_SLUG,
    catalog_entry_info,
    catalog_models,
    catalog_resolve_entry,
    model_downloaded,
)
from core.writers import supported_formats

from app.widgets.tooltip import bind_tooltip, help_icon, section_labelframe

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.app import App


# Output-format checkbox labels. Defaults to NAME.upper(); override
# here when the registry key isn't a clean display string. ``smtv_docx``
# is the transcription team's templated Word export.
_FORMAT_LABELS: dict[str, str] = {
    "smtv_docx": "SMTV transcription",
    # Bare "ASS" is opaque, and the acronym reads badly on its own.
    "ass": "ASS (styled subtitles / karaoke)",
    # Without an override these fall back to name.upper(): "EXPRESS_SCRIBE"
    # renders with a literal underscore (looks like a raw identifier, not a
    # label) and "INQSCRIBE" loses the product's own InqScribe capitalisation.
    "express_scribe": "Express Scribe",
    "inqscribe": "InqScribe",
}

# One-line "what is this / who uses it" for each output format's hover-help
# icon. Most of these acronyms (ELAN, InqScribe, Express Scribe, LRC, TSV)
# mean nothing to a non-technical user staring at a grid of checkboxes with
# no other explanation — added in the 2026-08-14 readability pass. Every
# key from core.writers.supported_formats() must appear here.
_FORMAT_HELP: dict[str, str] = {
    "srt": "The most common subtitle format. Works in VLC, YouTube "
           "uploads, and nearly every video player/editor.",
    "ass": "Styled subtitles with per-word karaoke highlighting and text "
           "effects. Used by subtitle editors like Aegisub.",
    "vtt": "The web-standard subtitle format (HTML5 video, YouTube). "
           "Also supports per-word karaoke highlighting.",
    "tsv": "Tab-separated start/end/text — opens directly as an Audacity "
           "Labels track for lining the transcript up against a waveform.",
    "txt": "Plain text, one line per segment, no timestamps — for "
           "reading or pasting the transcript elsewhere.",
    "json": "This app's own detailed format: every timestamp, word and "
            "speaker label. What Convert / re-import and the transcript "
            "viewer read.",
    "lrc": "Synced-lyrics format used by music players and some karaoke "
           "tools.",
    "md": "Markdown with bold timestamps — readable on GitHub, Notion, "
          "or any Markdown viewer.",
    "otr": "Round-trips with the free otranscribe.com web transcript "
           "editor.",
    "elan": "For ELAN, a linguistics annotation tool used in language "
            "research and documentation.",
    "inqscribe": "For InqScribe, a transcription-editing application.",
    "express_scribe": "For Express Scribe, transcription software often "
                       "paired with a foot pedal. Export-only.",
    "docx": "A Microsoft Word document with the transcript text.",
    "pdf": "A PDF of the transcript, ready to print or share.",
    "smtv_docx": "Fills the Supreme Master TV transcription team's exact "
                 "Word template layout.",
}


_SPONSORBLOCK_CATEGORIES = [
    ("sponsor", "Sponsor"),
    ("intro", "Intro"),
    ("outro", "Outro"),
    ("interaction", "Interaction reminder"),
    ("selfpromo", "Self-promo"),
    ("preview", "Preview/recap"),
    ("filler", "Filler tangent"),
]


# Engine picker — the SAME registry the Transcribe tab's Engine dropdown
# reads (core.backends.availability), so the two pickers can't drift apart.
_BACKEND_CHOICES: list[tuple[str, str]] = ENGINE_CHOICES
_BACKEND_LABEL_TO_VALUE = {label: value for label, value in _BACKEND_CHOICES}
_BACKEND_VALUE_TO_LABEL = {value: label for label, value in _BACKEND_CHOICES}

# "Jump to" sidebar: a link label -> the small grey caption placed above it,
# starting a new group of links.
_NAV_GROUP_CAPTIONS: dict[str, str] = {"Watched folder": "App preferences"}

# LLM provider picker — which implementation "Enable local LLM" turns on.
_LLM_PROVIDER_CHOICES: list[tuple[str, str]] = [
    ("Local — offline, downloaded model", "local"),
    ("Remote — your own OpenAI-compatible API", "remote"),
]
_LLM_PROVIDER_LABEL_TO_VALUE = {label: value for label, value in _LLM_PROVIDER_CHOICES}
_LLM_PROVIDER_VALUE_TO_LABEL = {value: label for label, value in _LLM_PROVIDER_CHOICES}

# Step-by-step help for getting a Google Cloud service-account JSON. Each
# entry is (numbered text, optional clickable URL). The URLs open the exact
# console pages; screenshots are not embedded.
_GCLOUD_HELP_STEPS: list[tuple[str, str]] = [
    (
        "1. Create or pick a Google Cloud project.",
        "https://console.cloud.google.com/projectcreate",
    ),
    (
        "2. Enable the Speech-to-Text API for that project.",
        "https://console.cloud.google.com/apis/library/speech.googleapis.com",
    ),
    (
        "3. (Optional but recommended) Make sure billing is on to unlock "
        "the 60 free min/month + $300 credit.",
        "https://console.cloud.google.com/billing",
    ),
    (
        "4. Create a service account, then give it the role "
        "'Cloud Speech-to-Text User' (for Batch mode also "
        "'Storage Object Admin' on your bucket).",
        "https://console.cloud.google.com/iam-admin/serviceaccounts",
    ),
    (
        "5. On that service account: Keys > Add key > Create new key > "
        "JSON > Download. Keep this file private.",
        "",
    ),
    (
        "6. Back here, click 'Browse...' and pick that downloaded .json "
        "file. Then click 'Test connection'.",
        "",
    ),
]
_GCLOUD_OFFICIAL_GUIDE = (
    "https://cloud.google.com/speech-to-text/docs/before-you-begin"
)
_GCLOUD_USAGE_CONSOLE = "https://console.cloud.google.com/billing"


class AdvancedDialog(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.app = app
        self.title("Advanced settings")
        self.transient(app)
        self.grab_set()
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        cfg = app.app_config
        self._vad_enabled = tk.BooleanVar(value=bool(cfg.get("vad_enabled", True)))
        self._vad_min_silence = tk.IntVar(value=int(cfg.get("vad_min_silence_ms", 500)))
        self._vad_threshold = tk.DoubleVar(value=float(cfg.get("vad_threshold", 0.5)))
        self._vad_speech_pad = tk.IntVar(value=int(cfg.get("vad_speech_pad_ms", 400)))
        self._initial_prompt = tk.StringVar(value=str(cfg.get("initial_prompt", "")))
        self._hotwords = tk.StringVar(value=str(cfg.get("hotwords", "")))
        self._cookies_browser = tk.StringVar(
            value=(cfg.get("cookies_from_browser") or "").strip() or "(off)"
        )
        existing_formats = set(cfg.get("output_formats") or ["srt", "json"])
        self._format_vars: dict[str, tk.BooleanVar] = {
            f: tk.BooleanVar(value=(f in existing_formats)) for f in supported_formats()
        }
        existing_sb = set(cfg.get("sponsorblock_categories") or [])
        self._sb_vars: dict[str, tk.BooleanVar] = {
            cat: tk.BooleanVar(value=(cat in existing_sb))
            for cat, _label in _SPONSORBLOCK_CATEGORIES
        }
        self._whisper_model = tk.StringVar(
            value=str(cfg.get("whisper_model") or DEFAULT_MODEL_SLUG)
        )
        self._hub_folder_display = tk.StringVar(value=self._resolved_hub_folder())
        # Cloud Speech-to-Text (Google Gemini API) — opt-in, uploads audio.
        self._cloud_api_key = tk.StringVar(
            value=str(cfg.get("cloud_stt_api_key") or "")
        )
        self._cloud_model = tk.StringVar(
            value=str(cfg.get("cloud_stt_model") or "gemini-3.5-flash")
        )
        self._cloud_test_result = tk.StringVar(value="")
        # Google Cloud Speech-to-Text (service-account JSON) — separate from
        # the Gemini "paste a key" backend above. Uploads audio too.
        self._gcloud_credentials = tk.StringVar(
            value=str(cfg.get("gcloud_stt_credentials_json") or "")
        )
        self._gcloud_batch_mode = tk.BooleanVar(
            value=bool(cfg.get("gcloud_stt_batch_mode", False))
        )
        self._gcloud_bucket = tk.StringVar(
            value=str(cfg.get("gcloud_stt_bucket") or "")
        )
        self._gcloud_diarization = tk.BooleanVar(
            value=bool(cfg.get("gcloud_stt_diarization", False))
        )
        self._gcloud_test_result = tk.StringVar(value="")
        self._gcloud_usage_text = tk.StringVar(value="")
        # NVIDIA Parakeet/FastConformer — LOCAL transformers backend (offline).
        self._nvidia_model_id = tk.StringVar(
            value=str(cfg.get("nvidia_asr_model_id") or "")
        )
        # Backend picker uses a human label internally; map back on save.
        self._backend_display = tk.StringVar(
            value=_BACKEND_VALUE_TO_LABEL.get(
                str(cfg.get("transcribe_backend") or "faster_whisper"),
                _BACKEND_CHOICES[0][0],
            )
        )
        # Deep (import-based) EngineStatus results, filled by probes this
        # dialog fires as the user tries engines, so the combobox markers
        # and the warning row reflect real readiness, not just the cheap
        # credential check.
        self._engine_deep_statuses: dict[str, EngineStatus] = {}
        self._hallucination_detect = tk.BooleanVar(
            value=bool(cfg.get("hallucination_detect_enabled", True))
        )
        # v0.8 Phase 2 + 3 toggles
        self._demucs_enabled = tk.BooleanVar(
            value=bool(cfg.get("demucs_enabled", False))
        )
        self._denoise_enabled = tk.BooleanVar(
            value=bool(cfg.get("denoise_enabled", False))
        )
        self._denoise_level = tk.StringVar(
            value=str(cfg.get("denoise_level", "auto") or "auto")
        )
        self._ai_enabled = tk.BooleanVar(
            value=bool(cfg.get("ai_enabled", False))
        )
        # Which LLM implementation "Enable local LLM" actually turns on —
        # the bundled offline model, or a remote OpenAI-compatible endpoint
        # the user configures themselves. See core/llm.py's
        # build_runner_from_config.
        self._llm_provider_display = tk.StringVar(
            value=_LLM_PROVIDER_VALUE_TO_LABEL.get(
                str(cfg.get("llm_provider") or "local"), _LLM_PROVIDER_CHOICES[0][0]
            )
        )
        self._llm_remote_base_url = tk.StringVar(
            value=str(cfg.get("llm_remote_base_url") or "https://api.openai.com/v1")
        )
        self._llm_remote_api_key = tk.StringVar(
            value=str(cfg.get("llm_remote_api_key") or "")
        )
        self._llm_remote_model = tk.StringVar(
            value=str(cfg.get("llm_remote_model") or "")
        )
        self._auto_chapters_enabled = tk.BooleanVar(
            value=bool(cfg.get("auto_chapters_enabled", True))
        )
        # Word-timing refinement: a plain on/off checkbox for what config
        # stores as alignment="stable_ts" / "none".
        self._alignment_enabled = tk.BooleanVar(
            value=str(cfg.get("alignment") or "none") == "stable_ts"
        )
        # GPU batch size has no control in this dialog any more; "Restore
        # transcription defaults" sets this so Save still resets it.
        self._reset_hidden_tuning = False
        self._telemetry_opt_in = tk.BooleanVar(
            value=bool(cfg.get("telemetry_opt_in", False))
        )
        self._minimise_to_tray = tk.BooleanVar(
            value=bool(cfg.get("minimise_to_tray", False))
        )
        self._watched_folder = tk.StringVar(
            value=str(cfg.get("watched_folder") or "")
        )
        self._watched_folder_enabled = tk.BooleanVar(
            value=bool(cfg.get("watched_folder_enabled", False))
        )

        self._build()

        self.update_idletasks()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # Use most of the screen while leaving margins
        width = int(screen_w * 0.75)
        height = int(screen_h * 0.85)

        # Minimum sensible size
        width = max(width, 1100)
        height = max(height, 800)

        # Never exceed screen bounds
        width = min(width, screen_w - 80)
        height = min(height, screen_h - 80)

        x = (screen_w - width) // 2
        y = (screen_h - height) // 2

        self.geometry(f"{width}x{height}+{x}+{y}")
        # resizable(True, True) above with no floor meant a user could drag
        # this narrower than every section was just verified to fit at
        # (1100px content-wise) — use the SAME already-screen-clamped
        # width/height as the minimum, not a bare 1100, so this can't force
        # the window wider than a genuinely small screen allows either.
        self.minsize(width, height)

        # Auto-verify the Google Cloud key on open so the user can see at a
        # glance that the configured key works — no need to click "Test
        # connection". Only while Google Cloud is the picked engine (its
        # section is hidden otherwise): the test can trigger a one-time
        # google-cloud library install, which someone who has switched to
        # another engine must not pay for just by opening this dialog. Runs
        # on a daemon thread via _test_gcloud_connection; deferred so the
        # window is mapped first.
        try:
            from core.backends.availability import has_gcloud_key

            if (
                self._selected_backend() == "google_cloud_stt"
                and has_gcloud_key(self.app.app_config)
            ):
                self.after(250, self._test_gcloud_connection)
        except Exception:  # noqa: BLE001
            pass

    def _build(self) -> None:
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        # Scrollable content area
        content_container = ttk.Frame(main)
        content_container.pack(fill="both", expand=True)

        # Quick-nav sidebar — each entry jumps the canvas straight to that
        # section. The links are (re)built by _refresh_nav(), because the
        # set of visible sections follows the Engine picker (only the
        # picked engine's own setup section is shown).
        nav = ttk.Frame(content_container, width=132)
        nav.pack(side="left", fill="y", padx=(0, 6))
        nav.pack_propagate(False)
        ttk.Label(
            nav, text="Jump to", font=("TkDefaultFont", 9, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self._nav_frame = nav
        self._nav_links: list[tk.Widget] = []

        canvas = tk.Canvas(content_container, highlightthickness=0)
        # Keep a handle so _teardown_mousewheel can drop the global
        # bind_all on close (the <Leave> unbind only fires while the dialog
        # stays open — closing with the pointer over the canvas would
        # otherwise leave a bind_all pointing at a destroyed widget).
        self._scroll_canvas = canvas
        scrollbar = ttk.Scrollbar(
            content_container,
            orient="vertical",
            command=canvas.yview,
        )

        body = ttk.Frame(canvas, padding=12)
        self._scroll_body = body

        body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=body, anchor="nw")

        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # macOS Tk reports event.delta as +/-1 per notch; Windows reports
        # +/-120. Linux doesn't generate <MouseWheel> at all (Button-4/5
        # below), so this divisor only needs to vary between win/mac.
        _wheel_divisor = 1 if sys.platform == "darwin" else 120

        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / _wheel_divisor)), "units")

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all(
                "<Button-4>",
                lambda e: canvas.yview_scroll(-1, "units")
            )
            canvas.bind_all(
                "<Button-5>",
                lambda e: canvas.yview_scroll(1, "units")
            )

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        # Sections, top to bottom: what runs the transcription (plus that
        # engine's own setup, when it needs one), what gets written, how
        # the audio is cleaned up, then app-wide preferences. The three
        # per-engine setup sections are built up front but only ever packed
        # by _sync_engine_sections — someone on the default Faster-Whisper
        # engine never sees the Gemini / Google Cloud / Parakeet setup.
        engine = self._build_engine_section(body)
        gemini = self._build_gemini_frame(body)
        gcloud = self._build_gcloud_frame(body)
        nvidia = self._build_nvidia_frame(body)
        outputs = self._build_outputs_section(body)
        noise = self._build_noise_section(body)
        prompt = self._build_prompt_section(body)
        ai = self._build_ai_section(body)
        watch = self._build_watch_section(body)
        download = self._build_download_section(body)
        misc = self._build_misc_section(body)

        self._engine_section = engine
        self._engine_setup_frames: dict[str, ttk.LabelFrame] = {
            "cloud_stt": gemini,
            "google_cloud_stt": gcloud,
            "nvidia_asr": nvidia,
        }
        # "Jump to" links in on-screen order; hidden sections are skipped.
        self._nav_targets: list[tuple[str, ttk.LabelFrame]] = [
            ("Model & engine", engine),
            ("Gemini setup", gemini),
            ("Google Cloud setup", gcloud),
            ("Parakeet setup", nvidia),
            ("Output formats", outputs),
            ("Silence & noise", noise),
            ("Prompt & hotwords", prompt),
            ("AI Layer", ai),
            ("Watched folder", watch),
            ("Downloads (yt-dlp)", download),
            ("App behaviour", misc),
        ]
        self._sync_engine_sections()

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=self._on_close).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save", command=self._save_and_close).pack(side="right")
        ttk.Button(
            buttons, text="Restore transcription defaults",
            command=self._restore_transcription_defaults,
        ).pack(side="left")
        help_icon(
            buttons,
            "Resets the Silence & noise settings (VAD, denoise, Demucs, "
            "hallucination flagging), word-timing refinement and "
            "auto-chapters back to their defaults — plus GPU batch size, "
            "which no longer has a control of its own. Nothing is saved "
            "until you click Save, so Cancel undoes this too. Output "
            "formats, the hotwords/prompt text, model/engine choice, "
            "watched folder, and any cloud credentials are left untouched "
            "— those are deliberate choices, not per-job tuning knobs.",
        ).pack(side="left", padx=(4, 0))

    def _refresh_nav(self) -> None:
        """(Re)build the "Jump to" links for the sections currently shown.

        Each link scrolls the canvas so the target section's top edge
        lines up with the canvas's own top. ``frame.winfo_y()`` is the
        target's pixel offset relative to its parent (``body``, the
        scrollable content) — fixed regardless of the current scroll
        position, unlike a screen-relative coordinate — divided by
        ``body``'s total height gives the ``yview_moveto`` fraction
        directly. Needs ``update_idletasks`` first so both heights have
        settled from layout instead of reading stale/zero values.
        """
        nav = self._nav_frame
        canvas = self._scroll_canvas
        body = self._scroll_body
        for widget in self._nav_links:
            widget.destroy()
        self._nav_links = []

        def _jump(frame: "ttk.LabelFrame") -> None:
            self.update_idletasks()
            total = max(body.winfo_height(), 1)
            canvas.yview_moveto(max(0.0, min(1.0, frame.winfo_y() / total)))

        for label, frame in self._nav_targets:
            if frame.winfo_manager() != "pack":
                continue  # the setup section of an engine that isn't picked
            caption = _NAV_GROUP_CAPTIONS.get(label)
            if caption:
                separator = ttk.Separator(nav, orient="horizontal")
                separator.pack(fill="x", pady=(8, 4))
                caption_label = ttk.Label(
                    nav, text=caption, foreground="#888",
                    font=("TkDefaultFont", 8),
                )
                caption_label.pack(anchor="w", pady=(0, 2))
                self._nav_links += [separator, caption_label]
            link = ttk.Label(
                nav, text=label, foreground="#1a73e8", cursor="hand2",
                wraplength=122, justify="left",
            )
            link.pack(anchor="w", pady=2, fill="x")
            link.bind("<Button-1>", lambda _e, f=frame: _jump(f))
            self._nav_links.append(link)

    def _selected_backend(self) -> str:
        """The engine currently picked in this dialog's Engine combobox
        (not necessarily saved yet).

        The combobox label may carry the ``⚠ unavailable`` marker, so the
        parse goes through the shared label helper instead of the plain
        label→value map (which only knows unmarked labels).
        """
        value = engine_value_for_label(self._backend_display.get())
        return value or "faster_whisper"

    def _sync_engine_sections(self) -> None:
        """Show only the setup the engine picked in this dialog needs.

        The Gemini / Google Cloud / NVIDIA Parakeet sections are packed
        directly under "Model & engine" while their engine is picked and
        hidden otherwise, and the whisper.cpp model button only shows for
        whisper.cpp. Hiding is purely visual: every field keeps its value
        and is saved exactly as before. Also refreshes the availability
        markers / warning row for the new pick, greys the Whisper-model
        picker out when the engine can't use it, and starts a deep probe so
        the warning is based on a real check. Never raises — it runs from a
        Tk callback, where an exception surfaces as a cryptic error dialog.
        """
        try:
            selected = self._selected_backend()
            for value, frame in self._engine_setup_frames.items():
                shown = frame.winfo_manager() == "pack"
                if value == selected and not shown:
                    frame.pack(fill="x", pady=(0, 14), after=self._engine_section)
                elif value != selected and shown:
                    frame.pack_forget()
            if selected == "whisper_cpp":
                self._whisper_cpp_btn.grid()
            else:
                self._whisper_cpp_btn.grid_remove()
            self._refresh_engine_combo_values()
            self._refresh_engine_warning()
            self._sync_model_picker_engine_state()
            self._probe_selected_engine()
            self._refresh_nav()
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync engine setup sections", exc_info=True)

    def _refresh_engine_combo_values(self) -> None:
        """Re-render engine labels (cheap + any cached deep results), keeping
        the current pick selected by value."""
        combo = getattr(self, "_engine_combo", None)
        if combo is None:
            return
        try:
            options = engine_options(
                self.app.app_config,
                deep=False,
                statuses=self._engine_deep_statuses,
            )
            combo.configure(values=[o.display_label for o in options])
            combo.configure(
                state="readonly" if any(o.ready for o in options) else "disabled"
            )
            current = self._selected_backend()
            for opt in options:
                if (
                    opt.value == current
                    and self._backend_display.get() != opt.display_label
                ):
                    self._backend_display.set(opt.display_label)
                    break
        except Exception:  # noqa: BLE001
            logger.debug("Could not refresh engine combo values", exc_info=True)

    def _engine_status_for_selected(self) -> EngineStatus:
        """Cached deep status of the current pick, else its cheap status."""
        value = self._selected_backend()
        cached = self._engine_deep_statuses.get(value)
        if cached is not None:
            return cached
        return engine_status(value, self.app.app_config, deep=False)

    def _refresh_engine_warning(self) -> None:
        """Show/hide the reason row under the Engine picker.

        The reason text matches the Transcribe tab's status line exactly;
        this dialog additionally shows the per-engine setup section right
        below, so it doesn't need the "go to Advanced settings" pointer.
        """
        try:
            self._set_engine_warning(self._engine_status_for_selected())
        except Exception:  # noqa: BLE001
            logger.debug("Could not refresh engine warning", exc_info=True)

    def _set_engine_warning(self, st: EngineStatus) -> None:
        label = getattr(self, "_engine_warning", None)
        var = getattr(self, "_engine_warning_var", None)
        if label is None or var is None:
            return
        text = "" if st.ready else format_engine_status(st, action_hint="")
        try:
            var.set(text)
            if text:
                label.grid()
            else:
                label.grid_remove()
        except tk.TclError:
            pass

    def _probe_selected_engine(self) -> None:
        """Deep-probe the picked engine on a daemon thread, via the App.

        The cheap status above paints immediately; the deep probe refines
        the warning + combobox marker once installs/credentials are really
        checked. Silently skipped when the hosting object has no probe
        helper (bare test doubles) — never a hard dependency.
        """
        probe = getattr(self.app, "probe_engine_status", None)
        if not callable(probe):
            return
        value = self._selected_backend()
        try:
            probe(value, lambda st: self._apply_engine_probe(value, st))
        except Exception:  # noqa: BLE001
            logger.debug("Engine probe dispatch failed", exc_info=True)

    def _apply_engine_probe(self, value: str, st: EngineStatus) -> None:
        """Tk-main-thread sink for a finished deep probe (stale-race safe)."""
        try:
            if not self.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return
        if self._selected_backend() != value:
            return
        self._engine_deep_statuses[value] = st
        self._refresh_engine_combo_values()
        self._set_engine_warning(st)

    def _sync_model_picker_engine_state(self) -> None:
        """Grey out the Whisper-model picker unless Faster-Whisper is picked.

        The model catalog only drives Faster-Whisper; whisper.cpp, NVIDIA
        Parakeet and the cloud engines each use their own model, so leaving
        the picker live would let the user "change" something the next
        transcription silently ignores. The hover reason explains it.
        """
        combo = getattr(self, "_model_combo", None)
        if combo is None:
            return
        try:
            combo.configure(
                state=(
                    "readonly"
                    if self._selected_backend() == "faster_whisper"
                    else "disabled"
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync model picker state", exc_info=True)

    def _model_picker_disabled_reason(self) -> str:
        """Hover text while the model picker is greyed out; "" when active."""
        combo = getattr(self, "_model_combo", None)
        if combo is None:
            return ""
        try:
            if str(combo.cget("state")) != "disabled":
                return ""
        except Exception:  # noqa: BLE001
            return ""
        value = self._selected_backend()
        engine_label = _BACKEND_VALUE_TO_LABEL.get(value, value)
        return (
            f"The {engine_label} engine uses its own model. This picker only "
            "applies to the Faster-Whisper engine, so a change here would "
            "have no effect."
        )

    def _sync_llm_provider_rows(self) -> None:
        """Show only the AI Layer rows the picked LLM provider uses: the
        model download for Local, the endpoint/key/model fields for Remote.

        Purely visual (hidden fields keep their values and still save).
        Never raises — runs from a Tk callback.
        """
        try:
            remote = _LLM_PROVIDER_LABEL_TO_VALUE.get(
                self._llm_provider_display.get() or "", "local"
            ) == "remote"
            for widget in self._llm_remote_widgets:
                if remote:
                    widget.grid()
                else:
                    widget.grid_remove()
            for widget in self._llm_local_widgets:
                if remote:
                    widget.grid_remove()
                else:
                    widget.grid()
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync LLM provider rows", exc_info=True)

    def _build_engine_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Model & engine": which model and engine run the transcription,
        where downloaded models live, and the optional word-timing pass."""
        engine = section_labelframe(
            body, "Model & engine",
            "Which Whisper model and engine run the transcription, where "
            "downloaded models are kept, and an optional word-timing "
            "refinement pass. An engine that needs a key or its own "
            "download gets a setup section right below this one once "
            "picked.",
        )
        engine.pack(fill="x", pady=(0, 14))

        # Model picker (v0.8) — slug → catalog entry. The catalog is the
        # MERGED config catalog (built-in MODEL_REGISTRY + any models the
        # online/local config adds under ``model_catalog``), so a new model
        # can ship without an app update. Changing the picker rewrites
        # cfg["model"] + cfg["model_path"] in _save_and_close so ensure_model
        # downloads the new variant on the next transcription.
        ttk.Label(engine, text="Whisper model").grid(
            row=0, column=0, sticky="w", padx=8, pady=4
        )
        # Augment each model's label with its on-disk status so the user
        # can see which models are already downloaded vs. which will
        # download (the ~size is already in the label) on first use.
        labeled = [
            (slug, f"{base}   "
                   f"[{'OK - downloaded' if self._model_downloaded(slug) else 'needs download'}]")
            for slug, base in catalog_models(self.app.app_config)
        ]
        self._model_slug_to_label = {slug: lbl for slug, lbl in labeled}
        self._model_label_to_slug = {lbl: slug for slug, lbl in labeled}
        current_label = self._model_slug_to_label.get(
            self._whisper_model.get(), labeled[0][1]
        )
        self._model_display = tk.StringVar(value=current_label)
        self._model_combo = ttk.Combobox(
            engine,
            textvariable=self._model_display,
            state="readonly",
            values=[lbl for _slug, lbl in labeled],
            width=56,
        )
        self._model_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        # Hover reason while the picker is greyed out under a non-Faster-
        # Whisper engine (see _sync_model_picker_engine_state).
        bind_tooltip(self._model_combo, self._model_picker_disabled_reason)
        ttk.Button(
            engine, text="?", width=3, command=self._show_model_info,
        ).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
        ttk.Button(
            engine, text="Download now", command=self._download_selected_model,
        ).grid(row=0, column=3, sticky="w", padx=(0, 8), pady=4)

        # Model folder (v0.9) — where the picker above actually downloads
        # to / reads from. Reuses HubSetupDialog (first-run's own picker)
        # so "change it later" and "pick it at first launch" share one
        # implementation instead of two folder-writability code paths.
        ttk.Label(engine, text="Model folder").grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        folder_row = ttk.Frame(engine)
        folder_row.grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=4)
        ttk.Entry(
            folder_row, textvariable=self._hub_folder_display, state="readonly",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            folder_row, text="Change...", command=self._change_model_folder,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            folder_row, text="Open folder", command=self._open_model_folder,
        ).pack(side="left", padx=(6, 0))
        help_icon(
            engine,
            "Where downloaded model files are stored (faster-whisper, "
            "whisper.cpp, NVIDIA Parakeet). Change it to send future "
            "downloads to a different drive -- for example one with more "
            "free space. Changing this does NOT move models you've "
            "already downloaded; point it at a folder that already has "
            "them to reuse it without re-downloading.",
        ).grid(row=1, column=3, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(engine, text="Engine").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        backend_combo = ttk.Combobox(
            engine,
            textvariable=self._backend_display,
            state="readonly",
            values=[
                opt.display_label
                for opt in engine_options(self.app.app_config, deep=False)
            ],
            width=56,
        )
        backend_combo.grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        self._engine_combo = backend_combo
        backend_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._sync_engine_sections()
        )
        # Only shown while whisper.cpp is picked (see _sync_engine_sections).
        self._whisper_cpp_btn = ttk.Button(
            engine, text="Get whisper.cpp model...",
            command=self._download_whisper_cpp_model,
        )
        self._whisper_cpp_btn.grid(row=2, column=2, sticky="w", padx=8, pady=4)
        help_icon(
            engine,
            "Which engine runs the transcription. Faster-Whisper is the "
            "default; whisper.cpp helps on low-end CPUs. The two cloud "
            "engines and NVIDIA Parakeet need a one-time setup, which "
            "appears right below this section once you pick one. An engine "
            "that cannot run until you set it up is marked "
            "'⚠ unavailable' here. Same picker as the Engine dropdown on "
            "the Transcribe tab.",
        ).grid(row=2, column=3, sticky="w", padx=(0, 8), pady=4)

        # Availability warning for the picked engine — mirrors the Transcribe
        # tab's status line, phrased for this dialog ("below" = the engine's
        # own setup section). Hidden while the pick is fully ready.
        self._engine_warning_var = tk.StringVar(value="")
        self._engine_warning = ttk.Label(
            engine,
            textvariable=self._engine_warning_var,
            foreground="#b06a00",
            wraplength=560,
            justify="left",
        )
        self._engine_warning.grid(
            row=3, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 4)
        )
        self._engine_warning.grid_remove()

        ttk.Label(engine, text="Hardware").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        ttk.Button(
            engine, text="Re-detect hardware…",
            command=self._open_hardware_wizard,
        ).grid(row=4, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(
            engine,
            text="Probes CUDA / NPU / DirectML and picks the fastest tier.",
            foreground="#666", wraplength=170, justify="left",
        ).grid(row=4, column=2, sticky="w", padx=8, pady=4)

        # Word-timing refinement — a plain on/off instead of the old
        # "none"/"stable_ts" dropdown; _save_and_close maps it back.
        ttk.Checkbutton(
            engine,
            text="Refine word timings with stable-ts (slower)",
            variable=self._alignment_enabled,
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        help_icon(
            engine,
            "After transcribing, re-aligns every word's start/end time "
            "against the audio (stable-ts, about ±50 ms) for sharper "
            "per-word timing, e.g. karaoke highlighting in ASS/VTT "
            "subtitles. Adds roughly 10-30% to the run time, and needs a "
            "one-time ~700 MB component that is offered the first time "
            "you transcribe with this on.",
        ).grid(row=5, column=3, sticky="w", padx=(0, 8), pady=4)
        engine.columnconfigure(1, weight=1)
        return engine

    def _build_gemini_frame(self, body: ttk.Frame) -> ttk.LabelFrame:
        """Build the Gemini ("paste an API key") cloud engine's setup frame.

        Not packed here — _sync_engine_sections shows it only while this
        engine is picked.
        """
        cloud = section_labelframe(
            body, "Cloud Speech-to-Text (Gemini)",
            "Optional — paste a free Gemini API key to transcribe via "
            "Google's cloud instead of this machine. Uploads your audio; "
            "see the privacy warning below before turning it on.",
        )
        ttk.Label(
            cloud,
            text=(
                "PRIVACY: the Gemini engine UPLOADS your audio to Google for "
                "transcription. This BREAKS the offline guarantee — only use "
                "it for content you may send to a cloud service. The default "
                "engines stay fully offline."
            ),
            foreground="#b00020",
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))
        ttk.Label(cloud, text="Google API key").grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        ttk.Entry(
            cloud, textvariable=self._cloud_api_key, show="*", width=52,
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(
            cloud, text="Test key", command=self._test_cloud_key,
        ).grid(row=1, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(
            cloud,
            textvariable=self._cloud_test_result,
            foreground="#666",
            wraplength=680,
            justify="left",
        ).grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(
            cloud,
            text="Get a free key at aistudio.google.com (paste it above).",
            foreground="#666",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(cloud, text="Model").grid(
            row=4, column=0, sticky="w", padx=8, pady=4
        )
        ttk.Entry(
            cloud, textvariable=self._cloud_model, width=32,
        ).grid(row=4, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(
            cloud,
            text="Default: gemini-3.5-flash (a current Gemini audio model).",
            foreground="#666",
        ).grid(row=4, column=2, sticky="w", padx=8, pady=4)
        # No free-minutes figure here: the Gemini API's free tier is
        # rate-limited, not a monthly minute allowance (that 60 min/month
        # number is Google Cloud Speech-to-Text's, a different service).
        used = float(self.app.app_config.get("cloud_stt_minutes_used") or 0.0)
        ttk.Label(
            cloud,
            text=(
                f"Cloud minutes used so far: {used:.1f} (counted on this "
                "computer). Real usage and any charges are only visible in "
                "Google's billing console:"
            ),
            wraplength=680,
            justify="left",
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        link = ttk.Label(
            cloud,
            text="https://console.cloud.google.com/billing",
            foreground="#1a73e8",
            cursor="hand2",
        )
        link.grid(row=6, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        link.bind("<Button-1>", lambda _e: self._open_billing_console())
        cloud.columnconfigure(1, weight=1)
        return cloud

    def _build_nvidia_frame(self, body: ttk.Frame) -> ttk.LabelFrame:
        """Build the NVIDIA Parakeet (local transformers) engine's setup frame.

        Not packed here — _sync_engine_sections shows it only while this
        engine is picked.
        """
        nvidia = section_labelframe(
            body, "NVIDIA Parakeet (local, offline)",
            "An alternative offline speech engine (multilingual "
            "FastConformer/Parakeet) that runs entirely on this machine — "
            "no audio ever leaves the device. Downloads transformers + "
            "torch + the model (a few GB) automatically on first use.",
        )
        ttk.Label(
            nvidia,
            text=(
                "Runs ENTIRELY on this machine (no audio leaves the device). "
                "On first use, transformers + torch and the model download "
                "automatically (a few GB, one time). The default is NVIDIA's "
                "multilingual Parakeet TDT v3; you can point this at any "
                "Hugging Face automatic-speech-recognition model id or a local "
                "folder. (NVIDIA's exact Nemotron-3.5 .nemo checkpoint needs "
                "the NeMo toolkit and is not loadable here.)"
            ),
            foreground="#444",
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))
        ttk.Label(nvidia, text="Model (HF id or local path)").grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        ttk.Entry(
            nvidia, textvariable=self._nvidia_model_id, width=52,
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(
            nvidia,
            text="Default: nvidia/parakeet-tdt-0.6b-v3",
            foreground="#666",
        ).grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Button(
            nvidia, text="Prepare Parakeet model now...",
            command=self._prepare_nvidia_asr_model,
        ).grid(row=3, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(
            nvidia,
            text=(
                "Installs transformers/torch/librosa and downloads the model "
                "ahead of time, instead of waiting on the first transcription."
            ),
            foreground="#666", wraplength=500, justify="left",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        nvidia.columnconfigure(1, weight=1)
        return nvidia

    def _build_outputs_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Output formats": which transcript files every job writes."""
        outputs = section_labelframe(
            body, "Output formats",
            "Which transcript file types to write for every transcription "
            "(SRT/VTT subtitles, plain TXT, JSON with timestamps, etc.). "
            "You can check more than one — all checked formats are "
            "written for every job.",
        )
        outputs.pack(fill="x", pady=(0, 14))
        for i, name in enumerate(supported_formats()):
            # Each checkbox + its hover-help icon share one cell frame so
            # the 3-per-row grid stays intact (a bare Checkbutton has no
            # spare column of its own to grid a second widget into).
            cell = ttk.Frame(outputs)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=8, pady=4)
            ttk.Checkbutton(
                cell,
                text=_FORMAT_LABELS.get(name, name.upper()),
                variable=self._format_vars[name],
            ).pack(side="left")
            help_icon(
                cell, _FORMAT_HELP.get(name, ""), wraplength=280,
            ).pack(side="left")
        return outputs

    def _build_noise_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Silence & noise": how the audio is prepared before the model
        hears it, plus hallucination flagging.

        These are exactly the settings "Apply noisy-audio preset" changes,
        so the preset button now sits in the same section as every value
        it sets — they used to be spread over the VAD, "Model & engine"
        and "AI Layer" sections.
        """
        noise = section_labelframe(
            body, "Silence & noise",
            "How the audio is prepared before the model hears it: skip "
            "silent stretches (VAD), reduce background noise, or isolate "
            "vocals from music (Demucs) — plus flagging of lines that look "
            "hallucinated. 'Apply noisy-audio preset' at the bottom sets "
            "these for a typical non-studio recording.",
        )
        noise.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(
            noise, text="Enable VAD (skip silent segments)",
            variable=self._vad_enabled,
            command=self._sync_vad_controls_state,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))
        help_icon(
            noise,
            "On (recommended): silent stretches are detected and skipped "
            "before the audio reaches the speech model — faster, and it "
            "stops Whisper from hallucinating text into pure silence.\n\n"
            "Off: the whole file is sent to the model as-is, silence "
            "included. The three sliders right below only matter while "
            "this is on.\n\n"
            "Min silence: how long a gap must be to count as silence. "
            "Threshold: how confident the detector must be that audio is "
            "speech (lower = more sensitive). Speech pad: extra padding "
            "kept around each detected speech chunk.",
        ).grid(row=0, column=3, sticky="w", padx=(0, 8), pady=(4, 2))
        self._vad_control_rows = [
            self._slider_row(noise, "Min silence (ms)", self._vad_min_silence, 100, 2000, 50, 1),
            self._slider_row(noise, "Threshold", self._vad_threshold, 0.1, 0.9, 0.05, 2, is_float=True),
            self._slider_row(noise, "Speech pad (ms)", self._vad_speech_pad, 0, 1000, 50, 3),
        ]
        self._sync_vad_controls_state()

        ttk.Checkbutton(
            noise, text="Reduce background noise before transcribing",
            variable=self._denoise_enabled,
            command=self._sync_denoise_level_state,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(10, 2))
        help_icon(
            noise,
            "Cleans hiss, hum and rumble out of the audio before the "
            "speech model hears it, which cuts hallucinated lines on "
            "noisy recordings.\n\n"
            "The audio is measured first: recordings that are already "
            "clean are left completely untouched, because over-cleaning "
            "makes transcripts worse, not better. The result is checked "
            "afterwards too — if the filter removed speech instead of "
            "noise, the original audio is used.\n\n"
            "Uses the bundled ffmpeg only: no download, no extra "
            "install, works offline. Costs roughly 20-40 seconds per "
            "hour of audio.",
        ).grid(row=4, column=3, sticky="w", padx=(0, 8), pady=(10, 2))
        self._denoise_level_label = ttk.Label(noise, text="Strength:")
        self._denoise_level_label.grid(
            row=5, column=0, sticky="e", padx=(24, 4), pady=(0, 6)
        )
        self._denoise_level_combo = ttk.Combobox(
            noise, textvariable=self._denoise_level, state="readonly", width=12,
            values=("auto", "light", "medium", "strong"),
        )
        self._denoise_level_combo.grid(
            row=5, column=1, sticky="w", padx=4, pady=(0, 6)
        )
        help_icon(
            noise,
            "Auto (recommended) measures each recording and picks the "
            "gentlest setting that helps — including doing nothing at "
            "all. Pick a fixed strength only to override that "
            "measurement on material you know well; a fixed strength is "
            "applied even to clean audio.",
        ).grid(row=5, column=3, sticky="w", padx=(0, 8), pady=(0, 6))
        self._sync_denoise_level_state()

        ttk.Checkbutton(
            noise, text="Pre-process noisy audio with Demucs vocals separation",
            variable=self._demucs_enabled,
        ).grid(row=6, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        help_icon(
            noise,
            "Demucs isolates vocals from background music/noise before "
            "transcribing. Can improve accuracy on noisy recordings; "
            "adds processing time.",
        ).grid(row=6, column=3, sticky="w", padx=(0, 8), pady=4)

        # Hallucination detector toggle (v0.8).
        ttk.Checkbutton(
            noise,
            text="Flag likely hallucinations (repetition + BoH heuristics)",
            variable=self._hallucination_detect,
        ).grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        help_icon(
            noise,
            "Marks segments that look like Whisper's known failure modes "
            "on silence/noise: repeated phrases, or text matching common "
            "'beginning of hallucination' (BoH) patterns. Flags them in "
            "the output rather than removing them.",
        ).grid(row=7, column=3, sticky="w", padx=(0, 8), pady=4)

        ttk.Button(
            noise, text="Apply noisy-audio preset",
            command=self._apply_noisy_audio_preset,
        ).grid(row=8, column=0, sticky="w", padx=8, pady=(8, 10))
        help_icon(
            noise,
            "One click for a non-studio recording (street noise, a "
            "crowded room, a phone call): turns on VAD + denoise "
            "(fixed 'medium', not 'auto') + hallucination flagging, and "
            "raises the VAD threshold so background noise is less "
            "likely to be misread as speech. Does NOT turn on Demucs — "
            "that's a much heavier download/step, opt into it above "
            "separately if this preset alone isn't enough.",
        ).grid(row=8, column=3, sticky="w", padx=(0, 8), pady=(8, 10))
        return noise

    def _build_prompt_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Prompt & hotwords": user-authored text that steers recognition."""
        prompt_section = section_labelframe(
            body, "Prompt & hotwords",
            "Optional text fed to the model before it starts, and words "
            "to bias recognition toward.",
        )
        prompt_section.pack(fill="x", pady=(0, 14))

        ttk.Label(prompt_section, text="Initial prompt").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(prompt_section, textvariable=self._initial_prompt, width=42).grid(
            row=0, column=1, sticky="ew", padx=8, pady=4
        )
        help_icon(
            prompt_section,
            "Optional text fed to the model as context before it starts — "
            "e.g. proper nouns or a punctuation/formatting style to "
            "nudge it toward. Leave blank for none.",
        ).grid(row=0, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(prompt_section, text="Hotwords (comma-separated)").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(prompt_section, textvariable=self._hotwords, width=42).grid(
            row=1, column=1, sticky="ew", padx=8, pady=4
        )
        help_icon(
            prompt_section,
            "Words or short phrases (names, jargon, acronyms) the model "
            "should be biased toward recognizing correctly when it hears "
            "something close to them.",
        ).grid(row=1, column=2, sticky="w", padx=8, pady=4)
        prompt_section.columnconfigure(1, weight=1)
        return prompt_section

    def _build_ai_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"AI Layer": the optional LLM behind the transcript viewer's AI
        Tools tab and the auto-chapter titles."""
        ai = section_labelframe(
            body, "AI Layer (optional)",
            "Optional AI extras on top of the transcript: the transcript "
            "viewer's AI Tools (summaries, action items, Q&A, translation) "
            "and sentence-like auto-chapter titles — run by a small model "
            "on this machine (Local) or by your own API (Remote).",
        )
        ai.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(
            ai, text="Enable AI tools (summaries, Q&A, translation, chapter titles)",
            variable=self._ai_enabled,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        help_icon(
            ai,
            "Master switch for the transcript viewer's AI Tools tab "
            "(summarize, action items, ask, translate) and for "
            "sentence-like auto-chapter titles (without it, chapters get "
            "plain generic titles). 'LLM provider' below picks where the "
            "model runs.",
        ).grid(row=0, column=3, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(ai, text="LLM provider").grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        provider_combo = ttk.Combobox(
            ai, textvariable=self._llm_provider_display, state="readonly",
            values=[label for label, _value in _LLM_PROVIDER_CHOICES], width=40,
        )
        provider_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        provider_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._sync_llm_provider_rows()
        )
        help_icon(
            ai,
            "Local (default): a small offline model (Qwen2.5-1.5B) on "
            "this machine — nothing leaves it. Install it once with "
            "'Install AI model…'.\n\n"
            "Remote: sends the same summarise/action-items/ask/translate "
            "requests to an OpenAI-compatible '/chat/completions' "
            "endpoint you configure instead — the real OpenAI API "
            "with your own key, or a self-hosted server (Ollama, LM "
            "Studio, vLLM) or proxy (OpenRouter) if you point the Base "
            "URL at one. Your transcript text is sent to whatever "
            "endpoint you configure — only use this with a provider you "
            "trust.",
        ).grid(row=1, column=3, sticky="w", padx=(0, 8), pady=4)

        # Local provider only (see _sync_llm_provider_rows).
        install_btn = ttk.Button(
            ai, text="Install AI model…",
            command=self._install_ai_model,
        )
        install_btn.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        install_note = ttk.Label(
            ai,
            text="Downloads the offline model once (~1 GB); Local needs it before it works.",
            foreground="#666",
        )
        install_note.grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self._llm_local_widgets: list[tk.Widget] = [install_btn, install_note]

        # Remote provider only.
        url_label = ttk.Label(ai, text="Base URL")
        url_label.grid(row=3, column=0, sticky="w", padx=8, pady=4)
        url_entry = ttk.Entry(ai, textvariable=self._llm_remote_base_url, width=42)
        url_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=8, pady=4)
        key_label = ttk.Label(ai, text="API key")
        key_label.grid(row=4, column=0, sticky="w", padx=8, pady=4)
        key_entry = ttk.Entry(
            ai, textvariable=self._llm_remote_api_key, show="*", width=42,
        )
        key_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=8, pady=4)
        key_hint = ttk.Label(
            ai, text="For the real OpenAI API, get a key at platform.openai.com. "
                     "Leave blank for a local server that doesn't need one.",
            foreground="#666", wraplength=420, justify="left",
        )
        key_hint.grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        model_label = ttk.Label(ai, text="Model")
        model_label.grid(row=6, column=0, sticky="w", padx=8, pady=4)
        model_entry = ttk.Entry(ai, textvariable=self._llm_remote_model, width=42)
        model_entry.grid(row=6, column=1, columnspan=2, sticky="ew", padx=8, pady=4)
        model_help = help_icon(
            ai,
            "The exact model id your endpoint expects, e.g. gpt-4o-mini "
            "or gpt-4o for the real OpenAI API, or a locally-loaded "
            "model's name for Ollama/LM Studio. This app does not pick "
            "one for you — different accounts/servers have different "
            "models available.",
        )
        model_help.grid(row=6, column=3, sticky="w", padx=(0, 8), pady=4)
        self._llm_remote_widgets: list[tk.Widget] = [
            url_label, url_entry, key_label, key_entry, key_hint,
            model_label, model_entry, model_help,
        ]

        ttk.Checkbutton(
            ai, text="Generate auto-chapter markers (writes <name>.chapters.json)",
            variable=self._auto_chapters_enabled,
        ).grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 4))
        help_icon(
            ai,
            "Splits the transcript into chapters at natural long pauses "
            "and writes them to a separate <name>.chapters.json file next "
            "to the transcript. Titles are a short generic label by "
            "default, or a real sentence-like title when 'Enable AI "
            "tools' above is also on. Browse them from the transcript "
            "viewer's Chapters tab.",
        ).grid(row=7, column=3, sticky="w", padx=(0, 8), pady=(10, 4))
        ai.columnconfigure(1, weight=1)
        self._sync_llm_provider_rows()
        return ai

    def _build_watch_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Watched folder": auto-queue new files dropped into a folder."""
        watch = section_labelframe(
            body, "Watched folder",
            "Automatically queues any new audio/video file dropped into "
            "this folder for transcription, using your current Transcribe "
            "settings — no need to open the app and browse for it.",
        )
        watch.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(
            watch, text="Auto-transcribe new files dropped here",
            variable=self._watched_folder_enabled,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Label(watch, text="Folder").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(watch, textvariable=self._watched_folder, width=42).grid(
            row=1, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(
            watch, text="Browse...",
            command=self._browse_watched_folder,
        ).grid(row=1, column=2, sticky="w", padx=8, pady=4)
        watch.columnconfigure(1, weight=1)
        return watch

    def _build_download_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"Downloads (yt-dlp)": SponsorBlock cuts + browser cookies.

        "Transcribe after download" is deliberately not repeated here —
        the Download Videos tab has its own checkbox for it, right next to
        the download it applies to.
        """
        download = section_labelframe(
            body, "Downloads (yt-dlp)",
            "Options for video downloads (Download Videos tab): which "
            "SponsorBlock segments get cut, and browser cookies for "
            "login-walled sites.",
        )
        download.pack(fill="x", pady=(0, 14))
        ttk.Label(download, text="SponsorBlock — remove these segments:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 4)
        )
        help_icon(
            download,
            "SponsorBlock is a community-maintained database of "
            "skippable segments (ads, intros, self-promo, etc.) for the "
            "exact video. Checked categories are cut from the downloaded "
            "file automatically when the site has data for it.",
        ).grid(row=0, column=2, sticky="w", padx=8, pady=(4, 4))
        for i, (cat, label) in enumerate(_SPONSORBLOCK_CATEGORIES):
            ttk.Checkbutton(download, text=label, variable=self._sb_vars[cat]).grid(
                row=1 + i // 3, column=i % 3, sticky="w", padx=8, pady=2
            )
        ttk.Label(
            download,
            text=("Cookies from browser (for login-walled sites — Facebook /"
                  " Instagram / TikTok stories, some YouTube Shorts):"),
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 2))
        ttk.Combobox(
            download, textvariable=self._cookies_browser, state="readonly",
            width=14,
            values=["(off)", "chrome", "edge", "firefox", "brave",
                    "chromium", "opera", "vivaldi"],
        ).grid(row=5, column=0, sticky="w", padx=8, pady=(0, 4))
        return download

    def _build_misc_section(self, body: ttk.Frame) -> ttk.LabelFrame:
        """"App behaviour": system tray + anonymous usage statistics."""
        misc = section_labelframe(
            body, "App behaviour",
            "General app behaviour: whether closing the window minimises "
            "to the system tray instead of exiting, and whether anonymous "
            "usage statistics (no audio or transcript content) are sent.",
        )
        misc.pack(fill="x", pady=(0, 14))
        tray_row = ttk.Frame(misc)
        tray_row.pack(anchor="w", fill="x")
        tray_check = ttk.Checkbutton(
            tray_row, text="Minimise to system tray instead of exit",
            variable=self._minimise_to_tray,
        )
        tray_check.pack(side="left", padx=8, pady=4)
        help_icon(
            tray_row,
            "When on, closing the main window (the X button) hides it to "
            "a small icon near the clock instead of quitting — any "
            "running or queued jobs keep going in the background. Click "
            "the tray icon to bring the window back, or use its right-"
            "click menu to Exit for real.",
        ).pack(side="left")
        if sys.platform == "darwin":
            # System tray is unsupported on macOS (TrayController bails
            # out for darwin); disable the checkbox so it can't be
            # enabled and silently do nothing.
            tray_check.state(["disabled"])
        ttk.Checkbutton(
            misc, text="Send anonymous usage statistics (on by default — uncheck to opt out)",
            variable=self._telemetry_opt_in,
        ).pack(anchor="w", padx=8, pady=4)
        return misc

    def _build_gcloud_frame(self, body) -> ttk.LabelFrame:
        """Build the Google Cloud Speech-to-Text (service-account) frame.

        Kept separate from the Gemini "paste a key" frame because the two
        cloud paths authenticate differently (an API key vs. a downloaded
        service-account JSON file) and a non-technical user must not
        confuse them. Not packed here — _sync_engine_sections shows it
        only while this engine is picked.
        """
        gc = section_labelframe(
            body, "Google Cloud Speech-to-Text (service account)",
            "Optional — the full Google Cloud Speech-to-Text service, "
            "signed in with a downloaded service-account JSON file (not "
            "the simple API key the separate Gemini engine uses). The "
            "only engine in this app that natively combines real "
            "word-level timestamps, speaker diarization, AND a cheap "
            "Batch mode for long files (~$0.004/minute, usually ready "
            "within 24 hours). New accounts get 60 free minutes/month "
            "plus a $300/90-day credit. Uploads your audio to Google — "
            "not offline.",
        )

        ttk.Label(
            gc,
            text=(
                "This is the FULL Google Cloud Speech-to-Text service. It "
                "signs in with a service-account JSON file you download from "
                "the Google Cloud console (NOT the simple API key the "
                "separate Gemini engine uses). New Google Cloud customers get "
                "60 free minutes every month plus a $300 / 90-day credit.\n\n"
                "It is the only engine here that combines all three: real "
                "word-level timestamps, speaker diarization, and a cheap "
                "Batch mode for long files — Batch costs about "
                "$0.004/minute (~75% less than Standard's ~$0.016/minute) "
                "and is usually ready within 24 hours."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8))

        # -- service-account JSON file row --------------------------------
        ttk.Label(gc, text="Service-account JSON file:").grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        self._gcloud_path_label = ttk.Label(
            gc,
            text=self._gcloud_path_display(),
            foreground="#666",
            wraplength=560,
            justify="left",
        )
        self._gcloud_path_label.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(
            gc, text="Browse...", command=self._browse_gcloud_credentials,
        ).grid(row=1, column=2, sticky="w", padx=8, pady=4)

        btns = ttk.Frame(gc)
        btns.grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Button(
            btns, text="How do I get this file?",
            command=self._show_gcloud_help,
        ).pack(side="left")
        ttk.Button(
            btns, text="Test connection",
            command=self._test_gcloud_connection,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            gc,
            textvariable=self._gcloud_test_result,
            foreground="#666",
            wraplength=680,
            justify="left",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        # -- batch mode + bucket ------------------------------------------
        ttk.Checkbutton(
            gc,
            text="Batch mode (cheaper, slower)",
            variable=self._gcloud_batch_mode,
            command=self._refresh_gcloud_dynamic,
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(
            gc,
            text=(
                "Batch is ~75% cheaper (~$0.004/min vs ~$0.016/min) but can "
                "take up to ~24 hours and needs a Google Cloud Storage bucket "
                "you own."
            ),
            foreground="#666",
            wraplength=680,
            justify="left",
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(gc, text="Cloud Storage bucket:").grid(
            row=6, column=0, sticky="w", padx=8, pady=4
        )
        self._gcloud_bucket_entry = ttk.Entry(
            gc, textvariable=self._gcloud_bucket, width=42,
        )
        self._gcloud_bucket_entry.grid(row=6, column=1, sticky="ew", padx=8, pady=4)
        help_icon(
            gc,
            "Only needed for Batch mode above: the name of a Google Cloud "
            "Storage bucket YOU own, that this Google Cloud account has "
            "access to. Create one in the Cloud Storage section of the "
            "console if you don't have one yet.",
        ).grid(row=6, column=2, sticky="w", padx=(0, 8), pady=4)

        # -- diarization ---------------------------------------------------
        ttk.Checkbutton(
            gc,
            text="Detect speakers (diarization)",
            variable=self._gcloud_diarization,
        ).grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        help_icon(
            gc,
            "Labels which speaker said each part of the transcript "
            "(Speaker 1, Speaker 2, ...). Works in both modes above. In "
            "Batch mode, labels stay consistent across the whole file. In "
            "Standard (online) mode, audio is sent to Google in ~1-minute "
            "pieces and the speaker numbering restarts each time, so the "
            "same person can end up under a different label in different "
            "parts of the transcript.",
        ).grid(row=7, column=3, sticky="w", padx=(0, 8), pady=4)

        # -- live usage / cost estimate -----------------------------------
        ttk.Label(
            gc,
            textvariable=self._gcloud_usage_text,
            wraplength=680,
            justify="left",
        ).grid(row=8, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(
            gc,
            text="(local estimate — see Google Cloud Console for the real figure)",
            foreground="#666",
        ).grid(row=9, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 2))
        usage_link = ttk.Label(
            gc,
            text="Open billing/usage console",
            foreground="#1a73e8",
            cursor="hand2",
        )
        usage_link.grid(row=10, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        usage_link.bind(
            "<Button-1>", lambda _e: self._open_url(_GCLOUD_USAGE_CONSOLE)
        )

        # -- privacy note --------------------------------------------------
        ttk.Label(
            gc,
            text="Cloud transcription uploads your audio to Google (it is not offline).",
            foreground="#b00020",
            wraplength=680,
            justify="left",
        ).grid(row=11, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 4))

        gc.columnconfigure(1, weight=1)

        # Initialise the dynamic bits (bucket enable/disable + usage label).
        self._refresh_gcloud_dynamic()
        self._refresh_gcloud_usage()

        return gc

    def _slider_row(self, parent, label: str, var, lo, hi, _step, row: int, *, is_float: bool = False):
        """Build one label/scale/value-echo row; return the 3 widgets.

        Returned so a caller with a parent enable/disable toggle (e.g. the
        VAD "Enable" checkbox) can grey the whole row out — see
        ``_sync_vad_controls_state``.
        """
        row_label = ttk.Label(parent, text=label)
        row_label.grid(row=row, column=0, sticky="w", padx=8, pady=4)
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal", length=240)
        scale.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        echo_var = tk.StringVar(value=f"{float(var.get()):.2f}" if is_float else str(int(var.get())))

        def _refresh(*_):
            echo_var.set(f"{float(var.get()):.2f}" if is_float else str(int(var.get())))

        var.trace_add("write", _refresh)
        echo_label = ttk.Label(parent, textvariable=echo_var, width=8)
        echo_label.grid(row=row, column=2, padx=8, pady=4)
        parent.columnconfigure(1, weight=1)
        return row_label, scale, echo_label

    def _show_model_info(self) -> None:
        """Show a small modal with the SELECTED model's description.

        Reads the catalog entry for whichever slug the combobox currently
        shows and displays its label, description, and approximate size.
        """
        slug = self._model_label_to_slug.get(
            self._model_display.get() or "", DEFAULT_MODEL_SLUG
        )
        info = catalog_entry_info(self.app.app_config, slug)
        if info is None:
            return

        top = tk.Toplevel(self)
        top.title("Model info")
        top.transient(self)
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text=info["label"], font=("", 10, "bold"),
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        body = info["info"] or "No description available."
        size_gb = info["approx_size_gb"]
        if size_gb:
            body = f"{body}\n\nApprox. download size: ~{size_gb:g} GB"

        ttk.Label(
            frame, text=body, wraplength=420, justify="left",
        ).pack(anchor="w")

        ttk.Button(frame, text="Close", command=top.destroy).pack(
            anchor="e", pady=(14, 0)
        )
        top.update_idletasks()
        try:
            top.grab_set()
        except tk.TclError:
            pass

    def _model_downloaded(self, slug: str) -> bool:
        """True when the model's weights are already on disk under the
        configured hub folder, so the dropdown can mark it downloaded.

        Delegates to core.model_manager.model_downloaded (shared with the
        Transcribe tab's quick model picker) -- kept as a thin instance
        method so existing tests can still monkeypatch it per-instance.
        """
        return model_downloaded(self.app.app_config, slug)

    def _resolved_hub_folder(self) -> str:
        """The model folder actually in effect right now: the configured
        ``hub_folder``, or the default per-user cache location when unset."""
        from core import hub as _hub

        return (self.app.app_config.get("hub_folder") or "").strip() or str(
            _hub.default_hub_folder()
        )

    def _refresh_model_picker_labels(self) -> None:
        """Rebuild the Whisper-model combobox's values/status after the
        model folder changes -- a different folder may already contain a
        model that showed "needs download" a moment ago, or vice versa."""
        combo = getattr(self, "_model_combo", None)
        if combo is None:
            return
        current_slug = self._model_label_to_slug.get(
            self._model_display.get() or "", DEFAULT_MODEL_SLUG
        )
        labeled = [
            (slug, f"{base}   "
                   f"[{'OK - downloaded' if self._model_downloaded(slug) else 'needs download'}]")
            for slug, base in catalog_models(self.app.app_config)
        ]
        self._model_slug_to_label = {slug: lbl for slug, lbl in labeled}
        self._model_label_to_slug = {lbl: slug for slug, lbl in labeled}
        combo["values"] = [lbl for _slug, lbl in labeled]
        self._model_display.set(
            self._model_slug_to_label.get(current_slug, labeled[0][1] if labeled else "")
        )

    def _change_model_folder(self) -> None:
        """Open the model-folder picker -- the same dialog first-run setup
        uses, pre-filled with the folder currently in effect.

        HubSetupDialog persists immediately on OK (writes hub_folder +
        model_path and saves to disk itself), independent of this dialog's
        own Save/Cancel -- matching every other on-demand action button
        here (Download now, Get whisper.cpp model, Install AI model, ...).
        "Skip for now" must NOT be treated as a change: HubSetupDialog's
        own _on_cancel still calls on_done (with the default path, so a
        first-run caller always gets something to proceed with), so the
        dialog's own ``saved`` flag -- not merely "on_done fired" -- is
        what tells a real pick apart from a dismiss.
        """
        from app.dialogs.hub_setup import HubSetupDialog

        holder: dict[str, Any] = {}

        def _on_done(path: str) -> None:
            dlg = holder.get("dlg")
            if dlg is not None and not getattr(dlg, "saved", False):
                return  # "Skip for now" -- nothing was actually changed
            self._hub_folder_display.set(path)
            self._refresh_model_picker_labels()
            refresh = getattr(self.app, "_refresh_model_selector", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:  # noqa: BLE001
                    pass

        holder["dlg"] = HubSetupDialog(self, self.app.app_config, on_done=_on_done)

    def _open_model_folder(self) -> None:
        """Reveal the current model folder in the OS file manager."""
        from app.widgets.platform import open_folder

        open_folder(self._hub_folder_display.get().strip(), parent=self)

    def _download_selected_model(self) -> None:
        """Download / install the model chosen in the picker, on demand —
        instead of waiting for the first transcription to trigger it."""
        slug = self._model_label_to_slug.get(
            self._model_display.get() or "", DEFAULT_MODEL_SLUG
        )
        entry = catalog_resolve_entry(self.app.app_config, slug)
        if entry is None:
            return
        if self._model_downloaded(slug):
            self.app.log("That model is already downloaded.")
            return
        cfg = self.app.app_config
        cfg["whisper_model"] = slug
        cfg["model"] = entry
        cfg["model_path"] = ""  # let ensure_model fetch it into the hub
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Could not save model choice: {e}")
            return
        # Close Advanced first, then open the download modal on the app so
        # two modal grabs don't stack. Tear down the global mousewheel binds
        # before destroy() — same as _save_and_close / _on_close. Without
        # this, closing via "Download now" while the pointer is over the
        # canvas leaves a bind_all pointing at the destroyed widget (the
        # <Leave> unbind never fires), leaking a stray callback on every
        # later scroll.
        self._teardown_mousewheel()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        # Use download_model_now (not ensure_model_with_modal): the latter
        # early-returns on the app-global model_ready flag, so once ANY model
        # was loaded "Download now" did nothing. We already confirmed THIS
        # slug's bytes are absent via _model_downloaded above; force the modal.
        self.app.after(0, lambda: self.app.download_model_now())

    def _restore_transcription_defaults(self) -> None:
        """Reset per-job transcription tuning knobs to `DEFAULT_CONFIG`.

        Scoped like Voice-Pro's own per-panel "Load Defaults" button: only
        the settings that shape a single transcription run. Deliberately
        excludes output formats, initial_prompt/hotwords (user-authored
        text), model/backend choice, watched folder, and every credential
        field - those are persistent choices a silent reset shouldn't
        touch, not experiments a user wants to undo.
        """
        self._vad_enabled.set(True)
        self._vad_min_silence.set(500)
        self._vad_threshold.set(0.5)
        self._vad_speech_pad.set(400)
        self._sync_vad_controls_state()
        self._hallucination_detect.set(True)
        self._alignment_enabled.set(False)
        self._demucs_enabled.set(False)
        self._denoise_enabled.set(False)
        self._denoise_level.set("auto")
        self._auto_chapters_enabled.set(True)
        self._sync_denoise_level_state()
        # GPU batch size has no control here any more; queue its reset so a
        # value tuned in an older version can't linger invisibly. Applied by
        # _save_and_close, like everything else above.
        self._reset_hidden_tuning = True

    def _save_and_close(self) -> None:
        cfg = self.app.app_config
        cfg["vad_enabled"] = bool(self._vad_enabled.get())
        cfg["vad_min_silence_ms"] = int(self._vad_min_silence.get())
        cfg["vad_threshold"] = round(float(self._vad_threshold.get()), 2)
        cfg["vad_speech_pad_ms"] = int(self._vad_speech_pad.get())
        cfg["output_formats"] = [name for name, v in self._format_vars.items() if v.get()] or ["srt"]
        # Settings with no control in this dialog are left exactly as they
        # are: batch_size (GPU tuning; only "Restore transcription defaults"
        # resets it), output_filename_template (config.json only), and
        # auto_transcribe_after_download (the Download Videos tab's own
        # checkbox saves it). Writing stale copies here would clobber them.
        if self._reset_hidden_tuning:
            cfg["batch_size"] = DEFAULT_CONFIG["batch_size"]
        cfg["initial_prompt"] = self._initial_prompt.get().strip()
        cfg["hotwords"] = self._hotwords.get().strip()
        cfg["sponsorblock_categories"] = [c for c, v in self._sb_vars.items() if v.get()]
        _cb = self._cookies_browser.get().strip()
        cfg["cookies_from_browser"] = "" if _cb in ("", "(off)") else _cb
        _old_backend = str(cfg.get("transcribe_backend") or "")
        cfg["transcribe_backend"] = (
            engine_value_for_label(self._backend_display.get()) or "faster_whisper"
        )
        _backend_changed = cfg["transcribe_backend"] != _old_backend
        cfg["cloud_stt_api_key"] = self._cloud_api_key.get().strip()
        cfg["cloud_stt_model"] = (
            self._cloud_model.get().strip() or "gemini-3.5-flash"
        )
        # Google Cloud Speech-to-Text (service-account) settings.
        cfg["gcloud_stt_credentials_json"] = (
            self._gcloud_credentials.get() or ""
        ).strip()
        cfg["gcloud_stt_batch_mode"] = bool(self._gcloud_batch_mode.get())
        cfg["gcloud_stt_bucket"] = (self._gcloud_bucket.get() or "").strip()
        cfg["gcloud_stt_diarization"] = bool(self._gcloud_diarization.get())
        # NVIDIA Parakeet / FastConformer (local transformers) settings.
        cfg["nvidia_asr_model_id"] = self._nvidia_model_id.get().strip()
        cfg["alignment"] = "stable_ts" if self._alignment_enabled.get() else "none"
        cfg["hallucination_detect_enabled"] = bool(self._hallucination_detect.get())
        cfg["demucs_enabled"] = bool(self._demucs_enabled.get())
        cfg["denoise_enabled"] = bool(self._denoise_enabled.get())
        cfg["denoise_level"] = (self._denoise_level.get() or "auto").strip().lower()
        cfg["ai_enabled"] = bool(self._ai_enabled.get())
        cfg["llm_provider"] = _LLM_PROVIDER_LABEL_TO_VALUE.get(
            self._llm_provider_display.get() or "", "local"
        )
        cfg["llm_remote_base_url"] = self._llm_remote_base_url.get().strip()
        cfg["llm_remote_api_key"] = self._llm_remote_api_key.get().strip()
        cfg["llm_remote_model"] = self._llm_remote_model.get().strip()
        cfg["auto_chapters_enabled"] = bool(self._auto_chapters_enabled.get())
        # Model picker — convert the displayed label back to the
        # registry slug and rewrite cfg["model"] + cfg["model_path"]
        # when the user picked something different. Setting
        # model_path to "" forces _apply_runtime_fallbacks to point
        # at the right cache folder for the new model.
        chosen_label = self._model_display.get() or ""
        new_slug = self._model_label_to_slug.get(chosen_label, DEFAULT_MODEL_SLUG)
        if new_slug and new_slug != cfg.get("whisper_model"):
            entry = catalog_resolve_entry(cfg, new_slug)
            if entry is not None:
                cfg["whisper_model"] = new_slug
                cfg["model"] = entry
                cfg["model_path"] = ""
                # Stop any live worker so the OLD model stops transcribing.
                # The worker loads the model once at spawn and keeps it hot;
                # rewriting cfg alone left it serving the previous model until
                # the process happened to restart. stop_all() forces a fresh
                # worker (loading the new model) on the next transcribe — the
                # same mechanism _offer_optional_install uses after an install.
                try:
                    self.app.transcription_service.stop_all()
                except Exception as e:  # noqa: BLE001
                    self.app.log(f"Could not restart the transcription worker: {e}")
                self.app.log(
                    f"Whisper model changed to {new_slug}. The new model "
                    "will download on the next transcription."
                )
            else:
                self.app.log(f"Unknown model slug {new_slug!r}; keeping current model.")
        cfg["telemetry_opt_in"] = bool(self._telemetry_opt_in.get())
        cfg["minimise_to_tray"] = bool(self._minimise_to_tray.get())
        new_watched = (self._watched_folder.get() or "").strip()
        new_watched_enabled = bool(self._watched_folder_enabled.get())
        watched_changed = (
            cfg.get("watched_folder", "") != new_watched
            or bool(cfg.get("watched_folder_enabled", False)) != new_watched_enabled
        )
        cfg["watched_folder"] = new_watched
        cfg["watched_folder_enabled"] = new_watched_enabled
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Failed to save settings: {e}")
        # Engine switch needs a fresh worker: the live worker snapshots
        # transcribe_backend at spawn and the dispatch prefers that stale
        # value, so rewriting cfg alone keeps the old engine running until the
        # process restarts. stop_all() forces a fresh worker (reading the new
        # backend) on the next transcribe — same mechanism as a model change.
        if _backend_changed:
            # stop_all() is a hard terminate, not the cooperative per-task
            # Cancel -- if something is actually running, ask first rather
            # than silently losing more progress than a normal Cancel
            # would. Declining still saves the new backend above; it just
            # lets the active job finish on its current worker instead of
            # forcing a respawn right now.
            confirm = getattr(self.app, "_confirm_backend_switch", None)
            if not callable(confirm) or confirm(self):
                try:
                    self.app.transcription_service.stop_all()
                except Exception as e:  # noqa: BLE001
                    self.app.log(f"Could not restart the transcription worker: {e}")
                self.app.log(
                    f"Transcription engine changed to {cfg['transcribe_backend']}. "
                    "The new engine will be used on the next transcription."
                )
            else:
                self.app.log(
                    f"Transcription engine changed to {cfg['transcribe_backend']}; "
                    "the current worker keeps running its active job and "
                    "will pick up the new engine once it's free."
                )
        # Refresh the Transcribe-tab engine + model pickers to match what was
        # just saved (backend, model, and/or model folder may have changed).
        _refresh = getattr(self.app, "_refresh_engine_selector", None)
        if callable(_refresh):
            try:
                _refresh()
            except Exception:  # noqa: BLE001
                pass
        _refresh_model = getattr(self.app, "_refresh_model_selector", None)
        if callable(_refresh_model):
            try:
                _refresh_model()
            except Exception:  # noqa: BLE001
                pass
        # Restart the folder watcher when its settings changed.
        if watched_changed:
            restart = getattr(self.app, "_restart_watched_folder", None)
            if callable(restart):
                try:
                    restart()
                except Exception as e:  # noqa: BLE001
                    self.app.log(f"Watched-folder restart failed: {e}")
        self._teardown_mousewheel()
        self.destroy()

    def _teardown_mousewheel(self) -> None:
        """Drop the global mousewheel binds before the dialog is destroyed.

        _bind_mousewheel uses canvas.bind_all (a GLOBAL bind) on <Enter> and
        only releases it on <Leave>. If the dialog is closed while the pointer
        is still over the canvas, <Leave> never fires and the global bind keeps
        pointing at the now-destroyed canvas — a stray callback on every
        subsequent scroll. Both close paths call this first."""
        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        self._teardown_mousewheel()
        self.destroy()

    def _browse_watched_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(parent=self, title="Choose a folder to watch")
        if folder:
            self._watched_folder.set(folder)

    def _open_hardware_wizard(self) -> None:
        """Launch the hardware autodetect wizard.

        The wizard probes CUDA / NPU / DirectML / CPU, persists the
        winning tier to ``%LOCALAPPDATA%\\WhisperTranscriberSuite\\hardware.json``,
        and ``core.transcriber.detect_device`` reads that file on the
        next model load. The dialog is non-modal so the user can keep
        the Advanced window open while it runs.
        """
        try:
            from app.widgets.hardware_wizard import HardwareWizard
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Hardware wizard unavailable: {e}")
            return
        try:
            HardwareWizard(self, app=self.app)
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Hardware wizard failed to launch: {e}")

    def _sync_vad_controls_state(self) -> None:
        """Grey out the three VAD sliders while VAD itself is off.

        Same reasoning as _sync_denoise_level_state: a live control under
        an unchecked toggle reads as "this applies", which is exactly the
        confusion this is trying to avoid. Never raises: it runs from a Tk
        callback, where an exception surfaces as a cryptic background-error
        dialog.
        """
        try:
            on = bool(self._vad_enabled.get())
            state = "normal" if on else "disabled"
            for row_label, scale, echo_label in self._vad_control_rows:
                row_label.configure(state=state)
                scale.state(["!disabled"] if on else ["disabled"])
                echo_label.configure(state=state)
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync VAD controls state", exc_info=True)

    def _apply_noisy_audio_preset(self) -> None:
        """One click for non-studio audio — see core.config.NOISY_AUDIO_PRESET
        for the reasoning behind each value. Deliberately leaves Demucs
        alone (see the button's own help_icon)."""
        preset = NOISY_AUDIO_PRESET
        self._vad_enabled.set(bool(preset["vad_enabled"]))
        self._vad_threshold.set(float(preset["vad_threshold"]))
        self._denoise_enabled.set(bool(preset["denoise_enabled"]))
        self._denoise_level.set(str(preset["denoise_level"]))
        self._hallucination_detect.set(bool(preset["hallucination_detect_enabled"]))
        self._sync_vad_controls_state()
        self._sync_denoise_level_state()
        self.app.log(
            "Applied the noisy-audio preset: VAD threshold raised, denoise "
            "set to 'medium', hallucination flagging on."
        )

    def _sync_denoise_level_state(self) -> None:
        """Grey out the strength picker while denoise is off.

        A live control under an unchecked toggle reads as "this applies",
        which is exactly the confusion the measurement-first design is
        trying to avoid. Never raises: it runs from a Tk callback, where
        an exception surfaces as a cryptic background-error dialog.
        """
        try:
            on = bool(self._denoise_enabled.get())
            self._denoise_level_combo.configure(
                state=("readonly" if on else "disabled")
            )
            self._denoise_level_label.configure(
                state=("normal" if on else "disabled")
            )
        except Exception:  # noqa: BLE001
            logger.debug("Could not sync denoise level state", exc_info=True)

    def _install_ai_model(self) -> None:
        """Download the local LLM model in a background thread.

        ~1 GB Qwen2.5-1.5B-Instruct Q4_K_M; the wizard logs progress
        to ``self.app.log`` so the user can leave the dialog open
        while it runs.
        """
        import threading
        try:
            from core import llm as _llm
        except Exception as e:  # noqa: BLE001
            self.app.log(f"LLM module unavailable: {e}")
            return
        if not _llm.runtime_available():
            self.app.log(_llm.runtime_availability_reason())
            return

        def _worker() -> None:
            try:
                self.app.log_threadsafe("Downloading Qwen2.5-1.5B LLM model (~1 GB)…")
                path = _llm.download_default_model(log=self.app.log_threadsafe)
                self.app.log_threadsafe(f"LLM model ready at {path}")
            except Exception as e:  # noqa: BLE001
                logger.exception("LLM model download failed")
                self.app.log_threadsafe(f"LLM model download failed: {e}")

        from core._threads import safe_thread
        safe_thread(_worker, name="llm-model-download")

    def _download_whisper_cpp_model(self) -> None:
        """Kick off the whisper.cpp model download in a daemon thread.

        The model lives under ``user_cache_dir() / "whisper_cpp" /
        ggml-large-v3-q5_0.bin``. The download is a single HTTPS
        request to the project's HuggingFace mirror (no auth needed).
        We surface progress + final status via the App's log() so the
        user can leave the dialog open while it runs.
        """
        import threading
        try:
            from core.backends import whisper_cpp as _wc
        except Exception as e:  # noqa: BLE001
            self.app.log(f"whisper.cpp backend unavailable: {e}")
            return

        def _worker() -> None:
            try:
                self.app.log_threadsafe("Downloading whisper.cpp model (~1.1 GB)…")
                path = _wc.download_default_model(log=self.app.log_threadsafe)
                self.app.log_threadsafe(f"whisper.cpp model ready at {path}")
            except Exception as e:  # noqa: BLE001
                logger.exception("whisper.cpp model download failed")
                self.app.log_threadsafe(f"whisper.cpp model download failed: {e}")

        from core._threads import safe_thread
        safe_thread(_worker, name="whispercpp-model-download")

    def _prepare_nvidia_asr_model(self) -> None:
        """Install deps + download the NVIDIA Parakeet model ahead of time.

        Mirrors :meth:`_download_whisper_cpp_model`: this backend installs
        transformers/torch/librosa and fetches the model from the Hugging
        Face Hub lazily, on the first ``load()`` call. Running that here, in
        a daemon thread, lets the user pre-fetch everything from Advanced
        settings instead of discovering the wait mid-transcription.
        """
        def _worker() -> None:
            try:
                self.app.log_threadsafe(
                    "Preparing NVIDIA Parakeet (installing transformers/torch/"
                    "librosa, then downloading the model)…"
                )
                from core.backends.nvidia_asr import NvidiaAsrBackend

                backend = NvidiaAsrBackend()
                if backend.load(status_cb=self.app.log_threadsafe):
                    self.app.log_threadsafe("NVIDIA Parakeet is ready.")
                else:
                    self.app.log_threadsafe(
                        f"NVIDIA Parakeet preparation failed: {backend.get_error()}"
                    )
            except Exception as e:  # noqa: BLE001
                logger.exception("NVIDIA Parakeet preparation failed")
                self.app.log_threadsafe(f"NVIDIA Parakeet preparation failed: {e}")

        from core._threads import safe_thread
        safe_thread(_worker, name="nvidia-asr-model-prepare")

    def _test_cloud_key(self) -> None:
        """Validate the pasted Google API key on a DAEMON thread.

        The check is a tiny ``models.list`` HTTPS request — it must
        never block the UI thread, and its result is posted back to the
        Tk main thread via ``app.post_to_main`` before touching the
        result StringVar (off-thread widget writes raise on 3.14).
        """
        key = self._cloud_api_key.get().strip()
        model = self._cloud_model.get().strip() or "gemini-3.5-flash"
        if not key:
            self._cloud_test_result.set("Paste an API key first.")
            return
        self._cloud_test_result.set("Testing key…")

        def _set_result(msg: str) -> None:
            try:
                self._cloud_test_result.set(msg)
            except Exception:  # noqa: BLE001
                pass

        def _worker() -> None:
            try:
                from core.backends.cloud_stt import CloudSttBackend
                backend = CloudSttBackend(
                    config={"cloud_stt_api_key": key, "cloud_stt_model": model}
                )
                backend.load()
                ok, msg = backend.ping_key()
            except Exception as e:  # noqa: BLE001
                ok, msg = False, f"Key check failed: {e}"
            text = ("OK — " if ok else "FAILED — ") + msg
            self.app.post_to_main(lambda: _set_result(text))
            self.app.log_threadsafe(f"Cloud STT key test: {text}")

        from core._threads import safe_thread
        safe_thread(_worker, name="cloud-stt-key-test")

    def _open_billing_console(self) -> None:
        """Open Google's billing console in the default browser."""
        self._open_url("https://console.cloud.google.com/billing")

    def _open_url(self, url: str) -> None:
        """Open ``url`` in the default browser; never raises."""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            self.app.log(f"Could not open link: {e}")

    # -- Google Cloud Speech-to-Text (service-account) handlers -----------

    def _gcloud_path_display(self) -> str:
        """The path text shown next to 'Browse...'.

        Falls back to announcing the build-bundled key so the user can see a
        key is loaded even when they have not picked their own JSON file.
        """
        path = (self._gcloud_credentials.get() or "").strip()
        if path:
            return path
        try:
            from core.backends.availability import bundled_gcloud_key_path

            if bundled_gcloud_key_path():
                return "✓ Using the built-in Google Cloud key (loaded)"
        except Exception:  # noqa: BLE001
            pass
        return "(none selected)"

    def _browse_gcloud_credentials(self) -> None:
        """Pick the downloaded service-account JSON file."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self,
            title="Pick your Google Cloud service-account JSON key file",
            filetypes=[("JSON key file", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._gcloud_credentials.set(path)
            self._gcloud_path_label.config(text=self._gcloud_path_display())

    def _refresh_gcloud_dynamic(self) -> None:
        """Enable/disable the bucket entry based on the batch-mode checkbox."""
        try:
            state = "normal" if self._gcloud_batch_mode.get() else "disabled"
            self._gcloud_bucket_entry.config(state=state)
        except tk.TclError:
            pass

    def _refresh_gcloud_usage(self) -> None:
        """Recompute the live 'minutes used / estimated cost' label.

        Reads the LOCAL monthly counter from config and asks the pure
        formatter (in the backend module) for the display string. The
        formatter resets the shown minutes to 0 when the stored month is
        not the current month (the free tier resets monthly).
        """
        try:
            from core.backends import google_cloud_stt as _g
        except Exception as e:  # noqa: BLE001
            self._gcloud_usage_text.set(f"Usage unavailable: {e}")
            return
        cfg = self.app.app_config
        used = float(cfg.get("gcloud_stt_minutes_used") or 0.0)
        month_stored = str(cfg.get("gcloud_stt_minutes_month") or "")
        cap = int(cfg.get("gcloud_stt_free_minutes_cap") or 60)
        batch = bool(self._gcloud_batch_mode.get())
        text = _g.format_usage(
            used, month_stored, _g.month_marker(), cap, batch
        )
        self._gcloud_usage_text.set(text)

    def _show_gcloud_help(self) -> None:
        """Open a step-by-step help dialog with clickable console links."""
        top = tk.Toplevel(self)
        top.title("How to get a Google Cloud service-account JSON file")
        top.transient(self)
        top.resizable(True, True)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=(
                "Follow these steps once. The links open the exact Google "
                "Cloud console pages (screenshots are not embedded)."
            ),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        for text, url in _GCLOUD_HELP_STEPS:
            row = ttk.Frame(frame)
            row.pack(fill="x", anchor="w", pady=2)
            ttk.Label(
                row, text=text, wraplength=620, justify="left",
            ).pack(anchor="w")
            if url:
                link = ttk.Label(
                    row, text=url, foreground="#1a73e8", cursor="hand2",
                    wraplength=620, justify="left",
                )
                link.pack(anchor="w", padx=(16, 0))
                link.bind("<Button-1>", lambda _e, u=url: self._open_url(u))

        guide = ttk.Label(
            frame,
            text=f"Official guide: {_GCLOUD_OFFICIAL_GUIDE}",
            foreground="#1a73e8",
            cursor="hand2",
            wraplength=620,
            justify="left",
        )
        guide.pack(anchor="w", pady=(12, 0))
        guide.bind(
            "<Button-1>", lambda _e: self._open_url(_GCLOUD_OFFICIAL_GUIDE)
        )

        ttk.Button(frame, text="Close", command=top.destroy).pack(
            anchor="e", pady=(14, 0)
        )
        top.update_idletasks()
        try:
            top.grab_set()
        except tk.TclError:
            pass

    def _test_gcloud_connection(self) -> None:
        """Validate the service account on a DAEMON thread (never blocks UI).

        Steps, all off the Tk thread:
          1. Ensure the google libraries are installed (install on demand
             via core.optional_deps if missing, surfacing an "installing..."
             status).
          2. Build the backend, call load() (validates the JSON + project),
             then build the v2 SpeechClient (proves auth + the credentials
             parse). A clean client build is enough to confirm the account
             without spending a recognise call.

        The result is marshalled back to the Tk main thread via
        ``app.post_to_main`` before touching the result StringVar — never
        touch Tk from the worker thread.
        """
        path = (self._gcloud_credentials.get() or "").strip()
        batch = bool(self._gcloud_batch_mode.get())
        bucket = (self._gcloud_bucket.get() or "").strip()
        using_bundled = False
        if not path:
            from core.backends.google_cloud_stt import bundled_credentials_path
            path = bundled_credentials_path()
            if not path:
                self._gcloud_test_result.set(
                    "Pick your service-account JSON file first (Browse...)."
                )
                return
            using_bundled = True
        self._gcloud_test_result.set(
            "Testing connection (using the build-bundled key)..."
            if using_bundled else "Testing connection..."
        )

        def _set_result(msg: str) -> None:
            try:
                self._gcloud_test_result.set(msg)
            except Exception:  # noqa: BLE001
                pass

        def _status(msg: str) -> None:
            self.app.post_to_main(lambda: _set_result(msg))

        def _worker() -> None:
            try:
                from core import optional_deps
                from core.backends import google_cloud_stt as _g
                if not _g.runtime_available():
                    _status("Installing Google Cloud libraries (one-time)...")
                    ok_install = optional_deps.install(
                        "google_cloud_stt", log_cb=self.app.log_threadsafe
                    )
                    if not ok_install or not _g.runtime_available():
                        _status(
                            "FAILED — could not install the Google Cloud "
                            "libraries. Check your internet connection and "
                            "retry."
                        )
                        return
                config = {
                    "gcloud_stt_credentials_json": path,
                    "gcloud_stt_batch_mode": batch,
                    "gcloud_stt_bucket": bucket,
                    "gcloud_stt_model": (
                        self.app.app_config.get("gcloud_stt_model") or "chirp_2"
                    ),
                    "gcloud_stt_location": (
                        self.app.app_config.get("gcloud_stt_location")
                        or "us-central1"
                    ),
                }
                backend = _g.GoogleCloudSttBackend(config=config)
                if not backend.load():
                    _status("FAILED — " + (backend.get_error() or "unknown error"))
                    return
                # Building the client proves the JSON authenticates and the
                # Speech-to-Text client can initialise (no audio spent).
                try:
                    backend._build_client()  # noqa: SLF001 — intentional probe
                except Exception as e:  # noqa: BLE001
                    _status("FAILED — " + str(e))
                    return
                _status(
                    (
                        "OK — the build-bundled service account works. "
                        if using_bundled else
                        "OK — service account accepted. "
                    )
                    + "The Speech-to-Text client initialised — "
                    "you can transcribe with this backend."
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("Google Cloud STT connection test failed")
                _status(f"FAILED — connection test error: {e}")

        from core._threads import safe_thread
        safe_thread(_worker, name="gcloud-stt-connection-test")
