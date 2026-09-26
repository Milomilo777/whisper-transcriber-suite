# Whisper Transcriber Suite v1.9.3

NVIDIA GPUs finally work, YouTube downloads work out of the box again, and a
long list of fixes for Windows, macOS and Linux. (There is no v1.9.2.)

## Download

| File | For | Size |
|---|---|---|
| [**WhisperTranscriberSuite-Installer-Windows-v1.9.3.exe**](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-Installer-Windows-v1.9.3.exe) | **Windows — most people.** Normal installer; upgrades an older version in place. | 234 MB |
| [**WhisperTranscriberSuite-Portable-Windows-v1.9.3.zip**](https://github.com/Milomilo777/whisper-transcriber-suite/releases/download/v1.9.3/WhisperTranscriberSuite-Portable-Windows-v1.9.3.zip) | Windows — unzip and run, no installation or admin rights. | 354 MB |
<!-- MAC_ROWS -->

<!-- MAC_PENDING -->
**macOS:** the Mac builds are being tested on a real Mac and will be added to
this page shortly.
<!-- /MAC_PENDING -->

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
  runtime YouTube requires (Deno). The Windows downloads include it; elsewhere
  the Download tab offers a one-click, checksum-verified **Install YouTube
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

<!-- MAC_INSTALL -->

## Help make it better

Found a bug, something confusing, or have an idea?
[Open an issue](https://github.com/Milomilo777/whisper-transcriber-suite/issues/new/choose)
or start a [Discussion](https://github.com/Milomilo777/whisper-transcriber-suite/discussions) —
a two-line report with a screenshot helps a lot. And if the app saved you some
time, a [⭐ on GitHub](https://github.com/Milomilo777/whisper-transcriber-suite/stargazers)
is how other people find it.

## Checksums (SHA-256)

```
d30510965bce72096cff402ca7d6407ab4580763528ff0b8b84b734a1fde5690  WhisperTranscriberSuite-Installer-Windows-v1.9.3.exe
9f41e63864c64bb13aa401ccca5e92765460b85b343b2198b1b8eeeba6765dcf  WhisperTranscriberSuite-Portable-Windows-v1.9.3.zip
```
