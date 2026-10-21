# Threat model

## What this project does and where untrusted input enters

Whisper Transcriber Suite is a desktop application (Python 3.11+, Tkinter; Windows first, macOS and Linux too). It
downloads audio and video with yt-dlp and transcribes it locally with Whisper (faster-whisper by default, also
whisper.cpp, NVIDIA Parakeet and two opt-in cloud engines), then writes the result in up to 14 formats. It runs with the
rights of the user who started it. `docs/ARCHITECTURE.md` is the code map and `SECURITY.md` is the public policy.

Untrusted input enters here, most important first:

- **The optional HTTP job server** (`core/server/`: `httpd.py`, `jobs.py`, `mcp.py`, `tls.py`; docs in `docs/SERVER.md`).
  Off by default. When on, it binds `127.0.0.1` (`HOST_LOOPBACK` in `core/server/__init__.py`) unless the user passes
  `--lan` or turns on "Share on local network", which binds `0.0.0.0`. It has no accounts, an optional shared token
  (`server_token`, compared with `hmac.compare_digest` in `httpd.py`), optional self-signed HTTPS. Routes: the browser
  page `/`, `/api/jobs` (multipart upload or a JSON body with a `url`), `/api/jobs/<id>/result?fmt=`, `/v1/audio/transcriptions`
  (OpenAI-compatible) and `/mcp` (Model Context Protocol). Everything a client sends is untrusted: the multipart parser,
  upload file names, the JSON body, the `url`, `fmt`, `language`, `formats` and per-job option fields, headers (`Host`,
  `Origin`, `Sec-Fetch-*`, `Authorization`), and the completion webhook URL.
- **The phone page and its link** (added in 2.2): the Web / LAN access tab shows a QR code that opens the browser page on
  a phone on the same Wi-Fi (`core/phone_link.py`). With an access password the link carries it as `?token=`; the page
  (`core/server/static/index.html`) moves it into the password box and `sessionStorage`, drops it from the address bar
  and sends it as a percent-encoded `X-Auth-Token` header (non-Latin passwords), which `token_ok` in `httpd.py` also
  accepts decoded. `POST /api/language-models/<language>/download` lets a page client make the host download a
  language-specific model from the Hugging Face Hub (`core/language_model_fetch.py`); its status and error text are
  returned to clients by `/api/options` (paths must be redacted, `redact_paths` in `jobs.py`). Token leaks through the
  link (history, Referer, logs, screenshots of the QR), a model download a client can trigger or repeat, and any path
  or error text that reaches a client belong here.
- **URLs given to yt-dlp**, from the server (`core/server/__init__.py` `_download_url`, command built with an
  end-of-options `--` before the URL) and from the GUI's Download tab (`app/services/download_service.py`). The pages,
  playlists, subtitles and media they return are attacker-controlled. yt-dlp and ffmpeg parse them.
- **Media, subtitle and transcript files the user opens or drops in** (also a watched folder, `core/watcher.py`): audio and
  video go to ffmpeg/ffprobe and PyAV; subtitle, `.otr` (`core/integrations/otranscribe.py`, which parses HTML) and
  transcript files are parsed by the transcript viewer and the converters (`core/convert.py`, `core/subtitle_qc.py`); resume checkpoints
  (`core/_checkpoint.py`) and the SQLite history (`core/history.py`) are read back from the user's data folder.
- **Network fetches the app makes itself**: the update check (`core/updates.py`, GitHub releases API; notify-only, it
  never downloads or installs anything); an online app-config JSON (`config_url` in `core/config.py`, capped at
  `MAX_CONFIG_BYTES`, only the keys in `ONLINE_ALLOWED_KEYS` are honoured, which include `model_catalog`, so a hostile
  config host could choose which Hugging Face repo the model downloader fetches); model downloads from the Hugging Face
  Hub (`core/model_manager.py`); the self-updating yt-dlp copy (`core/yt_dlp_update.py`, SHA-256 checked download from the
  yt-dlp GitHub releases); on-demand `pip install --target` of optional packages (`core/optional_deps.py`); the site-specific
  download helpers in `core/integrations/`; and the opt-in cloud engines and the LLM panel (`core/llm.py`, user-chosen
  OpenAI-compatible base URL).
- **Configuration files**: `config.json` in the per-user folder (`core/config.py`, with `LOCAL_ONLY_KEYS` that no remote
  source may set), including values that name a program the app starts (`subtitle_edit_path`).

## Components that matter most / least

- Most: `core/server/` (a network listener that writes uploads to disk, starts downloads and model downloads, and serves
  the phone page), `core/phone_link.py`, `core/language_model_fetch.py`, `core/server/jobs.py`
  (`is_safe_url`, `_safe_filename`, `post_webhook`, `output_path`), the yt-dlp and ffmpeg command construction
  (`app/services/download_service.py`, `core/server/__init__.py`, `core/_proc.py`), the file parsers and writers
  (`core/writers/`, `core/convert.py`, `core/integrations/otranscribe.py`), `core/config.py` (online layer and
  `LOCAL_ONLY_KEYS`), `core/yt_dlp_update.py`, `core/updates.py`, `core/model_manager.py`, `core/optional_deps.py`.
- Less: Tk widgets and dialogs under `app/`, and the packaging scripts in `platform/`, `tools/` and the `.iss`/`.spec` files
  (build time only).
- Out of scope as code: third-party packages and binaries (`ffmpeg`, `yt-dlp`, `faster-whisper`, CTranslate2, onnxruntime,
  PyAV, Pillow, model weights). Report flaws in them upstream; do report how this app calls them unsafely.
- `site/`, `docs/` and `tests/` are not shipped in the app. A problem in `site/` JavaScript that affects visitors of the
  project website is still welcome.

## How to exercise it

- `tests/` is the hermetic suite (`python -m pytest tests/ --ignore=tests/smoke -q`); `tests/smoke/` needs a real model and a
  network and skips itself. The server tests start a real `JobHTTPServer` on a loopback port and are the best examples of
  driving it: `tests/core/test_server_security.py`, `test_server_path_safety.py`, `test_server_upload_edge_cases.py`,
  `test_server_exposure_audit.py`, `test_server_mcp.py`, `test_server_openai.py`; for the phone page and token encoding
  `test_server_language_model.py`, `test_fixpack_D.py` and `test_server_jobs.py`.
- Start the server by hand with `python gui.py serve --token secret` (add `--lan` for `0.0.0.0`). Transcribing needs a model,
  which the first job downloads; the image has none, so job creation, uploads, auth and URL checks can be tested without one.
- The GUI needs a display; under `xvfb-run` Tk code runs headless. `python gui.py transcribe FILE` is the one-shot CLI.
- Linux has `ffmpeg` and `yt-dlp` on `PATH`; Windows and macOS builds bundle them in `bin/`, which is not in the repository.

## How you rate severity

The attacker we care about is a remote or cross-origin party who can reach the server, a web page the user visits, or a
file, link or feed the user opens, and who has no access to the machine.

- Critical: code execution, command or argument injection, or an arbitrary file write on the host, reachable from a crafted
  URL, media/subtitle/transcript file, server request, online-config or update/download response; a bypass of the server
  token that exposes jobs or results; leaking a stored credential (Gemini key, Google service-account JSON, LLM key,
  `server_token`) to a third party.
- High: reading an arbitrary file or another job's output through the server (path traversal, symlink, `fmt`/job id
  tricks); SSRF from a URL job or the webhook to loopback, link-local or cloud-metadata addresses that `is_safe_url`
  should refuse; a cross-site or DNS-rebinding request that the Host/Origin/`Sec-Fetch-Site` checks should stop; a
  tampered update or download that is accepted without its integrity check; writing outside the chosen output folder.
- Medium: memory or disk exhaustion by a remote client that bypasses the documented caps (upload size, 1 MB JSON body,
  64 connections, queue length, per-job 4 GB / 2 h download limit); sensitive paths or tokens in logs, error text or
  crash reports; information disclosure of host paths to a server client.
- Low: a crash or hang of the local app from a malformed local file, a slow-client or algorithmic-complexity DoS that
  needs an authenticated client, and anything the user must do to themselves.

## Anything to leave alone

- The server being reachable on a trusted LAN without a token or TLS is documented behaviour (`SECURITY.md`,
  `docs/SERVER.md`); exposing it to the open internet is a deployment choice. Report what it does beyond the documented
  routes and checks, not that it has no accounts.
- A client that holds the token can submit jobs, download results and cancel jobs; there is no per-user separation.
- An attacker who already runs code as the user, has local admin, or can edit `config.json`, the model folder, the
  user-writable yt-dlp copy or the `pip --target` extras folder is out of scope.
- The cloud engines uploading audio when the user turns them on, and the usage-statistics ping (`core/stats.py`, switch `telemetry_opt_in`), are intended.
- yt-dlp `--cookies-from-browser` reads the user's own browser profile by design.
- Antivirus heuristics on the packed Windows executable, and unpinned or outdated versions in `requirements.txt`
  without a reachable vulnerable code path.
- `tests/`, fixtures and `tools/` scripts that only run on a maintainer's machine.

## How we would like reports and patches

A minimal reproducer (a request, a short script or a tiny file), the affected file and line, the version or commit, and
what an attacker gains. A proposed patch is welcome if it keeps `pyright app core` at 0 errors and comes with a regression
test in `tests/` that fails before the fix and passes after; the server tests above show the pattern. Please do not add
non-English text to code or docs, and keep the change small.
