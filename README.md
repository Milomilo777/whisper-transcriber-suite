<!--
    title: Whisper Transcriber Suite — offline audio & video transcription for Windows, macOS and Linux
    description: Desktop app that runs OpenAI Whisper locally via faster-whisper. Transcribe audio and video to SRT, VTT, DOCX and PDF with no cloud, no account and no upload. Speaker diarisation, batch queue, yt-dlp downloads, live microphone transcription and a local-network mode.
    keywords: offline speech to text, local whisper GUI, faster-whisper desktop app, audio to text, video to text, subtitle generator, SRT VTT generator, transcription software, speaker diarization, private on-device transcription, yt-dlp downloader, live microphone transcription
    author: translation-robot
    product-type: Desktop transcription software
    platforms: Windows, macOS, Linux
    technology-stack: faster-whisper, CTranslate2, whisper.cpp, NVIDIA Parakeet, Tkinter, yt-dlp, ffmpeg, sherpa-onnx, stable-ts
    license: BSD-3-Clause
-->

<div align="center">

<img src="docs/img/hero.png" alt="Whisper Transcriber Suite — transcribe audio and video on your own machine. No cloud, no account, no upload." width="100%">

# Whisper Transcriber Suite

### Drag in an audio or video file. Get back a **timed, formatted transcript** — without it ever leaving your computer.

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![codecov](https://codecov.io/gh/Milomilo777/whisper-transcriber-suite/graph/badge.svg)](https://codecov.io/gh/Milomilo777/whisper-transcriber-suite)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#download)
[![Stars](https://img.shields.io/github/stars/Milomilo777/whisper-transcriber-suite?style=flat&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)

### [⬇  Download for Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

**[Download](#download)** · **[Screenshots](#what-it-looks-like)** ·
**[Features](#features)** · **[How it works](#how-it-works)** ·
**[Privacy](#offline-by-default)** · **[Docs](#documentation)** ·
**[FAQ](#frequently-asked-questions)** ·
**[Build from source](#build-from-source)**

<!-- Language switcher. Flag images rather than flag emoji on purpose:
     Windows does not render regional-indicator emoji as flags, so 🇰🇷
     shows up as the letters "KR" for a large share of readers. -->
<p>
  <img src="https://flagcdn.com/16x12/us.png" alt="" width="16" height="12">
  <b>English</b> ∙
  <a href="docs/i18n/README.zh-CN.md"><img src="https://flagcdn.com/16x12/cn.png" alt="" width="16" height="12"> 简体中文</a> ∙
  <a href="docs/i18n/README.ja.md"><img src="https://flagcdn.com/16x12/jp.png" alt="" width="16" height="12"> 日本語</a> ∙
  <a href="docs/i18n/README.ko.md"><img src="https://flagcdn.com/16x12/kr.png" alt="" width="16" height="12"> 한국어</a> ∙
  <a href="docs/i18n/README.de.md"><img src="https://flagcdn.com/16x12/de.png" alt="" width="16" height="12"> Deutsch</a> ∙
  <a href="docs/i18n/README.es.md"><img src="https://flagcdn.com/16x12/es.png" alt="" width="16" height="12"> Español</a> ∙
  <a href="docs/i18n/README.fr.md"><img src="https://flagcdn.com/16x12/fr.png" alt="" width="16" height="12"> Français</a> ∙
  <a href="docs/i18n/README.pt.md"><img src="https://flagcdn.com/16x12/pt.png" alt="" width="16" height="12"> Português</a> ∙
  <a href="docs/i18n/README.fa.md"><img src="https://flagcdn.com/16x12/ir.png" alt="" width="16" height="12"> فارسی</a>
</p>

</div>

---

A desktop app that runs OpenAI's Whisper model **locally** — via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) — so transcription
costs nothing per minute, works on a plane, and never uploads your recording to
anyone. Drop a file in and it writes `.srt`, `.vtt`, `.txt`, `.json`, `.docx`,
`.pdf`, `.ass` and more, right next to the original. It also downloads from any site
`yt-dlp` supports, labels speakers, batches a queue of jobs, and can turn itself
into a transcription page for the other devices on your network.

No account. No API key. No subscription. Your files stay on your disk.

- 🔒 **Runs on your machine** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) by default, plus **whisper.cpp** and **NVIDIA Parakeet**
- 📝 **14 output formats** — `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, plus oTranscribe / ELAN / InqScribe / Express Scribe
- 🎙️ **Live transcription** — a microphone or the system audio, transcribed as it happens → [docs/LIVE.md](docs/LIVE.md)
- 🗣️ **Speaker labels** — offline diarisation, per-word timestamps, time-range clipping
- 🎬 **Downloads** — any `yt-dlp` site, with optional transcribe-on-finish
- 🧹 **Adaptive denoise** — measures the audio and only cleans it when that helps → [docs/DENOISE.md](docs/DENOISE.md)
- 🌐 **Local-network mode** — turn this machine into a transcription page for your other devices
- 💸 **Free and BSD-3 licensed** — no per-minute cost, no subscription, no telemetry by default

## Download

Grab the latest build from the **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**:

| Asset | Size | Best for |
|---|---|---|
| **`WhisperTranscriberSuite-…-Setup-Standard.exe`** | ~215 MB | **Most people.** A normal installer: Start-menu shortcut, upgrades in place over an older version, files visible on disk. |
| **`WhisperTranscriberSuite-…-Portable.zip`** | ~330 MB | Unzip and run. No installation, no admin rights, happy on a USB stick. |
| **`WhisperTranscriberSuite-…-macOS-*.dmg`** | ~400 MB | macOS (x64 and arm64 builds are published separately). |

**Downloads by version** (each badge counts only that version's own
release — older versions stay published and their counts are never
reset):

[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

Everything needed is inside — a bundled Python, `ffmpeg`, `ffprobe` and
`yt-dlp`. The only thing fetched later is the speech model itself
(**~1–3 GB, once**, on first launch); after that the app is fully offline.

Step-by-step walkthrough, including what to click past on Windows SmartScreen:
**[docs/INSTALL.md](docs/INSTALL.md)**.

## What it looks like

<div align="center">

<img src="docs/img/screenshot-transcribe.png" alt="The Transcribe tab: a drop target, engine and language pickers, speaker-label and word-timestamp options" width="88%">

<sub>Drop a file, pick your options, press Transcribe. That is the whole workflow.</sub>

</div>

<details>
<summary><b>The other four tabs</b></summary>

<br>

**Transcription Queue** — batch jobs with live progress; pause, resume, cancel,
re-run or remove any row.

<img src="docs/img/screenshot-queue.png" alt="Transcription Queue tab" width="100%">

**Download Videos** — any `yt-dlp` site: pick a format, clip a time range, pull
subtitles, optionally transcribe as soon as the download finishes.

<img src="docs/img/screenshot-download.png" alt="Download Videos tab" width="100%">

**Video Tiling** — play one live stream as a full-screen N×N video wall,
optionally across several monitors.

<img src="docs/img/screenshot-tiling.png" alt="Video Tiling tab" width="100%">

**Web / LAN access** — one button turns this machine into a transcription page
for the phones and PCs on your network.

<img src="docs/img/screenshot-web.png" alt="Web / LAN access tab" width="100%">

</details>

## Features

<div align="center">

<img src="docs/img/features.png" alt="Five tabs, one window: Transcribe, Transcription Queue, Download Videos, Video Tiling, Web/LAN access, Convert transcript" width="100%">

</div>

| | |
|---|---|
| **Local transcription** | Whisper `large-v3` by default, plus `large-v3-turbo` and `distil-large-v3.5`. Backends: `faster_whisper` (default), `whisper.cpp`, NVIDIA Parakeet. |
| **Many output formats** | `srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf` — written next to your input file. |
| **Convert transcript** | Re-emit an existing transcript into the formats above, or into oTranscribe / ELAN / InqScribe / Express Scribe. Reads `.ass` / `.ssa` too. |
| **Live transcription** | Transcribe a microphone — or whatever this machine is playing — as it happens. Chunks are cut at natural pauses so words are never split in half. |
| **Speaker diarisation** | Optional "Identify speakers", plus per-word timestamps and time-range clipping. |
| **Adaptive denoise** | Measures each recording first and only cleans it when the measurement says that helps; verifies its own output and reverts if it removed speech. |
| **Last-Result card** | File sizes, one-click **Open file** / **Open folder**, and an in-app viewer with split-pane click-to-seek playback. |
| **Batch queue** | Live status for every pending and running job, with **Pause / Resume / Cancel / Re-run / Remove** always one click away. |
| **Downloads** | Anything `yt-dlp` handles, plus Supreme Master TV episode links. Downloads resume rather than restart. |
| **Video wall** | Tile one live stream as an N×N grid across one or many monitors. |
| **Local network mode** | A stdlib-only web server so other devices can transcribe through this machine — optional password, off until you start it. |
| **Post-processing** | Automatic chapters and hallucination detection, both toggleable. |

Keyboard: `Ctrl+O` browse · `Ctrl+Enter` transcribe · `Esc` cancel ·
`Ctrl+Q` exit.

## How it works

<div align="center">

<img src="docs/img/how-it-works.png" alt="Drop a file, the Tk GUI queues it, a worker subprocess holds the model in memory and runs faster-whisper, and the transcript lands in your folder" width="100%">

</div>

The Tk GUI runs in the main process. Each transcription job runs in a
long-lived subprocess worker that keeps the Whisper model in memory and talks
back over newline-delimited JSON on stdin/stdout; `yt-dlp` gets its own
subprocess per download. A per-worker UUID token and a 5-second heartbeat keep
that routing robust against PID recycling and let the GUI detect a wedged
worker instead of hanging with it.

Deeper: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (prose) ·
[docs/architecture.svg](docs/architecture.svg) (full diagram) ·
[docs/DECISIONS.md](docs/DECISIONS.md) (why things are the way they are).

## Offline by default

Every default backend runs on your machine. Nothing is uploaded, no account
exists, and the app works with the network unplugged once the model is
downloaded.

> [!IMPORTANT]
> Two **opt-in** backends break that guarantee, and both are off unless you go
> into **Advanced → Backend** and choose them. Use them only for content you
> are willing to send to a third party.
>
> - **`cloud_stt`** — Google **Gemini API**, authenticated with a free API key
>   you paste. Quickest to set up. → [docs/CLOUD_STT.md](docs/CLOUD_STT.md)
> - **`google_cloud_stt`** — full **Google Cloud Speech-to-Text**, authenticated
>   with a service-account JSON file. 60 free minutes/month, speaker labels, a
>   cheaper batch mode. → [docs/CLOUD_STT_GOOGLE.md](docs/CLOUD_STT_GOOGLE.md)

The optional update check is likewise **notify-only**: it asks GitHub whether a
newer release exists, at most once a day, and never downloads or installs
anything by itself. Turn it off with `update_check_enabled`.

<details>
<summary><b>First run — choosing where the model lives</b></summary>

<br>

On first launch the app asks where to store the Whisper model files. The
default is a private per-user cache that is always writable —
`%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models` — never the Program Files install
directory. Pick anywhere you like instead: an external drive, a network share.

The choice is saved to `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` under
`hub_folder`, and the dialog never appears again. To start over:

```cmd
WhisperTranscriberSuite.exe --safe-mode
```

That moves the user config aside and re-fires the first-run dialog with the
defaults.

</details>

<details>
<summary><b>Configuration keys</b></summary>

<br>

User settings live at `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json`.

| Key | What it controls |
|---|---|
| `hub_folder` | Where Whisper model files are stored (set by the first-run dialog) |
| `model_path` | Per-model override; derived from `hub_folder + model.name` when unset |
| `whisper_model` | `large-v3` (default), `large-v3-turbo`, `distil-large-v3.5` |
| `transcribe_backend` | `faster_whisper` (default), `whisper_cpp`, `parakeet`, `cloud_stt`, `google_cloud_stt` |
| `auto_chapters_enabled`, `hallucination_detect_enabled` | Post-process toggles |
| `update_check_enabled` | Opt-in GitHub update check (on by default; notify-only) |
| `last_update_check` | ISO date of the last check (once-per-day throttle) |

Full reference: [docs/CONFIG.md](docs/CONFIG.md).

</details>

<details>
<summary><b>Updating to a newer version</b></summary>

<br>

**No uninstall needed.** The Standard installer uses a stable application ID,
so you just download the newer `…-Setup-Standard.exe` and run it — it upgrades
over the existing install and keeps your shortcut and settings. The Portable
build is self-contained: replace the old folder with the new one.

**Help → Check for updates…** runs the check on demand and also tells you when
you are already current. The quiet daily check stays silent unless something
newer exists, and fails silently when offline.

</details>

<details>
<summary><b>Share it on your local network</b></summary>

<br>

Rather than installing the app on every machine, let people on a trusted
network transcribe through this one. The **Web / LAN access** tab does it with
one button, an optional port, a "Share on local network" checkbox and an
optional access password.

For headless or scripted use there is an equivalent command line (same
stdlib-only HTTP engine):

```cmd
python gui.py serve          REM loopback only (no firewall prompt)
python gui.py serve --lan    REM share on the LAN (allow the firewall prompt)
```

It has no accounts and no encryption — anyone who can reach the address (and
knows the password, if you set one) can use it. Trusted networks only. Routes,
the upload cap and the `--token` option: [docs/SERVER.md](docs/SERVER.md).

</details>

## Build from source

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Updating a source checkout later: `platform\windows\update.bat` on Windows,
`platform/linux/update.sh` on Linux — both pull the latest source and
refresh the dependencies ([platform/windows/README.md](platform/windows/README.md)).

[docs/BUILD.md](docs/BUILD.md) covers the build pipelines — which two are
actually shipped and which are kept alive but unpublished —  and
[docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md) has the ship sequence.

Regenerate the images in this README with `python tools/make_graphics.py`
(they are drawn by that script, not pasted in from a design tool).

## Project status

Actively maintained. The quality bar enforced on every commit:

- **pyright** on `app/` and `core/` — 0 errors, 0 warnings, 0 informations.
- The hermetic unit + integration suite (`pytest tests/ --ignore=tests/smoke`)
  runs on **every push, on Windows and Ubuntu** — see
  [docs/TESTING.md](docs/TESTING.md). Coverage is reported by the badge above.

[docs/CHANGELOG.md](docs/CHANGELOG.md) has what shipped recently; superseded
freeze and stability audits are archived under
[docs/history/](docs/history/).

## Documentation

| Doc | Audience |
|---|---|
| [INSTALL.md](docs/INSTALL.md) | End-user install + troubleshooting |
| [SERVER.md](docs/SERVER.md) | Local-network / web server mode (`gui.py serve`) |
| [BUILD.md](docs/BUILD.md) | Build the deliverables yourself |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Process model, threading, protocols |
| [CONFIG.md](docs/CONFIG.md) | Every config key with defaults |
| [CLOUD_STT.md](docs/CLOUD_STT.md) | Optional Gemini-API backend (paste a key) |
| [CLOUD_STT_GOOGLE.md](docs/CLOUD_STT_GOOGLE.md) | Optional Google Cloud STT backend (service account, batch mode) |
| [LIVE.md](docs/LIVE.md) | The Live tab: microphone / system-audio transcription |
| [DENOISE.md](docs/DENOISE.md) | The adaptive denoise pre-process |
| [RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md) | How to ship a new version |
| [CHANGELOG.md](docs/CHANGELOG.md) | Version history |
| [DECISIONS.md](docs/DECISIONS.md) | Non-obvious design choices and why |
| [ROADMAP.md](docs/ROADMAP.md) · [roadmap/](docs/roadmap/) | What is being considered next |

> **Coding agents:** start at [`PROJECT_INDEX.md`](PROJECT_INDEX.md) — a
> generated, tool-neutral repo map built for fast, low-token onboarding.

## Frequently asked questions

**Is Whisper Transcriber Suite free?**
Yes. It's BSD-3-Clause licensed, with no subscription, no per-minute cost and
no telemetry by default. The Whisper model itself downloads once (~1–3 GB)
on first launch; after that the app runs fully offline.

**Does it upload my audio or video anywhere?**
No, not by default. Every default backend — faster-whisper, whisper.cpp,
NVIDIA Parakeet — runs locally on your machine. Two backends are opt-in only
(`cloud_stt` via the Gemini API, and `google_cloud_stt`), and both stay off
until you turn them on yourself in Advanced → Backend.

**What platforms does it run on?**
Windows, macOS and Linux. Published downloads are a Windows installer, a
Windows portable ZIP, and a macOS DMG; Linux runs from source
([docs/BUILD.md](docs/BUILD.md)).

**What transcript formats can it produce?**
`srt` `vtt` `ass` `tsv` `txt` `json` `lrc` `md` `docx` `pdf`, plus
oTranscribe, ELAN, InqScribe and Express Scribe.

**Can it label who is speaking?**
Yes — optional speaker diarisation ("Identify speakers"), with per-word
timestamps and time-range clipping.

**Can it transcribe a live microphone or system audio?**
Yes, from the Live tab. See [docs/LIVE.md](docs/LIVE.md).

**Can it download and transcribe online videos, e.g. from YouTube?**
Yes, any site `yt-dlp` supports, with an optional transcribe-on-finish step.

**Can it summarize a transcript, pull out action items, or answer questions
about it?**
Yes, via the optional AI Tools tab in the transcript viewer — summarize,
action items, ask-a-question, and a per-segment translate pass that writes a
bilingual `.srt`. It's off by default; turn it on in Advanced → AI Layer,
using either the bundled local model or your own OpenAI-compatible endpoint
(OpenAI, Ollama, LM Studio, OpenRouter).

**How is this different from calling the Whisper API directly?**
It runs the model locally via faster-whisper by default, so there's no
per-minute API cost and no audio leaves your machine — unless you explicitly
opt into one of the two cloud backends above.

**Can several people on the same network use it without installing it on
every machine?**
Yes — Web / LAN access mode turns this machine into a transcription page the
other devices on the network can use. See [docs/SERVER.md](docs/SERVER.md).

## Contributing

Issues, pull requests and
[Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions) are all
welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the dev setup, the quality bar
and the PR conventions; if you are new here, the
[`good first issue`](https://github.com/Milomilo777/whisper-transcriber-suite/labels/good%20first%20issue)
label is the place to start.

This project follows the [Contributor Covenant](.github/CODE_OF_CONDUCT.md).
Security reports go through [SECURITY.md](SECURITY.md).

## Author and license

Written by **translation-robot** — <https://github.com/translation-robot>.

This project's own source is licensed under the **BSD 3-Clause License** — see
[LICENSE](LICENSE). The bundled binaries (`ffmpeg`, `ffprobe`, `yt-dlp`), the
bundled Python runtime and packages, and the Whisper model itself keep their own
upstream licenses; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) summarises
them and says what to include when redistributing.

---

<div align="center">

**Keywords** — offline speech to text · local Whisper GUI · audio to text ·
video to text · subtitle generator · SRT VTT generator · transcription software ·
speaker diarization · faster-whisper desktop app · yt-dlp downloader ·
private on-device transcription · Windows · macOS · Linux

</div>
