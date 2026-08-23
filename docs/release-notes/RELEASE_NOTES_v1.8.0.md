# Whisper Project v1.8.0

A features + reliability release on top of v1.7.0: a remote LLM
provider, chapters/AI tools/search wired into the transcript viewer, a
bilingual subtitle writer, and several real-world download/translation
bug fixes.

## Highlights

- **Remote LLM provider.** Advanced Settings' AI Layer section can now
  point the summarize/action-items/ask/translate tools at your own
  OpenAI-compatible endpoint (OpenAI itself, or a self-hosted
  Ollama/LM Studio/OpenRouter) instead of only the bundled local model.
- **Chapters + AI Tools tabs in the transcript viewer.** The right panel
  is now a Media/Chapters/AI Tools notebook: Chapters lists the sidecar
  chapter file and seeks the player on click; AI Tools exposes
  summarize/action items/ask, plus a per-segment translate pass that
  saves a bilingual `.srt` (original + translated line per cue).
- **Transcript search** — `Help > Search transcripts...` opens a
  full-text search dialog over your transcripts.
- **"Apply noisy-audio preset" button** in Advanced Settings — one click
  sets VAD/denoise/hallucination-detection to values reasonable for
  non-studio audio, instead of five separate sliders.

## Fixed

- **A failed format lookup (Facebook, Instagram, or any other site) now
  tells you why**, instead of a dead-end "wait for formats to load"
  message once the lookup has already given up.
- **A download could fail even for a fully public video** when "Cookies
  from browser" was on and the browser was still open — yt-dlp's own
  cookie-jar read failed and broke the download outright. It now
  retries once without cookies before giving up.
- **CLI log lines could crash mid-run on Windows** when a file name held
  a character the console's legacy codepage cannot encode (e.g. an
  emoji pulled from a social-media title).
- **Bilingual-subtitle translations could come back wrapped in stray
  quote marks** on a local-LLM pass — now stripped before the `.srt` is
  written.
- **Transcript search dialog:** an Escape-close during a background
  search/reindex, a slower/older search overwriting a newer one's
  results, and an invisible results list (Treeview parenting bug) —
  all fixed.
- **The AI panel could keep using a stale LLM provider** after Advanced
  Settings' provider/URL/key/model was changed while the transcript
  viewer stayed open.

## Builds

- **Setup-Standard** (Windows) — the recommended installer (embeddable
  Python; choose where models are stored on first run).
- **Portable** (Windows) — a ZIP of the same tree; extract and run
  `Run Whisper Project.bat`, no install.
- **macOS** — `WhisperProject-v1.5.0-macOS-x64.dmg` (Intel/x64-only) is
  attached to this release too, carried forward unchanged since v1.5.0;
  no new macOS build was done this round, so it does not include any
  v1.6.0/v1.7.0/v1.8.0 fix.

## Notes

- First launch asks where to keep the speech models (large files); the
  default is a writable per-user folder.
- Windows SmartScreen may warn on an unsigned installer — choose *More
  info → Run anyway*.
- Running from a git checkout instead of an installer? Use
  `run_from_source.bat` (new this release) — it pulls the latest
  source and launches, so it never drifts behind like a packaged build
  can.
