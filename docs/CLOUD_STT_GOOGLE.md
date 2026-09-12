# Google Cloud Speech-to-Text (optional) — service account

The Whisper Transcriber Suite is **offline by default**: every default backend runs
on your own machine and nothing is uploaded. This optional backend is one
of two cloud exceptions. When you select it, your audio is **uploaded to
Google** for transcription. **Do not use it for content you cannot send to
a cloud service.**

This page covers the **full Google Cloud Speech-to-Text** service
(`google_cloud_stt`). It is **not** the same as the simpler **Gemini cloud**
option — see the table below.

> **You need your own key.** Nothing ships with one. Builds v1.3.9–v1.5.0 did
> bundle a maintainer-owned service-account key, which also made this the
> default engine; that key is **revoked** and the bundling is gone, so on
> those older builds cloud STT now fails until you supply your own JSON.
> Background: [SECURITY.md](../SECURITY.md).

## Which cloud option do I want?

| | Gemini cloud (`cloud_stt`) | Google Cloud Speech-to-Text (`google_cloud_stt`) |
|---|---|---|
| Sign-in | A simple **API key** you paste | A **service-account JSON file** you download |
| Setup effort | Lower (copy one key) | Higher (a few console steps, once) |
| Free tier | Gemini API free quota | **60 minutes / month**, ongoing |
| New-customer credit | — | **$300 over 90 days** |
| Word-level timestamps | No (line-level only) | **Yes, always on** |
| Speaker labels | No | Yes (diarization) |
| Cheaper bulk mode | No | Yes (batch mode, ~75% cheaper) |
| Setup guide | [docs/CLOUD_STT.md](CLOUD_STT.md) | this page |

**Google Cloud Speech-to-Text is the only engine in this app that combines
all three at once: real word-level timestamps, speaker diarization, and a
cheap Batch mode for long files** — Batch costs about **$0.004/minute**
(~75% less than Standard's ~$0.016/minute) and is usually ready within
**24 hours**. See "Standard vs. batch mode" below for details.

If you just want the quickest setup, use the Gemini option. If you want the
ongoing 60 free minutes a month, real word-level timestamps, speaker labels,
or the cheaper batch mode, use this one.

## How do I get the service-account JSON file?

You do this **once**. In the app this same list is behind the **"How do I
get this file?"** button in **Advanced > Backend**, and each link opens the
exact console page.

1. **Create or pick a Google Cloud project** —
   https://console.cloud.google.com/projectcreate
2. **Enable the Speech-to-Text API** for that project —
   https://console.cloud.google.com/apis/library/speech.googleapis.com
3. **(Optional but recommended) Turn on billing** to unlock the 60 free
   min/month + $300 credit —
   https://console.cloud.google.com/billing
4. **Create a service account** —
   https://console.cloud.google.com/iam-admin/serviceaccounts → "Create
   service account" → give it the role **"Cloud Speech-to-Text User"** (for
   batch mode also **"Storage Object Admin"** on your bucket).
5. On that service account → **"Keys"** → **"Add key"** → **"Create new
   key"** → **JSON** → Download. **Keep this file private.**
6. Back in the app, open **Advanced > Backend**, find the **Google Cloud
   Speech-to-Text (service account)** box, click **"Browse..."** and pick
   that downloaded `.json` file. Then click **"Test connection"**.

Official guide:
https://cloud.google.com/speech-to-text/docs/before-you-begin

(Screenshots are not embedded — the links open the exact console pages.)

After the connection test passes, set the **Backend** dropdown to
**"Google Cloud Speech-to-Text — service account (60 min/mo free)"** and
click **Save**.

The path to your JSON file is stored in your per-user `config.json` under
`%LOCALAPPDATA%\WhisperTranscriberSuite`. The key file itself stays wherever you
saved it; keep it somewhere private.

## Standard vs. batch mode

There are two ways this backend can transcribe. You pick with the
**"Batch mode (cheaper, slower)"** checkbox.

- **Standard mode (default).** Online, near-real-time. The app sends your
  audio in short chunks and gets the transcript back right away. Costs
  about **$0.016 per minute**. No extra setup.
- **Batch mode.** About **75% cheaper (~$0.004 per minute)**, but it can
  take **up to ~24 hours** to come back, and it **needs a Google Cloud
  Storage bucket you own** (the app uploads the audio there, transcribes
  it, then deletes the uploaded copy). Enter your bucket name in the
  **"Cloud Storage bucket:"** field, which only appears when batch mode is
  on. The bucket entry is greyed out while batch mode is off.

Use standard mode for normal day-to-day work; use batch mode only when you
have a lot of audio, do not need it back quickly, and have a bucket set up.

## Speaker labels (diarization)

Tick **"Detect speakers (diarization)"** to have Google tag who is speaking
(`SPEAKER_1`, `SPEAKER_2`, …). This adds a per-segment speaker label to the
transcript.

## Which model / region (defaults)

The backend defaults to the **`chirp_2`** recognizer in the
**`us-central1`** region (config keys `gcloud_stt_model` /
`gcloud_stt_location`). `chirp_2` supports **language auto-detect and
multilingual** audio, so you can leave the language on **Auto**; the older
`long` model rejected `auto`. You can override either key in `config.json`
for a different model or region — an unavailable model surfaces a clear
error rather than crashing. Word-level time offsets are always requested, so
subtitle segments are timed from Google's word timings (not one flat block).

For a real-world quality comparison across all 8 selectable models (plus
every local model this app ships), see
[evaluations/STT_MODEL_COMPARISON_2026-08.md](evaluations/STT_MODEL_COMPARISON_2026-08.md) —
on a hard (weak audio, overlapping speakers) test clip, `chirp_3` and
`telephony` held up best; `short` and `chirp_telephony` returned nothing.

## The usage / cost figure is a LOCAL estimate

The box shows a line like:

```
This month: 12.5 / 60 free minutes  -  estimated cost ~ $0.20 of your $300 credit
```

Be aware of what this is and is not:

- The **minutes** are counted **locally by this app** — every time a
  transcription with this backend finishes, the app adds the audio length
  to a per-month counter and **resets it to 0 at the start of each month**
  (matching the free tier, which is 60 minutes every month).
- The **dollar figure is an estimate** computed from the published rate
  (~$0.016/min standard, ~$0.004/min batch) times the minutes you have used
  — **not** your real bill.
- Your **real remaining credit and bill are not readable from the
  service-account file** (that needs extra billing APIs and permissions),
  so the app cannot show the true number. For the authoritative figure,
  click **"Open billing/usage console"** (or go to
  https://console.cloud.google.com/billing).

Treat the in-app figure as a rough guide so you do not accidentally run far
past the free tier; check the console for the real numbers.

## Privacy / offline trade-off (read this)

- **Your audio leaves your machine.** It is uploaded to Google for
  transcription. The default engines (faster-whisper, whisper.cpp,
  parakeet) never do this.
- The app makes this loud: the box is labelled "uploads audio", and there
  is a red privacy note.
- Use this backend only for content you are allowed to send to a cloud
  service.

## Testing the connection

The **"Test connection"** button:

1. Installs the Google Cloud client libraries on first use (they are not
   bundled, to keep the base install small). This needs internet and may
   take a minute; the box shows an "Installing…" status while it runs.
2. Reads your JSON file, checks it has a project, and builds the
   Speech-to-Text client. A clean result means your service account is
   accepted and the API is reachable — without spending any transcription
   minutes.

If it fails, the message tells you what to fix (enable the API, re-download
a fresh key, check the role, or check your internet connection).
