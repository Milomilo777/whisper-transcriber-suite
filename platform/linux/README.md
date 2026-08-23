# Whisper Transcriber Suite on Linux

The app is plain Python (Tkinter UI + faster-whisper + yt-dlp + ffmpeg),
so it runs on Linux from source. These scripts set up a self-contained
virtualenv next to the repo and add launchers — updating later is just a
`git pull` + `update.sh`, no reinstall.

## Install

Clone the repo, then:

```bash
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
bash platform/linux/install.sh
```

If `~/.local/bin` isn't on your `PATH`, add it:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

The installer:
- creates `.venv/` and installs `requirements.txt` + `yt-dlp`;
- fetches a static `ffmpeg`/`ffprobe` into `bin/` when the system has none;
- installs `whisper-transcriber-suite` (GUI) and `whisper-transcribe` (headless CLI)
  plus a desktop entry.

The GUI needs **python3-tk** and a display:
`sudo apt install python3-tk` (Debian/Ubuntu) · `sudo dnf install
python3-tkinter` (Fedora) · `sudo pacman -S tk` (Arch).

## Desktop use

```bash
whisper-transcriber-suite
```

The first transcription downloads the Whisper model (~3 GB, one time) into
`~/.cache/WhisperTranscriberSuite`. The optional word-alignment / openai-whisper
backends download PyTorch on first use, exactly like on Windows.

## Headless / server use (no display)

The CLI mode transcribes without a UI — ideal for a server:

```bash
whisper-transcribe /path/to/media.mp4 --formats srt json --language en
# or directly:
.venv/bin/python gui.py transcribe /path/to/media.mp4 -f srt vtt txt
```

Note: Whisper is CPU-heavy. On a shared web server, `nice`/`cpulimit` it,
or run a smaller/faster model (set it once via the desktop app's Advanced
dialog, or edit `~/.config/WhisperTranscriberSuite/config.json`).

### Optional: a systemd one-shot for a watched job

```ini
# ~/.config/systemd/user/whisper-transcribe@.service
[Unit]
Description=Whisper transcribe %i
[Service]
Type=oneshot
ExecStart=%h/.local/bin/whisper-transcribe %i --formats srt json
```
`systemctl --user start whisper-transcribe@/srv/media/clip.mp4.service`

## Update

```bash
bash platform/linux/update.sh     # git pull + refresh the venv
```

## Uninstall

```bash
bash platform/linux/uninstall.sh  # removes launchers + .venv; keeps your data
```
