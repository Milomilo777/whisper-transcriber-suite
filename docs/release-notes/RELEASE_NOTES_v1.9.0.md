# Whisper Transcriber Suite v1.9.0

**This release starts with the macOS builds** — the first Mac builds that
were built *and tested on a real Mac* before shipping. The Windows
installer and portable ZIP for v1.9.0 will be added to this release
separately; until then, Windows users can keep using
[v1.8.0](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0).

## macOS — what's new

Earlier `.dmg` builds could not run ffmpeg on most Macs (they carried a
Homebrew ffmpeg without its libraries), had no working video downloader,
and declared the wrong minimum macOS. All of that is fixed, and every Mac
build is now checked before upload by a real transcription with the
finished app. What was tested for v1.9.0:

- **Intel (x64)** — on a real Intel Mac running macOS 10.15.7: installed
  from a browser-quarantined `.dmg` via Finder, opened past Gatekeeper,
  downloaded the Small model inside the app, transcribed a WAV and an MP4
  (correct text), downloaded a YouTube video. No Homebrew, no Python,
  nothing else installed.
- **Apple silicon (arm64)** — built and tested on GitHub's Apple-silicon
  Mac runner: real transcription with the finished app (WAV + MP4), GUI
  launch, bundled ffmpeg and yt-dlp.

| File | For | Needs |
|---|---|---|
| `WhisperTranscriberSuite-v1.9.0-macOS-arm64.dmg` | Apple silicon (M1/M2/M3/M4…) | macOS 14 Sonoma or newer (every Apple-silicon Mac can install it) |
| `WhisperTranscriberSuite-v1.9.0-macOS-x64.dmg` | Intel Macs | macOS 10.15 Catalina or newer |

Not sure which one? Apple menu → About This Mac: "Chip: Apple M…" →
arm64, "Processor: Intel…" → x64. Each `.dmg` has a `.sha256` next to it.

### Installing on a Mac (the app is free but not signed by Apple)

**Easiest — one line in Terminal, no security warning at all** (files
downloaded by `curl` are not quarantined):

```bash
A=$([ "$(uname -m)" = arm64 ] && echo arm64 || echo x64); curl -fL -o /tmp/wts.dmg "https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.0/WhisperTranscriberSuite-v1.9.0-macOS-$A.dmg" && hdiutil attach -nobrowse -quiet -mountpoint /tmp/wts-dmg /tmp/wts.dmg && cp -R "/tmp/wts-dmg/Whisper Transcriber Suite.app" /Applications/ && hdiutil detach -quiet /tmp/wts-dmg && rm /tmp/wts.dmg && open "/Applications/Whisper Transcriber Suite.app"
```

**Or the usual way:** open the `.dmg`, drag *Whisper Transcriber Suite*
into *Applications*. The first time you open it macOS says it "can't be
opened because Apple cannot check it for malicious software". Then:

- **macOS 14 and older:** right-click (or Control-click) the app →
  **Open** → **Open**. Only needed once.
- **macOS 15 and newer:** click *Done*, then System Settings → Privacy &
  Security → scroll down → **Open Anyway**.
- Or in Terminal:
  `xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber Suite.app"`

First launch asks where to keep the speech models (large files; the
default is fine). The model you pick downloads once, the first time you
transcribe.

## Also new in 1.9.0 (all platforms)

- **Pick the Whisper model straight from the Transcribe tab** — a
  "Model:" row with a "✓ Downloaded" hint, no trip to Advanced settings.
- **See and change the model folder** in Advanced settings ("Change…",
  "Open folder").
- **Clone Your Voice / Text to Voice** — a new, opt-in tab: record or
  load 1–3 short reference clips, type text, and generate it spoken in
  that voice locally (OmniVoice, Apache-2.0; ~2 GB model on first use).
- **Advanced settings is shorter** — engine-specific sections only show
  for the picked engine; noise/VAD options grouped under "Silence &
  noise"; four unused settings removed.

## Fixed

- **Settings, history and downloaded models carry over from the old
  "WhisperProject" name** on every platform (portable, run-from-source,
  macOS, Linux) — previously only the Windows installer did this, so
  already-downloaded models showed as "not downloaded". Mac users of the
  v1.5.0 `WhisperProject` build keep their settings and models.
- **Clearer reason when Hardware Autodetect falls back to CPU** on a
  GPU newer than the bundled CTranslate2 supports (e.g. RTX 50-series,
  #7), instead of blaming missing CUDA libraries.
- **The Live tab could hang on "Loading the speech model…" forever** when
  starting a session failed — the error is now shown.
- **Clone Your Voice** hardening: failures no longer freeze the tab
  silently, Cancel right after setup works, long reference clips are
  trimmed automatically.
- **macOS:** the source installer (`install.command`) works on Intel Macs
  again, and no longer installs an add-on (stable-ts/torch) that made
  every transcription crash there (`OMP: Error #15`).

Full details: [`docs/CHANGELOG.md`](https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/docs/CHANGELOG.md);
how the Mac builds are made and tested:
[`docs/MACOS_BUILD_NOTES.md`](https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/docs/MACOS_BUILD_NOTES.md).
