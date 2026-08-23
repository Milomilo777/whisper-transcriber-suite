# PROJECT INDEX — Whisper Transcriber Suite

> **Read this first.** Onboarding map for any coding agent (Claude Code, Codex, Cursor, Copilot, …) or human — written so you can understand the repo *without re-scanning it*, saving tokens and time.
>
> Semantic sections built **2026-07-04** by the `project-index` workflow. The Structure block at the bottom is regenerated deterministically (no AI) by `tools/index_refresh.py` — never hand-edit between the AUTO-INDEX markers.

## What it is
A Windows-first (also Linux and macOS) Tkinter desktop app that transcribes audio/video fully offline via faster-whisper plus 4 other pluggable ASR backends, downloads media through yt-dlp/Supreme Master TV, and exports transcripts to 13 subtitle/document formats.

Whisper Transcriber Suite is a drag-and-drop desktop app — a Windows Setup-Standard installer + Portable zip, a Linux source install (platform/linux/install.sh), and a macOS build (PyInstaller .app/.dmg, platform/macos/install.command, or Homebrew) — that transcribes audio/video fully offline using faster-whisper (CTranslate2) by default, with whisper.cpp, NVIDIA Parakeet, and two opt-in cloud backends (Gemini API, Google Cloud Speech-to-Text) selectable in Advanced settings. Each job can add VAD, word-level timestamps, speaker diarization, auto-chapters, and hallucination detection, then writes outputs in up to 13 formats (SRT/VTT/TSV/TXT/LRC/JSON/MD/DOCX/PDF/oTranscribe/ELAN/InqScribe/Express Scribe) — plus a separate "Convert transcript" picker that re-emits any existing transcript into those formats. It also downloads from any yt-dlp-supported site or a Supreme Master TV (SMTV) episode link with optional auto-transcribe, runs a live pausable/resumable Transcription Queue and Download queue, offers an in-app transcript viewer with VLC playback and karaoke word-highlighting, a multi-monitor "Video Tiling" live-stream video wall, and an optional stdlib-only LAN/web HTTP server for browser-based job submission on a trusted network. First launch downloads the ~3 GB Whisper model from a CDN mirror (MD5-verified, resumable); everything afterward is fully offline unless a cloud backend is deliberately chosen.

## Run it
```
Dev/source run: pip install -r requirements.txt && python gui.py  (or pip install -e .[dev] for an editable install with dev extras)
Headless one-shot transcription: python gui.py transcribe PATH\to\file.mp4 --language en --formats srt json docx [--diarization]
Optional LAN/web server: python gui.py serve (loopback only, no firewall prompt) or python gui.py serve --lan (binds 0.0.0.0)
Reset first-run state: python gui.py --safe-mode  (backs up %LOCALAPPDATA%\WhisperTranscriberSuite\config.json and re-fires the hub-folder picker)
Full local quality gate before committing: run_tests.bat  (pyright app core, must stay 0 errors/0 warnings/0 informations, then python -m pytest tests/ --ignore=tests/smoke -q)
Build the two shipped Windows deliverables: build_embed_installer.bat (produces embed_build\), then "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss for the Setup-Standard exe, then a shutil.make_archive zip of embed_build\ for the Portable zip — full recipe in docs/BUILD.md
Linux install: git clone https://github.com/Milomilo777/whisper-transcriber-suite.git && cd whisper-transcriber-suite && bash platform/linux/install.sh
macOS install: git clone https://github.com/Milomilo777/whisper-transcriber-suite.git && cd whisper-transcriber-suite && bash platform/macos/install.command
```

## Architecture
gui.py is a thin entry point (bare = launch the Tk app via app.run(); --worker = early-branch into core.worker.main() before argparse — a spawn-contract that must never be renamed/removed; transcribe FILE = headless CLI; serve = the HTTP job server; --safe-mode = config reset). app/app.py's App(tk.Tk) runs on the one Tk main thread, the only thread allowed to touch widgets; background work is bridged in via queue.Queue instances drained by after()-scheduled poll_*/loop() methods every 100-500ms. Two concurrency patterns: (1) transcription runs in long-lived subprocess workers (python gui.py --worker, core/worker.py) so the ~3 GB faster-whisper model loads once and stays hot — parent and worker speak newline-delimited JSON over stdin/stdout (actions transcribe/shutdown; events ready/started/progress/log/done/error/startup_error/worker_exit), guarded by a per-worker UUID token and a heartbeat so PID recycling or a wedged worker is detected; (2) yt-dlp.exe downloads run as short-lived per-task subprocesses whose stdout is regex-parsed for progress on a daemon thread. app/ is layered into services (download/format/transcription/integrations), domain (task models), widgets (tabs/console/tray), and dialogs (modal Toplevels); core/ is the Tk-free engine — config.py (three-layer merged config: local JSON > online allowlisted JSON > hardcoded defaults), model_manager.py/hub.py (resumable MD5-verified ZIP model download), transcriber.py orchestrating pluggable core/backends (faster_whisper, whisper_cpp, cloud_stt/Gemini, google_cloud_stt, nvidia_asr/Parakeet), pre/post-processing (alignment, diarization, chapters, hallucination, separator, voiceprint), pluggable core/writers (13 export formats), core/integrations (smtv scraper, otranscribe round-trip), an optional stdlib-only core/server package (httpd.py + jobs.py + static/index.html) for the LAN/web mode, and infra (history SQLite, logging_setup, watcher, recorder, tiling.py/monitors.py for the multi-monitor video wall, _proc/_threads). Packaging wraps this same source tree: Windows ships an embeddable-Python tree via Inno Setup (Setup-Standard) plus a Portable zip of that same tree; macOS builds a PyInstaller .app/.dmg (also installable from source via install.command or Homebrew); Linux is a source + venv install (install.sh).

**Tech stack:** Python 3.11-3.13, Tkinter + sv-ttk (theme) + tkinterdnd2 (drag-and-drop) for the GUI, faster-whisper / CTranslate2 (default ASR backend), Optional ASR backends: pywhispercpp (whisper.cpp), NVIDIA Parakeet (transformers + torch + librosa), Gemini API (cloud_stt), google-cloud-speech + google-cloud-storage (google_cloud_stt), stable-ts (opt-in word-level alignment, pulls torch), sherpa-onnx (pyannote ONNX speaker diarization, no HF token needed), yt-dlp.exe + bundled ffmpeg/ffprobe (vendored binaries) for media download/merge, python-vlc (embedded transcript-viewer playback), python-docx + reportlab (DOCX/PDF writers), platformdirs, requests, watchdog (folder watcher), pystray + Pillow (system tray), psutil, screeninfo (multi-monitor detection for Video Tiling), SQLite (core/history.py), pytest + pytest-cov + responses, pyright (basic mode, 0 errors/0 warnings/0 informations gate on app/ and core/), GitHub Actions CI: Windows + Ubuntu unit-test matrix on every push/PR (ci.yml), manual-dispatch macOS .app/.dmg build + smoke test (macos-app.yml), Packaging: embeddable-Python tree + Inno Setup (Windows Setup-Standard/Portable), PyInstaller .spec files (macOS .app/.dmg; unshipped Windows onefile/onedir kept in lock-step), shell installers for Linux/macOS (install.sh/install.command) + a Homebrew formula, BSD-3-Clause license

## Key docs
| Doc | Covers |
|---|---|
| `README.md` | Product overview, feature list, two-deliverable model, first-run hub-folder setup, config key summary, docs index |
| `CLAUDE.md` | Durable session rules for AI agents: commit-often/push-batched/slow-release cadence, single master mainline, pre-authorised git/gh ops, English-only scope, pyright 0/0/0 gate |
| `docs/SESSION_HANDOFF_NEXT.md` | Read-first source of truth for current state, latest audit/work log, and what (if anything) is left to do |
| `docs/ARCHITECTURE.md` | Process/threading model, worker JSON-stdio protocol, queue table, cancellation contract — STALE: written against an older monolithic gui.py, predates the app/+core/ package refactor |
| `docs/CONFIG.md` | Full config.json field reference, including the three-layer merged config (local > online allowlist > hardcoded) and the model catalog |
| `docs/BUILD.md` | All build pipelines (embeddable-Python Standard+Portable, PyInstaller onefile/onedir) and which are actually shipped |
| `docs/SERVER.md` | Optional local-network/web HTTP server mode: routes, upload cap, token/password, security caveats |
| `docs/CLOUD_STT.md` | Optional Gemini-API cloud transcription backend (paste an API key) |
| `docs/CLOUD_STT_GOOGLE.md` | Optional full Google Cloud Speech-to-Text backend (service-account JSON, batch mode, speaker labels) |
| `docs/DECISIONS.md` | Architecture Decision Records — why subprocess workers, vendored yt-dlp, MD5 ZIP model distribution, Tkinter, etc. |
| `docs/TESTING.md` | How to run run_tests.bat, what the test files are, hermetic tests/ vs resource-heavy tests/smoke/ |
| `docs/RELEASE_PROCESS.md` | Ship sequence: version-bump locations, tagging, gh release create/edit, release-pruning policy |
| `docs/CHANGELOG.md` | Version history (current: 1.5.0, 2026-07-03 — project/repo renamed to whisper_app) |
| `platform/macos/README.md` | macOS install/build notes (install.command, Homebrew, PyInstaller .app/.dmg) — its 'not yet validated on a real Mac' banner is stale; CI now builds and smoke-tests real .dmg artifacts |
| `platform/linux/README.md` | Linux install/update/uninstall via install.sh (venv-based, desktop entry, whisper-transcriber-suite/whisper-transcribe launchers) |

## Onboarding tips
- docs/ARCHITECTURE.md is stale (describes a single monolithic gui.py); trust the real app/ (services/domain/widgets/dialogs) + core/ (backends/writers/integrations/server) package layout described above instead.
- platform/macos/README.md's 'groundwork, not yet validated on a real Mac' banner is also stale — the manual-dispatch macos-app.yml CI workflow now builds and smoke-launches real arm64/x86_64 .app/.dmg artifacts and they have shipped on the v1.5.0 GitHub release.
- Read docs/SESSION_HANDOFF_NEXT.md first every session — it is the owner's declared source of truth for current state and is meant to be updated again at session end.
- Quality gate before every commit: run_tests.bat = pyright app core (must stay 0 errors/0 warnings/0 informations) + python -m pytest tests/ --ignore=tests/smoke -q.
- tests/smoke/ is NOT hermetic — it needs the real ~3 GB Whisper model, a real local test video, and live network (SMTV E2E); it is skipped via env vars and never expected to run in CI or a clean checkout.
- gui.py --worker is a spawn-contract handled before argparse — never rename/remove it; every transcription path spawns <exe/python> --worker to run core/worker.py.
- Tkinter is single-threaded: only after()-scheduled poll_*/loop() methods on app/app.py's App may touch widgets; workers, yt-dlp reader threads, the folder watcher, and daemon threads only ever post onto queue.Queue instances (worker_events/download_events/format_events, plus _main_thread_calls for background threads that need the main thread).
- Adding a module under app/ or core/ requires updating the hidden-import lists in BOTH whisper_project_onefile.spec and whisper_project_onedir.spec so the unshipped Windows PyInstaller pipelines don't bit-rot, even though only the embeddable-Python Setup-Standard + Portable ship on Windows.
- Optional/heavy dependencies (pywhispercpp, NVIDIA Parakeet's transformers+torch+librosa, stable-ts, google-cloud-speech, pystray, tkinterdnd2, python-vlc, darkdetect, screeninfo) are all designed to degrade silently to a no-op or disabled feature when absent — core/optional_deps.py manages on-demand install; absence should never crash the app.
- core/llm.py (local Qwen2.5-1.5B summarize/action-items/Q&A/translate), core/chapters.py (auto-chapters), and core/search.py (full-text search) are fully implemented and wired into the pipeline per the last handoff audit, but currently have no discoverable UI entry point — check before assuming a similar feature needs to be built from scratch.
- The project/repo was renamed to whisper_app at v1.5.0 (2026-07-03); some docs (docs/INSTALL.md) still reference the pre-rename name, older version numbers, and older asset names — cross-check version-specific claims against docs/CHANGELOG.md or the live GitHub release before trusting them.
- English-only repository policy (per this repo's CLAUDE.md): no Persian/Arabic/RTL in app/core code, comments, or commit messages — even though the SMTV scraper itself accepts non-English content URLs.
- Building any new UI surface: reuse `app/widgets/tooltip.py` (`help_icon`, `section_labelframe`) for hover-help and `app/widgets/error_dialog.py` (`show_error`) for user-facing errors — both added 2026-07-18 specifically so this doesn't get reinvented per-dialog. See Gotchas below for the collision trap `section_labelframe` exists to avoid.

## Subsystems

### app-gui — `app/`
Tkinter desktop GUI layer of Whisper Transcriber Suite. The App(tk.Tk) root in app/app.py wires together services (transcription worker lifecycle, yt-dlp downloads, format lookup, integrations), Toplevel dialogs (Advanced settings, transcript viewer, hardware wizard, model download/loading, hub setup), and widgets (5 tabs: Transcribe, Transcription Queue, Download Videos, Video Tiling, Web/LAN access) into a single-window offline transcription + video-download app.

**Key files**
- `app/app.py` — The App(tk.Tk) god-object root: owns self.queue/self.download_queue, the 500ms loop() driver, thread-safe cross-thread bridges (post_to_main/_drain_main_calls), drag-and-drop, watched-folder, tray, crash-resume, menu, and window lifecycle (on_exit). ~4650 lines; tab widgets are forward-declared here as type annotations but actually assigned by app/widgets/tabs.py builders.
- `app/__init__.py` — Package doc + lazy run() entry point; uses module __getattr__ so `import app` alone does not pull in tkinter/faster-whisper until app.App/app.run() is actually touched.
- `app/observability.py` — Optional Sentry crash reporting + anonymous launch ping; strictly opt-in via config telemetry_opt_in AND env vars SENTRY_DSN / WHISPER_TELEMETRY_URL — a total no-op otherwise.
- `app/domain/tasks.py` — VideoDownloadTask model (status/progress/pause/section_start-end/history_id); re-exports TranscriptionTask from core.task.
- `app/domain/languages.py` — SUBTITLE_LANGUAGES display-name/code table + subtitle_lang_args() for yt-dlp --sub-langs.
- `app/services/transcription_service.py` — TranscriptionService: spawns/manages long-lived `python -m core.worker` (or `<exe> --worker`) subprocesses, dispatches queued tasks to idle workers, drains worker JSON stdout events, drives the device badge, model-loading modal, and telemetry stats.
- `app/services/download_service.py` — DownloadService: builds yt-dlp argv (incl. Supreme Master TV special-case with sibling parts), runs downloads in daemon threads, posts events to app.download_events, handles subtitle burn-in, pause/resume/cancel/re-run.
- `app/services/format_service.py` — FormatService: runs `yt-dlp --dump-single-json` (or the SMTV page scrape) on a daemon thread to populate the Download tab's audio/video format dropdowns; polls app.format_events.
- `app/services/integrations_service.py` — oTranscribe .otr <-> .srt round-trip import/export + opening the oTranscribe website.
- `app/dialogs/advanced.py` — AdvancedDialog: the single settings hub — VAD knobs, word-timestamps, output-format checkboxes, backend picker (faster-whisper/whisper.cpp/Gemini/Google Cloud STT/NVIDIA Parakeet), SponsorBlock categories, hardware-wizard + model-download launchers, watched-folder picker. ~1441 lines.
- `app/dialogs/transcript_viewer.py` — TranscriptViewer: segment list + optional embedded VLC playback, find/replace, speaker rename, filler-word removal, word-confidence colouring, karaoke word highlight; FindReplaceDialog companion class. ~1523 lines.
- `app/dialogs/model_download.py` — ModelDownloadDialog: modal progress UI driving core.model_manager.ensure_model; on ModelDestinationNotWritable/PermissionError, reopens HubSetupDialog to re-pick a writable folder and retries.
- `app/dialogs/model_loading.py` — ModelLoadingDialog: simpler modal shown while an already-downloaded model loads into a worker subprocess's RAM (vs. model_download.py which drives the byte download).
- `app/dialogs/hub_setup.py` — HubSetupDialog + ensure_hub_configured(): first-run 'where do models live' picker with a writability probe (creates+deletes a temp file) before persisting hub_folder.
- `app/dialogs/statistics.py` — show_statistics(): read-only summary (finished counts, total minutes, top languages) from HistoryDB, shown via messagebox.
- `app/widgets/tabs.py` — build_transcribe_tab / build_queue_tab / build_download_tab / build_tiling_tab / build_server_tab construct each tab onto the App instance and assign its *_var/*_combo attributes. Also hosts the pure, unit-tested button_states_for_status / download_button_states_for_status / progress_cell / marquee_cell helpers. ~1085 lines.
- `app/widgets/hardware_wizard.py` — HardwareWizard: probes acceleration tiers (CUDA/NPU/DirectML/CPU) off-thread, lets the user override the auto-pick and run an opt-in 5s benchmark, persists to hardware.json.
- `app/widgets/tray.py` — TrayController: pystray+Pillow system-tray icon (idle/active colour), minimise-to-tray; explicitly unsupported on macOS.
- `app/widgets/console.py` — build_console(): the read-only log Text widget + its Copy/Copy all/Clear right-click menu. Theme-aware (apply_console_theme(), matches app.py's Light/Dark/System toggle) and colours likely-failure lines red via insert_log_line()'s word-boundary regex match on "could not"/"failed"/"error" — see Gotchas.
- `app/widgets/platform.py` — open_folder(): cross-platform 'reveal in file manager' helper (os.startfile / open / xdg-open); routes failures through error_dialog.show_error() when it has a real Tk/Toplevel parent.
- `app/widgets/tooltip.py` — Shared hover-help helpers, added 2026-07-18: `bind_tooltip(widget, text_or_getter)` (the low-level yellow-popup binder — text may be a callable for dynamic content, e.g. the device badge; shows after a ~450ms grace delay and clamps/flips the popup to stay on-screen near the right/bottom edges — clamping is skipped on secondary monitors since winfo_screenwidth/height describe only the primary display), `help_icon(parent, text)` (a small "ⓘ" Label for next to an individual control), `section_labelframe(parent, title, help_text, **kwargs)` (builds a ttk.LabelFrame whose *title bar itself* carries the help icon via labelwidget= — the only correct way to add a hover-help icon to a LabelFrame's header; see Gotchas for why a place()-based corner badge is NOT safe).
- `app/widgets/error_dialog.py` — `show_error(parent, title, message, detail=None)`, added 2026-07-18: the app-wide convention for user-facing error dialogs — a plain-language sentence up front, with str(e)/traceback text (if any) behind a collapsible "Show details" (still copyable). Matches a native messagebox's contract: Enter/Esc dismiss, focus starts on OK, a red warning glyph + bell on open. Non-blocking (returns immediately, unlike messagebox) — every call site must be fire-and-return. Use this instead of `messagebox.showerror(title, str(e))` for anything a non-technical user might hit.

**Entry points**
- gui.py (repo root) -> app.run() -> App().mainloop() — default GUI launch
- app.run() / app.App — lazily imported via app/__init__.py's __getattr__
- gui.py --worker -> core.worker.main() — NOT in app/, but app/services/transcription_service.py hardcodes spawning exactly this subprocess shape ('do NOT remove or rename' per gui.py's own docstring)

**Commands**
```
python gui.py
python gui.py --safe-mode   (backs up config.json, forces first-run hub/model dialogs)
pyright app core   (must report 0 errors before every commit, per repo CLAUDE.md)
python -m pytest tests/ --ignore=tests/smoke -q   (hermetic unit suite; tests/app/test_transcription_service.py is the only app/-specific unit test file)
python -m pytest tests/smoke/test_app_headless.py   (real Tk App + real worker subprocess; needs a Whisper model on disk, skips otherwise)
run_tests.bat   (runs the two checks above and prints PASS/FAIL)
```

**Depends on**
- core/ (config, task, history, hub, logging_setup, paths, watcher, model_manager, hardware, tiling, server, updates, convert, burn_subs, _threads, _proc, _checkpoint, transcriber, worker, writers, stats, monitors, optional_deps, integrations.smtv, integrations.otranscribe) — app/ is a thin UI layer that must never duplicate core/'s business logic
- faster-whisper (only inside the core.worker subprocess; app/ never imports it directly)
- tkinter + ttk (stdlib) — single-threaded UI toolkit; the Tk main loop owns every widget call
- sv_ttk (light/dark theme), darkdetect (optional, system theme detection)
- tkinterdnd2 (optional; drag-and-drop — App grafts TkinterDnD.DnDWrapper onto its own class at runtime)
- pystray + Pillow (optional; system tray icon)
- python-vlc + a system/bundled libvlc (optional; embedded playback in TranscriptViewer)
- watchdog (via core.watcher.FolderWatcher; optional watched-folder automation)
- yt-dlp (bundled binary invoked as a subprocess by download_service.py / format_service.py — not a Python import)
- bundled ffmpeg/ffplay binaries via core.paths.bundled_binary (hardware-wizard benchmark clip, Video Tiling)

**Gotchas**
- Tk is single-threaded: every background thread (burn-subs worker, tray runner, hardware-wizard probe/benchmark, model-download, folder-watcher, launch-ping, download/transcription workers) MUST marshal back via App.post_to_main() (drained by _drain_main_calls every 50ms, capped at 64/tick) rather than calling self.after() off-thread — that raises RuntimeError on Python 3.14 (silently no-op on older 3.x). This pattern repeats across tray.py, hardware_wizard.py, download_service.py, transcription_service.py.
- Drag-and-drop payloads must be parsed with app.py's own _split_dnd_paths (brace/space-aware, backslash-preserving) instead of Tk.splitlist — Tcl's list parser collapses a UNC path's leading double-backslash to one, silently breaking \\server\share drops; file:// URIs (including UNC file://server/share) go through the separate _file_uri_to_path.
- App.refresh() (called every 500ms by loop()) fully destroys and rebuilds the queue Treeview each tick, which reassigns new iids and would otherwise wipe the user's row selection (breaking the per-task action bar). Selection is preserved via the pure, unit-tested _iids_for_tasks() which maps old task objects (by id()) onto their new iids — any rewrite of refresh() must keep this snapshot/restore step.
- button_states_for_status() / download_button_states_for_status() in app/widgets/tabs.py are the SINGLE SOURCE OF TRUTH for which Pause/Resume/Cancel/Re-run/Remove/Open actions are valid per status. Both the right-click menu (App.menu_row / download_menu_row) and the always-visible action bar call these — never re-derive the status logic in a second place or the two will drift.
- TranscriptionService talks to a long-lived `python -m core.worker` (or `<frozen-exe> --worker`) subprocess over JSON-lines stdin/stdout. transcribe_command() is the one place that must carry every field the worker needs (language, resume, clip_start/clip_end, output_formats); a field omitted here is invisible both to the worker AND to helper-level tests — this exact class of bug shipped before (docx silently not written).
- HEADLESS_READY_TIMEOUT_S in transcription_service.py is deliberately 1200s on macOS vs 120s elsewhere (slow VM/CI model loads) — do not collapse this into one constant.
- App does NOT preload/standby the Whisper model at startup (v1.0.3 change, comment explicitly warns against re-adding it) — the model loads lazily on first Transcribe click via ensure_worker_ready(), showing ModelLoadingDialog. Eager preload previously cost ~1.5GB idle RAM + a CPU spike on every launch even when transcription was never used.
- App.on_exit() has a strict teardown order: confirm-if-active-tasks -> set self._closing=True (the ONLY gate letting loop()/_drain_main_calls/_drain_watched_paths keep re-arming their after() chains; only reset in __init__) -> save window geometry -> stop folder watcher -> stop tray -> kill_process_tree() on download subprocesses -> stop tiling -> shut down the web server -> transcription_service.stop_all() -> close history DB -> self.destroy(). Reordering can leak subprocesses or corrupt history.db's WAL.
- _exit_from_tray flag: File->Exit / Ctrl+Q / tray 'Exit' set it True to bypass the minimise-to-tray redirect. If the user declines the 'exit with queued tasks?' confirm dialog, the handler must reset _exit_from_tray back to False, otherwise the window's X button permanently stops honouring minimise-to-tray for the rest of the session.
- System tray (pystray) is explicitly disabled on macOS (TrayController.is_supported() returns False) because pystray's AppKit backend needs the main thread's run loop, which Tk already owns.
- Most App tab-widget attributes (fv, pb, tree, row_map, every *_var/*_combo, etc.) are only forward-declared as class-level type annotations in app.py — the real assignment happens inside the build_*_tab functions in app/widgets/tabs.py. Don't assume app.py itself initialises them.
- TranscriptViewer's embedded VLC playback is fully optional (_locate_vlc_dir / _try_load_vlc probe several install locations) and must degrade to an 'Open in system player' button, never crash, when python-vlc or the native libvlc DLL is missing.
- The console Text widget (app/widgets/console.py) is toggled state='disabled' between writes; its Clear handler must flip to 'normal', delete, then restore the PREVIOUS state, or the log becomes permanently editable.
- app/__init__.py uses TYPE_CHECKING + a module __getattr__ specifically so `import app` alone does not eagerly import tkinter/faster-whisper — only app.App / app.run() triggers it. Don't convert this back to an eager top-of-file import.
- Every preference-toggle save_config() call (theme, chime, tiling, server prefs, recent-files dismiss list) is individually wrapped in try/except and logged rather than allowed to raise — an uncaught exception inside a Tk callback surfaces as a cryptic background-exception dialog or silently truncates the rest of the callback.
- 'Clear list' under File > Recent files does NOT delete history.db rows (HistoryDB has no clear method and is owned by core/); it stores a recent_files_dismissed set in config.json and filters the menu, so a later transcription of a previously-dismissed path makes it reappear by design.
- Adding a new module/import under app/ must also update the hidden-import lists in BOTH whisper_project_onefile.spec and whisper_project_onedir.spec (per repo root CLAUDE.md) even though neither PyInstaller pipeline currently ships, to avoid silent bit-rot.
- Cross-thread event queues (worker_events, format_events, download_events, _watched_path_queue, _main_thread_calls) are all bounded at maxsize=2000 — producers get Full/drop rather than unbounded growth; this is deliberate backpressure, not a bug to 'fix' by making them unbounded.
- Adding a hover-help icon to a `ttk.LabelFrame`? Use `section_labelframe()` from `app/widgets/tooltip.py`, NOT a hand-rolled `icon.place(relx=1.0, anchor="ne")` corner badge. A place()-based badge only avoids overlapping real content when a section's first grid/pack row happens not to reach the frame's right edge — a full-width Label, a `sticky="ew"` widget, or a value/button in the last column all break that assumption. This was a real, confirmed bug (2026-07-18): 5 separate sections in tabs.py/advanced.py had a badge sitting directly on top of real content, found by measuring actual rendered widget bounding boxes against each other on a live Tk instance, not by eyeballing a screenshot. `section_labelframe()` puts the icon in the LabelFrame's title bar via `labelwidget=`, which Tk keeps structurally separate from grid/pack content — this class of bug is structurally impossible with it.
- The main App window, AdvancedDialog, and TranscriptViewer all have `self.minsize(...)` now (added 2026-07-18, matching each window's own computed default/floor size) — do not remove it. Before this, all three were resizable with no floor, so a user (or a stale saved `window_geometry`) could shrink any of them below the width their own layout needs; `pack(side="left")` rows don't wrap, they silently clip instead of erroring. AdvancedDialog's minsize is screen-aware (uses the same already-clamped width/height its own geometry() call computed), so it can't force a genuinely small screen's window wider than that screen allows.
- To verify a Tkinter layout change actually fits (no clipping/overflow), measure a REAL running Tk instance's `winfo_reqwidth()`/`winfo_width()`/`winfo_y()` directly — don't guess from reading the code. Force the dialog/window to a candidate size with `.geometry(...)`, `pump()` a few `update()` calls, then read the real geometry attributes; for screen-size-dependent code, monkey-patch `tk.Misc.winfo_screenwidth`/`winfo_screenheight` before constructing the widget to simulate a specific screen (e.g. a common 1366x768 laptop) rather than relying on the dev machine's own (often much wider) real display.
- Screenshotting the real app for a VISUAL check (not just geometry numbers) is possible and sometimes necessary — e.g. confirming a hover-tooltip popup actually renders, not just that its Toplevel object exists — but the window MUST be forced to the true OS foreground first, or `PIL.ImageGrab`/`PrintWindow` silently captures whatever unrelated window (File Explorer, the terminal, ...) happens to be on top instead (a real incident, both in the 2026-07-18 UI-readability work, which discarded the screenshot unread, and again in the 2026-08-15 hover-help session, which at first got a File-Explorer screenshot back with zero indication anything was wrong). The fix, confirmed working: `tk_window.lift()` + `wm frame` to get the real HWND, then Win32 `ShowWindow`/`BringWindowToTop`/`SetForegroundWindow` wrapped in `AttachThreadInput` (bypasses Windows' foreground-lock heuristic for a background-launched process) + `tk_window.focus_force()`, THEN pump `update()` a few times before screenshotting. For hover tests specifically, drive the mouse with real OS input (`ctypes user32.SetCursorPos`, or `SendInput` for full realism) rather than Tk's synthetic `event_generate('<Enter>')` — the 2026-08-15 session found a real discoverability bug (tiny, low-weight hover icon) that every earlier synthetic-event-based verification had missed specifically because it never modeled what a real user's mouse actually has to land on.
- Any user-facing error handler (a `try/except` around a file/subprocess/network operation that can plausibly fail) should call `app/widgets/error_dialog.show_error(parent, title, friendly_message, detail=str(e))` — not `messagebox.showerror(title, str(e))`. Dumping a raw Python exception as the entire dialog body is a real anti-pattern that shipped in 9 separate places before a 2026-07-18 sweep fixed them; a fresh multiline grep for `messagebox\.(showerror|showwarning)\([^,]+,\s*str\(` is the fastest way to check for new instances.
- The LAN web page (`core/server/static/index.html`) is plain vanilla JS that builds rows via string concatenation into `innerHTML`. EVERY value that originates from a job — `source`, `error`, output `name`, `formats`, transcript text/speaker — is attacker-influenceable on a shared network (a hostile video title / URL / filename) and MUST be wrapped in the page's `escapeHtml()` before it lands in `innerHTML`; numeric values used in a `style="width:…"` must go through `Number()`. This was a real 2026-07-18 fix (several sinks were unescaped). `escapeHtml` escapes `& < > " '`. Server-side (`normalize_formats`, filename sanitisation, uuid4 ids, `token_ok` via `hmac.compare_digest`) is the first line of defense; the client escaping is the second — keep both.

### core — `core/`
Tk-free transcription engine package: pluggable ASR backends, ~13 output-format writers, config/history/model-management, and optional features (diarization, alignment, LLM, search, recording, video tiling, an HTTP job server) that the Tk app (app/) and the CLI (gui.py) both drive without ever importing tkinter themselves.

**Key files**
- `core/transcriber.py` — Heart of the pipeline (~2060 lines). Module-global MODEL/PIPELINE/_ALT_BACKEND state; public API transcribe()/resume_transcription()/load_existing_model()/get_effective_device(). Normalizes language codes, builds transcribe kwargs, pre-slices clip/time-range audio via ffmpeg, drives periodic checkpointing, dispatches diarization/alignment/hallucination/chapters, and writes all requested output formats atomically.
- `core/worker.py` — Long-lived worker subprocess entry (main()). Reads one JSON command per stdin line, emits JSON events on stdout (ready/started/progress/done/error/language_detected/log/startup_error/heartbeat). A dedicated stdin-reader thread applies cancel/pause/resume immediately; transcribe/shutdown go through a queue to the main loop.
- `core/task.py` — TranscriptionTask plain-data class: file_path, status/progress, cancelled/paused flags, clip_start/clip_end, output_formats, output_paths, history_id, detected_language.
- `core/config.py` — Three-layer effective config (local config.json > online app-config > hard-coded DEFAULT_CONFIG) via merge_config_sources()/load_config()/save_config(); platformdirs path helpers (user_config_dir/user_cache_dir/user_log_dir/user_data_dir); per-folder .whisperproject.json project overrides (load_project_overrides/merge_project_overrides).
- `core/__init__.py` — Single bundled __version__ source of truth (currently 1.5.0), read by the About dialog and telemetry.
- `core/history.py` — SQLite history.db (downloads + transcriptions tables) with WAL mode and integrity_check-on-open self-healing (corrupt DB renamed aside and recreated).
- `core/hardware.py` — Tier auto-probe (CUDA float16/int8_float16 -> QNN NPU -> OpenVINO -> DirectML -> CPU int8), hardware.json persistence, and detect_device_for() -- the single canonical (device, compute_type) resolver used by transcriber.py and backends/faster_whisper_be.py.
- `core/model_manager.py` — ensure_model(): download/MD5-verify/extract the ~3 GB faster-whisper model with a mirror-then-HuggingFace-fallback strategy. MODEL_REGISTRY + catalog_models()/catalog_resolve_entry() (online-catalog-augmentable) list every selectable model variant.
- `core/hub.py` — Model hub folder resolution: model_path (explicit override) > hub_folder + model name > default_hub_folder() (per-user cache, never Program Files).
- `core/_checkpoint.py` — Periodic JSON checkpoint for resume-after-cancel, keyed by sha1(normcased absolute source path) under user_data_dir()/partials/. validate_checkpoint() refuses a stale partial (backend/model/config-fingerprint/source size+mtime mismatch).
- `core/_proc.py` — kill_process_tree(): cross-platform process-TREE termination (Windows taskkill /T, POSIX os.killpg on a session the child leads) so ffmpeg/yt-dlp/demucs grandchildren are never orphaned.
- `core/_threads.py` — safe_thread(): threading.Thread wrapper that logs (rather than silently swallows) an uncaught exception in the target.
- `core/_errors.py` — fmt_err() / with_retries() shared error-formatting and retry-with-backoff helpers.
- `core/_liveness_tick.py` — liveness_tick() context manager: emits a periodic log line during a long silent GIL-holding C call so the parent's worker-liveness watchdog doesn't kill the worker mid-pass.
- `core/paths.py` — resource_base()/bundled_binary(): resolves bundled-asset paths across onefile-exe / onedir-exe / source runtime contexts.
- `core/logging_setup.py` — setup_logging(); worker_log_filename() gives each worker process its own log file (a shared RotatingFileHandler can't roll over cross-process on Windows).
- `core/optional_deps.py` — On-demand pip install of heavy extras (stable-ts, openai-whisper, google-cloud-speech/storage, transformers+torch+librosa) into user_cache_dir()/pylibs, staged then atomically merged with per-entry rollback; activate() appends (never prepends) to sys.path so a bundled copy always wins.
- `core/llm.py` — Local LLM panel: Qwen2.5-1.5B-Instruct via llama-cpp-python, download-on-first-use (~1 GB), singleton LLMRunner (summarise/action_items/ask/translate).
- `core/diarization.py` — Offline speaker diarization via sherpa-onnx (pyannote-segmentation + CAMPlus embedding ONNX models under bin/diarization/); diarize() + assign_speakers_to_segments().
- `core/alignment.py` — Word-timestamp refinement via stable-ts (DTW over cross-attention weights); refine_word_timestamps_in_place().
- `core/hallucination.py` — Heuristic hallucination flagging: bag-of-hallucinations phrase list, in-segment token/n-gram repetition, VAD-disagreement; annotate_segments() sets suspect/suspect_reason.
- `core/separator.py` — Demucs htdemucs vocal-separation pre-process; mtime+size cache keyed under user_cache_dir()/demucs with a byte-budget eviction (prune_cache).
- `core/voiceprint.py` — Cross-file speaker fingerprint DB (voices.db + pyannote/embedding); enrol_speaker()/match_vector()/relabel_segments() to turn per-file SPEAKER_NN labels into stable enrolled names.
- `core/chapters.py` — Auto-chapter boundary detection (long-silence heuristic) plus optional LLM-generated 4-7 word chapter titles; build_chapters().
- `core/search.py` — Search over saved transcripts: FTS5 (sqlite, always available) with an optional semantic layer (sentence-transformers embeddings) that is tried first and falls back to FTS5.
- `core/watcher.py` — FolderWatcher: watchdog-based auto-enqueue of media files dropped into a configured watched folder.
- `core/recorder.py` — Recorder: microphone (sounddevice) or Windows WASAPI system-audio loopback (pyaudiowpatch) capture, streaming straight to a mono 16kHz WAV (no whole-take RAM buffering).
- `core/monitors.py` — Tk-free multi-monitor detection (screeninfo -> ctypes Win32 EnumDisplayMonitors fallback -> single 1920x1080 fallback) feeding core.tiling's per-monitor ffplay placement.
- `core/tiling.py` — TilingController: one yt-dlp stream fanned out to an NxN-tile ffplay grid across one or more monitors, with self-healing reconnect/backoff and a yt-dlp -U self-heal after repeated failures.
- `core/burn_subs.py` — burn(): ffmpeg subtitle burn-in; copies the SRT to a graph-safe ASCII temp path before invoking the subtitles= filter to avoid libavfilter metacharacter injection from an attacker-influenced download title.
- `core/convert.py` — Format-to-format conversion via the universal segment-list middle representation. parse_to_segments() auto-detects json/srt/vtt/tsv/otr/eaf/inqscribe; convert_file() re-emits through core.writers (plus smtv_docx as the one binary target).
- `core/stats.py` — Opt-in (telemetry_opt_in) anonymous telemetry-stats POST to config['stats_url']; build_stats_payload() is a pure/testable payload builder, post_stats_async() fires on a daemon thread.
- `core/updates.py` — Tk-free GitHub 'update available' check (releases/latest); notify-only, never downloads/installs, silent on any failure including a private repo's 404.
- `core/backends/base.py` — Backend ABC + LanguageInfo dataclass -- the load()/is_ready()/transcribe_to_segments()/unload()/get_error() contract every engine implements.
- `core/backends/__init__.py` — get_backend(name) factory dispatching faster_whisper (default) / whisper_cpp / cloud_stt / google_cloud_stt / nvidia_asr; unknown names silently fall back to faster_whisper.
- `core/backends/availability.py` — ENGINE_CHOICES registry (label <-> transcribe_backend value) shared by the Transcribe-tab picker and Advanced dialog; engine_status()/engine_statuses() cheap-vs-deep readiness probes; default_engine() picks google_cloud_stt when a trusted build ships creds/gcloud_stt.json.
- `core/backends/faster_whisper_be.py` — Default CTranslate2 engine; thin adapter that owns its own model/pipeline state, with the same self-healing CUDA->CPU downgrade as transcriber.py.
- `core/backends/whisper_cpp.py` — pywhispercpp/ggml quantized engine (ggml-large-v3-q5_0.bin, ~1.1 GB) for weak CPUs; download_default_model() with a truncated-download completeness check.
- `core/backends/cloud_stt.py` — OPTIONAL Gemini-API cloud STT (paste-an-API-key, uploads audio to Google). Chunks audio to FLAC, uploads via the Files API or inlines small chunks, tracks cloud_stt_minutes_used locally (no dollar-balance API exists).
- `core/backends/google_cloud_stt.py` — OPTIONAL real Google Cloud Speech-to-Text v2 (service-account JSON, not an API key). STANDARD mode chunks+recognizes inline (~55s/chunk); BATCH mode needs a user GCS bucket, ~75% cheaper via DYNAMIC_BATCHING, up to 24h turnaround.
- `core/backends/nvidia_asr.py` — Local (fully offline) NVIDIA Parakeet ASR via Hugging Face transformers; transcribes window-by-window (default 30s), tries word timestamps once and falls back to per-window segments if the model rejects that path.
- `core/writers/__init__.py` — WRITERS (text) + BINARY_WRITERS (docx/pdf/smtv_docx) registries; get_writer()/get_binary_writer()/is_binary()/supported_formats() -- new output formats register here.
- `core/writers/base.py` — Shared writer helpers: fmt_srt_time/fmt_vtt_time/fmt_lrc_time (NaN/Inf-safe), normalize_text, sanitize_for_xml, escape_cue_separator, speaker_prefix.
- `core/writers/srt.py` — SubRip .srt text writer (escapes literal '-->' in cue text; speaker prefix).
- `core/writers/vtt.py` — WebVTT .vtt text writer; emits per-word karaoke <c> cues when a words list is present.
- `core/writers/tsv.py` — start/end(ms)/text TSV writer (Audacity Labels-compatible).
- `core/writers/txt.py` — Plain text writer: one segment per line, no timestamps (output-only, not in convert.PARSE_FORMATS).
- `core/writers/json_writer.py` — This app's canonical JSON sidecar writer (the 'middle format' every other writer/converter/viewer reads); allow_nan=False, carries words/speaker/suspect fields through.
- `core/writers/lrc.py` — LRC lyric-timestamp writer.
- `core/writers/md.py` — Markdown writer (heading + bold timestamp + optional speaker per line).
- `core/writers/otr.py` — oTranscribe .otr writer; delegates serialization to core.integrations.otranscribe.segments_to_otr().
- `core/writers/elan.py` — ELAN .eaf XML writer (TIME_ORDER/TIME_SLOT + ALIGNABLE_ANNOTATION), stdlib ElementTree only.
- `core/writers/inqscribe.py` — InqScribe writer: inline [hh:mm:ss.ff] centisecond timestamps.
- `core/writers/express_scribe.py` — Express Scribe writer: [hh:mm:ss] whole-second timestamps; EXPORT-ONLY, deliberately absent from convert.PARSE_FORMATS.
- `core/writers/docx_writer.py` — Binary Word writer via python-docx. write_bytes() is the real entry; write() deliberately raises RuntimeError so a caller that bypasses the binary path fails loudly.
- `core/writers/pdf_writer.py` — Binary PDF writer via reportlab; same write_bytes()-is-real / write()-raises pattern as docx_writer.
- `core/writers/smtv_docx_writer.py` — Fills the transcription team's exact bundled Word template (core/writers/templates/smtv_template.docx) byte-for-byte. Needs extra language/work_title kwargs beyond the frozen (segments, audio_path) contract, so transcriber._write_outputs and convert.convert_file special-case it by name.
- `core/integrations/otranscribe.py` — Bidirectional .otr <-> SRT/JSON converter: fmt_otr_time, srt_to_otr, whisper_json_to_otr, otr_to_srt, segments_to_otr (5-function public API; everything else private).
- `core/integrations/smtv.py` — Supreme Master TV episode scraper: regex-parses videoPlayerData / article-text out of an episode page over stdlib urllib -- no yt-dlp involved.
- `core/server/__init__.py` — ServerHandle (non-blocking start/stop wrapper running serve_forever on a daemon thread), run_server() (blocking 'gui.py serve' entry), find_available_port(), reachable_urls().
- `core/server/httpd.py` — Stdlib-only ThreadingHTTPServer + BaseHTTPRequestHandler exposing the job REST API (GET/POST /api/jobs...) and a static page; per-job advanced options are validated then written into a generated .whisperproject.json so the existing per-folder override mechanism scopes them to just that job.
- `core/server/jobs.py` — JobManager: bounded in-memory job table + a SINGLE background worker thread processing jobs sequentially (deliberate -- keeps the ~3GB model hot and avoids concurrent access to transcriber's module-global MODEL). is_safe_url() is a minimal SSRF guard (blocks loopback/link-local/metadata, allows RFC-1918 private ranges).

**Entry points**
- gui.py --worker  (spawns core.worker.main() as a JSON-stdio subprocess -- the frozen protocol every deliverable relies on)
- gui.py transcribe FILE [--language|-l CODE] [--formats|-f fmt...] [--diarization]  (one-shot CLI transcription via core.transcriber.transcribe, no UI)
- gui.py serve [--port|-p N] [--host ADDR] [--lan] [--token TOKEN] [--max-upload-mb N]  (runs core.server.run_server -- the optional LAN HTTP job server)
- core.transcriber.transcribe(task, progress_cb, log_cb, language_cb) / resume_transcription(...)  (the actual engine call every caller ultimately makes)
- core.model_manager.ensure_model(config, status_cb, progress_cb, cancel_event)  (model download/verify/extract, called from both the worker and core.server)
- core.convert.convert_file(in_path, out_format, out_path=None)  (format-conversion library entry point used by app/ and gui.py)

**Commands**
```
python gui.py --worker
python gui.py transcribe path/to/file.mp4 --language en --formats srt json
python gui.py serve --port 8765
python gui.py serve --lan --token SECRET --max-upload-mb 1024
pyright app/ core/   (must report 0 errors before every commit; core/ has zero Tkinter imports by design)
```

**Depends on**
- faster-whisper / ctranslate2 (default ASR backend)
- sherpa-onnx (diarization, bundled ONNX models under bin/diarization/)
- stable-ts / stable_whisper (word-alignment refinement, on-demand install)
- pywhispercpp (whisper.cpp backend, ggml model on-demand download)
- demucs + torch (vocal separation, optional)
- pyannote.audio (voiceprint enrollment/matching, optional)
- sentence-transformers (semantic search layer, optional; FTS5 sqlite is the always-available fallback)
- llama-cpp-python (local LLM panel, optional, on-demand model download)
- google-cloud-speech / google-cloud-storage (google_cloud_stt backend, on-demand install)
- transformers + torch + librosa (nvidia_asr backend, on-demand install)
- watchdog (folder watcher, optional)
- sounddevice / pyaudiowpatch (mic / WASAPI loopback recording, optional)
- screeninfo (multi-monitor detection, optional; ctypes Win32 fallback otherwise)
- python-docx, reportlab (docx/pdf writers)
- requests, platformdirs, psutil (model download, path resolution, stats)
- bundled binaries via core.paths.bundled_binary(): bin/ffmpeg, bin/ffprobe, bin/ffplay, bin/yt-dlp
- app/ (the Tk UI imports core/ extensively; the dependency is one-way -- core/ must never import tkinter or anything under app/)
- gui.py (the process entry point that dispatches into core.worker / core.server / core.transcriber based on argv)

**Gotchas**
- The worker's JSON-stdio protocol (core/worker.py) is FROZEN: add fields, never rename or remove them. All stdout writes go through a single _emit_lock because print()'s write+flush is two operations and concurrent emits (main thread + stdin-reader thread + heartbeat thread) can otherwise interleave and corrupt a JSON line.
- A stray cancel/pause/resume command with no in-flight task is a silent no-op (each transcribe() builds a fresh task with clean flags) -- do not add error logging there expecting it to mean something broke.
- core/ must stay 100% Tk-free -- this is a hard architectural invariant restated in nearly every module docstring, not a style preference. It has to keep working inside worker subprocesses and the optional HTTP server.
- Every optional feature (diarization, alignment, demucs separation, voiceprint, semantic search, LLM, whisper_cpp/cloud_stt/google_cloud_stt/nvidia_asr backends, watcher, recorder, monitors/screeninfo) follows the same is_available()/availability_reason() lazy-import pattern -- never assume a dependency is installed; heavy ones (torch-based) install on demand via core.optional_deps into user_cache_dir()/pylibs, and activate() APPENDS that dir to sys.path (never prepends) so a bundled copy always wins over a stale on-demand one.
- Time-range/clip transcription is NEVER passed to faster-whisper as clip_timestamps (that decodes the WHOLE file and hung on multi-hour input); instead the span is pre-sliced to a temp WAV via ffmpeg (-ss before -i, -t for duration) and results are shifted back by +clip_start. Clipped runs NEVER write a resume checkpoint (the checkpoint has no clip marker, so a resume would run past clip_end).
- The periodic checkpoint (core/_checkpoint.py) is keyed by sha1(os.path.normcase(abspath(source))) and validated against backend + model_name + a config fingerprint + the source file's size/mtime at write time -- any mismatch on resume silently falls back to a full re-transcribe rather than erroring.
- core/transcriber.py's _runtime_overrides_scope MUST restore the module-level config dict after each file: the worker is long-lived and transcribes many files in sequence reusing that same dict, so a per-folder .whisperproject.json override for file A (e.g. diarization_enabled=true) would otherwise leak into file B if the scope didn't snapshot+restore exactly the touched keys on exit.
- config.py's online layer (fetch_online=True default) is restricted to ONLINE_ALLOWED_KEYS (model_catalog/stats_url/latest_version/ffplay_downloads) so a compromised/MITM'd online config can never override user-private settings; _NON_PERSISTED_KEYS (telemetry_opt_in, config_url, stats_url, ffplay_downloads, latest_version) are stripped on every save_config(). model_path and download_folder have bespoke persistence logic (_persistable_model_path/_persistable_download_folder) so an in-memory-derived path never hardens into a stale on-disk override that defeats a later hub_folder change.
- Long-running silent C calls (sherpa-onnx diarization, stable-ts align, demucs subprocess, llama-cpp inference, whisper.cpp transcribe) must be wrapped in core._liveness_tick.liveness_tick(log_cb, label) or the parent App's worker-liveness watchdog can SIGTERM the worker mid-pass on slow hardware, mistaking 'busy' for 'wedged'.
- faster-whisper only accepts ISO-639-1(-ish) codes, never a BCP-47 region tag ('en-US') or a yt-dlp multi-value code ('zh-Hans,zh-CN') -- transcriber._normalize_language / google_cloud_stt.normalize_language_code strip these; skipping normalization at a new call site silently produces zero output.
- docx_writer.write() and pdf_writer.write() and smtv_docx_writer.write() deliberately raise RuntimeError -- write_bytes() (with is_binary()==True routing) is the only real entry point for these three formats. _write_outputs additionally special-cases smtv_docx by name because it needs extra language/work_title kwargs the frozen 2-arg writer contract can't carry.
- _write_outputs (transcriber.py) computes one shared filename-collision index across ALL requested formats before writing any of them, so re-running a transcription produces a consistent set (name (1).srt + name (1).json together), never mismatched indices; each format writes to a unique per-pid+thread .part file then os.replace()s atomically, and one format's write failure never discards formats that already succeeded.
- core.server.jobs.JobManager intentionally runs a SINGLE background worker thread (not a pool): core.transcriber keeps the ~3GB model in a module-global, so concurrent transcribe() calls against it would be unsafe -- this is a deliberate serialization point, not an oversight to 'fix' with more workers.
- core.server.jobs.is_safe_url() blocks loopback/link-local(incl. 169.254.169.254 cloud metadata)/unspecified/multicast/reserved addresses but DELIBERATELY allows RFC-1918 private ranges (10.x/172.16-31.x/192.168.x) since the server is documented for trusted-LAN use; it is a first-line guard only -- yt-dlp still follows its own redirects.
- A trusted build that ships creds/gcloud_stt.json changes the DEFAULT transcribe_backend to google_cloud_stt (core.config._default_transcribe_backend / core.backends.availability.default_engine) -- a plain source checkout has no key and silently stays on faster_whisper; don't assume faster_whisper is always the default engine.
- core.model_manager.ensure_model() retries up to MAX_DOWNLOAD_ATTEMPTS=3 on an MD5 mismatch before raising, and has a zip-slip guard that rejects any archive member resolving outside the target cache dir; on any mirror failure it falls back to a deterministic HuggingFace download keyed by the registry's hf_repo (not a name-guess) to avoid resolving to the wrong upstream org.
- core.hardware / core.backends.faster_whisper_be self-heal a requested CUDA load that fails (typically missing cuDNN/cuBLAS runtime DLLs, not a corrupt model) by silently retrying on cpu/int8 and flipping a 'downgraded' flag the UI can surface -- a bare CUDA failure must never hard-crash the worker.
- history.db opens in WAL journal mode and runs PRAGMA integrity_check on every open; a corrupt DB (or one that fails to even run the pragma) is renamed to .corrupt and recreated fresh rather than crashing launch -- history is lost, not the app.
- The 5 ASR backends share two cross-cutting helpers from core/backends/cloud_stt.py (plan_chunks, offset_segments) that core/backends/nvidia_asr.py imports directly -- treat that pair as a mini shared module, not cloud_stt-private, before duplicating chunk-planning logic in a new backend.
- WHISPER_WORKER_TOKEN (set by the parent at spawn time) is attached to every emitted event as _token so the parent can route events correctly even if the OS recycles a PID between worker spawns; it's optional/empty for older parents, so never assume it's present when parsing worker events.

### platform — `platform/`
Non-Windows packaging and distribution for the Whisper Transcriber Suite: a Linux from-source installer/updater/uninstaller, and three independently-maintained macOS delivery paths (source+venv .command installer, a PyInstaller .app/.dmg pipeline, and a staged Homebrew formula). The app itself is plain cross-platform Python (Tkinter + faster-whisper + yt-dlp + ffmpeg); this subsystem only supplies the OS-specific install/build glue, not app logic.

**Key files**
- `platform/linux/install.sh` — Linux installer: creates .venv next to the repo, pip-installs requirements.txt + yt-dlp, fetches a static ffmpeg/ffprobe (johnvansickle.com) into bin/ if the system lacks one, writes ~/.local/bin/whisper-transcriber-suite (GUI) + whisper-transcribe (headless CLI) launchers, and a .desktop entry. Idempotent.
- `platform/linux/update.sh` — Linux updater: git pull --ff-only, then pip --upgrade requirements.txt + yt-dlp inside the existing .venv. Requires install.sh to have run first.
- `platform/linux/uninstall.sh` — Removes the launchers, .desktop entry, and .venv; deliberately keeps the repo checkout and user data (~/.config/WhisperTranscriberSuite, ~/.cache/WhisperTranscriberSuite).
- `platform/linux/README.md` — Linux usage docs: install/desktop/headless-server (systemd one-shot template included), update, uninstall, model-cache location.
- `platform/macos/install.command` — macOS installer (double-clickable). Rebuilds .venv FROM SCRATCH every run, de-quarantines the repo via xattr, prefers python.org/Homebrew Python over Apple's system python3 (Tk 8.5 trap), symlinks ffmpeg/ffprobe/ffplay into bin/, and builds a real ~/Applications/Whisper Transcriber Suite.app wrapper (own hand-written Info.plist, ad-hoc codesigned) plus a whisper-transcribe CLI. No Python bundled — end user needs Python+Tk installed.
- `platform/macos/unblock.command` — Gatekeeper helper: strips com.apple.quarantine from the repo and the installed Whisper Transcriber Suite.app.
- `platform/macos/README.md` — macOS usage + Gatekeeper explainer. Explicitly marked beta/unvalidated on a real Mac. Documents the Tk-8.5 blur trap, the two source-level install paths, VLC-at-/Applications/VLC.app requirement, Apple Silicon/Rosetta caveats.
- `platform/macos/homebrew/whisper-transcriber-suite.rb` — Personal-tap Homebrew formula (not homebrew-core style): virtualenv_create against python@3.12, depends_on ffmpeg + python-tk@3.12, pip-installs requirements.txt + yt-dlp at install time. url pinned to tag v1.3.6; sha256 is still the literal placeholder string.
- `platform/macos/homebrew/README.md` — How to publish the tap (separate public homebrew-tap repo) and refresh url/sha256 per release; install instructions for end users once published.
- `platform/macos/pyinstaller/whisper_project_mac.spec` — PyInstaller spec that freezes gui.py into dist/Whisper Transcriber Suite.app (self-contained, no Python needed by end user). Third copy of the spec pattern alongside the root's whisper_project_onedir.spec/whisper_project_onefile.spec; hiddenimports/datas mirror the Windows onedir spec. Resolves all paths via a SPECPATH-derived _REPO_ROOT. BUNDLE version currently 1.5.0 (in sync with core.__version__). Never built/verified on a real Mac.
- `platform/macos/pyinstaller/builddmg.command` — Wraps an ALREADY-BUILT dist/Whisper Transcriber Suite.app into dist/Whisper Transcriber Suite.dmg via create-dmg. Errors out if the .app or the create-dmg binary is missing. cd's to repo root first.
- `platform/macos/pyinstaller/compileall-whisper-mac.sh` — One-shot full build: rm -rf dist, run pyinstaller against whisper_project_mac.spec, then wrap into a .dmg (inlines the same create-dmg call as builddmg.command rather than invoking it). Fixed 2026-07-04 for a duplicated pyinstaller invocation and to cd to the repo root first.
- `platform/macos/pyinstaller/README.md` — Build steps for the .app/.dmg path (icon generation, staging Mac ffmpeg/ffprobe/ffplay/yt-dlp into bin/, pyinstaller + create-dmg commands). Framed as the highest-confidence Mac deliverable since it mirrors the maintainer's proven machine-translate-docx pipeline; still unsigned/un-notarized.

**Entry points**
- platform/linux/install.sh
- platform/linux/update.sh
- platform/linux/uninstall.sh
- platform/macos/install.command
- platform/macos/unblock.command
- platform/macos/pyinstaller/whisper_project_mac.spec
- platform/macos/pyinstaller/builddmg.command
- platform/macos/pyinstaller/compileall-whisper-mac.sh
- platform/macos/homebrew/whisper-transcriber-suite.rb

**Commands**
```
bash platform/linux/install.sh
PYTHON=/usr/bin/python3.12 bash platform/linux/install.sh
bash platform/linux/update.sh
bash platform/linux/uninstall.sh
bash platform/macos/install.command
PYTHON=/usr/local/bin/python3 bash platform/macos/install.command
bash platform/macos/unblock.command
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
bash platform/macos/pyinstaller/builddmg.command
bash platform/macos/pyinstaller/compileall-whisper-mac.sh
brew install translation-robot/tap/whisper-transcriber-suite
```

**Depends on**
- gui.py (repo root entry script every launcher/formula execs, including `gui.py transcribe` for the headless CLI and `gui.py serve --lan`)
- requirements.txt (installed by both installers and the Homebrew formula)
- core.paths (resource_base()/bundled_binary()/_ensure_executable() — how the frozen mac app and source installs locate bin/ffmpeg etc.)
- core.__version__ (source of truth the mac spec's BUNDLE version should track)
- assets/ (whisper.png, whisper.icns, whisper.ico — app icons)
- core/server/static and core/writers/templates (data dirs bundled into the mac .app by whisper_project_mac.spec)
- root PyInstaller specs: whisper_project_onedir.spec and whisper_project_onefile.spec (hiddenimports/datas must stay in lock-step with the mac spec per CLAUDE.md 'Style & scope')
- creds/gcloud_stt.json (optional, gitignored — bundled into the mac .app under creds/ only if present locally)
- external tools: python3-tk/tkinter, ffmpeg/ffprobe/ffplay, yt-dlp, create-dmg (brew), Homebrew itself

**Gotchas**
- As of this session, the PyInstaller .app/.dmg path (whisper_project_mac.spec + compileall-whisper-mac.sh) HAS been built and smoke-tested on real macOS runners via the manual-dispatch macos-app.yml/macos-compileall-script-test.yml GitHub Actions workflows (arm64 + x86_64), and real .dmg artifacts now ship on the v1.5.0 GitHub release. The install.command and Homebrew formula paths remain unverified on real hardware — platform/macos/README.md's blanket 'not yet validated' framing is now only accurate for those two, not for the PyInstaller path.
- Two macOS build methods are independently maintained and NOT interchangeable: install.command (source+venv, lightweight wrapper .app, requires the end user to have Python+Tk) vs whisper_project_mac.spec (PyInstaller freeze, self-contained .app/.dmg, no Python needed by the end user). A fix in one does not apply to the other, and each writes its own separate Info.plist.
- whisper_project_mac.spec is 'the third spec copy': per the root CLAUDE.md, adding a new module/hidden import must be mirrored into whisper_project_onedir.spec AND whisper_project_onefile.spec at the repo root or the unshipped pipelines bit-rot silently.
- whisper_project_mac.spec resolves every repo-relative path via `_REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir, os.pardir, os.pardir))` — a historical bug fix. PyInstaller resolves a bare relative script path (e.g. 'gui.py') against the spec file's OWN directory (platform/macos/pyinstaller/), not the CWD, which previously failed the build with 'gui.py not found'.
- compileall-whisper-mac.sh and builddmg.command both inline the same create-dmg invocation (window size/icon position/volname) rather than one calling the other — a packaging tweak made in one must be repeated in the other or they'll drift.
- Version numbers can drift across four places with nothing enforcing sync: core.__version__ (1.5.0, source of truth) / whisper_project_mac.spec BUNDLE+info_plist version (currently 1.5.0, in sync) / install.command's own hardcoded Info.plist CFBundleVersion (still 1.3.6 — tracked independently by design per the spec's own comment) / homebrew/whisper-transcriber-suite.rb url+tag (still v1.3.6, sha256 left as the literal placeholder 'PUT_SHA256_OF_THE_TARBALL_HERE').
- Docs under platform/macos/ (README.md, homebrew/README.md, whisper-transcriber-suite.rb comments) still say the GitHub repo is currently PRIVATE, which blocks a real Homebrew tap and the curl-based one-liner in linux/install.sh's own comment — the repo has since been made PUBLIC, so the Homebrew tap may now be publishable for real; re-verify and update these docs before trusting the 'private, staged for later' framing.
- Gatekeeper: the app is unsigned (no paid Apple Developer cert). Getting the repo via git clone/curl avoids the com.apple.quarantine flag entirely (why every doc pushes clone-first); a browser-downloaded zip needs unblock.command or System Settings -> Privacy & Security -> 'Open Anyway'. Never suggest `spctl --master-disable`.
- Apple's bundled system python3 links deprecated Tcl/Tk 8.5, which imports fine but renders a blurry/unstable GUI. install.command checks the actual `tkinter.TkVersion` (not just importability) and warns/prefers python.org or Homebrew Python (Tk 8.6). The headless whisper-transcribe CLI needs no Tk and works with any python3.
- install.command rebuilds its venv FROM SCRATCH every run (`rm -rf .venv`) so switching interpreters doesn't silently reuse a stale Tk-8.5-linked venv; Linux's install.sh is idempotent/incremental instead. Don't assume the two installers behave the same on re-run.
- ffmpeg/ffprobe/ffplay must always be symlinked/copied into repo-root bin/, even when already on PATH via Homebrew or the system — a Finder/LaunchServices-launched .app only inherits the minimal /usr/bin:/bin PATH, not /opt/homebrew/bin or /usr/local/bin, so core.paths.bundled_binary() would otherwise fail to find them. ffplay specifically is required for the Video Tiling tab; its absence degrades to an in-app 'Download ffplay' button rather than a hard failure.
- core.paths.bundled_binary() appends '.exe' only when os.name == 'nt'; on macOS/Linux it looks up the bare extension-less name, so bin/ on a Mac build must contain Mac ffmpeg/ffprobe/ffplay/yt-dlp, never the Windows .exe files, or the frozen app breaks silently at runtime instead of failing the build.
- PyInstaller's COLLECT/BUNDLE doesn't reliably preserve the executable bit on bundled POSIX binaries across versions, so core.paths._ensure_executable() re-asserts chmod +x at runtime as a safety net for the frozen macOS .app's bundled ffmpeg/ffprobe/ffplay/yt-dlp.
- The BUNDLE info_plist sets LSMinimumSystemVersion to 11.0 specifically because an unsigned app's file-access permissions get down-ranked by macOS on older/unspecified system versions — this is a deliberate Gatekeeper-adjacent pin, not an arbitrary compatibility floor.
- There is no Windows packaging under platform/ at all — Windows build/install tooling (build_embed_installer.bat, installer_embed.iss, installer.iss, whisper_project_onefile.spec, whisper_project_onedir.spec, build.bat) lives at the repo root and belongs to the build-packaging subsystem.
- Of the three non-Windows paths, Linux is the only one considered reasonably solid (plain venv, no Gatekeeper-equivalent friction, idempotent scripts); install.command and the Homebrew formula remain explicitly unvalidated on real hardware even though the PyInstaller .app/.dmg path is now CI-proven.

### tools-bin — `tools/, bin/`
tools/ holds standalone maintenance and dev scripts that are not part of the shipped app (PROJECT_INDEX.md refresher, a diarization-model fetcher, three live E2E drivers, and a startup-time profiler); bin/ is the runtime location where the app expects vendored third-party binaries (ffmpeg, ffprobe, yt-dlp) and ONNX speaker-diarization models to sit, resolved through core/paths.py and consumed by core/tiling.py, app/app.py, and core/diarization.py.

**Key files**
- `tools/index_refresh.py` — Zero-token, zero-network deterministic refresher for the AUTO-INDEX:STRUCTURE block in PROJECT_INDEX.md; writes .project_index.json manifest; silent no-op (exit 0) if PROJECT_INDEX.md doesn't exist at the target yet. Run by a Claude Code SessionStart hook and by the project-index skill (with --set-baseline) after semantic sections are rebuilt.
- `tools/download_diarization_models.bat` — One-time fetcher for bin/diarization/segmentation.onnx (+ .int8.onnx) and embedding.onnx from k2-fsa/sherpa-onnx GitHub releases. Build-time step, like fetching ffmpeg; CI does not run it.
- `tools/measure_startup.py` — Times cold start of dist/WhisperTranscriberSuite.exe using ctypes Win32 EnumWindows (no third-party deps); detects readiness by window title "Transcription helper", not PID. Manual dev tool, not wired into CI or BUILD.md.
- `tools/e2e_cancel_pause.py` — Live E2E: spawns the real core.worker subprocess and drives its JSON stdin/stdout protocol through pause -> resume -> cancel, asserting a resumable checkpoint survives cancel. Needs a real video (WHISPER_SMOKE_VIDEO env var, default E:\3029-NWN-Daily-Scroll-2m_0002.mp4) and the real model; SKIPs (exit 0) if absent.
- `tools/e2e_slim_pastbugs.py` — Live E2E that must run under the slim embed interpreter (embed_build\python\python.exe) against embed_build\gui.py; regression-guards a specific list of previously-shipped bugs (docx output, non-srt formats, hyphenated lang codes, clip ranges, apostrophe filenames) in the v1.3.4+ Setup-Standard/Portable build.
- `tools/e2e_tiny_macos.py` — Real (unmocked) faster-whisper/CTranslate2 inference E2E using the tiny model plus a short macOS `say`-generated clip; invoked directly by .github/workflows/macos-e2e.yml.
- `bin/ffmpeg.exe, bin/ffprobe.exe` — Vendored FFmpeg binaries (~100 MB each) used for audio/video decode, slicing, subtitle burn-in; resolved at runtime via core.paths.bundled_binary()/bin_dir(). Gitignored — not committed.
- `bin/yt-dlp.exe` — Vendored yt-dlp binary (~18 MB) for video downloads; self-updates via `yt-dlp -U` at runtime in dev builds only (frozen builds skip self-update since the install dir is read-only). Gitignored — not committed.
- `bin/diarization/segmentation.onnx, segmentation.int8.onnx, embedding.onnx, segmentation.tar.bz2` — pyannote-segmentation-3.0 and 3D-Speaker CAMPlus EN ONNX models consumed by core/diarization.py's _model_path(). Gitignored; normally produced by tools/download_diarization_models.bat.

**Entry points**
- tools/index_refresh.py [target_dir] [--set-baseline]  (also auto-run by a SessionStart hook and the project-index skill)
- tools/download_diarization_models.bat  (manual, once before any build)
- tools/measure_startup.py [path/to/WhisperTranscriberSuite.exe]
- tools/e2e_cancel_pause.py
- tools/e2e_slim_pastbugs.py  (must use embed_build\python\python.exe)
- tools/e2e_tiny_macos.py <clip.wav>  (invoked by .github/workflows/macos-e2e.yml)
- core.paths.bundled_binary("ffmpeg"|"ffprobe"|"yt-dlp")  (the runtime lookup entry point into bin/)

**Commands**
```
python tools/index_refresh.py .
python tools/index_refresh.py . --set-baseline
tools\download_diarization_models.bat
python tools/measure_startup.py
python tools/e2e_cancel_pause.py
embed_build\python\python.exe tools\e2e_slim_pastbugs.py
python tools/e2e_tiny_macos.py clip.wav
```

**Depends on**
- core/paths.py (resource_base/bin_dir/bundled_binary — the runtime resolver all bin/ consumers go through)
- core/diarization.py (consumes bin/diarization/*.onnx)
- core/tiling.py, app/app.py (consume bin/ffmpeg.exe, bin/ffprobe.exe, bin/yt-dlp.exe; ffplay is deliberately NOT in bin/ by default)
- whisper_project_onefile.spec, whisper_project_onedir.spec, platform/macos/pyinstaller/whisper_project_mac.spec, build_embed_installer.bat (bundle the whole bin/ tree into shipped builds)
- .github/workflows/macos-e2e.yml (runs tools/e2e_tiny_macos.py)
- project-index skill / SessionStart hook (runs tools/index_refresh.py)
- faster-whisper / CTranslate2 (external lib exercised by tools/e2e_tiny_macos.py)
- k2-fsa/sherpa-onnx GitHub releases (upstream source for the diarization ONNX models)

**Gotchas**
- bin/ is almost entirely gitignored (ffmpeg.exe, ffprobe.exe, yt-dlp.exe, bin/diarization/*.onnx, *.tar.bz2 all excluded; `git ls-files bin` returns nothing). This directly contradicts docs/BUILD.md's line 53 ("checked into the repo's bin\ folder") — that doc line is stale. Treat bin/ as a locally-vendored, machine-specific directory that a fresh clone will NOT have populated.
- Only the diarization ONNX models have an in-repo fetch script (tools/download_diarization_models.bat). There is no equivalent fetch script or recorded source URL/version for ffmpeg.exe/ffprobe.exe/yt-dlp.exe anywhere in the repo (README/BUILD.md/THIRD_PARTY_NOTICES.md all discuss licensing but not provenance) — a fresh machine must source those three binaries manually.
- docs/BUILD.md never mentions diarization or tools/download_diarization_models.bat at all, even though core/diarization.py hard-depends on bin/diarization/*.onnx — following BUILD.md's build steps top-to-bottom silently produces a build without diarization support unless you separately know about the .bat script.
- ffplay.exe is intentionally NOT part of bin/'s expected contents even though it's part of the FFmpeg suite — core/tiling.py explicitly documents that only ffmpeg/ffprobe/yt-dlp are bundled; ffplay must be added manually to bin/ or PATH (there's also an in-app ffplay downloader driven by config['ffplay_downloads'], separate from tools/).
- tools/e2e_cancel_pause.py and tools/e2e_slim_pastbugs.py are live smoke drivers, not hermetic tests, and live outside tests/ on purpose — they need a real video/model/embed build and SKIP (exit 0) rather than fail when prerequisites are missing, so a clean run of these alone proves nothing.
- tools/e2e_slim_pastbugs.py must be run with embed_build\python\python.exe (the slim embed interpreter), not the normal dev venv — it specifically regression-tests the v1.3.4+ embed build (Method C / Setup-Standard), the pipeline actually shipped per the repo-root CLAUDE.md.
- tools/index_refresh.py is a silent no-op whenever PROJECT_INDEX.md doesn't already exist at the target — intentional so one global SessionStart hook is safe repo-wide; "nothing happened" is expected/correct outside opted-in repos.
- tools/measure_startup.py matches the target process purely by visible window title ("Transcription helper"), never by PID, because PyInstaller builds can spawn a standby worker under a different PID than Popen returned.
- bin/ is bundled wholesale into PyInstaller builds via a ('bin','bin') data entry (Methods A/B) or xcopy (Method C); per the repo-root CLAUDE.md only Method C (embed-tree Setup-Standard + Portable ZIP) is actually shipped today, so bin/'s footprint matters most for that pipeline even though all three specs must stay buildable.
- bin/ is the largest thing on disk in this checkout (~215 MB: ffmpeg.exe + ffprobe.exe ~100 MB each, yt-dlp.exe ~18 MB, diarization models ~35 MB) — exactly why it's gitignored; never `git add -A` near this directory.

### build-packaging — `whisper_project_direct_download_v2/ (root-level build scripts, specs, installers)`
Root-level scripts/specs that turn the app/ + core/ source tree into the two shipped Windows deliverables (Setup-Standard installer and a Portable zip), both built from a bundled-Python embed_build/ tree produced by build_embed_installer.bat; two additional PyInstaller pipelines are kept building but are not published.

**Key files**
- `build_embed_installer.bat` — Method C build script: downloads a python-build-standalone CPython 3.11 install_only tarball (has tkinter, unlike python.org's embeddable zip), pip-installs requirements.txt into it, prunes heavy optional deps (torch/whisper/numba/etc, ~700MB saved), copies app/core/bin/gui.py, writes sitecustomize.py + a portable launcher .bat, runs sanity imports. Produces embed_build/, the single source tree for BOTH shipped deliverables.
- `installer_embed.iss` — Inno Setup script for the SHIPPED Setup-Standard installer. Wraps embed_build/ into dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe. Single version knob #define MyAppVersion. Also handles the hub-folder uninstall prompt, shell-extension registry keys, and the optional 'notiling' task (drops a no_tiling.flag marker).
- `installer.iss` — Inno Setup script for the UNSHIPPED 'Setup-Compact' installer (Method B). Wraps dist_onedir\WhisperTranscriberSuite\ (produced by whisper_project_onedir.spec) into WhisperTranscriberSuite-vX.Y.Z-Setup-Compact.exe. Maintained but not published.
- `whisper_project_onedir.spec` — UNSHIPPED PyInstaller onedir spec (Method B) — feeds installer.iss. Kept in lock-step with the onefile spec's hidden-imports/datas so it doesn't bit-rot.
- `whisper_project_onefile.spec` — UNSHIPPED PyInstaller onefile spec (Method A) — single self-extracting exe, was the Portable deliverable before v1.3.2. Its EXE() still hardcodes name='WhisperTranscriberSuite-v1.0.3-Portable', stale vs. the current 1.5.0.
- `build.bat` — STALE/likely-broken helper: runs `pyinstaller --noconfirm whisper_project.spec`, a file that does not exist in the repo root (only *_onedir.spec and *_onefile.spec exist). Also references an obsolete dist\config.json copy step from before the Phase-1.2 config migration to %LOCALAPPDATA%.
- `gui.py` — Actual app entry point (283 lines). argparse CLI with `transcribe` / `serve` subcommands, a pre-argparse `--worker` branch (JSON-stdio worker spawn contract used by every build method), a pre-argparse `--safe-mode` flag, and the default bare launch into app.run() (the Tk GUI).
- `pyproject.toml` — setuptools metadata, version = "1.5.0" (one of the '4 usual places'), pyright/pytest/coverage config, and optional-dependency extras (dev, crash_reporting, theme_detection, backend_cpp, alignment, nvidia_asr).
- `requirements.txt` — Pinned runtime deps installed into embed_build\Lib\site-packages by build_embed_installer.bat; must stay consistent with pyproject.toml's core dependency list (docs/RELEASE_PROCESS.md's maintenance loop calls this out explicitly).
- `configuration.json` — Master copy of the ONLINE app config (model_catalog, stats_url, latest_version, ffplay_downloads) that the maintainer manually uploads to https://smch.ir/whisper/app_config.json. NOT bundled into any build, NOT read from disk by the running app at all.

**Entry points**
- gui.py (bare argv) -> app.run() launches the Tk desktop GUI
- gui.py transcribe FILE [--language] [--formats] [--diarization] -> one-shot CLI transcription, exits
- gui.py serve [--port] [--host] [--lan] [--token] [--max-upload-mb] -> runs core.server's local/LAN HTTP job server
- gui.py --worker -> JSON-stdio worker subprocess (core.worker.main); handled before argparse, spawn-contract every deliverable relies on, must not be renamed/removed
- gui.py --safe-mode -> backs up + resets %LOCALAPPDATA%\WhisperTranscriberSuite\config.json before any other mode runs

**Commands**
```
build_embed_installer.bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable', 'zip', r'embed_build')"
python -m pyright app core
python -m pytest tests\ --ignore=tests\smoke
gh release upload vX.Y.Z dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable.zip --clobber
pyinstaller --noconfirm --clean whisper_project_onefile.spec  (unshipped Method A)
pyinstaller --noconfirm --clean --distpath dist_onedir whisper_project_onedir.spec  (unshipped Method B, input to installer.iss)
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss  (unshipped Method B installer)
```

**Depends on**
- app/ (Tkinter UI package, imported by gui.py's default launch)
- core/ (transcription/download/config/worker engine; core.worker, core.server, core.config, core.transcriber all invoked directly from gui.py)
- bin/ (bundled ffmpeg.exe, ffprobe.exe, yt-dlp.exe — copied/bundled by every pipeline)
- assets/ (whisper.ico, whisper.png — packaged by both .iss installers)
- creds/gcloud_stt.json (gitignored, optional — bundled into embed_build/creds/ when present)
- PyInstaller (Methods A/B)
- Inno Setup 6 / ISCC.exe (Methods B/C — winget install JRSoftware.InnoSetup)
- python-build-standalone (astral-sh GitHub releases — CPython 3.11.15 install_only tarball, Method C)
- Windows-native tar.exe/bsdtar (Method C extraction; Git's tar breaks on the C:\ path)
- requirements.txt runtime deps (faster-whisper, sherpa-onnx, python-docx, reportlab, etc. — NOT google-cloud-speech, which is on-demand only as of 2026-08-15)

**Gotchas**
- Only TWO deliverables ship: Setup-Standard (installer_embed.iss over embed_build/) and Portable (a zip of that SAME embed_build/ tree, via shutil.make_archive). Portable stopped being a PyInstaller onefile exe at v1.3.2.
- whisper_project_onefile.spec (Method A) and whisper_project_onedir.spec + installer.iss (Method B/'Compact') are UNSHIPPED but deliberately kept building. CLAUDE.md requires updating both specs' hidden-imports/datas lists whenever a new app/core module is added, purely so they don't bit-rot, even though nothing consumes their output.
- whisper_project_onefile.spec's EXE() hardcodes name='WhisperTranscriberSuite-v1.0.3-Portable' — stale vs. the current 1.5.0. Unlike installer_embed.iss's parameterized #define MyAppVersion, this literal isn't part of the version-bump checklist and isn't auto-updated.
- build.bat is stale/likely broken: it invokes `pyinstaller ... whisper_project.spec`, a file that does not exist at repo root (verified — only whisper_project_onedir.spec and whisper_project_onefile.spec are present). Its dist\config.json-copy logic is also obsolete after the Phase-1.2 config migration to %LOCALAPPDATA%.
- Version must be bumped in the '4 usual places' (per docs/SESSION_HANDOFF_NEXT.md): pyproject.toml (version=), core/__init__.py (__version__=), installer.iss (AppVersion= / OutputBaseFilename=), installer_embed.iss (#define MyAppVersion). configuration.json's own 'latest_version' field is a SEPARATE, informational value for the online-config layer — it is NOT one of the 4 and bumping it alone does nothing for the shipped version.
- configuration.json (repo root) vs core/config.py's DEFAULT_CONFIG is a duplication trap: configuration.json is only the master copy manually uploaded to config_url (https://smch.ir/whisper/app_config.json); it is never bundled and never read from disk by the running app. DEFAULT_CONFIG in core/config.py has its own near-empty baseline (model_catalog={}). The real effective config is a 3-way merge (core.config.merge_config_sources: local config.json > fetched-and-cached online config > DEFAULT_CONFIG) — editing configuration.json in the repo has zero runtime effect until someone re-uploads it to the URL.
- docs/RELEASE_PROCESS.md Step 5 still describes building 'three deliverables' (Portable exe + onedir/Compact + Standard) as if all three ship — that section is stale. The doc's own preamble says 'if anything here disagrees with CLAUDE.md, CLAUDE.md wins,' and CLAUDE.md + docs/BUILD.md are authoritative that only Setup-Standard + Portable(zip) ship; prefer docs/BUILD.md's 'Rebuild without bumping the version' recipe for routine same-version respins.
- build_embed_installer.bat prunes heavy optional packages (torch, torchaudio, whisper, stable_whisper, numba, llvmlite, sympy, networkx, mpmath, functorch, torchgen + their .libs siblings) from embed_build/Lib/site-packages after pip install, keeping the shipped bundle ~800MB instead of ~1.5GB; these install on demand at runtime via core.optional_deps only if the user enables stable-ts alignment or an opt-in backend.
- Method C needs the Windows-native tar.exe (bsdtar) at %SystemRoot%\System32\tar.exe — Git's bundled tar.exe misinterprets the 'C:' destination as a remote-host argument and fails.
- Release cadence is intentionally slow (CLAUDE.md 'Release cadence: slow down'): default to a same-version rebuild (docs/BUILD.md recipe) rather than bumping the version for routine fixes; docs/SESSION_HANDOFF_NEXT.md shows many same-version rebuild cycles already at v1.5.0.

### tests-docs — `tests/, docs/, plus root project-config files (pyproject.toml, requirements.txt, README.md, CLAUDE.md, THIRD_PARTY_NOTICES.md, run_tests.bat)`
The pytest-based verification suite (hermetic unit/integration tests plus a real-resource smoke suite) that gates every commit via run_tests.bat, and the docs/ knowledge base (build/release/config/architecture reference, session handoff, and evidence-based competitive/gap analysis) plus root metadata files that define how the project is built, tested, and licensed.

**Key files**
- `run_tests.bat` — Root everyday gate: runs `pyright app core` then `pytest tests/ --ignore=tests/smoke -q`, prints PASS/FAIL summary, non-zero exit on failure
- `pyproject.toml` — Project metadata, runtime deps, optional-dependency groups (dev/crash_reporting/theme_detection/backend_cpp/alignment/nvidia_asr), and [tool.pytest.ini_options]/[tool.coverage]/[tool.pyright] config
- `requirements.txt` — Pinned runtime dependencies for source installs; notes which libs are bundled vs. installed on demand via core/optional_deps.py
- `CLAUDE.md` — Durable auto-loaded Claude Code session rules: commit/push cadence, permitted vs forbidden git/gh operations, English-only repo policy, pyright gate, points to the handoff file
- `README.md` — User-facing project overview; top banner points readers to PROJECT_INDEX.md for fast onboarding
- `THIRD_PARTY_NOTICES.md` — Summary of bundled third-party runtime/binary/package licenses (FFmpeg, yt-dlp, faster-whisper, PyTorch, etc.)
- `tests/core/conftest.py` — Autouse fixtures: snapshot/restore core.transcriber module globals (MODEL/PIPELINE/etc.) around every test, and pin transcribe_backend to faster_whisper so a bundled cloud key doesn't change test behavior
- `tests/smoke/conftest.py` — Session-scoped skip-guard fixtures (test_video, model_dir, exe_path, gui_script) — each pytest.skip()s when its real-resource prerequisite is absent
- `tests/app/test_transcription_service.py` — NEW (2026-07-04) 11-test file covering app/services/transcription_service.py's _derive_transcript_stats and _post_usage_stats; closes GitHub issue #3 and reproduces the shipped word_count=0 bug
- `tests/core/test_config.py` — Config load/save, model_path/download_folder persistence, and the three-layer online/local/hard-coded merge rules; also guards configuration.json's stats_url against drifting from core.config.DEFAULT_CONFIG
- `tests/integrations/test_smtv.py` — Hermetic, fixture-driven tests for core/integrations/smtv.py (URL recognition, page parsing, transcript extraction); the live-network variant is separated into tests/smoke/test_smtv_smoke.py
- `tests/integrations/test_otranscribe.py` — Hermetic tests for the oTranscribe (.otr) integration round-trip
- `tests/smoke/test_exe_real_e2e.py` — Spawns the compiled WhisperTranscriberSuite.exe --worker against a real video; the only test category that catches PyInstaller packaging bugs (missing data files/hidden imports)
- `tests/fixtures/audio/*.wav` — Tiny committed WAV fixtures (silent_1s.wav, tone_440hz_2s.wav) so decode/VAD/transcribe tests never touch the network
- `docs/SESSION_HANDOFF_NEXT.md` — Single-source-of-truth handoff log; must be read first each session and updated at session end; newest entries appended at the top
- `docs/GAPS_AGAINST_PEERS_2026.md` — Feature-by-feature product gap analysis vs. peer desktop apps (MacWhisper, Buzz, Vibe, etc.); re-audited against current code 2026-07-04
- `docs/COMPETITIVE_ANALYSIS_2026.md` — Ecosystem/ASR-model survey (open-source landscape, cloud APIs, CJK specifics); companion to GAPS_AGAINST_PEERS, re-audited 2026-07-04 for our-own-capability claims only
- `docs/BUILD.md` — Build recipe: embed tree -> Setup-Standard installer + Portable zip (shipped), plus the unshipped PyInstaller onefile/onedir pipelines kept in lock-step
- `docs/RELEASE_PROCESS.md` — Full release sequence plus the shorter 'same-version rebuild' recipe used for source-only re-ships; defers to CLAUDE.md on any conflict
- `docs/CONFIG.md` — Full config-key reference and the three-level merged-configuration design (local config.json > online config_url > hard-coded DEFAULT_CONFIG)
- `docs/CHANGELOG.md` — Keep-a-Changelog-style version history, current head [1.5.0]
- `docs/TESTING.md` — Short how-to: run_tests.bat usage, hermetic vs. smoke distinction, one-time setup, running the app from source
- `docs/README.md` — Documentation folder index / reading order across five buckets (start-here, reference, per-feature, release notes, development state)
- `docs/history/README.md` — Index of ~23 archived phase-acceptance plans, audits, and superseded planning docs, preserved for traceability
- `docs/integrations/README.md` — Documents the research -> brief -> acceptance pattern used for each third-party integration (oTranscribe, SMTV)
- `docs/roadmap/README.md` — Index of future-release feature-research docs; entries move out once a release ships
- `docs/release-notes/RELEASE_NOTES_v*.md` — 19 per-version release-notes files, v0.7.0 through v1.5.0, produced by the 2026-07-04 docs reorg out of the flat docs/ root

**Entry points**
- run_tests.bat (double-click or CLI) -- the everyday pyright+pytest gate
- docs/SESSION_HANDOFF_NEXT.md -- read first at the start of any session
- docs/README.md -- documentation folder reading-order index
- docs/TESTING.md -- quick guide to running tests and the app from source

**Commands**
```
run_tests.bat
pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
python -m pytest tests/smoke/ -v -s
pip install -r requirements.txt
pip install pyright pytest
```

**Depends on**
- app/ subsystem (tests/app exercises app.services.transcription_service)
- core/ subsystem (tests/core is the bulk of the suite, ~150 test_*.py files exercising core.*)
- faster-whisper, pytest, pytest-cov, responses, pyright (external libs from pyproject.toml dev extras)
- GitHub Actions CI (ci.yml runs the hermetic suite; codecov/codecov-action uploads coverage.xml)
- Build subsystem (docs/BUILD.md, docs/RELEASE_PROCESS.md reference build_embed_installer.bat, installer_embed.iss, PyInstaller specs)

**Gotchas**
- Hermetic suite = tests/ minus tests/smoke/; run_tests.bat's pytest invocation is literally `pytest tests/ --ignore=tests/smoke`. A bare `pytest` from repo root also targets tests/smoke (via pyproject's testpaths=["tests"]) but each smoke test self-skips via pytest.skip() when its real-resource prerequisite (3GB Whisper model, a real test video, a compiled exe, live network) is absent.
- pyright app/ core/ must report exactly 0 errors / 0 warnings / 0 informations before every commit (the v1.0.3 baseline, protected); tests/ itself is excluded from pyproject.toml's [tool.pyright] include list.
- docs/SESSION_HANDOFF_NEXT.md must be read first every session and updated at session end -- it is a large, append-only running log (1200+ lines) with newest entries at the top.
- tests/core/conftest.py's autouse _isolate_transcriber_globals fixture exists because monkeypatch cannot undo `global`-statement mutations in core.transcriber; without it, tests leak MODEL/PIPELINE/backend state across files in an order-dependent way.
- tests/core/conftest.py's autouse _default_offline_backend fixture pins transcribe_backend to faster_whisper for every test, because a dev machine shipping creds/gcloud_stt.json would otherwise silently resolve the default backend to google_cloud_stt and break tests mocking the offline MODEL.
- tests/app/ is brand new as of 2026-07-04 -- currently only test_transcription_service.py, added specifically to cover the seam that shipped a real word_count=0 bug (GitHub issue #3, closed).
- docs/history/ and docs/release-notes/ are the result of a 2026-07-04 reorg that moved archived planning docs and all RELEASE_NOTES_vX.Y.Z.md files out of the flat docs/ root into subfolders, each with its own README/index.
- One pre-existing test-order-dependent flake is documented as NOT a regression: tests/core/test_resume_from_cancellation.py fails in isolation but passes under full-suite ordering. (tests/core/test_v08_real_file_e2e.py, the other entry formerly listed here, moved to tests/smoke/ on 2026-08-15 — it needs a real hot worker+model and running it concurrently with the rest of the hermetic suite was implicated in a real native crash; see docs/DECISIONS.md ADR 0008.)
- CLAUDE.md enforces an English-only repo (no Persian/Arabic/RTL in docs, code comments, or commit messages) because the branch is being prepared for handover to a separate maintainer -- this is a repo-specific rule distinct from any assistant-side language preference.
- RESOLVED 2026-08-15 (was a real gotcha before): requirements.txt used to bundle google-cloud-speech/google-cloud-storage unconditionally, left over from when a bundled key made google_cloud_stt the default engine. That key was revoked 2026-08-04 (SECURITY.md) and the default reverted to offline faster-whisper, but requirements.txt/build_embed_installer.bat/the three .spec files' comments weren't updated to match — contradicting docs/CONFIG.md, docs/CLOUD_STT_GOOGLE.md and core/optional_deps.py's own comment, which all already said "on-demand, not bundled." Now removed from requirements.txt; google-cloud-speech/storage install on demand like every other optional backend (pywhispercpp, stable-ts, screeninfo, nvidia_asr's transformers/torch/librosa) via core/optional_deps.py.
- docs/GAPS_AGAINST_PEERS_2026.md and docs/COMPETITIVE_ANALYSIS_2026.md were both re-audited 2026-07-04 with file:line evidence after a large fraction of their 'missing feature' claims turned out to already be shipped -- trust the 2026-07-04 corrections over the original May-2026 prose in either doc.

---

<!-- AUTO-INDEX:STRUCTURE:START -->
## Structure (auto-refreshed — do not hand-edit this block)

- **Source files tracked:** 465
- **Structure refreshed:** 2026-08-23T22:55:22
- **Semantic sections last built:** 2026-07-04T15:30:21
- **Drift since semantic build:** +61 added · ~132 changed · -4 removed

> ⚠️ **STALE** — the source tree changed a lot since the semantic sections were built. Re-run `/project-index` to regenerate purposes / gotchas / subsystem maps.
>
> Notable: `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/workflows/ci.yml`, `.github/workflows/macos-app.yml`, `.github/workflows/macos-compileall-script-test.yml`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`

| Top-level | Source files |
|---|---|
| `tests` | 189 |
| `docs` | 97 |
| `core` | 69 |
| `app` | 29 |
| `.claude` | 20 |
| `(root)` | 19 |
| `.github` | 13 |
| `platform` | 12 |
| `tools` | 8 |
| `whisper_transcriber_suite.egg-info` | 5 |
| `downloads` | 3 |
| `assets` | 1 |

**By type:** `.py`×291  `.md`×112  `.json`×17  `.yml`×11  `.txt`×9  `.bat`×6  `.spec`×4  `.html`×4  `.sh`×4  `.iss`×2  `.ps1`×2  `.toml`×1  `.js`×1  `.rb`×1

<!-- AUTO-INDEX:STRUCTURE:END -->
