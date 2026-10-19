# Roadmap

What has shipped, what is still open, and what the project deliberately does not do. Checked against the code
of v2.1.0 on 2026-10-19. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the current shape of the code and
[`CHANGELOG.md`](CHANGELOG.md) for what each version added.

The original phase-by-phase plan (May 2026, with per-item design notes and a competitor matrix) is kept in git
history: `git show 47d2fc6:docs/ROADMAP.md`. Phase and item numbers below match it. A sourced comparison with
similar apps lives in [`COMPARISON.md`](COMPARISON.md).

Effort labels: **XS** under an hour · **S** half a day · **M** one to three days · **L** a week · **XL** more.

---

## Progress snapshot

| Phase | Status | Shipped | Open |
|---|---|---|---|
| 0 — correctness baseline | **Done** | Non-blocking yt-dlp updates (ask / auto / never, once a day), bundled ffprobe, atomic `config.json` writes with a backup, no bare `except` | — |
| 1 — foundation | **Done** | sv-ttk Light/Dark/System theme; per-user paths (`%LOCALAPPDATA%\WhisperTranscriberSuite` on Windows); rotating logs; `gui.py` split into the `app/` package; hermetic test suite in CI; pyright (basic) on `app/` and `core/`; opt-in Sentry crash reports | 1.7 strict typing on `core/` |
| 2 — Whisper as a serious transcription tool | **Mostly done** | VAD, word timestamps, language detection, 14 output formats, batched GPU inference, CTranslate2 device detection, model picker with downloads, prompt and hotwords (Advanced dialog), translate to English, drag and drop, folder watcher | 2.10 named presets, 2.11 automatic subtitle line splitting, a custom Hugging Face model ID |
| 2-oTranscribe — format compatibility | **Done** | `.otr` import and export, ELAN, InqScribe, Express Scribe; in-app editor (see Phase 4) | — |
| 3 — yt-dlp as a serious downloader | **Partly done** | JSON progress, SQLite history with crash resume, SponsorBlock categories, cookies from the browser, auto-transcribe after download, own yt-dlp updater | 3.4 extra yt-dlp arguments, 3.7 parallel downloads, 3.8 rate limit and scheduler, 3.9 simple mode |
| 4 — editor and viewer | **Mostly done** | Transcript viewer with click-to-seek, edit-back with timestamps, speaker rename, filler-word removal per language, word-confidence colours | 4.3 gap/silence panel, 4.6 subtitle linter in the editor |
| 5 — power features | **Done** except 5.1b | Speaker diarization (sherpa-onnx), vocal separation, Live tab (microphone and system audio), local HTTP API (stdlib `core/server/`, OpenAI-compatible routes, MCP), CLI (`gui.py transcribe` / `serve`), Windows installer and Portable ZIP, macOS DMG, update check (notify only, by design), pluggable backends, text to speech (Kokoro, OmniVoice voice cloning) | 5.1b system-wide dictation hotkey |
| 6 — CJK polish | **Partly done** | Backends incl. NVIDIA Parakeet and whisper.cpp; hallucination flags and a repetition-loop guard; stable-ts alignment (opt-in) | 6.2 Chinese punctuation, 6.3 width-aware CJK line splitting in the writers, 6.4 Simplified/Traditional, 6.5 CJK numerals, 6.8 sound-event tags, SenseVoice backend |
| 7 — hardening and operations | **Ongoing** | 42 interface languages (2.1.0); design decisions in [`DECISIONS.md`](DECISIONS.md) | 7.6 language-specialised models |

---

## Open items

### Transcription (Phase 2)

- **2.10 Named presets** (M). Only the built-in "noisy audio" preset exists. Save a named bundle of settings
  (model, VAD, prompt and hotwords, output formats, output folder) and apply it with one click.
- **2.11 Automatic subtitle line splitting** (M). Raw segments are often too long for screen subtitles. A
  post-processor that uses word timestamps to emit blocks within common limits (about 42 characters a line,
  2 lines, 17 characters a second, at least 0.83 s on screen). `core/subtitle_qc.py` already measures these
  limits; nothing reflows the text yet.
- **Custom model ID** (S). Let a user type any faster-whisper-compatible Hugging Face repository instead of picking
  from the catalog.
- **1.7 Strict typing on `core/`** (M). pyright runs in basic mode on `app/` and `core/`; strict mode on `core/`
  would catch more.

### Downloads (Phase 3)

- **3.4 Extra yt-dlp arguments** (S). A box for flags the UI does not expose (for example `--limit-rate 1M`),
  with a preview of the full command.
- **3.7 Parallel downloads** (S). Downloads run one at a time; a `parallel_downloads` setting (default 1) would
  allow 2-3 for users with the bandwidth. (`parallel_workers` already covers transcription.)
- **3.8 Rate limit and scheduler** (S + M). Expose `--limit-rate`, and "start the queue at HH:MM".
- **3.9 Simple mode** (S). URL plus one quality choice (Best / 720p / 480p / Audio only) for new users.
- **3.6 Basic-auth fields** (XS). Cookies from the browser ship; user name and password fields for the rare site
  that needs them do not.

### Editor (Phase 4)

- **4.3 Gap and silence panel** (M). A sortable list of silences longer than N seconds; click to jump, and a
  "remove dead air" command that shifts later timestamps. Useful for podcasts and lectures.
- **4.6 Subtitle linter in the editor** (S). `core/subtitle_qc.py` checks characters per second, line length,
  gaps and minimum duration (with CJK limits) but is used only by tests; show its findings as badges in the
  editor.

### Power features (Phase 5)

- **5.1b System-wide dictation hotkey** (XL). Press a global hotkey, speak, and the text is typed into the
  focused app. A separate product mode; needs its own design.

### CJK quality (Phase 6)

- **6.2 Chinese punctuation** (S). Whisper's Mandarin output often lacks `。，！？`. Options: a Chinese initial
  prompt for `zh` with `condition_on_previous_text=False`, or an optional punctuation model as a post-processor.
- **6.3 Width-aware line splitting** (S). Count full-width characters as two cells so zh-Hans lines stay near 16
  characters and zh-Hant near 20. Belongs with 2.11.
- **6.4 Simplified / Traditional normalisation** (XS). Whisper can drift between the two inside one file; a
  `zh_variant` setting backed by OpenCC would make the output consistent.
- **6.5 CJK numerals** (XS). Choose between `二零二六年` and `2026 年`.
- **6.6 Cleanup, remaining part** (S). Hallucinated phrases are flagged and repetition loops are stopped; a
  CJK phrase list and collapsing adjacent identical segments are still open.
- **6.8 Sound-event tags** (M). `[Music]`, `[Applause]`, `[Laughter]` cues for subtitles for the deaf and
  hard of hearing; comes almost free with a backend that detects audio events (for example SenseVoice).
- **SenseVoice backend** (L). Reported to beat Whisper on Chinese, Cantonese, Japanese and Korean; the backend
  interface in `core/backends/` is ready for it.

### Language-specialised models (7.6, idea)

- **Persian.** `mehdi-hf/nemotron-asr-streaming-farsi` (NVIDIA Nemotron ASR fine-tuned on about 1,200 hours of
  Persian) reports 8.8% WER on FLEURS and streaming at roughly 10x real time on an M1 laptop. These are the
  author's own figures; before shipping, check the licence and test it on local Persian samples.
  [Model](https://huggingface.co/mehdi-hf/nemotron-asr-streaming-farsi),
  [code](https://github.com/mallahyari/nemotron-asr-streaming-farsi).
- **Per-language recommender.** Find the best open model per language (accuracy on FLEURS or Common Voice,
  licence, size, CPU and Apple Silicon speed), keep only models clearly better than Whisper for that language,
  offer them as engines, and suggest one when the user picks that language. The
  [multilingual benchmark](evaluations/benchmark-v1/README.md) is the starting point.

### Operations (Phase 7)

- **Release automation.** Windows installers build on pushes to `master` that touch build files; releases are
  cut by hand ([`RELEASE_PROCESS.md`](RELEASE_PROCESS.md)). A tag-triggered release workflow is not planned
  while every release gets a manual check.
- **Coverage.** CI measures coverage; there is no enforced target.

---

## What the project deliberately does not do

- **Electron or a web UI for the desktop app.** Large cost, no clear benefit to users, and it would end the
  lightweight desktop app. (The local-network mode already serves a browser page to other devices.)
- **A Qt rewrite.** sv-ttk gives a modern look without rewriting the UI.
- **Cloud by default.** Every default path keeps audio on the user's computer. The two cloud engines
  ([Gemini](CLOUD_STT.md), [Google Cloud](CLOUD_STT_GOOGLE.md)) are opt-in and off until enabled.
- **A native mobile app, for now.** Phones and tablets can use the desktop machine through the local-network mode.
