# Changelog

All notable changes to this project. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [1.8.0] — 2026-08-23

### Added

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

### Fixed

- **A failed format lookup (Facebook, Instagram, or any other site) now
  tells you why.** Previously, once yt-dlp's initial probe failed, the
  Download button just repeated "Wait for formats to load" forever — the
  real error sat in a small, easy-to-miss status label and never reached
  the download log. Clicking Download now shows that real reason (and
  logs it), instead of a dead-end message that implies the app is still
  loading when it has already given up.
- **A download could fail even for a fully public video.** With "Cookies
  from browser" on and the browser still open, yt-dlp's own cookie-jar
  read failed and broke the download outright — even when the video
  never needed cookies. It now retries once without cookies before
  giving up.
- **CLI log lines could crash mid-run on Windows** when a file name held
  a character the console's legacy codepage cannot encode (e.g. an
  emoji pulled from a social-media title) — the console now substitutes
  the character instead of raising.
- **Bilingual-subtitle translations could come back wrapped in stray
  quote marks** (a local-LLM quirk on short segments) — now stripped
  before the line is written to the `.srt`.
- **Transcript search dialog:** pressing Escape could leave a background
  search/reindex touching an already-closed window; a slower, older
  search could overwrite a newer one's results; the results list itself
  was invisible due to a Treeview parenting bug. All three fixed.
- **The AI panel could keep using a stale LLM provider** after Advanced
  Settings' provider/URL/key/model was changed while the transcript
  viewer stayed open.

## [1.7.0] — 2026-08-15

### Fixed

- **`save_config()` refuses a drastic silent shrink and keeps a backup** —
  a real config.json was found silently reduced from ~90 keys to 3 keys
  during ordinary use this cycle; the root cause was not pinned down
  despite a real, instrumented investigation. Saving now refuses to
  write a config with under 40% of the key count currently on disk
  (logging an error instead), and keeps a rotating `config.json.bak` of
  the last good state on every normal write.

- **Editing "Hotwords" in Advanced settings could be silently undone** —
  saving Advanced settings correctly wrote the new hotwords to disk, but
  the Transcribe tab kept its own frozen copy of whatever hotwords value
  existed when the app launched (left over from a UI redesign; that copy
  has no visible field of its own). Merely changing the language dropdown
  or the "Identify speakers" / "Word timestamps" checkboxes afterward
  re-saved preferences using that stale copy, overwriting the fresh
  Advanced-dialog edit with no warning. Fixed by no longer writing that
  stale copy back into config.

### Added

- **Advanced settings: "Enable VAD (skip silent segments)" checkbox** —
  Voice Activity Detection was always on with no way to turn it off from
  the desktop app, even though the engine and the optional LAN/web server
  both already supported disabling it. The three VAD tuning sliders (min
  silence, threshold, speech pad) now grey out while it's unchecked.

### Security

- **"Convert transcript" ELAN (`.eaf`) import: reject a DOCTYPE** — a
  crafted `.eaf` with a `DOCTYPE`/entity block could previously hang or
  balloon memory ("billion laughs") when imported; such files are now
  refused outright with a clear error. Found during an attacker's-eye
  pass over the whole codebase; every other input-parsing path checked
  in that pass (SSRF guard on the online-config URL, zip-slip guard on
  the model download, upload path/filename sanitising in the LAN server,
  constant-time token compare) was already hardened.

### Fixed

- **Engine-status / hardware-probe background threads hardened against a
  native-fault risk class** — a real Windows native fault was traced to
  Python's garbage collector running mid-import of a heavy optional
  package on a background probe thread. Every such probe now disables GC
  for its risky operation. See ADR 0008 in `docs/DECISIONS.md` for the
  full investigation.

- **That same GC-import guard used 10 separate locks instead of one
  shared lock**, so two probes on different threads did not actually
  serialize against each other and could still race. Found in a
  second-pass review; factored into one shared
  `core._gc_import_guard.gc_disabled_import()`.

- **Semantic search silently scored dimension-mismatched embeddings** —
  a stored embedding from a different model/dimension than the current
  query embedder was compared anyway via `zip()`, which silently
  truncates instead of erroring. `core.search._semantic_query` now
  skips a dimension-mismatched row.

- **`requirements.txt` no longer bundles `google-cloud-speech` /
  `google-cloud-storage`** — leftover from when a bundled service-account
  key made Google Cloud STT the default engine (see "Retired: the bundled
  Google Cloud key" above). Now genuinely on-demand via
  `core/optional_deps.py`, like every other optional backend.

### Added

- **Transcript viewer: "Edit timestamp..." (right-click a segment)** —
  hand-edit a segment's start/end time (HH:MM:SS.mmm). Only that segment
  changes; a resulting overlap with the previous segment or a sub-1s
  duration gets a light-orange row highlight as a warning, never a
  blocked save. Inspired by a comparable faster-whisper GUI's editable
  timestamp table.

- **Download tab: "Clear completed" button** — the Queue tab has always
  had one; the Download tab was missing the parity button (owner-noticed
  gap while reviewing the frontend, 2026-08-15).

- **LAN web page: source preview, Reset, Copy-transcript, Recent jobs** —
  picking a file now shows an instant local audio/video preview; a Reset
  button clears the form back to defaults; the transcript view has a
  one-click Copy button; and the Submit view shows the last 3 jobs so you
  don't have to switch tabs to see something is still running. Ergonomics
  borrowed from `voice-pro`'s Gradio frontend (see
  `docs/GAPS_VS_VOICE_PRO_2026.md` item 7) without adding Gradio itself.
- **Advanced dialog: "Restore transcription defaults" button** — resets
  the VAD, hallucination-detection, alignment, batch size, denoise,
  Demucs, auto-chapters and voiceprint options back to their defaults in
  one click. Deliberately scoped to per-job tuning knobs only — output
  formats, the hotwords/prompt text, model/backend choice, watched
  folder, and cloud credentials are left untouched. Nothing is written
  until you click Save, so Cancel undoes this too.

- **Advanced dialog: consistent section headers + a split-up "Whisper
  extras"** — the 3 cloud/NVIDIA sections now use the same short-title +
  hover-help header as the other 7 (previously plain, long run-on titles
  with no hover-help). The old 10-row "Whisper extras" grab-bag is now two
  focused sections, "Model & engine" and "Prompt, hotwords & output
  naming". Part of an ongoing readability pass (owner request,
  2026-08-14) — more rounds land alongside this one.
- **Advanced dialog: hover-help on every output format + a few more bare
  spots, and a grouped nav sidebar** — each of the 15 output-format
  checkboxes (SRT/VTT/ELAN/InqScribe/Express Scribe/etc.) now has a
  one-line "what is this" tooltip instead of a bare acronym; the Google
  Cloud "Cloud Storage bucket" field, "Detect speakers" checkbox, and
  "Minimise to system tray" checkbox gained tooltips too. The "Jump to"
  sidebar now groups its 11 links under small captions ("Alternate
  engines", "App preferences") so the 3 opt-in cloud/NVIDIA sections read
  as clearly optional rather than blending into one long list.
- **Advanced dialog: 3 more hover-help gaps closed** — the AI Layer's
  "Enable local LLM" and "Generate auto-chapter markers" checkboxes and
  the Downloads section's "Transcribe after download" checkbox now
  explain themselves on hover, matching every other control in the
  dialog. The "Enable local LLM" caption also no longer overclaims
  summary/Q&A support it has no UI for yet.

### Fixed

- **Hover-help icons were technically working but easy to miss** — the
  owner reported seeing no tooltips despite earlier sessions saying this
  was done. Root-caused with a real OS-level mouse-move + screenshot test
  (not Tk's synthetic events, which earlier sessions relied on): the
  popup mechanism itself was fine, but the "ⓘ" glyph was the same size
  and weight as body text. Now bigger and bold everywhere it's used
  (Advanced dialog, all tabs, Live tab, transcript viewer).
- **Installer: Video Tiling defaulted to installed, worded as a
  confusing double-negative** ("Do NOT include the Video Tiling
  feature", unticked by default = installed). Now a plain, positively
  worded opt-in checkbox, unticked by default = not installed (owner
  request, 2026-08-15).
- **Error dialogs could open on the wrong monitor** — the same
  negative-coordinate clamping bug already fixed for tooltips
  (`max(x, 0)` yanks a dialog onto the primary monitor even when its
  parent window lives on a secondary monitor placed to its left).
  `error_dialog.py` now only clamps when the parent itself is on the
  primary display.
- **Live tab transcript couldn't be selected/copied by dragging the
  mouse** — `state="disabled"` blocks all mouse interaction on a Tk
  Text widget, not just typing. It now stays selectable/copyable; a
  `<Key>` filter blocks typing instead (Ctrl+C/Ctrl+A and navigation
  keys still pass through).
- **Advanced dialog silently cleared "Detect speakers" for Google Cloud
  STT** — saving with that backend selected always reset the diarization
  checkbox back off, even though the backend has fully supported
  diarization since it was added. It now saves correctly; the tooltip
  explains the real caveat instead (speaker numbering restarts each
  ~1-minute chunk in Standard mode).
- **Live tab's default "Microphone" source did not work out of the box** —
  `sounddevice` (and, on Windows, `PyAudioWPatch` for the "System audio"
  source) were never in `requirements.txt`, so no shipped install actually
  had them; every user hit "sounddevice not installed" the first time they
  opened the Live tab. Both now ship by default, like the app's other small
  UI dependencies (`tkinterdnd2`, `python-vlc`), instead of requiring a
  manual `pip install` a non-technical user has no way to run.
- **Download tab: typing a Start/End time directly left the position
  slider stale, and the next drag on either slider silently discarded
  the typed value.** `_on_download_scale` only ever wrote slider ->
  field, never the reverse, so a manually-typed time was invisible to
  the sliders until something moved one and snapped it back to 0:00:00.
  Typing now moves the matching slider too. Found in a same-day
  self-review (real running app, not just source reading), verified
  with a real before/after screenshot.
- **Nine fixes from an adversarial frontend review** (`app/` only, isolated
  from the rest of the repo) — download queue selection was lost on every
  event tick (now preserved, matching the transcription queue); the yt-dlp
  auto-update check poisoned its 24h retry backoff on any timeout/failure;
  download error detection missed yt-dlp's lowercase `[error]` lines;
  one bad download event could wedge the whole download progress pump;
  relocating the model hub folder could silently redirect a different
  model's path to `large-v3`'s cache folder; switching engines mid-job now
  warns before force-stopping active work instead of silently killing it;
  a live-worker write path used `assert` for a check that vanishes under
  `-O`; the transcript viewer's right-click menu could leave a stuck
  pointer grab; and the hub-setup dialog's "Cancel" button (which doesn't
  cancel) is now labeled "Skip for now".
- **Eight more fixes from a second adversarial review** (same isolated
  `app/`, this time `claude-opus-4-6-thinking`) — a download-service
  refactor from the round above had left a duplicate self-re-arming timer
  that compounded on every progress event; a secondary-monitor tooltip
  could render on the wrong screen edge (negative-x `wm_geometry`); one
  locked/failing file in a watched folder could stall every other file
  queued behind it on every drain tick; the Live tab could raise
  `UnboundLocalError` inside its own crash handler; the model-download
  dialog could close with no error shown if the underlying exception had
  no message; the console's Copy (not Copy All) silently did nothing while
  the log widget sat disabled; a hand-edited config with quoted monitor
  indices was silently dropped instead of coerced; and Esc now confirms
  before cancelling a running transcription or download instead of killing
  it on one accidental keystroke.

## [1.6.0] — 2026-08-12

> Live tab + adaptive denoise release. Real-time microphone/system-audio
> transcription, an opt-in noise filter that measures before it acts, ASS/SSA
> subtitle output with real karaoke timing, a Windows source-install updater,
> and a fix for an `nvidia_asr` dependency clash that broke every build since
> whenever `tokenizers` last shipped a release newer than `transformers`
> accepts. pyright `app/ core/` 0/0/0; hermetic suite green.

### Security

- **No cloud credential is bundled any more, and the old one is revoked.**
  Builds since v1.3.9 shipped a maintainer-owned Google Cloud service-account
  key inside the package, which also made Google Cloud STT the default engine
  — every install transcribed through one shared account. The key was revoked
  by the maintainer; the build steps that copied it are removed. See
  [SECURITY.md](../SECURITY.md).

### Added

- **`platform\windows\update.bat`** — a one-command updater for a source
  (git clone) install on Windows, matching what Linux already had. It
  refuses to run against an installed build, and verifies the app still
  imports afterwards. The installed app's own update check stays
  notify-only on purpose.
- **ASS / SSA subtitle support** — a new `ass` output format, and `.ass`
  / `.ssa` files can now be converted *from* as well. ASS is what video
  editors and karaoke tools expect, and it is the first format that
  carries our per-word timings as real karaoke highlighting; speaker
  labels go in its dedicated actor column instead of being glued onto
  the subtitle text.
- **The README is now available in 7 more languages** — Chinese, Japanese,
  Korean, German, Spanish, French and Portuguese — reachable from a flag
  switcher at the top of each one. They are generated by
  `tools/make_i18n_readmes.py` so the layout and links cannot drift apart.
- **New Live tab: transcribe a microphone or the system audio as it
  happens.** Text appears as you speak instead of after a file finishes.
  Chunks are cut at natural pauses so words are not split in half,
  silence is never sent to the model, and the tab says so when the
  machine cannot keep up rather than skipping audio silently. System-audio
  capture is Windows-only. See [LIVE.md](LIVE.md).
- **Adaptive audio denoise before transcription** (**Advanced > AI Layer**,
  off by default). Cuts hallucinated lines and misheard words on noisy
  recordings. It measures each file first and leaves already-clean audio
  untouched, then checks its own output and falls back to the original if
  the filter removed speech instead of noise. Bundled ffmpeg only — no
  extra download or dependency. See [DENOISE.md](DENOISE.md).

### Docs

- **26-way STT model comparison** across all 8 Google Cloud STT v2 models
  and all 18 local faster-whisper models on a hard real-world clip (weak
  audio, overlapping speakers). Found a real hallucination bug in the
  Whisper Large-v3-Turbo family (fabricates unrelated text on ambiguous
  audio) — confirms the app's `large-v3` default over Turbo. See
  [STT_MODEL_COMPARISON_2026-08.md](evaluations/STT_MODEL_COMPARISON_2026-08.md).

### Changed

- **The default engine is always offline faster-whisper.** It no longer flips
  to Google Cloud STT because a key file exists next to the app. Cloud STT is
  now reached only by an explicit pick in **Advanced > Backend** with your own
  service-account JSON.
- **Resuming a cancelled job now re-checks the pre-processing settings.**
  Changing vocal separation or denoise between cancel and resume used to
  splice differently-conditioned halves into one transcript; the partial is
  now invalidated and re-run instead.
- **A failed or cancelled transcription no longer posts opt-in usage
  stats.** It used to send a fake "0 words, 0:00" row indistinguishable
  from a genuine empty transcription — e.g. every job against a backend
  with no valid key. The local history record is unaffected; only the
  external stats POST is now skipped for a non-success.

### Fixed

- **The `nvidia_asr` (Parakeet) backend could fail to import on a freshly
  built installer with a `tokenizers>=X,<=Y is required` error.** The
  bundled `faster-whisper` pinned `tokenizers` only loosely, so a build done
  on the wrong day could bundle a `tokenizers` release newer than
  `transformers` accepts, and the on-demand `nvidia_asr` install could never
  override it. `tokenizers` and `transformers` are now pinned to a verified
  matching pair, `docs/BUILD.md` has a re-check step before every release
  build, and the backend's error message and status probe both report the
  real cause instead of a generic import failure.

## [1.5.0] — 2026-07-03

> SMTV release. The SMTV docx header now shows the detected language, SMTV
> and oTranscribe join the Convert-transcript targets, and the format
> picker shows each target's real file extension in a curated
> (common-first) order. The project (and its GitHub repo) is renamed to
> `whisper_app`.
> pyright `app/ core/` 0/0/0; hermetic suite green.

### Added

- **SMTV docx header now shows the detected language.** Row 2 / column 3
  used to always read the literal "Foreign Language"; it is now replaced
  with the language faster-whisper detected (e.g. "Korean"), matching the
  title row and the "[... starts]" cue that already did this. With no
  detected language the header keeps its original generic text.
- **SMTV added to File → Convert transcript.** The format picker now
  offers `smtv_docx` alongside the existing text targets. Since a generic
  transcript file carries no language metadata, the emitted docx is filled
  the same way the writer already treats "no language detected" (neutral
  cue labels); the work title is taken from the source file's name.
- **oTranscribe (.otr) added to File → Convert transcript.** `.otr` was
  already importable there but not offered as an output — the app could
  only export it from a live transcription task or a downloaded subtitle,
  never from an arbitrary transcript file already on disk. A new
  `core.writers.otr` (backed by a new public
  `core.integrations.otranscribe.segments_to_otr()`) closes that gap.
- **Convert-format picker is more user-friendly.** A human-simulation pass
  on the dialog found the combobox showed bare internal registry names
  (`elan`, `smtv_docx`, `otr`, …) in plain alphabetical order, so there was
  no way to tell what file extension a pick would actually produce, and the
  four formats almost everyone wants (`srt`/`vtt`/`txt`/`json`) were buried
  among niche ones. It now shows `name (.ext)` for every target (via a new
  `core.convert.output_extension_for()`) and lists the common four first.

### Fixed

- **NVIDIA Parakeet could fail to load with a confusing `tokenizers>=X,<=Y
  required` error** — the `tokenizers` copy bundled at build time (pulled in
  by faster-whisper) could drift newer than the on-demand `transformers`
  install accepts, and retrying the on-demand install could never fix it
  (the bundled copy always wins on `sys.path`). `transformers` and
  `tokenizers` are now pinned to a verified-compatible pair, and both the
  error message and the Advanced-dialog status line now name the real
  cause up front instead of only surfacing it after a failed transcription.
- **A failed alternative engine (whisper.cpp / cloud / NVIDIA) startup
  misdiagnosed as a missing Whisper model** (2026-07-18) — the app
  force-opened the mandatory ~3 GB Whisper download modal and buried the
  real error in the console. It now shows the engine's own error dialog
  instead.
- **Liveness watchdog killed a healthy worker during a first-run engine
  download** (2026-07-18) — the worker's heartbeat thread only started
  after the model load, so a multi-GB silent download (NVIDIA HF weights,
  whisper.cpp ggml) blew the 120 s timeout and restarted the worker in a
  loop. The heartbeat now starts before the load.
- **Engine-status probe crashed its thread on Python 3.14**
  (2026-07-18) — it called `self.after()` off-thread; now routed through
  `post_to_main()` like every other background-thread callback.
- **NVIDIA backend: unrecognised-architecture load errors now say the
  real cause** (2026-07-18) — e.g. `nvidia/nemotron-3.5-asr-streaming-0.6b`
  needs `transformers >= 5.14`; older versions failed with a generic
  message. Verified end-to-end: with transformers 5.14.1 that model loads
  and transcribes correctly through the GUI.
- **macOS dmg build scripts now arch-suffix the output filename**
  (2026-07-18) — `builddmg.command` / `compileall-whisper-mac.sh` derive
  x64/arm64 from `uname -m`, so a single-arch build can no longer ship
  under an arch-less (or "universal") name.
- **SMTV docx filename was not actually fixed** — a colleague reported the
  "Convert transcript" / transcription SMTV output "sometimes" landing under
  an unexpected `(1)`/`(2)`-suffixed name. Root cause: `_write_outputs`
  computed one shared re-run-safety index across ALL requested formats,
  including `smtv_docx` — so a pre-existing `.srt`/`.json` from an earlier
  run pushed the SMTV file to a numbered suffix on its very first write,
  even though no SMTV file had been written for that source before.
  `smtv_docx` is now excluded from the shared index and always resolves to
  its documented fixed, recognisable filename (overwriting in place on
  re-run, which is the intended "one canonical team file" behaviour).
- **`stats_url` hyphen/underscore mismatch** — the published
  `configuration.json` (the online-config master copy) pointed at
  `transcription-stats.php` (404) while `core/config.py`'s
  `DEFAULT_CONFIG` pointed at the real `transcription_stats.php` (200).
  Anyone whose effective config resolved the online copy would have had
  opt-in telemetry silently go nowhere. Fixed to agree; added a
  regression test so the two can't drift apart unnoticed again.
- **macOS build didn't work** — the `arm64`/`x86_64` `.dmg`s built by
  Claude and uploaded 2026-07-04 were broken (owner-reported, no repro
  details available). A colleague built a working replacement and it
  was uploaded 2026-07-15, replacing both prior macOS assets. On
  2026-07-18 the colleague clarified it is Intel/x64-only (not
  universal), so the asset was renamed
  `WhisperProject-v1.5.0-macOS-x64.dmg`. See
  `docs/SESSION_HANDOFF_NEXT.md` for the provenance caveat.

### Changed

- **Project renamed** `whisper_project_direct_download_v2` →
  `whisper_app` (GitHub repo + local checkout folder name). The
  update-checker, `pyproject.toml` project URLs, the Homebrew formula,
  and the clone instructions in the READMEs / install docs now point at
  the new repo name.
- **`.otr` (oTranscribe) added to File → Convert transcript** — it was
  already importable there but never offered as an output; a new
  `core.writers.otr` closes the gap (also shows up as a transcription
  output checkbox in Advanced settings, same registry).
- **Convert-format picker** now shows `name (.ext)` for every target and
  lists the four common formats (srt/vtt/txt/json) first, instead of
  bare alphabetically-sorted internal registry keys.
- **macOS builds added to this release** — `WhisperProject-v1.5.0-macOS-
  arm64.dmg` / `-x86_64.dmg`, built via `macos-app.yml` on real Apple
  Silicon + Intel runners (the underlying `compileall-whisper-mac.sh`
  duplicate-invocation bug is fixed). Same version, no separate macOS
  release notes — Windows and macOS ship the same v1.5.0 feature set.

## [1.4.0] — 2026-06-22

> Engine cleanup + safety release. Removes the dead-end sherpa-onnx Parakeet
> engine in favour of the working transformers-based one, adds a "Prepare
> model now" button for it, stops a handful of app-level config keys from
> ever being persisted to disk, makes the Windows installers silently clean
> up the previous version before upgrading, and fixes the SMTV docx output's
> stale modified timestamp. pyright `app/ core/` 0/0/0; hermetic suite green.

### Added

- **"Prepare Parakeet model now..." button** in Advanced settings (NVIDIA
  Parakeet / FastConformer section) — installs `transformers`/`torch`/
  `librosa` and downloads the model ahead of time, mirroring the existing
  whisper.cpp download button, instead of the user discovering the wait mid-
  transcription. New `nvidia_asr` extras group in `pyproject.toml`
  (`transformers`/`torch`/`librosa`) for source checkouts that want to
  pre-install the backend's deps the same way `backend_cpp`/`alignment` do.
- Both Windows installers (`installer.iss`, `installer_embed.iss`) now
  silently uninstall a previously-installed version (looked up via the
  registry by the shared `AppId`) before laying down new files, so an
  in-place upgrade can no longer leave orphaned files behind from a version
  that removed/renamed something. The hub-folder deletion prompt is skipped
  during that automatic step (`UninstallSilent` guard) so a multi-GB model
  hub outside the install dir is never wiped without an explicit, interactive
  Yes. `installer_embed.iss` also moved its `config.json` cleanup (added by a
  colleague's `167ccf8`, originally an unconditional `[UninstallDelete]`
  entry) into the same `UninstallSilent`-guarded code path — otherwise every
  silent upgrade triggered by the new pre-install step above would have
  wiped the user's `hub_folder`, API keys, and preferences on every release.

### Changed

- **Removed the incomplete sherpa-onnx `parakeet` engine** from the engine
  picker. It duplicated the now fully-working `nvidia_asr` (transformers)
  Parakeet backend but never got a model downloader, so selecting it just
  produced a permanent "model files missing" warning with no way to fix it
  from the UI.
- `core.config.save_config` now strips `telemetry_opt_in`, `config_url`,
  `stats_url`, `ffplay_downloads`, and `latest_version` before writing
  `config.json` — these are re-derived from `DEFAULT_CONFIG` / the online
  config fetch on every load, so persisting them only risked pinning a stale
  value across an upgrade. Also cleans them out of any `config.json` that
  already has them from before this rule existed.

### Fixed

- The SMTV transcription `.docx` output's "modified" document property no
  longer carries straight through from the bundled template — every
  generated docx now reports the actual transcription time instead of
  whenever the template was last authored.

- **Local NVIDIA Parakeet / FastConformer engine** (`nvidia_asr`) — a new
  **fully offline** transcription engine that runs a Hugging Face transformers
  `automatic-speech-recognition` model entirely on this machine (no audio leaves
  the device). The default is NVIDIA's transformers-native multilingual
  FastConformer model `nvidia/parakeet-tdt-0.6b-v3`; it is configurable via
  `nvidia_asr_model_id` to any transformers ASR model id or local folder. Pick
  "NVIDIA Parakeet TDT v3 — local" in the Transcribe-tab engine picker or
  Advanced > Backend. The heavy libraries (`transformers` + `torch` + `librosa`)
  and the model weights are not bundled — they install / download on first use (a
  few GB, one time), like the openai-whisper backend, so the base install stays
  slim. The file is transcribed window by window (`nvidia_asr_chunk_seconds`) for
  progress + cancel; word timestamps are used when the model provides them, else
  one segment per window. New config keys `nvidia_asr_model_id` / `_device` /
  `_dtype` / `_chunk_seconds` (see [`CONFIG.md`](CONFIG.md)). New module
  `core/backends/nvidia_asr.py`; registered in the engine factory, the shared
  `availability` registry, the Advanced dialog, and `optional_deps`. Hermetic
  tests in `tests/core/test_nvidia_asr.py`; verified end-to-end on real speech
  with `parakeet-tdt-0.6b-v3`. pyright `app/ core/` 0/0/0; hermetic suite green.
  (NVIDIA's exact `nemotron-3.5-asr-streaming-0.6b` repo ships only a NeMo
  `.nemo` checkpoint that transformers cannot load — its parakeet sibling is the
  default; a different model needs the NeMo toolkit.)

## [1.3.9] — 2026-06-08

> Frontend-stability + cloud-default release on top of v1.3.8. Adds an engine
> picker to the Transcribe tab so the transcription engine can be chosen without
> opening Advanced settings, makes Google Cloud STT the default engine in trusted
> builds that ship a key (fully offline faster-whisper otherwise), and folds in a
> small batch of frontend stability fixes. pyright `app/ core/` 0/0/0; hermetic
> suite green.

### Added

- **Transcribe-tab engine picker** — choose the transcription engine (offline
  Faster-Whisper, whisper.cpp, Parakeet, Gemini cloud, Google Cloud STT) right on
  the Transcribe tab, with a readiness line (✓ Ready / ⚠ needs setup) for the
  chosen engine. Switching the engine restarts the worker so the change takes
  effect on the next transcription. The engine list + availability live in the
  new `core/backends/availability.py` shared by the tab and the Advanced dialog.
- **Google Cloud STT as the default engine** in builds that bundle a
  service-account key (`creds/gcloud_stt.json`, never committed — gitignored,
  build-tree only); a source checkout with no key stays fully offline on
  faster-whisper. The Advanced dialog now shows when the bundled key is loaded
  and auto-runs the connection test on open.

### Fixed

- **Worker stdin reader** could park forever on a Windows pipe — now uses a
  bounded `readline` so short JSON commands return promptly.
- **Checkpoint probe** no longer needs `model_path` set: it resolves the model
  folder from the configured model + hub folder, so the ~3 GB download dialog is
  not shown when the model is already present.
- **Download time-range sliders** no longer cross over — dragging one knob past
  the other snaps both so the visible range stays valid.
- **Engine switch now restarts the worker.** The live worker snapshots the
  backend at spawn and the dispatch preferred that stale value, so a switch did
  not take effect until the process restarted; both the picker and the Advanced
  dialog now stop the worker on a backend change.
- **CLI** `transcribe --formats` choices come from the writer registry (so
  `smtv_docx` is accepted) and the CLI reports the real written paths + live
  progress.
- The Advanced dialog refuses to save the unsupported Google Cloud STT +
  diarization combination.
- **Offline-model download has a HuggingFace fallback.** When the smch.ir
  mirror 404s / fails for a model, the same model is fetched from
  huggingface.co via faster-whisper's own download map — which resolves each
  model's correct upstream repo (e.g. `large-v3-turbo` →
  `mobiuslabsgmbh/...`, `distil-large-v3.5` → `distil-whisper/...`, not the
  `Systran/...` guess that 401'd).
- **Google Cloud STT client is now bundled** in the slim tree (was installed
  on first use), so the cloud engine works immediately with no "could not
  install … check internet" wait, and grpcio is built for the bundled
  Python so it can't be shadowed by a wrong-version cache.
- **On-demand extras dir is appended to `sys.path`, not prepended**, so a
  bundled library always wins over a stale on-demand copy in the user cache
  — repairing machines whose pylibs held a broken, wrong-Python grpcio.
- **Transcribe-tab readiness is a real check now** — the engine status line
  genuinely probes (model on disk, client actually imports, key present) on
  a background thread instead of always reading "Ready".
- **Advanced settings order** — the less-important Gemini "Google API key"
  field now sits below the Google Cloud Speech-to-Text section.

## [1.3.8] — 2026-06-06

> Hardening release on top of v1.3.7: the Phase 1–6 feature work (Google
> Cloud / Gemini cloud STT, the optional LAN/web server, transcript-format
> conversion, the SMTV team `.docx`, the multi-monitor Video Tiling rewrite,
> three-level merged config, multi-model picker, ffplay
> auto-download, and macOS groundwork) **plus a 44-finding adversarial audit
> fixpack** — every finding independently confirmed by skeptic review and
> covered by a hermetic regression test. pyright `app/ core/` 0/0/0; hermetic
> suite green.

### Fixed — adversarial audit fixpack (44 confirmed bugs)

- **Data loss:** transcript-format conversion overwrote the source file in
  place on a case-only extension difference (Windows); cloud STT collapsed a
  whole file into one chunk when the duration was unreadable (truncating long
  transcripts); the SMTV `.docx` writer rendered a literal `"None"` for a null
  segment.
- **Crashes / launch failures:** a non-finite (`Infinity`) numeric in a
  hand-edited config crashed startup; a non-string `model.name` crashed config
  load; the Advanced dialog's free-text Batch-size field crashed Save; a
  non-`dict` `words` entry crashed conversion; the TSV writer raised on
  non-finite timestamps; a non-ASCII LAN-server auth token bricked the server.
- **Reliability / concurrency:** the tray exit latch stayed stuck after a
  declined quit (minimise-to-tray broke permanently); a stopped-then-restarted
  Video Tiling run could revive the old worker; the LAN server leaked a worker
  (and the hot model) when a paused job was stopped; download pause/resume and
  the tiling run-token had races/TOCTOU windows; sqlite reads raced the writer
  thread.
- **Windows process teardown:** a graceful kill of the yt-dlp/ffmpeg tree could
  orphan the process and hold the file handle — now escalates to a forced kill.
- **Resource / security:** the LAN multipart upload was fully buffered in RAM
  (now streamed); JSON bodies and the online-config fetch are now size-capped;
  `stats_url` and URL-job hosts get scheme / SSRF validation; aborted optional
  pip installs no longer orphan their child tree.
- **Smaller correctness:** LRC timestamps no longer emit `:60.00`; SMTV episode
  URLs with a query string / fragment are recognised; per-chunk cloud
  diarization labels stay consistent; cloud RPCs have timeouts and honour
  cancel; the multi-monitor index is now a stable total order.

### Added

- **Optional LAN / web server mode.** `python gui.py serve` starts a
  stdlib-only HTTP server (no new dependency) so a phone or another PC can
  send a file or a URL to transcribe from a browser. It binds to loopback
  (`127.0.0.1`) by default — no Windows firewall prompt — and `--lan` is an
  explicit opt-in to listen on the local network. Optional `--port`,
  `--host`, `--token` (shared-secret gate) and `--max-upload-mb` (upload
  cap). The page and a small JSON API accept an upload **or** a URL job,
  poll progress, and download the result; transcription runs in-process and
  sequentially so the ~3 GB model stays hot, behind a bounded queue. Jobs
  are recorded to history. New Tk-free `core/server/` package; new config
  keys `server_port` / `server_max_upload_mb`. (Verified live on this
  machine: `GET /api/health`, `/api/formats`, and `/` all 200.)
- **Optional Google Gemini cloud Speech-to-Text backend** (`cloud_stt`).
  Paste a free AI Studio API key and transcribe over the Gemini API via
  stdlib REST (default model `gemini-3.5-flash`, configurable), with chunked
  upload through the Files API. A loud privacy opt-in makes clear this
  **uploads your audio to Google and breaks the offline guarantee**. An
  honest *local* minutes-used counter (the $300 free credit is **not**
  readable from an API key, so we don't pretend to show it) plus a link to
  Google's billing console. New config keys `cloud_stt_api_key` /
  `cloud_stt_model` / `cloud_stt_minutes_used` / `cloud_stt_free_minutes_cap`
  / `cloud_stt_chunk_seconds`. *(The real end-to-end Google call is
  UNTESTED here — no API key in this environment; live-test with your own
  key before relying on it.)*
- **Opt-in update check** (notify-only — it never auto-installs). A new
  `core/updates.py` queries the GitHub releases API; a Help-menu "Check for
  updates" runs it on demand and a throttled quiet check runs at launch. It
  is silent on a private repo, offline, or when already up to date. New
  config keys `update_check_enabled` / `last_update_check`. Also documented
  that the Standard installer already upgrades **in place** over the
  previous version (stable Inno `AppId` — no uninstall needed).
- **Always-visible per-task action bars** under both Queue tabs —
  Pause / Resume / Cancel / Re-run / Remove buttons on each row (plus a
  click on the status cell to toggle), so the controls are discoverable
  without the right-click menu (which, with Esc, still works). Download
  "pause" is **stop-and-continue**: it keeps the `.part` and resumes via
  yt-dlp `-c`/`--continue`; pause is disabled for Supreme Master TV
  downloads, which have no resume point.
- **Multi-monitor Video Tiling.** The Tiling tab was rewritten from a
  single-screen `ffplay tile=NxN` into a Tk-free multi-monitor engine
  (ported from the maintainer's `video-tiler` v1.1): one download is fanned
  out to one `ffplay` per selected monitor, with `poll()` liveness,
  exponential-backoff reconnect, self-healing `yt-dlp -U`, more robust
  extraction (player-client fallbacks, retries, height-based format),
  http(s) URL validation, and clean teardown via
  `core._proc.kill_process_tree` (fixes orphaned ffmpeg/yt-dlp children).
  New `core/monitors.py` detects screens (screeninfo → ctypes Win32 →
  single-monitor fallback). UI adds Quality / Mute / Multi-monitor and a
  "Monitors…" chooser with Identify and Auto-restart. New config keys
  `tiling_quality` / `tiling_mute` / `tiling_multi_monitor` /
  `tiling_selected_monitors` / `tiling_auto_restart`. New optional
  dependency: **screeninfo** (multi-monitor degrades gracefully without it).

#### Phase 2 (added later in the same local batch)

- **Real Google Cloud Speech-to-Text backend** (`google_cloud_stt`) — a
  second, more capable cloud option alongside the simple Gemini one. It
  authenticates with a **service-account JSON file** (not a pasted key) and
  uses the official `google-cloud-speech` **v2** client, which is installed
  **on demand on first use** (via `core/optional_deps.py`) — not bundled.
  Two modes:
  - **Standard / online** — decodes with the bundled ffmpeg, splits the
    local file into ≤ ~55 s chunks, calls `recognize()` inline per chunk,
    and offsets + stitches the timestamps. No Cloud Storage needed
    (~$0.016 / min).
  - **Batch** — uses v2 `BatchRecognize` through a user-supplied Google
    Cloud Storage bucket (`gs://`) with `DYNAMIC_BATCHING` (~$0.004 / min,
    ~75 % cheaper) at the cost of up to ~24 h turnaround.

  Supports word-level timestamps and speaker diarization. The earlier
  Gemini backend (`cloud_stt`) is **kept** as the simpler paste-a-key
  alternative; both are clearly labelled in the UI. *(The real Google Cloud
  network path is **UNTESTED** here — no service-account JSON in this
  environment; live-test before relying on it — see the handoff.)*
- **Cloud STT settings UI** (`app/dialogs/advanced.py`) — the backend
  dropdown now shows human labels for both cloud options, and a dedicated
  **Google Cloud Speech-to-Text** section adds: a service-account JSON file
  picker; a "How do I get this file?" step-by-step help dialog with
  clickable links to the exact Google Cloud console pages; a non-blocking
  **Test connection** button (installs the Google libs on demand, then
  validates the JSON + auth); a **Batch-mode** toggle with a GCS bucket
  field; a **diarization** toggle; and a **live usage display**.
- **Free-tier usage tracking** — a local **monthly** minutes counter (it
  resets each calendar month) plus an honest estimated-cost line
  ("X / 60 free minutes this month; estimated $Y of the $300 credit"),
  clearly labelled a *local estimate* with a link to the real Google
  billing console (the true remaining credit is **not** readable from the
  key). New config keys `gcloud_stt_minutes_used` /
  `gcloud_stt_minutes_month` / `gcloud_stt_free_minutes_cap`.
- **One-click Web / LAN access** — a new **Web / LAN access** tab
  (`app/app.py` + `app/widgets/tabs.py`, backed by a `core/server`
  `ServerHandle`) with a single **Start/Stop** toggle, a port field (with a
  free-port fallback when the chosen port is busy), a **Share on local
  network** checkbox (loopback by default vs `0.0.0.0` with a plain-language
  firewall note), an optional **access password** (token), the reachable
  URL(s) including the LAN IP, an **Open in browser** button, non-blocking
  start/stop, and auto-stop on app exit. New config keys `server_share_lan`
  / `server_token` (`server_port` / `server_max_upload_mb` already existed
  from the Phase-1 `gui.py serve` work).
- **About dialog enriched** (`app/app.py` `_show_about`) — a **What's new**
  section plus plain-language descriptions of all the cloud options, the
  Web / LAN access, the per-task controls, multi-monitor tiling, and the
  update check / in-place upgrade, with clickable helpful links.

#### Phase 3 (added later in the same local batch)

- **Seek / scrub transport bar in the VLC transcript preview.** The
  built-in transcript player now has a draggable position bar with a
  live `MM:SS` time readout, ±5 s / ±10 s skip buttons, and keyboard
  control, so you can scrub to a moment instead of only play/pause. It
  degrades gracefully when VLC is absent (the transport bar simply isn't
  shown).
- **Web / LAN feature parity with the desktop app.** A browser job can now
  carry the same **per-job advanced options** as the desktop (VAD, word
  timestamps, diarization, clip range, etc.), applied via a per-job
  `.whisperproject.json` override; a new `GET /api/jobs` lists all jobs;
  **pause / resume** routes were added; outputs are taken from the
  engine's `task.output_paths`; and the page is now a small **3-view
  browser UI** (Submit / Jobs / Result with the transcript shown inline).
  Uploads are **streamed to disk** (no full-RAM buffering). HTTP hardening:
  the request body is drained on an early reject (no broken-pipe noise) and
  the access token is compared in **constant time**. *(Security boundary:
  the cloud / alternate backends are deliberately NOT per-job switchable
  over the web — a remote submitter can't redirect your audio to a cloud
  backend.)*
- **"SMTV transcription" docx output format** (registry key `smtv_docx`,
  UI label **"SMTV transcription"**). It fills the transcription team's
  bundled Word template (`core/writers/templates/smtv_template.docx`) — a
  4-column table (auto row number; `Time Code` as `HH:MM:SS.m`; `Foreign
  Language` = the transcript text; `English Translation` left empty for the
  human translator), with a title line
  `"<work title> -Transcription in <language> – Translation in English"`
  and the output filename matched to it. The table grows past the template's
  31 pre-formatted rows, and a `.docx` extension is forced.
- **Installer opt-out for Video Tiling.** `installer_embed.iss` adds a
  **"do NOT include Video Tiling"** task; selecting it drops a
  `{app}\no_tiling.flag` marker and the app then hides the Video Tiling tab
  (`core.hub.tiling_tab_enabled()`).

### Changed

- **The model now downloads to a writable location by default.** The
  first-run hub default moved from the install directory (under Program
  Files — "access is denied" for a non-admin user) to
  `%LOCALAPPDATA%\WhisperProject\Cache\models`. The model-download dialog
  surfaces a typed `ModelDestinationNotWritable` and offers a re-pick, the
  hub-folder picker probes writability when you click OK, and the default
  hub is aligned with `model_folder_for`'s empty-hub fallback
  (`HUB_SUBFOLDER_NAME = "models"`) so an existing `Cache\models` model is
  **reused, not re-downloaded** (~3 GB saved). Verified on this machine with
  a real `load_config()` probe.

#### Phase 3

- **Google Cloud STT defaults are now `chirp_2` / `us-central1`** (were
  `long` / `global`). This was **live-verified** against the owner's
  service-account JSON (project `crucial-context-297802`): the previous
  `long` / `global` pairing rejected language auto-detect, whereas `chirp_2`
  supports auto-detect and multilingual input. New config defaults
  `gcloud_stt_model = "chirp_2"` and `gcloud_stt_location = "us-central1"`
  in `config.py`.

### Fixed

- **GPU/CPU autodetect is hardened and self-healing.** A cheap cuDNN/cuBLAS
  runtime-load gate means CUDA is only chosen when it's actually usable, and
  a failed CUDA model load now falls back to **CPU int8** instead of
  crashing the worker (and instead of falsely prompting a ~3 GB
  re-download). The effective device is reported additively on the worker
  `ready` event and shown as a live GPU/CPU badge (Transcribe header + Queue
  status); a one-time "running on CPU (slower)" warning is gated to the
  GPU-detected-but-unusable / downgrade case (config key
  `cpu_warning_shown`).
- **Network / UNC drag-and-drop no longer silently drops the file.** A
  backslash-preserving, brace-aware splitter replaces `tk.splitlist`, which
  was collapsing the leading `\\` of a `\\server\share\file` drop.

#### Phase 3 (reported issues + a deep adversarial review)

- **Every Web / LAN job crashed** with
  `'_CancelledTask' object has no attribute 'paused'`. The server's task
  object now mirrors the engine's read contract (renamed `_ServerTask`),
  and the test fakes were hardened so the gap can't regress.
- **"View transcript" closed the whole app.** The root cause was libvlc
  `set_hwnd` on an *unrealized* Tk window — a native crash that bypassed
  `try`/`except` entirely. The HWND bind is now **deferred until the window
  is mapped**, with a graceful fallback; the viewer also now opens the
  actual transcript `.json` instead of popping a spurious file-picker.
- **"Re-detect hardware" froze the UI.** The probe ran on the Tk main
  thread (plus an unbounded cuDNN/cuBLAS `ctypes.CDLL` probe). It now runs
  **off-thread** behind a generation-token guard, with a **timeout-bounded**
  DLL probe.
- **The Queue per-task action bar was unusable** — the 500 ms `refresh()`
  rebuilt the tree and wiped the row selection on every tick. Selection is
  now **preserved across the rebuild**.
- **Off-thread Tk writes fixed.** The Video Tiling log callback and four
  Advanced-dialog worker handlers now marshal back through the main thread
  via a new `App.log_threadsafe`; the tiling status colour is now applied.
- **Smaller fixes** — a status-cell click defers via `after_idle`;
  `start_tiling` guards a bad grid spinbox; `pause_download` only pauses a
  *running* download; the theme + download-folder `save_config` calls are
  guarded; `minimise_to_tray` / `telemetry_opt_in` were added to
  `DEFAULT_CONFIG`; a multi-file enqueue gates the model **once**; the
  Advanced mouse-wheel binding is released on close; and the server handle
  is registered **before** `start()`.
- **Google Cloud STT timing + language correctness** (live-verified with
  the owner's service-account JSON). Language codes are mapped ISO → BCP-47
  (Google v2 rejects a bare `"en"`); word time offsets are **always**
  requested and the words are re-segmented into properly-timed phrases — a
  real run produced **5 correctly-timed subtitle segments** instead of one
  0–30 s blob.

### Docs

- **Evaluation: skip Google's Gemma 4 12B as a transcription backend.**
  `docs/evaluations/GEMMA4_EVALUATION_2026-06.md` recommends a SKIP — a 30 s
  audio cap, a torch/BF16/~24 GB-VRAM requirement, no word timestamps, and
  no WER win over the current stack — while sketching a possible
  future-adjunct path and a hardware gate.
- **New `docs/CLOUD_STT_GOOGLE.md`** (Phase 2) — service-account setup,
  the Standard-vs-Batch trade-off, the GCS-bucket requirement for batch,
  and the honest "the real $300-credit balance is not readable from the
  key" usage note. `docs/SERVER.md` updated for the one-click Web / LAN
  access toggle (alongside the existing `gui.py serve` CLI).

#### Phase 3

- `docs/CONFIG.md` and `docs/CLOUD_STT_GOOGLE.md` updated for the new
  `chirp_2` / `us-central1` Google Cloud STT defaults (was `long` /
  `global`) and the auto-detect / multilingual reason behind the change.
- `docs/SERVER.md` updated for the Web / LAN feature parity — per-job
  advanced options, the `GET /api/jobs` list, the pause / resume routes,
  the 3-view browser UI, and streamed uploads — plus the note that cloud /
  alternate backends are **not** per-job switchable over the web.

## [1.3.7] — 2026-05-29

Senior-architect deep audit (8 parallel read-only shards → fix batches).
pyright `app/ core/` 0/0/0 and the hermetic suite stay green; no shipped
Windows behaviour changed at spawn time. Highlights:

### Security

- **Subtitle burning no longer breaks/injects on punctuated titles.** The
  SRT path went straight into ffmpeg's `subtitles=` filter graph escaping
  only `\` and `:`, but `' , ; [ ]` are filtergraph metacharacters and a
  downloaded video's title (hence its `.srt` name) is attacker-influenced.
  Burning now happens from a temp copy with a graph-safe ASCII name; the
  Windows drive-colon escape is gated to Windows so a POSIX colon path
  isn't mangled.

### Fixed

- **Orphaned grandchild processes.** Killing a worker (or cancelling/
  exiting a download) left its ffmpeg/ffprobe/demucs grandchildren running
  on Windows (`TerminateProcess` doesn't cascade) — burning CPU/RAM,
  holding file handles, leaking GPU memory. New `core/_proc.py` kills the
  whole tree (`taskkill /T` / `os.killpg`); the worker + yt-dlp are spawned
  isolated for it.
- **Alternate backends ignored the Transcribe-tab time range** — a clipped
  request on whisper.cpp / Parakeet silently transcribed and wrote the
  whole file. They now slice `[start,end]` and offset onto the timeline.
- **Model-loading modal could hang forever** if the worker failed to load
  or died before "ready" (only Cancel escaped); it now closes on those
  events and no longer stacks a second modal.
- **Model re-download loop is bounded** (was `while True`) so a bad mirror
  or a captive-portal MD5 body can't re-download ~3 GB forever; the MD5
  manifest parser rejects non-hex lines.
- **On-demand optional installs** (PyTorch features) gained cancel + a
  timeout and stage-then-merge, so a stalled or failed pip can't hang the
  modal or leave a half-written package that crashes the worker later.
- **Format lookups no longer die for the session** when yt-dlp returns
  non-object JSON — the poll loop is self-healing.
- **Hallucination "suspect" flags now reach the JSON** so the transcript
  viewer's red-row review actually works.
- **Resource hygiene**: history DB closed on exit; `partials/` swept of
  orphaned slices + aged-out checkpoints (and cleared when crash-resume is
  declined); demucs vocal-cache bounded; the recorder streams to disk
  (no multi-hour-recording OOM); the yt-dlp pipe is reaped on error.
- **Smaller correctness fixes**: per-format writer isolation verified;
  VTT word `start=None` no longer aborts the file; history paths derived
  via `splitext`; per-folder override defaults no longer leak between
  files; the resume progress bar advances instead of pinning at 99%; LLM
  chapter generation runs under the liveness watchdog; whisper.cpp model
  download verifies length; Parakeet surfaces a clean ffmpeg-decode error;
  download/format/worker loops short-circuit during shutdown.
- The About dialog stopped advertising two not-yet-wired capabilities
  (cross-file voiceprint matching, semantic/FTS5 search).

### Cross-platform

- `core.tiling` added to both PyInstaller specs' hidden-import lists.
- macOS `install.command` materialises ffmpeg/ffprobe into `bin/` (so the
  double-clicked `.app` finds them regardless of its minimal PATH) and the
  static-ffmpeg unzip is non-fatal under `set -e`. *(macOS unverified on
  real hardware.)*

## [1.3.6] — 2026-05-26

A new Video Tiling tab + the groundwork for running on Linux and macOS.

### Added

- **Video Tiling tab.** Paste a live-stream URL (YouTube, X/Twitter, and
  the other yt-dlp sites), pick a grid size, and the stream fills the
  screen as an N×N "video wall" (ports the maintainer's `video-tiler`).
  Uses **ffplay**, which isn't bundled — the tab shows how to add it when
  it's missing, so the base download stays the same size.
- **Linux support** (`platform/linux/`): a one-step `install.sh` (venv +
  deps + `yt-dlp` + a static `ffmpeg` fallback + desktop launcher), a
  headless `whisper-transcribe` CLI for servers, plus `update.sh` /
  `uninstall.sh` and a README.
- **macOS groundwork** (`platform/macos/`): a double-click `install.command`,
  a Gatekeeper `unblock.command` (`xattr -dr com.apple.quarantine`), and a
  README covering the unsigned-app install flow. Marked needs-real-Mac
  validation.

### Changed

- **Cross-platform core hardening.** `yt-dlp`/`ffmpeg`/`ffprobe` resolve to
  the right per-OS binary (bundled or on PATH); `--ffmpeg-location` is only
  passed when a bundled ffmpeg exists; VLC discovery now covers macOS
  (`VLC.app`) and Linux library dirs as well as the Windows registry. The
  Windows build is unchanged.
- Added a `.gitattributes` pinning LF on shell/`.command` scripts so they
  run on Linux/macOS regardless of git's autocrlf.

## [1.3.5] — 2026-05-25

Real pause/resume/cancel + a post-slim hardening pass (five parallel
code-audit shards over everything that changed in v1.3.x).

### Added

- **Pause / Resume now actually work, and Cancel keeps your progress.**
  Previously Pause did nothing to a running job and Cancel killed the
  worker and threw away the partial transcript. The worker now reads
  pause/resume/cancel on a side channel while it's transcribing: Pause
  halts at the next segment, Resume continues, and Cancel saves a
  resumable checkpoint (so "Re-run" picks up where you stopped) instead
  of discarding it.

### Fixed

- **A docx-only (or pdf-only) result no longer looks lost.** The "Last
  result" card and the history record now list the files the worker
  actually wrote — including docx/pdf and de-duped `name (1).srt` names —
  instead of guessing from settings (which only knew srt/json/txt/…).
- **You can cancel an auto-transcribe from the Download row.** Right-
  clicking a row that shows "transcribing" now offers Cancel (the menu
  was empty before).
- **A sub-second download end time no longer corrupts the range** (e.g.
  `1:30.999` no longer became a bogus `0:01:301`).
- **One broken output writer no longer discards the others.** A failing
  format is logged and skipped; the formats that wrote fine are kept
  (only an all-formats failure raises).
- Pausing a task that hadn't started yet no longer strands it.
- Progress bars tolerate a non-finite percentage without erroring.

### Changed

- On-demand optional-feature installs are serialized (two requests can't
  race into a half-written package) and their progress log is delivered
  to the UI thread safely.
- The slim build also drops the orphaned `llvmlite` native-lib folder
  (~30–40 MB) and the build's sanity check imports the docx/pdf writers,
  so a future prune mistake fails the build instead of silently breaking
  docx again.

## [1.3.4] — 2026-05-25

Much smaller install + a docx fix.

### Changed

- **Install size cut from ~1.5 GB to ~800 MB.** PyTorch and the heavy ML
  libraries it drags in (sympy/networkx/numba/llvmlite) are no longer
  bundled — they were only needed by two optional features.

### Added

- **On-demand optional features.** Word-timestamp alignment (stable-ts)
  and the openai-whisper backend now download their support (~700 MB,
  PyTorch) on first use into a user folder, the same way the Whisper model
  is fetched. Declining just runs without that feature. Core transcription,
  subtitles, diarization, and downloads are unaffected and need no
  download.

### Fixed

- **DOCX / PDF output now actually written.** The long-lived worker read
  its config once at startup, so a docx/pdf format ticked afterward never
  reached it; the selected output formats are now sent with each job.

## [1.3.3] — 2026-05-25

Features + a follow-up bug-hunt (the time-slice and download flows).

### Added

- **Position slider on the Download tab.** After a video is probed, drag
  the Start / End sliders (0 .. video length) to fill the time-range
  fields instead of typing.
- **Portable ZIP** is now a first-class download — the full embeddable-
  Python environment + a `Run Whisper Project.bat` launcher. No install;
  update by swapping `app\` / `core\` files.

### Changed

- **License changed from MIT to BSD-3-Clause.** Added a root `LICENSE`
  and a `THIRD_PARTY_NOTICES.md` summarizing the bundled components'
  licenses (FFmpeg, yt-dlp, the Python runtime + packages).

### Fixed

- **A clipped transcription that was cancelled then resumed** no longer
  transcribes past the end of the clip (a clipped run now neither resumes
  nor writes a whole-file checkpoint).
- **A reversed time range (end before start)** no longer makes the
  download fetch nothing — it degrades to "from start to the end".
- The Download-tab sliders no longer wipe a manually-typed range when the
  format probe finishes, and ignore stray drags before a video is probed.
- The login/cookie download hint no longer fires on unrelated errors
  (it matched substrings like "stor**age**"/"**page**").

## [1.3.2] — 2026-05-25

Security + features release. A dedicated security/concurrency/resource
bug-hunt (four more parallel audit shards) plus the most-requested
feature.

### Added

- **Transcribe a time-slice of a file.** The Transcribe tab now has
  Start / End fields (default 0:00:00 = whole file), so you can transcribe
  e.g. 5 minutes out of a 10-hour recording. Segment timestamps stay on
  the original timeline.

### Security

- **yt-dlp option injection closed.** A pasted "URL" beginning with "-"
  was handed to yt-dlp without a "--" end-of-options separator, so it
  could be parsed as a flag (e.g. `--exec` → command execution) — and the
  format probe fires on paste. All three yt-dlp argv builders now insert
  "--" before the URL.
- **Zip-slip guard** on model-archive extraction: members that would
  resolve outside the cache dir are now rejected.

### Fixed

- **Failed downloads now say WHY.** Instead of "yt-dlp exited with code
  N", the queue shows yt-dlp's real error line; for login-walled sites
  (Facebook / Instagram) it adds a hint to enable "Cookies from browser"
  in Advanced settings.
- **Progress percentage stays visible during start-up.** The "working"
  animation kept the number (it had briefly hidden it behind a moving
  bar), so you can always see how far along a transcription is.
- **Corrupt-but-readable media** (ffprobe reports "N/A" duration) no
  longer aborts the run with an opaque error — it transcribes anyway.
- **Model-path fix when a hub folder is selected** (contributed).

## [1.3.1] — 2026-05-25

Reliability release — a focused bug-hunt (tracing each UI action through
the code, four parallel audits) on top of v1.3.0.

### Fixed

- **Auto-transcribe after a download silently produced no transcript when
  the title had a non-ASCII character** (apostrophe, accent, emoji, CJK).
  yt-dlp wrote stdout in the Windows code page, so the saved path came back
  mojibake'd and didn't match the real file. Now forces UTF-8 output, plus
  a **self-healing fallback** that finds the actual downloaded file when
  the parsed path is wrong — so even an unheard-of character can't lose the
  transcript.
- **Picking a non-English language crashed transcription with no output.**
  A region tag ("en-US") or a multi-value picker code ("zh-Hans,zh-CN",
  "pt,pt-BR,pt-PT", "he,iw") was passed straight to faster-whisper, which
  rejected it. Language hints are now normalized to a base ISO code on
  every transcription path.
- **The viewer said "VLC isn't installed" when VLC was installed.** It now
  locates VLC via the registry / Program Files, and the message spells out
  that a 64-bit VLC is required (a 32-bit VLC can't load into the 64-bit
  app).
- **Cancelling a download that had moved on to transcribing** left the
  transcription running and silently undid the cancel; **re-running a
  time-range download** fetched the full video. Both fixed.
- **Optional features no longer crash the app on probe.** Speaker
  diarization / alternate engines that fail to load a native library now
  just show as unavailable instead of taking the app down.
- **The Transcribe tab rejects a missing / mistyped file** with a clear
  message instead of failing deep in the worker.

### Added

- **An animated "working" bar** in the queue while a task is starting up
  (model load) so it's clear something is happening before the percentage
  begins.
- **The download time-range Start / End fields are pre-filled with
  0:00:00** so they're easier to edit (leaving both = the full video).

## [1.3.0] — 2026-05-25

UX + reliability release on top of v1.2.0 — bug fixes and visibility
improvements found while running the app on real downloads.

### Added

- **Graphical progress bars in the queue rows.** The transcription and
  download queues draw a block bar (e.g. `████░░░░░░ 42%`) next to the
  number, so progress is visible at a glance instead of just a figure.
- **The version is visible.** The window title shows `Whisper Project
  v1.3.0`, and the Standard installer's Start-menu / desktop shortcut is
  named with the version — so you can tell which build is installed.
- **The Download tab shows transcription progress.** After an
  auto-transcribe-from-download, the download row reads "transcribing"
  and mirrors the live transcription progress, then flips to "finished",
  so a slow transcription no longer looks like a stalled, idle 100%.

### Changed

- **The "Last result" card no longer dominates the Transcribe tab** — it
  sizes to its content instead of expanding to fill the lower half.
- **The transcription language resets to "Auto" on every launch** and is
  no longer persisted; every other transcribe preference is still saved.

### Fixed

- **Auto-transcribe after a video+audio download.** yt-dlp merges the two
  streams into one file and deletes the per-stream fragments; the
  saved-path parser had been matching the now-deleted audio fragment, so
  auto-transcribe hit "No such file or directory" and silently did
  nothing. It now resolves the merged output (and the
  already-downloaded / extracted-audio cases too). Seen on Facebook reels
  and YouTube Shorts.

## [1.2.0] — 2026-05-25

UX + accessibility release on top of v1.1.0 — mostly things the operator
hit while using the app on a Persian keyboard.

### Added

- **Copy / paste works everywhere now** — a right-click menu (Copy / Cut
  / Paste / Select all) on every text field, plus a copyable log console
  (right-click → Copy / Copy all / Clear). Mouse-driven, so it never
  depends on the keyboard layout.
- **Bulk queue actions.** Select multiple rows in the transcription or
  download queue and Cancel / Re-run / Resume / Remove them all at once.
- **Scrollable queues.** Both queue lists get an auto-hiding vertical
  scrollbar that appears only when the list outgrows the visible area.
- **Model visibility + on-demand install.** The Advanced model picker
  marks each model "downloaded" / "needs download", and a "Download now"
  button installs the selected model without starting a transcription.
- **Open file from the Download tab** — a finished download's context
  menu can open the media file directly (not just its folder).

### Fixed

- **Clipboard shortcuts under a non-Latin keyboard layout.** Ctrl+C / V /
  X / A keyed off the Latin keysym, so copy/paste/cut/select-all were
  dead while a Persian (or Arabic, Russian, …) layout was active. They
  now dispatch by physical keycode.
- **Transcript outputs no longer overwrite a previous run** — a re-run
  writes `name (1).srt` / `name (1).json` (a shared index) instead of
  clobbering the earlier files.
- **The About dialog** shows the live app version (it was hard-coded to
  an old number) and opens in one click (it used to be a menu whose only
  item was another "About").

## [1.1.0] — 2026-05-25

Maintenance release — bug fixes plus one opt-in feature. Restores audio
in video downloads, removes several UI freezes and nags, makes the
model-hub and download-folder choices stick, fails a truncated SMTV
download instead of shipping a corrupt file, and adds browser-cookie
support so login-walled sites (Facebook / Instagram / TikTok stories,
age-gated YouTube Shorts) can download.

### Added

- **Download from login-walled / age-gated sites via browser cookies.**
  A new "Cookies from browser" picker in Advanced → Downloads passes
  yt-dlp's `--cookies-from-browser`, so Facebook / Instagram / TikTok
  stories and age-restricted YouTube Shorts can download using your
  logged-in browser session. Off by default; pick your browser
  (Chrome / Edge / Firefox / …) to enable.

### Fixed

- **Video downloads were silent (no audio).** yt-dlp's format selector
  was emitted as `video…/bestvideo+audio…/best` without grouping, so
  yt-dlp's `/` precedence selected a video-only stream and the merged
  file had no audio. Each stream group is now parenthesized:
  `(video…)+(audio…)/best`.
- **Model-load froze the UI on several paths.** Three main-thread
  enqueue paths — auto-transcribe-after-download, crash-resume
  ("Resume interrupted transcriptions?" → Yes), and the watched
  folder — waited synchronously for the Whisper model to load (up to
  the 120 s timeout), freezing the whole app. They now share one
  non-blocking helper that spawns the worker and polls for readiness
  with `after()`, so the UI stays responsive and the task is queued
  once the model is ready.
- **The model hub folder you picked was ignored.** A `model_path`
  derived from the *default* hub during startup was being written to
  `config.json`, then treated on the next launch as an explicit
  per-model override that outranked your chosen `hub_folder` — so the
  model always loaded from `<app>/hub` and `model_path` looked like it
  "reset" every launch. Auto-derived model paths are no longer
  persisted; a genuinely custom path is still kept.
- **The crash-resume prompt reappeared on every launch.** Declining
  "Resume interrupted transcriptions?" left the rows flagged
  `interrupted`, so the same prompt returned next time. Declining now
  clears the flag on the offered rows; genuine future crashes still
  prompt.
- **A download folder on a removable / network drive was forgotten.**
  If the drive was detached at launch, the folder was cleared *and the
  cleared value was written back to config*, so the choice was lost
  permanently. The cleared value is no longer persisted while the drive
  is merely unmounted — the folder returns when the drive does. (Same
  class as the `model_path` fix above.)
- **A truncated Supreme Master TV download was treated as success.** If
  the CDN dropped the connection mid-transfer, the partial file was
  renamed to the final name and auto-transcribed — a clean-looking but
  corrupt result. The download now fails and reports an error when fewer
  than the advertised (Content-Length) bytes arrive.

### Changed

- The **Advanced settings** dialog is now resizable and scrolls, so it
  fits on smaller screens.
- The **About** dialog no longer shows the source-repository URL.

## [1.0.3] — 2026-05-23

UX + memory release. Adds the optional time-range download
collaborators asked for and changes the model-load policy so
idle launches don't pay for ~2 GB of RAM the user may never use.

### Added

- **Time-range video download.** New optional Start / End fields
  on the Download tab. Fill either (or both) in `H:MM:SS`,
  `MM:SS`, or seconds, and yt-dlp's `--download-sections`
  fetches only that slice. The Queue row label shows a
  `trim 0:51 → 1:25` badge so it's obvious which jobs are
  partial. The transcribe step naturally runs proportionally
  faster — most of the savings come from the smaller audio,
  not the smaller download. Supreme Master TV URLs are not
  sliced in this release (the SMTV scraper has no slicing path);
  one clear WARN log line + a known-limitation note in
  `docs/integrations/smtv-brief.md`.
- **Lazy Whisper-model load.** The app no longer preloads the
  3 GB Whisper model on launch. Idle RAM drops by ~2 GB.
  The first transcribe of a session shows a modal "Loading
  Whisper model…" dialog with an indeterminate progressbar; the
  worker spawns and loads, the dialog dismisses, the transcribe
  proceeds. Subsequent transcribes reuse the alive worker — only
  the first one pays the load. Crash-resume and watched-folder
  enqueues go through the same gate without showing a modal
  (headless mode, 120 s timeout).

### Changed

- `App._on_start` no longer calls `start_standby()`. The method
  is kept as a deprecated proxy for backwards compatibility with
  any test that still calls it.

### Documentation

- `docs/integrations/smtv-brief.md` — added the time-range
  limitation note.

### Shipped artefacts

Same shape as v1.0.2: Portable + Setup-Standard only. The
Compact pipeline still exists in the repo + still builds, but no
Compact EXE is published.

## [1.0.2] — 2026-05-23

Reliability + UX release. Closes the long-uptime + multi-hour-file
gaps the 2026-05-23 stability audit catalogued, and lands the
resume-from-cancellation feature.

### Added

- **Resume from cancellation / pause / crash.** The transcribe
  loop now writes a periodic checkpoint
  (`%LOCALAPPDATA%/WhisperProject/partials/<sha1>.json`) every 10
  segments or 20 s. Cancelling, pausing or crashing keeps the
  checkpoint on disk; a new Resume command on cancelled rows
  slices the source audio from the last segment boundary,
  transcribes only the remainder, merges with the already-done
  segments, and runs the post-pipeline (diarisation, chapters,
  alignment, voiceprint) on the full merged result. faster-whisper
  backend only; whisper.cpp and Parakeet fall back to a fresh
  re-run with a clear log line. Validates source mtime/size and a
  config fingerprint before resuming, so a changed file or model
  silently starts fresh instead of producing garbage.
- **Pause command in the queue right-click menu** for running
  tasks. The engine already supported `task.paused`; the menu
  entry was the only missing UI surface.
- **About dialog feature inventory.** The previous one-line
  `messagebox.showinfo` is replaced by a scrollable Toplevel
  listing every capability of the app grouped into nine
  sections — Transcription engine, Output formats,
  Post-processing, Video download, Transcript viewer, Workflow
  + system integration, Search + statistics, Keyboard shortcuts,
  Privacy. Many capabilities ship enabled by default but live
  behind the Advanced dialog with no main-UI surface; this
  dialog is the canonical "what does this app actually do"
  reference.

### Fixed

- **3 GB re-download on the launch after the first-run hub picker.**
  (Originally fixed in v1.0.1; carried forward.) The hub-folder
  dialog was asynchronous and the worker spawned with an empty
  `hub_folder`, downloading the model to a path the next launch
  wouldn't resolve to. Aligned the empty-hub fallback in
  `_apply_runtime_fallbacks` with the dialog's default and
  deferred `start_standby()` until the dialog answers.
- **Worker liveness watchdog kills diarisation on long files.**
  `_run_post_pipeline` now plumbs `progress_cb` into
  `diarization.diarize`, mapping sherpa-onnx's 0..1 tick into the
  90..99 percent slot. Bumped `LIVENESS_TIMEOUT_S` from 30 s to
  120 s as defence in depth.
- **Same watchdog pattern in four more silent C calls.** New
  `core/_liveness_tick.py` context manager wraps
  `stable_ts.model.align(...)`, the Demucs CLI subprocess, the
  Parakeet `decode_stream(...)` call, and the whisper.cpp
  `model.transcribe(...)` call. Without this, every alt-backend
  transcription and every alignment / Demucs run on slow CPU was
  one watchdog tick away from a mid-flight kill.
- **`.whisperproject.json` overrides leak across files.**
  `_apply_runtime_overrides` mutated the module-level config in
  place. The long-lived worker carried a folder-A override into
  folder-B's files. Now wrapped in `_runtime_overrides_scope`
  which snapshots and restores touched keys around each file —
  with eight regression tests.
- **`tk.after(0, ...)` from background threads.** On Python 3.14
  this raises `RuntimeError`; on earlier 3.x it's undefined and
  the existing `try/except: pass` blocks silently dropped the
  callback. Added an `App._main_thread_calls` queue + drainer +
  `post_to_main(fn)` helper; rerouted burn-subs, hardware-wizard
  benchmark, and tray-click callbacks through it.
- **Demucs temp-directory leak.** `tempfile.mkdtemp(...)` in
  `core/separator.py` was never removed on the success path,
  leaking 30–50 MB per separation. Cleanup now lives in a
  `finally:`.

### Documentation

- `docs/STABILITY_AUDIT_2026-05-23.md` — 26-item audit driven by
  the diarisation-watchdog bug. 7 P0 / 9 P1 / 10 P2 with
  file:line + symptom + suggested fix. P0s plus the
  highest-leverage P1 are closed in this release; the rest are
  the next-session punch list.

### Shipped artefacts

This release skips the Setup-Compact installer (Portable +
Setup-Standard cover the same audiences). Two EXEs uploaded to
the v1.0.2 release page.

## [1.0.1] — 2026-05-23

First stable release. Marks the project as feature-complete + freeze-ready
after an audit-driven hardening sweep (~62 of 72 audit items closed, the
rest deferred with documented rationale), plus a pre-ship fix for a
fresh-install model re-download race caught during verification.

### Fixed

- **3 GB re-download on the launch after the first-run hub picker.**
  On a fresh install the first-run hub-folder dialog was asynchronous:
  it opened, returned the default path immediately, and `_on_start`
  fired `start_standby()` while the user was still reading the
  dialog. The worker then computed `model_path` from an empty
  `hub_folder` and downloaded the model under
  `%LOCALAPPDATA%\WhisperProject\Cache\models\`. When the user
  accepted the dialog default (`<app_dir>\hub`), the next launch
  resolved `model_path` to a directory the model was never
  extracted into, triggered a `startup_error`, and re-downloaded
  the full 3 GB archive. Fixed by:
    * Aligning the empty-hub fallback in
      `_apply_runtime_fallbacks` with the dialog's default
      (`default_hub_folder()`), so accepting the default is a no-op
      for the model location.
    * Deferring `start_standby()` in `App._on_start` until the hub
      dialog's `on_done` callback fires, so the worker starts with
      the user's actual choice even when they pick a custom folder.
  Regression test added in `tests/core/test_hub.py`.

### Added — v0.8 Phase 1 (Shards A + B)

- **Hallucination detector** — flags suspect Whisper segments via
  three signals: Bag-of-Hallucinations wordlist, 1/2/3-gram
  repetition, and (optional) VAD-disagreement. Annotates JSON with
  `seg["suspect"] = True` + `suspect_reason`. Transcript viewer
  highlights flagged rows in red. Toggle:
  `hallucination_detect_enabled`.
- **Multi-model picker** — Large v3 (default), Large v3 Turbo, and
  Distil Large v3.5 selectable from the Advanced dialog. Slug-keyed
  registry; existing config keeps working unchanged.
- **Hardware autodetect wizard** — probes CUDA → QNN/NPU → OpenVINO
  → DirectML → CPU int8, persists the choice in `hardware.json`,
  re-validates at every model load.

### Added — v0.8 Phase 2 (live + AI layer foundations)

- `core/recorder.py` — mic + WASAPI loopback recorder.
- `core/llm.py` — local LLM panel (Qwen2.5-1.5B, download-on-first-use).
- `core/separator.py` — Demucs vocal-separation pre-process.

### Added — v0.8 Phase 3 (data + recognition expansion)

- `core/backends/parakeet.py` — sherpa-onnx Parakeet TDT v3 backend.
- `core/search.py` — semantic + FTS5 search across saved transcripts.
- `core/chapters.py` — auto-chapter markers via long-silence heuristic.
- `core/voiceprint.py` — cross-file speaker fingerprint DB.

### Added — Model Hub Folder feature

- First-run dialog asks where to store Whisper model files; choice
  is persisted to `config.json` under `hub_folder`. Default
  suggestion: `<app>/hub`. Inno Setup uninstaller asks whether to
  delete out-of-tree hub folders.

### Hardened — audit-driven (R-series)

- WAL journal mode + integrity check on `history.db` (crash-safe).
- Worker IPC: per-worker UUID session token + 5 s heartbeat + 30 s
  liveness watchdog. stdin writes moved off Tk thread. History row
  inserted BEFORE dispatch.
- Structured 4-step worker shutdown (stdin → wait → terminate → kill).
- INFO logs at every device / backend / model decision point.
- `--safe-mode` CLI flag: backs up `config.json` aside, fires fresh
  first-run dialog.
- `safe_thread` helper: every daemon thread now logs uncaught
  exceptions with full stack trace.

### Tests

535 unit + integration tests (+260 from 0.7.x baseline of 275).
10/10 real-file end-to-end against the SMTV reference clip. 7/7
smoke + end-to-end against the real Whisper model. pyright `app/
core/` 0 errors, 0 warnings, 0 informations.

### Documentation

- `docs/SENIOR_REVIEW_2026-05-21.md` — engineering audit
- `docs/EXECUTION_ROADMAP.md` — derived patch plan (35+ items)
- `docs/FINAL_FREEZE_AUDIT_2026-05-21.md` — pre-release sign-off
- `docs/RELEASE_PROCESS.md` — the ship sequence
- `docs/README.md` — navigation index for `docs/`
- `docs/roadmap/` — future-release research (v0.9 + beyond)

## [0.7.1] — 2026-05-20

Version bump packaging the Session-14 hands-off polish push, listed
in detail below under the original 0.7.0 history. Same source as the
final 0.7.0 build; rebranded so the three installer EXEs reflect the
new feature surface (backends, viewer enhancements, tray, …).

## [0.7.0] — 2026-05-20

### Added — Session 14 (hands-off polish from `HANDOFF_NEXT_SESSION.md`)

- **Filename templating** — `output_filename_template` config key is now honoured by every writer. Tokens `{base}`, `{ext}`, `{lang}`, `{date}`, `{speaker_count}` resolve at write time. Templates may include sibling subdirectories (`transcripts/{base}.{ext}`) — those folders are created on the fly. Malformed templates fall back to the legacy `{base}.{ext}` layout so a corrupt config never blocks a write.
- **Pluggable Whisper backends** — `core/backends/` houses an ABC plus two implementations. `faster_whisper` (default) preserves the CTranslate2 path with module-level `MODEL`/`PIPELINE` globals; `whisper_cpp` drives pywhispercpp on quantised ggml models (~1.1 GB for large-v3-q5_0). The Advanced dialog grows a backend picker and a "Download whisper.cpp model..." button.
- **Word-level alignment refinement** — `core/alignment.py` post-processes Whisper segments through stable-ts when `config["alignment"] == "stable_ts"`. Loads stable-ts's `tiny` Whisper model for the DTW alignment pass so word boundaries lock to ±50 ms.
- **Viewer enhancements (find/replace, speaker rename, fillers, confidence colours, karaoke)** — `Ctrl+F` opens a Find-and-Replace dialog with case-insensitive default + match-case toggle. Right-click on a segment with a speaker label → "Rename ... (everywhere)..." rewrites every same-labelled segment. Word-confidence colour coding (green ≥ 0.85, amber ≥ 0.6, red below) when segments carry `words` with probabilities. "Remove fillers" button strips `uh`/`um`/`er`/… with a whole-word regex. Karaoke wraps the active word in `[brackets]` in the side panel as VLC plays. `Ctrl+S` saves all edits atomically via `core.writers.json_writer`.
- **System tray + minimise-to-tray + native toast** — `app/widgets/tray.py` wraps pystray + Pillow on a daemon thread. Right-click menu: Show / Hide / Exit. Icon flips between a hollow blue ring (idle) and a filled red dot (active job). `config["minimise_to_tray"]` (opt-in) redirects `WM_DELETE_WINDOW` to hide-window. Completed transcriptions trigger `TrayController.notify(...)` so the user sees a native toast even when minimised.
- **High-DPI scaling** — `App._apply_hidpi_scaling()` reads `winfo_fpixels('1i')` at startup and computes Tk's scaling factor so fonts and paddings don't shrink to a 1 cm icon on 125 / 150 % Windows displays.
- **Anonymous opt-in telemetry** — `app/observability.py` is now gated on `config["telemetry_opt_in"]` (Advanced dialog checkbox). Sentry crash reporting requires that *and* `$SENTRY_DSN`; launch ping requires that *and* `$WHISPER_TELEMETRY_URL`. The ping carries `{os, version, python, anonymised_id}` only — `anonymised_id` is a SHA-256 of a one-shot UUID4 stored under `user_cache_dir()/telemetry_id`.
- **Auto-resume after crash** — `App._maybe_offer_crash_resume` runs on launch: if `history.db` flagged rows interrupted on the *previous* run and the source files still exist, prompts to re-enqueue them.
- **Per-folder `.whisperproject.json` overrides** — `core.config.merge_project_overrides` walks up from each transcribed file and overlays the closest `.whisperproject.json` on top of the global config. Dict-valued keys (`model`, etc.) deep-merge one level. Bad JSON / non-object roots are silently ignored.
- **Watched-folder UI wiring** — the existing `core.watcher.FolderWatcher` class is now wired through the Advanced dialog. New media files dropped into the configured folder are stability-checked (size stable for 1.2 s) then auto-enqueued via a Tk-safe `after()` hop. Stops/restarts cleanly when the user picks a new folder.
- **Windows Explorer "Transcribe with Whisper Project"** — both `installer.iss` and `installer_embed.iss` ship an optional shell-extension task (`shellext`) that writes the appropriate registry entries under `HKCR\*\shell\WhisperProjectTranscribe`. Hits the existing v0.7.0 CLI mode (`gui.py transcribe "%1"`).

### Added — Session 13 (gap-closing push)

- **Speaker diarization** via `sherpa-onnx` (no HuggingFace token). Toggle on the Transcribe tab. SRT / JSON / MD / DOCX writers all carry the speaker label. ONNX models live in `bin/diarization/` and ship with each installer.
- **In-app transcript viewer** (`Help → Open transcript viewer…`, plus "View transcript" button on the Last Result card). Segment table with type-as-you-search filter, double-click to seek, embedded `python-vlc` playback when libvlc is installed (falls back gracefully).
- **DOCX export** via `python-docx`. New binary-write path in `_write_outputs` with atomic `.part → os.replace` semantics preserved.
- **Markdown export** — stdlib only. Heading + per-segment timestamps + optional `_Speaker N:_` italics.
- **Drag-and-drop** (one or many files, or a URL) onto the window. Powered by `tkinterdnd2`; the App stays usable when the dep is missing.
- **Recent files submenu** populated from `history.db` (last 10 unique files). `File → Recent files`.
- **Window geometry persistence** — saves on exit, restores on next launch.
- **Multi-file Browse…** — selecting several files in the dialog enqueues them all.
- **Keyboard shortcuts** — `Ctrl+O` Browse, `Ctrl+Enter` Transcribe, `Esc` Cancel running, `Ctrl+Q` Exit.
- **GitHub Actions CI** (`.github/workflows/ci.yml`). Pyright + the unit suite on every push and PR. Matrix: Windows + Ubuntu, Python 3.11 + 3.12. Ubuntu wraps the pytest invocation in `xvfb-run`.

### Added

- **Session 12** — Three independent installation methods, all shipped from a single branch (`release/v0.7.0-installer-3-options`) on a single tag (`v0.7.0`):
  - **Method A — Portable** (`WhisperProject-v0.7.0-Portable.exe`, ~190 MB). PyInstaller `--onefile` build via `whisper_project_onefile.spec`. One file, no install, unpacks to `%TEMP%\_MEI*` per launch.
  - **Method B — Setup-Compact** (`WhisperProject-v0.7.0-Setup-Compact.exe`, ~137 MB). PyInstaller onedir from `whisper_project_onedir.spec` wrapped in `installer.iss` (Inno Setup 6, LZMA2 ultra). Real installer with Start Menu / desktop / Add-Remove-Programs entries.
  - **Method C — Setup-Standard** (`WhisperProject-v0.7.0-Setup-Standard.exe`, ~153 MB). Embeds a full `cpython-3.11.15+20260510-x86_64-pc-windows-msvc-install_only` distribution from [python-build-standalone](https://github.com/astral-sh/python-build-standalone), pip-installs `requirements.txt` into the bundle, copies the source tree, and wraps it via `installer_embed.iss`. Shortcuts launch `pythonw.exe gui.py`; the source is browsable on disk after install.
  - `build_embed_installer.bat` orchestrates the Method C tree.
  - All three pass `tests/smoke/test_exe_real_e2e.py::test_exe_worker_transcribes_real_video` on a clean install location with a real video, confirmed via the dual-launcher conftest fixture (`WHISPER_SMOKE_GUI` env var selects the embeddable-Python flavour).
- **Session 11** — Supreme Master TV download integration. New module `core/integrations/smtv.py` (stdlib only) scrapes any `/{lang}1/v/<id>.html` episode page for video qualities (1080p/720p/396p), the MP3 audio file, the article-text transcript, and the sibling-parts playlist; the Download tab automatically routes SMTV URLs through this module instead of yt-dlp. Sub-features:
  - **Series download.** When a multi-part episode is pasted, a "Download all parts of this series (SMTV)" checkbox appears (default ON) and enqueues one task per sibling part.
  - **MP3 audio mode.** SMTV serves real MP3 files directly; the Audio mode dropdown shows `MP3 (audio only)` and the download path skips ffmpeg entirely.
  - **Transcript persistence.** The page's article-text body is saved next to the media as `<base>.txt` (UTF-8). Auto-transcribe-after-download still runs unchanged on top, so users get two transcript surfaces — the site's editorial transcript and whisper's SRT/JSON.
  - 23 unit tests under `tests/integrations/test_smtv.py` against three HTML fixtures; 2 live-network smoke tests under `tests/smoke/test_smtv_smoke.py` (skipped offline). `docs/integrations/smtv-research.md`, `smtv-brief.md`, `smtv-acceptance.md` document the URL contract and SMTV-T1..T8 verification tokens.
- **Session 8** — `tests/smoke/` integration suite for the compiled exe. Three pytest files (`test_exe_real_e2e.py`, `test_app_headless.py`, plus a `conftest.py` with skip-guards for missing model / video / exe) and a `README.md` explaining why these tests have to live alongside the unit suite — packaging bugs are invisible from source-side. `test_exe_real_e2e.py` spawns `WhisperProject.exe --worker`, sends the actual JSON `transcribe` command, and asserts SRT + JSON land on disk; `test_app_headless.py` drives the Tk App in a withdrawn window through every service. Regression guards `test_exe_bundles_silero_vad_asset` and `test_exe_bundles_ffmpeg` lock in the Session 8 packaging fix.
- **Session 8** — `docs/SESSION_8_PACKAGING_FIX.md` documenting the silero_vad_v6.onnx packaging bug and why source-side tests didn't catch it.
- **Session 7** — `docs/architecture-diagrams.md` (Mermaid simple overview + SVG embed + pointer to prose ARCHITECTURE.md). Hyphenated filename to avoid a case-insensitive Windows clash with the existing `ARCHITECTURE.md`. The Mermaid view uses the same color palette as the SVG so the two diagrams feel related at a glance. README now links to it as the first "Project documentation" entry.
- **Session 7** — `docs/NEXT_SESSION_HANDOFF.md` — two-minute briefing for any future architect. Includes the current commit/branch/tag inventory, a 60-second orientation command list, the candidate phases ranked by impact-per-effort, the hard rules (single branch, no tokens, `bin/` ignored, Tk single-threaded, JSON protocol sacred), what's explicitly out of scope (Persian/Arabic, cloud LLMs, mobile, streaming), where to look when something feels weird, files not to touch, and a one-paragraph user prompt to start the next session.

### Fixed

- **Session 9** — `App.destroy()` now cancels every pending `tk.after()` callback before tearing down the Tcl interpreter. Previously, the service poll loops (`TranscriptionService.poll`, `FormatService.poll`, `DownloadService.poll`) reschedule themselves every tick; on shutdown those pending callbacks fired into a destroyed interpreter and spammed the log with hundreds of `invalid command name "<id>poll"` errors. Now the override iterates `tk.call("after", "info")` and calls `after_cancel` on each id before delegating to `super().destroy()`.
- **Session 9** — `core/transcriber.py:load_model_async` no longer swallows exceptions. The background-thread wrapper had a bare `except Exception: pass` that hid a real model-corruption case in the field for a whole session. Now it logs via `logger.exception` and forwards the message to `status_cb` if provided.
- **Session 9** — `core/transcriber.py:get_duration` now passes `timeout=60` and (on Windows) `creationflags=subprocess.CREATE_NO_WINDOW` to the bundled ffprobe call. A wedged ffprobe used to hang transcription indefinitely with no cancel, and the windowed exe popped a black console window for every probed file.
- **Session 9** — `messagebox.showinfo("About", ...)` now passes `parent=self` so the dialog centers on the app window instead of the screen.
- **Session 8** — `whisper_project.spec` now collects `faster_whisper`'s data files via `collect_data_files('faster_whisper')`. Without this, the compiled exe crashed the moment a user clicked **Transcribe** with VAD enabled (the default) because `silero_vad_v6.onnx` was absent from the bundle. The bug was invisible from `python gui.py` because source-side code resolves the asset from `site-packages/faster_whisper/assets/`. Only spawning the compiled `WhisperProject.exe --worker` and sending a real `transcribe` command exposed it. Now covered by the smoke suite — see Added above.
- **Session 8** — `whisper_project.spec` retains the Session 8a `contents_directory='.'` on the `EXE()` call so bundled `bin/` lands beside the exe, not inside `_internal/`. The `build.bat` xcopy fallback is no longer triggered on a clean build.

### Changed

- **Session 12** — `whisper_project.spec` renamed to `whisper_project_onefile.spec` to disambiguate from the new onedir variant. EXE `name=` field updated to `WhisperProject-v0.7.0-Portable`. `installer.iss` `OutputBaseFilename=` updated to `WhisperProject-v0.7.0-Setup-Compact`. Both .gitignore whitelist entries follow the rename.
- **Session 12** — `tests/smoke/conftest.py` and `tests/smoke/test_exe_real_e2e.py` gained dual-launcher support. The new `gui_script` fixture reads `WHISPER_SMOKE_GUI` and, when set, makes the worker subprocess launch as `[pythonw, gui.py, "--worker"]` instead of `[exe, "--worker"]` — required to verify Method C without writing a third smoke file.
- **Session 12** — `installer_embed.iss` carries a `[UninstallDelete]` block that sweeps `__pycache__` and the install subdirectories on uninstall. Inno Setup otherwise leaves Python's runtime-generated `*.pyc` files behind because they weren't recorded in the install manifest.
- **Session 12** — Repo cleanup: nine phase-acceptance plans + briefs + session writeups (PHASE_0/1/1B/2A/3A/NEXT acceptance, PHASE_1 brief, PHASE_NEXT brief, NEXT_SESSION_HANDOFF, SESSION_8_PACKAGING_FIX, SESSION_SINGLE_FILE_EXE, SESSION_DUAL_DELIVERABLE) moved into `docs/history/` to keep the active docs surface at-a-glance. README rewritten 190 → ~60 lines. BUILD.md rewritten to cover all three pipelines.
- **Session 11** — `app/services/format_service.py` and `app/services/download_service.py` now branch on SMTV URLs (`core.integrations.smtv.parse_episode_id` and a `kind: "smtv"` marker on the format dict) and bypass the yt-dlp probe / spawn entirely. No behaviour change for YouTube or any other URL.
- **Session 11** — Both PyInstaller specs (`whisper_project_onefile.spec` and `whisper_project_onedir.spec`) gain `core.integrations.smtv` in `hiddenimports` so the module survives onefile bundling and onedir-via-installer packaging.
- **Session 7** — `docs/MANUAL_STEPS.md` scrubbed: the `## A. Security` block that named two leaked GitHub PAT prefixes was removed. Sections re-lettered (B → A through H → G) so the file still reads cleanly. The Summary was rewritten to drop the "two human-required items" framing; there's now exactly one open human decision — which Phase to ship next.
- **Session 7** — `README.md` "Project documentation" footer now points at `architecture-diagrams.md` first, then the direct SVG link, then the prose ARCHITECTURE.md, so a new reader hits the visuals before the prose.

### Notes

- The leaked PAT prefixes still appear in this repo's history at commit `6d97a5f`'s diff. With the tokens revoked (which the user was asked to do; see Session 7's pending-actions note in `SESSION_LOG.md`), those strings are inert. Standard guidance for accidental-token-commit is "revoke + move on" rather than rewrite history; we followed it.

- **Session 6 research** — `docs/COMPETITIVE_ANALYSIS_2026.md` (~2900 words, ~40 cited sources). 2026 STT landscape scoped to EN + CJK + FR + DE (Persian/Arabic explicitly excluded). Covers Alibaba FunAudioLLM (SenseVoice / FunASR / CapsWriter), NVIDIA NeMo (Parakeet-TDT-0.6B-v3 / Canary-1B-v2), Whisper speedups (Insanely-Fast-Whisper / WhisperX / stable-ts / WhisperKit / Whisper-Streaming / WhisperLive / pywhispercpp), Tencent Covo-Audio, and 17 commercial products (Deepgram Nova-3, AssemblyAI Universal-3-Pro + LeMUR, ElevenLabs Scribe v2, Descript, MacWhisper 12, Apple Voice Memos iOS 18, etc.). Synthesizes 15 candidate features ranked by impact, Chinese-language gotchas (tokenization, punctuation, simplified/traditional, line-length, CPS), best-model-per-language matrix, and a five-feature Descript-style Phase 4 editor blueprint.
- **`docs/architecture.svg`** — 1500×1100 layered system diagram, color-coded by role (user / UI / core / subprocess workers / external processes / filesystem / test+build / external network). Drop shadows, dashed-for-async arrows, red "killer flow" callout for Phase 3a auto-transcribe-after-download. Renders inline on GitHub. Authored after four reflection passes.
- **`docs/ROADMAP.md`** restructured (Session 6) — new **Phase 6 — CJK polish + pluggable backends** with 8 sub-items: SenseVoice + Parakeet pluggable backends, Chinese punctuation post-processor (FunASR `ct-punc`), CJK-aware line splitting per Netflix style guide, simplified↔traditional via OpenCC, number/date normalization via cn2an, hallucination + repetition cleanup, stable-ts integration for word-perfect timestamps, sound-event tagging for SDH. Old Phase 6 (Hardening) renumbered to Phase 7 with no content loss. **Phase 4 (editor) rewritten** to drop the RTL Persian items (de-scoped — user audience is now 94% Chinese) and adopt the Descript-style blueprint: edit-back-to-subtitle with re-flowed timestamps, gap/silence panel, speaker labels with global rename, multilingual filler-word bulk operations (EN/FR/DE/ZH dictionaries) with dual caption-only vs. cut modes, CJK-aware subtitle linter.
- `README.md` documentation footer updated to point at `docs/architecture.svg` and `docs/COMPETITIVE_ANALYSIS_2026.md`.
- **Final compile** — `whisper_project.spec` (PyInstaller `--onedir`, deterministic, committed) + `build.bat` at the repo root with documented exit codes (0 success / 1 PyInstaller failure / 2 verification failure / 3 smoke launch failure). Build verifies the four required runtime files (`WhisperProject.exe` plus `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `bin/yt-dlp.exe`) and falls back to a manual `xcopy` of `bin/` if PyInstaller's `datas` silently dropped it (which it does — caught on the first build). `docs/BUILD.md` documents modes, exit codes, the `bin/` fallback, and explains why `config.json` is intentionally not in `dist/` (Phase 1.2 placed it in `%LOCALAPPDATA%`). `.gitignore` now keeps the committed `whisper_project.spec` while ignoring stray local `.spec` files.
- **Phase 3a** — yt-dlp killer features. New SQLite history DB at `%LOCALAPPDATA%\WhisperProject\history.db` with `downloads` and `transcriptions` tables, `mark_interrupted()` on startup, and a `Statistics` menu item showing download/transcription counts, total minutes, and top languages. SponsorBlock category checkboxes in the Advanced dialog (`sponsorblock_categories` config key) — when set, the categories are appended to yt-dlp via `--sponsorblock-remove`. Auto-transcribe-after-download wiring is fully active: a finished media download with `auto_transcribe_after_download=True` enqueues a `TranscriptionTask` with the captured language hint. The `--progress-template "%(progress)j"` JSON parser landed in Phase 1b is now the live progress source for download rows. Right-click history actions on both queue tabs: `Open output folder`, `Re-run`, `Remove`. 17 new unit tests (history 11, auto-transcribe wiring 6).
- **Phase 2a** — Whisper masterpiece. VAD on by default, configurable via three knobs (`vad_min_silence_ms`, `vad_threshold`, `vad_speech_pad_ms`). Word-level timestamps as an opt-in (`word_timestamps`). Language detection captured from `info.language`/`info.language_probability`, posted via a new `language_detected` worker event, and rendered in a new `language` column on the Transcription Queue tab. New `core/writers/` package — six pure writers (`srt`, `vtt`, `tsv`, `txt`, `json`, `lrc`) + a `get_writer` registry. Output formats are user-selectable from a new `Advanced...` dialog (defaults: `["srt", "json"]`). VTT emits karaoke-style `<HH:MM:SS.ms><c>word</c>` cues when words are present. `BatchedInferencePipeline` wraps the model on CUDA when available. `initial_prompt` and `hotwords` plumbing in place (UI in Phase 2b). 39 new unit tests + 4 real-audio smoke tests + 3 end-to-end tests.
- **Phase 1b** — Foundation refactor. The 1296-line `gui.py` becomes an 11-line `--worker`-aware entry point; the rest is now an `app/` package with `app.py` (Tk root, ~430 lines), `dialogs/`, `domain/`, `services/` (DownloadService, FormatService, TranscriptionService, IntegrationsService), `widgets/` (console + tab builders), and `observability.py` (env-gated Sentry). Per-instance queues replace module globals (closes AUDIT B3). `pyproject.toml` lands at the repo root with `[project.optional-dependencies]` for `dev`, `crash_reporting`, `theme_detection`. (PHASE_NEXT_BRIEF Phase 1b)
- **Phase 1b / tests** — `tests/core/` adds 71 new unit tests (config 9, model_manager 10, worker_protocol 10, subtitle_lang_args 10, download_command 20, transcriber_helpers 12). `core/` line coverage rises to 77% overall; testable modules sit at 81–92%.
- **Phase 1b / type hints** — `from __future__ import annotations` + complete type signatures across every `core/` module. `pyright core/` is clean (0 errors, 0 warnings).
- **Phase 1b / observability** — `app/observability.py` opt-in Sentry hook. Activated only when `SENTRY_DSN` env var is set. No DSN ever in code, config, or git history.
- **Phase 1b / acceptance** — `docs/PHASE_1B_ACCEPTANCE.md` with grep-able tests 1B-T1 through 1B-T7.
- `README.md` at project root — first-class entry point for new readers
- `docs/ARCHITECTURE.md` — describes the current process model, layout, key flows, and design rationale
- `docs/AUDIT.md` — full audit findings tagged critical / high / medium / low
- `docs/ROADMAP.md` — six-phase plan based on competitive analysis of nine Whisper GUI projects and eight yt-dlp GUI projects
- `docs/CHANGELOG.md` — this file
- `docs/CONFIG.md` — `config.json` field reference
- `docs/DECISIONS.md` — short ADRs for the load-bearing architectural choices
- `docs/PHASE_1_ACCEPTANCE.md` — machine-parseable test plan for Phase 1a (theme + platformdirs + logging)
- `.gitignore` — first proper gitignore for the project
- `requirements.txt` — runtime dependencies, with Phase 1/2 additions commented for later
- `Phase 0 fixes` — see "Changed" and "Fixed" below
- **Phase 1.1** — Sun Valley theme via `sv-ttk`. Selectable Light / Dark / System under `View` menu, persisted via the new `theme` config key. Transcribe tab `tk.Label`/`tk.Button`/`tk.Entry` widgets converted to `ttk` equivalents so the theme applies uniformly. (ROADMAP 1.1)
- **Phase 1.2** — `platformdirs`-backed config, cache, and log directories. `core/config.py` now exposes `user_config_dir()`, `user_cache_dir()`, `user_log_dir()`, `user_data_dir()`. New `migrate_config_location()` runs on every `load_config()` call: a legacy `config.json` next to source is copied to `%LOCALAPPDATA%\WhisperProject\config.json` and the original renamed to `.migrated.bak`. `model_path` defaults derived from `user_cache_dir()`. (ROADMAP 1.2)
- **Phase 1.3** — `core/logging_setup.py` with `setup_logging()`, `get_ui_logger()`, and `open_log_folder()`. `RotatingFileHandler` writes to `<user_log_dir>/app.log` (5 MB × 3). Both `gui.py` and `core/worker.py` call `setup_logging` at startup. Every previous `print()` outside the worker's JSON `emit()` is now a `logging.getLogger(__name__).info/warning/error` call. New `Help → Open log folder` menu item. (ROADMAP 1.3)
- **Phase 1.5** — `sv-ttk>=2.6.0` and `platformdirs>=4.0.0` promoted from "Phase 1 additions (uncomment when implementing)" to active dependencies. (ROADMAP 1.5)
- `docs/integrations/` — new home for cross-tool integration notes. Contains a `README.md` index, a research note + implementation brief for **oTranscribe** (web-based manual transcription tool). The pattern is: every integration gets a research note authored before code, a hands-off brief that drives an autonomous session, and an acceptance plan added when the work lands. Documents survive the merge — never deleted.
- `docs/integrations/otranscribe-research.md` — full schema of the `.otr` file format (plain JSON with four keys: `text` HTML, `media`, `media-source`, `media-time`), the timestamp `<span>` HTML structure, oTranscribe's import/export limitations (imports only `.otr`; exports `.otr`/`.txt`/`.md` with no SRT/VTT), keyboard shortcuts, and a three-tier integration plan (MVP converters / UI buttons / power features).
- `docs/integrations/otranscribe-brief.md` — implementation brief modeled on `docs/PHASE_1_BRIEF.md`. Three public functions (`srt_to_otr`, `whisper_json_to_otr`, `otr_to_srt`), three UI additions (Export menu item, Import button, Help → Open oTranscribe), pytest fixtures, nine grep-able acceptance tests, hands-off push policy, and the eight known traps that survived Phase 1's discovery (newlines inside `text`, NBSP after the timestamp span, no zero-padding on the hour, etc.).
- **Phase 2-oTranscribe** — bidirectional `.otr` file-format converter at `core/integrations/otranscribe.py`. Public surface: `fmt_otr_time`, `srt_to_otr`, `whisper_json_to_otr`, `otr_to_srt`. Stdlib only (`json`, `html`, `html.parser`, `re`, `pathlib`); zero new runtime deps.
- **Phase 2-oTranscribe / UI** — `Transcription Queue` right-click on a `finished` task gains `Export → oTranscribe (.otr)` (writes `<base>.otr` next to the existing `<base>.srt`). `Transcribe` tab gains an `Import .otr → SRT...` button that runs through two file pickers. `Help → Open oTranscribe...` opens the official site in the user's browser.
- **Phase 2-oTranscribe / tests** — `tests/integrations/test_otranscribe.py` with nine pytest cases (display format, ASCII round-trip, Persian round-trip, whisper-JSON conversion, NBSP boundary, single-line `text`, last-segment end inference, `media` basename only, smoke). Fixtures under `tests/integrations/fixtures/`.
- `docs/integrations/otranscribe-acceptance.md` — machine-parseable acceptance plan for the oTranscribe integration with a mandatory final JSON block.

### Fixed

- **CRITICAL**: `yt-dlp --update` no longer blocks every download. The unconditional pre-download update call previously broke offline use and any case where GitHub was rate-limiting. Update is now gated to once per launch (and only when the user opts in via `auto_update_yt_dlp` setting). Failures log and continue. (AUDIT A1)
- **CRITICAL**: `core/transcriber.py`'s `detect_device` no longer swallows `KeyboardInterrupt` and `SystemExit` via a bare `except:` (AUDIT A2)
- **CRITICAL**: `get_duration` in `core/transcriber.py` now resolves `ffprobe` from the bundled `bin/` folder instead of expecting it on `PATH` (AUDIT A3)
- **HIGH**: `current_video_language` is now only captured when the lookup result still matches the current URL — fixes wrong-language hint after rapid URL changes (AUDIT A4)
- **HIGH**: Partial subtitle files are deleted when the subtitle phase is cancelled mid-write (AUDIT A5)
- **HIGH**: `config.json` is written atomically (`.tmp` + `os.replace`) so a crash during save can no longer leave the file corrupt (AUDIT C1)
- **HIGH**: `load_config` falls back to baked-in defaults if `config.json` is missing or invalid, instead of crashing at startup (AUDIT C2)
- **CRITICAL**: `load_config` now repairs unreachable `model_path` (e.g. config referencing an unmounted drive like `X:\`) by substituting `%LOCALAPPDATA%\WhisperProject\models\<model-folder>`. Unreachable `download_folder` is cleared so the UI re-prompts. This fixes the `[WinError 3] The system cannot find the path specified: 'X:\\'` crash during model setup. (AUDIT C7, escalated from LOW after a real user hit it.)

### Changed

- `transcriber.py`'s busy-wait loop in `transcribe()` replaced with an `assert MODEL_READY` since the only call path goes through `load_existing_model` first (AUDIT B6)

---

## [0.3.0] — 2026-05-11

### Added

- Automatic subtitle download in the "Download Videos" tab — checkbox plus 30-language combo (`docs/auto-subtitles-feature.md`)
- Per-phase status indicator next to the subtitle combo
- `download_subtitles_enabled` and `download_subtitle_lang` persisted to `config.json`
- Subtitle phase explicit `--- Subtitle phase: … ---` markers in the console log
- `--write-auto-subs` AND `--write-subs` in one yt-dlp call — yt-dlp prefers manual captions when available

### Changed

- `SUBTITLE_LANGUAGES` reordered to Automatic, English, then alphabetical (was: arbitrary regional grouping)
- Multi-variant language entries collapse `zh-Hans,zh-CN`, `no,nb`, `he,iw`, `id,in`, `pt,pt-BR,pt-PT`, `es,es-419`
- Subtitle combo starts in `state="disabled"` to avoid a readonly→disabled flash on launch

### Fixed

- `--sub-langs en.*` was matching translated captions like `en-de-DE`, `en-ja`, `en-pt-BR`, downloading 7 files instead of 1. Now uses exact codes joined with commas.
- "no subtitles" detection regex now matches yt-dlp's actual output (`There are no subtitles for the requested languages` / `no automatic captions for the requested languages`) instead of the never-triggered `WARNING: There are no` pattern

---

## [0.2.0] — 2026-05-07

### Added

- Bundled `yt-dlp.exe` in `bin/` for video downloads
- "Download Videos" tab with URL input, format detection via `yt-dlp --dump-single-json`, audio-only and audio+video modes, output format selection
- Download queue with progress, cancel, remove

---

## [0.1.0] — Initial version

### Added

- Tk GUI for `faster-whisper` transcription
- Worker subprocess model with JSON event protocol
- Resumable, MD5-verified model download from a CDN mirror
- Transcription queue with cancel, pause/resume, retry
- Multiple parallel workers (`parallel_workers` config)
- SRT and JSON output next to the input file
