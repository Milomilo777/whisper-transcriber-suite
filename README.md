<div align="center">

<img src="docs/img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Interviews with speaker labels, timed lecture subtitles, subtitled video from a link and live captions, all on your own computer." width="100%">

# Whisper Transcriber Suite

**Free, offline transcription and subtitles for long recordings in your language — on an ordinary laptop, with no account and no audio upload.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=downloads&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](LICENSE)

### [Download for Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS and Linux: see [Download](#download).

No install? **[Try it in your browser](https://whisper-transcriber-suite.com/try/)**: transcribe a short file
(up to 10 minutes) right in the page and get TXT, SRT or VTT. The audio never leaves your device.

Step-by-step guides: [YouTube video to text](https://whisper-transcriber-suite.com/youtube-to-text/) · [video to SRT subtitles](https://whisper-transcriber-suite.com/video-to-srt/) · [transcripts with speaker labels](https://whisper-transcriber-suite.com/speaker-labels/)

<!-- language-links:start -->

**English** · [Deutsch](docs/i18n/README.de.md) · [Français](docs/i18n/README.fr.md) · [Español](docs/i18n/README.es.md) · [Italiano](docs/i18n/README.it.md) · [Português (Brasil)](docs/i18n/README.pt-BR.md) · [Português (Portugal)](docs/i18n/README.pt.md) · [Nederlands](docs/i18n/README.nl.md) · [Polski](docs/i18n/README.pl.md) · [Русский](docs/i18n/README.ru.md) · [Українська](docs/i18n/README.uk.md) · [Türkçe](docs/i18n/README.tr.md) · [Čeština](docs/i18n/README.cs.md) · [Slovenčina](docs/i18n/README.sk.md) · [Magyar](docs/i18n/README.hu.md) · [Română](docs/i18n/README.ro.md) · [Български](docs/i18n/README.bg.md) · [Ελληνικά](docs/i18n/README.el.md) · [Svenska](docs/i18n/README.sv.md) · [Dansk](docs/i18n/README.da.md) · [Norsk bokmål](docs/i18n/README.nb.md) · [Suomi](docs/i18n/README.fi.md) · [Hrvatski](docs/i18n/README.hr.md) · [Српски](docs/i18n/README.sr.md) · [Slovenščina](docs/i18n/README.sl.md) · [Lietuvių](docs/i18n/README.lt.md) · [简体中文](docs/i18n/README.zh-CN.md) · [繁體中文](docs/i18n/README.zh-TW.md) · [日本語](docs/i18n/README.ja.md) · [한국어](docs/i18n/README.ko.md) · [Tiếng Việt](docs/i18n/README.vi.md) · [ไทย](docs/i18n/README.th.md) · [Bahasa Indonesia](docs/i18n/README.id.md) · [Bahasa Melayu](docs/i18n/README.ms.md) · [हिन्दी](docs/i18n/README.hi.md) · [العربية](docs/i18n/README.ar.md) · [فارسی](docs/i18n/README.fa.md) · [עברית](docs/i18n/README.he.md) · [Latviešu](docs/i18n/README.lv.md) · [Català](docs/i18n/README.ca.md) · [বাংলা](docs/i18n/README.bn.md) · [Filipino](docs/i18n/README.fil.md)

<!-- language-links:end -->

</div>

## Who it is for

Subtitlers, translators, researchers and journalists who turn long
recordings (interviews, lectures, talks, videos) into text or subtitles.
Drop in an audio or video file and the transcript is written next to it. The speech engine runs on your own computer, so there is
no per-minute cost and, once the model is downloaded, no internet connection
is needed.

<div align="center">
<img src="docs/img/screenshot-transcribe.png" alt="The Transcribe tab: a drop target, engine and language pickers, speaker-label and word-timestamp options" width="80%">
</div>

## What's new in 2.2

- **A simpler Transcribe tab:** pick **Accuracy** (Fast, Balanced or Best) and the app chooses a model that fits your language and your computer, with its download size shown. The rarer options wait under **More options**.
- **Right to left:** with a Persian, Arabic or Hebrew interface the tabs, lists, dialogs and tick boxes mirror (Windows).
- **From your phone:** turn on *Share on local network*, scan the QR code and send a recording from a phone on the same Wi-Fi.
- **A compact Download form** and a calmer Queue, with plainer words throughout.
- **Every message translated** in all 42 interface languages, and many fixes that keep your settings, history and finished work safe.

Version 2.1 added the interface in 42 languages, reliable speaker labels and safer saving; version 2.0 added the queue's speed and time left, [subtitled video from a link](docs/SUBTITLED_VIDEO.md), transcripts as an offline web page, a checkable Work offline mode and translation to English. Full list: [CHANGELOG](docs/CHANGELOG.md).

## Features

<div align="center">
<img src="docs/img/promo-features.svg" alt="Speaker labels, local engines faster-whisper, whisper.cpp and Parakeet, 14 transcript formats, no cloud and no cost." width="80%">
</div>

- **Local engines:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (default), whisper.cpp and NVIDIA Parakeet, for the many languages Whisper
  recognises. Uses an NVIDIA GPU through CUDA when it can, otherwise the CPU.
- **The app in your language:** menus, buttons and messages in 42 languages
  (machine-translated, marked as such; corrections welcome). It follows your
  system language, or you pick one in Advanced settings. Persian, Arabic and
  Hebrew are offered on Windows for now.
- **14 output formats:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX and
  PDF, plus the oTranscribe, ELAN, InqScribe and Express Scribe formats. DOCX
  and PDF draw every script, and Persian, Arabic and Urdu read right to left
  with joined letters.
- **Shareable web page:** save a finished transcript as one `.html` file that
  works offline in any browser; click a word to hear it, search, jump to
  chapters.
- **Speaker labels** without a Hugging Face account, plus word timestamps and
  time-range clipping.
- **Interrupted jobs resume** from their last checkpoint instead of starting
  over (default engine).
- **Online videos:** download from any site [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  supports and transcribe when the download finishes.
- **Link to subtitled video:** one tick turns a link into `<title>-subbed.mp4`
  with the subtitles burned in: download, transcribe and burn in one queued job
  ([docs/SUBTITLED_VIDEO.md](docs/SUBTITLED_VIDEO.md)).
- **Live:** transcribe a microphone, or the system audio on Windows, as it
  happens ([docs/LIVE.md](docs/LIVE.md)).
- **Batch queue and watched folder** for many files.
- **Local-network mode:** a transcription page and an OpenAI-compatible API for
  the other devices on your network ([docs/SERVER.md](docs/SERVER.md)).
- **Optional, off by default:** AI tools for a finished transcript (summary,
  questions, bilingual SRT), and offline text to voice with voice cloning.

How it compares with Subtitle Edit, Vibe, Buzz, noScribe and aTrain,
including when another app is the better pick:
**[docs/COMPARISON.md](docs/COMPARISON.md)**.

## Download

Latest release: **[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| File | For |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 or 11, 64-bit. Most people want this one. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows without installing: unzip and run. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Macs with Apple silicon, macOS 14 or newer. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Intel Macs, macOS 10.15 or newer. |

Linux runs from source: [platform/linux/README.md](platform/linux/README.md).

<div align="center">
<img src="docs/img/promo-release.svg" alt="The words Sound in become a timed transcript of two speakers, saved as SRT, DOCX and PDF, with no account and no upload." width="80%">
</div>

The bundled FFmpeg is a GPL build. Its corresponding source is attached to each release as
`WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*` files; the exact links are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

ffmpeg and yt-dlp are bundled. On first launch a quick start window picks
the speech model for your language: Fast (Small, about 500 MB) or Best
quality (up to about 3 GB); it downloads once, on first use. Plan for 8 GB
of RAM; on a CPU the Large models take about 1.5–2.5 times the length of
the audio and Small about half, an NVIDIA GPU is much faster. The Windows builds are not code-signed and the Mac builds are not
notarized, so SmartScreen and Gatekeeper warn on first launch;
[docs/INSTALL.md](docs/INSTALL.md) shows what to click. To update, run the
newer installer over the old one; settings are kept.

**Downloads by version** (each badge counts only that version's own
release — older versions stay published and their counts are never
reset):

[![all versions](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/total?label=all%20versions&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases)
[![v2.2.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.2.0/total?label=v2.2.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.2.0)
[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## What leaves your computer

With the default settings your audio and transcripts stay on your computer.
The app does use the network for:

- downloading a model or an optional component the first time it is needed;
- its online settings at startup and a daily update check on GitHub, which
  only tells you about a new version;
- usage statistics, on by default, after each finished transcription: model,
  language, durations, word count, app version, operating system, CPU and
  memory size, and region, never the file's name. Turn them off under
  **Help → Usage statistics**.

Audio or transcript text is sent only if you choose a cloud engine (Gemini API
or Google Cloud Speech-to-Text) or connect a remote AI provider yourself.
**File → Work offline** stops all of it. Every connection is listed in
[docs/CONFIG.md](docs/CONFIG.md#network-use).

<div align="center">
<img src="docs/img/promo-loom.svg" alt="Per-word timed subtitles, English subtitles offline with faster-whisper, whisper.cpp and Parakeet, 14 transcript formats, no account, BSD-3-Clause." width="80%">
</div>

## Documentation

[Install](docs/INSTALL.md) · [Configuration](docs/CONFIG.md) ·
[Live transcription](docs/LIVE.md) · [Local-network mode and API](docs/SERVER.md) ·
[Cloud engines](docs/CLOUD_STT.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Changelog](docs/CHANGELOG.md) · [All docs](docs/README.md)

## Build from source

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Needs Python 3.11 or newer. Build pipelines: [docs/BUILD.md](docs/BUILD.md). Tests and pull requests:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing and contact

- **Bugs and feature requests:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Questions and ideas:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Everything else:** by email to [admin@whisper-transcriber-suite.com](mailto:admin@whisper-transcriber-suite.com),
  or through the [Contact section of the website](https://whisper-transcriber-suite.com/#contact)
- **Security reports:** [SECURITY.md](SECURITY.md)

This project follows the [Contributor Covenant](.github/CODE_OF_CONDUCT.md).
If the app saves you time, a Star at the top of this page helps other people
find it.

## How this project is built

The maintainer develops it with heavy help from AI coding assistants (mainly Claude). Type checks
and the unit tests must pass before each commit, and CI runs them again on Windows and Linux after
every push. The [release checklist](docs/RELEASE_PROCESS.md) includes a manual install test on a
real machine. Commits made with AI help now name the model in an `Assisted-by:` line; many older
ones carry a `Co-Authored-By: Claude` line instead.

## License

Copyright (c) 2026 translation-robot (co-author). The project lives in this repository,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
The project's own source is under the [BSD 3-Clause License](LICENSE). Bundled
tools, the Python runtime and the models keep their own licences; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
