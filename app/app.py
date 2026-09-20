"""The Tk root. Wires services + dialogs + widgets together."""
from __future__ import annotations

import gc
import logging
import os
import sys
import threading
import time
import tkinter as tk
from queue import Empty, Full, Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import sv_ttk

from app.dialogs.advanced import AdvancedDialog
from app.dialogs.model_download import ModelDownloadDialog
from app.dialogs.transcript_viewer import open_viewer as _open_transcript_viewer
from app.domain.tasks import TranscriptionTask, VideoDownloadTask
from app.observability import init_sentry, send_launch_ping_async
from app.services.download_service import DownloadService
from app.services.format_service import FormatService
from app.services.integrations_service import IntegrationsService
from app.services.transcription_service import (
    HEADLESS_READY_TIMEOUT_S,
    TranscriptionService,
)
from app.dialogs.statistics import show_statistics as _show_stats
from app.widgets.console import apply_console_theme, build_console, insert_log_line
from app.widgets.error_dialog import show_error
from app.widgets.platform import open_folder as _open_folder_helper
from app.widgets.live_tab import build_live_tab, stop_live_session
from app.widgets.voice_clone_tab import build_voice_clone_tab, stop_voice_clone_worker
from app.widgets.tabs import (
    build_download_tab,
    build_queue_tab,
    build_server_tab,
    build_tiling_tab,
    build_transcribe_tab,
)
from app.widgets.tray import TrayController
from core import __version__ as _APP_VERSION
from core._proc import kill_process_tree
from core.config import load_config, save_config
from core.history import HistoryDB
from core.hub import tiling_tab_enabled, voice_clone_tab_enabled
from core.logging_setup import get_ui_logger, open_log_folder, setup_logging
from core.paths import bin_dir as _resource_bin_dir
from core.paths import bundled_binary as _bundled_binary
from core.watcher import FolderWatcher

logger = logging.getLogger(__name__)


def _iids_for_tasks(
    row_map: dict[str, Any], tasks: "list[Any]"
) -> list[str]:
    """Map task objects back to their (new) Treeview iids after a rebuild.

    refresh() rebuilds the tree every tick with fresh iids, wiping the
    selection. Given the freshly-built ``row_map`` (iid -> task) and the
    tasks that were selected before the rebuild, return the iids that now
    hold those same task objects (by identity), preserving tree order and
    dropping any task that has since left the queue. Pure + Tk-free so the
    selection-preservation contract can be unit-tested.
    """
    wanted = {id(t) for t in tasks}
    if not wanted:
        return []
    return [iid for iid, t in row_map.items() if id(t) in wanted]


def _resolve_theme(name: str) -> str:
    if name == "system":
        try:
            import darkdetect  # type: ignore[import-not-found]
            return "dark" if (darkdetect.theme() or "").lower() == "dark" else "light"
        except Exception:  # noqa: BLE001
            return "dark"
    return name if name in ("light", "dark") else "dark"


def _resolve_entry_file() -> str:
    """Where does ``bin/`` live? Frozen exe sits beside it; source uses gui.py."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "gui.py",
    )


def _split_dnd_paths(raw: str) -> list[str]:
    """Split a tkdnd ``<<Drop>>`` payload into individual paths.

    tkdnd packs all dropped items into one string: space-separated
    tokens, with any token that contains a space wrapped in ``{...}``.
    We intentionally do NOT use ``Tk.splitlist`` here: Tcl's list
    parser treats a leading ``\\\\`` as an escaped backslash and
    collapses it to a single one, so a UNC path like
    ``{\\\\server\\share\\my file.mp4}`` comes back as
    ``\\server\\share\\my file.mp4`` — no longer a valid UNC path, and
    the dropped network file is then silently dropped by the later
    ``os.path.isfile`` gate. This brace/space splitter preserves the
    backslashes verbatim so UNC drops survive (local ``C:\\`` and mapped
    ``Z:\\`` paths were never affected, having no leading ``\\\\``).
    """
    raw = raw.strip()
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] == " ":
            i += 1
        if i >= n:
            break
        if raw[i] == "{":
            # Scan for the CLOSING brace of this token. '{' and '}' are legal
            # filename characters, so a naive raw.find('}') split a real file
            # like 'my clip {v2}.mp4' at the inner '}', producing two bogus
            # tokens that both fail the later os.path.isfile gate (the file
            # is then silently not enqueued). Honour brace nesting AND only
            # accept a '}' as the token delimiter when it is followed by
            # end-of-string or a space (i.e. it really ends the token), so
            # embedded literal braces inside a filename survive. Backslashes
            # are NOT treated as escapes here: tkdnd's <<Drop>> payload keeps
            # them literal (UNC paths like \\server\share rely on that).
            j = i + 1
            depth = 1
            close = -1
            while j < n:
                c = raw[j]
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 1 and (j + 1 >= n or raw[j + 1] == " "):
                        # The real end of the brace-wrapped token.
                        close = j
                        break
                    if depth > 1:
                        depth -= 1
                    # else: a depth-1 '}' NOT at a token boundary is a
                    # literal brace inside the filename — leave depth alone
                    # and keep scanning for the true close.
                j += 1
            if close == -1:
                # Unbalanced brace — take the rest as one token.
                out.append(raw[i + 1:])
                break
            out.append(raw[i + 1:close])
            i = close + 1
        else:
            j = i
            while j < n and raw[j] != " ":
                j += 1
            out.append(raw[i:j])
            i = j
    return out


def _file_uri_to_path(uri: str) -> str:
    """Convert a ``file://`` URI to a local filesystem path.

    Handles the common shapes a drop target sees:
    ``file:///C:/dir/clip.mp4`` (Windows), ``file:///home/u/clip.mp4``
    (POSIX), and the UNC form ``file://server/share/clip.mp4``. Returns ""
    when ``uri`` isn't a ``file://`` URI or can't be parsed, so the caller
    can fall through to its unsupported-scheme path.
    """
    if not uri.startswith("file://"):
        return ""
    from urllib.parse import unquote, urlsplit
    from urllib.request import url2pathname
    try:
        parts = urlsplit(uri)
        # A non-empty netloc on file:// is a UNC host (file://server/share);
        # localhost/empty is the ordinary local-file case.
        netloc = parts.netloc
        path = url2pathname(unquote(parts.path))
        if netloc and netloc.lower() != "localhost":
            return r"\\{}{}".format(netloc, path)
        return path
    except Exception:  # noqa: BLE001
        return ""


def _media_files_in_folder(folder: str) -> list[str]:
    """Top-level media files inside a dropped folder (sorted, stable order).

    Only the folder's own files are scanned — deliberately no recursion, so
    dropping e.g. a drive root can't silently enqueue thousands of files.
    Media-ness comes from core.watcher's single extension list. Returns []
    on any listing error (permissions, folder vanished mid-drop).
    """
    from core.watcher import is_media_file

    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out: list[str] = []
    for name in names:
        full = os.path.join(folder, name)
        if os.path.isfile(full) and is_media_file(name):
            out.append(full)
    return out


# --- About dialog content (pure, Tk-free, unit-testable) -------------------
# The About dialog's text and links live in these two module-level helpers so
# they can be unit-tested without ever building a tk.Tk() root. The dialog in
# App._show_about only walks the returned data structures into widgets.

# A section is (title, [(subsection_title, [bullet, ...]), ...]).
AboutSection = tuple[str, list[tuple[str, list[str]]]]


def build_about_sections() -> list[AboutSection]:
    """Return the full, plain-language feature inventory for the About dialog.

    Many capabilities ship enabled-by-default but live behind the Advanced
    dialog or have no surface in the main UI, so this is the canonical
    "what does this app actually do" reference and is intentionally
    exhaustive. Pure data: no Tk, no I/O — safe to call from a test.
    """
    return [
        ("What's new in this version", [
            ("Highlights", [
                "Cloud transcription you can opt into: Google Gemini "
                "(paste one free key) and Google Cloud Speech-to-Text "
                "(service-account file, with a cheaper Batch mode)",
                "Web / LAN access — one click to let a browser on this PC "
                "or another device transcribe, with nothing to install",
                "Per-task buttons on every queue item: Pause, Resume, "
                "Cancel, Re-run, Remove",
                "Video Tiling — a multi-monitor video wall that "
                "auto-reconnects if a stream drops",
                "Built-in update check (opt-in); the installer upgrades "
                "in place over the old version — no need to uninstall first",
            ]),
        ]),
        ("Transcription engine", [
            ("Input", [
                "Any audio or video file ffmpeg can read",
                "Drag-and-drop one or many files onto the window",
                "Browse… (Ctrl+O) for single or multi-select",
                "Recent-files submenu (last 10 from history)",
            ]),
            ("Models", [
                "Whisper Large v3 (default, ~3 GB)",
                "Whisper Large v3 Turbo (~5× faster, ~1.6 GB)",
                "Distil Large v3.5 (fastest English-only, ~1.5 GB)",
                "Picker lives in the Advanced dialog",
            ]),
            ("Backends (pluggable)", [
                "Local Whisper via faster-whisper — the default, fully "
                "offline, nothing leaves your computer",
                "whisper.cpp via pywhispercpp — optional, quantised, "
                "kinder to weak CPUs",
                "NVIDIA Parakeet TDT v3 via transformers — optional, "
                "local, multilingual",
                "Switch in the Advanced dialog under Backend",
            ]),
            ("Cloud transcription (optional, uploads your audio)", [
                "Off by default. These send your audio to Google, so they "
                "break the offline guarantee — only use them on purpose.",
                "Gemini (simple API key): paste one free key from "
                "aistudio.google.com and it just works. Free tier is about "
                "60 minutes a month.",
                "Google Cloud Speech-to-Text (service account): a "
                "purpose-built transcription service with real word "
                "timestamps and speaker labels — the only engine here "
                "that combines all three: real word-level timestamps, "
                "speaker diarization, and a cheap Batch mode for long "
                "files. New accounts get 60 free minutes a month plus a "
                "$300 / 90-day credit.",
                "It needs a service-account JSON file — set it under "
                "Advanced › Backend, where a \"How do I get this file?\" "
                "button walks you through it step by step.",
                "Batch mode (Cloud Speech-to-Text): about 75% cheaper "
                "(~$0.004/minute vs ~$0.016/minute standard) but slower — "
                "usually ready within 24 hours — and needs a Cloud "
                "Storage bucket. Good for large jobs you are not waiting "
                "on.",
            ]),
            ("Hardware", [
                "Autodetect at first launch (CUDA / NPU / DirectML / CPU)",
                "Choice persisted in hardware.json",
                "Manual override in the Advanced dialog",
            ]),
            ("Quality controls", [
                "Voice Activity Detection (Silero VAD), tunable",
                "Word-level timestamps (opt-in)",
                "Optional stable-ts word-alignment refinement",
                "Optional Demucs vocal-separation pre-processing",
            ]),
        ]),
        ("Output formats", [
            ("Files written next to your source", [
                "SubRip — .srt",
                "WebVTT — .vtt",
                "Whisper JSON — .json (segments + word-level data)",
                "Plain text — .txt",
                "Tab-separated — .tsv",
                "LRC lyrics — .lrc",
                "Markdown — .md",
                "Microsoft Word — .docx",
                "PDF — via reportlab",
            ]),
            ("Round-trip", [
                "oTranscribe import (.otr → .srt)",
                "oTranscribe export (.srt → .otr) for manual editing",
                "ELAN import/export (.eaf)",
                "InqScribe import/export (.inqscr / [hh:mm:ss.ff])",
                "Express Scribe export (.txt / [hh:mm:ss]) — export only",
            ]),
            ("Templating", [
                "output_filename_template config key with tokens "
                "{base} {ext} {lang} {date} {speaker_count}",
                "Sibling subdirectories created on the fly",
            ]),
        ]),
        ("Post-processing", [
            ("Per-file extras", [
                "Speaker diarisation (sherpa-onnx, no HF token)",
                "Auto-chapter markers (long-silence heuristic)",
                "Hallucination detector — flags suspect segments "
                "in the viewer (red rows)",
            ]),
            ("Optional local LLM", [
                "Qwen2.5-1.5B-Instruct, download-on-first-use",
                "Summaries, Q&A, AI-generated chapter titles",
                "Off by default; opt in from the Advanced dialog",
            ]),
        ]),
        ("Video download", [
            ("Sources", [
                "Any URL yt-dlp supports (YouTube, Vimeo, …)",
                "Supreme Master TV episode pages "
                "(multi-quality + article text + series parts)",
            ]),
            ("Pipeline options", [
                "Format/quality picker per URL",
                "Audio-only mode (MP3 / m4a / opus)",
                "Subtitle download + burn-in to video",
                "SponsorBlock category skipping",
                "Auto-transcribe after download",
                "Cookies from browser — download login-walled / "
                "age-gated content (Facebook / Instagram / TikTok, "
                "some YouTube Shorts)",
            ]),
        ]),
        ("Video Tiling (video wall)", [
            ("What it does", [
                "Plays one live stream as a full-screen N×N grid",
                "Can spread the wall across several monitors",
                "Auto-reconnects if the stream drops, so the wall "
                "keeps running unattended",
                "Lives on its own \"Video Tiling\" tab",
            ]),
        ]),
        ("Web / LAN access", [
            ("Share transcription from a browser", [
                "One click on the \"Web / LAN access\" tab opens a simple "
                "web page served by this app — no app to install on the "
                "other devices",
                "Loopback by default: only this computer can reach it "
                "(no firewall prompt)",
                "Optional \"Share on local network\" so phones and other "
                "PCs can use it (Windows may ask to allow the firewall — "
                "click Allow)",
                "Optional access password if you want to limit who can use it",
                "Use it only on a network you trust — it is not encrypted",
            ]),
        ]),
        ("Transcript viewer", [
            ("Open via", [
                "Help → Open transcript viewer…",
                "Last-Result card → View transcript",
            ]),
            ("Editing", [
                "Find / replace (Ctrl+F), case-insensitive default",
                "Speaker rename — rewrites every same-labelled segment",
                "Remove fillers — strips uh/um/er… with whole-word regex",
                "Atomic save (Ctrl+S)",
            ]),
            ("Playback", [
                "Embedded VLC when python-vlc + libvlc are installed",
                "Click-to-seek on any segment",
                "Karaoke — active word wrapped in [brackets] as VLC plays",
            ]),
            ("Display", [
                "Word-confidence colour coding "
                "(green ≥ 0.85, amber ≥ 0.6, red below)",
                "Type-as-you-search filter",
            ]),
        ]),
        ("Workflow + system integration", [
            ("Queue", [
                "Multi-file batch with per-file progress",
                "Parallel workers (configurable, default 2)",
                "Right-click any item for Pause, Resume, Cancel, "
                "Re-run, and Remove — per task",
                "Cancel a running job (Esc)",
            ]),
            ("Automation", [
                "Watched folder — auto-enqueue files dropped in",
                "Windows Explorer right-click "
                "\"Transcribe with Whisper Transcriber Suite\" (optional install task)",
                "Per-folder .whisperproject.json overrides",
            ]),
            ("Desktop", [
                "System tray + minimise-to-tray (opt-in)",
                "Native Windows toast on completion + chime",
                "High-DPI scaling",
                "Light / dark / system theme",
            ]),
            ("Reliability", [
                "Crash-auto-resume — re-enqueues interrupted files",
                "Worker subprocess with 5 s heartbeat + 30 s watchdog",
                "history.db opens in WAL mode + integrity check",
                "--safe-mode CLI flag backs up config and re-runs first-run",
            ]),
        ]),
        ("Updates", [
            ("Staying current", [
                "Opt-in check against GitHub for a newer version — it only "
                "tells you; it never downloads or installs on its own",
                "Run it any time from Help → Check for updates…",
                "When you install the newer Setup it upgrades in place over "
                "the old version — you do NOT need to uninstall first",
            ]),
        ]),
        ("Search + statistics", [
            ("History", [
                "Every finished job recorded in SQLite history.db",
                "File → Recent files (last 10)",
                "File → Statistics… — total minutes transcribed, etc.",
            ]),
        ]),
        ("Keyboard shortcuts", [
            ("Global", [
                "Ctrl+O — Browse for files",
                "Ctrl+Enter — Transcribe selected",
                "Esc — Cancel running job",
                "Ctrl+Q — Exit (bypasses minimise-to-tray)",
            ]),
            ("Viewer", [
                "Ctrl+F — Find / replace",
                "Ctrl+S — Save edits",
            ]),
        ]),
        ("Privacy", [
            ("Default", [
                "Everything runs locally; no network call without your action",
                "The cloud backends above are the exception — they upload "
                "audio only when you choose one and start a job",
            ]),
            ("Opt-in telemetry", [
                "Anonymous launch ping (config: telemetry_opt_in)",
                "Sentry crash reporting (env: SENTRY_DSN + opt-in)",
            ]),
        ]),
    ]


def build_about_links() -> list[tuple[str, str]]:
    """Return (label, url) pairs of helpful links for the About dialog.

    Pure data: the dialog binds each to ``webbrowser.open``. The releases
    URL is sourced from ``core.updates`` so it tracks the repo move note
    there (single source of truth for the GitHub coordinates).
    """
    from core.updates import RELEASES_PAGE_URL

    return [
        ("Downloads & new versions (GitHub releases)", RELEASES_PAGE_URL),
        ("Get a free Gemini API key — aistudio.google.com",
         "https://aistudio.google.com/apikey"),
        ("Google Cloud console (service account, billing)",
         "https://console.cloud.google.com"),
        ("Cloud setup guide — Gemini (paste a key)",
         "https://github.com/Milomilo777/whisper-transcriber-suite"
         "/blob/master/docs/CLOUD_STT.md"),
        ("Cloud setup guide — Google Cloud Speech-to-Text",
         "https://github.com/Milomilo777/whisper-transcriber-suite"
         "/blob/master/docs/CLOUD_STT_GOOGLE.md"),
    ]


class App(tk.Tk):
    """The Tk root.

    Many attributes are populated *after* construction by the tab-
    builder functions in :mod:`app.widgets.tabs` (``fv``, ``pb``,
    every ``*_var`` and ``*_combo``, etc.). They live as forward-
    declared annotations on the class so pyright sees them and so
    refactoring tools follow them; the actual assignment still
    happens in the tab builder.
    """

    entry_file: str = _resolve_entry_file()

    # --- forward declarations of attributes assigned after init -----------
    # Transcribe tab
    fv: tk.StringVar
    vad_enabled_var: tk.BooleanVar
    word_timestamps_var: tk.BooleanVar
    # Queue tab
    tree: "ttk.Treeview"
    pb: "ttk.Progressbar"
    row_map: dict[str, Any]
    # R2 per-task action bar (assigned in tabs.build_queue_tab).
    queue_action_buttons: dict[str, "ttk.Button"]
    # Download tab
    download_url_var: tk.StringVar
    download_folder_var: tk.StringVar
    # v1.0.3 — optional time-range slice on the Download tab. Both
    # vars are created by tabs.build_download_tab and are per-job
    # (DownloadService clears them after enqueue, no config save).
    download_start_time_var: tk.StringVar
    download_end_time_var: tk.StringVar
    # Transcribe-tab time-slice (created by tabs.build_transcribe_tab).
    transcribe_start_time_var: tk.StringVar
    transcribe_end_time_var: tk.StringVar
    # Video Tiling tab (created by tabs.build_tiling_tab).
    tiling_url_var: tk.StringVar
    tiling_divisions_var: tk.IntVar
    tiling_status_var: tk.StringVar
    tiling_status_label: "ttk.Label"
    tiling_quality_var: tk.StringVar
    tiling_mute_var: tk.BooleanVar
    tiling_multi_monitor_var: tk.BooleanVar
    tiling_auto_restart_var: tk.BooleanVar
    tiling_monitors_info_var: tk.StringVar
    # Spatial monitor indices (core.monitors) ticked for multi-monitor.
    tiling_selected_monitors: list[int]
    # ffplay auto-download notice + button (only when ffplay is absent and a
    # download URL is configured; see tabs.build_tiling_tab).
    tiling_ffplay_notice: "ttk.Frame"
    tiling_download_ffplay_btn: "ttk.Button"
    # Web / LAN access tab (created by tabs.build_server_tab).
    server_port_var: tk.IntVar
    server_share_lan_var: tk.BooleanVar
    server_token_var: tk.StringVar
    server_https_enabled_var: tk.BooleanVar
    server_webhook_url_var: tk.StringVar
    server_status_var: tk.StringVar
    server_url_var: tk.StringVar
    server_toggle_btn: "ttk.Button"
    server_open_btn: "ttk.Button"
    # Download-tab position sliders (created by tabs.build_download_tab).
    download_start_scale: "ttk.Scale"
    download_end_scale: "ttk.Scale"
    download_duration_var: tk.StringVar
    download_mode_var: tk.StringVar
    download_mode_combo: "ttk.Combobox"
    audio_format_var: tk.StringVar
    audio_format_combo: "ttk.Combobox"
    video_format_var: tk.StringVar
    video_format_combo: "ttk.Combobox"
    output_format_var: tk.StringVar
    output_format_combo: "ttk.Combobox"
    download_subtitles_var: tk.BooleanVar
    subtitle_lang_var: tk.StringVar
    subtitle_lang_combo: "ttk.Combobox"
    subtitle_status_var: tk.StringVar
    auto_transcribe_var: tk.BooleanVar
    # "Use captions instead" shortcut (built in tabs.build_download_tab;
    # shown/hidden by update_caption_shortcut_state based on what the most
    # recent format lookup found — see app.services.format_service).
    caption_shortcut_status_var: tk.StringVar
    caption_shortcut_button: "ttk.Button"
    smtv_download_all_parts_var: tk.BooleanVar
    # Diarization toggle (Transcribe tab)
    diarization_var: tk.BooleanVar
    # Quick-options row on the Transcribe tab
    transcribe_lang_var: tk.StringVar
    device_var: tk.StringVar
    compute_type_var: tk.StringVar
    # Engine picker row on the Transcribe tab (built in tabs.py).
    transcribe_engine_var: tk.StringVar
    engine_status_var: tk.StringVar
    engine_status_label: "ttk.Label"
    # Model picker row on the Transcribe tab (built in tabs.py).
    transcribe_model_var: tk.StringVar
    _transcribe_model_label_to_slug: "dict[str, str]"
    model_status_var: tk.StringVar
    model_status_label: "ttk.Label"
    # R3: GPU/CPU device badge. The text var is set in update_model_state();
    # the two Labels (Transcribe-tab header + Queue-tab status line) are built
    # in tabs.py and registered here so apply_device_badge can recolour them.
    device_badge_var: tk.StringVar
    device_badge_labels: "list[ttk.Label]"
    device_badge_tip: str
    hotwords_var: tk.StringVar
    format_status_var: tk.StringVar
    # The real yt-dlp/SMTV failure reason from the most recent format
    # lookup, or "" when the lookup succeeded (or hasn't run yet). Lets
    # enqueue_from_form show the user WHY a URL has no formats instead of
    # a generic "wait for formats to load" that's misleading when the
    # lookup already failed and never will load. Set in format_service.
    format_lookup_error: str
    download_tree: "ttk.Treeview"
    download_row_map: dict[str, Any]
    # R2 per-download action bar (assigned in tabs.build_download_tab).
    download_action_buttons: dict[str, "ttk.Button"]
    # Set by format_service.lookup_formats / _apply_smtv_formats
    _smtv_episode: Any | None
    # Set by tabs.build_download_tab — toggles the series checkbox.
    # Signature: (visible: bool) -> None
    _smtv_series_toggle: Any
    # Console widget (built by app.widgets.console.build_console)
    txt: "tk.Text"
    # Optional history DB; None when SQLite init fails
    history: "HistoryDB | None"
    # Last-result card on the Transcribe tab
    last_result_frame: "ttk.LabelFrame"
    last_result_empty_var: tk.StringVar
    last_result_empty_label: "ttk.Label"
    last_result_body: "ttk.Frame"
    last_result_title_var: tk.StringVar
    last_result_files_frame: "ttk.Frame"
    # Queue-tab empty-state placeholder
    queue_empty_var: tk.StringVar
    queue_empty_label: "ttk.Label"
    # Whether to chime the system bell when a job finishes (View menu)
    chime_on_complete_var: tk.BooleanVar
    # Recent-files submenu rebuilt every time it opens
    _recent_menu: tk.Menu
    # System tray + watched-folder controllers (created lazily)
    tray: "TrayController | None"
    _folder_watcher: "FolderWatcher | None"
    # When True, on_exit treats Tk close as a true exit even when
    # minimise_to_tray is on (set by TrayController._exit_app).
    _exit_from_tray: bool

    def __init__(self) -> None:
        super().__init__()
        # Window-title base carries the version so the user can always see
        # which build is running (title bar / taskbar / Alt-Tab).
        self._base_title = f"Whisper Transcriber Suite v{_APP_VERSION}"
        self.title(self._base_title)
        # Make any on-demand-installed optional packages importable so
        # feature-availability checks (e.g. stable-ts alignment) see them.
        try:
            from core.optional_deps import activate as _activate_extras
            _activate_extras()
        except Exception:  # noqa: BLE001
            pass
        self._install_icon()
        # High-DPI scaling: pick up the system DPI so fonts and
        # paddings don't shrink to dollhouse size on 150 % displays.
        self._apply_hidpi_scaling()
        # Restore the user's saved window geometry if any; falls back
        # to a sensible default. _save_window_geometry persists it on
        # the WM_DELETE_WINDOW exit path.
        saved_geom = load_config().get("window_geometry") or ""
        if isinstance(saved_geom, str) and saved_geom.count("x") == 1:
            try:
                self.geometry(saved_geom)
            except Exception:  # noqa: BLE001
                self.geometry("960x640")
        else:
            self.geometry("960x640")
        # Nothing previously stopped the user (or a stale saved
        # window_geometry from an older, less-crowded layout) from
        # shrinking the window below the size every tab's layout is
        # actually laid out for — pack(side="left") rows don't wrap,
        # they silently clip. 960x640 is the app's own chosen default,
        # not an arbitrary number; this only stops shrinking below it,
        # growing is unaffected.
        self.minsize(960, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

        # Per-instance queues (no more module-globals — AUDIT B3 fix).
        self.queue: list[TranscriptionTask] = []
        self.download_queue: list[VideoDownloadTask] = []
        self.download_current: VideoDownloadTask | None = None

        self.status_var = tk.StringVar(value="Initializing...")
        # R3: device badge state created up-front so a worker "ready" event
        # firing before the tabs are built can't AttributeError. The Labels
        # register themselves in tabs.py; apply_device_badge recolours them.
        self.device_badge_var = tk.StringVar(value="")
        self.device_badge_labels: list[ttk.Label] = []
        self.device_badge_tip = ""
        self.model_ready = False
        self.model_loading = False
        self.model_setup_running = False
        self.workers: list[dict[str, Any]] = []
        # Audit A13: bound the inter-thread event queues. 2000 is
        # well above normal traffic (~1-5 events/s per worker) but
        # caps memory in catastrophic cases (Tk frozen, thousands
        # of files dropped into the watcher at once). Producers
        # block on Full rather than OOM the process — easier to
        # diagnose.
        self.worker_events: Queue = Queue(maxsize=2000)
        self.worker_ready = False
        self.app_config = load_config()
        setup_logging(self.app_config.get("log_level", "INFO"))
        init_sentry()
        send_launch_ping_async()
        self._ui_logger = get_ui_logger()
        logger.info("App startup; theme=%s", self.app_config.get("theme", "dark"))
        self.theme_var = tk.StringVar(value=self.app_config.get("theme", "light"))
        sv_ttk.set_theme(_resolve_theme(self.theme_var.get()))
        self.parallel_workers = max(1, int(self.app_config.get("parallel_workers", 2)))
        self.next_worker_id = 1
        self.format_events: Queue = Queue(maxsize=2000)
        self.download_events: Queue = Queue(maxsize=2000)
        self.audio_format_map: dict[str, dict[str, Any]] = {}
        self.video_format_map: dict[str, dict[str, Any]] = {}
        self.current_video_title = ""
        self.current_video_language = ""
        # code -> "manual" / "auto"; set by format_service after each
        # lookup, read by update_caption_shortcut_state.
        self.current_video_caption_langs: dict[str, str] = {}
        self.format_lookup_after: str | None = None

        # Services
        self.format_service = FormatService(self)
        self.download_service = DownloadService(self)
        self.transcription_service = TranscriptionService(self)
        from core.tiling import TilingController
        self.tiling = TilingController()
        self.integrations_service = IntegrationsService(self)
        # Optional in-process web / LAN server (built lazily on first
        # Start so importing core.server — and its model load — is paid
        # only when the user actually turns it on). None = never started.
        self._server_handle: Any = None
        # True while a start/stop worker thread is in flight, so the
        # toggle button can't be double-fired into a half-built state.
        self._server_busy = False

        # SQLite history (Phase 3a). Mark any pre-crash row as interrupted on launch.
        try:
            self.history = HistoryDB()
            interrupted = self.history.mark_interrupted()
            if interrupted:
                logger.info("Marked %d running rows as interrupted on launch", interrupted)
        except Exception as e:  # noqa: BLE001
            logger.warning("history.db unavailable: %s", e)
            self.history = None

        self._build_menu()
        self._build_tabs()
        self.txt = build_console(self, theme=_resolve_theme(self.theme_var.get()))

        # Wire global keyboard shortcuts now that the widgets exist:
        #   Ctrl+O          → Browse for a file to transcribe
        #   Ctrl+Enter      → Start transcribing whatever is in the
        #                     file picker
        #   Esc             → Cancel the currently-running task
        #   Ctrl+Q          → Quit (same as File → Exit)
        self.bind("<Control-o>", lambda _e: self.browse())
        self.bind("<Control-O>", lambda _e: self.browse())
        self.bind("<Control-Return>", lambda _e: self.add())
        self.bind("<Escape>", lambda _e: self._cancel_running())
        # Ctrl+Q always exits — same convention as File→Exit.
        self.bind("<Control-q>", lambda _e: self._force_exit())
        self.bind("<Control-Q>", lambda _e: self._force_exit())

        # Opt-in drag-and-drop on the main window. tkinterdnd2 is in
        # requirements.txt but the desktop app stays usable even if
        # the import fails — we just log and skip.
        self._install_drag_drop()

        # System tray + watched folder. Both are best-effort: missing
        # dependencies (pystray / Pillow / watchdog) silently disable
        # the feature rather than blocking app startup.
        self.tray = None
        self._folder_watcher = None
        self._exit_from_tray = False
        # Flag flipped to True at the top of on_exit so watcher
        # callbacks / stability-check ticks short-circuit before
        # touching destroyed widgets. Keep watched_after_ids so
        # each path only schedules ONE stability-check ladder.
        self._closing = False
        self._watched_after_ids: dict[str, str] = {}
        # Thread-safe queue drained on the Tk main thread by
        # _drain_watched_paths. watchdog fires callbacks from a
        # background thread; on Python 3.14 calling self.after()
        # from a non-main thread raises RuntimeError. Routing
        # through this queue lets us bounce safely.
        #
        # Sibling queue: _main_thread_calls (below) — same idea, but
        # for arbitrary callables coming from ANY background thread
        # (burn-subs worker, hardware-wizard benchmark, tray clicks).
        # _watched_path_queue is filesystem-watcher → main thread;
        # _main_thread_calls is any-thread → main thread.
        self._watched_path_queue: Queue = Queue(maxsize=2000)
        # Background threads (burn-subs worker, hardware-wizard benchmark,
        # tray clicks, …) can't call self.after() directly on Python 3.14
        # (RuntimeError; undefined on earlier 3.x). They push callables
        # here; _drain_main_calls() runs them on the Tk main thread.
        self._main_thread_calls: Queue = Queue(maxsize=2000)
        self._install_tray()
        self._install_clipboard_keys()
        self._install_text_context_menu()
        self._restart_watched_folder()
        self.after(250, self._drain_watched_paths)
        self.after(50, self._drain_main_calls)

        # Auto-resume after crash: history.mark_interrupted() above
        # flipped rows from running → interrupted. If any of those
        # files still exist on disk, offer to re-enqueue them.
        self.after(700, self._maybe_offer_crash_resume)

        # Bound the partials/ dir: sweep orphaned resume slices + aged-out
        # checkpoints so a killed/declined run doesn't accumulate forever.
        self.after(1500, self._sweep_partials_at_startup)

        self.after(100, self._on_start)
        self.after(300, self.loop)

        # Optional, opt-in GitHub update check. Fired ~4 s after launch
        # so it never competes with first-paint / model-setup work. The
        # check runs on a daemon thread; it is gated by
        # update_check_enabled AND a once-per-day throttle, and it stays
        # SILENT unless an update is actually available (no nagging when
        # up to date, offline, or on a private repo). See
        # _run_update_check / core.updates.
        self.after(4000, self._maybe_quiet_update_check)

    def _sweep_partials_at_startup(self) -> None:
        """Off-thread best-effort cleanup of the partials/ checkpoint dir."""
        import threading as _t

        def _work() -> None:
            try:
                from core import _checkpoint
                removed = _checkpoint.sweep_partials()
                if removed:
                    logger.info(
                        "Startup sweep removed %d stale partial file(s).", removed
                    )
            except Exception:  # noqa: BLE001
                logger.debug("partials sweep failed", exc_info=True)

        _t.Thread(target=_work, name="partials-sweep", daemon=True).start()

    # Bootstrap ---------------------------------------------------------------
    def _on_start(self) -> None:
        # First-run Hub Folder picker.
        #
        # v1.0.3 — lazy model load.
        # We used to call ``transcription_service.start_standby()`` here
        # (and in the hub-setup callbacks) so the Whisper model was
        # already in RAM when the user clicked Transcribe. That cost
        # ~1.5 GB of idle memory + a CPU spike on EVERY launch, even
        # for sessions where the user never transcribed (e.g. opened
        # the app just to browse history or download a video).
        #
        # The worker now spawns on the first transcribe request via
        # ``TranscriptionService.ensure_worker_ready``, which shows a
        # short modal "Loading Whisper model…" dialog. Do NOT re-add
        # the standby calls here — the trade-off is intentional.
        #
        # The hub-setup dialog still fires on first launch so the user
        # picks where models live; we just don't preload the model.
        from core import hub as _hub

        if _hub.is_hub_configured(self.app_config):
            return

        try:
            from app.dialogs.hub_setup import ensure_hub_configured

            def _hub_picked(path: str) -> None:
                self.log(f"Model hub folder set to: {path}")
                try:
                    self.app_config = load_config()
                except Exception:  # noqa: BLE001
                    pass

            ensure_hub_configured(
                self, self.app_config,
                on_done=_hub_picked,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Hub setup dialog failed: %s", e)

    # Menu --------------------------------------------------------------------
    def _build_menu(self) -> None:
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Browse...                          Ctrl+O", command=self.browse)
        # Recent files submenu — populated from history.db at menu-open
        # time so it always reflects the latest run. Skips when history
        # is None (SQLite init failed) and shows a single disabled
        # "(no recent files)" placeholder.
        self._recent_menu = tk.Menu(f, tearoff=0, postcommand=self._populate_recent_menu)
        f.add_cascade(label="Recent files", menu=self._recent_menu)
        f.add_separator()
        f.add_command(label="Convert transcript...", command=self.convert_transcript)
        f.add_separator()
        f.add_command(label="Statistics...", command=self.show_statistics)
        f.add_separator()
        # File→Exit bypasses the minimise-to-tray redirect. When the
        # user explicitly clicks Exit they mean exit; the redirect is
        # only for the window-close (X) button.
        f.add_command(label="Exit                                  Ctrl+Q",
                      command=self._force_exit)

        v = tk.Menu(m, tearoff=0)
        for label, value in (("Light", "light"), ("Dark", "dark"), ("System", "system")):
            v.add_radiobutton(label=label, value=value, variable=self.theme_var, command=self.apply_theme)
        v.add_separator()
        # Audible-cue toggle. Stored in app_config so the user's choice
        # survives a restart. Default ON — first-time users want to
        # know when a long job completes.
        self.chime_on_complete_var = tk.BooleanVar(
            value=bool(self.app_config.get("chime_on_complete", True))
        )
        v.add_checkbutton(
            label="Chime on completion",
            variable=self.chime_on_complete_var,
            command=self._save_chime_pref,
        )

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Open transcript viewer...", command=self._open_transcript_viewer_picker)
        h.add_command(label="Search transcripts...", command=self._open_search_dialog)
        h.add_separator()
        # oTranscribe round-trip — used to be a button on the Transcribe
        # tab; moved here in the UI simplification pass because it's a
        # secondary workflow (most users never touch it), and consumer
        # transcription apps (MacWhisper, Buzz, Aiko) keep
        # secondary imports under a menu.
        h.add_command(
            label="Import oTranscribe (.otr) → SRT...",
            command=self.integrations_service.import_otr_to_srt,
        )
        h.add_command(label="Open oTranscribe website...",
                      command=self.integrations_service.open_otranscribe)
        h.add_separator()
        h.add_command(label="Open log folder", command=self.open_log_folder)
        h.add_separator()
        # Manual update check — always runs (ignores the once-per-day
        # throttle the quiet launch check obeys) and DOES report the
        # "you're up to date" / "couldn't reach the server" cases, unlike
        # the silent launch check. Never downloads/installs anything.
        h.add_command(label="Check for updates...",
                      command=self._check_for_updates_manual)
        m.add_cascade(label="File", menu=f)
        m.add_cascade(label="View", menu=v)
        m.add_cascade(label="Help", menu=h)
        # Direct menubar command — clicking "About" opens the dialog in
        # one click. (It used to be a cascade whose only item was
        # another "About", so the user had to click About twice.)
        m.add_command(label="About", command=self._show_about)
        self.config(menu=m)

    def _populate_recent_menu(self) -> None:
        """Re-populate the File > Recent files submenu from history.db.

        Called automatically by Tk every time the user opens the
        submenu (via the ``postcommand`` hook), so the list is always
        current. We list the last 10 file_paths from the history.db
        transcriptions table; an "Open file" click sets fv + selects
        the Transcribe tab without auto-enqueueing.
        """
        menu = self._recent_menu
        menu.delete(0, "end")
        history = getattr(self, "history", None)
        rows: list[dict[str, Any]] = []
        if history is not None:
            try:
                rows = history.list_transcriptions(limit=10) or []
            except Exception:  # noqa: BLE001
                rows = []
        # Paths the user cleared via "Clear list" are hidden until a new
        # transcription re-adds them. Stored in config.json (the storage
        # this app manages) because HistoryDB has no clear method.
        dismissed: set[str] = set(self.app_config.get("recent_files_dismissed") or [])
        if not rows:
            menu.add_command(label="(no recent files)", state="disabled")
            return
        seen: set[str] = set()
        added = 0
        for row in rows:
            path = row.get("file_path") if isinstance(row, dict) else None
            if not path or path in seen or path in dismissed:
                continue
            seen.add(path)
            label = f"{os.path.basename(path)}  —  {os.path.dirname(path)[:48]}"
            menu.add_command(
                label=label,
                command=lambda p=path: self._open_recent(p),
            )
            added += 1
            if added >= 10:
                break
        if added == 0:
            # Every history row is currently dismissed (the user clicked
            # "Clear list"); show the empty placeholder instead of a lone
            # "Clear list" that has nothing to clear.
            menu.add_command(label="(no recent files)", state="disabled")
            return
        menu.add_separator()
        menu.add_command(label="Clear list", command=self._clear_recent)

    def _burn_subs_for(self, task: TranscriptionTask) -> None:
        """Burn the SRT next to the task's source media into a new MP4.

        Runs ffmpeg in a daemon thread so the UI stays responsive
        on long videos. On completion, surfaces a log line + chimes
        + opens the output folder. Failure logs via messagebox.
        """
        import threading
        from core import burn_subs

        base, _ = os.path.splitext(task.file_path)
        srt_path = base + ".srt"
        if not os.path.isfile(srt_path):
            messagebox.showwarning(
                "No SRT found",
                f"Expected SRT not found next to source:\n{srt_path}",
                parent=self,
            )
            return
        # Suggest "<base>-subbed.mp4" so the source is never clobbered.
        suggested = base + "-subbed.mp4"
        out_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save burned-in video as...",
            initialfile=os.path.basename(suggested),
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if not out_path:
            return

        self.log(f"Burning subtitles into {os.path.basename(out_path)}...")

        def worker() -> None:
            try:
                burn_subs.burn(task.file_path, srt_path, out_path)
                # Tk methods touched from a thread → route via the
                # main-thread queue (self.after(0, ...) from a worker
                # raises RuntimeError on Python 3.14).
                self.post_to_main(lambda: self._burn_subs_done(out_path))
            except Exception as e:  # noqa: BLE001
                # Audit B3: log the stack trace before the lossy
                # UI string-conversion so postmortem diagnosis is
                # possible from logs alone.
                logger.exception(
                    "burn_subs.burn failed: file=%s out=%s",
                    task.file_path, out_path,
                )
                msg = str(e)
                self.post_to_main(lambda: self._burn_subs_failed(msg))

        from core._threads import safe_thread
        safe_thread(worker, name="burn-subs")

    def _burn_subs_done(self, out_path: str) -> None:
        self.log(f"✓ Burned subtitles → {out_path}")
        if getattr(self, "chime_on_complete_var", None) is not None:
            try:
                if self.chime_on_complete_var.get():
                    self.bell()
            except Exception:  # noqa: BLE001
                pass
        self._open_folder(os.path.dirname(out_path) or ".")

    def _burn_subs_failed(self, msg: str) -> None:
        self.log(f"Burn-subs failed: {msg}")
        messagebox.showerror("Burn subtitles failed", msg, parent=self)

    def _open_transcript_viewer_picker(self) -> None:
        """Open the transcript viewer with a file picker."""
        _open_transcript_viewer(self, None)

    def _open_search_dialog(self) -> None:
        """Open the full-text search dialog over every saved transcript."""
        from app.dialogs.search_dialog import open_search_dialog
        open_search_dialog(self)

    def open_transcript_viewer_for(
        self, file_path: str, json_path: str | None = None
    ) -> None:
        """Open the viewer for the transcript JSON belonging to a task.

        Used by the Last Result card's and queue menu's "View transcript"
        button so the user is one click away from the just-finished output.

        Prefer the ACTUAL .json the worker reported writing (``json_path``,
        usually pulled from ``task.output_paths``): the basename can differ
        from the source media when the output was templated or relocated, so
        recomputing ``splitext(file_path)[0] + '.json'`` would miss it and
        pop a confusing file picker even though a real transcript exists.
        Only when no known JSON is on disk do we fall back to recomputing the
        beside-input name, and finally to the picker.
        """
        if json_path and os.path.isfile(json_path):
            _open_transcript_viewer(self, json_path)
            return
        base, _ = os.path.splitext(file_path)
        guessed = base + ".json"
        if os.path.isfile(guessed):
            _open_transcript_viewer(self, guessed)
        else:
            _open_transcript_viewer(self, None)

    @staticmethod
    def _task_json_output(task: Any) -> str | None:
        """Return the .json path the task actually wrote, if known.

        Reads ``task.output_paths`` (the exact files the worker reported)
        and returns the first .json entry — the source of truth for the
        viewer, robust to templated/relocated output names.
        """
        for p in getattr(task, "output_paths", None) or ():
            if isinstance(p, str) and p.lower().endswith(".json"):
                return p
        return None

    def _open_recent(self, path: str) -> None:
        if not os.path.isfile(path):
            messagebox.showwarning(
                "File missing",
                f"That file is no longer at:\n{path}",
                parent=self,
            )
            return
        self.fv.set(path)
        self.nb.select(self.t1)

    def _clear_recent(self) -> None:
        """Clear the File > Recent files list.

        HistoryDB has no clear method (and core/history.py is owned
        elsewhere), so instead of deleting history rows we hide the
        currently-listed paths via a dismissed-set persisted in config.json
        — the storage this app already manages. _populate_recent_menu
        filters these out, so the submenu shows "(no recent files)" until
        new transcriptions arrive. This is a true clear of the *list* the
        user sees, without touching the underlying history DB.
        """
        history = getattr(self, "history", None)
        # Snapshot whatever the menu would currently show and add it to the
        # dismissed set. New transcriptions (paths not in the set) reappear.
        paths: list[str] = []
        if history is not None:
            try:
                rows = history.list_transcriptions(limit=10) or []
            except Exception:  # noqa: BLE001
                rows = []
            for row in rows:
                p = row.get("file_path") if isinstance(row, dict) else None
                if isinstance(p, str) and p:
                    paths.append(p)
        dismissed = set(self.app_config.get("recent_files_dismissed") or [])
        dismissed.update(paths)
        self.app_config["recent_files_dismissed"] = sorted(dismissed)
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to persist cleared recent-files list")
            self.log(f"Could not save cleared recent list: {e}")

    def _save_chime_pref(self) -> None:
        self.app_config["chime_on_complete"] = bool(self.chime_on_complete_var.get())
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save chime preference")
            self.log(f"Could not save preference: {e}")

    def _show_about(self) -> None:
        """A full feature inventory in a scrollable Toplevel.

        Many capabilities ship enabled-by-default but live behind
        the Advanced dialog or have no surface in the main UI; this
        dialog is the canonical "what does this app actually do"
        reference and is intentionally exhaustive.
        """
        dlg = tk.Toplevel(self)
        dlg.title("About Whisper Transcriber Suite")
        dlg.transient(self)
        dlg.geometry("680x620")
        dlg.minsize(560, 480)

        header = ttk.Frame(dlg, padding=(16, 14, 16, 8))
        header.pack(fill="x")
        from core import __version__ as _app_ver
        ttk.Label(
            header,
            text=f"Whisper Transcriber Suite — v{_app_ver}",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "A local, offline Windows desktop app that turns audio "
                "and video into subtitles. Powered by OpenAI Whisper "
                "via faster-whisper. No cloud, no API key, no upload."
            ),
            wraplength=640,
            justify="left",
            foreground="#666",
        ).pack(anchor="w", pady=(4, 0))

        body_frame = ttk.Frame(dlg, padding=(16, 4, 16, 8))
        body_frame.pack(fill="both", expand=True)
        text = tk.Text(
            body_frame, wrap="word", borderwidth=0, highlightthickness=0,
            font=("TkDefaultFont", 9), padx=4, pady=4,
        )
        scroll = ttk.Scrollbar(body_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        text.tag_configure(
            "section", font=("TkDefaultFont", 10, "bold"),
            spacing1=8, spacing3=2,
        )
        text.tag_configure(
            "subsection", font=("TkDefaultFont", 9, "bold"),
            lmargin1=14, lmargin2=14, spacing1=4,
        )
        text.tag_configure(
            "bullet", lmargin1=28, lmargin2=42, spacing1=1, spacing3=1,
        )

        sections = build_about_sections()

        for section_title, subsections in sections:
            text.insert("end", section_title + "\n", "section")
            for sub_title, bullets in subsections:
                text.insert("end", sub_title + "\n", "subsection")
                for line in bullets:
                    text.insert("end", "• " + line + "\n", "bullet")

        # Helpful links — each rendered as a clickable, underlined row that
        # opens in the default browser. A per-link Text tag carries the URL
        # so one bound handler can serve them all.
        import webbrowser

        text.tag_configure(
            "link", foreground="#1a6fb5", underline=True,
            lmargin1=28, lmargin2=42, spacing1=1, spacing3=1,
        )
        text.insert("end", "Helpful links\n", "section")
        for idx, (label, url) in enumerate(build_about_links()):
            tag = f"link-{idx}"
            text.tag_configure(tag)

            def _open(_e: object, _u: str = url) -> None:
                webbrowser.open(_u)

            text.tag_bind(tag, "<Button-1>", _open)
            text.tag_bind(
                tag, "<Enter>",
                lambda _e: text.configure(cursor="hand2"),
            )
            text.tag_bind(
                tag, "<Leave>",
                lambda _e: text.configure(cursor=""),
            )
            text.insert("end", "• " + label + "\n", ("link", tag))

        text.configure(state="disabled")

        footer = ttk.Frame(dlg, padding=(16, 4, 16, 14))
        footer.pack(fill="x")
        ttk.Button(footer, text="OK", command=dlg.destroy).pack(side="right")
        # Author credit — the project was written by translation-robot.
        credit = ttk.Label(
            footer,
            text="Created by translation-robot — github.com/translation-robot",
            foreground="#1a6fb5", cursor="hand2",
        )
        credit.pack(side="left")

        def _open_author(_e: object) -> None:
            import webbrowser
            webbrowser.open("https://github.com/translation-robot")

        credit.bind("<Button-1>", _open_author)

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        try:
            dlg.grab_set()
        except tk.TclError:
            pass

    def show_statistics(self) -> None:
        _show_stats(self)

    def convert_transcript(self) -> None:
        """File → Convert transcript: parse a transcript file and re-emit it
        in another text format, written beside the input.

        Keeps the UI minimal: an open dialog for the source, a small themed
        format chooser, then a synchronous write (parsing a subtitle file is
        instant — no worker thread needed). All errors surface in a messagebox;
        nothing here can raise out of the Tk event loop.
        """
        from core import convert as _convert

        in_path = filedialog.askopenfilename(
            parent=self,
            title="Convert transcript — pick the source file",
            filetypes=[
                ("Transcripts", "*.json *.srt *.vtt *.tsv *.otr *.eaf *.inqscr *.txt"),
                ("SubRip", "*.srt"),
                ("WebVTT", "*.vtt"),
                ("TSV", "*.tsv"),
                ("Whisper JSON", "*.json"),
                ("oTranscribe", "*.otr"),
                ("ELAN", "*.eaf"),
                ("InqScribe", "*.inqscr *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not in_path:
            return

        fmt = self._ask_convert_format(in_path)
        if not fmt:
            return

        try:
            out_path = _convert.convert_file(in_path, fmt)
        except _convert.ConvertError as e:
            messagebox.showerror("Convert transcript", str(e), parent=self)
            return
        except OSError as e:
            messagebox.showerror(
                "Convert transcript",
                f"Could not write the output file: {e}",
                parent=self,
            )
            return

        self.log(f"Converted {os.path.basename(in_path)} -> {out_path}")
        if messagebox.askyesno(
            "Convert transcript",
            f"Wrote:\n{out_path}\n\nOpen its folder?",
            parent=self,
        ):
            try:
                _open_folder_helper(os.path.dirname(out_path) or ".")
            except Exception as e:  # noqa: BLE001
                self.log(f"Could not open output folder: {e}")

    # Shown first in the Convert-transcript format picker, ahead of the
    # rest of core.convert.CONVERT_TARGETS (alphabetical) — these four are
    # what almost every user actually wants; burying them alphabetically
    # among internal-registry names like "elan" / "smtv_docx" made the
    # common case require scrolling/hunting (UX pass, 2026-07-04).
    _COMMON_CONVERT_FORMATS = ("srt", "vtt", "txt", "json")

    def _ask_convert_format(self, in_path: str) -> str | None:
        """Small themed modal: pick the target format. Returns it or None.

        Defaults to ``srt`` unless the source already is ``.srt`` (then
        ``json``), so the common one-click case never re-emits the same format.

        The combobox shows "name (.ext)" rather than the bare registry key
        (e.g. "elan (.eaf)", "smtv_docx (.docx)") since the on-disk extension
        often differs from the internal name and users otherwise have no way
        to tell what file they're about to get.
        """
        from core import convert as _convert

        src_ext = os.path.splitext(in_path)[1].lower().lstrip(".")
        all_targets = list(_convert.CONVERT_TARGETS)
        ordered = [f for f in self._COMMON_CONVERT_FORMATS if f in all_targets]
        ordered += sorted(f for f in all_targets if f not in ordered)
        labels = {f: f"{f} (.{_convert.output_extension_for(f)})" for f in ordered}
        label_to_fmt = {v: k for k, v in labels.items()}
        choices = [labels[f] for f in ordered]

        default = "json" if src_ext == "srt" else "srt"
        if default not in ordered:
            default = ordered[0]

        dlg = tk.Toplevel(self)
        dlg.title("Convert transcript")
        dlg.transient(self)
        dlg.resizable(False, False)
        result: dict[str, str | None] = {"fmt": None}

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body, text=f"Source: {os.path.basename(in_path)}",
            foreground="#888",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text="Convert to format:").pack(anchor="w")
        fmt_var = tk.StringVar(value=labels[default])
        ttk.Combobox(
            body, textvariable=fmt_var, state="readonly",
            values=choices, width=22,
        ).pack(anchor="w", pady=(4, 12))

        def _ok() -> None:
            result["fmt"] = label_to_fmt.get(fmt_var.get(), fmt_var.get())
            dlg.destroy()

        def _cancel() -> None:
            result["fmt"] = None
            dlg.destroy()

        btns = ttk.Frame(body)
        btns.pack(fill="x")
        ttk.Button(btns, text="Convert", command=_ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=_cancel).pack(
            side="right", padx=(0, 8)
        )
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        dlg.bind("<Return>", lambda _e: _ok())
        dlg.bind("<Escape>", lambda _e: _cancel())
        dlg.grab_set()
        self.wait_window(dlg)
        return result["fmt"]

    def open_log_folder(self) -> None:
        path = open_log_folder()
        logger.info("Opened log folder: %s", path)

    def apply_theme(self) -> None:
        name = self.theme_var.get()
        resolved = _resolve_theme(name)
        sv_ttk.set_theme(resolved)
        if hasattr(self, "txt") and self.txt is not None:
            apply_console_theme(self.txt, resolved)
        self.app_config["theme"] = name
        # Guard the save like every other pref handler (Audit B1 / FB-01): a
        # disk/permissions failure inside this Tk callback must not raise out
        # of the event loop — log it and tell the user, don't crash silently.
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save theme preference")
            self.log(f"Could not save theme setting: {e}")

    def _force_exit(self) -> None:
        """Bypass the minimise-to-tray redirect and exit immediately.

        Called by File → Exit, Ctrl+Q, and the tray menu's Exit item.
        The window's X button (WM_DELETE_WINDOW) continues to honour
        the minimise-to-tray preference.
        """
        self._exit_from_tray = True
        self.on_exit()

    def on_exit(self) -> None:
        # Optional minimise-to-tray: when the user has enabled tray
        # support in the Advanced dialog and the tray icon is running,
        # the window's close (X) button hides the window instead of
        # tearing down. File → Exit / Ctrl+Q route through
        # _force_exit() which sets _exit_from_tray=True so they
        # always exit regardless of the preference.
        if (
            not self._exit_from_tray
            and bool(self.app_config.get("minimise_to_tray", False))
            and self.tray is not None
            and self.tray.is_supported()
        ):
            try:
                self.withdraw()
                self.log("Window minimised to tray. Right-click the tray icon to exit.")
            except Exception:  # noqa: BLE001
                pass
            return

        active = [t for t in self.queue if t.status not in ("finished", "cancelled", "error")]
        active_downloads = [
            t for t in self.download_queue if t.status not in ("finished", "cancelled", "error")
        ]
        if active or active_downloads:
            if not messagebox.askyesno(
                "Exit with queued tasks",
                "There are queued or running tasks. Exit anyway?",
                parent=self,
            ):
                # Declining must NOT freeze the app. _closing is the sole
                # gate that lets loop()/_drain_main_calls/_drain_watched_paths
                # re-arm their after() callbacks; setting it before this
                # return left it stuck True (it is only reset in __init__),
                # permanently killing the queue pump and the drains.
                #
                # Also reset the one-shot exit override: _force_exit /
                # tray Exit set _exit_from_tray=True to bypass the
                # minimise-to-tray redirect above. If we don't clear it on
                # the decline path, the flag stays True for the rest of the
                # session, so the window's X button no longer honours the
                # minimise-to-tray preference (it falls straight through to
                # teardown). The latch is otherwise only reset in __init__.
                self._exit_from_tray = False
                return

        # Confirmation passed (or there was nothing to confirm): flip the
        # closing flag so watcher events / stability-checks in flight
        # short-circuit before touching destroyed widgets.
        self._closing = True
        # Persist window size + position so the next launch reopens at
        # the same shape. Runs *before* terminating subprocesses so it
        # never sees a broken state.
        self._save_window_geometry()
        if self._folder_watcher is not None:
            try:
                self._folder_watcher.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:  # noqa: BLE001
                pass
        for task in self.download_queue:
            # Snapshot once (see cancel_download): a worker thread may null
            # task.process between the test and the poll(), which would raise
            # AttributeError mid-teardown.
            proc = task.process
            if proc is not None and proc.poll() is None:
                # Tree-kill so yt-dlp's ffmpeg merge child dies too (a bare
                # terminate() orphans it, holding the .part/output handle).
                try:
                    kill_process_tree(proc, force=False)
                except Exception:  # noqa: BLE001
                    pass
        try:
            self.tiling.stop()
        except Exception:  # noqa: BLE001
            pass
        # Stop the Live tab BEFORE the transcription workers: it owns its
        # own worker subprocess plus a capture thread holding the audio
        # device, and both would outlive the window otherwise.
        try:
            stop_live_session(self)
        except Exception:  # noqa: BLE001
            pass
        # Same reasoning as the Live tab: its own worker subprocess (a
        # separate, independent one -- see core.voice_clone_worker) plus
        # any in-progress mic recording must not outlive the window.
        try:
            stop_voice_clone_worker(self)
        except Exception:  # noqa: BLE001
            pass
        # Stop the in-process web / LAN server so its socket + worker
        # thread don't linger after the window closes.
        self._shutdown_server_on_exit()
        self.transcription_service.stop_all()
        # Close the history DB connection (and checkpoint its WAL) on a
        # clean exit — the GUI never did, leaking the connection + the
        # -wal/-shm sidecars until interpreter teardown. Mirrors gui.py.
        history = getattr(self, "history", None)
        if history is not None:
            try:
                history.close()
            except Exception:  # noqa: BLE001
                pass
        self.destroy()

    def destroy(self) -> None:  # type: ignore[override]
        # Cancel every pending after() callback before tearing down the
        # Tcl interpreter. Otherwise the service poll loops fire one last
        # time after destroy() and spam the console with
        #   invalid command name "<id>poll"
        # because their bound-method Tcl command no longer exists.
        #
        # tk.call("after", "info") returns a tuple of IDs when >=1 callback
        # is pending and an empty string when none are. The earlier
        # str(pending).split() path produced garbage tokens like
        # "('after#0',)" for the tuple case, which after_cancel silently
        # accepts without actually cancelling — so the fix was a no-op.
        try:
            pending = self.tk.call("after", "info")
            if isinstance(pending, (tuple, list)):
                ids = list(pending)
            else:
                text = str(pending).strip()
                ids = text.split() if text else []
            for cb_id in ids:
                try:
                    self.after_cancel(cb_id)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        super().destroy()

    # Tabs --------------------------------------------------------------------
    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.t1 = ttk.Frame(self.nb)
        self.t2 = ttk.Frame(self.nb)
        self.t3 = ttk.Frame(self.nb)
        self.t4 = ttk.Frame(self.nb)
        self.t5 = ttk.Frame(self.nb)
        self.t6 = ttk.Frame(self.nb)
        self.t7 = ttk.Frame(self.nb)
        self.nb.add(self.t1, text="Transcribe")
        self.nb.add(self.t2, text="Transcription Queue")
        self.nb.add(self.t6, text="Live")
        self.nb.add(self.t3, text="Download Videos")
        # Video Tiling is optional: the Standard installer can drop a
        # no_tiling.flag marker into {app} when the user opts out at install
        # time, in which case we don't add the tab at all. self.tiling (the
        # controller) is still constructed in __init__, so on_exit's
        # self.tiling.stop() stays safe; only the UI surface is hidden. All
        # tiling_* vars + start/stop callbacks are reachable only through this
        # tab's widgets, so skipping it leaves nothing dangling.
        self._tiling_tab_visible = tiling_tab_enabled()
        if self._tiling_tab_visible:
            self.nb.add(self.t4, text="Video Tiling")
        self.nb.add(self.t5, text="Web / LAN access")
        # Clone Your Voice / Text to Voice: same opt-in-at-install shape as
        # Video Tiling above (no_voice_clone.flag / voice_clone_tab_enabled),
        # but an entirely independent marker and worker -- the two features
        # are unrelated and toggled separately. Nothing needs constructing
        # in __init__ the way self.tiling is: the worker subprocess is
        # spawned lazily on first Generate, not up front, so skipping the
        # tab here leaves nothing to tear down (stop_voice_clone_worker is
        # a no-op when app.vc_worker was never set).
        self._voice_clone_tab_visible = voice_clone_tab_enabled()
        if self._voice_clone_tab_visible:
            self.nb.add(self.t7, text="Clone Your Voice")
        build_transcribe_tab(self, self.t1)
        build_queue_tab(self, self.t2)
        build_live_tab(self, self.t6)
        build_download_tab(self, self.t3)
        if self._tiling_tab_visible:
            build_tiling_tab(self, self.t4)
        build_server_tab(self, self.t5)
        if self._voice_clone_tab_visible:
            build_voice_clone_tab(self, self.t7)

    def _save_auto_transcribe_pref(self) -> None:
        self.app_config["auto_transcribe_after_download"] = bool(self.auto_transcribe_var.get())
        try:
            save_config(self.app_config)
        except Exception as e:
            # Audit B1 / FB-01: config-save failures must NOT be
            # silent. The user has just toggled a preference; if
            # the disk write fails (permission denied, antivirus
            # lock), they need to know — otherwise their choice
            # silently reverts on the next launch.
            logger.exception("Failed to save auto-transcribe preference")
            self.log(f"Could not save preference: {e}")

    def _save_transcribe_prefs(self) -> None:
        # vad_enabled is intentionally NOT written here, same reasoning as
        # hotwords below: vad_enabled_var has no matching widget on this
        # tab (build_transcribe_tab's "vars without a matching widget are
        # simply not packed" note), so it is frozen at whatever
        # config.json held when the tab was built.
        # AdvancedDialog._save_and_close's new "Enable VAD" checkbox
        # (2026-08-15) is the real editor of cfg["vad_enabled"] now —
        # writing the stale var here would silently revert that checkbox
        # the moment the user touched the language dropdown or a checkbox
        # on this tab, the exact same clobbering bug hotwords had.
        self.app_config["word_timestamps"] = bool(self.word_timestamps_var.get())
        if getattr(self, "diarization_var", None) is not None:
            self.app_config["diarization_enabled"] = bool(self.diarization_var.get())
        # transcribe_language is intentionally NOT persisted: the picker
        # resets to "Auto" every launch (user request). The choice still
        # lives in transcribe_lang_var for the rest of the session.
        if getattr(self, "device_var", None) is not None:
            self.app_config["device"] = self.device_var.get()
        if getattr(self, "compute_type_var", None) is not None:
            self.app_config["compute_type"] = self.compute_type_var.get()
        # hotwords is intentionally NOT written here. hotwords_var has no
        # matching widget on this tab (see build_transcribe_tab's "vars
        # without a matching widget are simply not packed" note) — it is
        # frozen at whatever config.json held when the tab was built, and
        # AdvancedDialog._save_and_close is the only real editor of
        # cfg["hotwords"]. Writing hotwords_var's stale value here used to
        # silently clobber a hotwords edit made in Advanced the moment the
        # user touched the language dropdown or a checkbox on this tab
        # afterward — a real, confirmed data-loss bug (2026-08-15).
        try:
            save_config(self.app_config)
        except Exception as e:
            logger.exception("Failed to save transcribe preferences")
            self.log(f"Could not save preferences: {e}")

    def open_advanced_dialog(self) -> None:
        dlg = AdvancedDialog(self)
        # Block (nested event loop) until the modal dialog closes, then re-sync
        # the Transcribe-tab engine + model pickers in case the backend,
        # model, or model folder was changed in Advanced settings.
        try:
            self.wait_window(dlg)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_engine_selector()
        self._refresh_model_selector()

    def _confirm_backend_switch(self, parent: "tk.Misc | None" = None) -> bool:
        """True if it's safe to stop_all() workers for an engine switch.

        stop_worker() is a hard terminate (shutdown request, then
        terminate/kill), not the cooperative per-task Cancel -- so
        switching engines while a transcription is actually running can
        lose more progress than a normal Cancel would, with no warning.
        Asks first when any worker has an assigned task; returns True with
        no prompt when nothing is actually running.
        """
        svc = getattr(self, "transcription_service", None)
        if svc is None:
            return True
        busy = [w for w in svc.active_workers() if w.get("task") is not None]
        if not busy:
            return True
        from tkinter import messagebox
        n = len(busy)
        return messagebox.askyesno(
            "Switch transcription engine?",
            (
                f"{n} transcription{'s are' if n != 1 else ' is'} running "
                "right now. Switching engines stops "
                f"{'them' if n != 1 else 'it'} immediately -- more "
                "abruptly than a normal Cancel, so more progress may be "
                "lost.\n\nSwitch anyway?"
            ),
            parent=parent or self,
        )

    def _on_engine_selected(self) -> None:
        """Persist the Transcribe-tab engine pick and restart the worker so the
        new engine takes effect on the next transcription.

        The live worker snapshots ``transcribe_backend`` at spawn and the
        dispatch prefers that stale value, so a fresh worker is required for a
        switch to take effect — the same mechanism a model change uses.
        """
        from core.backends import availability as _eng

        evar = getattr(self, "transcribe_engine_var", None)
        if evar is None:
            return
        value = _eng.LABEL_TO_VALUE.get(evar.get() or "", _eng.FALLBACK_ENGINE)
        old = str(self.app_config.get("transcribe_backend") or "")
        if value != old:
            if not self._confirm_backend_switch():
                evar.set(_eng.VALUE_TO_LABEL.get(old, evar.get()))
                return
            self.app_config["transcribe_backend"] = value
            try:
                save_config(self.app_config)
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to save engine selection")
                self.log(f"Could not save engine selection: {e}")
            try:
                self.transcription_service.stop_all()
            except Exception as e:  # noqa: BLE001
                self.log(f"Could not restart the transcription worker: {e}")
            self.log(
                f"Transcription engine set to {value}. "
                "It will be used on the next transcription."
            )
        self._refresh_engine_status()

    def _refresh_engine_status(self) -> None:
        """Update the Transcribe-tab engine readiness line for the current pick.

        Paints an immediate cheap/neutral line synchronously (so startup and
        selection never block), then kicks off the REAL readiness probe
        (``deep=True`` — genuinely checks installs, model presence, keys) on
        a short-lived background thread and marshals the result back onto
        the Tk main thread via ``self.after``. This keeps the UI responsive
        even when a heavy native-lib import is slow.
        """
        var = getattr(self, "engine_status_var", None)
        if var is None:
            return
        try:
            from core.backends import availability as _eng

            evar = getattr(self, "transcribe_engine_var", None)
            label = evar.get() if evar is not None else ""
            value = _eng.LABEL_TO_VALUE.get(label) or self.app_config.get(
                "transcribe_backend"
            )
            value = _eng.normalise_engine(value)

            # 1) Immediate, cheap, non-blocking paint — "Checking…" so the
            #    user sees something right away while the real probe runs.
            var.set("Checking…")
            lbl = getattr(self, "engine_status_label", None)
            if lbl is not None:
                try:
                    lbl.configure(foreground="#888")
                except Exception:  # noqa: BLE001
                    pass

            # 2) Real probe on a daemon thread — never blocks the UI thread.
            cfg_snapshot = dict(self.app_config)

            def _probe() -> None:
                # GC disabled for this ENTIRE probe thread, not just the
                # engine_status() call — a real crash was confirmed
                # (2026-08-15, Python 3.14) three times, each narrower fix
                # disproven by the next instrumented full-suite rerun:
                # (1) GC firing mid-import inside engine_status() faulted a
                # C-extension class-registration step; (2) narrowing the
                # gc.disable() window to just that call "fixed" it once,
                # then a later rerun faulted one line later in a plain
                # EngineStatus(...) dataclass construction; (3) widening the
                # window to the whole engine_status() try/finally "fixed" it
                # again, then ANOTHER rerun faulted right after gc.enable()
                # returned, inside the post_to_main() call below. gc.disable
                # ()/gc.enable() are PROCESS-GLOBAL, not thread-local — every
                # other thread's allocations pile up ungarbage-collected
                # while this one holds GC off, so re-enabling it here was
                # itself triggering an immediate, larger-than-usual
                # collection at the exact moment this thread kept running.
                # Holding GC off for the probe's ENTIRE body (including
                # post_to_main) removes that re-enable-triggers-a-collision
                # window too. See core/backends/google_cloud_stt.py's
                # matching comment and ADR 0008 in docs/DECISIONS.md for the
                # full three-round story — treat this as a mitigation that
                # has repeatedly needed widening, not a proven-complete fix.
                was_gc_enabled = gc.isenabled()
                gc.disable()
                try:
                    try:
                        st = _eng.engine_status(value, cfg_snapshot, deep=True)
                    except Exception as e:  # noqa: BLE001
                        st = _eng.EngineStatus(value, False, str(e) or "probe failed")
                    # post_to_main, NOT self.after: this runs on a daemon
                    # thread, and off-thread after() raises on Python 3.14.
                    self.post_to_main(
                        lambda: self._apply_engine_status(value, st)
                    )
                finally:
                    if was_gc_enabled:
                        gc.enable()

            threading.Thread(target=_probe, daemon=True).start()
        except Exception:  # noqa: BLE001
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass

    def _apply_engine_status(self, probed_value: str, st: Any) -> None:
        """Apply a background-probed ``EngineStatus`` to the status label.

        Runs on the Tk main thread (scheduled via ``self.after``). Drops the
        result if the user switched engines mid-probe (stale-race guard) or
        if the widgets were destroyed in the meantime (shutdown guard).
        """
        try:
            from core.backends import availability as _eng

            var = getattr(self, "engine_status_var", None)
            lbl = getattr(self, "engine_status_label", None)
            if var is None:
                return
            if lbl is not None:
                try:
                    if not lbl.winfo_exists():
                        return
                except Exception:  # noqa: BLE001
                    return

            evar = getattr(self, "transcribe_engine_var", None)
            current_label = evar.get() if evar is not None else ""
            current_value = _eng.normalise_engine(
                _eng.LABEL_TO_VALUE.get(current_label)
                or self.app_config.get("transcribe_backend")
            )
            if current_value != probed_value:
                return  # stale — the user picked a different engine meanwhile

            if st.ready:
                text = "✓ Ready" + (f" — {st.detail}" if st.detail else "")
                color = "#3a8f3a"
            else:
                text = f"⚠ {st.detail}  (set up in Advanced settings…)"
                color = "#b06a00"
            var.set(text)
            if lbl is not None:
                try:
                    lbl.configure(foreground=color)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _refresh_engine_selector(self) -> None:
        """Re-sync the Transcribe-tab engine picker to the saved backend (e.g.
        after the Advanced dialog changed it), then refresh the status line."""
        evar = getattr(self, "transcribe_engine_var", None)
        if evar is None:
            return
        try:
            from core.backends import availability as _eng

            value = _eng.normalise_engine(self.app_config.get("transcribe_backend"))
            label = _eng.VALUE_TO_LABEL.get(value)
            if label and label != evar.get():
                evar.set(label)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_engine_status()

    def _on_model_selected(self) -> None:
        """Persist the Transcribe-tab Whisper-model pick and restart the
        worker so the new model takes effect on the next transcription.

        Mirrors _on_engine_selected: the live worker snapshots the model at
        spawn, so rewriting cfg alone would leave the OLD model loaded until
        the process happened to restart. Same rewrite AdvancedDialog's model
        picker does in _save_and_close (cfg["whisper_model"] + cfg["model"]
        + cfg["model_path"]), just triggered from this tab's combobox
        instead of a Save button.
        """
        from core.model_manager import (
            DEFAULT_MODEL_SLUG,
            catalog_resolve_entry,
        )

        mvar = getattr(self, "transcribe_model_var", None)
        label_to_slug = getattr(self, "_transcribe_model_label_to_slug", None)
        if mvar is None or not label_to_slug:
            return
        new_slug = label_to_slug.get(mvar.get() or "", DEFAULT_MODEL_SLUG)
        old_slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
        if new_slug == old_slug:
            return
        entry = catalog_resolve_entry(self.app_config, new_slug)
        if entry is None:
            self.log(f"Unknown model slug {new_slug!r}; keeping current model.")
            return
        self.app_config["whisper_model"] = new_slug
        self.app_config["model"] = entry
        self.app_config["model_path"] = ""
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save model selection")
            self.log(f"Could not save model selection: {e}")
        try:
            self.transcription_service.stop_all()
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not restart the transcription worker: {e}")
        self.log(
            f"Whisper model changed to {new_slug}. It will be used on the "
            "next transcription."
        )
        self._refresh_model_status()

    def _refresh_model_status(self) -> None:
        """Update the Transcribe-tab model-downloaded status line.

        A plain on-disk existence check (core.model_manager.model_downloaded)
        -- cheap and import-free, unlike _refresh_engine_status's deep probe,
        so this runs synchronously on the main thread with no background
        thread needed.
        """
        var = getattr(self, "model_status_var", None)
        if var is None:
            return
        try:
            from core.model_manager import DEFAULT_MODEL_SLUG, model_downloaded

            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
            if model_downloaded(self.app_config, slug):
                var.set("✓ Downloaded")
            else:
                var.set("Downloads automatically on first use")
        except Exception:  # noqa: BLE001
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass

    def _refresh_model_selector(self) -> None:
        """Re-sync the Transcribe-tab model picker to the saved slug (e.g.
        after the Advanced dialog changed the model or the model folder),
        then refresh its status line."""
        mvar = getattr(self, "transcribe_model_var", None)
        if mvar is None:
            return
        try:
            from core.model_manager import DEFAULT_MODEL_SLUG, catalog_models

            slug = str(self.app_config.get("whisper_model") or DEFAULT_MODEL_SLUG)
            labeled = catalog_models(self.app_config)
            label_to_slug = {lbl: s for s, lbl in labeled}
            slug_to_label = {s: lbl for s, lbl in labeled}
            self._transcribe_model_label_to_slug = label_to_slug
            label = slug_to_label.get(slug)
            if label and label != mvar.get():
                mvar.set(label)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_model_status()

    # Generic helpers ---------------------------------------------------------
    def yt_dlp_path(self) -> str:
        # Bundled bin/yt-dlp[.exe] when present, else the bare name so
        # Linux/Mac fall back to a yt-dlp on PATH.
        return _bundled_binary("yt-dlp")

    def bin_path(self) -> str:
        # Point yt-dlp's --ffmpeg-location at our bin/ ONLY when a bundled
        # ffmpeg actually lives there. On Linux/Mac with ffmpeg on PATH
        # (no bundled copy) return "" so the flag is omitted and yt-dlp
        # discovers ffmpeg itself instead of failing on an empty bin dir.
        return _resource_bin_dir() if os.path.dirname(_bundled_binary("ffmpeg")) else ""

    def browse(self) -> None:
        """Pick one or more files.

        The dialog supports multi-select; if the user picks several
        files we enqueue each. Single-file selection still just
        populates the file-picker entry without auto-enqueueing —
        keeps the muscle-memory of "Browse → Transcribe" intact.
        """
        chosen = filedialog.askopenfilenames(parent=self)
        if not chosen:
            return
        if len(chosen) == 1:
            self.fv.set(chosen[0])
            return
        count = self._bulk_enqueue(list(chosen))
        if count:
            self.log(f"Enqueued {count} files via Browse...")

    def browse_download_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.download_folder_var.set(folder)
            self.app_config["download_folder"] = folder
            # Guard the save like every other pref handler (Audit B1 / FB-01):
            # a disk/permissions failure must not raise out of the Tk callback.
            try:
                save_config(self.app_config)
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to save download folder preference")
                self.log(f"Could not save download folder setting: {e}")

    def update_download_mode(self) -> None:
        audio_only = self.download_mode_var.get() == "Audio"
        if audio_only:
            self.video_format_combo.configure(state="disabled")
            outputs = ("mp3", "m4a", "aac", "opus", "flac", "wav")
            if self.output_format_var.get() not in outputs:
                self.output_format_var.set("mp3")
        else:
            self.video_format_combo.configure(state="readonly")
            outputs = ("mp4", "mkv", "webm")
            if self.output_format_var.get() not in outputs:
                self.output_format_var.set("mp4")
        self.output_format_combo["values"] = outputs

    def update_subtitle_state(self) -> None:
        if self.download_subtitles_var.get():
            self.subtitle_lang_combo.configure(state="readonly")
        else:
            self.subtitle_lang_combo.configure(state="disabled")
            self.subtitle_status_var.set("")

    def update_caption_shortcut_state(self) -> None:
        """Show/hide the "Use captions instead" shortcut.

        Called after every format lookup (see app.services.format_service)
        and whenever the subtitle-language combo changes. Independent of
        the "Download subtitles" checkbox above it -- this is a separate
        action, not a modifier of the main Download button. SMTV already
        writes its own transcript alongside every download, so the
        shortcut never applies while an SMTV episode is loaded.
        """
        status_var = getattr(self, "caption_shortcut_status_var", None)
        button = getattr(self, "caption_shortcut_button", None)
        if status_var is None or button is None:
            return
        if getattr(self, "_smtv_episode", None) is not None:
            status_var.set("")
            button.pack_forget()
            return

        from app.domain.languages import SUBTITLE_LANGUAGES, resolve_caption_kind

        sub_lang_name = self.subtitle_lang_var.get() if hasattr(self, "subtitle_lang_var") else ""
        lang_code_csv = next(
            (code for name, code in SUBTITLE_LANGUAGES if name == sub_lang_name), ""
        )
        caption_langs = getattr(self, "current_video_caption_langs", None) or {}
        kind = resolve_caption_kind(
            caption_langs, lang_code_csv, fallback_lang=self.current_video_language
        )
        if not kind:
            status_var.set("")
            button.pack_forget()
            return

        label = sub_lang_name if sub_lang_name and sub_lang_name != "Automatic" else (
            self.current_video_language or "the detected language"
        )
        if kind == "manual":
            status_var.set(
                f'Captions (creator-provided) are already available in "{label}" '
                "-- skip downloading and transcribing?"
            )
        else:
            status_var.set(
                f'Auto-generated captions are already available in "{label}" -- '
                "skip downloading and transcribing? (may be less accurate than "
                "a real transcription)"
            )
        button.pack(side="left", padx=(10, 0))

    def model_status(self, msg: str) -> None:
        # Display only. Worker readiness is tracked authoritatively via the
        # worker's 'ready' event → TranscriptionService.update_model_state();
        # don't latch model_ready off a log-line substring — any line that
        # merely contained "Model loaded" (an echo, a future diagnostic)
        # could desync the app-global flag from real worker state (P2-30).
        self.status_var.set(msg)
        self.log(msg)

    # R3: device badge --------------------------------------------------------
    def register_device_badge_label(self, label: "ttk.Label", tier_label: str = "") -> None:
        """Register a badge Label so apply_device_badge can recolour it.

        Called by tabs.py for each placement (Transcribe header + Queue
        status line). Stores an optional tier label used in the tooltip.
        """
        self.device_badge_labels.append(label)
        if tier_label:
            self.device_badge_tip = tier_label
        self._bind_device_badge_tooltip(label)

    def apply_device_badge(self, text: str, kind: str, worker: dict[str, Any]) -> None:
        """Set the badge text + colour from the worker's effective device.

        ``kind`` is one of ``gpu`` (green), ``cpu`` (amber), ``cpu_downgraded``
        (amber). Colours are theme-agnostic enough to read on sv_ttk's dark
        and light palettes. The tooltip is refreshed with the full detail.
        """
        self.device_badge_var.set(text)
        colour = {
            "gpu": "#2e9e44",            # green — running on the GPU
            "cpu": "#d08a1d",            # amber — CPU (slower)
            "cpu_downgraded": "#d08a1d",  # amber — GPU asked, fell back to CPU
        }.get(kind, "")
        req = str(worker.get("requested_device") or "")
        ct = str(worker.get("compute_type") or "")
        dev = str(worker.get("device") or "")
        tip = f"Transcribing on {dev or 'cpu'}"
        if ct:
            tip += f" ({ct})"
        if kind in ("cpu", "cpu_downgraded"):
            tip += (
                ". CPU is much slower than a GPU. Open the Hardware wizard to "
                "check for a CUDA GPU; if you have an NVIDIA card, install its "
                "drivers + the cuDNN/cuBLAS runtime."
            )
        if kind == "cpu_downgraded" and req:
            tip = f"Requested {req} but it was unavailable. " + tip
        self.device_badge_tip = tip
        for label in self.device_badge_labels:
            try:
                if colour:
                    label.configure(foreground=colour)
                label.configure(text=text)
            except Exception:  # noqa: BLE001
                pass

    def _bind_device_badge_tooltip(self, widget: "ttk.Label") -> None:
        """Lightweight hover tooltip showing the full device detail.

        Uses the shared tooltip helper with a getter (not a plain string)
        since ``device_badge_tip`` is rewritten on every model-state change
        after this is first bound.
        """
        from app.widgets.tooltip import bind_tooltip

        bind_tooltip(widget, lambda: self.device_badge_tip, wraplength=320)

    def warn_cpu_once(self, downgraded: bool) -> None:
        """One-time modal + log warning that transcription is on CPU (slower).

        Only invoked by TranscriptionService when the situation is actionable
        (a CUDA->CPU downgrade, or a GPU detected-but-unusable). Kept short.
        """
        if downgraded:
            msg = (
                "Your GPU could not be used, so transcription is running on "
                "the CPU — this is much slower.\n\n"
                "This usually means the NVIDIA cuDNN/cuBLAS runtime is missing "
                "or broken (not a corrupt model). Open the Hardware wizard "
                "for details."
            )
        else:
            msg = (
                "A GPU was detected but cannot be used, so transcription is "
                "running on the CPU — this is much slower.\n\n"
                "Check your NVIDIA drivers and the cuDNN/cuBLAS runtime. Open "
                "the Hardware wizard for details."
            )
        self.log(msg.replace("\n\n", " "))
        try:
            messagebox.showwarning("Running on CPU (slower)", msg, parent=self)
        except Exception:  # noqa: BLE001
            pass

    # Modal model setup -------------------------------------------------------
    def ensure_model_with_modal(self, mandatory: bool = False) -> bool:
        if self.model_ready:
            self.status_var.set("Model loaded")
            return True
        return self._open_model_download_modal(mandatory=mandatory)

    def download_model_now(self) -> bool:
        """Force the model-download modal for the CONFIGURED slug.

        Unlike ``ensure_model_with_modal``, this does NOT short-circuit on the
        app-global ``model_ready`` flag. The Advanced "Download now" button
        targets one specific model's bytes; once ANY model was loaded,
        ``model_ready`` was True and the old gate made "Download now" a silent
        no-op. ``ensure_model`` is idempotent (a fast MD5 check when the bytes
        are already present), so opening the modal here is safe even if some
        model is loaded.
        """
        return self._open_model_download_modal(mandatory=False)

    def _open_model_download_modal(self, mandatory: bool = False) -> bool:
        if self.model_setup_running:
            return False
        self.model_setup_running = True
        dialog = ModelDownloadDialog(self)
        self.wait_window(dialog)
        self.model_setup_running = False
        if dialog.success:
            # v1.0.3 — lazy model load.
            # Used to call ``transcription_service.start_standby()``
            # here to spawn a worker the moment the model bytes
            # finished downloading. We no longer preload — the worker
            # spawns on the first transcribe via
            # ``ensure_worker_ready``, which puts up its own modal.
            # Just log that the bytes are ready.
            self.log("Model downloaded.")
            return True
        self.model_ready = False
        self.status_var.set("Model is required")
        if mandatory:
            self.log("Model setup was cancelled or failed.")
        return False

    # On-demand optional dependencies (slim build) ---------------------------
    def _offer_optional_install(self, feature: str, friendly: str, size_hint: str) -> bool:
        """If a slim-build optional feature's package is missing, offer a
        one-time download. Returns True if usable (already present or just
        installed), False if declined/failed — the caller then proceeds
        without the feature (the worker skips it gracefully).
        """
        import threading

        import core.optional_deps as optional_deps
        if optional_deps.is_available(feature):
            return True
        if not messagebox.askyesno(
            f"{friendly} needs a download",
            f"{friendly} needs a one-time download of about {size_hint} "
            f"(PyTorch + support files).\n\nDownload and install it now?\n"
            f"Choose No to continue this time without it.",
            parent=self,
        ):
            self.log(f"{friendly}: skipped the optional download — continuing without it.")
            return False
        win = tk.Toplevel(self)
        win.title(f"Installing {friendly}")
        win.transient(self)
        win.resizable(False, False)
        ttk.Label(
            win,
            text=(f"Downloading and installing {friendly} (~{size_hint}).\n"
                  "This happens once and can take a few minutes…"),
            justify="left",
        ).pack(padx=18, pady=(16, 8))
        bar = ttk.Progressbar(win, mode="indeterminate", length=340)
        bar.pack(padx=18, pady=(0, 12))
        bar.start(12)
        state = {"ok": False, "done": False}
        cancel_event = threading.Event()

        def _request_cancel() -> None:
            # Set the event so optional_deps.install terminates pip and
            # returns False promptly; the window closes via _poll once the
            # worker thread observes it. Without this, closing the modal
            # left pip running orphaned and the bar could spin forever on a
            # stalled download.
            cancel_event.set()
            try:
                cancel_btn.config(state="disabled", text="Cancelling…")
            except tk.TclError:
                pass

        cancel_btn = ttk.Button(win, text="Cancel", command=_request_cancel)
        cancel_btn.pack(pady=(0, 14))
        win.protocol("WM_DELETE_WINDOW", _request_cancel)

        def _work() -> None:
            # self.log writes the Tk text widget directly; this runs off
            # the main thread, so marshal every line through post_to_main.
            def _safe_log(line: str) -> None:
                self.post_to_main(lambda: self.log(line))
            try:
                state["ok"] = optional_deps.install(
                    feature, log_cb=_safe_log, cancel_event=cancel_event
                )
            except Exception as e:  # noqa: BLE001
                self.post_to_main(lambda e=e: self.log(f"{friendly} install failed: {e}"))
            finally:
                state["done"] = True

        threading.Thread(target=_work, name="optdeps-install", daemon=True).start()

        def _poll() -> None:
            if state["done"]:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                return
            self.after(200, _poll)

        self.after(200, _poll)
        self.wait_window(win)
        if state["ok"]:
            self.log(f"{friendly} installed.")
            # A live worker activated its sys.path BEFORE this install, so
            # restart workers to pick up the new package on the next task.
            try:
                self.transcription_service.stop_all()
            except Exception:  # noqa: BLE001
                pass
            return True
        return False

    # Adding tasks ------------------------------------------------------------
    def add(self) -> None:
        text = self.fv.get().strip()
        if not text:
            self.log("Pick a file first — use the Browse button on the Transcribe tab.")
            return
        # YouTube / yt-dlp URL detection — if the user pastes a URL
        # into the Transcribe file field, route it through the
        # Download tab with auto-transcribe-after-download on. The
        # download flow is the established way to fetch network
        # media; we just connect the dots.
        if text.startswith(("http://", "https://")):
            try:
                self.download_url_var.set(text)
                if hasattr(self, "auto_transcribe_var"):
                    self.auto_transcribe_var.set(True)
                self.nb.select(self.t3)
                self.log(
                    f"URL detected — pasted into the Download tab with "
                    f"auto-transcribe ON: {text[:60]}"
                )
            except Exception as e:  # noqa: BLE001
                self.log(f"URL handoff failed: {e}")
            return
        # Local-path sanity: a deleted / mistyped path would otherwise
        # enqueue a task that only fails deep in the worker with a cryptic
        # error. Catch it here where we can give a clear message.
        if not os.path.isfile(text):
            self.log(f"File not found — pick an existing file: {text}")
            return
        if not self._ensure_transcribe_ready():
            return
        # Per-task language override + optional clip range.
        task = TranscriptionTask(self.fv.get())
        self._apply_task_options(task)
        self.queue.append(task)
        self.pb["value"] = 0
        self.nb.select(self.t2)
        self.log(f"Queued: {os.path.basename(self.fv.get())}")
        self.refresh()

    def _ensure_transcribe_ready(self) -> bool:
        """Run the one-time transcribe gates; True if a task may be enqueued.

        Shared by add() and _bulk_enqueue so the ~3 GB model-download modal,
        the optional-alignment offer, and the worker spawn happen exactly
        ONCE per user action — not once per file in a multi-file batch.

        First-transcribe gating:
          1. If the model bytes are not on disk → download dialog.
          2. Then call ensure_worker_ready to lazy-load the model into a
             worker subprocess. v1.0.3: was previously preloaded at startup;
             deferring it here saves ~1.5 GB of idle RAM in sessions where the
             user never clicks Transcribe.
        """
        if not self._model_bytes_present():
            if self.model_setup_running:
                self.log("Model download already in progress — please wait.")
                return False
            if not messagebox.askyesno(
                "Whisper model required",
                "The Whisper model must be downloaded before the first transcription. "
                "Download it now? (about 3 GB, one time only)",
                parent=self,
            ):
                self.log("Transcription cancelled: the Whisper model is required.")
                return False
            if not self.ensure_model_with_modal():
                self.log("Transcription cancelled: the Whisper model is not ready.")
                return False
        # Slim build: if word-alignment is enabled but its (large, optional)
        # package isn't installed, offer the one-time download BEFORE the
        # worker spawns so the worker activates with it present. Declining
        # is fine — the worker skips alignment gracefully.
        if self.app_config.get("alignment") == "stable_ts":
            self._offer_optional_install("alignment", "Word-timestamp alignment", "700 MB")
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Transcription cancelled: model load was cancelled")
            return False
        return True

    def _apply_task_options(self, task: TranscriptionTask) -> None:
        """Apply the Transcribe-tab language + clip-range options to a task.

        Shared by add() and _bulk_enqueue so a bulk-enqueued file gets the
        same per-task language override and optional time-slice as a single
        file enqueued through Transcribe.
        """
        # Per-task language override. The picker shows "Auto" for the
        # default Whisper auto-detect; any other value is a language
        # name that maps to a known code via app.domain.languages.
        lang_choice = getattr(self, "transcribe_lang_var", None)
        if lang_choice is not None:
            choice = lang_choice.get().strip()
            if choice and choice.lower() != "auto":
                from app.domain.languages import SUBTITLE_LANGUAGES
                code = next(
                    (c for name, c in SUBTITLE_LANGUAGES if name == choice),
                    "",
                )
                if code:
                    task.language = code
        # Optional time-slice (Transcribe-tab time range): transcribe only
        # [start, end]. A 0:00:00 / blank bound is "unset", so leaving both
        # at 0:00:00 transcribes the whole file.
        if hasattr(self, "transcribe_start_time_var"):
            from app.services.download_service import _parse_timecode
            task.clip_start = _parse_timecode(self.transcribe_start_time_var.get()) or None
            task.clip_end = _parse_timecode(self.transcribe_end_time_var.get()) or None

    def _bulk_enqueue(self, paths: "list[str]") -> int:
        """Enqueue many files as transcription tasks in one shot.

        Multi-file Browse and multi-file drag-and-drop both call this instead
        of looping add() per path: add() re-pops the ~3 GB model-download
        modal and re-runs the tab-switch + full-tree refresh() PER FILE, which
        is jarring for a 20-file drop. Here the model/worker gate runs ONCE up
        front, every existing file is enqueued with the same language/clip
        options, and refresh() runs ONCE at the end. Returns the count
        enqueued (0 if the gate was declined or no path existed).
        """
        files = [p for p in paths if p and os.path.isfile(p)]
        if not files:
            return 0
        if not self._ensure_transcribe_ready():
            return 0
        count = 0
        for path in files:
            task = TranscriptionTask(path)
            self._apply_task_options(task)
            self.queue.append(task)
            count += 1
        if count:
            self.pb["value"] = 0
            self.nb.select(self.t2)
            self.refresh()
        return count

    def _model_bytes_present(self) -> bool:
        """True when the Whisper model files are already on disk.

        Cheap probe used by the lazy-load enqueue gate to decide
        whether to surface the ~3 GB download dialog. Just checks
        that the resolved model directory exists; the worker's
        load step will surface any deeper corruption via a
        ``startup_error`` event.
        """
        try:
            from pathlib import Path
            from core.hub import default_hub_folder, model_folder_for

            mp = str(self.app_config.get("model_path") or "").strip()
            if mp and Path(mp).exists():
                return True

            model_info = self.app_config.get("model") or {}
            model_name = ""
            if isinstance(model_info, dict):
                model_name = str(model_info.get("name") or "").strip()
            if not model_name:
                model_name = str(self.app_config.get("whisper_model") or "").strip()
            if not model_name:
                model_name = "faster-whisper-large-v3"

            hub_folder = str(self.app_config.get("hub_folder") or "").strip()
            if not hub_folder:
                hub_folder = str(default_hub_folder())

            return model_folder_for(hub_folder, model_name).exists()
        except Exception:  # noqa: BLE001
            return False

    def enqueue_transcription_from_download(
        self, file_path: str, language: str, source_download: "Any" = None
    ) -> None:
        """Auto-transcribe-after-download wiring: push a task without freezing.

        Runs on the Tk main thread (the download-complete handler). A
        cold Whisper-model load takes 10–60 s, and the old code waited
        for the worker's ``ready`` event synchronously here — which
        froze the whole UI after every download with the checkbox on
        (the "Transcribe after download freezes the app" bug).

        Instead we spawn a worker if none is alive yet and poll for
        readiness with ``after()`` so the event loop keeps running; the
        task is enqueued the moment a worker reports ready. If the load
        never completes we drop the task rather than queue one that can
        never run.
        """
        base = os.path.basename(file_path)

        def _enqueue() -> None:
            # The model-load wait can run up to ~120 s. If the user cancelled
            # or removed this download during that window, don't resurrect it
            # — re-stamping 'transcribing' and enqueuing a transcription for a
            # download they explicitly cancelled (Audit P2-3).
            if source_download is not None and getattr(
                source_download, "status", None
            ) in ("cancelled", "error"):
                return
            task = TranscriptionTask(file_path)
            if hasattr(task, "language"):
                setattr(task, "language", language)
            # Link the originating download row to this transcription so
            # the Download tab shows "transcribing" + live progress, then
            # flips back to "finished" when the transcription ends.
            if source_download is not None:
                task.source_download = source_download
                source_download.transcription_task = task
                source_download.status = "transcribing"
                self.refresh_download_queue()
            self.queue.append(task)
            self.refresh()

        def _on_timeout() -> None:
            self.log(f"Auto-transcribe skipped: model load timed out for {base} — {HEADLESS_READY_TIMEOUT_S} s")
            if source_download is not None:
                source_download.status = "finished"
                source_download.transcription_task = None
                self.refresh_download_queue()

        self._when_worker_ready(
            _enqueue,
            on_timeout=_on_timeout,
            loading_label=f"will transcribe {base} when ready.",
        )

    def _when_worker_ready(
        self,
        on_ready: Callable[[], None],
        *,
        on_timeout: Callable[[], None] | None = None,
        loading_label: str = "",
    ) -> None:
        """Run ``on_ready`` on the Tk main thread once a transcription
        worker is loaded, without blocking the event loop.

        Every main-thread enqueue path (auto-transcribe-after-download,
        crash-resume, watched-folder) used to call
        ``ensure_worker_ready(headless=True)``, which blocks on a
        ``threading.Event.wait`` for up to the model-load timeout. Those
        handlers run on the Tk main thread, so a cold model load froze
        the whole UI. This spawns a worker if none is alive and polls
        for readiness with ``after()`` instead; ``on_timeout`` (if
        given) runs when the load doesn't finish within the timeout.
        """
        svc = self.transcription_service
        if svc.ready_workers():
            on_ready()
            return
        # Spawn a worker if none is alive yet — but don't spawn a second
        # if one is already loading (a parallel path may have started it).
        if not svc.active_workers():
            svc.start_worker(temporary=False)
            if loading_label:
                self.log(f"Loading Whisper model — {loading_label}")
        deadline = time.monotonic() + HEADLESS_READY_TIMEOUT_S

        def _await_ready() -> None:
            if svc.ready_workers():
                on_ready()
                return
            if time.monotonic() >= deadline:
                if on_timeout is not None:
                    on_timeout()
                return
            self.after(400, _await_ready)

        self.after(400, _await_ready)

    def add_download(self) -> None:
        self.download_service.enqueue_from_form()

    # Right-click context menus -----------------------------------------------
    def menu_row(self, e: tk.Event) -> None:
        item = self.tree.identify_row(e.y)
        if not item:
            return
        sel = self.tree.selection()
        # If the right-clicked row is part of a multi-row selection, act
        # on the whole selection (bulk) rather than resetting to one row.
        if item in sel and len(sel) > 1:
            tasks = [t for t in (self.row_map.get(i) for i in sel) if t]
            if tasks:
                self._bulk_task_menu(tasks, e)
            return
        self.tree.selection_set(item)
        task = self.row_map.get(item)
        if not task:
            return
        # Drive the menu entries from the SAME pure helper the always-visible
        # action bar uses (button_states_for_status), so the two can never
        # disagree about which actions a status offers.
        from app.widgets.tabs import button_states_for_status
        states = button_states_for_status(
            task.status, self._task_has_checkpoint(task)
        )
        m = tk.Menu(self, tearoff=0)
        if states["pause"]:
            m.add_command(label="Pause", command=lambda: self.pause(task))
        if states["resume"] and task.status == "paused":
            m.add_command(label="Resume", command=lambda: self.resume(task))
        if states["cancel"]:
            m.add_command(label="Cancel", command=lambda: self.cancel(task))
        if task.status in ("finished", "cancelled", "error"):
            if task.status == "finished":
                m.add_command(
                    label="Export → oTranscribe (.otr)",
                    command=lambda: self.integrations_service.export_task_to_otr(task),
                )
                m.add_command(
                    label="Burn subtitles into video...",
                    command=lambda: self._burn_subs_for(task),
                )
                m.add_command(
                    label="View transcript",
                    command=lambda: self.open_transcript_viewer_for(
                        task.file_path, self._task_json_output(task)
                    ),
                )
                m.add_command(
                    label="Open output folder",
                    command=lambda: self._open_folder(os.path.dirname(task.file_path)),
                )
                m.add_separator()
            # Resume-from-cancellation: a "Resume" entry sits above "Re-run"
            # only when a resumable checkpoint exists (states["resume"] for a
            # cancelled task). Error / finished never invite a resume from a
            # potentially stale partial.
            if states["resume"] and task.status == "cancelled":
                m.add_command(
                    label="Resume",
                    command=lambda: self.resume_task(task),
                )
            if states["rerun"]:
                m.add_command(label="Re-run", command=lambda: self._rerun_task(task))
            if states["remove"]:
                m.add_command(label="Remove", command=lambda: self.remove_task(task))
        m.tk_popup(e.x_root, e.y_root)

    def _task_has_checkpoint(self, task: TranscriptionTask) -> bool:
        """True when a cancelled task has a resumable partial on disk.

        Cheap, defensive probe shared by menu_row and the action bar so
        both surface "Resume" under the same condition. Any failure (the
        checkpoint module missing, a bad path) is swallowed — the probe
        must never block the menu or the action-bar refresh.

        Goes straight to ``core._checkpoint`` (a tiny, dependency-light
        module — just hashlib/json/os/pathlib) rather than through
        ``core.transcriber.has_resumable_checkpoint``: that one-line
        wrapper forces the FIRST import of the whole faster_whisper /
        ctranslate2 backend stack onto the Tk main thread, synchronously,
        inside a probe that runs on every 500 ms refresh tick for every
        selected row. That is exactly the kind of front-end wiring fault
        that froze the whole app the moment a task was first cancelled —
        the probe only ever needed a cheap file-existence check.
        """
        if getattr(task, "status", "") != "cancelled":
            return False
        try:
            from core import _checkpoint
            return bool(_checkpoint.has_checkpoint(task.file_path))
        except Exception:  # noqa: BLE001
            return False

    def download_menu_row(self, e: tk.Event) -> None:
        item = self.download_tree.identify_row(e.y)
        if not item:
            return
        sel = self.download_tree.selection()
        if item in sel and len(sel) > 1:
            tasks = [t for t in (self.download_row_map.get(i) for i in sel) if t]
            if tasks:
                self._bulk_download_menu(tasks, e)
            return
        task = self.download_row_map.get(item)
        if not task:
            return
        from app.services.download_service import _is_smtv_task
        from app.widgets.tabs import download_button_states_for_status
        saved_dl = getattr(task, "saved_path", None)
        has_file_dl = bool(saved_dl) and os.path.isfile(saved_dl) if saved_dl else False
        dstates = download_button_states_for_status(
            task.status, is_smtv=_is_smtv_task(task), has_saved_file=has_file_dl
        )
        m = tk.Menu(self, tearoff=0)
        if task.status in ("waiting", "running", "transcribing"):
            # "transcribing" = the download finished and handed off to an
            # auto-transcribe; Cancel here stops that linked task too
            # (cancel_download unlinks + cancels transcription_task).
            if dstates["pause"]:
                m.add_command(label="Pause", command=lambda: self.pause_download(task))
            m.add_command(label="Cancel", command=lambda: self.cancel_download(task))
        elif task.status == "paused":
            m.add_command(label="Resume", command=lambda: self.resume_download(task))
            m.add_command(label="Cancel", command=lambda: self.cancel_download(task))
        elif task.status in ("finished", "cancelled", "error"):
            saved = getattr(task, "saved_path", None)
            if task.status == "finished" and saved and os.path.isfile(saved):
                m.add_command(
                    label="Open file",
                    command=lambda p=saved: self._open_file(p),
                )
            m.add_command(
                label="Open download folder",
                command=lambda: self._open_folder(task.folder),
            )
            m.add_command(label="Re-run", command=lambda: self._rerun_download(task))
            m.add_command(label="Remove", command=lambda: self.remove_download(task))
        m.tk_popup(e.x_root, e.y_root)

    # --- bulk (multi-select) queue actions -----------------------------------
    def _bulk_apply(self, tasks: list[Any], fn: Callable[[Any], Any]) -> None:
        for t in list(tasks):
            try:
                fn(t)
            except Exception:  # noqa: BLE001
                pass

    def _resumable_tasks(self, tasks: list[Any]) -> list[Any]:
        # See _task_has_checkpoint: go straight to the lightweight
        # core._checkpoint module rather than core.transcriber, which
        # would force the heavy faster_whisper/ctranslate2 backend
        # import onto the Tk main thread for a plain file-existence check.
        try:
            from core import _checkpoint
        except Exception:  # noqa: BLE001
            return []
        out: list[Any] = []
        for t in tasks:
            if getattr(t, "status", "") == "cancelled":
                try:
                    if _checkpoint.has_checkpoint(t.file_path):
                        out.append(t)
                except Exception:  # noqa: BLE001
                    pass
        return out

    def _active_dup_in_queue(self, file_path: str) -> bool:
        """True if a non-terminal queue task already targets ``file_path``.

        Re-run / Resume re-enqueue a fresh task from a terminal (finished /
        cancelled / error) row. Without this guard, double-clicking Re-run
        (or re-running while a previous re-run of the same file is still
        waiting / running) enqueues a SECOND concurrent transcription of the
        same file — wasted work and confusing duplicate rows. Mirrors the
        watched-folder dedup in :meth:`_enqueue_watched_file`: skip only when
        a same-path task is still pending; a finished/cancelled/error row
        does not block a fresh re-run.
        """
        try:
            norm = os.path.normcase(os.path.abspath(file_path))
        except Exception:  # noqa: BLE001
            return False
        for existing in self.queue:
            try:
                if (os.path.normcase(os.path.abspath(existing.file_path)) == norm
                        and getattr(existing, "status", "")
                        not in ("finished", "cancelled", "error")):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _bulk_rerun(self, tasks: list[Any]) -> None:
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Re-run cancelled: model load was cancelled")
            return
        for t in tasks:
            if self._active_dup_in_queue(t.file_path):
                self.log(
                    f"Re-run skipped: {os.path.basename(t.file_path)} is "
                    f"already in the queue."
                )
                continue
            nt = TranscriptionTask(t.file_path)
            if getattr(t, "language", None):
                nt.language = t.language
            # Preserve the time-range slice across re-run (mirrors the Download
            # tab's _rerun_download fix) — without this a clipped row re-runs
            # the WHOLE file instead of the slice the user picked.
            nt.clip_start = getattr(t, "clip_start", None)
            nt.clip_end = getattr(t, "clip_end", None)
            self.queue.append(nt)
        self.refresh()

    def _bulk_resume(self, tasks: list[Any]) -> None:
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Resume cancelled: model load was cancelled")
            return
        for t in tasks:
            if self._active_dup_in_queue(t.file_path):
                self.log(
                    f"Resume skipped: {os.path.basename(t.file_path)} is "
                    f"already in the queue."
                )
                continue
            nt = TranscriptionTask(t.file_path)
            if getattr(t, "language", None):
                nt.language = t.language
            nt.clip_start = getattr(t, "clip_start", None)
            nt.clip_end = getattr(t, "clip_end", None)
            nt.resume = True
            nt.cancelled = False
            self.queue.append(nt)
        self.refresh()

    def _bulk_task_menu(self, tasks: list[Any], e: tk.Event) -> None:
        active = [t for t in tasks if t.status in ("waiting", "running", "paused")]
        terminal = [t for t in tasks if t.status in ("finished", "cancelled", "error")]
        if not active and not terminal:
            return
        m = tk.Menu(self, tearoff=0)
        if active:
            m.add_command(label=f"Cancel selected ({len(active)})",
                          command=lambda ts=active: self._bulk_apply(ts, self.cancel))
        if terminal:
            m.add_command(label=f"Re-run selected ({len(terminal)})",
                          command=lambda ts=terminal: self._bulk_rerun(ts))
            resumable = self._resumable_tasks(terminal)
            if resumable:
                m.add_command(label=f"Resume selected ({len(resumable)})",
                              command=lambda ts=resumable: self._bulk_resume(ts))
            m.add_command(label=f"Remove selected ({len(terminal)})",
                          command=lambda ts=terminal: self._bulk_apply(ts, self.remove_task))
        m.tk_popup(e.x_root, e.y_root)

    def _bulk_download_menu(self, tasks: list[Any], e: tk.Event) -> None:
        active = [t for t in tasks if t.status in ("waiting", "running")]
        terminal = [t for t in tasks if t.status in ("finished", "cancelled", "error")]
        if not active and not terminal:
            return
        m = tk.Menu(self, tearoff=0)
        if active:
            m.add_command(label=f"Cancel selected ({len(active)})",
                          command=lambda ts=active: self._bulk_apply(ts, self.cancel_download))
        if terminal:
            m.add_command(label=f"Re-run selected ({len(terminal)})",
                          command=lambda ts=terminal: self._bulk_apply(ts, self._rerun_download))
            m.add_command(label=f"Remove selected ({len(terminal)})",
                          command=lambda ts=terminal: self._bulk_apply(ts, self.remove_download))
        m.tk_popup(e.x_root, e.y_root)

    def _open_folder(self, folder: str) -> None:
        _open_folder_helper(folder, parent=self)

    def _rerun_task(self, task: TranscriptionTask) -> None:
        # Right-click re-run is an interactive action: show the
        # lazy-load modal if no worker is alive yet.
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Re-run cancelled: model load was cancelled")
            return
        if self._active_dup_in_queue(task.file_path):
            self.log(
                f"Re-run skipped: {os.path.basename(task.file_path)} is "
                f"already in the queue."
            )
            return
        new_task = TranscriptionTask(task.file_path)
        if getattr(task, "language", None):
            new_task.language = task.language
        new_task.clip_start = getattr(task, "clip_start", None)
        new_task.clip_end = getattr(task, "clip_end", None)
        self.queue.append(new_task)
        self.refresh()

    def resume_task(self, task: TranscriptionTask) -> None:
        """Re-enqueue a cancelled task to resume from its checkpoint.

        We don't try to revive the original task object in place: the
        cancel path tore down its worker and the row is in a terminal
        state. A fresh TranscriptionTask carrying ``resume=True`` is
        clearer for the user (a new Queue row appears) and matches
        the existing ``_rerun_task`` pattern.

        The worker side falls back to a full re-run if the checkpoint
        turns out to be stale at validation time, so the user always
        gets an output.
        """
        # Interactive — surface the lazy-load modal if needed.
        if not self.transcription_service.ensure_worker_ready(self):
            self.log("Resume cancelled: model load was cancelled")
            return
        if self._active_dup_in_queue(task.file_path):
            self.log(
                f"Resume skipped: {os.path.basename(task.file_path)} is "
                f"already in the queue."
            )
            return
        new_task = TranscriptionTask(task.file_path)
        if getattr(task, "language", None):
            new_task.language = task.language
        new_task.clip_start = getattr(task, "clip_start", None)
        new_task.clip_end = getattr(task, "clip_end", None)
        new_task.resume = True
        new_task.cancelled = False
        self.queue.append(new_task)
        self.refresh()

    def _rerun_download(self, task: VideoDownloadTask) -> None:
        from app.domain.tasks import VideoDownloadTask as VDT
        copy = VDT(
            task.url, task.folder, task.format_label, task.format_info, task.title,
            subtitles_enabled=task.subtitles_enabled,
            subtitle_lang=task.subtitle_lang,
            detected_language=task.detected_language,
            # Preserve the time-range slice — without this a re-run silently
            # fetched the full video instead of the slice the user picked.
            section_start=task.section_start,
            section_end=task.section_end,
            # Preserve the caption-only shortcut — without this a retry of
            # a failed "use captions instead" task would silently fall
            # back to a full media download.
            caption_only=task.caption_only,
            caption_kind=task.caption_kind,
        )
        self.download_queue.append(copy)
        self.refresh_download_queue()
        self.download_service.process_queue()

    def set_download_duration(self, seconds: float) -> None:
        """Point the Download-tab position sliders at the probed video
        length. seconds <= 0 (live / unknown / SMTV) leaves them disabled."""
        dur = max(0.0, float(seconds or 0.0))
        self._download_duration = dur
        start = getattr(self, "download_start_scale", None)
        end = getattr(self, "download_end_scale", None)
        if start is None or end is None:
            return
        # Reset the slider knobs to 0 WITHOUT firing _on_download_scale —
        # otherwise the (debounced) probe would wipe a range the user just
        # typed into the Start/End fields.
        self._suppress_scale_cb = True
        try:
            for sc in (start, end):
                sc.configure(to=dur if dur > 0 else 1.0)
                sc.set(0.0)
                sc.state(["!disabled"] if dur > 0 else ["disabled"])
        finally:
            self._suppress_scale_cb = False
        if getattr(self, "download_duration_var", None) is not None:
            from app.services.download_service import _fmt_timecode
            self.download_duration_var.set(
                f"video length {_fmt_timecode(dur)} — drag to set the range"
                if dur > 0 else ""
            )

    def _sync_download_scale_from_text(self, which: str) -> None:
        """Move the position slider to match its Start/End field after a
        direct edit (typing, not dragging).

        _on_download_scale only writes slider -> field. Without this, typing
        a value directly left the slider at its old (usually 0:00:00)
        position -- invisible until the user later touched EITHER slider,
        at which point that slider's stale position silently overwrote the
        just-typed value back to wherever the knob visually still sat.
        """
        if getattr(self, "_suppress_scale_cb", False):
            return
        dur = getattr(self, "_download_duration", 0.0)
        if dur <= 0:
            return
        scale = getattr(
            self, "download_start_scale" if which == "start" else "download_end_scale",
            None,
        )
        if scale is None:
            return
        var = self.download_start_time_var if which == "start" else self.download_end_time_var
        try:
            raw = var.get()
        except Exception:  # noqa: BLE001
            return
        from app.services.download_service import _parse_timecode
        secs = _parse_timecode(raw)
        if secs is None:
            # Mid-typing (e.g. "0:0") or garbled -- leave the slider alone
            # rather than snapping it to a meaningless position.
            return
        secs = max(0.0, min(dur, secs))
        self._suppress_scale_cb = True
        try:
            scale.set(secs)
        finally:
            self._suppress_scale_cb = False

    def _on_download_scale(self, which: str, value: str) -> None:
        """A position slider moved — write its timecode into the matching
        Start/End field (0:00:00 stays the 'unset' sentinel).

        If the user drags one knob past the other, keep the visible range
        non-crossing by snapping the other knob to the same point. That keeps
        the UI readable even though the backend also sanitises invalid ranges.
        """
        if getattr(self, "_suppress_scale_cb", False):
            return
        # No probed video length → ignore stray drags (a disabled ttk.Scale
        # still accepts the mouse, and the range would be a useless 0..1s).
        if getattr(self, "_download_duration", 0.0) <= 0:
            return
        from app.services.download_service import _fmt_timecode, _parse_timecode
        try:
            secs = float(value)
        except (TypeError, ValueError):
            return
        tc = _fmt_timecode(secs)
        if which == "start":
            self.download_start_time_var.set(tc)
            end_raw = ""
            try:
                end_raw = self.download_end_time_var.get()
            except Exception:  # noqa: BLE001
                end_raw = ""
            end_secs = _parse_timecode(end_raw)
            if end_secs is not None and end_secs > 0 and secs > end_secs:
                end_scale = getattr(self, "download_end_scale", None)
                self._suppress_scale_cb = True
                try:
                    self.download_end_time_var.set(tc)
                    if end_scale is not None:
                        end_scale.set(secs)
                finally:
                    self._suppress_scale_cb = False
        else:
            self.download_end_time_var.set(tc)
            start_raw = ""
            try:
                start_raw = self.download_start_time_var.get()
            except Exception:  # noqa: BLE001
                start_raw = ""
            start_secs = _parse_timecode(start_raw)
            if start_secs is not None and start_secs > 0 and secs < start_secs:
                start_scale = getattr(self, "download_start_scale", None)
                self._suppress_scale_cb = True
                try:
                    self.download_start_time_var.set(tc)
                    if start_scale is not None:
                        start_scale.set(secs)
                finally:
                    self._suppress_scale_cb = False

    def cancel_download(self, task: VideoDownloadTask) -> None:
        task.cancelled = True
        # Clear any pause hold so the (now cancelled) task can't be mistaken
        # for resumable, and a stale torn-down "paused" event can't resurrect
        # it (the _finish stale-pause guard only spares running/waiting).
        task.paused = False
        task.status = "cancelled"
        # Freeze the Elapsed column at the cancel moment.
        if task.end_time is None:
            task.end_time = time.time()
        # Snapshot task.process ONCE: the download worker thread can null it
        # (in _run_task's finally / _media_phase / _subtitle_phase) between
        # the truthiness test and the .poll() call, which on the shared
        # attribute would dereference None -> AttributeError on the Tk thread.
        proc = task.process
        if proc is not None and proc.poll() is None:
            # Tree-kill so the ffmpeg merge/extract child dies with yt-dlp;
            # otherwise it keeps the .part/output handle open and the
            # follow-up unlink/replace can fail with PermissionError.
            try:
                kill_process_tree(proc, force=False)
            except Exception:  # noqa: BLE001
                pass
        # If the download had already handed off to auto-transcribe, stop
        # that too and unlink it — otherwise the transcription keeps running
        # and finish_task would later overwrite this "cancelled" status.
        tr = getattr(task, "transcription_task", None)
        if tr is not None:
            task.transcription_task = None
            try:
                tr.source_download = None
                self.cancel(tr)
            except Exception:  # noqa: BLE001
                pass
        self.refresh_download_queue()

    def remove_download(self, task: VideoDownloadTask) -> None:
        if task in self.download_queue:
            self.download_queue.remove(task)
        self.refresh_download_queue()

    def pause_download(self, task: VideoDownloadTask) -> None:
        """R2 "pause" for a download = STOP-AND-CONTINUE (not a true freeze).

        yt-dlp has no live pause signal, so we tear the process down the
        same way ``cancel_download`` does (reusing kill_process_tree) BUT:
          * land on status "paused" (not "cancelled"),
          * KEEP the partial .part file so resume can continue it,
          * only HOLD a linked auto-transcribe (don't cancel it permanently).

        SMTV downloads can't be paused (no HTTP Range on the CDN stream), so
        the action bar disables Pause for them; this method also guards.
        """
        from app.services.download_service import _is_smtv_task
        # Only a RUNNING download can be paused. A not-yet-started "waiting"
        # download has no process to stop-and-continue, and pausing it would
        # just strand it in "paused" (the action bar offers Cancel for waiting
        # rows, not Pause). Mirrors download_button_states_for_status.
        if task.status != "running":
            return
        if _is_smtv_task(task):
            self.log("Pause is unavailable for SMTV downloads (no resume point).")
            return
        task.paused = True
        task.status = "paused"
        if task.end_time is None:
            task.end_time = time.time()
        # Snapshot once (see cancel_download): the worker thread may null
        # task.process between the test and the .poll(), which would raise
        # AttributeError on the Tk thread and skip the tree-kill.
        proc = task.process
        if proc is not None and proc.poll() is None:
            # Same tree-kill as cancel so the ffmpeg child dies with yt-dlp
            # and releases the .part handle — but we do NOT delete the .part.
            try:
                kill_process_tree(proc, force=False)
            except Exception:  # noqa: BLE001
                pass
        # Hold (don't cancel) any linked auto-transcribe: keep it referenced
        # so a resume can re-establish the hand-off. The download row stops
        # mirroring its progress because the status is no longer "transcribing".
        if self.download_current is task:
            self.download_current = None
        self.refresh_download_queue()
        # Let the next waiting download (if any) start now that this one
        # released the single-download slot.
        self.download_service.process_queue()

    def resume_download(self, task: VideoDownloadTask) -> None:
        """Re-enqueue a paused download so yt-dlp continues its .part.

        build_download_command passes ``-c``/``--continue``, so re-running
        the SAME task resumes from the existing fragment instead of
        restarting at zero. We don't build a fresh task (unlike _rerun_
        download) precisely so the partial keeps its identity.
        """
        if task.status != "paused":
            return
        task.paused = False
        task.cancelled = False
        task.status = "waiting"
        task.end_time = None
        if task not in self.download_queue:
            self.download_queue.append(task)
        self.refresh_download_queue()
        self.download_service.process_queue()

    # --- R2: always-visible Download action bar ------------------------------
    def _selected_downloads(self) -> list[VideoDownloadTask]:
        tree = getattr(self, "download_tree", None)
        if tree is None:
            return []
        return [
            t for t in (self.download_row_map.get(i) for i in tree.selection()) if t
        ]

    def _download_action_apply(
        self, fn: "Callable[[VideoDownloadTask], Any]"
    ) -> None:
        """Run a per-download handler over the current selection, then
        refresh the action-bar enabled state. Each handler already guards
        its own valid statuses, so we don't pre-filter here."""
        for t in list(self._selected_downloads()):
            try:
                fn(t)
            except Exception:  # noqa: BLE001
                pass
        self._update_download_action_bar()

    def _download_action_open(self) -> None:
        """Open button — opens the saved file of a finished download, else
        falls back to its download folder."""
        for t in list(self._selected_downloads()):
            saved = getattr(t, "saved_path", None)
            if t.status == "finished" and saved and os.path.isfile(saved):
                self._open_file(saved)
            elif getattr(t, "folder", ""):
                self._open_folder(t.folder)

    def _update_download_action_bar(self) -> None:
        """Enable/disable Download action-bar buttons for the selection.

        Recomputed on <<TreeviewSelect>> and inside refresh_download_queue
        (which rebuilds the tree each tick) so a row whose status flipped
        never leaves a stale button enabled. Uses the same pure helper
        (download_button_states_for_status) as the design contract."""
        buttons = getattr(self, "download_action_buttons", None)
        if not buttons:
            return
        from app.services.download_service import _is_smtv_task
        from app.widgets.tabs import (
            DOWNLOAD_ACTION_KEYS,
            download_button_states_for_status,
        )

        merged = {k: False for k in DOWNLOAD_ACTION_KEYS}
        for t in self._selected_downloads():
            saved = getattr(t, "saved_path", None)
            has_file = bool(saved) and os.path.isfile(saved) if saved else False
            states = download_button_states_for_status(
                getattr(t, "status", ""),
                is_smtv=_is_smtv_task(t),
                has_saved_file=has_file,
            )
            for k, v in states.items():
                if v:
                    merged[k] = True
        for key, btn in buttons.items():
            if merged.get(key):
                btn.state(["!disabled"])
            else:
                btn.state(["disabled"])

    def pause(self, t: TranscriptionTask) -> None:
        # Only a task actually running on a worker can be paused.
        # Pausing a still-"waiting" task would flip it to "paused", and
        # dispatch_waiting only picks up "waiting" — it would never run.
        if t.status != "running":
            return
        t.paused = True
        t.status = "paused"
        # Cooperative: the worker's reader thread flips its task.paused
        # and the transcriber waits between segments.
        self.transcription_service.send_control(t, "pause")
        self.refresh()

    def resume(self, t: TranscriptionTask) -> None:
        if t.status != "paused":
            return
        t.paused = False
        t.status = "running"
        self.transcription_service.send_control(t, "resume")
        self.refresh()

    def cancel(self, t: TranscriptionTask) -> None:
        # Terminal-status guard (mirrors pause()/resume()): a right-click menu
        # left open while the task finished could otherwise flip a just-
        # completed task back to "cancelled".
        if getattr(t, "status", "") in ("finished", "cancelled", "error"):
            return
        t.cancelled = True
        t.status = "cancelled"
        # Freeze the Elapsed column at the cancel moment so the user
        # sees how long the task actually ran before they stopped it.
        if getattr(t, "end_time", None) is None:
            t.end_time = time.time()
        # Cooperative cancel: tell the worker to stop at the next segment
        # boundary. The transcriber flushes a resumable checkpoint and the
        # worker emits "done", which finish_task() routes to release (and
        # retire, if temporary) the worker — so a partial run is no longer
        # lost the way a hard kill+restart lost it. The liveness watchdog
        # still reaps a worker that wedges instead of honouring the cancel.
        if not self.transcription_service.send_control(t, "cancel"):
            self.log("Cancelled (task was not yet running on a worker).")
        else:
            self.log("Cancelling task; saving a resume checkpoint...")
        self.refresh()

    def remove_task(self, t: TranscriptionTask) -> None:
        if t in self.queue:
            self.queue.remove(t)
        self.refresh()

    # --- R2: always-visible Queue action bar ---------------------------------
    def _selected_tasks(self) -> list[TranscriptionTask]:
        """Tasks currently selected in the Queue Treeview (may be empty)."""
        tree = getattr(self, "tree", None)
        if tree is None:
            return []
        return [t for t in (self.row_map.get(i) for i in tree.selection()) if t]

    def _action_bar_apply(
        self, fn: "Callable[[TranscriptionTask], Any]", *, active_only: bool
    ) -> None:
        """Run a per-task handler over the current Queue selection.

        ``active_only`` restricts Pause/Cancel to waiting/running/paused
        rows; Re-run/Remove (active_only=False) apply to terminal rows.
        Shared by the action-bar buttons; mirrors the bulk context menu.
        """
        active = {"waiting", "running", "paused"}
        terminal = {"finished", "cancelled", "error"}
        wanted = active if active_only else terminal
        for t in list(self._selected_tasks()):
            if getattr(t, "status", "") in wanted:
                try:
                    fn(t)
                except Exception:  # noqa: BLE001
                    pass
        self._update_queue_action_bar()

    def _action_bar_resume(self) -> None:
        """Resume button — paused tasks resume in place; a cancelled task
        with a checkpoint re-enqueues from its partial (resume_task)."""
        for t in list(self._selected_tasks()):
            status = getattr(t, "status", "")
            if status == "paused":
                self.resume(t)
            elif status == "cancelled" and self._task_has_checkpoint(t):
                self.resume_task(t)
        self._update_queue_action_bar()

    def _update_queue_action_bar(self) -> None:
        """Enable/disable the Queue action-bar buttons for the selection.

        Recomputed on <<TreeviewSelect>> AND inside refresh() (which
        rebuilds the tree every tick), so the buttons never reflect a
        stale row. Uses the same button_states_for_status helper as
        menu_row. With a multi-row selection a button is enabled when it
        is valid for ANY selected row (matching the bulk menu).
        """
        buttons = getattr(self, "queue_action_buttons", None)
        if not buttons:
            return
        from app.widgets.tabs import QUEUE_ACTION_KEYS, button_states_for_status

        merged = {k: False for k in QUEUE_ACTION_KEYS}
        for t in self._selected_tasks():
            states = button_states_for_status(
                getattr(t, "status", ""), self._task_has_checkpoint(t)
            )
            for k, v in states.items():
                if v:
                    merged[k] = True
        for key, btn in buttons.items():
            if merged.get(key):
                btn.state(["!disabled"])
            else:
                btn.state(["disabled"])

    def queue_status_cell_click(self, event: tk.Event) -> None:
        """Single-click on a running/paused row's Status or Progress cell
        toggles pause/resume — a discoverable shortcut on top of the menu.

        Other cells / statuses fall through so normal row selection still
        works (this is bound additively with ``add="+"``).
        """
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        # columns are ("file","status","progress","language","time")
        # -> status is #2, progress is #3.
        if col not in ("#2", "#3"):
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        task = self.row_map.get(item)
        if not task:
            return
        # pause()/resume() call refresh(), which delete()s and re-inserts every
        # row. Doing that from INSIDE the <Button-1> handler mutates the tree
        # while the click is still being dispatched (the iid under the pointer
        # is gone mid-event). Defer to after_idle so the click finishes
        # dispatching first, then the tree rebuilds cleanly.
        if task.status == "running":
            self.after_idle(lambda: self.pause(task))
        elif task.status == "paused":
            self.after_idle(lambda: self.resume(task))

    def clear_completed(self) -> None:
        self.queue[:] = [t for t in self.queue if t.status not in ("finished", "cancelled", "error")]
        self.refresh()

    def clear_completed_downloads(self) -> None:
        """Download-tab counterpart to clear_completed() above -- the
        Queue tab has always had this; the Download tab didn't."""
        self.download_queue[:] = [
            t for t in self.download_queue if t.status not in ("finished", "cancelled", "error")
        ]
        self.refresh_download_queue()

    # Video tiling ------------------------------------------------------------
    def _save_tiling_prefs(self) -> None:
        """Persist the Video Tiling tab choices to config.

        Mirrors the Tk vars into ``app_config`` and saves. Surfaces a save
        failure in the status line rather than letting the choice silently
        revert on the next launch.
        """
        self.app_config["tiling_quality"] = self.tiling_quality_var.get()
        self.app_config["tiling_mute"] = bool(self.tiling_mute_var.get())
        self.app_config["tiling_multi_monitor"] = bool(
            self.tiling_multi_monitor_var.get()
        )
        self.app_config["tiling_auto_restart"] = bool(
            self.tiling_auto_restart_var.get()
        )
        # Persist the grid size too (it was never saved/restored). The Spinbox
        # is free-text editable, so .get() can raise TclError on junk — keep the
        # prior saved value in that case rather than crashing the save.
        try:
            from core.tiling import clamp_divisions
            self.app_config["tiling_divisions"] = clamp_divisions(
                self.tiling_divisions_var.get()
            )
        except (tk.TclError, ValueError):
            pass
        self.app_config["tiling_selected_monitors"] = list(
            getattr(self, "tiling_selected_monitors", [])
        )
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not save tiling settings: {e}")

    def refresh_tiling_monitor_info(self) -> None:
        """Update the detected-monitors info line under the tiling controls."""
        try:
            from core.monitors import list_monitors
            mons = list_monitors()
            sel = [
                m for m in mons
                if m["index"] in getattr(self, "tiling_selected_monitors", [])
            ]
            txt = ", ".join("#{}".format(m["index"] + 1) for m in sel) or "none"
            self.tiling_monitors_info_var.set(
                f"Detected {len(mons)} monitor(s).  "
                f"Selected for multi-monitor: {txt}"
            )
        except Exception:  # noqa: BLE001
            pass

    def identify_tiling_monitors(self) -> None:
        """Flash each monitor's number on its own borderless overlay (~2.5s)."""
        try:
            from core.monitors import list_monitors
            wins: list[tk.Toplevel] = []
            for m in list_monitors():
                w = tk.Toplevel(self)
                w.overrideredirect(True)
                w.geometry(
                    "{w}x{h}+{x}+{y}".format(
                        w=m["width"], h=m["height"], x=m["x"], y=m["y"]
                    )
                )
                w.configure(bg="black")
                try:
                    w.attributes("-topmost", True)
                except Exception:  # noqa: BLE001
                    pass
                tk.Label(
                    w, text=str(m["index"] + 1), fg="#39d0ff", bg="black",
                    font=("Helvetica", 240, "bold"),
                ).pack(expand=True)
                wins.append(w)
            self.after(2500, lambda: [w.destroy() for w in wins])
        except Exception as e:  # noqa: BLE001
            self.log(f"Identify monitors failed: {e}")

    def choose_tiling_monitors(self) -> None:
        """Modal chooser: tick which monitors get a tiled-playback window."""
        from core.monitors import describe, list_monitors
        monitors = list_monitors()
        dlg = tk.Toplevel(self)
        dlg.title("Select monitors")
        dlg.transient(self)
        dlg.grab_set()
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        ttk.Label(
            dlg, text="Tick the monitors to use for tiled playback:",
        ).pack(padx=12, pady=(12, 6), anchor="w")
        rows: list[tuple[int, tk.BooleanVar]] = []
        current = getattr(self, "tiling_selected_monitors", [])
        for m in monitors:
            var = tk.BooleanVar(value=(m["index"] in current))
            ttk.Checkbutton(dlg, text=describe(m), variable=var).pack(
                padx=18, pady=2, anchor="w"
            )
            rows.append((m["index"], var))

        def set_all(value: bool) -> None:
            for _, v in rows:
                v.set(value)

        def apply_sel() -> None:
            chosen = [idx for idx, v in rows if v.get()]
            if not chosen:
                messagebox.showwarning(
                    "Monitors", "Please tick at least one monitor.", parent=dlg
                )
                return
            self.tiling_selected_monitors = chosen
            if len(chosen) > 1:
                self.tiling_multi_monitor_var.set(True)
            self._save_tiling_prefs()
            self.refresh_tiling_monitor_info()
            dlg.destroy()

        helpers = ttk.Frame(dlg)
        helpers.pack(pady=(8, 0))
        ttk.Button(
            helpers, text="Select all", command=lambda: set_all(True)
        ).pack(side="left", padx=6)
        ttk.Button(
            helpers, text="Select none", command=lambda: set_all(False)
        ).pack(side="left", padx=6)
        ttk.Button(
            helpers, text="Identify", command=self.identify_tiling_monitors
        ).pack(side="left", padx=6)
        btns = ttk.Frame(dlg)
        btns.pack(pady=12)
        ttk.Button(btns, text="OK", width=10, command=apply_sel).pack(
            side="left", padx=10
        )
        ttk.Button(btns, text="Cancel", width=10, command=dlg.destroy).pack(
            side="left", padx=10
        )

    def _tiling_status(self, message: str, color: str) -> None:
        """Status callback for the tiling engine (called from its worker
        thread). Marshals the widget update onto the Tk main thread, applying
        BOTH the text and the engine's state colour (green Playing / orange
        Reconnecting / grey Stopped) so the status line reflects health at a
        glance instead of a fixed grey."""
        def _apply() -> None:
            self.tiling_status_var.set(f"Tiling: {message}")
            label = getattr(self, "tiling_status_label", None)
            if label is not None:
                try:
                    label.configure(foreground=color or "#666")
                except Exception:  # noqa: BLE001
                    pass
        self.post_to_main(_apply)

    def _tiling_log(self, msg: str) -> None:
        """Log callback for the tiling engine. The engine calls this from its
        daemon worker thread (every stream drop / reconnect / self-heal), so
        it must be marshalled onto the Tk main thread — App.log writes the
        console Text widget directly and Tk is not thread-safe."""
        self.post_to_main(lambda: self.log(msg))

    def start_tiling(self) -> None:
        # A cleared / non-numeric Grid spinbox makes IntVar.get() raise
        # tk.TclError ("expected floating-point number"), which would surface
        # as a confusing "Could not start tiling" message. Default to 3 (the
        # engine also clamps to 1–64); mirrors _save_server_prefs' guarded get.
        try:
            divisions = self.tiling_divisions_var.get()
        except (tk.TclError, ValueError):
            divisions = 3
        try:
            self.tiling.start(
                self.tiling_url_var.get(),
                divisions,
                quality=self.tiling_quality_var.get(),
                mute=bool(self.tiling_mute_var.get()),
                multi_monitor=bool(self.tiling_multi_monitor_var.get()),
                selected_monitors=list(
                    getattr(self, "tiling_selected_monitors", [])
                ),
                auto_restart=bool(self.tiling_auto_restart_var.get()),
                log=self._tiling_log,
                status=self._tiling_status,
            )
            self._save_tiling_prefs()
        except (FileNotFoundError, RuntimeError) as e:
            self.tiling_status_var.set(str(e))
        except Exception as e:  # noqa: BLE001
            self.tiling_status_var.set(f"Could not start tiling: {e}")
            self.log(f"Tiling error: {e}")

    def stop_tiling(self) -> None:
        try:
            self.tiling.stop()
        except Exception:  # noqa: BLE001
            pass
        self.tiling_status_var.set("Stopped.")

    def download_ffplay(self) -> None:
        """Download ffplay for Video Tiling on a daemon thread (P4-5).

        ffplay isn't bundled; when a download URL is configured for this
        platform (``config['ffplay_downloads']``) this fetches it into the
        app's bin/ dir. The blocking download runs off-thread; progress + the
        success/failure result are marshalled back to the Tk main thread via
        post_to_main — this method NEVER touches Tk from the worker thread.
        """
        from core.tiling import download_ffplay as _download_ffplay

        btn = getattr(self, "tiling_download_ffplay_btn", None)
        try:
            if btn is not None:
                btn.config(state="disabled", text="Downloading ffplay…")
        except Exception:  # noqa: BLE001
            pass
        self.tiling_status_var.set("Downloading ffplay…")

        def _progress(msg: str) -> None:
            self.post_to_main(lambda m=msg: self._on_ffplay_progress(m))

        def _worker() -> None:
            ok = _download_ffplay(progress_cb=_progress, config=self.app_config)
            self.post_to_main(lambda: self._on_ffplay_done(ok))

        import threading as _threading
        _threading.Thread(target=_worker, daemon=True).start()

    def _on_ffplay_progress(self, msg: str) -> None:
        self.tiling_status_var.set(msg)
        self.log(msg)

    def _on_ffplay_done(self, ok: bool) -> None:
        from core.tiling import ffplay_available

        btn = getattr(self, "tiling_download_ffplay_btn", None)
        if ok and ffplay_available():
            # Hide the whole notice (label + button) — ffplay is here now.
            notice = getattr(self, "tiling_ffplay_notice", None)
            if notice is not None:
                try:
                    notice.pack_forget()
                except Exception:  # noqa: BLE001
                    pass
            self.tiling_status_var.set("ffplay is ready — you can start tiling.")
        else:
            if btn is not None:
                try:
                    btn.config(state="normal", text="Download ffplay")
                except Exception:  # noqa: BLE001
                    pass
            messagebox.showwarning(
                "Download ffplay",
                "Could not download ffplay automatically. You can put "
                "ffplay in the app's bin folder manually (it ships with the "
                "full ffmpeg build).",
                parent=self,
            )

    # Web / LAN access server -------------------------------------------------
    def _save_server_prefs(self) -> None:
        """Persist the port / share-on-LAN / token choices."""
        try:
            port = int(self.server_port_var.get())
        except (tk.TclError, ValueError):
            port = 8765
        port = port if 1 <= port <= 65535 else 8765
        self.app_config["server_port"] = port
        self.app_config["server_share_lan"] = bool(self.server_share_lan_var.get())
        self.app_config["server_token"] = self.server_token_var.get().strip()
        self.app_config["server_https_enabled"] = bool(
            self.server_https_enabled_var.get())
        self.app_config["server_webhook_url"] = (
            self.server_webhook_url_var.get().strip())
        try:
            save_config(self.app_config)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to save web/LAN server preferences")
            self.log(f"Could not save Web / LAN settings: {e}")

    def _server_is_running(self) -> bool:
        h = self._server_handle
        return h is not None and h.is_running()

    def toggle_server(self) -> None:
        """One-click Start/Stop for the web / LAN server (idempotent).

        The bind + (first-time) model load happen on a daemon thread so
        the UI never freezes; the result is marshalled back onto the Tk
        main thread via post_to_main. Re-entrancy is guarded by
        ``_server_busy`` so a double-click can't start two servers.
        """
        if self._server_busy:
            return
        self._save_server_prefs()
        if self._server_is_running():
            self._stop_server_async()
        else:
            self._start_server_async()

    def _start_server_async(self) -> None:
        import threading as _t

        try:
            port = int(self.server_port_var.get())
        except (tk.TclError, ValueError):
            port = int(self.app_config.get("server_port", 8765))
        # Clamp an out-of-range typed port (0, >65535, negative) to the
        # default, mirroring _save_server_prefs. _save_server_prefs only
        # clamps app_config; it does NOT rewrite server_port_var, so without
        # this the raw typed value would flow into find_available_port, which
        # rejects it and silently binds a random ephemeral port instead.
        port = port if 1 <= port <= 65535 else 8765
        share_lan = bool(self.server_share_lan_var.get())
        token = self.server_token_var.get().strip()
        https = bool(self.server_https_enabled_var.get())
        webhook_url = self.server_webhook_url_var.get().strip()
        max_upload_mb = int(self.app_config.get("server_max_upload_mb", 512))

        self._server_busy = True
        self.server_toggle_btn.config(state="disabled")
        self.server_status_var.set("Starting...")
        self.server_url_var.set("")

        def _work() -> None:
            try:
                from core.server import HOST_LAN, HOST_LOOPBACK, ServerHandle
                host = HOST_LAN if share_lan else HOST_LOOPBACK
                handle = ServerHandle()
                # Register the handle BEFORE start(). start() can block on a
                # model load ("Starting…"); if the user quits during that
                # window, _shutdown_server_on_exit must already see the handle
                # so it can stop it. The handle is start-idempotent and
                # is_running() stays False until the serve thread is alive, so
                # an early stop() on a not-yet-started handle is a safe no-op.
                self._server_handle = handle
                # auto_port: if the chosen port is busy the handle falls
                # back to a free one rather than failing — we report what
                # it actually bound.
                handle.start(host, port, token, max_upload_mb=max_upload_mb,
                             https=https, webhook_url=webhook_url)
                urls = handle.urls()
                bound_port = handle.port
                self.post_to_main(
                    lambda: self._on_server_started(urls, bound_port, share_lan)
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("Web / LAN server failed to start")
                msg = str(e)
                self.post_to_main(lambda: self._on_server_failed(msg))

        _t.Thread(target=_work, name="server-start", daemon=True).start()

    def _stop_server_async(self) -> None:
        import threading as _t

        handle = self._server_handle
        self._server_busy = True
        self.server_toggle_btn.config(state="disabled")
        self.server_status_var.set("Stopping...")

        def _work() -> None:
            try:
                if handle is not None:
                    handle.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Web / LAN server failed to stop cleanly")
            finally:
                self._server_handle = None
                self.post_to_main(self._on_server_stopped)

        _t.Thread(target=_work, name="server-stop", daemon=True).start()

    def _on_server_started(
        self, urls: list[str], port: int, share_lan: bool
    ) -> None:
        self._server_busy = False
        # Reflect the port the server actually bound (auto-port fallback).
        # save_config can raise OSError/PermissionError (disk full, an
        # antivirus lock on config.json, a read-only profile); that must NOT
        # skip the button-re-enable / status / url updates below — otherwise
        # the server is live but its only toggle stays greyed out and the
        # status is stuck "Starting...". So catch OSError too AND persist
        # only after the UI is restored.
        try:
            if int(self.server_port_var.get()) != port:
                self.server_port_var.set(port)
                self.app_config["server_port"] = port
                try:
                    save_config(self.app_config)
                except OSError:
                    logger.exception("Failed to persist auto-bound server port")
        except (tk.TclError, ValueError):
            pass
        self.server_toggle_btn.config(
            text="Stop web access", state="normal")
        self.server_open_btn.config(state="normal")
        primary = urls[0] if urls else f"http://127.0.0.1:{port}/"
        if share_lan and len(urls) > 1:
            self.server_status_var.set(
                "Running. On this PC and on your network.")
            self.server_url_var.set(
                f"This PC:  {urls[0]}\nNetwork:  {urls[1]}")
        elif share_lan:
            # LAN sharing was requested but the network address could not be
            # determined (LAN-IP detection failed — no active network
            # interface, VPN-only, etc.). The server is bound on all
            # interfaces and IS reachable from the network if you know this
            # PC's IP; we just can't display it. Say so distinctly instead of
            # the misleading "Running on this computer." (local-only) line.
            self.server_status_var.set(
                "Running. Network sharing on, but your network address "
                "couldn't be detected.")
            self.server_url_var.set(primary)
        else:
            self.server_status_var.set("Running on this computer.")
            self.server_url_var.set(primary)
        self.log(f"Web / LAN access started: {primary}")

    def _on_server_failed(self, message: str) -> None:
        self._server_busy = False
        self._server_handle = None
        self.server_toggle_btn.config(text="Start web access", state="normal")
        self.server_open_btn.config(state="disabled")
        self.server_status_var.set("Off")
        self.server_url_var.set("")
        messagebox.showerror(
            "Could not start web access",
            f"The web / LAN server could not start.\n\n{message}",
            parent=self,
        )

    def _on_server_stopped(self) -> None:
        self._server_busy = False
        self.server_toggle_btn.config(text="Start web access", state="normal")
        self.server_open_btn.config(state="disabled")
        self.server_status_var.set("Off")
        self.server_url_var.set("")
        self.log("Web / LAN access stopped.")

    def open_server_in_browser(self) -> None:
        """Open the loopback URL in the default browser."""
        handle = self._server_handle
        if handle is None or not handle.is_running():
            return
        import webbrowser
        urls = handle.urls()
        if urls:
            try:
                webbrowser.open(urls[0])
            except Exception:  # noqa: BLE001
                logger.exception("Could not open browser")

    def _shutdown_server_on_exit(self) -> None:
        """Best-effort synchronous stop of the server during app exit."""
        handle = self._server_handle
        if handle is None:
            return
        try:
            handle.stop(timeout=3.0)
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping web / LAN server on exit")
        self._server_handle = None

    # Rendering ---------------------------------------------------------------
    def fmt_time(self, t: Any) -> str:
        if not getattr(t, "start_time", None):
            return ""
        # Freeze at end_time once the task is in a terminal state
        # (finished / cancelled / error). Before this, the Elapsed
        # column kept incrementing forever — the user never saw
        # "this file took 1m 22s", just a number that grew while
        # they were doing something else.
        end = getattr(t, "end_time", None)
        if end is not None:
            s = end - t.start_time
        else:
            s = time.time() - t.start_time
        s = max(0.0, s)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        return f"{h:02}:{m:02}:{sec:02}"

    def _download_row_progress(self, task: Any) -> float:
        # While an auto-transcribe runs, the download row mirrors the
        # linked transcription's live progress (else it sits at 100%).
        tr = getattr(task, "transcription_task", None)
        if task.status == "transcribing" and tr is not None:
            return tr.progress
        return task.progress

    def _row_progress_text(self, status: str, progress: float) -> str:
        """Progress text for a queue row: the real bar, or an indeterminate
        marquee while the row is working but has no percentage yet (e.g.
        during the model load before the first segment)."""
        from app.widgets.tabs import marquee_cell, progress_cell

        if status in ("running", "transcribing") and (progress or 0) <= 0:
            return marquee_cell(getattr(self, "_anim_frame", 0), progress)
        return progress_cell(progress)

    def _ensure_animation(self) -> None:
        """Start the marquee loop if any row is working without a real %."""
        if getattr(self, "_anim_running", False):
            return
        needs = any(
            t.status == "running" and (t.progress or 0) <= 0 for t in self.queue
        ) or any(
            d.status in ("running", "transcribing")
            and (self._download_row_progress(d) or 0) <= 0
            for d in self.download_queue
        )
        if needs:
            self._anim_running = True
            self._animate_tick()

    def _animate_tick(self) -> None:
        from app.widgets.tabs import marquee_cell

        self._anim_frame = getattr(self, "_anim_frame", 0) + 1
        bar = marquee_cell(self._anim_frame)
        active = False
        for item_id, t in list(getattr(self, "row_map", {}).items()):
            if t.status == "running" and (t.progress or 0) <= 0:
                active = True
                try:
                    self.tree.set(item_id, "progress", bar)
                except tk.TclError:
                    pass
        for item_id, d in list(getattr(self, "download_row_map", {}).items()):
            if d.status in ("running", "transcribing") and (self._download_row_progress(d) or 0) <= 0:
                active = True
                try:
                    self.download_tree.set(item_id, "progress", bar)
                except tk.TclError:
                    pass
        if active:
            self.after(250, self._animate_tick)
        else:
            self._anim_running = False

    def refresh(self) -> None:
        from app.widgets.tabs import status_label

        # Snapshot the SELECTED tasks (by identity) before we tear the tree
        # down: refresh() runs every 500ms via loop(), and a plain
        # delete()+re-insert() assigns brand-new iids, wiping the Treeview
        # selection. With the selection gone _update_queue_action_bar() below
        # would see nothing selected and disable every Pause/Resume/Cancel/
        # Re-run/Remove button ~0.5s after the user clicks a row — making the
        # action bar unusable. We restore the selection onto the new iids so
        # it survives the rebuild.
        prev_selected = self._selected_tasks()
        self.tree.delete(*self.tree.get_children())
        self.row_map = {}
        for t in self.queue:
            lang = getattr(t, "detected_language", "") or ""
            prob = getattr(t, "language_probability", None)
            lang_str = f"{lang} ({prob * 100:.0f}%)" if (lang and isinstance(prob, (int, float))) else lang
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    os.path.basename(t.file_path),
                    status_label(t.status),
                    self._row_progress_text(t.status, t.progress),
                    lang_str,
                    self.fmt_time(t),
                ),
            )
            self.row_map[item_id] = t
        # Re-select the same task objects on their new iids (no-op when the
        # selection was empty or its tasks left the queue).
        restore = _iids_for_tasks(self.row_map, prev_selected)
        if restore:
            self.tree.selection_set(restore)
        # Empty-state hint visibility — show when the queue is empty,
        # hide once there is at least one task. Kept here (rather than
        # in tabs.py) because refresh is the choke point for queue
        # changes, so the placeholder can't drift out of sync.
        if hasattr(self, "queue_empty_label"):
            if self.queue:
                self.queue_empty_label.pack_forget()
            else:
                self.queue_empty_label.pack(fill="x", pady=(2, 0))
        # Reflect work-in-progress in the window title so users with
        # the app minimised see "Whisper — 34% transcribing foo.mp4"
        # in their taskbar / Alt-Tab.
        self._refresh_window_title()
        self._ensure_animation()
        # Recompute the action-bar enabled state AFTER the selection is
        # restored: refresh rebuilds the tree every tick, so a row whose
        # status flipped (e.g. running->finished) must not leave the buttons
        # reflecting the old status, and a still-selected row must keep them
        # enabled.
        self._update_queue_action_bar()

    def refresh_download_queue(self) -> None:
        from app.widgets.tabs import status_label

        # Snapshot the SELECTED tasks (by identity) before tearing the tree
        # down -- same rationale as refresh() above: a plain delete()+
        # re-insert() assigns brand-new iids, wiping the selection and
        # disabling the Pause/Resume/Cancel action bar mid-download, since
        # this runs on every drained download event (frequent while a
        # download is active), not just periodically.
        prev_selected = self._selected_downloads()
        self.download_tree.delete(*self.download_tree.get_children())
        self.download_row_map = {}
        for task in self.download_queue:
            # While auto-transcribe runs, mirror the linked transcription's
            # live progress on the download row (otherwise a finished
            # download would sit at 100% and look idle while it transcribes).
            prog = self._download_row_progress(task)
            item_id = self.download_tree.insert(
                "",
                "end",
                values=(
                    task.title,
                    task.url,
                    task.format_label,
                    status_label(task.status),
                    self._row_progress_text(task.status, prog),
                    self.fmt_time(task),
                ),
            )
            self.download_row_map[item_id] = task
        # Re-select the same task objects on their new iids (no-op when the
        # selection was empty or its tasks left the queue).
        restore = _iids_for_tasks(self.download_row_map, prev_selected)
        if restore:
            self.download_tree.selection_set(restore)
        self._refresh_window_title()
        self._ensure_animation()
        self._update_download_action_bar()

    # -- UX helpers (Phase v0.7.1 — user-friendly result surfacing) ----------

    def _refresh_window_title(self) -> None:
        """Update the Tk window title so the taskbar / Alt-Tab reflects state.

        Idle: "Whisper Transcriber Suite".
        One running task: "Whisper Transcriber Suite — 34% transcribing foo.mp4".
        Multiple running: "Whisper Transcriber Suite — 2 tasks (avg 41%)".
        """
        running = [t for t in self.queue if t.status == "running"]
        running_dl = [
            d for d in self.download_queue if d.status == "running"
        ]
        # Sync the tray icon colour to current activity.
        if self.tray is not None:
            try:
                self.tray.set_active(bool(running or running_dl))
            except Exception:  # noqa: BLE001
                pass
        if not running and not running_dl:
            self.title(self._base_title)
            return
        if running and not running_dl and len(running) == 1:
            t = running[0]
            self.title(
                f"{self._base_title} — {t.progress}% transcribing "
                f"{os.path.basename(t.file_path)}"
            )
            return
        if running_dl and not running and len(running_dl) == 1:
            d = running_dl[0]
            self.title(
                f"{self._base_title} — {d.progress}% downloading "
                f"{d.title[:40] if d.title else d.url[:40]}"
            )
            return
        total = len(running) + len(running_dl)
        all_p = [t.progress for t in running] + [d.progress for d in running_dl]
        avg = sum(all_p) // len(all_p) if all_p else 0
        self.title(f"{self._base_title} — {total} tasks (avg {avg}%)")

    def show_last_result(self, task: "TranscriptionTask") -> None:
        """Populate the Transcribe-tab Last Result card.

        Called by TranscriptionService.finish_task when a job
        completes successfully. Lists every output file that
        actually exists on disk next to the input, with sizes and
        one-click "Open" buttons. Also offers a single "Open folder"
        button as a shortcut.
        """
        from app.widgets.tabs import _fmt_bytes

        if not hasattr(self, "last_result_frame"):
            return

        try:
            self.last_result_empty_label.pack_forget()
        except Exception:  # noqa: BLE001
            pass

        # Wipe any previous result card body and rebuild from scratch
        # — simpler than diff-updating a handful of widgets.
        for child in list(self.last_result_body.winfo_children()):
            child.destroy()
        try:
            self.last_result_body.pack_forget()
        except Exception:  # noqa: BLE001
            pass

        base, _ = os.path.splitext(task.file_path)
        folder = os.path.dirname(task.file_path) or "."
        # Prefer the exact files the worker reported writing — that
        # covers docx/pdf/md and the de-duped "name (1).srt" form the
        # hard-coded candidate list below would miss (a docx-only run
        # used to show "no output files found" despite a clean write).
        written = getattr(task, "output_paths", None)
        if written:
            existing = [p for p in written if os.path.isfile(p)]
        else:
            candidates = [
                f"{base}.{ext}"
                for ext in ("srt", "json", "vtt", "tsv", "txt", "lrc", "docx", "pdf", "md")
            ]
            existing = [p for p in candidates if os.path.isfile(p)]

        ttk.Label(
            self.last_result_body,
            text=f"✓ {os.path.basename(task.file_path)}",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w")
        if existing:
            ttk.Label(
                self.last_result_body,
                text=f"Saved {len(existing)} output file"
                     f"{'' if len(existing) == 1 else 's'} in {folder}",
                foreground="#666",
            ).pack(anchor="w", pady=(2, 6))

            files_frame = ttk.Frame(self.last_result_body)
            files_frame.pack(fill="x")
            for path in existing:
                row = ttk.Frame(files_frame)
                row.pack(fill="x", pady=1)
                size = _fmt_bytes(os.path.getsize(path))
                ttk.Label(
                    row, text=f"• {os.path.basename(path)}  ({size})"
                ).pack(side="left")
                ttk.Button(
                    row, text="Open",
                    command=lambda p=path: self._open_file(p),
                ).pack(side="right")
        else:
            ttk.Label(
                self.last_result_body,
                text="(no output files were found on disk — re-run the task?)",
                foreground="#a00",
            ).pack(anchor="w")

        button_row = ttk.Frame(self.last_result_body)
        button_row.pack(anchor="w", pady=(8, 0))
        ttk.Button(
            button_row, text="Open folder",
            command=lambda: self._open_folder(folder),
        ).pack(side="left")
        # "View transcript" launches the in-app viewer with the JSON
        # next to the source media (or the file picker if no JSON
        # found). Discoverable single click into the new viewer.
        json_output = next(
            (p for p in existing if p.lower().endswith(".json")), None
        )
        if json_output is not None:
            ttk.Button(
                button_row, text="View transcript",
                command=lambda jp=json_output: self.open_transcript_viewer_for(
                    task.file_path, jp
                ),
            ).pack(side="left", padx=(8, 0))

        self.last_result_body.pack(fill="both", expand=True)
        # Chime + log so the user notices even if they're on another
        # tab. The bell is one short cross-platform beep; suppressed
        # when the View > Chime on completion toggle is off.
        if getattr(self, "chime_on_complete_var", None) is not None:
            try:
                if self.chime_on_complete_var.get():
                    self.bell()
            except Exception:  # noqa: BLE001
                pass
        # Native toast via the tray controller — visible even when the
        # window is minimised. Falls through silently if pystray /
        # Pillow aren't installed (tray controller is None) or the
        # user disabled tray support.
        if self.tray is not None:
            body = (
                f"Wrote {len(existing)} output file"
                f"{'' if len(existing) == 1 else 's'} for "
                f"{os.path.basename(task.file_path)}"
            )
            try:
                self.tray.notify("Whisper Transcriber Suite — transcription done", body)
            except Exception:  # noqa: BLE001
                pass
        self.log(
            f"Done: {os.path.basename(task.file_path)} → "
            f"{len(existing)} file(s) in {folder}"
        )
        # Auto-switch back to the Transcribe tab when a job finishes
        # so the user lands on the Last Result card (file paths +
        # Open buttons) instead of having to manually switch from the
        # Queue tab. Mirrors the auto-switch to Queue when a
        # transcription starts.
        try:
            self.nb.select(self.t1)
        except Exception:  # noqa: BLE001
            pass

    def _open_file(self, path: str) -> None:
        """Open a single file with the OS default handler."""
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", path], check=False)
            else:
                import subprocess
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:  # noqa: BLE001
            show_error(
                self, "Open failed",
                "Could not open that file with your system's default app.",
                detail=str(e),
            )

    def _install_tray(self) -> None:
        """Bring up the system-tray icon if pystray + Pillow are present.

        The icon's right-click menu offers Show/Hide/Exit; the icon
        colour mirrors active/idle state. Failing imports silently
        leave ``self.tray = None`` so the rest of the app still
        boots in environments without tray support.
        """
        try:
            tray = TrayController(self)
            if not tray.is_supported():
                logger.info("Tray icon unavailable: pystray or Pillow missing")
                self.tray = None
                return
            tray.start()
            self.tray = tray
            logger.info("Tray icon installed")
        except Exception as e:  # noqa: BLE001
            logger.warning("Tray icon failed to install: %s", e)
            self.tray = None

    def _restart_watched_folder(self) -> None:
        """(Re)start the watched-folder watcher from current config.

        The watcher class lives in ``core.watcher``; if the
        ``watchdog`` Python package isn't installed the call no-ops.
        Files dropped into the watched folder are auto-enqueued onto
        the transcription queue via a Tk-safe ``after()`` hop.
        """
        # Tear down any previous watcher so we don't leak observer
        # threads when the user picks a new folder in Advanced.
        if self._folder_watcher is not None:
            try:
                self._folder_watcher.stop()
            except Exception:  # noqa: BLE001
                pass
            self._folder_watcher = None

        if not bool(self.app_config.get("watched_folder_enabled", False)):
            return
        folder = str(self.app_config.get("watched_folder") or "").strip()
        if not folder or not os.path.isdir(folder):
            self.log(
                f"Watched folder ignored — not a directory: {folder!r}"
            )
            return

        def _on_new_file(path: str) -> None:
            # watchdog calls back from its own thread — DON'T touch Tk
            # from here. Calling self.after() off-thread raises
            # RuntimeError on Python 3.14 (and is undefined behaviour
            # on earlier 3.x). Instead push the path into a
            # thread-safe queue that the Tk main loop drains via
            # _drain_watched_paths.
            if self._closing:
                return
            try:
                self._watched_path_queue.put_nowait(path)
            except Exception:  # noqa: BLE001
                pass

        try:
            watcher = FolderWatcher(folder, _on_new_file)
            watcher.start()
        except Exception as e:  # noqa: BLE001
            self.log(f"Could not start folder watcher: {e}")
            return
        self._folder_watcher = watcher
        self.log(f"Watching folder for new media: {folder}")

    def _drain_watched_paths(self) -> None:
        """Drain the cross-thread queue of watched-folder paths.

        Runs on the Tk main thread (scheduled via after()). watchdog
        callbacks push into ``_watched_path_queue`` from their worker
        thread; this method dequeues + hands each path to
        ``_enqueue_watched_file`` (which is now safe because we're
        on the Tk thread). Re-arms itself every 250 ms while the
        app is alive.

        ``_enqueue_watched_file`` is wrapped in its own try/except so
        one path that keeps raising (e.g. a file the OS holds locked)
        can't stall every other path queued behind it on every single
        250 ms tick -- it used to share one try/except with the
        ``get_nowait()`` loop, so any exception from the enqueue call
        was caught the same way as the intended ``Empty``-means-stop
        signal, ending that tick's drain early.
        """
        if self._closing:
            return
        while True:
            try:
                path = self._watched_path_queue.get_nowait()
            except Empty:
                break
            try:
                self._enqueue_watched_file(path)
            except Exception:  # noqa: BLE001
                logger.exception("Watched-folder enqueue failed for %r", path)
        if not self._closing:
            try:
                self.after(250, self._drain_watched_paths)
            except Exception:  # noqa: BLE001
                pass

    # Update check ------------------------------------------------------------
    def _maybe_quiet_update_check(self) -> None:
        """Fire the silent launch-time GitHub update check, if eligible.

        Runs on the Tk main thread (scheduled via ``after``). Gated by
        ``update_check_enabled`` and a once-per-day throttle keyed on
        ``last_update_check`` (an ISO date). When eligible, the date is
        stamped immediately (so a second launch the same day won't
        re-check) and the network call runs on a daemon thread. The
        result only ever pops the "update available" prompt — it shows
        NOTHING when up to date, offline, or on a private repo.
        """
        if self._closing:
            return
        try:
            if not bool(self.app_config.get("update_check_enabled", True)):
                return
            from datetime import date
            today = date.today().isoformat()
            if (self.app_config.get("last_update_check") or "") == today:
                return  # already checked today
            # Stamp the date up-front so we throttle even if the check
            # races / fails; persist via save_config so it survives a
            # restart.
            self.app_config["last_update_check"] = today
            try:
                save_config(self.app_config)
            except Exception:  # noqa: BLE001
                logger.debug("Could not persist last_update_check", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("Quiet update-check gate failed", exc_info=True)
            return
        self._run_update_check(manual=False)

    def _check_for_updates_manual(self) -> None:
        """Help-menu "Check for updates..." — always runs, reports all cases."""
        self._run_update_check(manual=True)

    def _run_update_check(self, *, manual: bool) -> None:
        """Run core.updates.check_for_update on a daemon thread.

        The network call happens off the Tk thread (it can block for up
        to the urllib timeout); the result is marshalled back via
        :meth:`post_to_main` so all widget work stays on the main
        thread. ``manual`` controls whether the "up to date" /
        "couldn't reach the server" cases are surfaced (manual) or
        swallowed (the quiet launch check).
        """

        def _worker() -> None:
            from core import updates as _updates
            info = _updates.check_for_update()
            self.post_to_main(lambda: self._on_update_result(info, manual=manual))

        from core._threads import safe_thread
        safe_thread(_worker, name="update-check")

    def _on_update_result(self, info: object, *, manual: bool) -> None:
        """Show the appropriate dialog for an update-check result (main thread).

        ``info`` is a ``core.updates.UpdateInfo`` or ``None`` (typed as
        ``object`` here to keep this glue free of a hard import at the
        annotation site). On a found newer release we ask whether to open
        the download page; on a manual check we also report up-to-date /
        unreachable; the quiet launch check stays silent in those cases.
        """
        if self._closing:
            return
        from core.updates import RELEASES_PAGE_URL, UpdateInfo

        if info is None:
            if manual:
                messagebox.showinfo(
                    "Check for updates",
                    "Could not reach the update server.\n\n"
                    "Please check your internet connection and try again "
                    "later.",
                    parent=self,
                )
            return

        if not isinstance(info, UpdateInfo):  # defensive; never expected
            return

        if info.is_newer:
            open_page = messagebox.askyesno(
                "Update available",
                f"A newer version ({info.latest_tag}) is available — "
                f"you have v{_APP_VERSION}.\n\n"
                "Open the download page?",
                parent=self,
            )
            if open_page:
                import webbrowser
                webbrowser.open(info.html_url or RELEASES_PAGE_URL)
        elif manual:
            messagebox.showinfo(
                "Check for updates",
                f"You're on the latest version (v{_APP_VERSION}).",
                parent=self,
            )

    def _drain_main_calls(self) -> None:
        """Drain the cross-thread queue of main-thread callables.

        Runs on the Tk main thread (scheduled via after()). Any
        background thread that needs to touch widgets pushes a
        zero-arg callable into ``_main_thread_calls`` via
        :meth:`post_to_main`; this method dequeues and runs each on
        the Tk thread. Bounded to 64 calls per tick so a flood from
        a misbehaving thread can't stall the Tk loop.
        """
        if self._closing:
            return
        drained = 0
        while drained < 64:  # bound to keep the Tk loop responsive
            try:
                fn = self._main_thread_calls.get_nowait()
            except Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001
                logger.exception("Main-thread call raised")
            drained += 1
        if not self._closing:
            try:
                self.after(50, self._drain_main_calls)
            except Exception:  # noqa: BLE001
                pass

    def post_to_main(self, fn: Callable[[], None]) -> None:
        """Schedule ``fn`` on the Tk main thread from any thread.

        Safe to call from worker / background threads where
        ``self.after(0, fn)`` would either raise (Python 3.14) or
        silently no-op (older 3.x with off-thread Tk calls). The
        callable is drained by :meth:`_drain_main_calls` on the
        next Tk tick (≤ 50 ms).
        """
        try:
            self._main_thread_calls.put_nowait(fn)
        except Full:
            logger.warning("Main-thread call queue full; dropping callback")

    def _enqueue_watched_file(self, path: str) -> None:
        """Auto-enqueue a media file dropped into the watched folder.

        Mirrors the bookkeeping of App.add(): builds a
        TranscriptionTask, appends to the queue, refreshes the
        Treeview. Skips when the file is still being written (size
        keeps growing for a few seconds after the first detect on
        Windows).

        Deduplicated by path: Windows fires both ``on_created`` and
        ``on_modified`` for the same file (sometimes several of the
        latter as the writer flushes). Each invocation cancels any
        in-flight stability-check ladder for the same path before
        scheduling a fresh one, so we never enqueue the same file
        twice.
        """
        if self._closing:
            return
        if not os.path.isfile(path):
            return
        try:
            size1 = os.path.getsize(path)
        except OSError:
            return

        norm = os.path.normcase(os.path.abspath(path))
        # Cancel any prior stability-check ladder for this path so
        # we don't double-enqueue under rapid event bursts.
        prior = self._watched_after_ids.pop(norm, None)
        if prior is not None:
            try:
                self.after_cancel(prior)
            except Exception:  # noqa: BLE001
                pass

        def _check_stable_then_enqueue(prev_size: int) -> None:
            self._watched_after_ids.pop(norm, None)
            if self._closing:
                return
            try:
                size_now = os.path.getsize(path)
            except OSError:
                return
            if size_now != prev_size:
                # File still growing — re-schedule. Track the new id
                # so a later event can cancel us cleanly.
                try:
                    aid = self.after(1200, lambda: _check_stable_then_enqueue(size_now))
                    self._watched_after_ids[norm] = aid
                except Exception:  # noqa: BLE001
                    pass
                return
            # Don't re-enqueue a file we've already finished. Cheap
            # dedup: skip if any queue entry references the same
            # normalised path AND is not in a terminal state.
            for existing in self.queue:
                try:
                    if (os.path.normcase(os.path.abspath(existing.file_path)) == norm
                            and existing.status not in ("finished", "cancelled", "error")):
                        return
                except Exception:  # noqa: BLE001
                    continue
            # Lazy model load without freezing the UI. The watched-folder
            # tick runs on the Tk main thread, so a synchronous wait for
            # the model would freeze the app; spawn + await the worker via
            # after()-polling instead and enqueue once it's ready.
            base = os.path.basename(path)

            def _do_enqueue() -> None:
                task = TranscriptionTask(path)
                self.queue.append(task)
                self.refresh()
                self.log(f"Watched: enqueued {base}")

            self._when_worker_ready(
                _do_enqueue,
                on_timeout=lambda: self.log(
                f"Watched: skipped {base} — model load timed out {HEADLESS_READY_TIMEOUT_S} s"
                ),
                loading_label=f"will transcribe {base} when ready.",
            )

        try:
            aid = self.after(1200, lambda: _check_stable_then_enqueue(size1))
            self._watched_after_ids[norm] = aid
        except Exception:  # noqa: BLE001
            pass

    def _maybe_offer_crash_resume(self) -> None:
        """If history.db flagged any rows interrupted on launch, offer
        to re-enqueue the still-existing files."""
        history = getattr(self, "history", None)
        if history is None:
            return
        try:
            rows = history.list_transcriptions(limit=200) or []
        except Exception:  # noqa: BLE001
            return
        interrupted = [
            r for r in rows
            if r.get("status") == "interrupted"
            and r.get("file_path")
            and os.path.isfile(r["file_path"])
        ]
        if not interrupted:
            return
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in interrupted:
            p = r["file_path"]
            if p not in seen:
                seen.add(p)
                unique.append(r)
        n = len(unique)
        # Pluralise verb + noun together so the message reads
        # correctly for both n=1 and n>1.
        noun = "transcription" if n == 1 else "transcriptions"
        verb = "was" if n == 1 else "were"
        pronoun = "it" if n == 1 else "them"
        if not messagebox.askyesno(
            "Resume interrupted transcriptions?",
            f"We found {n} {noun} that {verb} interrupted by a "
            f"previous crash. Resume {pronoun} now?",
            parent=self,
        ):
            # User declined — clear the interrupted flag on the rows we
            # offered so this prompt doesn't reappear on every launch.
            try:
                history.dismiss_interrupted_transcriptions(
                    [r["id"] for r in unique]
                )
            except Exception:  # noqa: BLE001
                logger.debug("Failed to dismiss interrupted rows", exc_info=True)
            # Also drop the on-disk partial checkpoints for the declined
            # files: declining means "don't resume", so the JSON (which can
            # be MBs of captured segments) is now dead weight. Without this
            # it lingered until the age-based startup sweep.
            try:
                from core import _checkpoint
                for r in unique:
                    _checkpoint.delete_checkpoint(r["file_path"])
            except Exception:  # noqa: BLE001
                logger.debug("Failed to delete declined checkpoints", exc_info=True)
            return
        # Crash-resume: if a partial checkpoint exists for any of
        # these interrupted files, flag the new task as a resume so
        # the worker reuses the on-disk segments instead of starting
        # over. Worker validation will fall back to a fresh
        # transcribe if the checkpoint is stale (different model,
        # mtime drift, etc.) so this is always safe to set when the
        # partial is present.
        # See _task_has_checkpoint: go straight to the lightweight
        # core._checkpoint module rather than core.transcriber, which
        # would force the heavy faster_whisper/ctranslate2 backend
        # import onto the Tk main thread for a plain file-existence check.
        try:
            from core import _checkpoint
            has_resumable_checkpoint = _checkpoint.has_checkpoint
        except Exception:  # noqa: BLE001
            has_resumable_checkpoint = lambda _p: False  # type: ignore[assignment]
        # Lazy model load without freezing the UI. This fires from a
        # startup after(), i.e. on the Tk main thread, so we spawn and
        # await the worker via after()-polling instead of a synchronous
        # wait (which froze the app while the model loaded). On timeout
        # the rows stay flagged interrupted for a later attempt.
        def _do_resume() -> None:
            resumed = 0
            for r in unique:
                task = TranscriptionTask(r["file_path"])
                lang = r.get("language") or ""
                if lang and hasattr(task, "language"):
                    task.language = lang  # type: ignore[attr-defined]
                try:
                    if has_resumable_checkpoint(r["file_path"]):
                        task.resume = True
                        resumed += 1
                except Exception:  # noqa: BLE001
                    pass
                self.queue.append(task)
            self.refresh()
            if resumed:
                self.log(
                    f"Re-enqueued {n} interrupted transcription(s) "
                    f"({resumed} will resume from checkpoint)"
                )
            else:
                self.log(f"Re-enqueued {n} interrupted transcription(s)")

        self._when_worker_ready(
            _do_resume,
            on_timeout=lambda: self.log(
                f"Crash-resume skipped: model load timed out "
                f"({n} task(s) not re-enqueued) — {HEADLESS_READY_TIMEOUT_S} s"
            ),
            loading_label=f"resuming {n} interrupted transcription(s) when ready.",
        )

    _CLIPBOARD_VK = {86: "paste", 67: "copy", 88: "cut", 65: "selectall"}

    @staticmethod
    def _clipboard_action(keysym: str, keycode: int) -> str | None:
        """Map a Ctrl+key press to a clipboard action, layout-independently.

        Returns None when Tk's own Latin-keysym binding already handles
        the key (English layout) — so we don't act twice — or when it
        isn't a clipboard key. Otherwise it dispatches by the physical
        key's keycode, which is identical whatever the active keyboard
        layout. This fixes paste / copy / cut / select-all under a
        non-Latin layout (Persian, Arabic, Russian, …), where Tk's
        built-in ``<Control-v>`` keysym binding never fires because the
        layout doesn't produce the Latin 'v' keysym.
        """
        if (keysym or "").lower() in ("a", "c", "v", "x"):
            return None
        return App._CLIPBOARD_VK.get(keycode)

    def _install_clipboard_keys(self) -> None:
        virt = {"paste": "<<Paste>>", "copy": "<<Copy>>", "cut": "<<Cut>>"}

        def _on_ctrl_key(event: tk.Event) -> str | None:
            action = self._clipboard_action(
                event.keysym or "", getattr(event, "keycode", -1)
            )
            if action is None:
                return None
            w = event.widget
            if action == "selectall":
                try:
                    w.select_range(0, "end")  # type: ignore[attr-defined]
                    w.icursor("end")  # type: ignore[attr-defined]
                    return "break"
                except (tk.TclError, AttributeError):
                    pass
                try:
                    w.tag_add("sel", "1.0", "end-1c")  # type: ignore[attr-defined]
                    return "break"
                except (tk.TclError, AttributeError):
                    pass
                return None
            try:
                w.event_generate(virt[action])
                return "break"
            except tk.TclError:
                return None

        self.bind_all("<Control-KeyPress>", _on_ctrl_key, add="+")

    def _install_text_context_menu(self) -> None:
        """Right-click Copy / Cut / Paste / Select all on every text field.

        A mouse-driven, keyboard-layout-independent way to use the
        clipboard. The keyboard shortcuts also work (see
        _install_clipboard_keys), but a right-click menu is what a
        non-technical user reaches for and it never depends on the active
        layout — e.g. selecting + copying the download-folder path. Bound
        on the Entry / Text widget classes so it covers every field; the
        Treeview queue menus use a different class and are unaffected.
        """
        def _popup(event: tk.Event) -> str:
            w = event.widget

            def _select_all() -> None:
                try:
                    w.select_range(0, "end")  # type: ignore[attr-defined]
                    w.icursor("end")  # type: ignore[attr-defined]
                except (tk.TclError, AttributeError):
                    try:
                        w.tag_add("sel", "1.0", "end-1c")  # type: ignore[attr-defined]
                    except (tk.TclError, AttributeError):
                        pass

            menu = tk.Menu(w, tearoff=0)
            menu.add_command(label="Cut", command=lambda: w.event_generate("<<Cut>>"))
            menu.add_command(label="Copy", command=lambda: w.event_generate("<<Copy>>"))
            menu.add_command(label="Paste", command=lambda: w.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="Select all", command=_select_all)
            try:
                w.focus_set()
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        for cls in ("TEntry", "Entry", "Text"):
            self.bind_class(cls, "<Button-3>", _popup, add="+")
            if sys.platform == "darwin":
                # macOS Tk reports right-click as Button-2, not Button-3.
                self.bind_class(cls, "<Button-2>", _popup, add="+")

    def _install_icon(self) -> None:
        """Set the window-title-bar + taskbar icon from ``assets/whisper.ico``.

        Cosmetic — silently no-ops when the file is missing so a
        damaged install never blocks launch.
        """
        if getattr(sys, "frozen", False):
            ico = os.path.join(
                os.path.dirname(os.path.abspath(sys.executable)),
                "assets", "whisper.ico",
            )
        else:
            ico = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "whisper.ico",
            )
        if not os.path.isfile(ico):
            return
        if sys.platform == "darwin":
            # iconbitmap(default=...) is not supported on macOS/Tk and
            # throws "wrong # args: should be 'wm iconbitmap window ?bitmap?'"
            return
        try:
            self.iconbitmap(default=ico)
        except tk.TclError as exc:
            logger.warning("Could not set window icon (%s): %s", ico, exc)

    def _apply_hidpi_scaling(self) -> None:
        """Bump Tk's pt→px scaling on high-DPI displays.

        Tk default is 72 dpi (1.0). Most modern Windows machines
        report 96 dpi (1.33). Computing from ``self.winfo_fpixels``
        gives the right factor on 125 % / 150 % Windows scaling, so
        the app's fonts and widget paddings keep their physical
        size rather than shrinking to the size of a 1 cm icon.
        """
        try:
            dpi = float(self.winfo_fpixels("1i"))
            if dpi <= 0:
                return
            scale = max(1.0, dpi / 72.0)
            self.tk.call("tk", "scaling", scale)
            logger.info("Tk scaling set to %.2f (%.0f dpi)", scale, dpi)
        except Exception as e:  # noqa: BLE001
            logger.info("Could not apply HiDPI scaling: %s", e)

    def _install_drag_drop(self) -> None:
        """Wire tkinterdnd2 if available, no-op otherwise.

        ``TkinterDnD._require(self)`` loads the Tcl ``tkdnd`` package
        into the interpreter but DOES NOT add the
        ``drop_target_register`` / ``dnd_bind`` methods to a plain
        ``tk.Tk`` instance — those live on ``TkinterDnD.DnDWrapper``.
        Mix the wrapper into our App's class so the methods become
        bound. Without this graft, drag-and-drop silently never
        registered in v0.7.1.
        """
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-not-found]
        except ImportError:
            logger.info("tkinterdnd2 not present; drag-and-drop disabled")
            return
        try:
            TkinterDnD._require(self)
            # Graft DnDWrapper's methods onto our class so this
            # instance gains drop_target_register / dnd_bind.
            wrapper = getattr(TkinterDnD, "DnDWrapper", None)
            if wrapper is not None and wrapper not in self.__class__.__mro__:
                self.__class__ = type(
                    self.__class__.__name__,
                    (self.__class__, wrapper),
                    {},
                )
            if not hasattr(self, "drop_target_register"):
                logger.warning(
                    "tkinterdnd2 imported but drop_target_register "
                    "is still missing; drag-and-drop disabled"
                )
                return
            self.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            logger.info("Drag-and-drop enabled (tkinterdnd2)")
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not initialise drag-and-drop: %s", e)

    def _on_drop(self, event: tk.Event) -> None:
        """Handle a drag-and-drop onto the window.

        tkinterdnd2 packs all dropped paths into a single string with
        space-or-brace separation. We split it with ``_split_dnd_paths``
        rather than ``self.tk.splitlist`` because Tcl's list parser
        collapses a UNC path's leading double-backslash down to a single
        one, which then fails the ``os.path.isfile`` gate and silently
        drops network-share files. ``self.tk.splitlist`` is kept as a
        fallback for any unexpected token shape, so behaviour is
        otherwise unchanged.
        Behaviour:
          - one file dropped → populate the Transcribe tab's file
            field
          - multiple files   → enqueue each as a Transcription task
            without further prompts
          - folder dropped   → its top-level media files are treated as
            a multi-file drop (empty folders are reported, not ignored)
          - URL dropped      → if it's a known download URL, paste
            into the Download tab's URL field
          - anything else    → reported in the log; a drop is never a
            silent no-op
        """
        raw = getattr(event, "data", "") or ""
        items = _split_dnd_paths(raw)
        if not items and raw.strip():
            # Helper found nothing in a non-empty payload — fall back to
            # Tcl's own splitter so we don't regress on an odd token shape.
            try:
                items = list(self.tk.splitlist(raw))
            except Exception:  # noqa: BLE001
                items = [raw]
        paths: list[str] = []
        urls: list[str] = []
        folders: list[str] = []
        unsupported: list[str] = []
        for item in items:
            s = item.strip()
            if not s:
                continue
            if s.startswith(("http://", "https://")):
                urls.append(s)
            elif s.startswith("file://"):
                # A file:// URI (some apps / file managers hand these to a
                # drop target) points at a local file. Convert it to a real
                # path and treat it like any other local file rather than
                # silently swallowing it.
                local = _file_uri_to_path(s)
                if local and os.path.isfile(local):
                    paths.append(local)
                else:
                    unsupported.append(s)
            elif os.path.isfile(s):
                paths.append(s)
            elif os.path.isdir(s):
                folders.append(s)
            else:
                # An unsupported scheme (ftp:, magnet:, smb:, …), a path
                # that no longer exists, or plain text. Don't pretend it
                # worked — note it so the drop isn't a silent no-op.
                unsupported.append(s)

        for folder in folders:
            found = _media_files_in_folder(folder)
            display = os.path.basename(folder.rstrip("\\/")) or folder
            if found:
                paths.extend(found)
                self.log(
                    f"Dropped folder {display}: queueing its "
                    f"{len(found)} media file(s)."
                )
            else:
                self.log(
                    f"Dropped folder {display} has no media files at its "
                    f"top level; nothing to queue."
                )

        if urls and hasattr(self, "download_url_var"):
            self.download_url_var.set(urls[0])
            self.nb.select(self.t3)
            self.log(f"Pasted URL into Download tab: {urls[0]}")
            if len(urls) > 1:
                # The Download tab takes one URL at a time; the rest of a
                # multi-URL drop would otherwise vanish without a trace.
                self.log(
                    f"Only the first of {len(urls)} dropped URLs was used; "
                    f"drop the others one at a time."
                )
        if paths:
            if len(paths) == 1:
                self.fv.set(paths[0])
                self.nb.select(self.t1)
                self.log(f"Picked: {os.path.basename(paths[0])} (drag-and-drop)")
            else:
                count = self._bulk_enqueue(paths)
                if count:
                    self.log(f"Enqueued {count} files via drag-and-drop")
        if unsupported:
            self.log(
                f"Ignored {len(unsupported)} dropped item(s) that aren't "
                f"usable (e.g. {unsupported[0]}). Drop a media file, a "
                f"folder of media files, or an http(s) URL."
            )
        elif not paths and not urls and not folders and raw.strip():
            # A non-empty payload that produced nothing actionable — e.g.
            # an empty selection. Without this the drop is a silent no-op
            # and the user can't tell what went wrong.
            self.log(
                "Nothing to do with that drop — drop a media file, a "
                "folder of media files, or an http(s) URL."
            )

    def _cancel_running(self) -> None:
        """Esc handler — cancel whichever single running task is most relevant.

        Confirms first: Esc is an easy accidental keystroke and the
        running task can be a long transcription, not something to
        drop with zero recovery on one stray tap.
        """
        for t in self.queue:
            if t.status == "running":
                if messagebox.askyesno(
                    "Cancel transcription?",
                    f"A transcription is running ({os.path.basename(t.file_path)}). Cancel it?",
                    parent=self,
                ):
                    self.cancel(t)
                return
        for d in self.download_queue:
            if d.status == "running":
                if messagebox.askyesno(
                    "Cancel download?",
                    "A download is running. Cancel it?",
                    parent=self,
                ):
                    self.cancel_download(d)
                return

    def _save_window_geometry(self) -> None:
        """Persist the window's current size + position in config.json."""
        try:
            geom = self.geometry()
        except Exception:  # noqa: BLE001
            return
        if not geom:
            return
        try:
            self.app_config["window_geometry"] = geom
            save_config(self.app_config)
        except Exception:  # noqa: BLE001
            pass

    def queue_row_double_click(self, event: tk.Event) -> None:
        """Double-click on a finished Queue row opens its folder.

        For waiting/running/error/cancelled rows the action is a
        no-op (no useful destination yet).
        """
        item = self.tree.identify_row(event.y)
        if not item:
            return
        task = self.row_map.get(item)
        if not task or task.status != "finished":
            return
        self._open_folder(os.path.dirname(task.file_path) or ".")

    def log(self, msg: str) -> None:
        self._ui_logger.info(msg)
        if hasattr(self, "txt") and self.txt is not None:
            insert_log_line(self.txt, msg)

    def log_threadsafe(self, msg: str) -> None:
        """Thread-safe wrapper around :meth:`log` for background threads.

        log() writes the console Text widget directly, and Tk is not
        thread-safe, so any background-thread caller (e.g. the Advanced
        dialog's install / model-download / cloud-key / gcloud-test workers)
        must marshal through here. Mirrors the post_to_main pattern already
        used by _offer_optional_install and the tiling callbacks."""
        self.post_to_main(lambda: self.log(msg))

    # Driver loops ------------------------------------------------------------
    def update_overall_progress(self) -> None:
        running = [t for t in self.queue if t.status == "running"]
        if not running:
            self.pb["value"] = 0
            return
        self.pb["value"] = sum(t.progress for t in running) / len(running)

    def loop(self) -> None:
        # Once shutdown starts, don't begin new subprocess work (a nested
        # "exit with queued tasks?" modal pumps the event loop, so this
        # after()-chain keeps firing during teardown otherwise). Audit P2-5.
        if self._closing:
            return
        self.refresh()
        self.transcription_service.dispatch_waiting()
        self.download_service.process_queue()
        self.after(500, self.loop)
