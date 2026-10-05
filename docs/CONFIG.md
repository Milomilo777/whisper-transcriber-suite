# Configuration Reference

`configuration.json` at the repo root is the **master copy of the online
app config** — the maintainer uploads it to `config_url`
(`https://smch.ir/whisper/app_config.json`). It contains only the
`ONLINE_ALLOWED_KEYS` keys (`model_catalog`, `stats_url`, `latest_version`,
`ffplay_downloads`) and is fetched/merged as described below. It is NOT
read by the app directly from the repo — it must be uploaded to `config_url`
for the online layer to pick it up.

`config.json` lives at `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` on Windows (`platformdirs.user_config_dir("WhisperTranscriberSuite")` on every platform). On first launch, a legacy `config.json` next to `gui.py` is copied to the new location and the original renamed to `.migrated.bak`. Subsequent launches read only from the platformdirs path.

The file is read once at startup and written when the user changes a persisted setting (download folder, subtitle preferences, theme, etc.). Manual edits take effect on next launch.

## Three-level merged configuration (P4-1)

The effective config is merged from **three layers**, in priority order:

1. **Local `config.json`** — the user's file (described above). **Highest priority.** A local override file is the place for expert / per-machine overrides; it may set ANY key, including the local-only ones the online layer is forbidden from touching (paths, API keys, credentials, the model hub folder, user preferences).
2. **Online app config** — a JSON the maintainer hosts at `config_url`, fetched on startup. It lets **app-level** settings change **without redistributing the program** (the model catalog, the telemetry-stats endpoint, the latest version, the ffplay download links). It is restricted to a **safe allowlist** (`stats_url`, `latest_version`, `ffplay_downloads`, `model_catalog`) — it can **never** override user-private / local-only keys.
3. **Hard-coded `DEFAULT_CONFIG`** — the in-code baseline. **Lowest priority.**

A key missing from a higher-priority layer falls through to the next. Dict-valued keys (e.g. `model`, `model_catalog`) are deep-merged, so a partial override keeps the sibling keys from the lower layer.

The online fetch is **fail-safe**: a short timeout, the last good response cached under `user_cache_dir()/app_config_cache.json`, and a fall-through to the cache (then to nothing) when offline. It **never blocks or crashes startup**. The worker-subprocess start-up paths (`core.transcriber` import, `core.worker.main`, the faster-whisper model load) skip the fetch (`load_config(fetch_online=False)`), so a worker spawn is never delayed by the network. A worker's first transcription does fetch it once (`core.transcriber._apply_runtime_overrides` calls `load_config()`; 4 s timeout, then the cache).

The merge itself is pure and testable: `core.config.merge_config_sources(hardcoded, online, local)`. The fetch is the separate `core.config.fetch_online_config(url, cache_path=...)` helper. `core.config.load_config()` wires the two together; `load_config(fetch_online=False)` uses only the local + hard-coded layers.

| Field | Type | Default | Description |
|---|---|---|---|
| `config_url` | string | `https://smch.ir/whisper/app_config.json` (placeholder — the maintainer sets the real URL) | URL of the online app-level config JSON. Fetched best-effort on startup; cached for offline fallback. Empty disables the online layer. A hand edit in `config.json` (e.g. a staging URL, or `""`) is honoured on load, but `save_config` drops this key, so the edit lasts only until the app next saves its settings. |
| `model_catalog` | object | `{}` | Online/local-supplied catalog of selectable models, same shape as `core.model_manager.MODEL_REGISTRY` (`slug → {label, name, url, md5, hf_repo, approx_size_gb, info}`). `url`/`md5` may be `""` for a model with no smch.ir mirror — `ensure_model` then downloads straight from `hf_repo`. Overlaid on the built-in catalog so new models can ship without an app update. **Allowlisted** for the online layer. |
| `stats_url` | string | `https://smch.ir/stats/transcription_stats.php` | Usage-stats POST endpoint. The desktop app POSTs one row here per successfully finished transcription while `telemetry_opt_in` is true, which is the default — see **Usage statistics (P4-4)** below for every field. Empty or a non-http(s) URL = no POST. **Allowlisted** for the online layer so it can be set/changed remotely; like `config_url` it is not written to `config.json`. |
| `latest_version` | string | `""` | Newest published version string (informational; complements the GitHub update check). **Allowlisted** for the online layer. |
| `ffplay_downloads` | object | `{"windows": "<BtbN win64-gpl .zip>", "macos": "<evermeet ffplay .zip>", "linux": ""}` | Platform → ffplay download URL map for the Video-Tiling ffplay binary (not bundled). Each value is a DIRECT `ffplay[.exe]` URL **or** a `.zip` of a full ffmpeg build that contains it (the downloader extracts just ffplay; `.7z`/`.tar.*` are NOT supported). See **ffplay auto-download (P4-5)** below. **OWNER ACTION: verify/override these URLs via the online config** — third-party static-build URLs and their archive layouts rot. **Allowlisted** for the online layer. |

## Where things live (Phase 1.2)

| Purpose | Path (Windows) | Helper |
|---|---|---|
| `config.json` | `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` | `core.config.config_path()` |
| Model hub (default `hub_folder`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\` | `core.hub.default_hub_folder()` |
| Cached models (default `model_path`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<model-folder>\` | `core.config.user_cache_dir()` |
| Rotating logs | `%LOCALAPPDATA%\WhisperTranscriberSuite\Logs\app.log` (5 MB × 3) | `core.config.user_log_dir()` |
| Voice-clone consent record (local only, see [below](#consent-record-local-only)) | `%LOCALAPPDATA%\WhisperTranscriberSuite\voice_clone_consent.jsonl` | `core.synthetic_audio.consent_log_path()` |

`platformdirs` chooses the equivalent paths on macOS and Linux. The "Help → Open log folder" menu item opens the log directory.

## Network use

Every outbound connection the app can make. Transcription with a local engine works without a network once its model is on disk: the automatic requests below then fail quietly and the app carries on. The rows marked *automatic* happen without a click.

| What | When | Destination | What is sent | How to stop it |
|---|---|---|---|---|
| Online app config | *Automatic*: at startup of the desktop app, the CLI and the server, and on the first transcription in each worker process (once per process) | `config_url`, default `https://smch.ir/whisper/app_config.json` | A plain GET | No switch. A hand-set `"config_url": ""` in `config.json` works until the app next saves its settings (see the `config_url` row above). |
| Update check | *Automatic*: desktop app, a few seconds after launch, at most once a day; also **Help → Check for updates…** on demand | `https://api.github.com/repos/Milomilo777/whisper-transcriber-suite/releases/latest` | A plain GET | `update_check_enabled: false` in `config.json` (no UI toggle; the Help item still works). |
| Usage statistics | *Automatic*: after each successfully finished transcription in the desktop app | `stats_url`, default `https://smch.ir/stats/transcription_stats.php` | A form POST with the fields listed under **Usage statistics (P4-4)** | Untick **Help → Send usage statistics** or the same checkbox in **Advanced → App behaviour** (`telemetry_opt_in: false`). |
| Whisper model download | First transcription with a model that is not on disk (also after switching models) | The `smch.ir` mirror (zip + MD5 manifest) for `large-v3`, `large-v3-turbo`, `distil-large-v3.5` and `medium`; Hugging Face (`huggingface.co` and its download CDN) for every other model and as the fallback | GETs | Runs while the model is missing, or after the model check below finds a changed or missing file. |
| Model check | When `core.model_manager.ensure_model` runs for one of the four mirror models above while it is already on disk — when the Web / LAN server starts (`gui.py serve` or the **Web / LAN access** tab), and in the model dialog shown after an installed model failed to load. A normal desktop, CLI or Live transcription loads an on-disk model without this check. | The model's `.md5` manifest on `smch.ir` | A plain GET; the local files are hashed and compared with it. If a file is missing or differs, the model folder is deleted and the whole model downloads again (row above). | No switch. A failed request is ignored and the model is used as-is. |
| Other models | First use of the feature: whisper.cpp engine, local AI Layer model, Kokoro text-to-voice, OmniVoice voice cloning, NVIDIA Parakeet, stable-ts word alignment, Demucs vocal separation | `huggingface.co` (whisper.cpp `ggml` model, Qwen2.5 GGUF, OmniVoice and Parakeet weights); `github.com` release assets (Kokoro); `openaipublic.azureedge.net` (the OpenAI Whisper checkpoint stable-ts aligns with); Demucs fetches its own weights | GETs | Only runs while that model is missing. |
| Optional components | First use of a feature whose Python packages are not bundled (`core.optional_deps.FEATURES`). stable-ts alignment asks first; the NVIDIA Parakeet and Google Cloud engines install when a job starts with them selected (Google Cloud also from its connection test in the Advanced dialog, see **Cloud engines**); voice cloning installs on its first use; the CUDA runtime from the Hardware wizard's button | PyPI (`pypi.org`, `files.pythonhosted.org`) via `pip install` | Standard pip requests | Do not select those engines or features; nothing installs while they stay unused. |
| Video downloads, captions, Video Tiling | When the user downloads a URL, fetches its captions or starts a stream | The site of the URL and its media servers (YouTube: `www.youtube.com` plus `*.googlevideo.com`), or any other site yt-dlp supports | yt-dlp's requests to that site; a link pasted in **Download Videos** is looked up at once (formats, title, captions) | User action. |
| yt-dlp self-update | Before a download when `auto_update_yt_dlp` is `true` (default `false`), at most once every 24 h and only when the yt-dlp folder is writable; and *automatic* in Video Tiling: the self-heal after repeated stream failures while `tiling_auto_restart` is on (the default). Both are skipped in PyInstaller builds (the macOS app); the Windows installer and Portable builds run them. | yt-dlp's release channel on `github.com`, or PyPI for a pip-installed yt-dlp | GETs | `auto_update_yt_dlp: false` (default); `tiling_auto_restart: false`. |
| YouTube JavaScript helper (Deno) | When the user clicks **Install YouTube helper** (shown for a YouTube link when no Deno is found) | `https://github.com/denoland/deno/releases/latest/download/` (archive + `.sha256sum`) | GETs | User action. |
| ffplay | When the user clicks **Download ffplay** on the Video Tiling tab | `ffplay_downloads[<platform>]` (defaults: a BtbN FFmpeg build on `github.com`, `evermeet.cx` on macOS) | A GET | User action. |
| SMTV integration | When the user opens the SMTV tab (it loads the listing and thumbnails) or downloads from it | `suprememastertv.com` and its video CDN | GETs | User action. |
| Cloud engines | A job started with a cloud engine selected in **Advanced → Backend**, and the Gemini **Test key** button. The Google Cloud connection test (it also runs by itself when the Advanced dialog opens with that engine selected and a key file set) only reads the key file and builds the client; its one network use is the library install under **Optional components** | Gemini: `generativelanguage.googleapis.com`. Google Cloud Speech-to-Text: `speech.googleapis.com` (or `<region>-speech.googleapis.com`), `oauth2.googleapis.com` for the service-account sign-in, plus Cloud Storage in batch mode | Jobs: **the audio**. Every request: the API key / service-account credentials | Pick a local engine (the default). |
| Remote AI provider | Only when the AI Layer is on (`ai_enabled`) and `llm_provider` is `remote` | `llm_remote_base_url` (default `https://api.openai.com/v1`) | **Transcript text** in the prompt, with `llm_remote_api_key` | Keep `llm_provider: "local"` (the default) or leave the AI Layer off (the default). |
| Web / LAN server | Only while the server runs (`gui.py serve` or the **Web / LAN access** tab) | Inbound: loopback by default, the LAN when sharing is on. Outbound: the URLs clients submit, and the webhook URL when set (`server_webhook_url`, or `serve --webhook`) | Webhook: a small JSON job summary | Stop the server; leave the webhook unset (the default). |
| Launch ping, Sentry | Only when `$WHISPER_TELEMETRY_URL` / `$SENTRY_DSN` are set (published builds set neither) and `telemetry_opt_in` is on | The URL / DSN in those variables | See **Launch ping and crash reports** | Leave the variables unset. |

Two features use packages the app never installs: semantic search (`core.search`, needs `sentence-transformers`) and voiceprint speaker matching (`core.voiceprint`, needs `pyannote.audio`). When a user has installed those packages by hand, their models (`all-MiniLM-L6-v2`, `pyannote/embedding`) download from Hugging Face on first use.

Opening a link (Help menu, About dialog, release page) hands the URL to the system browser; the app itself sends nothing for it.

## Field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | object | (see below) | The active model's source and verification info |
| `model.name` | string | `"faster-whisper-large-v3"` | Display name in logs |
| `model.url` | string | `https://smch.ir/models/...zip` | ZIP archive of the model |
| `model.md5` | string | `<url>.md5` | URL of the per-file MD5 manifest |
| `whisper_model` | string | `"large-v3"` | Slug of the selected model in the merged catalog (built-in `MODEL_REGISTRY` + online `model_catalog`). Set by the **Advanced > Whisper model** combo, which also rewrites `model` + `model_path` so the new model downloads on the next transcription. See the Models section below. |
| `hub_folder` | string | `""` (first-run dialog) | Parent folder that holds the `models--Vendor--name` model directories. Empty triggers the first-run picker, which pre-fills `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models` — a per-user, always-writable location (never the Program Files install dir). |
| `model_path` | string | (derived from `hub_folder`) | Absolute path where the model is extracted. When empty it is derived at startup from `hub_folder + model.name`; with no hub set it falls back to `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<name>`. A non-empty value is a per-model override. |
| `device` | string | `"auto"` | `"auto"` / `"cuda"` / `"cpu"`. With `"auto"`, the autodetect only selects CUDA when ctranslate2 reports a GPU **and** the CUDA runtime library it needs actually loads (cuBLAS for CUDA 12; CTranslate2 before 4.6.3 also needed cuDNN) — found on the system path, in NVIDIA's pip wheels (`nvidia-cublas-cu12`, which Advanced › Re-detect hardware can install), a CUDA Toolkit, or a CUDA PyTorch; otherwise it falls back to CPU. At model-load time a CUDA load — or its one-pass GPU warm-up — that still fails self-heals to CPU `int8` instead of crashing the worker — the active tab shows a GPU/CPU badge and (once) a "running on CPU (slower)" warning. |
| `compute_type` | string | `"int8"` | `faster-whisper` compute type. Common values: `int8`, `int8_float16`, `float16`, `float32`. `int8` is the smallest/fastest on CPU; `float16` is preferred on GPU. |
| `cpu_warning_shown` | bool | `false` | Set to `true` after the one-time "running on CPU (slower)" warning has been shown, so it never repeats. The warning only appears when a GPU was detected-but-unusable or a CUDA→CPU downgrade happened — never on a genuine CPU-only machine. |
| `parallel_workers` | int | `2` | Maximum simultaneous transcription worker subprocesses. Each loads the model and uses ~3 GB RAM (or VRAM on GPU). |
| `download_folder` | string | `""` | Default destination for video downloads. Updated by the Folder Browse button. |
| `download_subtitles_enabled` | bool | `false` | Last state of the subtitle checkbox on the Download Videos tab |
| `download_subtitle_lang` | string | `"Automatic"` | Last-selected subtitle language (display name from `SUBTITLE_LANGUAGES`, not the code). |
| `theme` | string | `"dark"` | `"light"` / `"dark"` / `"system"` — applied via `sv_ttk` (Phase 1.1). `"system"` falls back to `"dark"` if the optional `darkdetect` package is not installed. |
| `log_level` | string | `"INFO"` | Python logging level for the file handler (Phase 1.3) |
| `auto_update_yt_dlp` | bool | `false` | Phase 0 fix to AUDIT A1: yt-dlp's `--update` before a download is off by default. When `true` it runs at most once every 24 h (backoff stamped in `last_yt_dlp_update_check`), only when the yt-dlp folder is writable and never in a PyInstaller build. When this is `false`, downloads never wait on `--update`. |
| `last_yt_dlp_update_check` | string (ISO date) | `""` | Timestamp of the last update attempt (used by the once-per-day guard inside `maybe_update_yt_dlp`) |
| `update_check_enabled` | bool | `true` | GitHub "update available" check (`core.updates`), on by default. When on, a quiet launch check runs at most once per day (throttled by `last_update_check`) and stays SILENT unless a newer release exists — never nagging when up to date, offline, or when the repo is private (a 404 is swallowed). When a newer release is found it offers to open the download page. It is **notify-only**: it never auto-downloads or auto-installs. Set to `false` to disable the quiet launch check; the **Help → Check for updates...** menu item still runs on demand. |
| `last_update_check` | string (ISO date) | `""` | Date (`YYYY-MM-DD`) of the last *quiet* update check, used only for the once-per-day throttle. The manual **Help → Check for updates...** menu item ignores it. |
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

A malformed catalog entry (missing/empty `name`, or with no `url` AND no `hf_repo`, or not a dict) is skipped so a bad online payload never breaks the picker — the built-ins always survive.

### Video Tiling

Persisted choices for the Video Tiling tab (the `core.tiling.TilingController`
video-wall engine). All are remembered between launches.

| Field | Type | Default | Description |
|---|---|---|---|
| `tiling_quality` | string | `"Auto"` | yt-dlp quality band: `Auto` / `1080p` / `720p` / `480p` / `360p` / `240p` / `144p`. `Auto` lowers resolution as the grid gets denser (a dense grid needs far less than 1080p). Always ends in `/best` so playback never fails on a missing resolution. |
| `tiling_mute` | bool | `false` | Mute audio. In a multi-monitor wall only the first window keeps audio anyway (to avoid echo); this mutes that one too. |
| `tiling_multi_monitor` | bool | `false` | Fan the one download out to one `ffplay` window per selected monitor (a multi-screen wall) instead of a single full-screen window. |
| `tiling_selected_monitors` | array of int | `[]` | Spatial monitor indices (from `core.monitors`, `0` = left-most) ticked in the **Monitors…** chooser. Empty = all monitors when multi-monitor is on, or the primary when off. Stale indices (a monitor that has been unplugged) are ignored at start. |
| `tiling_auto_restart` | bool | `true` | Reconnect automatically with exponential backoff (3s→30s) when the stream drops; after repeated quick failures the engine self-heals by updating yt-dlp. Off = a drop just stops. |

#### ffplay auto-download (P4-5)

ffplay is **not bundled** (only ffmpeg / ffprobe / yt-dlp are). When ffplay is missing, the Video Tiling tab behaves as follows:

- If `ffplay_downloads[<platform>]` is set, it shows a **Download ffplay** button. Clicking it runs `core.tiling.download_ffplay()` on a daemon thread, fetching the URL into the app's `bin/` dir. The URL may be a direct `ffplay[.exe]` binary, or a `.zip` of a full ffmpeg build — in which case `core.tiling.extract_ffplay_from_zip()` pulls out just `ffplay[.exe]`. `.7z` / `.tar.*` are rejected (stdlib `zipfile` only).
- If no URL is configured, it keeps the original "put ffplay in the bin folder / install ffmpeg on PATH" guidance.

The pure seams are `select_ffplay_url(downloads, platform_key)` and `extract_ffplay_from_zip(zip_path, dest_dir)`. **Owner: verify the default `ffplay_downloads` URLs (Windows BtbN, macOS evermeet) and override them via the online config — those third-party builds and their archive layouts change over time.**

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
| `voice_clone.consent_accepted` | bool | `false` | Set to `true` after the user accepts the one-time consent dialog (own-voice-or-permission confirmation + ethics note) shown before the very first generation. Once accepted, the dialog does not reappear. |

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
| `consent_accepted` | The consent confirmation the generation ran under (always `true`: cloning is refused without it). |
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
| `server_token` | string | `""` | Optional shared-secret password. When non-empty, every request must present it (`X-Auth-Token` header or `?token=` query). Stored in **cleartext** here, consistent with cookies / API keys (the file is per-user under `%LOCALAPPDATA%\WhisperTranscriberSuite` and is not encrypted). |

### Usage statistics (P4-4)

**On by default.** After each transcription that finishes successfully in the desktop app, the app POSTs one form-encoded row to `stats_url`. Failed and cancelled jobs send nothing, and the CLI, the Web / LAN server and the Live tab never send stats. Nothing is sent while `telemetry_opt_in` is false or `stats_url` is empty.

| Field | Type | Default | Description |
|---|---|---|---|
| `telemetry_opt_in` | bool | `true` | The usage-statistics switch: **Help → Send usage statistics**, or the same checkbox under **Advanced → App behaviour** (both show the same value). Turning it off is saved in `config.json` and survives restarts and upgrades; the untouched default is not written to the file. Local-only: the online config can never set it (`core.config.LOCAL_ONLY_KEYS`). The same flag also gates the launch ping and Sentry crash reports below, which in addition need environment variables. |

What is sent (built by `core.stats.build_stats_payload`, posted by `core.stats.post_stats_async` on a daemon thread with a 5 s timeout; every error is swallowed, so stats never block or crash a transcription):

| Field | Content |
|---|---|
| `form_submitted` | always `1` (tells the server script to store the row) |
| `file_name` | name of the source file, without its folder |
| `model` | the model or engine that transcribed: the faster-whisper model name, `nvidia_asr:<model id>`, or the engine id for other engines |
| `language` | detected language |
| `audio_duration` | seconds; the last segment's end time |
| `transcription_time` | seconds of wall-clock time from task start to finish |
| `word_count` | words in the transcript |
| `status` | `finished` (only successful runs are sent) |
| `program_version` | app version |
| `country` | two-letter code from the operating system's region setting (`core.stats.region_country`: Windows "Country or region", macOS `AppleLocale`, else `LC_ALL` / `LANG`); read locally, no network lookup; empty when no region is set |
| `platform_system`, `platform_release`, `platform_version`, `platform_machine`, `platform_processor` | OS name, release and build, CPU architecture and processor string (Python `platform` module) |
| `cpu_count`, `mem_total` | logical CPU count and total RAM in bytes (`psutil`; `0` when it is missing) |

Never sent: audio, transcript text, the file's folder path, the computer name, the user name, serial numbers or an IP address field. The server still sees the connection's IP address, as every web server does; what it stores is decided by the server script.

The server script in this repo (`platform/stats-server/transcription_stats.php`; deployment notes in that folder's `README.md`) stores the fields above, length-capped; it does not read, look up or store the connection's IP address. The server at the default `stats_url` is updated separately: until it runs this version, it may record the request's **client IP** and a **geoip lookup** of it, as older versions did. The same `word_count` is also stored locally in `history.db` (`transcriptions.word_count`, added by an idempotent migration) whatever the switch says.

`build_stats_payload` does no network I/O (it only reads local OS facts), and `post_stats_async` re-checks `telemetry_opt_in`, the `stats_url` scheme (http/https only) and the payload, so a direct call can never send while the switch is off.

#### Launch ping and crash reports (inactive unless configured)

`app/observability.py` holds two more senders. Both need `telemetry_opt_in` AND an environment variable that the published builds do not set, so by default neither sends anything:

- **Launch ping** — one JSON POST per launch to `$WHISPER_TELEMETRY_URL`, carrying `schema`, `version`, `os`, `os_release`, `python` and `anonymised_id`. Despite its name, `anonymised_id` is a stable per-install id: a random value created once under `user_cache_dir()/telemetry_id`, so pings from one install can be linked to each other (not to a machine or a person).
- **Sentry crash reports** — initialised only when `$SENTRY_DSN` is set and the optional `sentry-sdk` package (the `crash_reporting` extra) is installed; `send_default_pii=False`.

### Transcript conversion (P4-3)

Not a config key — a **File → Convert transcript…** menu action backed by the Tk-free `core.convert`. It parses an existing transcript (`.srt` / `.vtt` / `.tsv` / `.json`, plus `.otr` import) into the faster-whisper JSON segment list (the universal middle format) and re-emits any text format from the writers registry (`srt` / `vtt` / `tsv` / `txt` / `json` / `lrc` / `md`). `.txt` is **output-only** (no timestamps to parse back). Pure seams: `parse_to_segments(path)` (auto-detects by extension then content) and `convert_file(in, out_format, out_path=None)` (writes beside the input; never clobbers the source on an in-place re-emit).

## Coming in later phases

| Field | Type | Default | Description |
|---|---|---|---|
| `crash_reporting` | bool | `false` | Planned separate switch for Sentry crash reports (ROADMAP 1.8). Not read today: crash reports follow `telemetry_opt_in` + `$SENTRY_DSN` (see **Launch ping and crash reports**). |

## Coming in Phase 2

| Field | Type | Default | Description |
|---|---|---|---|
| `models` | array of objects | (see ROADMAP 2.7) | List of available models with their URLs and active flag |
| `active_model` | string | `"large-v3"` | Which entry in `models` is currently selected |
| `vad_enabled` | bool | `true` | Voice Activity Detection on by default |
| `vad_min_silence_ms` | int | `500` | |
| `vad_threshold` | float | `0.5` | |
| `word_timestamps` | bool | `false` | |
| `initial_prompt` | string | `""` | |
| `hotwords` | string | `""` | |
| `task` | string | `"transcribe"` | `"transcribe"` / `"translate"` |
| `output_formats` | array of strings | `["srt", "json"]` | Subset of `srt / vtt / tsv / json / txt / lrc` |
| `presets_dir` | string | (platformdirs) | Where preset TOML files live |
| `active_preset` | string | `null` | Currently applied preset name |

## Coming in Phase 3

| Field | Type | Default | Description |
|---|---|---|---|
| `parallel_downloads` | int | `1` | Max concurrent yt-dlp downloads |
| `sponsorblock_categories` | array | `[]` | E.g. `["sponsor", "intro", "outro"]` |
| `cookies_from_browser` | string | `null` | `"firefox"` / `"chrome"` / `"edge"` / `"brave"` |
| `extra_ytdlp_args` | string | `""` | Free-form args to append to every yt-dlp invocation |
| `download_rate_limit` | string | `""` | E.g. `"5M"` for `--limit-rate 5M` |

## Migration policy

When a new field is introduced, `load_config` will populate it with the default if absent. Removing a field is a breaking change and bumps the minor version.

`save_config` always writes the full known schema. Unknown fields read from `config.json` are preserved (forward-compat for downgrades).

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
- A per-folder **`.whisperproject.json`** (nearest one walking up from the input file) deep-merges on top for that job only — see `core.config.merge_project_overrides`. Wrong-typed keys are dropped + logged.
