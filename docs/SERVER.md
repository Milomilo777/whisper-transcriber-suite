# Local-network / web server mode

An optional HTTP job server so other people on your network can transcribe
through a web browser instead of each installing the desktop app. It reuses
the same engine the desktop app uses (`core.transcriber`) and adds no new
third-party dependency — it is built on the Python standard library
(`http.server`).

> Trusted-network use only. There is no user accounts system; anyone who can
> reach the address (and present the optional token) can submit jobs and
> download results. Run it on a network you trust.

## Easiest: the one-click toggle in the app

Open the desktop app and go to the **Web / LAN access** tab. There is one
obvious button:

- Click **Start web access** to turn it on. The status line shows the
  address to open in a browser. Click **Open in browser** to open it on
  this PC, or type the address on a phone / another computer.
- Click **Stop web access** to turn it off. It is off until you start it,
  and it stops automatically when you close the app.

Three optional settings on that tab (all remembered for next time):

- **Port** — the number after the address. Leave the default (8765) unless
  it is already in use; if it is, the app quietly picks a free port and
  shows you the one it used.
- **Share on local network** — OFF (default) = only this computer can use it
  and there is no firewall prompt. ON = other devices on your network can
  use it; Windows may ask to allow it through the firewall — click **Allow**.
- **Access password (optional)** — leave blank for none. If you set one,
  share it; the other person adds `?token=YOURPASSWORD` to the address.

The rest of this document describes the equivalent command-line server for
headless / scripted use.

## Start it from the command line

```
python gui.py serve
```

That binds **loopback only** (`127.0.0.1:8765`) — reachable just from the
machine it runs on, and it never triggers a Windows firewall prompt. Open
the printed URL in a browser on the same machine.

To share it with other devices on your LAN, opt in explicitly:

```
python gui.py serve --lan
```

`--lan` binds all network interfaces (`0.0.0.0`). **This is the only mode
that triggers the Windows Defender firewall prompt** — that prompt is
expected, and you must allow access for other devices to connect. On
startup the server prints the LAN URL (e.g. `http://192.168.1.42:8765/`) to
hand to people on the network.

Options:

```
--port 9000              # listen port (default: config server_port, 8765)
--host 0.0.0.0           # explicit bind address (same effect as --lan)
--token SECRET           # require a shared secret (see Security below)
--max-upload-mb 200      # reject uploads larger than this (default 512)
```

The server loads the Whisper model once at startup and keeps it hot, then
processes jobs **one at a time** (a single background worker). Sequential
processing is intentional: the ~3 GB model lives in a process global and
running transcriptions concurrently against it is unsafe.

## What the browser page does

The page (served at `/`) is a small **3-view** UI — **Submit**, **Jobs**,
and **Result** — that lets a user:

1. pick a local file **or** paste a link (anything yt-dlp supports),
2. choose output formats (the checkboxes are populated from what the
   server reports),
3. optionally set a language code **and the same per-job advanced options
   the desktop app has** (VAD, word timestamps, diarization, clip range,
   etc.), which are applied for that one job via a `.whisperproject.json`
   override,
4. start the job and watch progress; the **Jobs** view lists every job and
   offers **pause / resume / cancel**,
5. view the transcript inline and download each produced file from the
   **Result** view when it finishes.

Uploads are **streamed to disk** as they arrive (not buffered in RAM), so a
large file does not balloon the host's memory.

**Backend is fixed to the host's setting.** A web submitter can pick formats
and per-job options but **cannot switch the transcription backend** (e.g.
force a cloud backend) — that is a deliberate security boundary so a remote
request can't redirect your audio to a cloud service.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET  | `/` | the browser page |
| GET  | `/api/health` | `{status, version, formats}` |
| GET  | `/api/formats` | `{formats}` |
| GET  | `/api/jobs` | list all jobs |
| POST | `/api/jobs` | create a job — multipart upload OR JSON `{url, formats, language, options}` → `{job_id}` (`options` carries the per-job advanced settings) |
| GET  | `/api/jobs/<id>` | `{status, progress, error, outputs:[{fmt, name}]}` |
| GET  | `/api/jobs/<id>/result?fmt=srt` | download one written output |
| POST | `/api/jobs/<id>/cancel` | flag the job for cancellation |
| POST | `/api/jobs/<id>/pause` | pause a running job |
| POST | `/api/jobs/<id>/resume` | resume a paused job |

`status` is one of `queued`, `downloading`, `running`, `finished`,
`error`, `cancelled`.

## Security caveats

- **Trusted network only.** No authentication beyond the optional token,
  no encryption (plain HTTP). Do not expose it to the open internet.
- **Optional token.** Pass `--token SECRET`; clients must then send it via
  the `X-Auth-Token` header or a `?token=SECRET` query parameter. Without a
  token every request is accepted. The token is checked with a
  **constant-time** comparison so it can't be guessed by timing.
- **Audio is uploaded to the host.** Uploaded media is written to a
  per-job temp directory under the host's cache folder
  (`%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\server_jobs\<id>\`) and the outputs
  are written beside it. Per-job directories are cleaned up as jobs are
  evicted.
- **Upload size cap.** A single upload is capped (`--max-upload-mb`,
  default 512 MB) and rejected with HTTP 413 before being buffered.
- **URL safety.** Only `http`/`https` URLs are accepted (no `file://`).
  yt-dlp performs the actual download with an end-of-options `--` guard so
  a URL can never be parsed as a yt-dlp flag.
- **Bounded queue.** Total and queued job counts are capped; once full the
  server replies HTTP 503.
- **Supreme Master TV (SMTV) scraping is not reachable through this
  server.** A URL job (`POST /api/jobs` with `{url: ...}`) always goes
  through the yt-dlp download path (`core.server.jobs.JobManager`'s
  `_download` callback); `core.integrations.smtv`'s page-scraping is
  wired only into the desktop GUI's Download tab. A remote LAN/web
  client cannot trigger it, so this server's threat model does not need
  to account for that scraper's regex-based HTML parsing.

## Configuration

Keys in `config.json` (see [CONFIG.md](CONFIG.md)) hold the defaults. The
`serve` subcommand reads `server_port` / `server_max_upload_mb` when its
flags are omitted; the in-app **Web / LAN access** toggle reads and writes
all four:

```
server_port            8765     listen port
server_max_upload_mb   512      single-upload cap (MB)
server_share_lan       false    in-app toggle: bind 0.0.0.0 (LAN) vs 127.0.0.1
server_token           ""       optional access password (cleartext; see below)
```

`server_token` is stored in cleartext, the same as cookies / API keys —
`config.json` is per-user under `%LOCALAPPDATA%\WhisperTranscriberSuite` and is not
encrypted. The CLI's `--lan` / `--token` flags are the command-line
equivalents of `server_share_lan` / `server_token`.
