<!--
    type: reference
    status: current
    created: 2026-10-05
-->

# Whisper Transcriber Suite compared with other free transcription apps

Last checked: 2026-10-05

This page compares Whisper Transcriber Suite (WTS) with five free, open-source
desktop apps that also transcribe speech on your own computer: Subtitle Edit,
Vibe, Buzz, noScribe and aTrain.

- Facts about the other apps come from each project's own README, docs,
  website and GitHub API, all read on the date above. Every fact has a source
  link in [Sources for the other apps](#sources-for-the-other-apps).
- Facts about WTS describe release v1.9.3 and were checked against this
  repository's code and docs on the same date; the file behind each one is in
  [Where the WTS facts come from](#where-the-wts-facts-come-from).
- "Not stated" means the cited source was read and says nothing on the point.
  It is not proof that the app lacks the feature.
- Apps change quickly. If a fact here is wrong or out of date, please
  [open an issue](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
  with a link to the source.

## Which one to choose

- **Choose Whisper Transcriber Suite if** you want one app that combines file
  transcription with a live microphone (and system audio on Windows), online
  video downloads with yt-dlp, a watched folder, 14 output formats (including
  DOCX, PDF and the ELAN, InqScribe, Express Scribe and oTranscribe formats)
  and a local-network mode that serves other devices through a browser page
  and an OpenAI-compatible transcription route. Some of these exist elsewhere
  too: Buzz, for example, has a live microphone and a watch folder. WTS also
  fits if you need a Windows portable ZIP, or a macOS build for Intel Macs
  running macOS 10.15 or newer.
- **Choose Subtitle Edit if** you want to pick from many speech engines in one
  app: its speech-to-text page lists several Whisper builds plus Parakeet,
  Canary, Qwen3-ASR, Voxtral and others, local and online. It also offers a
  Windows ARM64 build, Linux Flatpak and tar.gz builds, and a macOS build
  that is signed and notarized by Apple.
- **Choose Vibe if** you want a Windows installer that its docs say is
  code-signed, a README that names AMD and Intel GPUs next to NVIDIA (through
  Vulkan / CoreML; Subtitle Edit and Buzz also state Vulkan support), or Linux
  .deb and .rpm packages.
- **Choose Buzz if** you want Linux packages for Flatpak, Snap or AppImage, an
  install from PyPI, or Vulkan acceleration that its README says works on most
  GPUs, including integrated ones. New Buzz versions need an Apple silicon
  Mac; 1.4.5 is the last version for Intel Macs.
- **Choose noScribe if** you want Whisper (through faster-whisper) with
  pyannote speaker detection and a built-in transcript editor, and a macOS
  build for Apple Silicon signed with the author's Apple developer ID.
- **Choose aTrain if** you need output that MAXQDA, ATLAS.ti or NVivo can
  read, or want to install from the Microsoft Store or Flathub.

## When Whisper Transcriber Suite is not the right pick

- **You need a code-signed Windows installer or a notarized Mac app.** WTS has
  neither, so Windows SmartScreen and macOS Gatekeeper warn on first launch.
  Vibe documents a signed Windows installer; Subtitle Edit signs and
  notarizes its macOS build, and noScribe signs its Apple Silicon build.
- **Your GPU is from AMD or Intel, or you want GPU speed on a Mac.** WTS
  accelerates on NVIDIA GPUs (CUDA, for faster-whisper and Parakeet); its
  default engine, faster-whisper, runs on the CPU everywhere else. Vibe,
  Subtitle Edit and Buzz state Vulkan support, and Buzz states Apple silicon
  support.
- **You want the interface in a language other than English.** The WTS
  interface is English only (the README is translated into 8 languages).
  Subtitle Edit, Vibe, Buzz and noScribe have 35, 22, 16 and 9 interface
  language files or folders (English included).
- **You want a Linux package.** WTS runs on Linux from source, set up by an
  install script; there is no .deb, .rpm, Flatpak or Snap.
- **You want no data sent by default.** After each transcription that finishes
  in the desktop app, WTS sends one usage-statistics row (it includes the
  file name) unless you turn the switch off; see
  [Usage statistics](CONFIG.md#usage-statistics-p4-4) and the full list of
  [network connections](CONFIG.md#network-use).

## At a glance

| | Whisper Transcriber Suite | Subtitle Edit | Vibe | Buzz | noScribe | aTrain |
|---|---|---|---|---|---|---|
| Latest stable version | v1.9.3 (September 2026) | v5.2.0 (2026-09-10) | v3.2.2 (2026-09-05) | v1.4.5 (2026-08-23) | v0.7.2 (2026-06-02) | v1.4.1 (2026-01-28); v1.5.0 release candidates since 2026-08-19 |
| Licence | BSD-3-Clause | MIT | MIT | MIT | GPL-3.0 | AGPL-3.0 |
| Price | Free, no paid tier | Free; donations | Free; support link, no paid tier stated | Free, no paid tier stated | Free; donations | Free; Microsoft Store price not checked |
| Windows | 10 or 11, 64-bit: installer and portable ZIP | 10 22H2 or newer: x64 installer and zip, ARM64 zip | x64 installer | Yes (README sends Windows users to SourceForge) | Standard and CUDA installers | 10 and 11, from the Microsoft Store |
| macOS | Apple silicon (macOS 14+) and Intel (macOS 10.15+) | macOS 12 or newer, Apple silicon and Intel | Apple silicon and Intel | Apple silicon; 1.4.5 is the last version for Intel | Apple Silicon (macOS 14+); Intel gets 0.6 | Not in the current README (an older README lists an Apple Silicon beta) |
| Linux | From source, with an install script | Flatpak (x64), tar.gz (x64, ARM64) | .deb, .rpm | Flatpak, Snap, AppImage, PyPI | tar.gz (CPU or CUDA) or from source | Flathub |
| Speech engines | faster-whisper, whisper.cpp, NVIDIA Parakeet TDT v3 (local); Gemini API and Google Cloud Speech-to-Text (opt-in cloud) | Whisper builds (whisper.cpp, Faster-Whisper-XXL, CTranslate2, Const-me, WhisperX, OpenAI), Crisp ASR models (Parakeet, Canary, Voxtral and more), Qwen3-ASR, OpenAI-compatible servers, OpenRouter, Google Cloud | Whisper, Nemotron 3.5, Parakeet TDT v3, custom models; speaker diarization | Several Whisper backends, Hugging Face Whisper-type models; speaker identification | Whisper via faster-whisper; pyannote speaker detection | Whisper via faster-whisper; pyannote.audio speaker detection |
| GPU acceleration | NVIDIA (CUDA); the default engine uses the CPU otherwise | NVIDIA (CUDA), Vulkan (whisper.cpp) | NVIDIA, AMD, Intel (Vulkan); CoreML | NVIDIA (CUDA), Apple silicon, Vulkan | NVIDIA (CUDA) build, RTX 20xx or newer with 6 GB VRAM | NVIDIA (CUDA) only; otherwise CPU |
| Windows installer signed | No | Not stated | Yes, per the project's docs | No | No | From v1.5.0 (pre-release so far); Store packages signed by Microsoft |
| macOS app signed | Ad-hoc only, not notarized | Developer ID, notarized | Not checked | Not stated | Apple Silicon build: Developer ID | Not checked |
| Interface languages | English only | 35 language files | 22 locale files | 16 locale folders | 9 translation files | Not stated; no translation files found |

## Where the WTS facts come from

| Fact | Source in this repository |
|---|---|
| Version 1.9.3 | [`core/__init__.py`](../core/__init__.py), [`pyproject.toml`](../pyproject.toml), [CHANGELOG](CHANGELOG.md) |
| BSD-3-Clause licence, free | [`LICENSE`](../LICENSE) |
| Windows 10 or 11, 64-bit; not code-signed (SmartScreen warning) | [INSTALL.md](INSTALL.md) |
| Windows installer and portable ZIP | [BUILD.md](BUILD.md) |
| macOS builds for Apple silicon (macOS 14+) and Intel (macOS 10.15+), ad-hoc signed, not notarized | [MACOS_BUILD_NOTES.md](MACOS_BUILD_NOTES.md) |
| Linux from source with an install script | [`platform/linux/README.md`](../platform/linux/README.md) |
| Speech engines: faster-whisper (default), whisper.cpp, NVIDIA Parakeet TDT v3 (any Hugging Face transformers speech model can replace it), Gemini API, Google Cloud Speech-to-Text | [`core/backends/availability.py`](../core/backends/availability.py), [`core/backends/nvidia_asr.py`](../core/backends/nvidia_asr.py) |
| NVIDIA CUDA for faster-whisper and Parakeet; faster-whisper on the CPU otherwise (OpenVINO, DirectML and Snapdragon NPU tiers are only listed, as "backend not bundled") | [`core/hardware.py`](../core/hardware.py), [`core/backends/faster_whisper_be.py`](../core/backends/faster_whisper_be.py), [`core/backends/nvidia_asr.py`](../core/backends/nvidia_asr.py) |
| 14 output formats (the registry also holds a 15th entry, `smtv_docx`, a project-specific layout of the DOCX output) | [`core/writers/__init__.py`](../core/writers/__init__.py) |
| Live microphone; system audio on Windows (WASAPI loopback) | [`core/recorder.py`](../core/recorder.py), [LIVE.md](LIVE.md) |
| Online video downloads with yt-dlp | [`core/tiling.py`](../core/tiling.py) |
| Watched folder | [`core/watcher.py`](../core/watcher.py) |
| Local-network mode: browser page, JSON job API, OpenAI-compatible `/v1/audio/transcriptions`, optional HTTPS | [SERVER.md](SERVER.md), [`core/server/httpd.py`](../core/server/httpd.py), [`core/server/tls.py`](../core/server/tls.py) |
| Interface in English only (no translation files and no interface-language setting) | [`core/config.py`](../core/config.py) |
| README in 8 more languages | [`docs/i18n/`](i18n/) |
| Usage statistics on by default, file name included | [CONFIG.md](CONFIG.md#usage-statistics-p4-4), [`core/stats.py`](../core/stats.py), [`core/config.py`](../core/config.py) |

## Sources for the other apps

All pages below were read on 2026-10-05. `api.github.com` links are GitHub's
public API for the project's repository, releases or folder listing.

### Subtitle Edit

| Fact | Source |
|---|---|
| Version, release files, dates | https://api.github.com/repos/SubtitleEdit/subtitleedit/releases/latest , https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.2.0 |
| Licence | https://api.github.com/repos/SubtitleEdit/subtitleedit |
| Operating systems, macOS signing and notarization, donations | https://raw.githubusercontent.com/SubtitleEdit/subtitleedit/main/README.md , https://subtitleedit.github.io/subtitleedit/ |
| Speech engines, GPU | https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/speech-to-text.md , https://raw.githubusercontent.com/SubtitleEdit/subtitleedit/main/docs/faq.md |
| Windows signing not stated (no signing step in the build workflows) | https://api.github.com/repos/SubtitleEdit/subtitleedit/git/trees/HEAD?recursive=1 |
| Interface languages | https://api.github.com/repos/SubtitleEdit/subtitleedit/contents/src/ui/Assets/Languages |

### Vibe

| Fact | Source |
|---|---|
| Version, release files, dates | https://api.github.com/repos/thewh1teagle/vibe/releases/latest , https://github.com/thewh1teagle/vibe/releases/tag/v3.2.2 |
| Licence | https://api.github.com/repos/thewh1teagle/vibe |
| Operating systems, speech engines, diarization, GPU, price | https://raw.githubusercontent.com/thewh1teagle/vibe/main/README.md |
| Windows signing | https://raw.githubusercontent.com/thewh1teagle/vibe/main/docs/code-signing/WINDOWS_ESIGNING.md |
| macOS signing guide (released file not checked) | https://raw.githubusercontent.com/thewh1teagle/vibe/main/docs/code-signing/MACOS.md |
| Interface languages | https://api.github.com/repos/thewh1teagle/vibe/contents/i18n/desktop |

### Buzz

| Fact | Source |
|---|---|
| Version, release files, dates | https://api.github.com/repos/chidiwilliams/buzz/releases/latest , https://github.com/chidiwilliams/buzz/releases/tag/v1.4.5 |
| Licence | https://api.github.com/repos/chidiwilliams/buzz |
| Operating systems, speech engines, speaker identification, GPU, Windows signing, price | https://raw.githubusercontent.com/chidiwilliams/buzz/main/README.md |
| Interface languages | https://api.github.com/repos/chidiwilliams/buzz/contents/buzz/locale |

### noScribe

| Fact | Source |
|---|---|
| Version, release date | https://api.github.com/repos/kaixxx/noScribe/releases/latest |
| Licence | https://api.github.com/repos/kaixxx/noScribe |
| Operating systems, GPU, Windows and macOS signing | https://noscribe.de/en/docs/download-installation/ |
| Speech engine, speaker detection, editor, macOS signing, price | https://raw.githubusercontent.com/kaixxx/noScribe/main/README.md , https://noscribe.de/en/ |
| Interface languages | https://api.github.com/repos/kaixxx/noScribe/contents/trans |

### aTrain

aTrain's default branch is `develop`; its `main` README is older.

| Fact | Source |
|---|---|
| Versions, release candidates, dates | https://api.github.com/repos/aTrainTranscription/aTrain/releases?per_page=4 , https://github.com/aTrainTranscription/aTrain/releases/tag/v1.4.1 |
| Licence | https://api.github.com/repos/aTrainTranscription/aTrain |
| Operating systems, speech engine, speaker detection, MAXQDA / ATLAS.ti / NVivo output, GPU, price | https://raw.githubusercontent.com/aTrainTranscription/aTrain/develop/README.md |
| Apple Silicon beta in the older README | https://raw.githubusercontent.com/aTrainTranscription/aTrain/main/README.md |
| Signing policy | https://raw.githubusercontent.com/aTrainTranscription/aTrain/develop/docs/code-signing-policy.md |
| Interface languages (no translation files in the source tree) | https://api.github.com/repos/aTrainTranscription/aTrain/git/trees/develop?recursive=1 |

## Not checked

- The Windows signature of Subtitle Edit's installer (its docs are silent; the
  file was not downloaded and inspected).
- Whether Vibe's released Windows and macOS files carry the signatures its
  docs describe.
- aTrain's Microsoft Store price.
- Whether WTS's optional whisper.cpp engine uses the Apple GPU on a Mac (WTS
  sets no GPU option for it).
- Accuracy and speed. No benchmark is part of this page; WTS's own engine
  tests are in [evaluations/](evaluations/).
- Accessibility, package-manager availability (winget, Scoop, Homebrew) and
  download numbers.
