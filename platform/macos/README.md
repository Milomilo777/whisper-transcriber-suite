# Whisper Transcriber Suite on macOS

> Status: **groundwork, not yet validated on a real Mac.** The code is
> cross-platform and the scripts follow current best practice for unsigned
> apps, but no one has run them on macOS yet — treat as beta and report back.

The app is plain Python (Tkinter + faster-whisper + yt-dlp + ffmpeg), so it
runs from source on macOS. It is **unsigned** (no paid Apple Developer
certificate), so macOS Gatekeeper needs a one-time nudge — see below.

## Install

You need Python 3.11+ **with Tk**. The easiest is the official installer
from <https://www.python.org/downloads/macos/> (it bundles a good Tk 8.6).
With Homebrew instead: `brew install python python-tk`.

> **Don't use Apple's built-in `python3` for the GUI.** It links Apple's
> deprecated Tk 8.5, which *imports* fine but renders a blurry/unstable
> window. The installer detects this and warns; pass the python.org one
> explicitly if needed:
> `PYTHON=/usr/local/bin/python3 bash platform/macos/install.command`.
> (The headless CLI doesn't use Tk, so any python3 is fine for it.)

Get the repo **via Terminal** (this matters — see Gatekeeper note), then run
the installer:

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
bash platform/macos/install.command
```

The installer makes a `.venv`, installs the deps from `requirements.txt`
(which now includes `screeninfo` for the Video Tiling multi-monitor wall)
plus `yt-dlp`, gets `ffmpeg`/`ffprobe`/`ffplay` (Homebrew if present, else a
static build into `bin/`), and creates:
- `~/Applications/Whisper Transcriber Suite.app` — a real double-clickable app bundle
  (no lingering Terminal window), built locally so it isn't quarantined;
- `~/.local/bin/whisper-transcribe` — headless CLI for servers. If your
  shell can't find it, add `~/.local/bin` to PATH in **`~/.zshrc`**
  (macOS uses zsh): `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc`.

`ffplay` is materialised into `bin/` alongside `ffmpeg`/`ffprobe` so the
**Video Tiling** video-wall works out of the box (`core.paths.bundled_binary`
drops the `.exe` suffix off Windows, so it resolves `bin/ffplay` on macOS). If
a minimal static build omits it, the in-app tab offers a **Download ffplay**
button instead.

## Features that work on this path

All cross-platform, so they run on macOS the same as on Windows (the engine
code is Tk-free stdlib + REST; the only OS-specific bits — `taskkill` vs
`killpg`, the console-window flag, the Win32 monitor probe — are guarded and
no-op off Windows):

- **LAN / web server** — `gui.py serve --lan` (or the in-app Web/LAN tab)
  serves a browser UI for transcription + downloads over the local network.
- **Cloud STT backends** — Google Gemini (paste an API key) and Google Cloud
  Speech-to-Text v2 (a service-account JSON). Both decode audio with the
  bundled `ffmpeg` and upload over HTTPS.
- **SMTV transcription `.docx`** export (the team's 4-column table template).
- **Format conversion** — File > Convert transcript between
  SRT / VTT / TSV / JSON / TXT (and import `.otr`).

## Gatekeeper (unsigned app) — why and how

macOS tags files **downloaded by a browser** with a `com.apple.quarantine`
flag; Gatekeeper then blocks unsigned apps from opening. Three ways through,
cleanest first:

1. **Get the code without quarantine.** Files fetched via `git clone` or
   `curl` are *not* quarantined, so the launchers just work. This is why the
   install steps use `git clone`.
2. **Strip the flag** (if you did download a zip in a browser):
   ```bash
   xattr -dr com.apple.quarantine /path/to/whisper_app
   ```
   or just run `bash platform/macos/unblock.command`.
3. **Open Anyway.** Try to open the launcher, dismiss the warning, then
   **System Settings → Privacy & Security → scroll down → "Open Anyway"**.
   (On macOS 15 Sequoia the old right-click→Open shortcut was removed; use
   the Settings route.)

Do **not** disable Gatekeeper globally (`spctl --master-disable`) — it's a
system-wide security downgrade and unnecessary here.

## Headless / server use

```bash
whisper-transcribe /path/to/media.mp4 --formats srt json --language en
```

## Notes / what still needs a real Mac

- The static-ffmpeg fallback (evermeet.cx) is **Intel x86_64** and runs
  under Rosetta on Apple Silicon, and now fetches `ffplay` too (for Video
  Tiling). The installer tries Homebrew first, which gives a native arm64
  ffmpeg + ffplay — prefer that on M-series Macs.
- **Two install methods are kept** (pick either):
  1. **This script** (`bash platform/macos/install.command`) — works on a
     private repo, no Homebrew needed.
  2. **Homebrew** — the cleanest channel (no quarantine; native
     python/ffmpeg, and brew's ffmpeg includes `ffplay` so Video Tiling
     works out of the box; `brew upgrade` to update). The ready-to-publish
     formula + instructions live in `platform/macos/homebrew/`. It needs
     the repo **public** (a tap can't reach a private repo), so it's staged
     for when/if that happens.
- The embedded VLC preview needs VLC at `/Applications/VLC.app` (the app
  now looks there); without it the transcript viewer is read-only.
- Apple-silicon vs Intel: faster-whisper/ctranslate2 ship arm64 + x86_64
  wheels, so both should work, but neither has been run here yet.
- A signed/notarized `.app` would remove the Gatekeeper step entirely but
  needs a paid Apple Developer account — out of scope for now.

## References (Gatekeeper / unsigned distribution)

- Removing the quarantine attribute (`xattr -dr com.apple.quarantine`) and
  the "Open Anyway" flow — standard, widely documented.
- Distributing via Homebrew, or fetching with `curl`/`git` (no quarantine),
  is the common workaround for unsigned OSS apps.
