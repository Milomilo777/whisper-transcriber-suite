# Release Notes — v1.0.1 (first stable)

**Date:** 2026-05-23
**Branch:** `chore/cleanup-hardening`
**Distribution:** private — to a named group of users.

---

## What's new

v1.0.1 is the first stable release. It packages the full feature
set, a multi-round hardening sweep, and a fix for a fresh-install
model re-download race caught during pre-ship verification.

### Major user-visible features

- **Model Hub Folder** — first-run dialog asks the user where to
  store Whisper model files. Default is a `hub/` sub-folder next to
  the app. The Inno Setup uninstaller offers to delete this folder
  if it lives outside the install directory.
- **Multi-model picker** — Advanced dialog lets you choose between
  Whisper Large v3 (default), Large v3 Turbo, and Distil Large v3.5.
- **Hardware autodetect wizard** — probes CUDA / NPU / DirectML /
  CPU at first launch, persists the optimal choice.
- **Hallucination detector** — flags suspect transcript segments
  (Whisper boilerplate, repetition loops). Suspect rows show red in
  the transcript viewer.
- **Auto-chapter markers** — long-silence boundary detection writes
  `<base>.chapters.json` next to every transcript.
- **`--safe-mode` recovery** — `WhisperProject.exe --safe-mode`
  backs up the user config aside and fires a fresh first-run dialog.

### Foundations for live + AI (Phase 2/3)

The modules exist (download-on-first-use design) but are not yet
wired into the UI:

- `core/recorder.py` — mic + WASAPI loopback recording
- `core/llm.py` — Qwen2.5-1.5B local LLM (summary / Q&A / translate)
- `core/separator.py` — Demucs vocal-separation pre-process
- `core/search.py` — semantic + FTS5 search across saved transcripts
- `core/voiceprint.py` — cross-file speaker fingerprint database
- `core/backends/parakeet.py` — sherpa-onnx Parakeet TDT backend

These can be enabled per-feature in the Advanced dialog; UI panels
arrive in a later release.

---

## What changed (silent behaviour)

- The default `compute_type` / `device` are now logged at every
  decision point with a `source=` field (`config`, `hardware.json`,
  `ctranslate2_probe`, `torch_probe`, `cpu_fallback`). Support
  questions like "why is the model loading on CPU when I have a
  GPU?" become trivial to diagnose.
- Every worker subprocess now emits a 5-second heartbeat. The parent
  declares a worker wedged after 30 s of silence and restarts it
  automatically; this prevents the "transcribe stuck at 47 %"
  experience.
- `history.db` now opens in WAL mode + runs an integrity check at
  every startup. A corrupt DB is renamed `.corrupt` and replaced
  with a fresh one rather than blocking app launch.
- `config.json` saves no longer silently fail. Permission errors and
  antivirus locks now surface a UI message + log a full stack trace.

---

## Pre-ship fix worth calling out

**Fresh installs no longer re-download the 3 GB Whisper model on
the launch after the first-run hub picker.**

The first-run "Choose Model Hub Folder" dialog used to be
asynchronous: it opened and immediately let the rest of startup
continue. The transcription worker spawned with an empty
`hub_folder` and downloaded the model into
`%LOCALAPPDATA%\WhisperProject\Cache\models\`. When the user
accepted the dialog's default (`<install-dir>\hub`), the choice
was saved — but the next launch resolved `model_path` to a
folder the model had never been extracted into, hit a startup
error, opened the model-download dialog, and pulled the full
3 GB archive again.

The patch makes the dialog default and the empty-hub fallback
agree on the same path, and defers the worker spawn until the
dialog has fired its on-done callback. Accepting the default is
now a no-op; picking a custom folder routes the first download
straight to the right place. Verified by a `load_config()`
simulation of the fresh-install path plus a regression test
(`tests/core/test_hub.py`).

---

## Migration from v0.7.x

Existing v0.7.x users:

- **First launch:** a hub-folder dialog appears. The default is
  `<app>/hub`. The legacy `model_path` is auto-migrated — if you
  already had a model on disk, the dialog should NOT fire
  (`hub_folder` is back-derived from your existing `model_path`).
- **Config keys added:** `hub_folder`, `whisper_model`, `ai_enabled`,
  `demucs_enabled`, `auto_chapters_enabled`, `voiceprint_enabled`,
  `hallucination_detect_enabled`. All default to safe values.
- **No breaking changes.** Old `.whisperproject.json` project
  overrides keep working; values are now schema-validated and any
  with a wrong type are dropped + logged as a warning instead of
  silently coerced.

---

## Quality bar

| Metric | Result |
|---|---|
| pyright `app/ core/` | 0 errors, 0 warnings, 0 informations |
| Unit + integration suite | 535/535 passing |
| Real-file end-to-end (SMTV clip) | 10/10 |
| Smoke + end-to-end (Whisper model) | 7/7 |
| Audit closure (R-series) | ~62 / 72 |

None of the remaining items from the 2026-05-21 freeze audit is a
user-visible regression.

---

## Deliverables

Three EXEs uploaded to the v1.0.1 release page:

| Asset | Size | Best for |
|---|---|---|
| `WhisperProject-v1.0.1-Portable.exe` | ~450 MB | one file, no install |
| `WhisperProject-v1.0.1-Setup-Compact.exe` | ~330 MB | normal user — Start-menu shortcut |
| `WhisperProject-v1.0.1-Setup-Standard.exe` | ~350 MB | inspectable — files live on disk |

Step-by-step install: [INSTALL.md](INSTALL.md). Build it yourself:
[BUILD.md](BUILD.md).

---

## Known issues

- A few Tk-heavy tests in the unit suite (transcript_viewer, hub
  setup dialog) intermittently flake when run in the full suite
  (~10 % rate). Each passes in isolation. Caused by Tcl state
  contamination across many `tk.Tk()` instances per test process.
  Documented as a deferred maintenance item; does not affect
  shipped code behaviour.
- The full `except`-block sweep is partial (14 high-value sites
  converted; ~65 intentional cleanup-path swallows left alone).
  Documented in `docs/EXECUTION_ROADMAP.md` as a non-blocking item.

---

## Acknowledgements

Built on:

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — the
  CTranslate2 Whisper inference engine.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — the universal video
  downloader.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — speaker
  diarisation + Parakeet ONNX runtime.
- [Inno Setup](https://jrsoftware.org/isinfo.php) — Windows installer.
- [Tk + sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme) —
  the GUI toolkit and dark theme.

Bundled binaries (`ffmpeg`, `ffprobe`, `yt-dlp`) and the Whisper
model are subject to their respective upstream licenses.
