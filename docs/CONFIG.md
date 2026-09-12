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

The online fetch is **fail-safe**: a short timeout, the last good response cached under `user_cache_dir()/app_config_cache.json`, and a fall-through to the cache (then to nothing) when offline. It **never blocks or crashes startup**. The hot worker-subprocess code paths (`core.transcriber` import, `core.worker.main`, the faster-whisper model load) skip the fetch entirely (`load_config(fetch_online=False)`), so a worker spawn is never delayed by the network.

The merge itself is pure and testable: `core.config.merge_config_sources(hardcoded, online, local)`. The fetch is the separate `core.config.fetch_online_config(url, cache_path=...)` helper. `core.config.load_config()` wires the two together; `load_config(fetch_online=False)` uses only the local + hard-coded layers.

| Field | Type | Default | Description |
|---|---|---|---|
| `config_url` | string | `https://smch.ir/whisper/app_config.json` (placeholder — owner sets the real URL) | URL of the online app-level config JSON. Fetched best-effort on startup; cached for offline fallback. Empty disables the online layer. A local `config.json` may override this (e.g. a staging URL). |
| `model_catalog` | object | `{}` | Online/local-supplied catalog of selectable models, same shape as `core.model_manager.MODEL_REGISTRY` (`slug → {label, name, url, md5, hf_repo, approx_size_gb, info}`). `url`/`md5` may be `""` for a model with no smch.ir mirror — `ensure_model` then downloads straight from `hf_repo`. Overlaid on the built-in catalog so new models can ship without an app update. **Allowlisted** for the online layer. |
| `stats_url` | string | `""` | Telemetry-stats POST endpoint. The app POSTs per-transcription usage here (file name, model, language, audio duration, AI time, word count, status) **only when `telemetry_opt_in` is true** (default OFF) — see **Telemetry stats (P4-4)** below. Empty = no POST. **Allowlisted** for the online layer so it can be set/changed remotely. |
| `latest_version` | string | `""` | Newest published version string (informational; complements the GitHub update check). **Allowlisted** for the online layer. |
| `ffplay_downloads` | object | `{"windows": "<BtbN win64-gpl .zip>", "macos": "<evermeet ffplay .zip>", "linux": ""}` | Platform → ffplay download URL map for the Video-Tiling ffplay binary (not bundled). Each value is a DIRECT `ffplay[.exe]` URL **or** a `.zip` of a full ffmpeg build that contains it (the downloader extracts just ffplay; `.7z`/`.tar.*` are NOT supported). See **ffplay auto-download (P4-5)** below. **OWNER ACTION: verify/override these URLs via the online config** — third-party static-build URLs and their archive layouts rot. **Allowlisted** for the online layer. |

## Where things live (Phase 1.2)

| Purpose | Path (Windows) | Helper |
|---|---|---|
| `config.json` | `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` | `core.config.config_path()` |
| Model hub (default `hub_folder`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\` | `core.hub.default_hub_folder()` |
| Cached models (default `model_path`) | `%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models\<model-folder>\` | `core.config.user_cache_dir()` |
| Rotating logs | `%LOCALAPPDATA%\WhisperTranscriberSuite\Logs\app.log` (5 MB × 3) | `core.config.user_log_dir()` |

`platformdirs` chooses the equivalent paths on macOS and Linux. The "Help → Open log folder" menu item opens the log directory.

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
| `device` | string | `"auto"` | `"auto"` / `"cuda"` / `"cpu"`. With `"auto"`, the autodetect only selects CUDA when ctranslate2 reports a GPU **and** the cuDNN/cuBLAS runtime libraries actually load; otherwise it falls back to CPU. At model-load time a CUDA load that still fails self-heals to CPU `int8` instead of crashing the worker — the active tab shows a GPU/CPU badge and (once) a "running on CPU (slower)" warning. |
| `compute_type` | string | `"int8"` | `faster-whisper` compute type. Common values: `int8`, `int8_float16`, `float16`, `float32`. `int8` is the smallest/fastest on CPU; `float16` is preferred on GPU. |
| `cpu_warning_shown` | bool | `false` | Set to `true` after the one-time "running on CPU (slower)" warning has been shown, so it never repeats. The warning only appears when a GPU was detected-but-unusable or a CUDA→CPU downgrade happened — never on a genuine CPU-only machine. |
| `parallel_workers` | int | `2` | Maximum simultaneous transcription worker subprocesses. Each loads the model and uses ~3 GB RAM (or VRAM on GPU). |
| `download_folder` | string | `""` | Default destination for video downloads. Updated by the Folder Browse button. |
| `download_subtitles_enabled` | bool | `false` | Last state of the subtitle checkbox on the Download Videos tab |
| `download_subtitle_lang` | string | `"Automatic"` | Last-selected subtitle language (display name from `SUBTITLE_LANGUAGES`, not the code). |
| `theme` | string | `"dark"` | `"light"` / `"dark"` / `"system"` — applied via `sv_ttk` (Phase 1.1). `"system"` falls back to `"dark"` if the optional `darkdetect` package is not installed. |
| `log_level` | string | `"INFO"` | Python logging level for the file handler (Phase 1.3) |
| `auto_update_yt_dlp` | bool | `false` | Phase 0 fix to AUDIT A1: yt-dlp's `--update` is now opt-in and gated to once per launch (with `last_yt_dlp_update_check`). When this is `false`, downloads never wait on `--update`. |
| `last_yt_dlp_update_check` | string (ISO date) | `""` | Timestamp of the last update attempt (used by the once-per-day guard inside `maybe_update_yt_dlp`) |
| `update_check_enabled` | bool | `true` | Opt-in GitHub "update available" check (`core.updates`). When on, a quiet launch check runs at most once per day (throttled by `last_update_check`) and stays SILENT unless a newer release exists — never nagging when up to date, offline, or when the repo is private (a 404 is swallowed). When a newer release is found it offers to open the download page. It is **notify-only**: it never auto-downloads or auto-installs. Set to `false` to disable the quiet launch check; the **Help → Check for updates...** menu item still runs on demand. |
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
one time), mirroring the on-demand openai-whisper backend.

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

### Telemetry stats (P4-4) — opt-in, privacy

After each transcription finishes (any terminal status), the app can POST a small telemetry record to `stats_url`. **This is OFF by default and gated strictly on `telemetry_opt_in`** (the same flag the launch-ping telemetry uses; toggled in **Advanced → telemetry opt-in**). Nothing is sent unless BOTH `telemetry_opt_in` is true AND `stats_url` is non-empty.

What is sent (form-encoded, by `core.stats.post_stats_async` on a daemon thread, short timeout, all errors swallowed — it never blocks or crashes a transcription):

| Field | Source |
|---|---|
| `file_name` | basename of the source file (no path) |
| `model` | the model name / slug used |
| `language` | detected language |
| `audio_duration` | best-effort, the last segment's end time (s) |
| `transcription_time` | wall-clock AI compute time (s) |
| `word_count` | total words in the transcript |
| `status` | finished / error / cancelled / … |

The server (`stats/transcription_stats.php`, a deliverable in this repo) ADDITIONALLY records the request's **client IP** and a **geoip lookup** (country + the full geoip JSON, fetched server-side from `https://smch.ir/stats/geoip/index.php?ip={ip}`). Because IP + filename are involved, the opt-in gate is mandatory. The same `word_count` is also stored locally in `history.db` (`transcriptions.word_count`, added by an idempotent migration) regardless of opt-in.

The payload builder `core.stats.build_stats_payload(...)` is a pure function (no I/O), and `post_stats_async` re-checks the opt-in itself so a mistaken direct call can never leak data.

### Transcript conversion (P4-3)

Not a config key — a **File → Convert transcript…** menu action backed by the Tk-free `core.convert`. It parses an existing transcript (`.srt` / `.vtt` / `.tsv` / `.json`, plus `.otr` import) into the faster-whisper JSON segment list (the universal middle format) and re-emits any text format from the writers registry (`srt` / `vtt` / `tsv` / `txt` / `json` / `lrc` / `md`). `.txt` is **output-only** (no timestamps to parse back). Pure seams: `parse_to_segments(path)` (auto-detects by extension then content) and `convert_file(in, out_format, out_path=None)` (writes beside the input; never clobbers the source on an in-place re-emit).

## Coming in later phases

| Field | Type | Default | Description |
|---|---|---|---|
| `crash_reporting` | bool | `false` | Opt-in to Sentry crash reports (ROADMAP 1.8) |

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
