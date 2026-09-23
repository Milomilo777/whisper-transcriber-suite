from __future__ import annotations

import copy
import http.client
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import platformdirs

# Module-level lock serialises concurrent save_config calls — on
# Windows os.replace fails with PermissionError when another thread
# is also mid-replace on the same path; the lock collapses the race.
_SAVE_LOCK = threading.Lock()

logger = logging.getLogger(__name__)

APP_NAME = "WhisperTranscriberSuite"
APP_AUTHOR = False  # platformdirs: omit author segment on Windows


def _default_transcribe_backend() -> str:
    """Default engine: always the offline one (faster-whisper).

    Until 2026-08 a build could drop a maintainer-owned Google Cloud
    service-account key at ``<resource_base>/creds/gcloud_stt.json``, and this
    function flipped the default engine to ``google_cloud_stt`` whenever that
    file existed. That shipped one shared credential inside a public
    distribution — extractable by anyone who downloaded it, billed to the
    maintainer's project, and answerable for whatever it was used to
    transcribe. The key is revoked and is no longer bundled (see
    ``docs/CLOUD_STT_GOOGLE.md`` and ``SECURITY.md``), so the default is now
    unconditional: the app starts offline and a cloud backend is only ever
    reached by an explicit user choice with the user's own credentials.

    A user's saved choice in ``config.json`` still overrides this via the
    local-config merge layer.
    """
    return "faster_whisper"


DEFAULT_CONFIG = {
    "model": {
        "name": "faster-whisper-large-v3",
        "url": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip",
        "md5": "https://smch.ir/models/models--Systran--faster-whisper-large-v3.zip.md5",
        "hf_repo": "Systran/faster-whisper-large-v3",
    },
    "model_path": "",
    "device": "auto",
    "compute_type": "int8",
    "parallel_workers": 2,
    "download_folder": "",
    "download_subtitles_enabled": False,
    "download_subtitle_lang": "Automatic",
    "auto_update_yt_dlp": False,
    "last_yt_dlp_update_check": "",
    # Optional, opt-in GitHub "update available" check (core.updates).
    # When enabled, a quiet launch check (once per day, throttled via
    # last_update_check) and a Help-menu manual check ask GitHub for the
    # latest release tag and offer to open the download page — they NEVER
    # auto-download or auto-install, and a private-repo 404 / offline box
    # fails silently. last_update_check is the ISO date (YYYY-MM-DD) of
    # the last quiet check, used only for the once-per-day throttle.
    "update_check_enabled": True,
    "last_update_check": "",
    # Browser to read cookies from for yt-dlp, so login-walled / age-gated
    # content downloads using the user's logged-in session (Facebook,
    # Instagram, TikTok stories; some YouTube Shorts). Empty = off. One of
    # brave/chrome/chromium/edge/firefox/opera/safari/vivaldi/whale,
    # optionally with yt-dlp's :PROFILE suffix.
    "cookies_from_browser": "",
    "theme": "light",
    "log_level": "INFO",
    # R3: set once the first time a one-time "running on CPU (slower)"
    # warning has been shown, so it never nags again. Defaulted here so
    # reads are always a plain bool (no KeyError / wrong-type trap).
    "cpu_warning_shown": False,
    # Phase 2a — Whisper masterpiece
    "vad_enabled": True,
    "vad_min_silence_ms": 500,
    "vad_threshold": 0.5,
    "vad_speech_pad_ms": 400,
    "word_timestamps": False,
    "output_formats": ["srt", "json"],
    "batch_size": 16,
    "initial_prompt": "",
    "hotwords": "",
    # Phase 3a — yt-dlp killer features
    "auto_transcribe_after_download": False,
    "sponsorblock_categories": [],
    # v0.7.1 — diarization (off by default; opt-in via Transcribe tab)
    "diarization_enabled": False,
    "diarization_num_speakers": -1,         # -1 = auto-cluster
    "diarization_cluster_threshold": 0.5,
    # v0.7.1 — Transcribe tab quick options
    "transcribe_language": "Auto",   # display name; resolves to code at task build
    # v0.7.1 — UX persistence + new features
    "window_geometry": "",
    "chime_on_complete": True,
    # v0.7.1 — filename templating; tokens {base}, {ext}, {lang}, {date}, {speaker_count}
    "output_filename_template": "{base}.{ext}",
    # v0.7.1 — watched folder (off by default)
    "watched_folder": "",
    "watched_folder_enabled": False,
    # v0.7.1 — backend selection. Always offline faster_whisper by default;
    # a bundled key can no longer flip it (see _default_transcribe_backend
    # and SECURITY.md). cloud_stt/google_cloud_stt/whisper_cpp/nvidia_asr are
    # opt-in; a user's saved choice always wins via the local-config merge
    # layer.
    "transcribe_backend": _default_transcribe_backend(),
    # OPTIONAL cloud Speech-to-Text backend (Google Gemini API). Off
    # unless the user selects transcribe_backend="cloud_stt". The API
    # key is stored in CLEARTEXT here, consistent with how cookies and
    # paths are already stored — config.json lives per-user under
    # %LOCALAPPDATA%\WhisperTranscriberSuite and is not encrypted. Using this
    # backend UPLOADS audio to Google (breaks the offline guarantee).
    # cloud_stt_minutes_used is tracked LOCALLY (the $ free credit is
    # NOT readable from an API key); cloud_stt_free_minutes_cap is just
    # the informational free-tier figure shown in the UI.
    "cloud_stt_api_key": "",
    "cloud_stt_model": "gemini-3.5-flash",
    "cloud_stt_minutes_used": 0.0,
    "cloud_stt_free_minutes_cap": 60,
    "cloud_stt_chunk_seconds": 480,
    # OPTIONAL REAL Google **Cloud** Speech-to-Text v2 backend (distinct
    # from the Gemini-API cloud_stt above). Off unless the user selects
    # transcribe_backend="google_cloud_stt". Unlike Gemini, it authenticates
    # with a service-account JSON FILE (NOT a pasted key) — the user picks
    # the .json they downloaded from the Google Cloud console; project_id is
    # read out of that file. Using this backend UPLOADS audio to Google
    # (breaks the offline guarantee).
    #   gcloud_stt_credentials_json: absolute path to the service-account
    #     JSON key file (empty = not configured; the backend reports a clear
    #     "pick your JSON file" error).
    #   gcloud_stt_model: v2 model name. Default "chirp_2": the app's default
    #     Transcribe language is "Auto", and chirp_2 supports BOTH auto
    #     language detection AND explicit BCP-47 codes (the older "long" model
    #     rejects "auto"). "short"/"long"/"telephony" also valid. Configurable
    #     so a renamed/new model needs no code change.
    #   gcloud_stt_location: API location/region. Default "us-central1":
    #     chirp_2 is a REGIONAL model and does NOT exist in "global", so the
    #     shipped default must be a region. "global" works for "long"/"short";
    #     any non-"global" value uses the matching regional endpoint.
    #   gcloud_stt_batch_mode: False = STANDARD online chunked-inline recognise
    #     (~$0.016/min, no bucket needed, the default). True = cheaper GCS
    #     BATCH (~$0.004/min, slower) — REQUIRES gcloud_stt_bucket.
    #   gcloud_stt_bucket: a Google Cloud Storage bucket name the service
    #     account can write to; required only for batch mode (the decoded
    #     audio is uploaded there, transcribed, then the blob is deleted).
    #   gcloud_stt_diarization: enable speaker diarization (adds a per-segment
    #     "speaker" label). gcloud_stt_min/max_speakers bound the count
    #     (0 = let Google decide).
    #   gcloud_stt_chunk_seconds: STANDARD-mode chunk length; kept under the
    #     ~1-minute online-recognise inline cap.
    #   gcloud_stt_batch_timeout_s: how long to wait on the batch
    #     long-running operation before giving up.
    #   gcloud_stt_minutes_used / gcloud_stt_minutes_month: LOCAL monthly
    #     minute counter (the 60-min/month free tier is NOT readable from a
    #     service-account key, so we track it here and reset on a new month;
    #     the UI displays it). The marker is a "YYYY-MM" string.
    # OPTIONAL local NVIDIA Parakeet / FastConformer ASR backend, run through
    # Hugging Face transformers. Off unless transcribe_backend="nvidia_asr".
    # Runs fully ON THIS MACHINE (no audio leaves the device). transformers +
    # torch are heavy and install on first use (NOT bundled, like the other
    # torch features). The default is the transformers-native multilingual
    # FastConformer model; point model_id at any transformers
    # automatic-speech-recognition model (a HF repo id OR a local dir path).
    # (NVIDIA's exact nemotron-3.5-asr checkpoint ships only a NeMo .nemo file
    # which transformers cannot load, so its Parakeet sibling is the default.)
    #   nvidia_asr_model_id      : HF repo id OR local dir path of the model.
    #   nvidia_asr_device        : "auto" | "cpu" | "cuda".
    #   nvidia_asr_dtype         : "auto" | "float32" | "float16".
    #   nvidia_asr_chunk_seconds : audio window length (seconds) per inference;
    #     also the segment granularity when the model returns text-only (no word
    #     timestamps), so smaller = finer subtitles.
    "nvidia_asr_model_id": "nvidia/parakeet-tdt-0.6b-v3",
    "nvidia_asr_device": "auto",
    "nvidia_asr_dtype": "auto",
    "nvidia_asr_chunk_seconds": 30,
    "gcloud_stt_credentials_json": "",
    "gcloud_stt_model": "chirp_2",
    "gcloud_stt_location": "us-central1",
    "gcloud_stt_batch_mode": False,
    "gcloud_stt_bucket": "",
    "gcloud_stt_diarization": False,
    "gcloud_stt_min_speakers": 0,
    "gcloud_stt_max_speakers": 0,
    "gcloud_stt_chunk_seconds": 55,
    "gcloud_stt_batch_timeout_s": 3600,
    "gcloud_stt_minutes_used": 0.0,
    "gcloud_stt_minutes_month": "",
    "gcloud_stt_free_minutes_cap": 60,
    # v0.8 — hallucination detector (BoH + repetition + optional VAD
    # disagreement). Flags segments in the JSON output and the viewer.
    "hallucination_detect_enabled": True,
    # v0.8 — model picker. Slug into core.model_manager.MODEL_REGISTRY.
    # When the user changes this, the Advanced dialog also rewrites
    # ``model`` + ``model_path`` so ensure_model downloads the new one.
    "whisper_model": "large-v3",
    # Live tab model: a catalog slug (default "tiny"), "auto" (small model
    # on CPU, main model on GPU) or "main" (same as whisper_model). See
    # core/live_model.py.
    "live_model": "tiny",
    # v0.8 Phase 2 — Demucs vocal-separation pre-process (off by default;
    # heavy dep, large model). When True + demucs installed, transcribe
    # pipeline runs the input through Demucs first and feeds Whisper the
    # vocals stem.
    "demucs_enabled": False,
    # Cap (MB) on the demucs vocals-separation cache; oldest stems are
    # evicted past this. 0 disables eviction. See core.separator.prune_cache.
    "demucs_cache_mb": 2048,
    # v1.6 — adaptive audio denoise pre-process (ffmpeg only, no extra
    # dependency). Off by default: it costs one measurement pass plus one
    # filter pass per file, which nobody asked for on already-clean audio.
    # When on, core.denoise MEASURES the source first and leaves clean
    # audio completely untouched — over-denoising makes Whisper worse.
    "denoise_enabled": False,
    # "auto" picks off/light/medium/strong from the measured speech-to-
    # noise ratio; naming a level forces it regardless of measurement.
    "denoise_level": "auto",
    # Cap (MB) on the denoised-render cache; oldest are evicted past this.
    # 0 disables eviction. See core.denoise.prune_cache.
    "denoise_cache_mb": 1024,
    # v0.8 Phase 2 — AI Layer. ``ai_enabled`` is the global on/off; the
    # actual model file lives at ``ai_model_path`` (empty = use the
    # default cache path under ``user_cache_dir()/llm/``).
    "ai_enabled": False,
    "ai_model_path": "",
    # Which LLM implementation ``ai_enabled`` turns on. "local" (default)
    # is the bundled-on-first-use Qwen2.5-1.5B above; "remote" sends the
    # same 4 prompts (summarise/action items/ask/translate) to a
    # user-configured OpenAI-compatible ``/chat/completions`` endpoint —
    # the real OpenAI API, or a self-hosted server (Ollama/LM
    # Studio/vLLM) or third-party proxy (OpenRouter). See core/llm.py's
    # RemoteLLMRunner. Local stays the default so a fresh install has no
    # network dependency for this feature.
    "llm_provider": "local",
    # llm_remote_model is deliberately blank — the whole point of "remote"
    # is the user names their OWN model (this app has no business
    # defaulting to a specific paid model id on their account). The
    # Advanced dialog's help text shows examples (gpt-4o-mini, etc.).
    "llm_remote_base_url": "https://api.openai.com/v1",
    "llm_remote_model": "",
    # Stored in CLEARTEXT here, consistent with cloud_stt_api_key /
    # gcloud_stt_credentials_json / server_token above — config.json is
    # per-user under %LOCALAPPDATA%\WhisperTranscriberSuite and is not encrypted.
    "llm_remote_api_key": "",
    # v0.8 Phase 3 — auto-chapter markers in the JSON sidecar. Pure
    # heuristic by default; if ai_enabled + LLM loaded, chapter titles
    # are LLM-generated.
    "auto_chapters_enabled": True,
    "chapter_min_seconds": 60.0,
    "chapter_gap_seconds": 2.5,
    # v0.8 Phase 3 — cross-file voice fingerprint matching. When True
    # AND pyannote is installed AND voices.db has enrolled speakers,
    # the diariser's per-file SPEAKER_NN labels are renamed to the
    # matching enrolled names.
    "voiceprint_enabled": True,
    # Model Hub folder — the parent directory that holds one or more
    # ``models--Vendor--name`` subdirectories. Empty by default so
    # ``app.dialogs.hub_setup`` fires its first-run picker. The
    # picker pre-fills ``core.hub.default_hub_folder()`` =
    # ``%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models`` (a per-user,
    # always-writable location — NOT under the Program Files install
    # dir, which is not writable for a standard user).
    # ``model_path`` (above) remains as a per-model override for users
    # with an existing config; new installs derive ``model_path`` from
    # ``hub_folder + model.name``.
    "hub_folder": "",
    # Video Tiling tab — persisted UI choices for the tiling engine
    # (core.tiling.TilingController). quality is a band from
    # core.tiling.QUALITY_CHOICES ("Auto"/"1080p"/…/"144p"); multi_monitor
    # fans the one download out to one ffplay per selected monitor; the
    # selected list holds spatial monitor indices from core.monitors
    # (0 = left-most); auto_restart reconnects with backoff on a drop.
    "tiling_quality": "Auto",
    "tiling_mute": False,
    "tiling_multi_monitor": False,
    "tiling_selected_monitors": [],
    "tiling_auto_restart": True,
    # Clone Your Voice / Text to Voice tab — independent of every setting
    # above. consent_accepted gates the one-time confirmation dialog
    # (own-voice-or-permission + ethics note) so it only ever asks once
    # per profile, not on every generation.
    "voice_clone": {
        "consent_accepted": False,
    },
    # Optional local-network / web HTTP job server (``gui.py serve`` and the
    # one-click toggle on the Web / LAN access tab).
    # Defaulted here so reads never KeyError and pyright sees the type.
    # ``server_port`` is the default listen port; ``server_max_upload_mb``
    # caps a single upload (the worker's 1 MB command guard does NOT cover
    # browser uploads). The server binds loopback by default — LAN access
    # is an explicit opt-in (the only path that triggers the Windows firewall
    # prompt):
    #   server_share_lan  — when True the GUI toggle binds 0.0.0.0 (all
    #     interfaces, so other devices on the network can reach it) instead
    #     of 127.0.0.1 (this machine only). Persisted from the
    #     "Share on local network" checkbox. The CLI uses --lan instead.
    #   server_token  — optional shared secret. When non-empty, every request
    #     must present it (X-Auth-Token header or ?token= query). Stored in
    #     CLEARTEXT here, consistent with cookies / API keys — config.json is
    #     per-user under %LOCALAPPDATA%\WhisperTranscriberSuite and is not encrypted.
    "server_port": 8765,
    "server_max_upload_mb": 512,
    "server_share_lan": False,
    "server_token": "",
    #   server_https_enabled — when True the server wraps its socket in TLS
    #     using a self-signed certificate generated once under
    #     user_data_dir()/server/ (see core.server.tls). OFF by default,
    #     matching --lan: HTTPS is an explicit opt-in. The CLI equivalent is
    #     --https.
    #   server_webhook_url — optional URL to POST a small JSON completion
    #     payload to when a job finishes (success or failure). Empty = off.
    #     The POST is fire-and-forget on a daemon thread and is refused by
    #     the same SSRF guard (core.server.jobs.is_safe_url) the inbound URL
    #     path uses, so it can never target loopback / link-local /
    #     cloud-metadata addresses. The CLI equivalent is --webhook.
    "server_https_enabled": False,
    "server_webhook_url": "",
    # Window / privacy toggles set on the Advanced dialog's General tab and
    # read at runtime. Defaulted here (both OFF) so reads are always a plain
    # bool and they get the same merge + type-coercion protection as every
    # other key:
    #   minimise_to_tray  — when True the window's X button hides to the system
    #     tray instead of exiting (app.py close handler + widgets.tray).
    #   telemetry_opt_in  — gates anonymous usage stats (core.stats POSTs a
    #     per-transcription row to stats_url) plus the optional launch ping /
    #     Sentry crash reports. ON by default so opted-in usage stats flow for
    #     this distribution; a user can turn it off in the Advanced dialog. The
    #     launch ping and Sentry stay inert unless their WHISPER_TELEMETRY_URL /
    #     SENTRY_DSN env vars are ALSO set (a plain build sets neither), so this
    #     default only activates the stats_url POST.
    "minimise_to_tray": False,
    "telemetry_opt_in": True,
    # --- Three-level config: ONLINE layer (P4-1) -------------------------
    # URL of an app-level JSON config the maintainer hosts, fetched on
    # startup so APP-LEVEL settings (model catalog, stats endpoint, latest
    # version, ffplay download links) can change WITHOUT redistributing the
    # program. The fetch is best-effort: a short timeout, a cached copy
    # under user_cache_dir(), and a fall-through to the hard-coded defaults
    # when offline — it NEVER blocks or crashes startup.
    #
    # OWNER ACTION: replace this placeholder with the real URL on the
    # maintainer's host (e.g. a raw GitHub file or this smch.ir path). Until
    # a valid JSON lives there, the app silently uses the built-in defaults.
    "config_url": "https://smch.ir/whisper/app_config.json",
    # Catalog of selectable Whisper models, in the same shape as
    # core.model_manager.MODEL_REGISTRY (slug → {label, name, url, md5,
    # hf_repo, approx_size_gb, info}). ``url``/``md5`` may be "" for a model
    # with no smch.ir mirror — ``ensure_model`` then downloads straight from
    # ``hf_repo``. Empty by default: the built-in MODEL_REGISTRY is the
    # baseline. The ONLINE config can ADD/OVERRIDE entries here so new models
    # ship without an app update; a LOCAL override file can pin its own.
    "model_catalog": {},
    # App-level URLs/info that the ONLINE config is allowed to set. Defaulted
    # here so reads never KeyError. ``stats_url`` is the usage-stats POST
    # endpoint, defaulted to the project's smch.ir collector so opted-in
    # stats work out of the box (still a no-op unless ``telemetry_opt_in``
    # is on — see core.stats.post_stats_async); ``latest_version`` is the
    # newest published version string; ``ffplay_downloads`` maps a platform
    # key ("windows"/"macos"/...) to a download URL for the Video-Tiling
    # ffplay binary (which is NOT bundled). All three are SAFE for the online
    # layer to control.
    "stats_url": "https://smch.ir/stats/transcription_stats.php",
    "latest_version": "",
    # ffplay (Video Tiling) is NOT bundled. When it's missing, the app can
    # auto-download it from the platform's URL here (see
    # core.tiling.download_ffplay). The value maps a platform key
    # ("windows"/"macos"/"linux") to either a DIRECT ffplay[.exe] URL or a
    # .zip of a full ffmpeg build that CONTAINS ffplay[.exe] (the helper
    # extracts just ffplay).
    #
    # OWNER ACTION — VERIFY / OVERRIDE THESE VIA THE ONLINE CONFIG. The
    # defaults below point at well-known public static-ffmpeg builds, but
    # third-party URLs rot and their archive layout can change. Confirm they
    # still resolve to an ffmpeg build that includes ffplay, then host the
    # canonical values in the online app config (config_url) so they can be
    # corrected without an app update.
    #
    # The download helper only handles a direct ffplay[.exe] URL or a .ZIP
    # that contains it (stdlib zipfile) — NOT .7z / .tar.xz. The Windows
    # default below is a BtbN full build shipped as a .zip (contains
    # bin/ffplay.exe); macOS evermeet.cx serves a per-binary ffplay .zip.
    "ffplay_downloads": {
        "windows": (
            "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
            "ffmpeg-master-latest-win64-gpl.zip"
        ),
        "macos": "https://evermeet.cx/ffmpeg/getrelease/ffplay/zip",
        "linux": "",
    },
}


# One-click "this recording is noisy" bundle for the Advanced dialog's AI
# Layer section — sets several independent knobs (VAD / denoise /
# hallucination) to values reasonable for non-studio audio in one action,
# instead of making the user hand-tune five sliders across three sections.
# Reasoning per key:
#   vad_threshold  — raised from the 0.5 default to 0.6: a noisy recording
#     has few TRUE silences, so the risk is background noise getting
#     misclassified AS speech (which then feeds the hallucination
#     detector junk), not real speech getting skipped. A higher
#     confidence bar before calling something "speech" is the safer
#     direction here.
#   denoise_level  — fixed at "medium" rather than "auto": "auto" measures
#     the file and may pick "off" for material that only sounds noisy to
#     a human ear; the user clicking this button IS the signal that
#     cleanup should actually run.
#   demucs_enabled is deliberately NOT part of this preset — it's a heavy
#     opt-in dependency (pulls torch) and a big download; a one-click
#     preset silently starting that is a worse surprise than leaving it
#     for the user to opt into separately.
NOISY_AUDIO_PRESET: dict[str, Any] = {
    "vad_enabled": True,
    "vad_threshold": 0.6,
    "denoise_enabled": True,
    "denoise_level": "medium",
    "hallucination_detect_enabled": True,
}


# Keys the ONLINE config is allowed to set/override. The online layer must
# NEVER touch user-private / local-only settings — paths, API keys,
# credentials, the model hub folder, or any user preference. Only this
# APP-LEVEL allowlist is honoured from the fetched JSON; everything else in
# the online payload is dropped. (Precedence is still local > online >
# hard-coded — see ``merge_config_sources``.)
ONLINE_ALLOWED_KEYS: frozenset[str] = frozenset({
    "model_catalog",
    "stats_url",
    "latest_version",
    "ffplay_downloads",
})


# Hard cap on the online-config response body. config_url defaults to a
# third-party host; a compromised/MITM endpoint streaming a multi-GB body
# would otherwise be buffered whole into memory at startup. 2 MB is far
# above any legitimate app-config JSON, so an oversized body is treated as
# hostile and we fall through to the cache instead of parsing it.
MAX_CONFIG_BYTES = 2 * 1024 * 1024


def _reject_nonfinite(value: str) -> float:
    """``json`` ``parse_constant`` hook that rejects Infinity/-Infinity/NaN.

    Python's JSON parser accepts these non-standard literals by default,
    which then poison numeric coercion downstream (``int(float('inf'))``
    raises ``OverflowError``; NaN compares false to everything). Raising
    here turns such a payload into a ``ValueError``, so the caller treats
    the file as corrupt and reverts to defaults / the cache.
    """
    raise ValueError(f"non-finite JSON literal not allowed: {value!r}")


def online_cache_path() -> Path:
    """Path of the cached last-good online config under the cache dir."""
    return user_cache_dir() / "app_config_cache.json"


# Process-lifetime memo of the fetched online config, so the many
# ``load_config()`` callers in one process (worker import, backends,
# dialogs) don't each pay a network round-trip / timeout. Keyed by URL.
# ``refresh_online_config()`` clears it for an explicit re-check.
_ONLINE_MEMO: dict[str, dict[str, Any]] = {}
_ONLINE_MEMO_LOCK = threading.Lock()


def refresh_online_config() -> None:
    """Forget the in-process online-config memo so the next load re-fetches."""
    with _ONLINE_MEMO_LOCK:
        _ONLINE_MEMO.clear()


def _legacy_config_path() -> str:
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
    return os.path.abspath(os.path.join(base, "..", "config.json"))


def user_config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))


def user_cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME, APP_AUTHOR))


def user_log_dir() -> Path:
    return Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))


def user_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def config_path() -> str:
    return str(user_config_dir() / "config.json")


def migrate_config_location() -> str:
    """Move a legacy next-to-source config.json into the platformdirs path.

    Returns the new path. Idempotent: if the new file already exists, the legacy
    one is renamed to .migrated.bak and not copied. Safe to call on every launch.
    """
    new_path = config_path()
    legacy = _legacy_config_path()
    try:
        user_config_dir().mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # A read-only profile / ACL that blocks the config dir (or a stray
        # FILE occupying that path) must not crash launch: load_config()
        # then degrades to the defaults + online + project layers, exactly
        # like every other unreadable-config path. Saving settings will
        # still surface its own error at save time.
        logger.warning(
            "Could not create config dir %s (%s); using defaults",
            user_config_dir(), e,
        )
        return new_path

    if not os.path.exists(legacy):
        return new_path
    if os.path.abspath(legacy) == os.path.abspath(new_path):
        return new_path

    if not os.path.exists(new_path):
        try:
            shutil.copy2(legacy, new_path)
            logger.info("Migrated legacy config.json from %s to %s", legacy, new_path)
        except OSError as e:
            logger.error("Failed to migrate legacy config: %s", e)
            return new_path

    backup = legacy + ".migrated.bak"
    try:
        if os.path.exists(backup):
            os.unlink(backup)
        os.replace(legacy, backup)
        logger.info("Renamed legacy config to %s", backup)
    except OSError as e:
        logger.exception(
            "Could not rename legacy config to .migrated.bak (path=%s): %s",
            legacy, e,
        )

    return new_path


# Pre-rebrand APP_NAME (renamed 2026-08-23). Only the Windows installer
# carried a migration for it, so Portable / run-from-source / macOS /
# Linux users silently started on an empty profile: no settings, no
# history, and every already-downloaded model reported "not downloaded".
LEGACY_APP_NAME = "WhisperProject"
_LEGACY_DATA_FILES = ("history.db", "hardware.json", "search.db")
# Large, non-configurable model / recording caches. Moved (one atomic
# same-volume rename each), never copied -- a copy of several GB would
# stall launch. A folder that already exists under the new name is left
# alone.
_LEGACY_CACHE_SUBDIRS = ("whisper_cpp", "llm", "live", "demucs")
_legacy_migration_done = False


def _legacy_app_dirs() -> dict[str, Path] | None:
    """Per-user dirs of the pre-rebrand app. Patched to None by the test suite."""
    return {
        "config": Path(platformdirs.user_config_dir(LEGACY_APP_NAME, APP_AUTHOR)),
        "data": Path(platformdirs.user_data_dir(LEGACY_APP_NAME, APP_AUTHOR)),
        "cache": Path(platformdirs.user_cache_dir(LEGACY_APP_NAME, APP_AUTHOR)),
    }


def _has_model_folders(hub: Path) -> bool:
    try:
        return any(p.is_dir() and p.name.startswith("models--") for p in hub.iterdir())
    except OSError:
        return False


def _set_local_hub_folder(value: str) -> None:
    """Write only ``hub_folder`` into config.json, leaving every other key as-is."""
    with _SAVE_LOCK:
        path = config_path()
        local: dict[str, Any] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return
            local = loaded
        local["hub_folder"] = value
        directory = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(local, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def migrate_legacy_app_data() -> None:
    """Carry data over from the pre-rebrand ``WhisperProject`` profile.

    Runs once per process from ``load_config``. Never deletes anything
    from the old profile, and every step is individually best-effort:

    1. No new config.json yet -> copy config.json + history/hardware/search
       files (same set as the installer's MigrateOldAppData).
    2. Hub still at the new, model-less default while the old hub has
       models -> point ``hub_folder`` at the old hub (no multi-GB copy).
       Independent of step 1, so it also rescues a profile that a
       previous launch already created empty.
    3. Move the non-configurable caches in ``_LEGACY_CACHE_SUBDIRS``.
    """
    global _legacy_migration_done
    if _legacy_migration_done:
        return
    _legacy_migration_done = True
    try:
        legacy = _legacy_app_dirs()
    except Exception:  # noqa: BLE001
        return
    if not legacy or not legacy["config"].is_dir():
        return

    new_config = Path(config_path())
    legacy_config = legacy["config"] / "config.json"
    if legacy_config.is_file() and not new_config.exists():
        copies = [(legacy_config, new_config)] + [
            (legacy["data"] / name, user_data_dir() / name)
            for name in _LEGACY_DATA_FILES
        ]
        # SQLite sidecars hold not-yet-checkpointed rows.
        for db in ("history.db", "search.db"):
            for suffix in ("-wal", "-shm"):
                copies.append(
                    (legacy["data"] / (db + suffix), user_data_dir() / (db + suffix))
                )
        for src, dst in copies:
            if not src.is_file() or dst.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.info("Migrated %s -> %s", src, dst)
            except OSError as e:
                logger.warning("Could not migrate %s: %s", src, e)

    try:
        from .hub import default_hub_folder

        legacy_hub = legacy["cache"] / "models"
        new_default = default_hub_folder()
        local = _read_local_config()
        hub = str(local.get("hub_folder") or "").strip()
        at_default = not hub or os.path.normcase(
            os.path.abspath(hub)
        ) == os.path.normcase(os.path.abspath(new_default))
        if (
            at_default
            and not _has_model_folders(new_default)
            and _has_model_folders(legacy_hub)
        ):
            _set_local_hub_folder(str(legacy_hub))
            logger.info("Pointed hub_folder at pre-rebrand model hub %s", legacy_hub)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not reuse pre-rebrand model hub: %s", e)

    for name in _LEGACY_CACHE_SUBDIRS:
        src = legacy["cache"] / name
        dst = user_cache_dir() / name
        if not src.is_dir() or os.path.lexists(dst):
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            logger.info("Moved pre-rebrand cache %s -> %s", src, dst)
        except OSError as e:
            logger.warning("Could not move pre-rebrand cache %s: %s", src, e)


def _drive_is_mounted(path: str | Path) -> bool:
    if os.name != "nt":
        return True
    try:
        p = Path(str(path))
    except (TypeError, ValueError):
        return False
    if not p.drive:
        return True
    # UNC paths (``\\server\share\...``) — checking exists() on a
    # disconnected share can block for the SMB resolution timeout
    # (~30 s). Treat them as available; downstream code surfaces
    # the I/O error if the share is really gone. The slow probe is
    # worse than a deferred error message.
    drive = p.drive
    if drive.startswith("\\\\") or drive.startswith("//"):
        return True
    return Path(drive + os.sep).exists()


def _apply_runtime_fallbacks(config: dict[str, Any]) -> dict[str, Any]:
    # Migration (v0.8 hub folder): if the user has a legacy
    # ``model_path`` set but no ``hub_folder``, derive the hub from
    # the parent directory of the model. This keeps existing
    # installs working without forcing the first-run dialog when
    # the user has clearly already pointed the app at a real model
    # folder. We don't clear model_path — it stays as an explicit
    # override per resolve order in core.hub.
    from . import hub as _hub  # local import to avoid bootstrap cycle
    model_path = (config.get("model_path") or "").strip()
    hub_folder = (config.get("hub_folder") or "").strip()
    if model_path and not hub_folder:
        derived = _hub.derive_hub_from_model_path(model_path)
        if derived:
            config["hub_folder"] = derived
            hub_folder = derived
            logger.info(
                "Migrated legacy model_path → hub_folder=%s "
                "(model_path kept as explicit override).",
                derived,
            )

    # Compute model_path on the fly when it's missing or unreachable,
    # using the hub folder when configured. Resolution order:
    # explicit model_path wins → hub_folder + model_name → the same
    # default_hub_folder() value the first-run dialog suggests.
    #
    # Using default_hub_folder() as the empty-hub fallback fixes a
    # re-download race: the hub-setup dialog is asynchronous, so the
    # worker subprocess starts before the user has clicked OK. If the
    # worker resolved a different path than the dialog's default, the
    # next launch (with hub_folder now saved) would resolve a new
    # model_path and trigger a full re-download. Aligning the fallback
    # with default_hub_folder() — now %LOCALAPPDATA%\...\Cache\models —
    # means "accept default" is a no-op for the model location.
    if not model_path or not _drive_is_mounted(model_path):
        # Defensive coercion: the top-level type pass in load_config only
        # validates that ``model`` is a dict, not the nested ``name``. A
        # hand-edited / externally-produced config of ``{"model": {"name":
        # 123}}`` would reach hub.model_folder_for, whose ``name.strip()``
        # then raises AttributeError and crashes launch. Treat any non-string
        # name as absent and fall back to the placeholder.
        raw_name = (config.get("model") or {}).get("name")
        model_name = (raw_name.strip() if isinstance(raw_name, str) else "") \
            or "whisper-model"
        effective_hub = hub_folder or str(_hub.default_hub_folder())
        source = "hub_folder" if hub_folder else "default_hub_fallback"
        try:
            fallback = _hub.model_folder_for(effective_hub, model_name)
        except ValueError:
            fallback = user_cache_dir() / "models" / "whisper-model"
            source = "cache_fallback_unnamed"
        if model_path:
            logger.warning(
                "model_path %r is unreachable on this machine; "
                "using fallback %s. Change a setting in the UI to make it permanent.",
                model_path,
                fallback,
            )
        # Audit B11 / QW-13: surface the resolution decision so a
        # "why is the model loading from this path?" question has a
        # one-line answer in the log.
        logger.info(
            "model_path_resolved path=%s source=%s exists=%s",
            fallback, source, fallback.exists(),
        )
        config["model_path"] = str(fallback)

    download_folder = (config.get("download_folder") or "").strip()
    if download_folder and not _drive_is_mounted(download_folder):
        logger.warning(
            "download_folder %r is unreachable; clearing", download_folder
        )
        config["download_folder"] = ""

    return config


def _merge_with_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
    # Retained as a single-layer (local-over-hardcoded) merge helper. The
    # canonical effective-config path is now the three-layer
    # ``merge_config_sources`` used by ``load_config``; this remains for
    # callers/tests that want only the defaults+local overlay.
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


# --- Three-level merged configuration (P4-1) --------------------------------
#
# Sources, merged with priority ``local file > online config > hard-coded
# DEFAULT_CONFIG`` (a key missing from a higher-priority source falls through
# to the next). The online layer is restricted to ``ONLINE_ALLOWED_KEYS`` so
# it can change APP-LEVEL settings (model catalog, stats endpoint, latest
# version, ffplay links) WITHOUT touching user-private / local-only keys
# (paths, API keys, hub folder, credentials, user preferences). The merge is
# PURE/testable (the three dicts are injected); fetching the online layer is a
# separate, best-effort helper that caches its last good result and never
# blocks or crashes startup.


def merge_config_sources(
    hardcoded: dict[str, Any],
    online: dict[str, Any] | None,
    local: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge the three config layers by precedence: local > online > hardcoded.

    - ``hardcoded`` is the full baseline (``DEFAULT_CONFIG``).
    - ``online`` is the fetched app-level config; only keys in
      ``ONLINE_ALLOWED_KEYS`` are honoured, so it can never override
      user-private / local-only settings (paths, keys, hub folder, prefs).
    - ``local`` is the user's ``config.json`` (highest priority); it may set
      any key, including the local-only ones the online layer cannot touch.

    Dict-valued keys are deep-merged so a partial override (e.g. one new
    ``model_catalog`` slug, or ``model.name`` alone) keeps the sibling keys
    from the lower layer. A key missing from a higher-priority source falls
    through to the next. The function is pure: inputs are never mutated and a
    fresh dict is returned.
    """
    merged: dict[str, Any] = json.loads(json.dumps(hardcoded))
    if online:
        safe_online = {
            k: v for k, v in online.items() if k in ONLINE_ALLOWED_KEYS
        }
        deep_merge_dicts(merged, safe_online)
    if local:
        deep_merge_dicts(merged, local)
    return merged


def fetch_online_config(
    url: str,
    *,
    timeout: float = 4.0,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch the app-level online config JSON, with a cache fallback.

    Best-effort and FAIL-SAFE — it never raises and never blocks startup for
    long:
      1. GET ``url`` (stdlib urllib only) with a short ``timeout``.
      2. On a successful JSON-object response, write it to ``cache_path``
         (the last-good cache) and return it.
      3. On ANY failure (offline, timeout, HTTP error, bad JSON), fall back
         to the cached copy at ``cache_path`` if present and valid.
      4. If there is no usable cache either, return ``{}`` — the caller then
         uses only the hard-coded + local layers.

    ``cache_path`` defaults to ``online_cache_path()``. An empty ``url``
    short-circuits to the cache (then to ``{}``), so disabling the online
    layer is just clearing ``config_url``.
    """
    if cache_path is None:
        cache_path = online_cache_path()

    # Refuse non-http(s) config URLs: a file:// / ftp:// / custom scheme would let
    # urlopen read a local file (or reach an internal host — SSRF) and cache it.
    if url and urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
        logger.warning(
            "online config_url %r uses a non-http(s) scheme; refusing it", url
        )
        url = ""

    if url:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "WhisperTranscriberSuite"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # Reject an oversized body BEFORE buffering it whole: a
                # hostile/MITM host could stream multiple GB and exhaust
                # memory on the launch path. The Content-Length (if sent)
                # is an early-out; the capped read defends against a body
                # that lies about or omits its length. ``getattr`` keeps
                # this tolerant of a response object without ``.headers``.
                headers = getattr(resp, "headers", None)
                clen = headers.get("Content-Length") if headers is not None else None
                if isinstance(clen, str) and clen.strip().isdigit():
                    if int(clen) > MAX_CONFIG_BYTES:
                        raise ValueError(
                            f"online config Content-Length {clen} exceeds "
                            f"{MAX_CONFIG_BYTES} bytes"
                        )
                raw = resp.read(MAX_CONFIG_BYTES + 1)
            if len(raw) > MAX_CONFIG_BYTES:
                raise ValueError(
                    f"online config body exceeds {MAX_CONFIG_BYTES} bytes"
                )
            data = json.loads(
                raw.decode("utf-8"), parse_constant=_reject_nonfinite
            )
            if isinstance(data, dict):
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(
                        json.dumps(data), encoding="utf-8"
                    )
                except OSError as e:
                    logger.warning("Could not cache online config: %s", e)
                return data
            logger.warning("Online config at %s is not a JSON object", url)
        except (
            urllib.error.URLError,
            OSError,
            ValueError,
            http.client.HTTPException,
            RecursionError,
        ) as e:
            # URLError covers offline / timeout / HTTP errors; ValueError
            # covers a JSON parse failure (and UnicodeDecodeError, a
            # ValueError). http.client.HTTPException (BadStatusLine,
            # IncompleteRead, ...) is NOT an OSError/URLError subclass, but
            # urlopen lets it escape on garbage/truncated responses (broken
            # proxy, captive portal) — it must fall through to the cache
            # too, not crash launch. RecursionError covers a hostile
            # deeply-nested body under the size cap. Fall through to cache.
            logger.info(
                "Online config fetch failed (%s); using cache if available", e
            )

    try:
        cached = json.loads(
            cache_path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite,
        )
        if isinstance(cached, dict):
            return cached
    except (OSError, ValueError, RecursionError):
        # RecursionError: a hostile deeply-nested cache file under the
        # size cap — treated as corrupt, same as any other bad JSON.
        pass
    return {}


def _read_local_config() -> dict[str, Any]:
    """Read the user's ``config.json`` and return it as a dict.

    Returns ``{}`` when the file is missing (a fresh install) and on a
    corrupt / non-object file (which is renamed aside to ``.corrupt`` so the
    next launch starts clean). Never raises — a bad local file degrades to
    "use the online + hard-coded layers", not a crashed launch.
    """
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            # parse_constant rejects the non-standard Infinity/-Infinity/NaN
            # literals (which json.load accepts by default). A non-finite
            # numeric poisons int()/float() coercion downstream (e.g.
            # int(float('inf')) raises OverflowError on an int-typed key),
            # so treat such a file as corrupt and revert to defaults.
            loaded = json.load(f, parse_constant=_reject_nonfinite)
    except FileNotFoundError:
        logger.warning("config.json not found at %s; using defaults", path)
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError,
            RecursionError) as e:
        # UnicodeDecodeError is a ValueError that escapes the OSError
        # branch (e.g. cp1252 bytes saved by an external editor); the
        # original try/except missed it and crashed launch. ValueError
        # also catches any other JSON parser-internal raises (including the
        # non-finite-literal rejection above). RecursionError covers a
        # pathologically nested file (legal JSON, absurd depth) that the
        # C scanner refuses — also degraded to defaults, not a crash.
        logger.error("Failed to read config.json (%s); using defaults", e)
        try:
            os.replace(path, path + ".corrupt")
            logger.info("Moved corrupt config to %s.corrupt", path)
        except OSError:
            pass
        return {}

    if not isinstance(loaded, dict):
        logger.error("config.json is not a JSON object; using defaults")
        return {}
    return loaded


def load_config(*, fetch_online: bool = True) -> dict[str, Any]:
    """Return the effective config from the three merged layers.

    Precedence: ``local config.json`` > ``online app config`` > hard-coded
    ``DEFAULT_CONFIG`` (see ``merge_config_sources``). The online layer is
    fetched best-effort with a cache fallback and is restricted to
    ``ONLINE_ALLOWED_KEYS``; pass ``fetch_online=False`` (or clear
    ``config_url``) to skip the network entirely and use only the local +
    hard-coded layers — useful in tests and for an offline-only run.
    """
    migrate_config_location()
    migrate_legacy_app_data()
    local = _read_local_config()

    # The online config URL itself can be overridden locally (an expert can
    # point at a staging URL); otherwise the hard-coded default is used.
    # Distinguish "key absent" (use the default URL) from "key present and
    # empty" (the user deliberately blanked it to opt out of the network
    # fetch): an explicit "" must STAY empty so it short-circuits below,
    # otherwise ``"" or default`` would silently restore the third-party URL
    # and still phone home for a privacy/offline-conscious user.
    config_url = ""
    if fetch_online:
        if "config_url" in local:
            config_url = str(local["config_url"] or "")
        else:
            config_url = str(DEFAULT_CONFIG["config_url"])
    online: dict[str, Any] = {}
    if config_url:
        with _ONLINE_MEMO_LOCK:
            cached = _ONLINE_MEMO.get(config_url)
        if cached is not None:
            online = cached
        else:
            online = fetch_online_config(config_url)
            with _ONLINE_MEMO_LOCK:
                _ONLINE_MEMO[config_url] = online

    merged = merge_config_sources(DEFAULT_CONFIG, online, local)
    # Coerce / drop wrong-type values for keys that ship a default —
    # e.g. parallel_workers="many" survives the merge and downstream
    # int() crashes later. Drop the bad value (restore default).
    for k, default in DEFAULT_CONFIG.items():
        if k not in merged:
            continue
        # A null (JSON ``null`` / Python None) from the online or local layer
        # used to slip past the type check below (it was gated on
        # ``merged[k] is not None``), leaving None where a typed value is
        # expected — a later int()/strip()/iteration then crashes. When the
        # key ships a non-None default, drop the null and restore the default.
        if merged[k] is None:
            if default is not None:
                logger.warning(
                    "config key %r is null; reverting to default %r", k, default
                )
                merged[k] = json.loads(json.dumps(default))
            continue
        # Reject a non-finite numeric (inf / -inf / nan) for any key that
        # ships a numeric default, even when its Python type already matches
        # (e.g. a float-typed vad_threshold left as float('inf')). Such a
        # value passes the isinstance check below but poisons everything
        # downstream — int(inf) raises OverflowError, nan compares false to
        # all bounds. Only ``float`` is probed: an int is always finite, and
        # math.isfinite() on a huge JSON integer (a 400-digit literal is
        # legal JSON) raises OverflowError itself, crashing launch before the
        # type check ever runs. _read_local_config already rejects the JSON
        # literals at parse time; this guards values arriving via the online
        # layer or in-memory.
        if (
            isinstance(default, (int, float))
            and not isinstance(default, bool)
            and isinstance(merged[k], float)
            and not math.isfinite(merged[k])
        ):
            logger.warning(
                "config key %r is non-finite (%r); reverting to default %r",
                k, merged[k], default,
            )
            merged[k] = json.loads(json.dumps(default))
            continue
        if not isinstance(merged[k], type(default)):
            # Special-case: bool defaults accept int (Python's bool is int).
            if isinstance(default, bool) and isinstance(merged[k], int):
                merged[k] = bool(merged[k])
                continue
            # Special-case: int defaults accept float (lossy but harmless).
            if isinstance(default, (int, float)) and isinstance(
                merged[k], (int, float)
            ):
                # OverflowError guards int(float('inf')); a non-finite that
                # somehow reaches here (the finiteness check above normally
                # handles it) reverts to the default rather than crashing.
                try:
                    merged[k] = type(default)(merged[k])
                    continue
                except (TypeError, ValueError, OverflowError):
                    pass
            logger.warning(
                "config key %r has wrong type %s (expected %s); "
                "reverting to default %r",
                k, type(merged[k]).__name__, type(default).__name__, default,
            )
            merged[k] = json.loads(json.dumps(default))
    return _apply_runtime_fallbacks(merged)


def _persistable_model_path(config: dict[str, Any]) -> str:
    """Return the ``model_path`` value that is safe to write to disk.

    ``_apply_runtime_fallbacks`` fills ``model_path`` in memory by
    deriving it from ``hub_folder`` (or the default hub) so the model
    loaders get a concrete path. That derived value must NOT be
    persisted: on the next load any non-empty ``model_path`` on a
    mounted drive is treated as an explicit per-model override that
    wins over ``hub_folder`` (see the resolution order in core.hub).
    Writing a derived path back therefore pins the model location to a
    stale folder and silently ignores the user's hub choice — most
    visibly, the first-run hub picker never takes effect because the
    default-hub path resolved during startup gets saved and then
    outranks the folder the user actually picked.

    Only a genuinely custom ``model_path`` — one that matches no
    hub-derived layout — is preserved. Anything that equals the path
    we would derive from the current ``hub_folder`` or the default hub
    is stored as "" so it re-derives cleanly on every launch.
    """
    from . import hub as _hub
    raw = (config.get("model_path") or "").strip()
    if not raw:
        return ""
    model = config.get("model")
    raw_name = model.get("name") if isinstance(model, dict) else ""
    # A non-string nested name (e.g. {"model": {"name": 123}}) must not reach
    # hub.model_folder_for, whose name.strip() would raise AttributeError.
    model_name = (raw_name.strip() if isinstance(raw_name, str) else "") \
        or "whisper-model"
    hub_folder = (config.get("hub_folder") or "").strip()

    def _norm(p: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(p)))

    def _same_path(a: str, b: str) -> bool:
        # os.path.samefile (st_dev/st_ino) is authoritative on case-insensitive
        # macOS (APFS) / Windows volumes when both paths exist; os.path.normcase
        # only folds case on Windows (identity on POSIX), so use it only as the
        # fallback for a path that is not yet on disk.
        try:
            if os.path.exists(a) and os.path.exists(b):
                return os.path.samefile(a, b)
        except OSError:
            pass
        return _norm(a) == _norm(b)

    for h in (hub_folder, str(_hub.default_hub_folder())):
        if not h:
            continue
        try:
            if _same_path(raw, str(_hub.model_folder_for(h, model_name))):
                return ""
        except ValueError:
            continue
    return raw


def _persistable_download_folder(config: dict[str, Any]) -> str:
    """Return the ``download_folder`` value that is safe to write to disk.

    ``_apply_runtime_fallbacks`` clears ``download_folder`` to "" in
    memory when its drive is unmounted, so the UI re-prompts for this
    session. Persisting that "" would *permanently* forget a folder that
    merely lives on a removable / network drive detached at launch. So
    when the in-memory value is empty, fall back to the on-disk value if
    it points at a currently-unmounted drive — keeping the user's choice
    until the drive returns. (Same spirit as _persistable_model_path:
    don't let a session-only repair leak into a permanent loss.)
    """
    # A non-string download_folder (e.g. a hand-edited config.json with
    # an int or list) must not reach .strip(), which would raise an
    # uncaught AttributeError and crash save_config. Mirror the
    # model.name guard in _persistable_model_path: treat anything that
    # is not a str as empty, so a corrupt value normalises to "".
    def _as_str(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    current = _as_str(config.get("download_folder"))
    if current:
        return current
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            # Mirror the non-finite guard used by _read_local_config /
            # fetch_online_config: this re-reads the raw on-disk config
            # directly, bypassing _read_local_config's guard, so without
            # parse_constant an Infinity/-Infinity/NaN literal would be
            # accepted here too — and a non-finite download_folder value
            # then crashes the .strip() below (AttributeError, uncaught).
            # Treat such a file as corrupt: _reject_nonfinite raises a
            # ValueError, already handled by the except, so we fall back
            # to the in-memory value.
            on_disk = json.load(f, parse_constant=_reject_nonfinite)
    except (OSError, ValueError):
        return current
    if not isinstance(on_disk, dict):
        return current
    prev = _as_str(on_disk.get("download_folder"))
    if prev and not _drive_is_mounted(prev):
        return prev
    return current


#: App-level keys that must never be written to the user's config.json. They
#: are either re-derived from DEFAULT_CONFIG / the online config fetch on
#: every load, or (telemetry_opt_in) too easy to silently pin to a stale value
#: across an upgrade. Stripped on every save, including from a config.json
#: that already has them from before this rule existed.
_NON_PERSISTED_KEYS: frozenset[str] = frozenset({
    "telemetry_opt_in",
    "config_url",
    "stats_url",
    "ffplay_downloads",
    "latest_version",
})


def save_config(config: dict[str, Any]) -> None:
    # Serialise concurrent saves through _SAVE_LOCK — without this,
    # two threads racing to os.replace the same destination throw
    # PermissionError on Windows (NTFS rename semantics differ from
    # POSIX). Even though only one UI thread normally writes, the
    # Advanced dialog + tray + debounced auto-save can overlap.
    with _SAVE_LOCK:
        path = config_path()
        directory = os.path.dirname(path) or "."
        Path(directory).mkdir(parents=True, exist_ok=True)
        # Don't persist an auto-derived model_path — it would harden
        # into an explicit override that defeats hub_folder. See
        # _persistable_model_path for the full rationale.
        to_persist = dict(config)
        to_persist["model_path"] = _persistable_model_path(config)
        to_persist["download_folder"] = _persistable_download_folder(config)
        for key in _NON_PERSISTED_KEYS:
            to_persist.pop(key, None)

        # Guard + backup (2026-08-15, after a real incident: config.json
        # was found silently reduced from ~90 keys to 3 during ordinary
        # use; the root cause was never pinned down despite a real,
        # repeated investigation — see docs/SESSION_HANDOFF_NEXT.md).
        # Compares against what is CURRENTLY on disk, not a hardcoded
        # key count, so a deliberately-small dict written to a fresh
        # path (every test fixture in tests/core/test_config.py etc.)
        # is unaffected — there is nothing on disk yet to shrink from.
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if (
                    isinstance(existing, dict)
                    and len(existing) >= 10
                    and len(to_persist) < len(existing) * 0.4
                ):
                    logger.error(
                        "save_config() refused: new config has %d keys vs "
                        "%d currently on disk at %s -- this looks like "
                        "data loss, not an intentional shrink. Not "
                        "writing.",
                        len(to_persist), len(existing), path,
                    )
                    return
                # Only reachable when the size looks reasonable: keep one
                # rotating backup of the last good state before
                # overwriting it. Best-effort -- never let a backup
                # failure block the actual save.
                shutil.copy2(path, path + ".bak")
        except (OSError, json.JSONDecodeError, TypeError):
            pass

        fd, tmp_path = tempfile.mkstemp(
            prefix=".config-", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(to_persist, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# Per-folder project overrides --------------------------------------------------

PROJECT_FILE_NAME = ".whisperproject.json"


def find_project_file(start: str | Path) -> Path | None:
    """Walk up from ``start`` looking for ``.whisperproject.json``.

    Returns the first match or ``None`` when none is found. We stop
    at the filesystem root so a misconfigured cwd never causes an
    infinite loop. Both files and directories are valid starting
    points — for a file we begin from its parent directory.
    """
    try:
        p = Path(str(start)).resolve()
    except (OSError, ValueError):
        return None
    if p.is_file():
        p = p.parent
    for candidate in [p, *p.parents]:
        f = candidate / PROJECT_FILE_NAME
        if f.is_file():
            return f
    return None


def load_project_overrides(start: str | Path) -> dict[str, Any]:
    """Read the nearest ``.whisperproject.json`` and return its keys.

    Returns an empty dict when the file is absent, malformed, or not
    a JSON object. Never raises — a bad project file should not
    block a transcription, only the in-file override. We catch
    ``UnicodeDecodeError`` explicitly because it's a ``ValueError``
    that bubbles past the OSError branch (e.g. when a user saves
    the file in cp1252 with a non-UTF8 character).

    Audit A11: returned dict is shape-validated against
    ``DEFAULT_CONFIG``. Entries whose type does NOT match the
    matching default are dropped + logged so a typo
    (``"diarization_enabled": "yes"``) surfaces as a warning
    instead of getting silently coerced to bool("yes") == True
    downstream.
    """
    f = find_project_file(start)
    if f is None:
        return {}
    try:
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        # RecursionError: a pathologically nested project file (legal JSON,
        # absurd depth) — ignored like any other malformed file, never raised.
        logger.warning("Could not read project overrides at %s", f)
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "Project override at %s is not a JSON object; ignoring", f
        )
        return {}
    return _validate_overrides(data, f)


def _validate_overrides(
    overrides: dict[str, Any], source: Path,
) -> dict[str, Any]:
    """Drop entries whose type doesn't match ``DEFAULT_CONFIG``.

    Permissive: keys not present in DEFAULT_CONFIG are allowed
    through unchanged (forward-compat with experimental config
    keys); known keys must have the right type or they're dropped.
    Bool defaults still accept ints (Python bool is int), and
    numeric defaults still accept floats / ints interchangeably —
    same coercion rules as ``load_config`` to keep behaviour
    consistent. A null or a non-finite number (``Infinity`` / ``NaN``,
    including a ``1e400``-style overflow) is never a valid value for a
    known key and is dropped rather than handed to the runtime
    coercions as ``None`` / ``inf``.
    """
    cleaned: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in DEFAULT_CONFIG:
            cleaned[key] = value
            continue
        default = DEFAULT_CONFIG[key]
        # No known key has a None default, so a null is never a legitimate
        # value: passing it through let ``None`` reach the runtime coercion
        # block in ``core.transcriber._apply_runtime_overrides``
        # (``int(config["diarization_num_speakers"])``), which raises
        # TypeError and aborts the transcription for every file in that
        # folder. Non-finite numbers are just as poisonous — ``1e400`` /
        # ``Infinity`` parse to inf and ``int(inf)`` raises OverflowError
        # straight out of this "never raises" loader, while a NaN threshold
        # compares false to every bound. Drop both like any other wrong
        # type.
        if value is None or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            logger.warning(
                "Project override at %s has an unusable value for %r: %r; "
                "dropping.",
                source, key, value,
            )
            continue
        if isinstance(value, type(default)):
            cleaned[key] = value
            continue
        if isinstance(default, bool) and isinstance(value, int):
            cleaned[key] = bool(value)
            continue
        if isinstance(default, (int, float)) and isinstance(value, (int, float)):
            try:
                cleaned[key] = type(default)(value)
                continue
            except (TypeError, ValueError, OverflowError):
                # OverflowError: a float default receiving a huge (but
                # finite) JSON integer, e.g. float(10**400); the finite
                # check above only inspects actual floats.
                pass
        logger.warning(
            "Project override at %s has wrong type for %r: %s "
            "(expected %s); dropping.",
            source, key, type(value).__name__, type(default).__name__,
        )
    return cleaned


def deep_merge_dicts(dest: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``src`` into ``dest`` and return ``dest``.

    Unlike ``dict.update``, nested dicts are walked depth-first so a
    project override of ``{"model": {"name": "tiny"}}`` keeps every
    other key under ``model`` (``url``, ``md5`, …) intact.

    A mutable value (dict / list) that has no dict counterpart in ``dest``
    is deep-COPIED in, never aliased. Otherwise a nested object from ``src``
    (e.g. a ``model_catalog`` slug entry absent from ``dest``) would be
    shared by reference; a later merge that recurses into it would then
    mutate the original ``src`` object in place. Since ``merge_config_sources``
    feeds the memoized ``_ONLINE_MEMO`` value as a merge source, that aliasing
    let a local override permanently rewrite the process-wide online cache.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dest.get(k), dict):
            deep_merge_dicts(dest[k], v)
        elif isinstance(v, (dict, list)):
            dest[k] = copy.deepcopy(v)
        else:
            dest[k] = v
    return dest


def merge_project_overrides(
    base_config: dict[str, Any], source_path: str | Path
) -> dict[str, Any]:
    """Return a deep copy of ``base_config`` with overrides applied.

    Walks up from ``source_path`` to find the nearest
    ``.whisperproject.json`` and overlays its keys on top of
    ``base_config``. Dict-valued keys are deep-merged recursively
    so the user can override ``model.name`` (or anything deeper)
    without forcing the whole sub-dict.
    """
    overrides = load_project_overrides(source_path)
    if not overrides:
        return base_config
    merged: dict[str, Any] = json.loads(json.dumps(base_config))
    return deep_merge_dicts(merged, overrides)
