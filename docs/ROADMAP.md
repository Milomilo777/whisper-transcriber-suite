# Roadmap

The prioritized plan for turning this from a working draft into a masterpiece. Every item names the source of inspiration (which competitor does this well), the rough effort, and the reason it matters. See `AUDIT.md` for the findings that justify the priorities; see `ARCHITECTURE.md` for the current shape.

Effort labels:

- **XS** — under an hour
- **S** — half a day
- **M** — one to three days
- **L** — a week
- **XL** — more than a week

---

## Progress snapshot

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — correctness baseline + docs | **DONE** (`50a4fea`) | All CRITICAL and HIGH AUDIT items fixed; full docs suite published |
| Phase 1a — theme + platformdirs + logging | **DONE** (`376141a` + 3 prior) | `sv-ttk`, `%LOCALAPPDATA%` paths, RotatingFileHandler |
| Phase 1b — split gui.py + tests + type hints + Sentry | **DONE** (Session 5) | `gui.py` 11 lines; `app/` package with services + dialogs + widgets + observability; 80 tests; pyright clean; `pyproject.toml` with optional deps. See `docs/PHASE_1B_ACCEPTANCE.md`. |
| Phase 2a — Whisper as serious transcription tool | **DONE** (Session 5) | VAD on by default + tunable; word timestamps opt-in; `BatchedInferencePipeline` on CUDA; multi-format writers (SRT/VTT/TSV/TXT/JSON/LRC); language detection in queue; Advanced settings dialog. See `docs/PHASE_2A_ACCEPTANCE.md`. Phase 2b (UI for `initial_prompt` / `hotwords`, model picker, presets) deferred. |
| Phase 2-oTranscribe — file-format compatibility | **DONE** (Session 4) | Tier 1 + Tier 2 shipped: bidirectional `.otr` converter, Export/Import UI, `Help → Open oTranscribe`. See [docs/integrations/otranscribe-acceptance.md](integrations/otranscribe-acceptance.md). Tier 3 (vendored fork, in-app editor, forced alignment) deferred — see Phase 5 backlog. |
| Phase 3a — yt-dlp as serious downloader | **DONE** (Session 5) | `--progress-template` JSON; SQLite history DB + `Statistics` menu; SponsorBlock category list in Advanced dialog; auto-transcribe-after-download fully wired; right-click `Open output folder` + `Re-run`. See `docs/PHASE_3A_ACCEPTANCE.md`. |
| Phase 4 — editor and viewer | TODO | Click-word→audio, edit-back-to-subtitle, gap detection, speaker rename, filler removal (re-prioritized after Session 6 research — see `docs/COMPETITIVE_ANALYSIS_2026.md` §4) |
| Phase 5 — power features | TODO | Diarization, vocal separation, live mic, REST, CLI |
| Phase 6 — CJK polish + backend abstraction | NEW (Session 6 research) | SenseVoice + Parakeet backends, Chinese punctuation post-processor, CJK line splitting, simplified↔traditional normalization. See `docs/COMPETITIVE_ANALYSIS_2026.md` §1-3 |

Integration briefs live under `docs/integrations/` and follow a separate cadence from the numbered phases — each is a single hands-off session.

**Visual:** [`docs/architecture.svg`](architecture.svg) renders the system at-a-glance: UI layer, services, subprocess workers, vendored binaries, filesystem state, external network. Color-coded by layer; killer-flow `auto-transcribe-after-download` is highlighted in red.

---

## Research notes

- **`docs/COMPETITIVE_ANALYSIS_2026.md`** (Session 6) — 2026 snapshot of the speech-to-text landscape: Alibaba FunAudioLLM stack (SenseVoice / FunASR / CapsWriter), NVIDIA NeMo (Parakeet-TDT-0.6B-v3, Canary-1B-v2), Whisper speedups (Insanely-Fast-Whisper, WhisperX, stable-ts, WhisperKit), commercial reference (Deepgram Nova-3, AssemblyAI LeMUR, ElevenLabs Scribe v2, Descript, MacWhisper 12, Apple Voice Memos). Synthesizes 15 candidate features, Chinese-specific gotchas, backend abstraction proposal, Phase 4 editor blueprint.

## Completed integrations

- **oTranscribe** (Session 4) — bidirectional `.otr` ↔ SRT round-trip, Export/Import UI, `Help → Open oTranscribe`. Reference: [research note](integrations/otranscribe-research.md), [implementation brief](integrations/otranscribe-brief.md), [acceptance plan](integrations/otranscribe-acceptance.md).
- **Supreme Master TV download** (Session 11) — Download tab auto-detects SMTV episode URLs (`/{lang}1/v/<id>.html`), reads `videoPlayerData` from the page, exposes 1080p/720p/396p MP4 plus an MP3 audio mode in the existing dropdowns. Multi-part series get a "Download all parts" checkbox (default on). Page-embedded article transcript is saved as `<base>.txt` next to the media; auto-transcribe-after-download still runs on top for the whisper SRT/JSON. No new dependencies, stdlib only. Reference: [research note](integrations/smtv-research.md), [implementation brief](integrations/smtv-brief.md), [acceptance plan](integrations/smtv-acceptance.md).

---

## Phase 0 — Critical fixes (do this week)

These are correctness or trust-breaking issues. The user gets a better product the moment they merge.

| # | Item | Source | Effort | Why |
|---|------|--------|--------|-----|
| 0.1 | Stop `yt-dlp --update` from blocking every download (AUDIT A1) | own audit | XS | One offline user = zero downloads |
| 0.2 | Replace bare `except:` in `transcriber.detect_device` with `except (ImportError, AttributeError):` (AUDIT A2) | own audit | XS | Ctrl+C currently disappears |
| 0.3 | Make `get_duration` use `bin/ffprobe.exe` instead of `ffprobe` on PATH (AUDIT A3) | own audit | XS | Hard-fails on clean machines |
| 0.4 | Atomic write for `config.json` (AUDIT C1) | own audit | XS | Crash-during-save = corrupt config |
| 0.5 | `load_config` fallback to defaults if file missing/corrupt (AUDIT C2) | own audit | XS | First-run UX, recovery from C1 |
| 0.6 | Add `.gitignore`, `requirements.txt`, `README.md`, `LICENSE` | basic hygiene | S | New contributors / users can find their way |
| 0.7 | Gate `current_video_language` capture on URL match (AUDIT A4) | own audit | XS | Wrong language hint on rapid URL changes |
| 0.8 | Delete partial subtitle file on cancel (AUDIT A5) | own audit | XS | Already a documented limitation |

**Total estimate:** one to two days. The whole of Phase 0 should ship as one PR titled "Phase 0: correctness baseline."

---

## Phase 1 — Foundation (next 2-3 weeks)

Set the stage for sustainable growth: modern look, sane logging, proper packaging, tests. None of this is user-visible feature work, but every later phase depends on it.

### 1.1 Modern theme with sv-ttk — DONE (Phase 1a)

- **Source:** rdbende/Sun-Valley-ttk-theme
- **Effort:** XS (10 minutes)
- **Why:** Default Tk look is the single biggest "amateur software" signal. Two lines of code give us Windows 11 styling for free.
- **Implementation:**
  ```python
  import sv_ttk
  sv_ttk.set_theme(self.app_config.get("theme", "dark"))
  ```
  Add a theme picker (Light / Dark / System) in a new Settings dialog.

### 1.2 platformdirs for config and logs — DONE (Phase 1a)

- **Source:** standard practice
- **Effort:** S (2 hours)
- **Why:** Today `config.json` lives next to the executable. That breaks the moment we ship a signed installer that puts the exe in `Program Files\` (read-only). It also forces every user on a shared machine to share settings.
- **Implementation:**
  - `config.json` → `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` (via `platformdirs.user_config_dir`)
  - First-run migration: if old `config.json` is next to the exe, copy it to the new location and rename old to `.bak`
  - Model cache → `%LOCALAPPDATA%\WhisperTranscriberSuite\models\` instead of the current `X:\whisper_cache2\...`

### 1.3 Proper logging — DONE (Phase 1a)

- **Source:** standard practice
- **Effort:** S
- **Why:** Currently a mix of `print()` and a Tk Text widget. Crash diagnostics are lost when the user closes the app.
- **Implementation:**
  - `logging.getLogger(__name__)` in every module
  - `RotatingFileHandler` at `%LOCALAPPDATA%\WhisperTranscriberSuite\logs\app.log`, 5 MB × 3 backups
  - Worker subprocess uses a `QueueHandler` that writes to stderr (parent already captures stderr)
  - Stdout protocol stays JSON-only — see AUDIT B7
  - "Open log folder" menu item

### 1.4 Split `gui.py` (Phase 1 of refactor)

- **Source:** common Python desktop project structure
- **Effort:** M
- **Why:** 1156 lines blocks understanding and testing. See AUDIT B1.
- **Implementation:** the conservative split first — keep `App` class, but extract:
  - `app/dialogs/model_dialog.py` ← `ModelDownloadDialog`
  - `app/domain/tasks.py` ← `TranscriptionTask`, `VideoDownloadTask`
  - `app/domain/languages.py` ← `SUBTITLE_LANGUAGES`
  - `app/services/format_service.py` ← `lookup_formats`, `poll_format_events`
  - `app/services/download_service.py` ← `build_download_command`, `build_subtitle_command`, `process_download_queue`, `poll_download_events`
  - Whatever's left in `gui.py` is the `App` class wiring the rest together. Should be under 400 lines.

### 1.5 `requirements.txt` / `pyproject.toml` — PARTIALLY DONE (Phase 1a)

- **Source:** standard
- **Effort:** XS
- **Why:** AUDIT D18.
- **Implementation:** `pyproject.toml` with `[project.optional-dependencies]` for `gpu`, `dev`, `test`. Pin lower bounds, not upper.
- **Status:** `requirements.txt` ships sv-ttk and platformdirs in active deps. `pyproject.toml` migration deferred to Phase 1b.

### 1.6 Tests for `core/` (Phase 1 of test coverage)

- **Source:** standard
- **Effort:** M
- **Target coverage:** 80% on `core/`
- **Priority order:**
  1. `tests/test_subtitle_lang_args.py` — pure-function, written first as a smoke test of the test infra
  2. `tests/test_model_manager.py` — mock `requests`, exercise MD5 parsing, mismatch handling, resume from partial download
  3. `tests/test_worker_protocol.py` — spawn worker, feed a 1-second silent WAV, assert event sequence
  4. `tests/test_config.py` — atomic write, fallback to defaults
- Add GitHub Actions CI: pytest + ruff + (optionally) pyright

### 1.7 Type hints on `core/`

- **Source:** standard
- **Effort:** S
- **Why:** AUDIT B2.
- **Implementation:** strict pyright on `core/`, basic on `app/`. `pyproject.toml`:
  ```toml
  [tool.pyright]
  include = ["core", "app"]
  strict = ["core"]
  ```

### 1.8 Sentry crash reporting

- **Source:** common practice
- **Effort:** XS
- **Why:** Free tier is generous, and we have zero visibility into user-side failures today. Especially important for the model download path which has many failure modes.
- **Implementation:** `sentry_sdk.init(dsn=..., traces_sample_rate=0.0, before_send=scrub_pii)`. A setting to disable it. Privacy disclosure in README.

---

## Phase 2 — Whisper as a serious transcription tool (next 1-2 months)

These features take us from "wraps faster-whisper with defaults" to "comparable to Buzz / CheshireCC / WhisperX for the workflows we care about."

### 2.1 Voice Activity Detection (VAD)

- **Source:** Whisper-WebUI, Buzz, Purfview/whisper-standalone-win
- **Effort:** XS (one line) + S (UI)
- **Why:** Single biggest accuracy win. Eliminates hallucinations on silence and music. Should be on by default.
- **Implementation:**
  ```python
  segments, info = MODEL.transcribe(
      file,
      vad_filter=True,
      vad_parameters=dict(
          min_silence_duration_ms=settings.vad_min_silence_ms,
          speech_pad_ms=settings.vad_pad_ms,
          threshold=settings.vad_threshold,
      ),
  )
  ```
  UI: checkbox (default on) + advanced panel with two sliders.

### 2.2 Word-level timestamps

- **Source:** every modern Whisper GUI
- **Effort:** S
- **Why:** Karaoke-style subtitles, accurate line splits at word boundaries, color-coded low-confidence words, foundation for the integrated editor (2.7).
- **Implementation:** `word_timestamps=True` adds a `words: list[dict]` per segment. Include in the JSON output. Use for VTT karaoke and LRC formats.

### 2.3 Language detection display

- **Source:** Buzz, CheshireCC
- **Effort:** XS
- **Why:** `info.language` and `info.language_probability` are already returned. We just don't show them.
- **Implementation:** emit a `language_detected` event from the worker; show "Detected: Persian (97%)" in the UI before transcription kicks in.

### 2.4 Multi-format output

- **Source:** standard across all competitors
- **Effort:** S
- **Why:** AUDIT D12.
- **Implementation:** factor the output writers out of `transcriber.transcribe()` into a `core/writers/` module: `SrtWriter`, `VttWriter`, `TsvWriter`, `JsonWriter`, `TxtWriter`, `LrcWriter`. Steal logic from `openai-whisper`'s `whisper/utils.py` (MIT-licensed, well-tested).

### 2.5 BatchedInferencePipeline for GPU

- **Source:** faster-whisper documentation
- **Effort:** XS
- **Why:** 3-12× speedup on GPU for long files. One-line wrapper.
- **Implementation:**
  ```python
  if device == "cuda":
      MODEL = BatchedInferencePipeline(model=MODEL)
  ```

### 2.6 Robust device detection with CTranslate2

- **Source:** AUDIT D14, faster-whisper best practice
- **Effort:** S
- **Why:** Current `torch.cuda.is_available()` check requires torch even on CPU users. CTranslate2 has native device introspection.
- **Implementation:** replace `detect_device` with `ctranslate2.contains_cuda_device()` and `ctranslate2.get_supported_compute_types()`. Drop the torch dependency entirely (we don't need it for inference).

### 2.7 Model picker + lazy model downloader

- **Source:** CheshireCC, cbro33
- **Effort:** M
- **Why:** Today the user gets exactly one model (`large-v3`, 3 GB on disk). Need at least:
  - `tiny`, `base`, `small`, `medium`, `large-v3` — official whisper sizes
  - `distil-large-v3` — 6× faster, English-only
  - Custom HuggingFace repo ID (`Systran/faster-whisper-...`)
- **Implementation:** rework `config.json` to `{ "models": [...], "active_model": "large-v3" }`. UI: a model picker in Settings; the model is downloaded on first use, not at startup. Reuse the existing `ensure_model` + MD5 verify path with per-model URL/manifest.

### 2.8 Initial prompt and hotwords UI

- **Source:** faster-whisper docs
- **Effort:** S
- **Why:** Domain accuracy on names like "Supreme Master Ching Hai", "Loving Hut", proper nouns and jargon improves dramatically. Cheap to expose.
- **Implementation:** a multi-line text field for `initial_prompt` and a single-line field for `hotwords`. Saved per-preset (2.10).

### 2.9 Translate-to-English toggle

- **Source:** Whisper-WebUI, CheshireCC
- **Effort:** XS
- **Why:** AUDIT D9. The user produces bilingual content; toggling `task="translate"` produces English from Persian audio.
- **Implementation:** radio buttons "Transcribe / Translate to English."

### 2.10 Preset system

- **Source:** dsymbol/yt-dlp-gui, Stacher
- **Effort:** M
- **Why:** Save a named bundle of settings (model, VAD params, initial_prompt, hotwords, output formats, output folder template) and apply with one click. Critical for the BMD workflow.
- **Implementation:** `~/.config/whisper-transcriber-suite/presets/<name>.toml`. Preset picker in the main UI. Ship 3-4 starter presets: "Supreme Master TV (Persian)", "Podcast English", "Music video", "Meeting notes".

### 2.11 Subtitle splitting heuristics

- **Source:** stable-ts, Netflix/BBC subtitle standards
- **Effort:** M
- **Why:** Raw segments from faster-whisper are often too long for TV display. Industry standards: max 42 chars/line, max 2 lines, CPS ≤ 17, min display 0.83s.
- **Implementation:** post-processor in `core/writers/` that consumes word-level timestamps and emits clean subtitle blocks. Configurable.

### 2.12 Drag-and-drop + folder watcher

- **Source:** CheshireCC, Buzz
- **Effort:** S (DnD) + M (folder watcher)
- **Why:** AUDIT D6, D7.
- **Implementation:**
  - DnD: `tkinterdnd2` on the Transcribe tab
  - Folder watcher: a separate tab "Watch folder", uses `watchdog` to enqueue new files automatically. New audio/video files appearing in the watched folder get transcribed.

---

## Phase 3 — yt-dlp as a serious downloader (1-2 months)

Currently the yt-dlp tab is a working download front-end. To compete with yt-dlg, Tartube, Open Video Downloader, etc., we need feature parity on the things that matter most.

### 3.1 `--progress-template "%(progress)j"` for robust progress

- **Source:** best-practice across modern yt-dlp wrappers
- **Effort:** XS
- **Why:** Today we regex `[download] N.N%` from stdout. Fragile (the format can change). `--progress-template "%(progress)j"` emits one JSON line per progress event with `downloaded_bytes`, `total_bytes`, `speed`, `eta`.
- **Implementation:** add the flag, replace `percent_re` parsing with `json.loads(line)`.

### 3.2 Auto-update yt-dlp.exe, but properly (fixes AUDIT A1)

- **Source:** cbro33, Seal
- **Effort:** S
- **Why:** AUDIT A1 — the current implementation breaks downloads if the update fails. Need a non-blocking, opt-in update with rate-limiting and SHA256 verification.
- **Implementation:**
  - On launch, async check `https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest`
  - Compare with `bin/yt-dlp.exe --version`
  - If newer, prompt the user (or auto-update if they opted in)
  - Verify SHA256 of the downloaded binary
  - Atomic replace
  - At most one check per day, gated by a timestamp in `config.json`
  - **Never run on the user's download click.** Today's `--update` call must go.

### 3.3 Persistent queue and history

- **Source:** yt-dlg, Tartube, Open Video Downloader
- **Effort:** M
- **Why:** AUDIT D10.
- **Implementation:** SQLite at `%LOCALAPPDATA%\WhisperTranscriberSuite\history.db` with two tables:
  ```sql
  CREATE TABLE downloads (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    folder TEXT,
    format_label TEXT,
    status TEXT,    -- queued / running / finished / cancelled / error
    started_at INTEGER,
    finished_at INTEGER,
    output_paths TEXT,  -- JSON array of files written
    error TEXT
  );
  CREATE TABLE transcriptions (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    model TEXT,
    status TEXT,
    started_at INTEGER,
    finished_at INTEGER,
    duration_seconds REAL,
    language TEXT,
    output_paths TEXT,
    error TEXT
  );
  ```
  Restore non-finished queue items on app start (mark them "interrupted").

### 3.4 Command preview / editable args

- **Source:** Stacher (their killer feature)
- **Effort:** S
- **Why:** Power users want to add `--cookies-from-browser firefox` or `--throttled-rate 1M` without us building UI for every flag.
- **Implementation:** Ctrl+Enter on the Download tab opens a small dialog showing the full constructed command and an "extra args" text box. Persist the extra args in config.

### 3.5 SponsorBlock integration

- **Source:** Tartube
- **Effort:** XS
- **Why:** AUDIT D16. Single-line addition.
- **Implementation:** checkbox "Skip sponsored segments (SponsorBlock)" → adds `--sponsorblock-remove sponsor,intro,outro,interaction`.

### 3.6 Cookie / auth wizard

- **Source:** Open Video Downloader
- **Effort:** S
- **Why:** Members-only content, age-restricted content, throttling avoidance via account login.
- **Implementation:** in Settings, a section "Authentication" with:
  - "Use cookies from browser" combo (firefox / chrome / edge / brave) → `--cookies-from-browser`
  - Basic auth fields (rarely needed)

### 3.7 Smart queue with concurrency limit

- **Source:** Open Video Downloader, yt-dlg
- **Effort:** S
- **Why:** Today downloads are serial. For users with bandwidth, allowing 2-3 parallel downloads helps.
- **Implementation:** `parallel_downloads` setting (default 1). `process_download_queue` allows up to N concurrent tasks. Use a `threading.Semaphore`.

### 3.8 Throttling and scheduling

- **Source:** Tartube, yt-dlg
- **Effort:** S (throttle) + M (scheduler)
- **Why:** Politeness to source servers, off-peak downloading.
- **Implementation:** `--limit-rate` and `--throttled-rate` flags exposed in Settings. Scheduler: "Start queue at HH:MM" via `after()` or a small APScheduler.

### 3.9 Simple / Advanced mode toggle

- **Source:** YTPTube (Classic Mode in Tartube)
- **Effort:** S
- **Why:** New users find the format combos overwhelming. Simple mode is just URL + Quality dropdown (Best / 720p / 480p / Audio only).
- **Implementation:** a Settings switch; advanced widgets hidden when Simple is on.

### 3.10 Auto-transcribe after download

- **Source:** **no competitor does this** — our unique value proposition
- **Effort:** S
- **Why:** This is the killer integration: download a YouTube video, automatically queue the resulting file for transcription with `language=` set to whatever yt-dlp detected as the original. Today the user has to manually do step 2.
- **Implementation:** a checkbox "Transcribe after download" in the Download tab. On `download_event "done"`, find the saved media file and call `add_transcription_task(file_path, language=task.detected_language)`.

---

## Phase 4 — Editor and viewer (1-2 months)

Take the app from "produces subtitle files" to "produces good subtitle files that the user can edit and refine."

### 4.1 Integrated transcript viewer

- **Source:** Buzz, aTrain
- **Effort:** L
- **Why:** Click a word in the transcript → audio jumps to that timestamp. Re-export after tweaks. This single feature is what justifies the app over a CLI.
- **Implementation:**
  - A new tab "Edit" that opens after transcription completes (or via right-click on a finished item)
  - Left: scrollable transcript view, one row per segment, each cell editable
  - Right: audio player (use `pygame.mixer` or `simpleaudio` or shell out to ffplay)
  - Word-level highlight follows playback position
  - "Save SRT" / "Save VTT" buttons re-emit the file

### 4.2 Edit-back-to-subtitle with re-flowed timestamps

- **Source:** Descript, competitor synthesis §4 item 4
- **Effort:** M
- **Why:** When the user merges/splits/edits cues in the editor view, the output SRT/VTT must keep working caption sync. Arithmetic redistribution of timestamps (`duration * chars_before / chars_total`) is the standard approach.
- **Implementation:** writer in `core/writers/` that takes the edited segment list (with text changes) and the original word-timestamps, re-distributes proportionally. Add a "preserve original timing" toggle.

### 4.3 Gap / silence detection panel

- **Source:** Riverside, Descript, competitor synthesis §4 item 5
- **Effort:** M
- **Why:** A sortable list of all silences > N seconds. Click → audio jumps. "Delete dead air" command shifts downstream timestamps. Critical for podcast/lecture post-prod.
- **Implementation:** scan VAD output or segment gaps; render a side panel.

### 4.4 Speaker labels with global rename

- **Source:** Descript, MacWhisper 12, competitor synthesis §4 item 2
- **Effort:** M (depends on 5.1 diarization)
- **Why:** Diarization emits `SPK_00`, `SPK_01`. Editor lets the user rename them once (`SPK_01 → Marie`) and the change propagates with a single undo step. Color-code on the timeline.

### 4.5 Filler-word bulk operations (multilingual)

- **Source:** Descript filler-word removal, competitor synthesis §4 item 3
- **Effort:** M
- **Why:** Detect language-specific fillers — EN: `um, uh, like, you know`; FR: `euh, ben, voilà`; DE: `ähm, also`; ZH: `嗯, 啊, 那个, 这个`. Two removal modes: **caption-only** (cleaner subtitles, audio untouched) and **cut** (when audio is re-rendered). The dual-mode is a longstanding Descript pain point users explicitly want.
- **Implementation:** dictionary per language + UI panel ("Found 47 fillers, preview, Remove all in selection").

### 4.6 Subtitle quality linter

- **Source:** subtitle-edit, professional workflows
- **Effort:** M
- **Why:** Flag rows that violate Netflix/BBC rules: CPS > 17 (Latin) / > 12 (CJK), line length > 42 (Latin) / > 16 (zh-Hans) / > 20 (zh-Hant), gap < 0.083s, duration < 0.833s, etc.
- **Implementation:** column in the editor with colored badges; tooltip with the specific violation. CJK rules pulled in from Phase 6.3.

### 4.7 Word-confidence visualization

- **Source:** Buzz, Pikurrot/whisper-gui
- **Effort:** S (depends on 2.2)
- **Why:** Help the user find places to review. Words with `probability < 0.5` get underlined red.
- **Implementation:** color tags in the Text widget tied to word confidence from 2.2.

> **Implementation order** (per `docs/COMPETITIVE_ANALYSIS_2026.md` §4): 4.1 → 4.2 → 4.3 → 4.4 → 4.5. Items 4.1/4.2/4.3 are pure media-player + data-structure work; 4.4/4.5 sit on top of the Phase 5 diarization branch. 4.6/4.7 are independent and can land at any time after 2.2.

---

## Phase 5 — Power features (when there's appetite)

These are the items that take the project beyond "best-in-class for our niche" into "ambitious."

### 5.1 Speaker diarization — SHIPPED v0.7.0 (Session 13)

- **Status:** ✓ Done. `core/diarization.py` wraps sherpa-onnx
  pyannote-segmentation-3.0 + 3D-Speaker CAMPlus EN embedding.
  Toggle on the Transcribe tab; SRT / JSON / MD / DOCX all carry
  speaker labels when present. No HuggingFace token required.
  ONNX models live in `bin/diarization/` and ship with each
  installer.

### 5.1b System-wide dictation hotkey (deferred — needs own session)

- **Source:** Superwhisper, Wispr Flow, MacWhisper (live), Handy,
  VoiceTypr.
- **Effort:** XL. Genuinely large — a full session of its own.
- **Why:** The hottest growth category in 2025/2026 Whisper apps.
  Defines a separate product mode ("dictate anywhere") that
  doesn't fit on the existing Transcribe tab.
- **Why not now:** v0.7.0 already lands four priorities in one
  session (writers, CI, diarization, viewer). Adding a fifth XL
  item would compromise quality on all five. This is the right
  feature to start v0.8 with.
- **Design sketch for the next session:**
  - **Global hotkey listener** — `pynput` or `keyboard` (both
    pip-installable, no admin needed on most Windows setups). One
    background thread, daemon. Hotkey defaults to `Ctrl+Win+Space`.
  - **Audio capture** — `sounddevice` reading 16 kHz mono from the
    default input device into a circular buffer. Stop on second
    press or after 30 s of silence.
  - **Real-time inference** — `distil-large-v3` or `tiny.en` so
    a 5 s clip transcribes in <1 s. Use `faster_whisper.transcribe`
    on the buffer when the user releases the hotkey, not streaming.
    LocalAgreement-n streaming is a future v0.9 step.
  - **Text injection** — `pyautogui.typewrite` or, better,
    `SendInput` via `ctypes` to drop the transcribed text into
    whatever window had focus when the hotkey fired. Honour the
    OS keyboard layout.
  - **System tray icon** — `pystray` + `PIL.Image` for a 32x32
    glyph that shows recording state (red dot when capturing).
  - **Permissions** — Windows microphone privacy prompt needs to
    be navigated; document the one-time consent dialog.
  - **Settings** — hotkey customiser dialog, "Run on Windows
    startup" toggle (via the Run registry key under HKCU).
- **Acceptance criteria for the next session:**
  - Press hotkey anywhere → red tray icon → speak → press hotkey →
    text appears in the focused window in <2 s.
  - Hotkey rebinding works without restart.
  - No crash if hotkey conflicts with another app's hotkey
    (graceful fallback to a different combo).
  - Real-machine test: drop text into Notepad, Slack, Chrome
    address bar, and a VSCode buffer.
- **Estimated effort:** 5-7 hours of focused work (XL bucket).

### 5.1c Original 5.1 reference (pyannote / WhisperX)

- The shipped Session-13 implementation chose sherpa-onnx over
  pyannote.audio specifically to avoid the HuggingFace token
  requirement that pyannote-audio enforces on its diarization
  pipelines. WhisperX would have been the other option but it
  drags in PyTorch (~ 700 MB) for marginal accuracy gains on this
  app's use cases.

### 5.2 Vocal separation (Demucs / UVR)

- **Source:** CheshireCC (Demucs), Whisper-WebUI (UVR)
- **Effort:** L
- **Why:** Massively improves transcription quality on music videos and clips with heavy background music. Especially useful for the user's Supreme Master TV workflow where some content is musical.
- **Implementation:** `demucs` is pip-installable but adds heavy deps. Opt-in. Pre-process the audio file before passing to Whisper.

### 5.3 Live microphone transcription

- **Source:** Buzz, Const-me/Whisper
- **Effort:** L
- **Why:** Meeting notes use case. Probably out of scope but worth noting.
- **Implementation:** `sounddevice` + a rolling 5-second buffer + faster-whisper streaming on `tiny.en` or `distil-large-v3`.

### 5.4 REST API server mode

- **Source:** Whisper-WebUI, speaches
- **Effort:** L
- **Why:** Run on a GPU box, control from a laptop. OpenAI-Whisper-API-compatible endpoint for tool interop.
- **Implementation:** FastAPI app in `app/server/`, launched via `python -m whisper_project serve`. Reuses the same `core/transcriber.py`.

### 5.5 CLI mode

- **Source:** Buzz, Purfview
- **Effort:** S
- **Why:** Automation. `whisper-transcriber-suite transcribe in.mp3 --model large-v3 --vad`.
- **Implementation:** `click` or `argparse` entry point in `app/cli.py`. Wraps the same `core/` services.

### 5.6 Packaging: PyInstaller --onedir + installer

- **Source:** common practice
- **Effort:** M
- **Why:** Users shouldn't need Python installed. `--onedir` over `--onefile` because antivirus false-positives are much rarer.
- **Implementation:**
  - PyInstaller spec file
  - Inno Setup or NSIS for an installer that places files in `Program Files`, registers in Start menu, optional desktop shortcut
  - First-run downloads the model (not bundled in the installer)
  - Code signing — deferred until users complain about SmartScreen

### 5.7 Auto-update for the app itself

- **Source:** Open Video Downloader, cbro33
- **Effort:** M
- **Why:** Users get bug fixes without manual download.
- **Implementation:** version check against GitHub releases on launch. If newer, show a banner. Hand-rolled (not PyUpdater, which is overkill).

### 5.8 Backend abstraction (faster-whisper vs whisper.cpp)

- **Source:** Buzz, sandrohanea/whisper.net
- **Effort:** XL
- **Why:** Apple Silicon and AMD GPU users would benefit from whisper.cpp. CTranslate2 is best-in-class for NVIDIA + CPU.
- **Implementation:** `core/backends/` with `FasterWhisperBackend` and `WhisperCppBackend` implementing a common protocol. Likely defer indefinitely.

---

## Phase 6 — CJK polish + pluggable backends (new, Session 6 research)

Driven by `docs/COMPETITIVE_ANALYSIS_2026.md`. The target audience is producing transcripts in EN/CJK/FR/DE; the gaps versus 2026 state-of-the-art are sharply localized in those four languages, and the research surfaced concrete fixes. Persian/Arabic are out of scope.

### 6.1 Pluggable transcription backends

- **Source:** competitor synthesis §3 — no single OSS model wins all four target languages
- **Effort:** L
- **Why:** `faster-whisper-large-v3` is the only OSS choice that covers EN+CJK+FR+DE in one model, but SenseVoice beats it on CJK by a large margin, and Parakeet-TDT-0.6B-v3 beats it on EU-language batch throughput. A pluggable interface unlocks both wins without losing our baseline.
- **Implementation:**
  - `core/backends/base.py` — `TranscriptionBackend` ABC with `transcribe(media_path, lang_hint, **opts) -> Iterable[Segment]`
  - `core/backends/faster_whisper.py` — wrap the current code (no behavior change)
  - `core/backends/sensevoice.py` — load FunAudioLLM/SenseVoiceSmall, route ZH/YUE/JA/KO via this
  - `core/backends/parakeet.py` — optional NeMo-based fast path for EN/FR/DE on long batches, gated behind a config flag and a NeMo install
  - Router policy: detected language ∈ {zh, yue, ja, ko} ⇒ SenseVoice; user opt-in for Parakeet on EU langs; default ⇒ faster-whisper
  - `core/backends/__init__.py` exposes `pick_backend(config, detected_lang) -> TranscriptionBackend`
- **Tests:** mock backends, exercise router; integration test with a tiny SenseVoice variant if download permits

### 6.2 Chinese punctuation post-processor

- **Source:** competitor synthesis §1 item 1 — biggest single CJK quality lift
- **Effort:** S
- **Why:** Whisper's Mandarin output is wall-of-text. CJK readers expect `。，！？` separators; without them, subtitle line-splitting and downstream NLP both suffer.
- **Implementation:**
  - Default mitigation: pin `initial_prompt="以下是普通话的句子。"` (zh-Hans) or `"以下是普通話的句子。"` (zh-Hant) when detected language is `zh*`, set `condition_on_previous_text=False` to suppress English hallucinations
  - Optional: ship FunASR `ct-punc` (~50 MB, CPU) as a post-processor for plain-text refinement after transcription. Toggle in Advanced dialog.
  - SenseVoice (6.1) emits punctuation natively, so this is unnecessary when SenseVoice routes the job
- **Tests:** golden-file diff before/after on a ZH fixture

### 6.3 CJK-aware line splitting

- **Source:** competitor synthesis §2 — Netflix style guide
- **Effort:** S
- **Why:** our current 42-char default targets Latin; CJK readers want ≤ 16 zh-Hans chars or ≤ 20 zh-Hant per line. Each Han glyph is a full-width cell.
- **Implementation:** add a `width_aware_split(text, max_cells, max_lines)` to `core/writers/`. CJK fullwidth characters count as 2 cells; Latin as 1. Per-language defaults: `zh-Hans` 32 cells (≈16 glyphs), `zh-Hant` 40 cells, others 42 cells. CPS budget: 9-12 for CJK, 15-17 for Latin.
- **Tests:** unit test on width counting; round-trip with a ZH fixture

### 6.4 Simplified ↔ Traditional normalization

- **Source:** competitor synthesis §2
- **Effort:** XS
- **Why:** Whisper drifts mid-file. Users want a deterministic choice.
- **Implementation:** dependency `opencc-python-reimplemented` (Apache-2.0). New setting `zh_variant: zh-Hans | zh-Hant | auto`. Apply as a post-processor when detected lang is `zh` and `zh_variant != auto`.

### 6.5 Number / date normalization for CJK

- **Source:** competitor synthesis §2 gotcha 4
- **Effort:** XS
- **Why:** Whisper writes `"二零二六年"` where users often want `"2026 年"`. Configurable both ways.
- **Implementation:** dependency `cn2an` (Apache-2.0). New setting `zh_numerals: chinese | arabic | preserve`.

### 6.6 Hallucination / repetition cleanup

- **Source:** competitor synthesis §2 gotcha 1+3
- **Effort:** S
- **Why:** Whisper inserts "Thank you for watching." into silence; repeats the same line 5-10x on noisy input. Both are well-documented in our intended audio.
- **Implementation:** post-processor that drops segments matching a small phrase blocklist when the surrounding language is CJK, and collapses adjacent identical-text segments into one. Toggle in Advanced.

### 6.7 stable-ts integration (forced alignment lite)

- **Source:** competitor synthesis §1 item 2
- **Effort:** S
- **Why:** WhisperX-style alignment is desirable for Phase 4 editor (`click word → audio jumps`). Full WhisperX adds heavy deps (pyannote, wav2vec2); `stable-ts` is a near-drop-in for faster-whisper with much better timestamps and an excellent `split_callback`.
- **Implementation:** add `stable-ts` as opt-in dep; when enabled, route transcription through `stable_whisper.WhisperModel` instead of bare `WhisperModel`. Same output shape.

### 6.8 Sound-event tagging for SDH subtitles

- **Source:** ElevenLabs Scribe v2, competitor synthesis §1 item 14
- **Effort:** M
- **Why:** SDH (subtitles for the deaf and hard-of-hearing) requires `[Music]`, `[Applause]`, `[Laughter]` cues. SenseVoice emits AED tags natively; if backend is SenseVoice, we get this for free.
- **Implementation:** define a small canonical tag set; when backend supports AED, surface as inline cues per industry convention.

---

## Phase 7 — Hardening and operations (ongoing)

Not phase-locked; do as items mature.

### 7.1 Sentry crash reports → fixes

Once 1.8 ships, every release cycle should triage Sentry issues.

### 7.2 Test coverage growth

Phase 1 establishes infra. Goal: 80% on `core/`, 50% on `app/services/`, smoke tests on `app/views/`.

### 7.3 GitHub release workflow

A release tag (`vX.Y.Z`) triggers an Actions workflow that:
- Builds the PyInstaller bundle
- Verifies the SHA256 of bundled binaries
- Uploads the ZIP and an installer to the release
- Updates the latest-version JSON used by 5.7

### 7.4 Internationalization (when 2nd locale arrives)

Start with a simple `dict[str, dict[str, str]]` in `app/i18n.py`. Migrate to Babel only when string count > 100. Persian is no longer a target locale; CJK rendering already works in Tk on Windows without special handling.

### 7.5 Architecture Decision Records

Every chunky choice gets a short ADR in `docs/decisions/NNNN-title.md`. Start now while the rationale is fresh. First three to write:

- `0001-subprocess-workers.md` — why workers, not threads
- `0002-yt-dlp-as-binary.md` — why we ship the exe, not `pip install yt_dlp`
- `0003-md5-zip-model-source.md` — why our own mirror, not HF Hub

---

## What we explicitly are NOT doing

- **Migrating to Electron / web UI.** Cost is enormous, no clear user benefit, breaks the lightweight desktop story.
- **Migrating to PyQt6.** CustomTkinter / sv-ttk / ttkbootstrap give us most of the visual upgrade without the rewrite.
- **Building our own model serving infrastructure.** faster-whisper is sufficient.
- **Cloud transcription.** The app's selling point is offline / private. We're not adding "send to OpenAI" toggles.
- **Mobile.** Different problem domain. The Seal Android app already owns yt-dlp-on-mobile.

---

## Synthesis: the masterpiece thesis

What competitors do well, we adopt (Phases 1–3).

What competitors do poorly, we make our differentiation:

1. **Tight yt-dlp ↔ Whisper integration** (Phase 3.10) — no major Whisper GUI auto-transcribes a downloaded video. We do.
2. **Bilingual Persian-English subtitle workflow** (Phases 2.9, 4.2, 4.3) — no Whisper GUI is RTL-aware or has a side-by-side bilingual editor.
3. **Verified, resumable, mirror-served model downloads** (already shipped, document it) — most projects punt to `huggingface_hub`. We're robust on bad networks.
4. **Subtitle production pipeline** (Phases 2.11, 4.4) — most projects emit raw Whisper output. We emit Netflix-grade subtitles.

If we ship Phases 0, 1, 2, and 3, we are at parity with the leaders. Phases 4 and the differentiation pieces above put us ahead of them in a clearly defined niche.

---

## Appendix: competitor matrix (for reference)

### Whisper GUIs

| Project | UI | Distribution | Stars | Standout feature |
|---|---|---|---|---|
| chidiwilliams/buzz | PyQt6 | PyPI / Flatpak / DMG / MSI | 19.2k | Live mic, folder watcher, integrated editor |
| jhj0517/Whisper-WebUI | Gradio (web) | Docker | 2.8k | UVR vocal separation, NLLB translation, diarization |
| CheshireCC/faster-whisper-GUI | PySide6+Fluent | exe | 2.9k | WhisperX, Demucs, karaoke output |
| Purfview/whisper-standalone-win | CLI | standalone exe | 3.0k | 7 VAD methods, --batch_recursive |
| BANDAS-Center/aTrain | Flask+webview | MS Store / Flathub | 1.1k | GDPR-conscious, MAXQDA/ATLAS.ti export |
| Const-me/Whisper | C#/WinForms | portable ZIP | 10.4k | DirectCompute GPU (any vendor) |
| Pikurrot/whisper-gui | Gradio | install wizard | 429 | WhisperX, word+sentence timestamps |
| m-bain/whisperX | (lib only) | pip | 21.8k | Forced alignment, diarization pipeline |
| cbro33/Faster-Whisper-XXL-GUI | Tkinter | exe | 85 | Closest-shape competitor — yt-dlp integrated! |

### yt-dlp GUIs

| Project | UI | Distribution | Stars | Standout feature |
|---|---|---|---|---|
| oleksis/youtube-dl-gui (yt-dlg) | wxPython | MSIX / winget / Snap | ~2k | History, scheduling, throttling |
| jely2002/youtube-dl-gui (OVD) | Vue 3 + Tauri | exe / dmg / AppImage | 8.2k | Smart queue, cookies, notifications |
| StefanLobbenmeier/youtube-dl-gui | Electron | Win/Mac/Linux installers | 2.6k | 32 concurrent downloads, size estimates |
| axcore/tartube | GTK 3 | exe / deb | 3k+ | DB hierarchy, livestream, SponsorBlock |
| dsymbol/yt-dlp-gui | PySide6 | portable ZIP | 1.4k | TOML presets |
| Stacher | Electron | commercial | — | Editable command preview |
| JunkFood02/Seal | Kotlin Compose | APK / F-Droid | 23.6k (Android) | aria2c multithread, Material You |
| arabcoders/ytptube | Python+Vue (web) | Docker | — | Conditions/per-link options, scheduled feeds |
