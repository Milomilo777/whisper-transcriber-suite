# Cloud Speech-to-Text (optional) — Google Gemini API

The Whisper Transcriber Suite is **offline by default**: every default backend runs
on your own machine and nothing is uploaded. This optional backend is the
one exception. When you select it, your audio is **uploaded to Google**
for transcription. It exists for users who want a fast, no-local-model
option and accept that trade-off. **Do not use it for content you cannot
send to a cloud service.**

## Why the Gemini API and not Google Cloud Speech-to-Text

Google has two different speech products, and only one of them works with
a simple pasted key:

- **Google Cloud Speech-to-Text** (`speech.googleapis.com`, the v2
  service) does **not** authenticate with a pasted API key. It requires a
  Google Cloud project plus a service-account or OAuth JSON credential.
  That defeats the "paste a key and go" goal, so this project does **not**
  target it.
- **The Gemini API** (`generativelanguage.googleapis.com`) **does** accept
  a bare API key via `?key=<API_KEY>`. The key you copy from
  https://aistudio.google.com/apikey works directly. This backend targets
  the Gemini audio-understanding flow and asks the model to produce a
  verbatim, timestamped transcript.

## Get a free API key

1. Go to https://aistudio.google.com/apikey and sign in with a Google
   account.
2. Click **Create API key** and copy the key.
3. In the app, open **Advanced > Backend**, find the **Cloud
   Speech-to-Text (Google)** box, paste the key into the masked **Google
   API key** field, and click **Test key** to verify it.
4. Set the **Backend** dropdown to `cloud_stt`, then **Save**.

The key is stored in cleartext in your per-user `config.json` under
`%LOCALAPPDATA%\WhisperTranscriberSuite` (the same place cookies and folder paths
are already stored). It is not encrypted. Treat that file accordingly.

## Privacy / offline trade-off (read this)

Selecting `cloud_stt` **uploads your audio to Google** and breaks the
project's "everything stays on this machine" guarantee. The Advanced
dialog states this in red, and the transcription log prints a reminder on
every run. The default engines (faster_whisper / whisper_cpp / parakeet)
remain fully offline — switch back to one of them at any time.

## The "$300 / 90-day free credit" — what you can and cannot see

Google advertises free credit for new accounts. **That dollar balance is
not readable from an API key** — reading it needs the Cloud Billing API,
which requires OAuth or a service account, not a pasted key. So this
backend does **not** show a live "$300 remaining" figure (that would be a
lie). Instead it tracks the **minutes of audio you have transcribed**
locally (`cloud_stt_minutes_used` in config) and links you to Google's
billing console for the authoritative balance:

> https://console.cloud.google.com/billing

The Advanced dialog shows `Cloud minutes used: N` next to an informational
free-tier figure (`cloud_stt_free_minutes_cap`, default ~60 min). That cap
is informational only — it is **not** enforced and does not block
transcription.

## Quota / error behaviour

Errors are translated into clear messages (never a raw traceback):

- **Invalid / unauthorised key** (HTTP 401 / 403): "Invalid Google API key
  (or it lacks Gemini API access)…".
- **Quota reached** (HTTP 429): "Free quota reached for this Google API
  key — see Google AI Studio…".
- **Model not found / renamed** (HTTP 404): "The cloud model was not found
  (it may have been renamed or retired). Set a current model name in
  Advanced > Backend.".
- **Offline / blocked**: "Could not reach Google… (offline or blocked)".

## How it works (model + endpoint)

- **Model:** `cloud_stt_model`, default `gemini-3.5-flash`. This is a
  config value so a renamed or newer model needs **no code change** — just
  type the new model ID in Advanced > Backend. (`gemini-2.0-flash` was
  shut down on 2026-06-01; `gemini-3.5-flash` is the current GA flash
  model, released 2026-05-19.)
- **Decode + chunk:** the bundled ffmpeg decodes any input to 16 kHz mono
  **FLAC** (compact, lossless) and splits it into ~8-minute windows
  (`cloud_stt_chunk_seconds`). Chunking gives per-chunk progress, lets you
  cancel/pause between chunks, and keeps each request within Google's size
  limits.
- **Upload:** each chunk is uploaded via the Gemini **Files API**
  resumable-upload protocol, then the file is polled until its `state`
  becomes `ACTIVE`. (Very small chunks may instead be sent inline as
  base64; the inline request hard cap is 20 MB including the prompt.)
- **Transcribe:** a `generateContent` call references the uploaded file and
  asks for a verbatim, timestamped transcript. The per-chunk
  chunk-relative timestamps are offset back onto the global file timeline,
  then handed to the **same** diarization / writers / output pipeline every
  other backend uses — so SRT/VTT/JSON/docx output, the viewer, and the
  queue all work unchanged.
- **No new dependency:** all HTTP uses the Python stdlib
  (`urllib.request`). No `google-cloud-speech` / `google-generativeai`.

## Verified documentation sources (fetched 2026-06-06)

The request shapes and model names above were verified against the
official Google AI / Gemini API docs:

- Audio understanding (generateContent, inline base64, the 20 MB inline
  limit, `file_data` / `file_uri` reference):
  https://ai.google.dev/gemini-api/docs/audio
- Files API resumable upload (`X-Goog-Upload-*` headers, poll until
  `state == "ACTIVE"`): https://ai.google.dev/gemini-api/docs/files
- Model list (current models + which are shut down):
  https://ai.google.dev/gemini-api/docs/models
- Changelog (`gemini-3.5-flash` GA 2026-05-19; `gemini-2.0-flash` shut
  down 2026-06-01): https://ai.google.dev/gemini-api/docs/changelog

## Limitations

- Word-level timestamps are not reliably available from the model, so
  word-timestamp output is empty for this backend (segments still carry
  start/end times).
- Transcription quality, latency, and cost are governed by Google, not by
  this app.
- A live end-to-end call requires a real key and is not exercised by the
  hermetic test suite (which tests only the pure request/response/offset
  logic). Validate with your own key after pasting it.
