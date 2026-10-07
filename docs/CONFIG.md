# Configuration Reference

`configuration.json` at the repo root is the **master copy of the online
app config** — the maintainer uploads it to `config_url`
(`https://smch.ir/whisper/app_config.json`). It contains only the
`ONLINE_ALLOWED_KEYS` keys (`model_catalog`, `stats_url`, `latest_version`)
and is fetched/merged as described below. It is NOT
read by the app directly from the repo — it must be uploaded to `config_url`
for the online layer to pick it up.

`config.json` lives at `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` on Windows (`platformdirs.user_config_dir("WhisperTranscriberSuite")` on every platform). On first launch, a legacy `config.json` next to `gui.py` is copied to the new location and the original renamed to `.migrated.bak`. Subsequent launches read only from the platformdirs path.

The file is read once at startup and written when the user changes a persisted setting (download folder, subtitle preferences, theme, etc.). Manual edits take effect on next launch.

### How the file is read and saved

The desktop app, its worker processes, the HTTP server and the CLI share this one file, so
reading and saving are built to never lose a setting (`core.config`):

- **Saving writes only what changed.** `load_config()` returns a dict that remembers the values
  it was loaded with; `save_config()` writes the keys this process changed over the file as it
  is *now*, so the app's own copy (held from launch to exit) never reverts a value another
  process saved meanwhile, such as the cloud minutes a worker records. Nested objects (`model`,
  `voice_clone`) are compared field by field; lists are one value. `cfg.copy()` keeps the
  load-time values; a plain dict (`dict(cfg)`, `{**cfg}`) is written whole, as before, with a
  one-time warning in the log. Counters that several processes change go through
  `core.config.update_config(fn)`: lock, read the file, change it, write it (`fn` must not load
  or save the config itself).
- **Writes are atomic and serialised.** A temporary file is written, flushed and moved over
  `config.json`; other processes are kept out by `config.json.lock` next to it. A lock still held
  is a live writer (the OS releases the lock of a process that dies), so `save_config` waits up to
  8 s and `update_config` up to 2 s, then raises `ConfigBusyError` (a `ConfigSaveError`) and
  writes nothing. Only a lock file that cannot be opened at all (a read-only folder) lets the
  save go ahead without it, logged. The lock file is never deleted. On Windows a reader holding the file
  makes the move fail for a moment, so it is retried for up to 1 s. A save that still fails
  raises `ConfigSaveError`; **Advanced** then shows the error and stays open, and
  **File → Work offline** says so in the window.
- **A backup is kept.** Every save first copies the current, valid file to `config.json.bak`
  (through `config.json.bak.tmp`, so a cut-off copy never leaves a torn backup).
  A save that would write fewer than 40 % of the keys on disk is refused as data loss.
- **A read error is not damage.** A file that cannot be opened for a moment (another process is
  replacing it, an antivirus scan) is retried for up to 1 s, then the last copy this process
  read is used; the file is never renamed for it. A save that cannot read the file refuses to
  write blind (`ConfigSaveError`), and while no last copy exists the privacy switches read
  closed for that run (without saving that). UTF-8 with or without a BOM (PowerShell 5.1 writes
  one) is read as UTF-8. A file saved by an editor in the Windows ANSI code page
  (cp1252) is read, and the next save writes it as UTF-8; a UTF-8 file with a broken byte counts
  as damaged instead, so its non-Latin text is never turned into mojibake.
- **A damaged file falls back to its backup.** A file that is not a JSON object is copied to
  `config.json.corrupt` (only if it is still the file found damaged) and `config.json.bak` is
  written in its place, with the three privacy switches closed: the backup is the generation
  before the last save and may predate turning Work offline on. If the damaged file cannot be
  kept, it is not overwritten either and saves are refused. With no usable backup it is moved to
  `config.json.corrupt` and the app starts from the defaults, privacy switches closed. A missing
  `config.json` next to a `config.json.corrupt` that is not older than the backup (a repair cut
  short, or an older version that wrote nothing back) is restored the same way; a backup newer
  than the `.corrupt` means the file was deleted by hand after later saves, and the app starts
  fresh with the switches closed.
- **Privacy switches fail closed.** `work_offline`, `telemetry_opt_in` and `update_check_enabled`
  accept `true`/`false` (also as the words true/false, yes/no, on/off, 1/0); any other value
  reads as *offline*, *no usage statistics* and *no update check*. While a `config.json.corrupt`
  exists, a switch missing from the file reads the same way
  (the saved choice was lost), and the next save writes all three explicitly. Work offline then
  shows in the window title and the File menu, so it can be turned off again.

## Three-level merged configuration (P4-1)

The effective config is merged from **three layers**, in priority order:

1. **Local `config.json`** — the user's file (described above). **Highest priority.** A local override file is the place for expert / per-machine overrides; it may set ANY key, including the local-only ones the online layer is forbidden from touching (paths, API keys, credentials, the model hub folder, user preferences).
2. **Online app config** — a JSON the maintainer hosts at `config_url`, fetched on startup. It lets **app-level** settings change **without redistributing the program** (the model catalog, the telemetry-stats endpoint, the latest version). It is restricted to a **safe allowlist** (`stats_url`, `latest_version`, `model_catalog`) — it can **never** override user-private / local-only keys.
3. **Hard-coded `DEFAULT_CONFIG`** — the in-code baseline. **Lowest priority.**

A key missing from a higher-priority layer falls through to the next. Dict-valued keys (e.g. `model`, `model_catalog`) are deep-merged, so a partial override keeps the sibling keys from the lower layer.

The online fetch is **fail-safe**: a short timeout, the last good response cached under `user_cache_dir()/app_config_cache.json`, and a fall-through to the cache (then to nothing) when offline. It **never blocks or crashes startup**. The worker-subprocess start-up paths (`core.transcriber` import, `core.worker.main`, the faster-whisper model load) skip the fetch (`load_config(fetch_online=False)`), so a worker spawn is never delayed by the network. A worker's first transcription does fetch it once (`core.transcriber._apply_runtime_overrides` calls `load_config()`; 4 s timeout, then the cache).

The merge itself is pure and testable: `core.config.merge_config_sources(hardcoded, online, local)`. The fetch is the separate `core.config.fetch_online_config(url, cache_path=...)` helper. `core.config.load_config()` wires the two together; `load_config(fetch_online=False)` uses only the local + hard-coded layers.

| Field | Type | Default | Description |
|---|---|---|---|
| `config_url` | string | `https://smch.ir/whisper/app_config.json` (placeholder — the maintainer sets the real URL) | URL of the online app-level config JSON. Fetched best-effort on startup; cached for offline fallback. Empty disables the online layer. A hand edit in `config.json` (e.g. a staging URL, or `""`) is honoured on load and kept by every save; the app itself never writes this key (the shipped URL is not stored). |
| `model_catalog` | object | `{}` | Online/local-supplied catalog of selectable models, same shape as `core.model_manager.MODEL_REGISTRY` (`slug → {label, name, url, md5, hf_repo, approx_size_gb, info}`). `url`/`md5` may be `""` for a model with no smch.ir mirror — `ensure_model` then downloads straight from `hf_repo`. Overlaid on the built-in catalog so new models can ship without an app update. **Allowlisted** for the online layer. Never written from memory: a catalog hand-written into `config.json` is kept by every save, and the online one is not copied into the file, so a corrected online entry reaches every user. Older versions did copy it into the file; at load, a copy identical (as JSON) to a catalog a release shipped (`core.config._SHIPPED_MODEL_CATALOG_DIGESTS`) is removed once, the previous file kept as `config.json.bak`; a catalog with any edit is kept. |
| `stats_url` | string | `https://smch.ir/stats/transcription_stats.php` | Usage-stats POST endpoint. The desktop app POSTs one row here per successfully finished transcription while `telemetry_opt_in` is true, which is the default — see **Usage statistics (P4-4)** below for every field. Empty or a non-http(s) URL = no POST. **Allowlisted** for the online layer so it can be set/changed remotely; like `config_url` it is not written to `config.json`. |
| `latest_version` | string | `""` | Newest published version string (informational; complements the GitHub update check). **Allowlisted** for the online layer. |

## Where things live (Phase 1.2)

| Purpose | Path (Windows) | Helper |
|---|---|---|
| `config.json` | `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` | `core.config.config_path()` |
| Model hub (default `hub_folder`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\` | `core.hub.default_hub_folder()` |
| Cached models (default `model_path`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<model-folder>\` | `core.config.user_cache_dir()` |
| Rotating logs | `%LOCALAPPDATA%\WhisperTranscriberSuite\Logs\app.log` (5 MB × 3) | `core.config.user_log_dir()` |
| Voice-clone consent record (local only, see [below](#consent-record-local-only)) | `%LOCALAPPDATA%\WhisperTranscriberSuite\voice_clone_consent.jsonl` | `core.synthetic_audio.consent_log_path()` |
| Text to Voice speed figures (see [below](#estimate-before-a-long-text)) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\tts\speed_calibration.json` | `core.tts_plan.calibration_path()` |

`platformdirs` chooses the equivalent paths on macOS and Linux. The "Help → Open log folder" menu item opens the log directory.

## Network use

Every outbound connection the app can make. Transcription with a local engine works without a network once its model is on disk: the automatic requests below then fail quietly and the app carries on. The rows marked *automatic* happen without a click.

**Work offline** (**File → Work offline**, or the same checkbox in **Advanced → App behaviour**; `work_offline` in `config.json`) stops all of them at once: the automatic requests skip themselves, and an action that needs the internet says "Offline mode is on" and offers to turn the switch off, so nothing fails silently. The window title ends in "— Work offline" while it is on. Turning it on stops new connections; a download or install that is already running finishes, and a download waiting in the queue is refused before its next step. The online config cannot change the switch, and is not fetched while it is on. Behind the checks at each call site (`core.offline`), every process of the app (the desktop app, its transcription and voice-clone workers, the CLI and the server) refuses any other outbound TCP connection or host-name lookup that does not stay on this computer, so a library that downloads by itself fails instead of connecting. The last column says what the switch does to each row.

| What | When | Destination | What is sent | How to stop it | Blocked by Work offline |
|---|---|---|---|---|---|
| Online app config | *Automatic*: at startup of the desktop app, the CLI and the server, and on the first transcription in each worker process (once per process) | `config_url`, default `https://smch.ir/whisper/app_config.json` | A plain GET | No switch. A hand-set `"config_url": ""` in `config.json` works until the app next saves its settings (see the `config_url` row above). | Yes: not fetched in any process; the last copy fetched before (on disk) still applies. |
| Update check | *Automatic*: desktop app, a few seconds after launch, at most once a day (and once a day while it stays open); also **Help → Check for updates…** on demand | `https://api.github.com/repos/Milomilo777/whisper-transcriber-suite/releases/latest` | A plain GET | **Advanced → App behaviour → Don't check for updates** (`update_check_enabled: false`), or the environment variable `WTS_DISABLE_UPDATER=1`; the Help item still works. | Yes: no automatic check. **Help → Check for updates…** first offers to turn Work offline off. |
| Usage statistics | *Automatic*: after each successfully finished transcription in the desktop app | `stats_url`, default `https://smch.ir/stats/transcription_stats.php` | A form POST with the fields listed under **Usage statistics (P4-4)** | Untick **Help → Send usage statistics** or the same checkbox in **Advanced → App behaviour** (`telemetry_opt_in: false`). | Yes: nothing is posted. |
| Whisper model download | First transcription with a model that is not on disk (also after switching models) | The `smch.ir` mirror (zip + MD5 manifest) for `large-v3`, `large-v3-turbo`, `distil-large-v3.5` and `medium`; Hugging Face (`huggingface.co` and its download CDN) for every other model and as the fallback | GETs | Runs while the model is missing, or after the model check below finds a changed or missing file. | Yes: a missing model is not downloaded and the transcription fails with "Offline mode is on: downloading the model … needs the internet". A model already on disk is used. |
| Model check | When `core.model_manager.ensure_model` runs for one of the four mirror models above while it is already on disk — when the Web / LAN server starts (`gui.py serve` or the **Web / LAN access** tab), and in the model dialog shown after an installed model failed to load. A normal desktop, CLI or Live transcription loads an on-disk model without this check. | The model's `.md5` manifest on `smch.ir` | A plain GET; the local files are hashed and compared with it. If a file is missing or differs, the model folder is deleted and the whole model downloads again (row above). | No switch. A failed request is ignored and the model is used as-is. | Yes: skipped; the model on disk is used as it is. |
| Other models | First use of the feature: whisper.cpp engine, local AI Layer model, Kokoro text-to-voice, OmniVoice voice cloning, NVIDIA Parakeet, stable-ts word alignment, Demucs vocal separation | `huggingface.co` (whisper.cpp `ggml` model, Qwen2.5 GGUF, OmniVoice and Parakeet weights); `github.com` release assets (Kokoro); `openaipublic.azureedge.net` (the OpenAI Whisper checkpoint stable-ts aligns with); Demucs fetches its own weights | GETs | Only runs while that model is missing. | Yes: the app's own downloads (whisper.cpp, AI Layer, Kokoro) stop with the offline message. The libraries that fetch weights themselves (OmniVoice, Parakeet, stable-ts) are stopped by the network guard below, and Demucs gets a closed proxy, so only weights already on disk load. |
| Optional components | First use of a feature whose Python packages are not bundled (`core.optional_deps.FEATURES`). stable-ts alignment asks first; the NVIDIA Parakeet and Google Cloud engines install when a job starts with them selected (Google Cloud also from its connection test in the Advanced dialog, see **Cloud engines**); voice cloning installs on its first use; the CUDA runtime from the Hardware wizard's button | PyPI (`pypi.org`, `files.pythonhosted.org`) via `pip install` | Standard pip requests | Do not select those engines or features; nothing installs while they stay unused. | Yes: nothing is installed; the log names the switch. |
| Video downloads, captions | When the user downloads a URL or fetches its captions | The site of the URL and its media servers (YouTube: `www.youtube.com` plus `*.googlevideo.com`), or any other site yt-dlp supports | yt-dlp's requests to that site; a link pasted in **Download Videos** is looked up at once (formats, title, captions) | User action. | Yes: a pasted link is not looked up, **Download** and **Use captions instead** first offer to turn Work offline off, and a download queued earlier is refused. |
| yt-dlp update | **Update it** on the "video downloader may be out of date" bar, offered after a download or a format lookup fails with HTTP 403, a signature or an extractor error; or *automatic* before a download, at most once every 24 h, when **Advanced → Downloads (yt-dlp)** is set to "Keep it up to date automatically" (`yt_dlp_update_mode: "auto"`). Never while a download runs. Not in the macOS app (its yt-dlp is a folder build, which cannot update itself). | yt-dlp's own updater: `https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest`, then downloads from `https://github.com/yt-dlp/yt-dlp/releases/` (`_update_spec`, `SHA2-256SUMS` and the yt-dlp binary, about 18 MB; GitHub redirects them to its file host) | GETs | **Advanced → Downloads (yt-dlp) → Never update it** (`yt_dlp_update_mode: "never"`). With "Ask me" (the default) nothing is fetched until **Update it** is clicked. | Yes: no automatic update; **Update it** first offers to turn Work offline off. |
| YouTube JavaScript helper (Deno) | When the user clicks **Install YouTube helper** (shown for a YouTube link when no Deno is found) | `https://github.com/denoland/deno/releases/latest/download/` (archive + `.sha256sum`) | GETs | User action. | Yes: **Install YouTube helper** first offers to turn Work offline off. |
| SMTV integration | When the user opens the SMTV tab (it loads the listing and thumbnails) or downloads from it | `suprememastertv.com` and its video CDN | GETs | User action. | Yes: no listing, thumbnail or episode is fetched; the tab shows the offline message. |
| Cloud engines | A job started with a cloud engine selected in **Advanced → Backend**, and the Gemini **Test key** button. The Google Cloud connection test (it also runs by itself when the Advanced dialog opens with that engine selected and a key file set) only reads the key file and builds the client; its one network use is the library install under **Optional components** | Gemini: `generativelanguage.googleapis.com`. Google Cloud Speech-to-Text: `speech.googleapis.com` (or `<region>-speech.googleapis.com`), `oauth2.googleapis.com` for the service-account sign-in, plus Cloud Storage in batch mode | Jobs: **the audio**. Every request: the API key / service-account credentials | Pick a local engine (the default). | Yes: a job with a cloud engine fails with the offline message before any audio is sent; **Test key** says the same. |
| Remote AI provider | Only when the AI Layer is on (`ai_enabled`) and `llm_provider` is `remote` | `llm_remote_base_url` (default `https://api.openai.com/v1`) | **Transcript text** in the prompt, with `llm_remote_api_key` | Keep `llm_provider: "local"` (the default) or leave the AI Layer off (the default). | Yes, unless `llm_remote_base_url` is on this computer (a local Ollama or LM Studio): each request fails with the offline message, and a bilingual translation stops at the first one. |
| Web / LAN server | Only while the server runs (`gui.py serve` or the **Web / LAN access** tab) | Inbound: loopback by default, the LAN when sharing is on. Outbound: the URLs clients submit, and the webhook URL when set (`server_webhook_url`, or `serve --webhook`) | Webhook: a small JSON job summary | Stop the server; leave the webhook unset (the default). | Outbound only: link jobs are refused (HTTP 400, also one queued earlier) and no webhook is sent. The server still answers clients on this computer, and on the LAN while sharing is on. |
| Launch ping, Sentry | Only when `$WHISPER_TELEMETRY_URL` / `$SENTRY_DSN` are set (published builds set neither) and `telemetry_opt_in` is on | The URL / DSN in those variables | See **Launch ping and crash reports** | Leave the variables unset. | Yes: neither starts. |

Two features use packages the app never installs: semantic search (`core.search`, needs `sentence-transformers`) and voiceprint speaker matching (`core.voiceprint`, needs `pyannote.audio`). When a user has installed those packages by hand, their models (`all-MiniLM-L6-v2`, `pyannote/embedding`) download from Hugging Face on first use.

Opening a link (Help menu, About dialog, release page) hands the URL to the system browser; the app itself sends nothing for it. Work offline does not stop the browser.

## Field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | object | (see below) | The active model's source and verification info |
| `model.name` | string | `"faster-whisper-large-v3"` | Display name in logs |
| `model.url` | string | `https://smch.ir/models/...zip` | ZIP archive of the model |
| `model.md5` | string | `<url>.md5` | URL of the per-file MD5 manifest |
| `whisper_model` | string | `"large-v3"` | Slug of the selected model in the merged catalog (built-in `MODEL_REGISTRY` + online `model_catalog`). Set by the **Advanced > Whisper model** combo, which also rewrites `model` + `model_path` so the new model downloads on the next transcription. See the Models section below. |
| `hub_folder` | string | `""` (first-run dialog) | Parent folder that holds the `models--Vendor--name` model directories. Empty triggers the first-run picker, which pre-fills `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models` — a per-user, always-writable location (never the Program Files install dir). **Finish** in the quick start window sets this default without showing the picker. |
| `quick_start_enabled` | bool | `true` | Shows the quick start window (`app/dialogs/quick_start.py`) on the first launch of a new install: main spoken language, "Fast" or "Best quality", and the folder for downloaded videos and audio (`download_folder`; transcripts are saved next to their source file). The model comes from `core/language_defaults.py`; the size and time per minute of audio shown are estimates (`core.hardware.estimate_seconds_per_audio_minute`: the benchmark's CPU speed, or faster-whisper's published GPU figure when the model fits in the GPU's memory). The window makes no network call; the model downloads on the first transcription. `false` turns the window off. **No UI control.** |
| `quick_start_done` | bool | `false` | Set by **Skip**, **Finish** or closing the quick start window, so it shows only once. A `config.json` written by an older version (no such key) counts as done, and so does an unreadable one (renamed to `config.json.corrupt`), so existing installs never see the window; a deleted `config.json` or `--safe-mode` starts fresh. **Skip** changes nothing else and the first-run model-folder picker follows, as before. |
| `model_path` | string | (derived from `hub_folder`) | Absolute path where the model is extracted. When empty it is derived at startup from `hub_folder + model.name`; with no hub set it falls back to `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<name>`. A non-empty value is a per-model override. |
| `device` | string | `"auto"` | `"auto"` / `"cuda"` / `"cpu"`. With `"auto"`, the autodetect only selects CUDA when ctranslate2 reports a GPU **and** the CUDA runtime library it needs actually loads (cuBLAS for CUDA 12; CTranslate2 before 4.6.3 also needed cuDNN) — found on the system path, in NVIDIA's pip wheels (`nvidia-cublas-cu12`, which Advanced › Re-detect hardware can install), a CUDA Toolkit, or a CUDA PyTorch; otherwise it falls back to CPU. At model-load time a CUDA load — or its one-pass GPU warm-up — that still fails self-heals to CPU `int8` instead of crashing the worker — the active tab shows a GPU/CPU badge and (once) a "running on CPU (slower)" warning. |
| `compute_type` | string | `"int8"` | `faster-whisper` compute type. Common values: `int8`, `int8_float16`, `float16`, `float32`. `int8` is the smallest/fastest on CPU; `float16` is preferred on GPU. |
| `cpu_warning_shown` | bool | `false` | Set to `true` after the one-time "running on CPU (slower)" warning has been shown, so it never repeats. The warning only appears when a GPU was detected-but-unusable or a CUDA→CPU downgrade happened — never on a genuine CPU-only machine. |
| `parallel_workers` | int | `2` | Maximum simultaneous transcription worker subprocesses. Each loads the model and uses ~3 GB RAM (or VRAM on GPU). |
| `download_folder` | string | `""` | Default destination for video downloads. Updated by the Folder Browse button and by **Finish** in the quick start window (which pre-fills the user's Downloads folder). |
| `download_subtitles_enabled` | bool | `false` | Last state of the subtitle checkbox on the Download Videos tab |
| `download_subtitle_lang` | string | `"Automatic"` | Last-selected subtitle language (display name from `SUBTITLE_LANGUAGES`, not the code). |
| `download_caption_choice` | string | `"ask"` | What a download does when "Transcribe after download" is on and the video already has subtitles in the chosen language: `"ask"` shows the question "Use the existing subtitles or transcribe?", `"captions"` always fetches only the subtitles, `"transcribe"` always downloads and transcribes. The question's "Don't ask again" sets it; Advanced → Downloads changes it back. |
| `theme` | string | `"light"` | `"light"` / `"dark"` / `"system"` — applied via `sv_ttk` (Phase 1.1). `"system"` falls back to `"dark"` if the optional `darkdetect` package is not installed. |
| `log_level` | string | `"INFO"` | Python logging level for the file handler (Phase 1.3) |
| `yt_dlp_update_mode` | string | `"ask"` | How the video downloader (yt-dlp) stays current (`core.yt_dlp_update`; **Advanced → Downloads (yt-dlp)**). `"ask"`: a download or format lookup that fails with HTTP 403, a signature or an extractor error shows a bar with **Update it**. `"auto"`: also updates before a download, at most once every 24 h. `"never"`: no bar and no update. An update runs yt-dlp's own `--update-to stable` on a copy in `<user cache>/tools/yt-dlp/` (first copied from the bundled binary; yt-dlp checks the download against the release's `SHA2-256SUMS`), never on the bundled binary and never while a download runs; the app then runs whichever of the two copies is newer, recorded in `tools/yt-dlp/state.json`. Not available in the macOS app (its yt-dlp is a folder build, which yt-dlp cannot update) or without a bundled binary. A config with the older `auto_update_yt_dlp: true` loads as `"auto"`; that key is no longer written. Local only. |
| `last_yt_dlp_update_check` | string (ISO date) | `""` | UTC timestamp of the last automatic update check that ran to its end; `"auto"` waits 24 h after it. A timeout or a skipped check (a download was running) is not stamped. Local only. |
| `subtitle_edit_path` | string | `""` | **Advanced → App behaviour → Subtitle Edit program** (Windows only, `core.subtitle_edit`). Path to `SubtitleEdit.exe` (or its folder) for the **Open in Subtitle Edit** button on the Last Result card and in the transcript viewer. Empty = look for an installed copy: the uninstall registry entries, then `Program Files`; no disk search and no network. The button opens the best subtitle file written (SRT, then VTT, ASS, SSA, LRC). Local only: the online config can never set it (`core.config.LOCAL_ONLY_KEYS`). |
| `work_offline` | bool | `false` | **Work offline** (`core.offline`; **File → Work offline** and **Advanced → App behaviour**, kept in sync). `true` = the app makes no network connection: see the last column of **Network use** above for each request. Every process reads it from this file, so a change reaches a running transcription worker at its next network use. Local only: the online config can neither set nor clear it. |
| `update_check_enabled` | bool | `true` | GitHub "update available" check (`core.updates`), on by default; the choice in **Advanced → App behaviour** ("Tell me when a new version is available" / "Don't check for updates"). When on, a quiet launch check runs at most once per day (throttled by `last_update_check`) and stays SILENT unless a newer release exists — never nagging when up to date, offline, when the repo is private (a 404 is swallowed), or while the release has no file for this kind of install yet. A newer release shows a bar under the menu, at most once per launch and without taking focus: **What's new** (the release headline and first three highlights), **Download** (the installer, Portable ZIP or Mac dmg matching this copy; a source checkout gets its update command; anything else the release page), **Later** and **Skip this version**. It is **notify-only**: it never auto-downloads or auto-installs. `false` (or the environment variable `WTS_DISABLE_UPDATER=1`) turns off the quiet check and the Help-menu dot; **Help → Check for updates...** still runs on demand. Local only: the online config cannot set it. |
| `last_update_check` | string (ISO date) | `""` | Date (`YYYY-MM-DD`) of the last *quiet* update check, used only for the once-per-day throttle. The manual **Help → Check for updates...** menu item ignores it. Local only. |
| `update_latest_seen` | string | `""` | Latest release the last check found (e.g. `1.9.4`). Another version (a newer one, or an older one after a release was withdrawn) restarts the **Later** ladder. While it is newer than the running app and not skipped, "Help" and "Check for updates..." carry a dot and the About window names it. Local only. |
| `update_skipped_version` | string | `""` | Version the user chose **Skip this version** for. That version (and anything older) shows no bar and no dot; a newer release does. A manual check offers to stop skipping. Local only. |
| `update_snooze_count` | int | `0` | How often **Later** was clicked for `update_latest_seen`. The 1st, 2nd and 3rd hide the bar for 3, 7 and 14 days; after the 4th only the Help-menu dot and the About line remain. Local only. |
| `update_snooze_until` | string (ISO date) | `""` | Day the bar may come back after a **Later**. A date more than 14 days ahead (a wrong clock) is ignored. Local only. |
| `star_first_run` | string (ISO date) | `""` | Day of the first launch that saw this key; the star invitation (`core.star_invite`) waits 7 days after it. A missing, unreadable or future date is replaced by today. Local only; never sent. |
| `star_success_count` | int | `0` | Successful transcription jobs (not the sample clip, not errors or cancels). The star invitation needs 5. Local only; never sent. |
| `star_invites_shown` | int | `0` | How often the quiet "Enjoying it? A star on GitHub helps other people find it." bar was shown. At most 2 ever, and the second at least 30 days after the first. Local only; never sent. |
| `star_last_invite` | string (ISO date) | `""` | Day the bar was last shown. Local only; never sent. |
| `star_dont_ask` | bool | `false` | `true` after **Don't ask again** or **Open GitHub page**: the bar never comes back. The bar also stays away while a job runs or waits and in Work offline mode. Local only; the online config can never set or clear any `star_*` key. |
| `denoise_enabled` | bool | `false` | Adaptive audio denoise pre-process (`core.denoise`, **Advanced > Silence & noise**). Uses the bundled ffmpeg only — no extra dependency, no download, works offline. Off by default because it costs one measurement pass plus one filter pass per file. When on, the audio is measured first and **left completely untouched if it already measures clean**, and the filtered result is re-measured and discarded if it removed speech instead of noise. See [DENOISE.md](DENOISE.md). |
| `denoise_level` | string | `"auto"` | `"auto"` / `"light"` / `"medium"` / `"strong"`. `auto` picks the level (including `off`) from the measured speech-to-noise ratio. Naming a level forces it regardless of the measurement — it is then applied even to clean audio. Unknown values fall back to `auto` with a logged warning. |
| `denoise_cache_mb` | int | `1024` | Byte budget (MB) for the denoised-render cache under `user_cache_dir()/denoise`; oldest renders are evicted past it. `0` disables eviction. Renders are 16 kHz mono WAV (~1.9 MB per minute of audio). |
| `ai_enabled` | bool | `false` | Master on/off for the AI Layer (**Advanced > AI Layer**) — summarise/action-items/ask/translate in the transcript viewer's AI Tools tab, and LLM-generated auto-chapter titles. Gates both providers below; `llm_provider` picks which one actually runs. |
| `ai_model_path` | string | `""` | Override path for the local provider's model file. Empty uses the default `user_cache_dir()/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf`. |
| `llm_provider` | string | `"local"` | `"local"` (the bundled, download-on-first-use Qwen2.5-1.5B via `core.llm.LLMRunner`) or `"remote"` (`core.llm.RemoteLLMRunner`, an OpenAI-compatible `/chat/completions` endpoint configured via the three keys below). See [`core/llm.py`](../core/llm.py). |
| `llm_remote_base_url` | string | `"https://api.openai.com/v1"` | Base URL for the remote provider. Works with the real OpenAI API, or any self-hosted/proxy server that speaks the same API shape (Ollama, LM Studio, vLLM, OpenRouter, ...). |
| `llm_remote_api_key` | string | `""` | API key sent as `Authorization: Bearer <key>`. Stored in CLEARTEXT, consistent with `cloud_stt_api_key` / `gcloud_stt_credentials_json` / `server_token` above — `config.json` is per-user and not encrypted. May be left blank for a local server that doesn't require one. |
| `llm_remote_model` | string | `""` | Exact model id the remote endpoint expects (e.g. `gpt-4o-mini`). Deliberately has **no** default — the app never picks a specific paid model on the user's behalf; the Advanced dialog's help text shows examples. |
| `alignment` | string | `"none"` | `"none"` or `"stable_ts"`. `stable_ts` re-aligns every word's start/end against the audio (±50 ms) after transcribing — sharper karaoke-style timing, ~10-30% slower, and it needs the optional ~700 MB `stable-ts` component (offered on the first transcription with it on). Set by **Advanced > Model & engine > "Refine word timings with stable-ts"**. |
| `batch_size` | int | `16` | Chunks per GPU batch for faster-whisper's batched pipeline (CUDA only; CPU runs ignore it). **No UI control** — edit `config.json` directly. Lower it if a large model runs out of VRAM. Advanced settings' "Restore transcription defaults" resets it to `16`. |
| `output_filename_template` | string | `"{base}.{ext}"` | Pattern for every written transcript file. Tokens: `{base}` `{ext}` `{lang}` `{date}` `{speaker_count}`; a template may include sibling subdirectories (`transcripts/{base}.{ext}`), which are created on the fly. Malformed templates fall back to `{base}.{ext}`, and path traversal is rejected. **No UI control** — edit `config.json` directly. |
| `vad_window_s` | number | `30` | Long-file VAD fix (`core.vad_window`). faster-whisper runs the Silero VAD over the whole file in one pass, carrying the model's state from the first second to the last; after long loud music that state can stay at "not speech" for minutes, so later speech is skipped and shows up as minutes-long one-word segments. With this set, the speech probabilities are computed with a fresh state every N seconds (the speech/silence decision still runs over the whole file, so speech crossing a window edge is not cut). Files shorter than one window are unaffected. `0` = the old single pass. Needs faster-whisper 1.1+ (on 1.0 the VAD is left as it is). **No UI control.** |
| `loop_guard_repeats` | int | `3` | Repetition-loop guard (`core.loop_guard`). When this many consecutive segments have the same text (letters and digits compared, case-insensitive), the first is kept and decoding restarts from the second without the previous text as a prompt (once per file; the GPU batched pipeline only drops repeats); later runs are dropped down to one line. A line that is really said three or more times in a row (a chant, a chorus) is therefore kept once. The log names each event and counts them. Values below `2` switch it off. **No UI control.** |
| `translate_to_english` | bool | `false` | **Transcribe tab → Output: English translation** (`core.translate_task`). `true` = each file queued from the tab uses Whisper's own translate task, so non-English speech comes out as English text in one pass, with no extra AI model. The output files are named `name.en-translated.srt` (and so on), the history row records `task = translate`, and a resumed job keeps the task its checkpoint was started with. Only the Faster-Whisper engine with a multilingual model can do it: the checkbox is greyed out (reason on hover) for the other engines, for `large-v3-turbo` (the OpenAI Whisper README: "The `turbo` model is not trained for translation tasks") and for English-only models (`.en`, `distil-*`); a job that reaches the worker with such a combination fails with a clear message instead of returning untranslated text. Stable-ts word alignment is skipped for a translated run. |

Related: `core.config.NOISY_AUDIO_PRESET` is not a config key itself — it's a named bundle of `vad_enabled`/`vad_threshold`/`denoise_enabled`/`denoise_level`/`hallucination_detect_enabled` values that the Advanced dialog's "Apply noisy-audio preset" button (Silence & noise section) writes into the fields above in one click.

Two keys above are deliberately config-only: `batch_size` and `output_filename_template` had Advanced-dialog controls until 2026-09-12, when they were removed as jargon most users never touch (see `docs/CHANGELOG.md`). Both still work exactly as documented here.

### Models (config-driven catalog, P4-2)

The selectable model list shown in **Advanced > Whisper model** comes from the **merged catalog**: the built-in `core.model_manager.MODEL_REGISTRY` overlaid with the `model_catalog` key from the merged config (so the online config can add or re-point models without an app update). Read it via `core.model_manager.catalog_models(config)`, `catalog_resolve_entry(config, slug)`, and `catalog_entry_info(config, slug)` (label/description/size for the "?" info button).

`large-v3` is the **default** (best accuracy, slower). Built-in entries — the full Systran `faster-whisper` family plus the Large v3 Turbo variants:

| Slug | `model.name` | HF repo | Notes |
|---|---|---|---|
| `tiny.en` / `tiny` | `faster-whisper-tiny[.en]` | `Systran/faster-whisper-tiny[.en]` | Fastest, lowest accuracy, ~0.075 GB. |
| `base.en` / `base` | `faster-whisper-base[.en]` | `Systran/faster-whisper-base[.en]` | Very fast, low accuracy, ~0.145 GB. |
| `small.en` / `small` | `faster-whisper-small[.en]` | `Systran/faster-whisper-small[.en]` | Fast, moderate accuracy, ~0.5 GB. |
| `medium.en` / `medium` | `faster-whisper-medium[.en]` | `Systran/faster-whisper-medium[.en]` | Slower, good accuracy, ~1.5 GB. `medium` (no `.en`) has an smch.ir mirror; `medium.en` downloads from `hf_repo`. |
| `large-v1` / `large-v2` / `large-v3` | `faster-whisper-large-v1/v2/v3` | `Systran/faster-whisper-large-v1/v2/v3` | ~3 GB. `large-v3` is the **default** and has an smch.ir mirror; v1/v2 download from `hf_repo`. |
| `distil-small.en` | `faster-distil-whisper-small.en` | `Systran/faster-distil-whisper-small.en` | Fast, English-only, ~0.4 GB. |
| `distil-medium.en` | `faster-distil-whisper-medium.en` | `Systran/faster-distil-whisper-medium.en` | Fast, English-only, ~0.8 GB. |
| `distil-large-v2` / `distil-large-v3` | `faster-distil-whisper-large-v2/v3` | `Systran/faster-distil-whisper-large-v2/v3` | Fast, English-only, ~1.5 GB. |
| `distil-large-v3.5` | `faster-distil-whisper-large-v3.5` | `distil-whisper/distil-large-v3.5-ct2` | Fastest English-only, ~1.5 GB. Has an smch.ir mirror. |
| `large-v3-turbo` | `faster-whisper-large-v3-turbo` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | ~5× faster, similar accuracy, ~1.6 GB. Has an smch.ir mirror. |
| `deepdml-large-v3-turbo` | `faster-whisper-large-v3-turbo-deepdml` | `deepdml/faster-whisper-large-v3-turbo-ct2` | Community CT2 conversion of Large v3 Turbo, multilingual, ~1.6 GB. |

Only `large-v3`, `large-v3-turbo`, `distil-large-v3.5`, and `medium` have an smch.ir mirror (`url`/`md5` non-empty). Every other entry has `url=""`/`md5=""` and `ensure_model` downloads it straight from `hf_repo` via `_download_via_huggingface` — the mirror attempt is skipped entirely for those.

A bigger/denser model is slower — `large-v3` stays the default; the combo just lets the user pick. Switching the model triggers `ensure_model` for the new slug on the next load. The "?" button next to the picker shows the selected model's description and approximate size (`catalog_entry_info`).

### HuggingFace fallback resolution (`hf_repo`)

Every registry/catalog entry carries an explicit `hf_repo` (`Org/Repo`), which `_hf_model_ref` prefers over faster-whisper's own short-id map or a guess parsed from the mirror zip name. This makes the fallback deterministic and correctly disambiguates models that would otherwise collide on the same faster-whisper short id — e.g. `deepdml-large-v3-turbo` and `large-v3-turbo` both map to faster-whisper's `large-v3-turbo` short id, but live under different HF orgs (`deepdml/...` vs `mobiuslabsgmbh/...`); `hf_repo` picks the right one for each.

To add a model from the **online** config (no app update), put it under `model_catalog` in the hosted JSON (`configuration.json` at the repo root is the master copy):

```json
{
  "model_catalog": {
    "my-new-model": {
      "label": "My New Model (~2 GB)",
      "name": "faster-whisper-my-new-model",
      "hf_repo": "SomeOrg/faster-whisper-my-new-model",
      "url": "",
      "md5": "",
      "approx_size_gb": 2.0,
      "info": "~2 GB. One or two lines describing speed/accuracy/language coverage."
    }
  }
}
```

Changing the catalog in `configuration.json` also means adding its digest to `core.config._SHIPPED_MODEL_CATALOG_DIGESTS` (`tests/core/test_config_catalog_cleanup.py` checks it): older versions still in use copy the hosted catalog into `config.json`, and the digest lets the cleanup recognise that copy as unedited.

A malformed catalog entry (missing/empty `name`, or with no `url` AND no `hf_repo`, or not a dict) is skipped so a bad online payload never breaks the picker — the built-ins always survive.

### Keys of removed features

`tiling_*` (the Video Tiling tab and engine) and `ffplay_downloads` came from earlier versions.
A settings file that still holds them loads normally; the next save drops them
(`core.config._NON_PERSISTED_KEYS`).

### Cloud Speech-to-Text (optional, Google Gemini API)

Off by default. These keys only take effect when `transcribe_backend` is
set to `cloud_stt` (in **Advanced > Backend**). Selecting this backend
**uploads your audio to Google** — it breaks the offline guarantee. See
[`CLOUD_STT.md`](CLOUD_STT.md) for the full setup, privacy, and quota
notes. The API key is stored in **cleartext** in `config.json`,
consistent with how cookies/paths are already stored (the file is
per-user under `%LOCALAPPDATA%\WhisperTranscriberSuite` and is not encrypted).

| Field | Type | Default | Description |
|---|---|---|---|
| `cloud_stt_api_key` | string | `""` | Google API key pasted from aistudio.google.com. Empty = the backend reports "No Google API key set". Stored in cleartext. |
| `cloud_stt_model` | string | `"gemini-3.5-flash"` | The Gemini model used for transcription. A config value so a renamed/newer model needs no code change; an unavailable model surfaces a clear "model not found" error (HTTP 404), not a crash. |
| `cloud_stt_minutes_used` | float | `0.0` | Minutes of audio transcribed via the cloud backend so far, accumulated **locally** after each successful run. The dollar free-credit balance is NOT readable from an API key, so this local counter is the only usage signal shown. |
| `cloud_stt_free_minutes_cap` | int | `60` | Informational free-tier figure shown in the Advanced dialog. Not enforced — it does not block transcription. |
| `cloud_stt_chunk_seconds` | int | `480` | Window size (seconds, ~8 min) the audio is split into before upload. Smaller windows give finer progress/cancel granularity and smaller uploads; larger windows mean fewer requests. |

### Google Cloud Speech-to-Text (optional, service-account)

A second, more capable cloud option, selected by setting
`transcribe_backend` to `google_cloud_stt` (in **Advanced > Backend** —
labelled "Google Cloud Speech-to-Text"). Unlike the Gemini backend above,
it authenticates with a **service-account JSON key file** (not a pasted
API key) and uses the official `google-cloud-speech` **v2** client, which
is installed **on demand on first use** (it is not bundled). Like every
cloud option it **uploads your audio to Google** and breaks the offline
guarantee. Full setup, the Standard-vs-Batch trade-off, and the honest
usage note are in [`CLOUD_STT_GOOGLE.md`](CLOUD_STT_GOOGLE.md).

| Field | Type | Default | Description |
|---|---|---|---|
| `gcloud_stt_credentials_json` | string | `""` | Absolute path to the service-account JSON key file downloaded from the Google Cloud console. Empty = the backend reports a clear "pick your JSON file" error. The `project_id` is read out of this file. |
| `gcloud_stt_model` | string | `"chirp_2"` | The v2 recognizer model. `"chirp_2"` is the default — it supports language auto-detect and multilingual input (the older `"long"` rejected `"auto"`). `"long"` / `"short"` / `"telephony"` are also valid. A config value so a renamed/newer model needs no code change; an unavailable model surfaces a clear error, not a crash. |
| `gcloud_stt_location` | string | `"us-central1"` | API location/region. `"us-central1"` is the default region that hosts `chirp_2`; `"global"` works for the common older models and some newer models are region-only (e.g. `"europe-west4"`), in which case the backend talks to that regional endpoint. |
| `gcloud_stt_batch_mode` | bool | `false` | `false` = **Standard / online** chunked-inline `recognize()` (~$0.016/min, no bucket needed — the default). `true` = the cheaper GCS **Batch** path (`BatchRecognize`, ~$0.004/min, ~75 % cheaper) at the cost of up to ~24 h turnaround. Batch **requires** `gcloud_stt_bucket`. |
| `gcloud_stt_bucket` | string | `""` | A Google Cloud Storage bucket name the service account can write to (the `gs://` target). Required **only** for batch mode — the decoded audio is uploaded there, transcribed, then the blob is deleted. The service account needs **Storage Object Admin** on it. |
| `gcloud_stt_diarization` | bool | `false` | Enable speaker diarization (adds a per-segment `speaker` label). |
| `gcloud_stt_min_speakers` | int | `0` | Lower bound on the diarized speaker count. `0` = let Google decide. |
| `gcloud_stt_max_speakers` | int | `0` | Upper bound on the diarized speaker count. `0` = let Google decide. |
| `gcloud_stt_chunk_seconds` | int | `55` | Standard-mode chunk length (seconds). Kept under the ~1-minute online-`recognize()` inline cap; each chunk's timestamps are offset and stitched back into one timeline. |
| `gcloud_stt_batch_timeout_s` | int | `3600` | How long (seconds) to wait on the batch long-running operation before giving up. Batch turnaround can be long; raise this if a large job times out. |
| `gcloud_stt_minutes_used` | float | `0.0` | Minutes of audio transcribed via this backend **this calendar month**, accumulated locally after each successful run. Resets when `gcloud_stt_minutes_month` rolls over. The real $300-credit balance is NOT readable from a service-account key, so this local counter (and its cost estimate) is the only usage signal shown. |
| `gcloud_stt_minutes_month` | string | `""` | The `"YYYY-MM"` marker for the month `gcloud_stt_minutes_used` belongs to. When the current month differs, the counter resets to 0 before the run is added. |
| `gcloud_stt_free_minutes_cap` | int | `60` | Informational free-tier figure (60 min/month) shown in the live usage display. Not enforced — it does not block transcription. |

### NVIDIA Parakeet / FastConformer — local (optional)

A local, **fully offline** engine, selected by setting `transcribe_backend`
to `nvidia_asr` (in **Advanced > Backend** — labelled "NVIDIA Parakeet TDT
v3 — local"). It runs a Hugging Face **transformers**
`automatic-speech-recognition` model entirely on this machine (no audio
leaves the device). The default is NVIDIA's transformers-native multilingual
FastConformer model `nvidia/parakeet-tdt-0.6b-v3`; you can point it at any
transformers ASR model id or a local directory.

The heavy libraries (`transformers` + `torch` + `librosa`) and the model
weights are **not bundled** — they install / download on first use (a few GB,
one time), like the other on-demand components (see **Network use**).

> NVIDIA's exact `nemotron-3.5-asr-streaming-0.6b` repo ships only a NeMo
> `.nemo` checkpoint (no transformers weights), so the transformers pipeline
> cannot load it — that precise model needs the heavy NeMo toolkit.
> `parakeet-tdt-0.6b-v3` is its transformers-native FastConformer sibling and
> is the default here. Some models (this one in current transformers
> included) return text only, not per-word timestamps; in that case the engine
> emits one segment per window, so a smaller `nvidia_asr_chunk_seconds` gives
> finer subtitles.

| Field | Type | Default | Description |
|---|---|---|---|
| `nvidia_asr_model_id` | string | `"nvidia/parakeet-tdt-0.6b-v3"` | Hugging Face repo id OR a local directory of a transformers `automatic-speech-recognition` model. Empty = the default. |
| `nvidia_asr_device` | string | `"auto"` | `"auto"` (CUDA if available, else CPU), or force `"cpu"` / `"cuda"` / `"cuda:1"`. |
| `nvidia_asr_dtype` | string | `"auto"` | `"auto"` (float16 on CUDA, float32 on CPU), or force `"float32"` / `"float16"`. |
| `nvidia_asr_chunk_seconds` | int | `30` | Audio window length (seconds) per inference; also the segment granularity when the model returns text-only. The file is sliced into back-to-back windows whose timestamps are offset and stitched into one timeline. |

### Clone Your Voice / Text to Voice (optional, installer opt-in)

A fully independent, **off-by-default** feature: record or load 1-3 short
reference clips of a voice and generate arbitrary typed text spoken back in
that voice, via **OmniVoice** (k2-fsa, Apache-2.0), running entirely on this
machine. Unlike the cloud backends above, no audio or text is ever uploaded.

Shown only when the "Clone Your Voice / Text to Voice" task was ticked at
install time (`core.hub.voice_clone_tab_enabled` — see the `installer_embed.iss`
`voiceclone` task). The OmniVoice package + `torch` + `soundfile` (~2GB) and
the model weights (~2GB, fetched separately by OmniVoice itself on first
model load) are **not bundled** — both install/download on first use and
need an internet connection for that one-time step only.

| Field | Type | Default | Description |
|---|---|---|---|
| `voice_clone.engine` | str | unset (Kokoro) | Last model picked on the tab: `kokoro` or `omnivoice`. |
| `voice_clone.mode` | str | unset (`clone`) | Last OmniVoice mode: `clone`, `design` or `auto`. |
| `voice_clone.kokoro_voice` | str | unset (`af_heart`) | Last Kokoro voice key. |

Consent is not a setting. The tab always shows the rules (own voice, or the
speaker's clear permission; no impersonation, no misleading audio of real
people), and cloning from reference clips needs the tick "I have the
speaker's permission to clone this voice (or it is my own)" each session;
adding or removing a reference clip clears it. Voice design, the model's own
voice and Kokoro need no tick. A `voice_clone.consent_accepted` key written by
older versions (it backed a one-time confirmation dialog) still loads and is
ignored.

#### Estimate before a long text

One job takes at most 100,000 characters (`core.tts_plan.MAX_TEXT_CHARS`, both
engines; about 90 minutes of speech and a WAV of about 265 MB);
`tts_no_text_limit` below lifts it. Before a long text starts, **Generate** shows a confirm step under
the text box: the time range on this computer, the speech length, the WAV size
(24 kHz, 16-bit mono, about 2.8 MB a minute) and the free space where the file
is written. **Start** runs it, **Cancel** runs nothing; the text box and the
speed slider stay locked while the step is open. If the free space is below the
largest expected file plus 500 MB kept free (checked again on **Start**), the
job is refused and the step says how much space it needs. Texts of up to about 300 characters, and
jobs estimated under two minutes, start at once (`core.tts_plan.needs_confirm`).

The time range comes from a speed figure measured on this computer, stored per
engine and device in `Cache\tts\speed_calibration.json` (`core.tts_plan`):

- **Kokoro**: the first long text offers **Measure this computer's speed**, a
  short run of about 10 seconds in the default voice; nothing runs before that
  click, and the model must already be downloaded.
- **OmniVoice**: no separate measuring run, since on a CPU one pass takes over a
  minute even for a single word. Until a run is measured, the range comes from a
  reference computer and says so.
- Every finished job with at least 5 seconds of speech (8 seconds for OmniVoice)
  replaces the stored figure for its engine and device.

A figure stores the speech length, compute time, text length in speech units
(characters, with each Chinese, Japanese or Korean character counted as two to
three and each run of spaces as one), speed, the engine version and a hardware
fingerprint (OS, CPU name, thread count and the
graphics card for CUDA). When the version or the fingerprint changes, the
figure is ignored and measured again. The file stays on this computer; delete
it to start over.

#### Long text, piece by piece

A text longer than one piece is spoken piece by piece (`core.tts_job`): it is
split at sentence ends (else after a comma, else after a space) into pieces of
at most 2,000 characters for Kokoro and 500 for OmniVoice. Each finished piece
is written as its own WAV file, next to a small progress file:

```
Cache\voice_clone\job-<id>\output.wav                     the final file
Cache\voice_clone\job-<id>\output.parts\progress.json      which pieces are done
Cache\voice_clone\job-<id>\output.parts\piece-0001.wav ... one file per finished piece
```

`<id>` comes from the text, the engine, the voice (the Kokoro voice; for an
OmniVoice clone the language and the contents of the reference clips) and the
speed. The status line shows the piece and the time left, from the speed
measured on the pieces done so far. **Cancel** keeps the finished pieces, and
so do a crash and a power cut (the piece in progress is redone). Pressing
**Generate** again with the same text, voice and speed shows the confirm step
with **Continue the unfinished job** (skips the finished pieces) and **Start
over** (deletes them). The final file is joined only after the last piece,
tagged as AI-generated and checked; then the pieces are deleted. The free-disk
check of a piece-by-piece job counts the pieces still to write plus two copies
of the whole file (the joined file and its tagged copy exist next to all the
pieces for a moment). **Start over** deletes the pieces only when the disk has
room for the whole job again. The voice, mode, clips and language are the ones
set when **Generate** was pressed. A cloning job writes one consent record, for
the joined file.

OmniVoice's voice design and own voice are never split: every pass picks a new
voice, so the pieces would not sound like one speaker. Those two modes take up
to 5,000 characters in one pass (`core.tts_plan.MAX_PASS_CHARS`, also the
limit of any single call into either engine). Unfinished job folders are kept
for 30 days after their last finished piece; other scratch folders for 7 days.

| Field | Type | Default | Description |
|---|---|---|---|
| `tts_no_text_limit` | bool | `false` | **Advanced → App behaviour → Text to Voice: no text length limit (advanced)**. `true` = a Text to Voice job is not limited to `MAX_TEXT_CHARS`; the estimate, the free-disk check and the piece-by-piece writer still apply, and a speech longer than one WAV file can hold (4 GB, about 24 hours) is refused. Local only: the online config can never set it (`core.config.LOCAL_ONLY_KEYS`). |

#### AI-generated tag

Every WAV file the tab produces (OmniVoice clone, voice design or model
voice, and every Kokoro voice, the voice preview included) carries a RIFF
`LIST`/`INFO` chunk, placed just before the audio data:

| INFO field | Value | ffmpeg shows it as |
|---|---|---|
| `ICMT` | `AI-generated synthetic speech` (fixed text, safe to match in scripts) | `comment` |
| `ISFT` | `Whisper Transcriber Suite <version>` | `encoder` |

The audio samples are untouched; only the container gets the extra chunk
(`core.synthetic_audio.tag_wav`). **Save** copies the generated file
byte for byte, so the saved copy keeps the tag. To check a file:
`ffmpeg -i file.wav` lists both fields under `Metadata:`.

#### Consent record (local only)

Each generation that clones a voice from reference clips appends one JSON
line to `voice_clone_consent.jsonl` in the user data folder
(`%LOCALAPPDATA%\WhisperTranscriberSuite\` on Windows,
`core.synthetic_audio.consent_log_path()`). Generations without reference
audio (voice design, model voice, Kokoro) write no line. The file never
leaves this computer: nothing uploads it and it is not part of the usage
statistics. The app only appends to it; delete it whenever you like. If the
line cannot be written (for example the folder is read-only), the generated
file is kept anyway: the tab's status line shows a warning and the error
goes to the app log.

| Field | Meaning |
|---|---|
| `time_utc` | When the file was generated, UTC, e.g. `2026-10-05T14:03:22Z`. |
| `output_file` | Absolute path of the generated WAV in the session scratch folder (`Cache\voice_clone\<timestamp>\`, swept after 7 days); use **Save** to keep the file. |
| `output_sha256` | SHA-256 of that finished, tagged WAV. A copy made with **Save** has the same hash, so it can be matched to its record. |
| `reference_sha256` | List of SHA-256 hashes, one per reference clip used (at most 3), in order, of the clip as fed to the model: a clip longer than 10 s is first cut to its first 10 s, so its hash differs from the original file's. The clips themselves are not copied. |
| `consent_accepted` | The permission tick the generation ran under (always `true`: cloning is refused without it). |
| `engine` | `omnivoice`. |
| `app_version` | App version that generated the file. |

### Web / LAN access (optional local HTTP job server)

Backs both the `gui.py serve` CLI and the one-click **Web / LAN access**
tab. The server is a stdlib-only HTTP server (no new dependency) that lets
a phone or another PC send a file or a URL to transcribe from a browser.
It binds **loopback (`127.0.0.1`) by default** — no Windows firewall prompt
— and LAN sharing is an explicit opt-in. See [`SERVER.md`](SERVER.md).

| Field | Type | Default | Description |
|---|---|---|---|
| `server_port` | int | `8765` | Default listen port for the server. If the port is busy when started from the tab, a free-port fallback picks another and shows the actual URL. |
| `server_max_upload_mb` | int | `512` | Caps a single browser upload (MB). The worker's ~1 MB command guard does NOT cover browser uploads, so this is the upload size limit for the web path. |
| `server_share_lan` | bool | `false` | When `true`, the tab's Start binds `0.0.0.0` (all interfaces — other devices on the network can reach it) instead of `127.0.0.1` (this machine only). Persisted from the **Share on local network** checkbox; this is the path that triggers the Windows firewall prompt. The CLI uses `--lan` instead of this key. |
| `server_token` | string | `""` | Optional shared-secret password. When non-empty, every request must present it (`X-Auth-Token` header or `?token=` query). Used by the tab and by `gui.py serve` (unless `--token` is given; `--token=` serves without one). While it is empty the server refuses requests from other web origins and answers only a `Host` that is an IP address, `localhost`, `host.docker.internal` or this computer's name (see [SERVER.md](SERVER.md#browser-protections)). Stored in **cleartext** here, consistent with cookies / API keys (the file is per-user under `%LOCALAPPDATA%\WhisperTranscriberSuite` and is not encrypted). |

### Usage statistics (P4-4)

**On by default.** After each transcription that finishes successfully in the desktop app, the app POSTs one form-encoded row to `stats_url`. Failed and cancelled jobs send nothing, and the CLI, the Web / LAN server and the Live tab never send stats. Nothing is sent while `telemetry_opt_in` is false or `stats_url` is empty.

| Field | Type | Default | Description |
|---|---|---|---|
| `telemetry_opt_in` | bool | `true` | The usage-statistics switch: **Help → Send usage statistics**, or the same checkbox under **Advanced → App behaviour** (both show the same value). Turning it off is saved in `config.json` and survives restarts and upgrades; the untouched default is not written to the file. Local-only: the online config can never set it (`core.config.LOCAL_ONLY_KEYS`). The same flag also gates the launch ping and Sentry crash reports below, which in addition need environment variables. |

What is sent (built by `core.stats.build_stats_payload`, posted by `core.stats.post_stats_async` on a daemon thread with a 5 s timeout; every error is swallowed, so stats never block or crash a transcription):

| Field | Content |
|---|---|
| `form_submitted` | always `1` (tells the server script to store the row) |
| `model` | the model or engine that transcribed: the faster-whisper model name, `nvidia_asr:<model id>`, or the engine id for other engines; a model loaded from a local folder is sent as `local-model` (e.g. `nvidia_asr:local-model`), never as its path (`core.stats.public_model_name`) |
| `language` | detected language |
| `audio_duration` | seconds; the last segment's end time |
| `transcription_time` | seconds of wall-clock time from task start to finish |
| `word_count` | words in the transcript |
| `status` | `finished` (only successful runs are sent) |
| `program_version` | app version |
| `country` | two-letter code from the operating system's region setting (`core.stats.region_country`: Windows "Country or region", macOS `AppleLocale`, else `LC_ALL` / `LANG`); read locally, no network lookup; empty when no region is set |
| `platform_system`, `platform_release`, `platform_version`, `platform_machine`, `platform_processor` | OS name, release and build, CPU architecture and processor string (Python `platform` module) |
| `cpu_count`, `mem_total` | logical CPU count and total RAM in bytes (`psutil`; `0` when it is missing) |

Never sent: audio, transcript text, the source file's name or folder path, a local model folder's path, the computer name, the user name, serial numbers or an IP address field. (App versions up to 1.9.3 also sent `file_name`, the source file's name without its folder.) The server still sees the connection's IP address, as every web server does; what it stores is decided by the server script.

The server script in this repo (`platform/stats-server/transcription_stats.php`; deployment notes in that folder's `README.md`) stores the fields above, length-capped; it does not read, look up or store the connection's IP address, and it ignores a `file_name` posted by an older app version. The server at the default `stats_url` is updated separately: until it runs this version, it may record the request's **client IP** and a **geoip lookup** of it, as older versions did, and the `file_name` that app versions up to 1.9.3 still send. The same `word_count` is also stored locally in `history.db` (`transcriptions.word_count`, added by an idempotent migration) whatever the switch says.

`build_stats_payload` does no network I/O (it only reads local OS facts), and `post_stats_async` re-checks `telemetry_opt_in`, the `stats_url` scheme (http/https only) and the payload, so a direct call can never send while the switch is off.

#### Launch ping and crash reports (inactive unless configured)

`app/observability.py` holds two more senders. Both need `telemetry_opt_in` AND an environment variable that the published builds do not set, so by default neither sends anything:

- **Launch ping** — one JSON POST per launch to `$WHISPER_TELEMETRY_URL`, carrying `schema`, `version`, `os`, `os_release`, `python` and `anonymised_id`. Despite its name, `anonymised_id` is a stable per-install id: a random value created once under `user_cache_dir()/telemetry_id`, so pings from one install can be linked to each other (not to a machine or a person).
- **Sentry crash reports** — initialised only when `$SENTRY_DSN` is set and the optional `sentry-sdk` package (the `crash_reporting` extra) is installed; `send_default_pii=False`, no local variables, no breadcrumbs. Every event first passes `app.observability.scrub_sentry_event`: it drops the host name, `sys.argv`, user and request data, each frame's absolute path (only the source file's base name stays) and log-message arguments, and masks URLs, absolute paths and quoted paths or file names in the remaining text. A file name written into a message without quotes or a folder is not recognised.

### Transcript conversion (P4-3)

Not a config key — a **File → Convert transcript…** menu action backed by the Tk-free `core.convert`. It parses an existing transcript (`.srt` / `.vtt` / `.tsv` / `.json`, plus `.otr` import) into the faster-whisper JSON segment list (the universal middle format) and re-emits any text format from the writers registry (`srt` / `vtt` / `tsv` / `txt` / `json` / `lrc` / `md`). `.txt` is **output-only** (no timestamps to parse back). Pure seams: `parse_to_segments(path)` (auto-detects by extension then content) and `convert_file(in, out_format, out_path=None)` (writes beside the input; never clobbers the source on an in-place re-emit).

## Coming in later phases

| Field | Type | Default | Description |
|---|---|---|---|
| `crash_reporting` | bool | `false` | Planned separate switch for Sentry crash reports (ROADMAP 1.8). Not read today: crash reports follow `telemetry_opt_in` + `$SENTRY_DSN` (see **Launch ping and crash reports**). |

## Transcription and download options

| Field | Type | Default | Description |
|---|---|---|---|
| `vad_enabled` | bool | `true` | Voice Activity Detection (skip silence before transcribing). |
| `vad_min_silence_ms` | int | `500` | Shortest silence (ms) that splits speech. |
| `vad_threshold` | float | `0.5` | Speech probability above which audio counts as speech. |
| `vad_speech_pad_ms` | int | `400` | Audio kept (ms) on each side of detected speech. |
| `word_timestamps` | bool | `false` | Per-word timings in the JSON output. |
| `initial_prompt` | string | `""` | Text given to the model before the audio (names, spelling). |
| `hotwords` | string | `""` | Words the model should prefer. |
| `output_formats` | array of strings | `["srt", "json"]` | Subset of `srt / vtt / tsv / json / txt / lrc / md`. |
| `transcribe_backend` | string | `"faster_whisper"` | The transcription engine (Advanced settings). Cloud engines run only when chosen here, with the user's own credentials. |
| `transcribe_language` | string | `"Auto"` | Spoken-language picker on the Transcribe tab (display name). Kept for older files; the picker itself is not saved. |
| `hallucination_detect_enabled` | bool | `true` | Flags repeated or invented lines in the output. |
| `auto_chapters_enabled` | bool | `true` | Adds chapters to the output after a transcription. |
| `chapter_min_seconds` | float | `60.0` | Shortest chapter, in seconds. |
| `chapter_gap_seconds` | float | `2.5` | Silence (s) that may start a new chapter. |
| `diarization_enabled` | bool | `false` | Speaker labels (optional pyannote install). |
| `diarization_num_speakers` | int | `-1` | Number of speakers; `-1` = detect. |
| `diarization_cluster_threshold` | float | `0.5` | How alike two voices must be to count as one speaker. |
| `voiceprint_enabled` | bool | `true` | Renames speaker labels to enrolled voices when diarization is on and voices are enrolled. |
| `demucs_enabled` | bool | `false` | Separates the voice from music before transcribing (optional Demucs install). |
| `demucs_cache_mb` | int | `2048` | Disk budget (MB) for separated audio kept for reuse. |
| `live_model` | string | `"tiny"` | Model of the Live tab. |
| `auto_transcribe_after_download` | bool | `false` | Transcribes each finished download. |
| `cookies_from_browser` | string | `""` | Browser whose cookies yt-dlp uses (`"firefox"`, `"chrome"`, `"edge"`, `"brave"`, …); empty = none. |
| `sponsorblock_categories` | array | `[]` | SponsorBlock segments to cut from downloads, e.g. `["sponsor", "intro", "outro"]`. |
| `watched_folder` | string | `""` | Folder whose new media files are transcribed automatically. |
| `watched_folder_enabled` | bool | `false` | Turns the watched folder on. |
| `chime_on_complete` | bool | `true` | Plays a sound when a job finishes. |
| `minimise_to_tray` | bool | `false` | Minimising hides the window to the tray. |
| `window_geometry` | string | `""` | Last window size and position. |
| `server_https_enabled` | bool | `false` | Web / LAN access tab: serve over HTTPS. |
| `server_webhook_url` | string | `""` | Web / LAN access tab: URL told about finished jobs (skipped while Work offline is on). |
| `voice_clone` | object | `{}` | Clone Your Voice tab: engine, mode and Kokoro voice. |

Not read by the app (planned only): `models`, `active_model`, `task`, `presets_dir`,
`active_preset`, `parallel_downloads`, `extra_ytdlp_args`, `download_rate_limit`.

## Migration policy

When a new field is introduced, `load_config` will populate it with the default if absent. Removing a field is a breaking change and bumps the minor version.

`save_config` writes the keys the app changed and keeps every other key already in `config.json`, including unknown ones (forward-compat for downgrades); a new install, or a save from a plain dict, writes the full known schema. Derived and online-only keys are never written (`_NON_PERSISTED_KEYS`, `_DISK_ONLY_KEYS`).

## Examples

### Minimum viable config (current)

```json
{
  "model": {
    "name": "faster-whisper-large-v3",
    "url": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip",
    "md5": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip.md5"
  },
  "hub_folder": "C:\\Users\\Owner\\AppData\\Local\\WhisperTranscriberSuite\\Cache\\models",
  "model_path": "",
  "device": "auto",
  "compute_type": "int8",
  "parallel_workers": 2,
  "download_folder": ""
}
```

### GPU + multiple workers

```json
{
  "device": "cuda",
  "compute_type": "float16",
  "parallel_workers": 4
}
```

### CPU-only, minimum resource usage

```json
{
  "device": "cpu",
  "compute_type": "int8",
  "parallel_workers": 1
}
```

## Manual / expert override files

Two override mechanisms exist, both higher-priority than the hard-coded defaults:

- The user's **`config.json`** itself is the highest-priority layer in the three-level merge (see *Three-level merged configuration* above) — edit it for per-machine expert overrides, including the local-only keys the online layer cannot touch.
- A per-folder **`.whisperproject.json`** (nearest one walking up from the input file) applies on top for that job only — see `core.config.merge_project_overrides`. Wrong-typed keys are dropped + logged.

### What a `.whisperproject.json` may set

A project file can sit inside a downloaded or shared folder, so it may only change per-file
transcription choices that keep the audio, the transcript and your keys on this computer
(`core.config.PROJECT_ALLOWED_KEYS`):

| Group | Keys |
|---|---|
| Output | `output_formats` |
| Prompting | `initial_prompt`, `hotwords` |
| Timing | `word_timestamps`, `alignment` (`none` / `stable_ts`) |
| Speed | `batch_size` |
| Voice detection | `vad_enabled`, `vad_threshold`, `vad_min_silence_ms`, `vad_speech_pad_ms`, `vad_window_s` |
| Clean-up | `hallucination_detect_enabled`, `demucs_enabled`, `denoise_enabled`, `denoise_level` |
| Speakers | `diarization_enabled`, `diarization_num_speakers`, `diarization_cluster_threshold` |
| Chapters | `auto_chapters_enabled`, `chapter_min_seconds`, `chapter_gap_seconds` |

Numbers must also be in a sane range (for example `batch_size` 1-256, `chapter_min_seconds` at
least 10, `vad_threshold` 0-1; `core.config._PROJECT_KEY_RANGES`), else that key is dropped.
Every other key is ignored, and the log names the file and the ignored keys once (names only,
never values). That includes the engine (`transcribe_backend`), anything with a URL, an API key, a
token, a webhook or the stats upload, the AI / LLM settings, server settings, folders and program
paths, `output_filename_template`, and the model: the model and the transcription language come from
the app settings and the job, not from a project file. Example:

```json
{
  "output_formats": ["srt", "txt"],
  "hotwords": "Anthropic, Claude",
  "diarization_enabled": true,
  "diarization_num_speakers": 2
}
```
