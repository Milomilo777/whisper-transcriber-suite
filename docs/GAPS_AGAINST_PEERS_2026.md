# Gaps against peer products (May 2026)

> **Companion to:** [COMPETITIVE_ANALYSIS_2026.md](COMPETITIVE_ANALYSIS_2026.md)
> — that file is the *ecosystem* survey (ASR models, cloud APIs, ZH/JA
> specifics). This file is the *product* gap analysis: feature-by-
> feature, what comparable desktop apps do that **we** do not.
>
> Scope: Windows desktop. Peers chosen as the closest like-for-like:
>
> - **MacWhisper** (Jordi Bruin) — macOS file transcription + AI
> - **Buzz** (chidiwilliams/buzz) — open-source, Win/macOS/Linux,
>   Whisper-multi-backend
> - **Vibe** (thewh1teagle/vibe) — open-source Tauri, Win/macOS/Linux
> - **Superwhisper / Wispr Flow** — system-wide dictation overlays
> - **Descript** — transcript-driven media editor (cloud, but UX leader)
> - **WhisperX / WhisperKit / Insanely-Fast-Whisper** — alignment +
>   speed reference implementations
>
> Rating: 🟢 we have it · 🟡 partially / behind · 🔴 missing.
> Effort: XS (≤1 day) · S (≤3 days) · M (1–2 weeks) · L (2–4 weeks) · XL (>4 weeks).

---

## A. Core ASR features

| Feature | Us | Peers | Effort to close | Notes |
|---|---|---|---|---|
| **Speaker diarization** (who said what) | 🟢 shipped — fully offline via `core/diarization.py` (sherpa-onnx: pyannote-segmentation-3.0 + CAMPlus embedding, no HuggingFace token, no PyTorch) | MacWhisper (beta), Buzz, WhisperX, Descript, Otter | — | Was marked absent (this document's own #1 priority gap) — confirmed implemented, tested (`tests/core/test_diarization.py`), and wired into writers (`speaker` field) + the Advanced dialog. |
| **Word-level ±50 ms alignment** | 🟢 shipped (opt-in, off by default) | WhisperX, stable-ts, MacWhisper, Vibe | — | Was marked partial; confirmed `core/alignment.py` does real stable-ts DTW refinement to ±50ms, selectable via the Advanced-dialog "Refine word timings with stable-ts" checkbox (was a "Word alignment" combobox until 2026-09-12), tested (`tests/core/test_alignment.py`). |
| **Live mic transcription** | 🟡 partial — record-then-transcribe, not streaming | Buzz (live), MacWhisper (recording), Vibe | L | `core/recorder.py` records mic (sounddevice) or system audio (pyaudiowpatch loopback) to WAV, then runs the normal transcribe pipeline. True continuous streaming (Whisper-Streaming's LocalAgreement-n) still not built. |
| **System-wide dictation hotkey** | 🔴 absent | Superwhisper, Wispr Flow, MacWhisper, Handy, VoiceTypr | XL | Out-of-process hotkey + active-window-aware text insertion. The fastest-growing category in 2025/2026. Re-confirmed absent 2026-07-04 — no hotkey/keyboard-hook code anywhere. |
| **Multiple Whisper sizes selectable from UI** | 🟢 shipped | Buzz, MacWhisper, Vibe (model picker dropdown) | — | Was marked hard-coded; confirmed `core/model_manager.py` `MODEL_REGISTRY` covers tiny/base/small/medium/large/distil/turbo, with a full Advanced-dialog combobox (download status, info, one-click download). |
| **GPU vs CPU choice exposed in UI** | 🟢 shipped | Buzz (Vulkan/CUDA dropdown), MacWhisper | — | Was marked auto-only; confirmed a Hardware Wizard (`app/widgets/hardware_wizard.py`) with override + persistence (`hardware.json`) + a benchmark button. |
| **Alternative backends** (whisper.cpp, MLX, NeMo Parakeet) | 🟢 shipped — 5 backends | Buzz (4 backends), Vibe (whisper-rs), MacWhisper (Whisper + Parakeet + cloud routing) | — | Was marked faster-whisper-only; confirmed `core/backends/{faster_whisper_be,whisper_cpp,cloud_stt,google_cloud_stt,nvidia_asr}.py` behind a common `Backend` ABC, all selectable from the Transcribe-tab engine combobox. |
| **Custom hot-words / phrase biasing** | 🟡 single global field, no per-project glossary | Deepgram, Azure, ElevenLabs, MacWhisper, CapsWriter | S | Upgraded from "no UI" — `app/dialogs/advanced.py` has a real "Hotwords" entry wired to config — but it's one global comma-separated field, not a per-project glossary editor. |
| **Language picker per-file** | 🟢 shipped | Buzz, MacWhisper, Vibe (dropdown next to each task) | — | Was marked config-only; confirmed a "Language:" combobox on the Transcribe tab, applied per task. |
| **Translation (target ≠ source)** | 🔴 absent | MacWhisper, Buzz, Descript, Canary-1B-v2 backend | M | Whisper itself supports translation-to-English via `task="translate"`. We never expose this — re-confirmed 2026-07-04; `core/llm.py` has an unused LLM-based `translate()` helper with zero call sites in `app/`. |
| **Voice/track separation before transcribe** | 🟢 shipped (opt-in, off by default) | Buzz (Demucs option), Krisp | — | Was marked absent; confirmed `core/separator.py` Demucs htdemucs pre-process with disk cache, `demucs_enabled` config toggle. |
| **PII / entity redaction** | 🔴 absent | AssemblyAI, ElevenLabs Scribe v2, Otter | M | Healthcare/legal users need "bleep card numbers" + entity timestamps. Re-confirmed absent 2026-07-04. |
| **Sound-event tags** (`[Music]`, `[Applause]`) | 🔴 absent | ElevenLabs Scribe v2, SenseVoice (AED) | M | Required for SDH-compliant subtitles. Re-confirmed absent 2026-07-04. |
| **Cancel mid-transcription** | 🟢 yes | 🟢 all | — | Done. |
| **Auto-resume after crash** | 🟢 shipped | MacWhisper (auto-resume), Buzz | — | Was marked "marks but doesn't re-queue"; confirmed a "Resume interrupted transcriptions?" prompt at startup that re-enqueues on accept (`app/app.py`, `tests/core/test_crash_resume*.py`). |

---

## B. Editor / playback / transcript viewing

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **In-app transcript viewer** | 🟢 shipped | Descript, MacWhisper, Buzz, Vibe | — | Was marked absent; confirmed a full `TranscriptViewer` (`app/dialogs/transcript_viewer.py`, 1524 lines) with a segment Treeview + embedded VLC panel, launched from the Last-Result card, File menu, and queue right-click. |
| **Click-word → seek audio/video** | 🟡 segment granularity, not per-word | Descript (the killer feature), MacWhisper, Buzz | S | Was marked absent; confirmed click-to-seek shipped (`_on_segment_select` → `_seek_to`) but at segment, not literal per-word, granularity — the word label is a non-interactive display. |
| **Inline transcript editing** | 🟡 partial | Descript, MacWhisper, Buzz | M | Was marked absent; confirmed find/replace, filler-strip, and speaker-rename all edit real data, but `_save_changes` writes back only to the source `.json` (no re-export to SRT/VTT/TXT) and there's no free-text cell edit. |
| **Karaoke-style word highlight during playback** | 🟢 shipped | Descript, MacWhisper, Buzz | — | Was marked absent; confirmed `_update_karaoke` (bisect over segment starts, 250ms VLC-position poll). |
| **Search inside transcripts** | 🟡 partial | Otter, Descript, MacWhisper | S | Was marked absent; confirmed in-viewer search is shipped, but the separate FTS5+semantic cross-history search engine (`core/search.py`, fully built and tested) is imported by zero files under `app/` — no UI entry point. |
| **Speaker rename (global)** | 🟢 shipped | Descript, MacWhisper, Otter | — | Was marked absent; confirmed right-click rename (`_rename_speaker`) applies everywhere within the open transcript (there's no cross-transcript speaker identity to rename globally against). |
| **Filler-word remove** ("uh"/"um" bulk delete) | 🟢 shipped | Descript, Riverside, CapCut | — | Was marked absent; confirmed `_FILLER_WORDS` + `_strip_fillers()` with a confirm dialog. |
| **Find-and-replace across transcript** | 🟢 shipped | Descript, MacWhisper, Buzz | — | Was marked absent; confirmed a real `FindReplaceDialog` (find-next/replace/replace-all, case toggle, backreference-safe). |
| **Embed media player** (audio waveform / video frame) | 🟢 shipped | Descript, MacWhisper, Buzz, Vibe | — | Was marked absent; confirmed via `python-vlc` (`_try_load_vlc`/`_init_vlc_player`) with a graceful fallback to the system player when VLC is missing. |
| **Word-confidence colour coding** | 🟢 shipped | Descript, ElevenLabs | — | Was marked absent; confirmed `_segment_min_probability()` + tag-based colouring at 0.85/0.6 thresholds. |

---

## C. Output / export

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **SRT / VTT / TSV / TXT / LRC / JSON / MD / DOCX / PDF / oTranscribe / ELAN / InqScribe / Express Scribe** | 🟢 13 formats (`core/writers/`) | Buzz 3, MacWhisper 5, Vibe 4 | — | **We're well ahead here** — updated 2026-07-04; DOCX/PDF/MD shipped since (at least) v1.0.3, oTranscribe EMIT added same day as this correction. |
| **DOCX export** | 🟢 shipped (`core/writers/docx_writer.py`) | MacWhisper (DOCX), Buzz (DOCX), Otter | — | Was marked absent; confirmed implemented + tested (`tests/core/test_writers.py`). |
| **PDF export** | 🟢 shipped (`core/writers/pdf_writer.py`, `reportlab`) | MacWhisper, Descript | — | Was marked absent; confirmed implemented + tested. |
| **Markdown export** | 🟢 shipped (`core/writers/md.py`) | Descript | — | Was marked absent; confirmed implemented + tested. |
| **SCC / EBU-STL** (broadcast caption formats) | 🔴 absent | Descript, EZTitles | M | Niche but high-value for TV/news clients. |
| **Burn subtitles into the video** | 🔴 absent | MacWhisper, Descript, CapCut | M | `ffmpeg -vf subtitles=…` — we already ship ffmpeg. |
| **Per-format batch export from one transcript** | 🟡 partial | MacWhisper ("export TXT + SRT + DOCX in one click") | S | Was marked absent; confirmed `core/convert.py` + the app's Convert-transcript dialog re-export any transcript to any other single format post-hoc (no ASR re-run, 16 tests) — but the picker is single-select, not a literal one-click multi-format batch. |
| **Output filename templating** | 🟢 shipped | MacWhisper, Buzz | — | Was marked absent; confirmed `output_filename_template` (default `"{base}.{ext}"`) supports `{base}/{ext}/{lang}/{date}/{speaker_count}` tokens, a malformed-template fallback, and a path-traversal guard, tested (9+ tests). Not yet documented in `docs/CONFIG.md` — a docs gap, not a code gap. |
| **Output directory templating** | 🟡 partial | MacWhisper, Buzz | S | Was marked hard-coded; confirmed the same template mechanism supports a sibling subfolder (e.g. `"transcripts/{base}.{ext}"`, auto-created, tested) — but the path-traversal guard rejects any path outside the source file's own directory, so one common folder across different source directories is still impossible. |

---

## D. Workflow / ingestion

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **Drag-and-drop into the window** | 🟢 shipped (optional dep) | Buzz, MacWhisper, Vibe, Descript | — | Was marked absent; confirmed via `tkinterdnd2` (graceful no-op if missing), tested (`tests/core/test_dnd_paths.py`). |
| **Batch queue of dozens of files in one go** | 🟢 shipped | MacWhisper batch exporter, Buzz, Vibe | — | Was marked single-file-picker; confirmed `browse()` uses `askopenfilenames` (plural) and enqueues each. |
| **Watched folders** ("transcribe everything I drop into `D:\inbox\`") | 🟢 shipped (optional dep) | MacWhisper, Buzz | — | Was marked absent; confirmed `core/watcher.py` `FolderWatcher` (watchdog, lazy-import) + config toggles. |
| **YouTube URL ingestion on the Transcribe tab** | 🟢 shipped | MacWhisper (paste YouTube URL anywhere), Vibe | — | Was marked Download-tab-only; confirmed the Transcribe tab itself detects a pasted URL, auto-fills Download + flips auto-transcribe. |
| **Right-click "Transcribe this" in Explorer / Finder** | 🟢 shipped (optional, default-on install task) | MacWhisper (Services menu), VLC + plugin | — | Was marked absent; confirmed `HKCR\*\shell\WhisperProjectTranscribe` registered by both installers' default-on `shellext` task. |
| **CLI mode** (`WhisperProject.exe transcribe a.mp4`) | 🟢 shipped | Buzz (`buzz-captions transcribe …`) | — | Was marked absent; confirmed real `transcribe`/`serve` subcommands (`gui.py` `_build_argparser()`), live-verified via `python gui.py --help`. |
| **Per-project / per-folder settings** | 🟢 shipped | MacWhisper (per-folder rules) | — | Was marked single-global-config; confirmed `.whisperproject.json` overrides (`core/config.py` `load_project_overrides()`), wired into both the desktop transcriber and the HTTP server job path. |
| **Recent files menu** | 🟢 shipped (File → Recent files, `app/app.py`) | every comparable app | — | Was marked absent; confirmed implemented. |

---

## E. UI / presentation

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **System tray icon + minimise-to-tray** | 🟢 shipped (`app/widgets/tray.py`) | Superwhisper, Wispr Flow, Handy, VoiceTypr | — | Was marked absent; confirmed implemented + tested (`tests/core/test_tray.py`). |
| **Windows toast notification on completion** | 🟢 shipped — bell **and** native toast | MacWhisper (NSUserNotification), Buzz | — | Was marked bell-only; confirmed `tray.notify()` fires on every completed job and calls pystray's native toast whenever pystray+Pillow are present. |
| **Internationalised UI** | 🟢 English-only **by design** | MacWhisper (multiple), Buzz | — | Scope choice: this app targets English-speaking users. Multi-language UI is explicitly out of scope. The SMTV scraper accepts non-English URLs but the UI labels stay English. |
| **RTL layout support** | 🟢 not applicable (English-only) | Most modern Qt/Electron apps | — | Out of scope by the same scope choice above. |
| **Dark / light theme** | 🟢 yes (sv-ttk) | 🟢 most | — | Done. |
| **High-DPI scaling** | 🟢 shipped | MacWhisper, modern Qt apps | — | Was marked implicit-default; confirmed an explicit `_apply_hidpi_scaling()` using `winfo_fpixels("1i")`, tested (`tests/core/test_app_hidpi.py`, 5 tests). |
| **Resizable / dockable result panel** | 🟡 nuanced | Descript, Buzz | — | The Last Result card itself is fixed by design, but the transcript viewer it launches (`transcript_viewer.py`) is a separate resizable Toplevel with a real `ttk.PanedWindow` draggable sash. |
| **Window state persistence** (remember size / position) | 🟢 shipped | every modern desktop app | — | Was marked absent; confirmed `window_geometry` is restored on launch and saved on exit (`app/app.py`). |
| **Keyboard shortcuts** (Ctrl+O Browse, Ctrl+Enter Transcribe, Esc cancel, Ctrl+Q exit) | 🟢 shipped (README.md) | Buzz, MacWhisper | — | Was marked absent; confirmed implemented. |
| **Accessibility / screen reader** | 🔴 untested | Apple-first apps inherit it | L | Tk accessibility on Windows is weak; UIA is partial. |

---

## F. Distribution and trust

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **Code-signed exe** (no SmartScreen warning) | 🔴 unsigned | MacWhisper (Developer ID), Buzz (since 2023, Sectigo) | M | Costs ~$200/year for a cert + signing pipeline. Without it, first-launch always trips SmartScreen. |
| **Notarised macOS build** | 🟡 not notarised, but no longer Windows-only | MacWhisper, Buzz | M | Was marked N/A/Windows-only; confirmed 3 real macOS paths exist (PyInstaller `.app`→`.dmg`, `install.command` source venv, Homebrew formula) — `macos-compileall-script-test.yml` completed successfully on a real macOS runner 2026-07-04, and `macos-app.yml` has prior successful arm64+x86_64 runs. Still explicitly unsigned/un-notarised. Effort is now M (buy an Apple Developer cert) rather than XL — the porting work is already done. |
| **Auto-update from inside the app** | 🟡 partial — notify-only | Buzz (Squirrel), MacWhisper (Sparkle), Vibe | S | Was marked absent; confirmed `core/updates.py` + a Help-menu "Check for updates" hit the GitHub releases API and compare versions, but only ever notify (`_on_update_result` calls `webbrowser.open`) — no auto-download/install. |
| **Per-machine install + per-user override** | 🔴 absent — admin-only | MacWhisper, Buzz | S | Verified 2026-07-04: both `installer.iss` and `installer_embed.iss` hardcode `PrivilegesRequired=admin` with no `PrivilegesRequiredOverridesAllowed`; `docs/INSTALL.md` confirms "Asks for admin rights (Yes)" with no alternative. The Portable ZIP is a separate distribution method, not a per-user installer mode. |
| **Linux / Flatpak / AppImage** | 🟡 Linux is real, just not packaged | Buzz (.deb, AppImage), Vibe (.deb, AppImage) | L | Was marked Windows-only; confirmed `platform/linux/{install,update,uninstall}.sh` + a full Ubuntu CI matrix (Python 3.11/3.12 under xvfb-run) — a real, tested source/venv install path exists, just no `.deb`/Flatpak/AppImage binary yet. |
| **Reproducible builds** | 🔴 not enforced | Tor Project, Reproducible Builds Project | M | A Method-A user who hash-compares the binary to ours would not get a match because of build-time inputs. |
| **Crash reporting** | 🟡 Sentry available but commented out | Buzz uses sentry-sdk | XS | Just uncomment + flip a config; need to add a UI consent toggle. |
| **Opt-in usage telemetry** | 🟢 shipped (`core/stats.py`, `telemetry_opt_in` config key, off by default) | Vibe (anonymous metrics, off by default), MacWhisper | — | Was marked absent; confirmed implemented (host/hardware/app-version fields added v1.5.0). |
| **GitHub Actions CI** | 🟢 shipped — `.github/workflows/ci.yml` (Windows + Ubuntu, Python 3.11/3.12) gates every push/PR, plus 7 macOS workflows | Buzz (matrix Win/Mac/Linux), Vibe | — | Was marked absent; confirmed implemented and green. |
| **Release-notes RSS / API integration** | 🔴 manual `gh release create` | Modern desktop tooling | S | A `latest.json` we can publish so future auto-update can pick it up. |

---

## G. Project / community health

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **Contributor docs** (`CONTRIBUTING.md`) | 🟢 shipped (2026-07-04) | Buzz (full), Vibe (full) | — | Was marked absent; added. |
| **`CODE_OF_CONDUCT.md`** | 🟢 shipped (`.github/CODE_OF_CONDUCT.md`) | Buzz, Vibe (CC) | — | Was marked absent; confirmed already present. |
| **Issue templates** | 🟢 shipped (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`) | Buzz, Vibe | — | Was marked absent; confirmed already present. |
| **PR template** | 🟢 shipped (`.github/pull_request_template.md`) | Buzz, Vibe | — | Was marked absent; confirmed already present. |
| **Discussions enabled** | 🟢 enabled (2026-07-04) | Buzz (active), Vibe (active) | — | Was "status unknown"; now on. |
| **A test suite that runs in CI** | 🟢 1700+ tests, gated on every push/PR (Windows + Ubuntu) | Buzz (GH Actions), Vibe (CI matrix) | — | Was "no CI gate"; confirmed CI-gated (see GitHub Actions row above). |
| **Coverage report published** | 🔴 absent (we generate `.coverage` but never publish) | Buzz | XS | Codecov / Coveralls badge in the README. |
| **Versioned API / SDK docs** | 🔴 absent (no public Python API beyond running the app) | MacWhisper (HTTP API in Pro), Buzz (CLI) | M | Anyone wanting to embed our transcription as a library has to copy from `core/`. |
| **Sample data / demo media** in the repo | 🔴 absent (smoke tests need a private E: drive video) | Buzz (small sample), Vibe | XS | A 10 s public-domain clip checked into `tests/fixtures/` would let outside contributors run the smoke suite. |
| **Localised documentation** | 🟡 INSTALL.md has Persian section; rest is English | Buzz (English, Vibe (15+ langs in app) | M | If the UI is going to be internationalised (E above), docs follow. |
| **Versioning policy** (SemVer? CalVer?) | 🟡 we used 0.3 → 0.6 → 0.7 without a stated policy | most | XS | A line in CHANGELOG.md saying which scheme we use. |
| **Stability promise per public API** | 🔴 no contract; users of `core/integrations/` are on their own | rare in this space — fine | — | Worth a note that internal modules may break. |

---

## H. Performance / packaging

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **Installer size** | 🟢 Setup-Standard ~226 MB, Portable ~343 MB | Buzz Windows: ~ 220 MB, Vibe: ~ 60 MB (Tauri lighter) | — | Was describing the unshipped PyInstaller onefile (now ~447 MB per `BUILD.md`); corrected 2026-07-04 to the artifacts actually shipped (v1.5.0 release, sizes cross-verified local disk vs `gh release view`). Competitive with Buzz. |
| **Cold start** | 🟢 ~ 1.9 s warm, ~ 4.7 s fresh disk cache (shipped embed launch) | Buzz: ~ 4 s; MacWhisper: < 1 s native | — | Verified 2026-07-04 with a real stopwatch measurement against `embed_build/` (`pythonw.exe gui.py`, the actual Setup-Standard launch mechanism — no PyInstaller bootloader at all, so the old "onefile"/"onedir" framing didn't match what ships). Competitive with Buzz either way. |
| **Memory footprint** | 🟡 ~ 2 GB once model is loaded | Buzz (model-dependent same), MacWhisper (Apple Neural Engine — much less) | — | Inherent to faster-whisper large-v3. Smaller model = lower memory; the whisper.cpp q5_0 backend (~1.1 GB) is already a lower-memory alternative. |
| **GPU acceleration tested on each release** | 🔴 only CPU smoke runs in the test suite | Buzz (GPU smoke per release in CI) | S | Without GPU testing, a ctranslate2 / CUDA upgrade can silently break GPU users. Re-confirmed 2026-07-04 — the CI matrix is Windows/Ubuntu CPU-only across all 9 workflow files. |
| **Streaming model download with resume + checksum** | 🟢 already implemented in `core/model_manager.py` | most cloud-down apps lack this | — | Done; better than peers actually. |
| **Quantised model support** (int4, int8, q5_0 from whisper.cpp) | 🟢 shipped — q5_0 | Buzz / Vibe (whisper.cpp ggml q5_0, q4_K_M) | — | Was marked int8-only; confirmed `core/backends/whisper_cpp.py` runs ggml q5_0 (~1.1 GB) via pywhispercpp, one-click download in the Advanced dialog, 7+ tests. Only q5_0 is wired (no q4_K_M), so a smaller residual gap remains. |

---

## I. SMTV / yt-dlp / integration

| Feature | Us | Peers | Effort | Notes |
|---|---|---|---|---|
| **yt-dlp passthrough** | 🟢 yes, with auto-transcribe wiring | Buzz (YT URL paste), MacWhisper (YT URL paste) | — | Done. |
| **Supreme Master TV native scraper** | 🟢 yes (Session 11) | nobody else has this | — | **Unique.** |
| **Other niche video site scrapers** (Aparat, ArvanCloud VOD, our user's likely Persian sources) | 🔴 absent | none in this category — but bespoke scrapers are routine | per-site M | Pattern is established by `core/integrations/smtv.py`; copy-paste for new sites. |
| **Subtitle download from YouTube** | 🟢 supports yt-dlp subtitle phase | Buzz/MacWhisper rely on YouTube directly | — | Done. |
| **Live URL (RTMP, HLS) ingestion** | 🔴 absent | Buzz no, Vibe no, WhisperLive yes | L | Would require server-mode and is a different product. |

---

## J. The honest "where do we stand" verdict

**Rewritten 2026-07-04** — a two-agent, evidence-based re-audit of this entire document found the large majority of the original May-2026 "gaps" had already shipped since: speaker diarization, DOCX/PDF/Markdown export, the full in-app transcript viewer (VLC playback, karaoke highlight, find-and-replace, filler strip, word-confidence colour, speaker rename), all 5 ASR backends, the hardware wizard + model picker, Demucs separation, crash auto-resume, drag-and-drop, watched folders, multi-select batch queue, right-click Explorer integration, CLI mode, per-folder overrides, GitHub Actions CI, and opt-in telemetry. See every row above for the file:line evidence.

We're now a **feature-rich local file transcriber** with an **unusual standout** (SMTV native scraping), a genuinely **full-featured in-app transcript viewer**, and a **modern packaging story** (three install methods, audit-clean code, 1701 tests gated in CI on every push/PR). We are also **one of the only Windows-first Whisper apps that bundles the model download + ffmpeg + yt-dlp + a real UI in a single install**, which Buzz and Vibe piece together with separate steps.

The five things actually keeping us behind the leaders now, in priority order:

1. **System-wide dictation hotkey.** The one large, unambiguous absence left in the whole document. Defines the entire Superwhisper / Wispr Flow category that's growing fastest in 2025/2026. Effort: XL. Impact: 9/10.
2. **True streaming live mic transcription.** The "Live" tab today is record-then-transcribe (mic/system-audio to WAV, then the normal pipeline), not continuous streaming. Whisper-Streaming's LocalAgreement-n is the proven pattern. Effort: L. Impact: 7/10.
3. **Word-level click-to-jump + real inline re-export editing.** The transcript viewer already does almost everything peers do (karaoke highlight, find/replace, filler-strip, speaker rename) — the two gaps left are segment- (not word-) granularity seeking and edits that save back only to the source `.json` with no re-export to SRT/VTT/TXT. Effort: M. Impact: 7/10 — closes out what used to be our single biggest gap (section B).
4. **Trust: code-signing (Windows) + notarisation (macOS).** Both installers/builds are unsigned, so Windows SmartScreen and macOS Gatekeeper both warn on first launch. The macOS side now has 3 working build paths (just needs a cert); Windows just needs a ~$200/yr signing cert + pipeline. Effort: M each. Impact: 6/10 (first-run friction, not a functional gap).
5. **Translation exposure** (`task="translate"`). Whisper already supports translate-to-English internally; we never expose it in the UI. Cheap relative to its impact for non-English-source users. Effort: M. Impact: 5/10.

Everything else in this document is real and reasonable to address over time (per-project hotword glossary, PII redaction, sound-event tags, a q4_K_M quantised model, a single shared output folder across source directories, GPU-per-release CI), but the five above are the ones that would most change how users describe the product today.

---

## Sources

- [MacWhisper feature reviews 2026](https://daveswift.com/macwhisper/), [MacWhisper Pro features](https://www.getvoibe.com/resources/macwhisper-pricing/), [MacWhisper speaker recognition docs](https://macwhisper.helpscoutdocs.com/article/32-automatic-speaker-recognition-in-macwhisper)
- [Buzz Captions GitHub](https://github.com/chidiwilliams/buzz), [Buzz 2026 review](https://www.aitoolsdigest.com/blog/buzz-transcription-app-review-2026), [Buzz docs](https://chidiwilliams.github.io/buzz/docs)
- [Vibe (thewh1teagle)](https://github.com/openai/whisper/discussions/2293), [Tauri+whisper.cpp landscape 2026](https://dev.to/ottoaria/tauri-in-2026-build-cross-platform-desktop-apps-with-web-technologies-better-than-electron-11mo)
- [Superwhisper, Wispr Flow, MacWhisper 2026 comparison](https://spokenly.app/blog/wispr-flow-vs-superwhisper-vs-macwhisper)
- [WhisperX, stable-ts, WhisperKit, Whisper-Streaming, WhisperLive](../docs/COMPETITIVE_ANALYSIS_2026.md#a-open-source-landscape-we-have-not-yet-evaluated)
- [Descript transcript-driven editor product page](https://www.descript.com/)
- Our own [ROADMAP.md](ROADMAP.md) — Phases 4–7 already plan a chunk of this.
