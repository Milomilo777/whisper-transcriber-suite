# Local-network / web server mode

An optional HTTP server so other people, other programs and other apps on your
network can transcribe through this computer instead of each installing the
desktop app. It reuses the same engine the desktop app uses
(`core.transcriber`) and adds no third-party dependency: it is built on the
Python standard library (`http.server`).

It offers three things:

- a **browser page** (Submit / Jobs / Result),
- a **JSON job API** (`/api/...`) for scripts,
- an **OpenAI-compatible** speech-to-text route (`/v1/audio/transcriptions`)
  so tools such as Open WebUI and the `openai` SDKs can use it as a drop-in
  backend.

> Trusted-network use only. There are no user accounts; anyone who can reach
> the address (and present the optional token) can submit jobs and download
> results. Plain HTTP is the default; HTTPS with a self-signed certificate is
> optional (see [HTTPS](#https-self-signed-certificate)). Do not expose the
> server to the open internet.

Contents: [In-app toggle](#easiest-the-one-click-toggle-in-the-app) ·
[Command line](#start-it-from-the-command-line) ·
[Quick start with curl](#quick-start-with-curl) ·
[OpenAI-compatible API](#openai-compatible-api) ·
[Open WebUI](#use-it-from-open-webui) ·
[JSON job API](#json-job-api) ·
[Authentication](#authentication) ·
[HTTPS](#https-self-signed-certificate) ·
[Webhook](#completion-webhook) ·
[Security](#security-caveats) ·
[Browser protections](#browser-protections) ·
[Configuration](#configuration)

## Easiest: the one-click toggle in the app

Open the desktop app and go to the **Web / LAN access** tab. There is one
obvious button:

- Click **Start web access** to turn it on. The status line shows the
  address to open in a browser. Click **Open in browser** to open it on
  this PC, or type the address on a phone / another computer.
- Click **Stop web access** to turn it off. It is off until you start it,
  and it stops automatically when you close the app.

Optional settings on that tab (all remembered for next time):

- **Port**: the number after the address. Leave the default (8765) unless
  it is already in use; if it is, the app quietly picks a free port and
  shows you the one it used.
- **Share on local network**: OFF (default) = only this computer can use it
  and there is no firewall prompt. ON = other devices on your network can
  use it; Windows may ask to allow it through the firewall, click **Allow**.
- **Access password (optional)**: leave blank for none. If you set one,
  share it; see [Authentication](#authentication) for how clients send it.
- **Use HTTPS (self-signed certificate)**: serve over TLS, see
  [HTTPS](#https-self-signed-certificate).
- **Webhook URL (optional)**: see [Completion webhook](#completion-webhook).

The rest of this document describes the equivalent command-line server for
headless / scripted use.

## Start it from the command line

```
python gui.py serve
```

That binds **loopback only** (`127.0.0.1:8765`): reachable just from the
machine it runs on, and it never triggers a Windows firewall prompt. Open
the printed URL in a browser on the same machine.

To share it with other devices on your LAN, opt in explicitly:

```
python gui.py serve --lan
```

`--lan` binds all network interfaces (`0.0.0.0`). **This is the only mode
that triggers the Windows Defender firewall prompt**; that prompt is
expected, and you must allow access for other devices to connect. On
startup the server prints the LAN URL (e.g. `http://192.168.1.42:8765/`) to
hand to people on the network.

Options of `serve`:

```
--port, -p 9000          # listen port (default: config server_port, 8765)
--host 0.0.0.0           # explicit bind address (default 127.0.0.1; 0.0.0.0 = same as --lan)
--lan                    # bind all interfaces (0.0.0.0)
--token SECRET           # require a shared secret (default: config server_token; see Authentication)
--max-upload-mb 200      # reject uploads larger than this (default: config, 512)
--https                  # serve over TLS with a self-signed certificate
--webhook URL            # POST a JSON summary to URL when a job finishes
```

Notes:

- Unlike the app's toggle, the command line uses exactly the port you give it
  and never picks another one. If something already listens there, it prints
  a "could not bind" error and exits with code 1.
- `--token`, `--https` and `--webhook` fall back to the config keys
  `server_token` (the app's **Access password**), `server_https_enabled` and
  `server_webhook_url` when the flag is not given. `--token=` serves without
  a password even when the app has one (write it with the `=`: Windows
  PowerShell drops an empty `""` argument).
- The server loads the Whisper model once at startup (the first start can
  take a while; large models need more than a minute on a CPU) and keeps it
  hot. It processes jobs **one at a time** (a single background worker).
  Sequential processing is intentional: the model lives in a process global
  and running transcriptions concurrently against it is unsafe.
- The server uses the transcription engine and model chosen in the desktop
  app's settings.

There is also a one-shot command-line transcription that needs no server:

```
python gui.py transcribe FILE [--language en] [--formats srt txt] [--diarization] [--model large-v3]
```

`--model` is saved as the app's model, as if you had picked it in the app.
`--formats` and `--diarization` apply to that one run and leave the app's
settings unchanged. It writes the outputs next to the input file and exits with code 0 on success,
2 for a missing file or unknown model, 3 when the model cannot be loaded and 4
when the transcription failed. Run `python gui.py transcribe --help` for the
list of formats.

## Quick start with curl

Start a server with a token, then run these from any machine that can reach it
(replace `127.0.0.1` with the LAN address when you use `--lan`):

```
python gui.py serve --token mysecret
```

```
# 1. Is it up? (needs the token because one is set)
curl -H "X-Auth-Token: mysecret" http://127.0.0.1:8765/api/health

# 2. OpenAI-style transcription: waits and returns the transcript
curl http://127.0.0.1:8765/v1/audio/transcriptions \
  -H "Authorization: Bearer mysecret" \
  -F file=@meeting.wav \
  -F model=whisper-1
# -> {"text": "..."}

# 3. Same, but as subtitles
curl http://127.0.0.1:8765/v1/audio/transcriptions \
  -H "Authorization: Bearer mysecret" \
  -F file=@meeting.wav -F model=whisper-1 -F response_format=srt
```

Without `--token`, leave the header out. The first command above printed
`{"status": "ok", "version": ..., "formats": [...]}` and the second printed
`{"text": "..."}` when run against a local server for this document.

## OpenAI-compatible API

The `/v1` routes follow OpenAI's audio API closely enough for existing clients.
Point a client at the base URL `http://<host>:8765/v1`.

### `GET /v1/models`

Returns a one-entry list so clients can validate the backend:

```
{"object": "list", "data": [{"id": "whisper-1", "object": "model",
 "created": 0, "owned_by": "whisper-transcriber-suite"}]}
```

### `POST /v1/audio/transcriptions`

Multipart form, **synchronous**: the request stays open until the
transcription is done (a long file means a long wait; set a generous client
timeout). Jobs from this route join the same single queue as every other job.
At most 32 such requests may wait at once (fewer on a server started with a
small connection cap), so the web page and status calls always find a free
connection; one more gets HTTP 503 (a place is taken only once the whole upload
has arrived). If the connection is **reset** while the client waits (it crashed
or was killed), the server notices within a moment and **cancels that job**:
nobody is left to read the answer, and a client that retries would otherwise
queue one job per attempt. Only a reset is noticed, over HTTP and HTTPS alike:
a client that closed or half-closed its side (HTTP/1.0 style, or after
`close_notify`) keeps its job, which runs to the end; sending the answer to a
client that really left fails harmlessly.

| Field | Required | Notes |
|---|---|---|
| `file` | yes | the audio/video file |
| `model` | yes | any non-empty value (use `whisper-1`); the server ignores it, the model is chosen in the app |
| `language` | no | ISO code such as `en`; an unknown or empty value means auto-detect |
| `response_format` | no | `json` (default), `text`, `srt`, `verbose_json`, `vtt` |
| `prompt`, `temperature`, `timestamp_granularities[]` | no | accepted and ignored |

Responses:

- `json`: `{"text": "..."}`
- `text`: the plain transcript (`text/plain`)
- `srt`, `vtt`: subtitles (`text/plain`)
- `verbose_json`: `task`, `language` (the detected ISO code, e.g. `en`),
  `duration`, `text`, `segments` (every field the OpenAI SDK type declares;
  log-probability style fields carry neutral `0` values) and `usage`; `words`
  is added only when the transcript carries word timings.

`diarized_json` is not supported and returns a 400.

Errors use OpenAI's envelope:

```
{"error": {"message": "...", "type": "invalid_request_error", "param": "model", "code": null}}
```

| Status | When |
|---|---|
| 400 | missing `file` or `model`, unsupported `response_format`, not multipart, or a `language` the server's English-only model cannot do (see [Security caveats](#security-caveats)) |
| 401 | wrong or missing token (`code` is `invalid_api_key`) |
| 403 | refused by the [browser protections](#browser-protections) (`code` is `forbidden`) |
| 411 | upload without a `Content-Length` (chunked) |
| 413 | upload larger than the cap |
| 500 | transcription failed or was cancelled |
| 503 | job queue full, or the server is shutting down |

The `401` for a **GET** route (for example `/v1/models` without a token) uses
the plain `{"error": "auth required"}` shape of the job API instead.

Python (`openai` SDK):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="mysecret")
with open("meeting.wav", "rb") as f:
    result = client.audio.transcriptions.create(model="whisper-1", file=f)
print(result.text)
```

With no token configured, `api_key` can be any non-empty string.

## Use it from Open WebUI

[Open WebUI](https://github.com/open-webui/open-webui) can use any
OpenAI-compatible speech-to-text endpoint. In its **Admin Settings → Audio**
page choose the OpenAI engine for speech-to-text and set:

- API base URL: `http://<host>:8765/v1`
- API key: the server's token (any non-empty text if the server has none)
- model: `whisper-1`

The same can be set with environment variables when Open WebUI starts (names
checked against Open WebUI's `config.py`):

```
AUDIO_STT_ENGINE=openai
AUDIO_STT_OPENAI_API_BASE_URL=http://<host>:8765/v1
AUDIO_STT_OPENAI_API_KEY=mysecret
AUDIO_STT_MODEL=whisper-1
```

If Open WebUI runs in Docker, the container cannot reach the host's
`127.0.0.1`. Start the server with `--lan` and use the computer's LAN address
or `host.docker.internal` as `<host>`; any other host name needs a password
(see [Browser protections](#browser-protections)). Menu labels can differ between Open
WebUI versions. The `/v1` calls above were tested with `curl`; this page has
not been run against a live Open WebUI.

## JSON job API

For scripts that prefer submit-then-poll. All paths need the token when one is
set, except `GET /` (the page itself).

| Method | Path | Purpose |
|---|---|---|
| GET  | `/` | the browser page |
| GET  | `/api/health` | `{status, version, formats}` |
| GET  | `/api/formats` | `{formats}` |
| GET  | `/api/options` | `{formats, languages, diarization_available, backend_switchable}` |
| GET  | `/api/jobs` | `{jobs: [{job_id, status, progress, paused, source, formats, created_at}]}` |
| POST | `/api/jobs` | create a job: multipart upload OR JSON (below); replies `202 {job_id}` |
| GET  | `/api/jobs/<id>` | `{job_id, status, progress, error, paused, outputs: [{fmt, name}]}` |
| GET  | `/api/jobs/<id>/outputs` | `{job_id, outputs: [{fmt, name}]}` |
| GET  | `/api/jobs/<id>/result?fmt=srt` | download one written output |
| POST | `/api/jobs/<id>/cancel` | flag the job for cancellation |
| POST | `/api/jobs/<id>/pause` | pause a running or queued job |
| POST | `/api/jobs/<id>/resume` | resume a paused job |
| GET  | `/v1/models` | OpenAI-compatible model list |
| POST | `/v1/audio/transcriptions` | OpenAI-compatible transcription (above) |

`status` is one of `queued`, `downloading`, `running`, `finished`, `error`,
`cancelled`. Cancel, pause and resume answer 404 `no such active job` for a
job that already ended. A job's `error` names files by their file name only,
never by their full path on the server.

Create a job from an uploaded file (put the `file` part first, as browsers do):

```
curl -H "X-Auth-Token: mysecret" http://127.0.0.1:8765/api/jobs \
  -F file=@meeting.wav -F formats=srt,txt -F language=en
# -> {"job_id": "45db6250929d46598b9ce55123743cfc"}

curl -H "X-Auth-Token: mysecret" http://127.0.0.1:8765/api/jobs/<job_id>
# -> {"job_id": "...", "status": "finished", "progress": 100, "error": "",
#     "paused": false, "outputs": [{"fmt": "srt", "name": "meeting.srt"}, ...]}

curl -H "X-Auth-Token: mysecret" -o meeting.srt \
  "http://127.0.0.1:8765/api/jobs/<job_id>/result?fmt=srt"
```

Or from a link (anything yt-dlp supports; only `http` / `https`):

```
curl -H "X-Auth-Token: mysecret" -H "Content-Type: application/json" \
  http://127.0.0.1:8765/api/jobs \
  -d '{"url": "https://example.com/video", "formats": ["srt"], "language": "en"}'
```

The `Content-Type: application/json` header is required: a JSON body sent
with any other type (curl's `-d` alone sends a form type) gets `415`.

Fields (multipart fields or JSON keys):

- `formats`: comma-separated string or JSON list, from `GET /api/formats`
  (unknown names are dropped; the default is `srt`).
- `language`: ISO code from `GET /api/options` (`en`, `fa`, ...); empty or
  unknown means auto-detect.
- Per-job advanced options, applied to that job only: `vad_enabled`,
  `vad_threshold` (0 to 1), `vad_min_silence_ms`, `word_timestamps`,
  `diarization_enabled`, `diarization_num_speakers` (below 1 = automatic),
  `demucs_enabled`, `hallucination_detect_enabled`, `auto_chapters_enabled`,
  plus `clip_start` / `clip_end` in seconds.

**Backend is fixed to the host's setting.** A web submitter can pick formats
and per-job options but **cannot switch the transcription backend** (for
example to a cloud one): that is a deliberate security boundary so a remote
request cannot redirect your audio to a cloud service.

Uploads are **streamed to disk** as they arrive (not buffered in RAM), so a
large file does not balloon the host's memory. A JSON body is capped at 1 MB.

## Authentication

Authentication is optional. With no token, every request is accepted. With a
token (`--token`, or **Access password** in the app), each request must carry
it in one of three ways:

| Way | Example |
|---|---|
| header | `X-Auth-Token: mysecret` |
| OpenAI-style header | `Authorization: Bearer mysecret` |
| query string | `http://host:8765/api/jobs?token=mysecret` |

Prefer a header for scripts. The comparison is constant-time, and the server
log shows a query-string token as `token=[redacted]`.

The page at `/` loads without a token; its API calls need one. Type it into
the page's **Auth token** box, or open a link with it added, for example
`http://192.168.1.42:8765/?token=mysecret` (characters other than letters and
digits must be percent-encoded there; the box takes the password as typed):
the page moves the token into the box and removes it from the address bar and
the browser history. It is kept
for that browser tab only, so a reload still works. With a password set, a
download link on the page fetches the file with the token in a header and saves
it from memory, so the address never carries `?token=` (the page says that
"Open in new tab" and "Save link as" cannot send the password, and a failed
download names the reason: wrong password, file gone, or a server error); a
browser without `fetch` and `Blob` falls back to the address form.

`gui.py serve` uses the app's **Access password** (`server_token`) unless
`--token` is given.

## HTTPS (self-signed certificate)

Off by default. Turn it on with `--https`, the **Use HTTPS** checkbox, or
`server_https_enabled` in `config.json`:

```
python gui.py serve --lan --https --token mysecret
```

- The certificate is generated once, with the Python standard library only,
  under the app's data folder (`%LOCALAPPDATA%\WhisperTranscriberSuite\server\`,
  files `server_cert.pem` and `server_key.pem`) and reused on every start.
  It is regenerated only when the pair is missing or cannot be loaded.
- It is **self-signed**, valid 10 years, ECDSA P-256, and lists `localhost`,
  `127.0.0.1`, `::1`, this computer's name and its LAN address. TLS 1.2 or
  newer is required.
- Browsers show a "not trusted" warning until you accept it once. With curl,
  either skip verification or trust the file:

```
curl -k https://127.0.0.1:8765/api/health
curl --cacert "%LOCALAPPDATA%\WhisperTranscriberSuite\server\server_cert.pem" https://localhost:8765/api/health
```

- With HTTPS on, the port speaks TLS only: a plain `http://` request to it is
  refused. If a certificate cannot be produced, the server refuses to start
  instead of silently serving plain HTTP.
- Clients that insist on a trusted certificate (some OpenAI SDK setups) need
  the certificate file added to their trust store, or a reverse proxy with a
  real certificate in front of the plain-HTTP server.

## Completion webhook

Optional. Give a URL with `--webhook URL`, the **Webhook URL** field in the
app, or `server_webhook_url` in `config.json`; empty (the default) means off.
When a job ends the server sends one `POST` with a JSON body:

```
{
  "event": "job.finished",        // or "job.error"
  "job_id": "45db6250929d46598b9ce55123743cfc",
  "status": "finished",           // or "error"
  "source": "meeting.wav",        // file name or URL of the job
  "language": "en",               // detected language, else the requested one
  "formats": ["srt", "txt"],
  "outputs": [{"fmt": "srt", "name": "meeting.srt"}],
  "error": "",
  "created_at": 1791137802.37,    // Unix seconds
  "finished_at": 1791137881.02
}
```

Behaviour to know:

- It fires for jobs that **finish or fail**, from any route (browser, JSON API
  or the `/v1` route); a cancelled job sends nothing.
- Delivery is fire-and-forget on its own thread: 10-second timeout, no retry,
  redirects are not followed, a failure is only logged. Logs and the start-up
  message show only the receiver's `scheme://host:port/...`, never the path or
  query of the URL.
- Only `http` / `https` URLs are used, and a URL that points at this
  computer's own loopback, a link-local address (including cloud metadata
  addresses) or another reserved address is **refused**, so the receiver has
  to live on another machine or a LAN address. Ordinary private LAN addresses
  (10.x, 172.16-31.x, 192.168.x) are allowed.
- Outputs are listed by file name only, never by path. The request carries no
  signature or secret; treat the receiving URL itself as the secret, or check
  the job id against `GET /api/jobs/<id>`.

## Security caveats

- **Trusted network only.** No authentication beyond the optional token, and
  no encryption unless HTTPS is on. Do not expose it to the open internet.
- **Audio is uploaded to the host.** An incoming upload is first spooled to
  the operating system's temp folder (`upload-*.part`, deleted right after);
  the media is then written to a per-job directory under the host's cache
  folder (`%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\server_jobs\<id>\`)
  and the outputs are written beside it. When a job ends, its uploaded or
  downloaded media is deleted from that directory (a file the server did not
  store itself is never touched) and the outputs stay. While the server runs,
  the oldest finished jobs' directories are removed as new jobs arrive.
  Directories of finished jobs are **not** removed when the server stops, but
  a later start deletes job folders of this version older than 6 hours whose
  server is gone (the job list is in memory only, so nothing can reach them
  any more). A folder whose server still runs, in this or another process
  (for example the app's web access and `gui.py serve` at the same time), is
  never deleted, and folders left by older versions are only deleted after 7
  days. A job's outputs are also copied to `server_outputs\` next to the cache
  folder before the job reads as finished; delete that folder yourself when
  you want them gone. A job on a paid cloud engine that fails part-way keeps
  the text of the finished chunks as an output named `partial_srt`
  (`GET /api/jobs/<id>/result?fmt=partial_srt`); it is copied to
  `server_outputs\` too and never deleted with the job folder. If a copy to
  `server_outputs\` fails (for example the disk is full), the job still
  finishes but carries a `warning` in `GET /api/jobs/<id>`, and its folder
  is never deleted until the results have been copied (a later start
  retries; the list of unsaved files in the folder is `.wts-keep`, and an
  unreadable list keeps the whole folder).
- **Upload size cap.** A single upload is capped (`--max-upload-mb`,
  default 512 MB, hard ceiling 4096 MB) and rejected with HTTP 413 before
  being buffered. An upload needs a `Content-Length` (chunked uploads get
  HTTP 411), and one that ends before that length (the client left) is
  refused with HTTP 400 and creates no job. File names are read as UTF-8, as
  browsers send them.
- **Link downloads are bounded.** One URL job may download at most 4 GB and
  run for 2 hours; Cancel stops a running download. The job list and the
  webhook show a link's address without its query string and user info.
- **URL safety.** Only `http`/`https` URLs are accepted (no `file://`), and
  a host that is, or resolves to, a loopback, link-local, unspecified,
  multicast or otherwise reserved address is refused. A name that fails to
  resolve is let through (yt-dlp then reports the real error), and yt-dlp
  follows its own redirects, so this check is a first line of defence only.
  yt-dlp performs the actual download with an end-of-options `--` guard so
  a URL can never be parsed as a yt-dlp flag. Private LAN addresses are
  allowed on purpose (fetching from a media server on the same network).
- **Bounded queue.** Total and queued job counts are capped; once full the
  server replies HTTP 503. A full queue is answered before an upload body is
  stored, so refused uploads do not fill the temp folder.
- **Bounded connections.** At most 64 connections are served at once (one
  thread each). A further client gets HTTP 503 with `Retry-After` from a small
  separate refuser (at most 16 at a time, so it takes no normal slot): it sends
  the reply, then reads and drops what the client is still uploading for up to
  2 seconds or 16 MB, so the reply is not lost to a connection reset. A client
  that sends more than that, or any client over HTTPS (no reply is possible
  without a TLS handshake), sees the connection closed instead.
  Once three quarters of the slots are in use, every reply ends its connection
  (`Connection: close`), and an idle keep-alive connection is kept for at most
  15 seconds, so browsers cannot hold the slots between requests.
- **Time budgets.** A client that trickles bytes is cut off: 15 seconds to
  send a request line and its headers (also the idle time of a keep-alive
  connection) and 60 seconds for a small JSON body. An upload is cut only when
  it stalls: every 64 KB that arrives earns another 60 seconds, so a slow but
  steady upload of a big file is not cut by the stall rule. A sanity bound
  still ends an upload that is slower than about 16 KB/s overall (its size at
  16 KB/s, between 10 minutes and 6 hours). A cut upload or JSON body gets
  HTTP 408 with a message saying it was too slow.
- **English-only models.** When the server's Whisper model is English-only
  (`tiny.en`, `small.en`, ...), a job or `/v1` request that names another
  language is refused with HTTP 400 and a message naming a multilingual model;
  such a model would otherwise return invented English. A request without a
  language (auto-detect) or with `en` is accepted.
- **Web options are clamped.** `vad_min_silence_ms` and
  `diarization_num_speakers` above their limits (60000 ms, 100 speakers) are
  set to the limit instead of being dropped.
- **Timeouts.** A connection that sends nothing for 60 seconds is closed, and
  with HTTPS a client gets 10 seconds to finish the TLS handshake (on its own
  connection, so a silent client cannot stall anyone else). A request refused
  before its body is read (wrong token, browser protections, unknown route)
  has its body read and discarded for at most 10 seconds, never past the
  upload cap, and only while the client keeps sending (a 2-second pause ends
  it), so the client still sees the answer; then the connection is closed.
  The same limits (30 seconds in all, a 5-second pause) apply to a body the
  server is about to refuse as too large.
- **Busy port.** A second server cannot bind a port that is already in use
  (an exclusive bind on Windows); the command line reports the error.
- **Supreme Master TV (SMTV) scraping is not reachable through this
  server.** A URL job (`POST /api/jobs` with `{url: ...}`) always goes
  through the yt-dlp download path (`core.server.jobs.JobManager`'s
  `_download` callback); `core.integrations.smtv`'s page-scraping is
  wired only into the desktop GUI's Download tab. A remote LAN/web
  client cannot trigger it, so this server's threat model does not need
  to account for that scraper's regex-based HTML parsing.

### Browser protections

The server runs on the same computer as your web browser, so a web page you
visit must not be able to use it behind your back. These checks stop that:

- **JSON needs `Content-Type: application/json`** (else `415`). A web page
  can send `text/plain` to another site without asking the browser first; it
  cannot send `application/json` that way. This check is always on.
- **No framing.** The page at `/` tells browsers that no other site may show
  it inside a frame, so a visited page cannot steer your clicks on it.
- **No loads from other sites.** A browser request that another site makes
  in the background (`Sec-Fetch-Site: cross-site` or `same-site` on anything
  but a navigation, such as a `<script>` tag) gets `403`, so a page cannot
  use the answers to guess the password. Opening a shared link still works.

Without an access password, two more checks apply (each answers `403`):

- **Other web origins are refused.** A browser request whose `Origin` header
  is not the server's own address (scheme, host and port), including
  `Origin: null`, is refused. Requests without an `Origin` header (curl,
  scripts, the OpenAI SDKs, Open WebUI's backend) are not affected.
- **Only direct addresses are served.** The `Host` header must be an IP
  address (`127.0.0.1`, `192.168.1.42`, `[::1]`), `localhost`,
  `host.docker.internal`, this computer's name or that name with `.local`.
  This stops DNS rebinding, where a web page's own domain is pointed at your
  computer. Other names (a router name such as `mypc.lan`, a Tailscale name)
  get `403`: use the IP address, or set a password.

With a password set, any `Host` is accepted and the password is what keeps
other pages out. A request from another origin must then carry the password
in the `X-Auth-Token` or `Authorization` header (another site's form cannot
set a header, but it can put a guessed password in `?token=`); the server's
own page always sends the header. This is also what makes a reverse proxy
work (it forwards its own name and an `https://` origin to the plain-HTTP
server), so put a password on a server behind one.

## Configuration

Keys in `config.json` (see [CONFIG.md](CONFIG.md)) hold the defaults. The
`serve` subcommand reads `server_port`, `server_max_upload_mb`,
`server_https_enabled` and `server_webhook_url` when its flags are omitted;
the in-app **Web / LAN access** toggle reads and writes all of them except
`server_max_upload_mb`, which it only reads (edit that one in `config.json`):

```
server_port            8765     listen port
server_max_upload_mb   512      single-upload cap (MB)
server_share_lan       false    in-app toggle: bind 0.0.0.0 (LAN) vs 127.0.0.1
server_token           ""       optional access password (cleartext; see below)
server_https_enabled   false    serve over TLS (self-signed certificate)
server_webhook_url     ""       completion webhook target (empty = off)
```

`server_token` is stored in cleartext, the same as cookies / API keys:
`config.json` is per-user under `%LOCALAPPDATA%\WhisperTranscriberSuite` and is not
encrypted. The CLI's `--lan` flag is the command-line equivalent of
`server_share_lan` (the command line does not read that key). `--token`
overrides `server_token`; without it the command line uses the saved value.
