# Whisper Transcriber Suite v1.9.3

NVIDIA GPUs finally work, YouTube downloads work out of the box again, and a
long list of fixes for Windows, macOS and Linux. (There is no v1.9.2.)

## Download

| File | For | Size |
|---|---|---|
| [**WhisperTranscriberSuite-Installer-Windows-v1.9.3.exe**](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-Installer-Windows-v1.9.3.exe) | **Windows — most people.** Normal installer; upgrades an older version in place. | 234 MB |
| [**WhisperTranscriberSuite-Portable-Windows-v1.9.3.zip**](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-Portable-Windows-v1.9.3.zip) | Windows — unzip and run, no installation or admin rights. | 354 MB |
| [WhisperTranscriberSuite-v1.9.3-macOS-arm64.dmg](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-v1.9.3-macOS-arm64.dmg) | Mac with Apple silicon (M1/M2/M3/M4…), macOS 14+ (on macOS 11–13 use the Intel file; it runs through Rosetta) | 246 MB |
| [WhisperTranscriberSuite-v1.9.3-macOS-x64.dmg](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-v1.9.3-macOS-x64.dmg) | Intel Mac, macOS 10.15+ | 306 MB |

> ⭐ **Enjoying it?** Click **Star** at the top of this page — it's free, takes one click, and it's how other people find the project.

Mac install steps — including the one-line Terminal install — are below.

**Linux** — one line in a terminal (Debian / Ubuntu; installs from source into
`~/whisper-transcriber-suite`, no admin rights needed after the first `apt`):

```bash
sudo apt install -y git python3-venv python3-tk && git clone --depth 1 https://github.com/Milomilo777/whisper-transcriber-suite.git ~/whisper-transcriber-suite && bash ~/whisper-transcriber-suite/platform/linux/install.sh && ~/.local/bin/whisper-transcriber-suite
```

Fedora: replace the first part with `sudo dnf install -y git python3-tkinter`;
Arch: `sudo pacman -S --needed git tk`. Update later with
`bash ~/whisper-transcriber-suite/platform/linux/update.sh`. Details:
[platform/linux/README.md](https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/platform/linux/README.md).

## Highlights

- **NVIDIA GPUs are used again (#7).** Every version before this one checked
  for CUDA with a function CTranslate2 does not have, so every PC ran on the
  CPU. If your GPU still can't be used, *Advanced → Re-detect hardware* now
  says why and offers **Install GPU support** (NVIDIA cuBLAS, ~550 MB) and
  **Copy diagnostics** for a bug report. A GPU that fails on first use falls
  back to the CPU instead of failing the transcription.
- **YouTube works without extra setup (#8).** yt-dlp now gets the JavaScript
  runtime YouTube requires (Deno). The Windows and Mac downloads include it; on
  Linux the Download tab offers a one-click, checksum-verified **Install YouTube
  helper**.
- **"Log-in cookies" in the Download tab** for sites that need you to be
  logged in (Instagram, Facebook, …). On Windows, Chrome/Edge/Brave cookies
  can't be read by other programs — use Firefox for those sites.
- **"Best for this PC…"** next to the model picker suggests the fastest and
  the most accurate model for your hardware.
- **Simpler Settings and laptop-friendly window**: cloud setups folded away,
  fine-tuning sliders behind "Fine-tune", tall tabs scroll on small screens.

## Fixes

- A link copied from inside a playlist no longer downloads the whole playlist.
- A video with no sound says so, instead of "tuple index out of range".
- Changing the model during a transcription asks first.
- "Engine: Checking…" can no longer stay forever.
- The first-download prompt shows the selected model's real size.
- CLI: `transcribe --model tiny|small|…` downloads a missing model instead of
  failing with "model not loaded".
- Full list: [CHANGELOG](https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/docs/CHANGELOG.md#193--2026-09-27).

## Installing on a Mac (the app is free but not signed by Apple)

**Easiest — one line in Terminal, no security warning at all** (files
downloaded by `curl` are not quarantined). It picks the right file for your
Mac; an Apple-silicon Mac older than macOS 14 gets the Intel version, which
runs through Rosetta:

```bash
A=x64; [ "$(uname -m)" = arm64 ] && [ "$(sw_vers -productVersion | cut -d. -f1)" -ge 14 ] && A=arm64; curl -fL -o /tmp/wts.dmg "https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-v1.9.3-macOS-$A.dmg" && hdiutil attach -nobrowse -quiet -mountpoint /tmp/wts-dmg /tmp/wts.dmg && cp -R "/tmp/wts-dmg/Whisper Transcriber Suite.app" /Applications/ && hdiutil detach -quiet /tmp/wts-dmg && rm /tmp/wts.dmg && open "/Applications/Whisper Transcriber Suite.app"
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

**Mac notes for this version:** YouTube works out of the box (the Deno
helper is inside the app). "Log-in cookies" works with Safari and Firefox.
Word-timing refinement (stable-ts) is not part of the Mac app — it needs a
source install ([platform/macos/README.md](https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/platform/macos/README.md)).

## Help make it better

Found a bug, something confusing, or have an idea?
[Open an issue](https://github.com/Milomilo777/whisper-transcriber-suite/issues/new/choose)
or start a [Discussion](https://github.com/Milomilo777/whisper-transcriber-suite/discussions) —
a two-line report with a screenshot helps a lot. And if the app saved you some
time, a [⭐ on GitHub](https://github.com/Milomilo777/whisper-transcriber-suite)
is how other people find it.
