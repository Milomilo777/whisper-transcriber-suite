# Installation Guide — Whisper Transcriber Suite

This guide is for someone who doesn't know Python or programming and just wants to install and use the application.

---

## What you need

- **Windows 10 or 11** (64-bit)
- At least **8 GB RAM** (CPU); or an **NVIDIA GPU with CUDA** for 10× speedup
- About **5 GB free disk space** (1.5 GB app + 3 GB model + working space)
- Internet connection once for the model download (offline afterwards)

---

## Install — pick one of two methods

Both files are on the
**[releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**
and contain the same app (`X.Y.Z` is the version number).

| Method | File | What it is |
|---|---|---|
| **Installer** | `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | A normal installer: Program Files, Start Menu shortcut, Add/Remove Programs entry, upgrades in place. Best for most people. |
| **Portable** | `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Unzip anywhere and run. Nothing is installed and no admin rights are needed. |

### On a Mac

Download `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` for Apple silicon
(macOS 14 or newer) or `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` for
Intel (macOS 10.15 or newer), open it and drag the app into Applications.
The app is not notarized by Apple, so the first launch is blocked with
"Apple cannot check it for malicious software". To open it anyway:

- macOS 14 and older: right-click the app → **Open** → **Open**.
- macOS 15 and newer: **System Settings → Privacy & Security** → scroll
  down → **Open Anyway**.
- Or in Terminal:
  `xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber Suite.app"`

macOS remembers the choice. Running from source on a Mac:
[platform/macos/README.md](../platform/macos/README.md).

### If you picked Portable

Unzip the archive anywhere convenient (`C:\Apps\`, your Desktop, a USB
stick) and double-click **Run Whisper Transcriber Suite.bat** inside the
folder.

### If you picked the Installer

Double-click the `…-Installer-Windows-….exe` file. The installer:

1. Asks for admin rights (Yes).
2. Confirms an install location (`C:\Program Files\WhisperTranscriberSuite\`
   by default — change it if you like).
3. Optionally creates a desktop icon and installs the Clone Your Voice /
   Text to Voice feature (both are checkboxes on the wizard).
4. Installs.

After install: launch from the Start Menu under **Whisper Transcriber Suite**,
or from the desktop icon if you ticked the box. Uninstall from
**Settings → Apps → Whisper Transcriber Suite → Uninstall** or from the
folder's `unins000.exe`.

### First launch — common to both methods

#### ⚠️ SmartScreen warning
Windows may show:
> "Windows protected your PC — Microsoft Defender SmartScreen prevented an unrecognized app from starting"

This is **normal** because the binary is not code-signed. To continue:
1. Click **More info**
2. The **Run anyway** button appears — click it

#### Quick start (one time)
On the first launch a **Quick start** window asks three things: the main
language you will transcribe, **Fast** or **Best quality**, and the folder
for downloaded videos and audio (transcripts are always saved next to the
file they come from). Each choice shows the model it picks, its download
size and a rough time per minute of audio on your computer.
Click **Finish**, or **Skip** to keep the defaults (the Large v3 model,
about 3 GB). Either way the window does not appear again; every choice can
be changed later (the model on the Transcribe tab, the folder on the
Download tab).

#### Model download (one time)
The model downloads the first time you transcribe: a "Whisper model
required" dialog appears with its size. Click **Download**. Small is about
500 MB; Large v3 is about 3 GB and takes 10–30 minutes at average speeds.

If the CDN download fails, you can install the model manually (see Troubleshooting below).

Once the download finishes, the app is ready to use.

#### Where the models live
Models are stored in a per-user cache that is always writable,
`%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\models`, never the Program
Files install folder. **Finish** in the quick start window uses it; after
**Skip** the app asks where to store the model files (an external drive or
a network share works too). The choice is saved as `hub_folder` in
`config.json`, and **Advanced settings → Model folder → Change...** moves it
later. To start over, open a Command Prompt in the app's folder
(the install folder, or the unzipped Portable folder) and launch it once
with `--safe-mode`:

```cmd
python\pythonw.exe gui.py --safe-mode
```

That renames your `config.json` to a timestamped backup and shows the
first-run windows again with the defaults.

### Updating to a newer version

No uninstall is needed: run the newer
`WhisperTranscriberSuite-Installer-Windows-….exe` and it upgrades the
existing install, keeping your shortcut and settings. For the Portable
build, replace the old folder with the new one. **Help → Check for
updates…** checks on demand; the automatic daily check only tells you when
a newer version exists and never downloads anything by itself. It shows a
quiet bar under the menu: **What's new**, **Download** (opens the file for
your kind of install in the browser; close the app before you run it),
**Later** (again in 3, 7, then 14 days, then about once a month) and
**Skip this version** (silent until a newer version). The bar never appears
while a transcription or download runs, and a major new version (for example
3.0) is announced as such, with up to five highlights under **What's new**.
Turn the check off under **Advanced → App behaviour**.

---

## Usage

### Transcribe (audio/video → subtitles)

1. Open the **Transcribe** tab
2. **Browse** → pick an audio or video file (mp3, mp4, wav, m4a, mkv, …)
3. Click **Transcribe**
4. Watch the **Transcription Queue** tab for progress
5. When done, two files are written next to your input:
   - `<filename>.srt` — subtitle file
   - `<filename>.json` — segments with precise timestamps

Keyboard: `Ctrl+O` browse · `Ctrl+Enter` transcribe · `Esc` cancel ·
`Ctrl+Q` exit.

### Download Videos (from YouTube and other sites)

1. **Download Videos** tab
2. Paste the video URL
3. **Browse** next to "Folder" → choose the destination
4. For audio only, change format to mp3/m4a
5. Click **Download**

If "Auto-transcribe after download" is enabled in Advanced, the downloaded file is transcribed automatically.

- **YouTube** needs a small JavaScript helper (Deno) for yt-dlp. When a
  YouTube link is pasted and it is missing, an **Install YouTube helper**
  button appears next to the status line: one click downloads it (~42 MB,
  checksum-verified, no admin rights) into the app's cache.
- **Instagram / Facebook / private or age-restricted videos**: pick the
  browser you are logged in with under **Log-in cookies** (next to the URL).
  On Windows, close that browser completely if reading its cookies fails.

### oTranscribe round-trip (text editing)

1. After a successful transcription, go to **Transcription Queue**
2. **Right-click** the row → **Export → oTranscribe (.otr)**
3. Open the `.otr` file at https://otranscribe.com, edit, export
4. Back to the **Transcribe** tab → **Import .otr → SRT...**

---

## Troubleshooting

### "MSVCP140.dll is missing" or a similar DLL error

Install the Visual C++ Redistributable from Microsoft:
🔗 https://aka.ms/vs/17/release/vc_redist.x64.exe

This is free and usually already installed on Windows 10/11.

### The exe won't run — antivirus removes it

PyInstaller-built binaries are sometimes flagged as tampered by antivirus engines. Fix:
1. Open Windows Security → Virus & threat protection → Exclusions
2. Add the `WhisperTranscriberSuite\` folder as an exclusion
3. Re-extract the ZIP

### "Model folder missing" or "Existing model failed to load"

Re-trigger the model-download dialog from the app. If it still fails, install the model manually:

```powershell
pip install huggingface_hub
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3', local_dir=r'C:\Users\YOUR_USER\AppData\Local\WhisperTranscriberSuite\Cache\models\models--Systran--faster-whisper-large-v3')"
```

(Replace `YOUR_USER` with your Windows username.)

This needs **Python**, installable from https://python.org (tick "Add to PATH" during install).

### Transcription is very slow

- The default model is `large-v3` (large). On CPU with int8 it takes about 2–3× the audio length.
- If you have an NVIDIA GPU: open Advanced → **Re-detect hardware…**. It picks CUDA when it can, and otherwise says why not — usually NVIDIA's cuBLAS library is missing (the graphics driver does not include it); the **Install GPU support** button installs it (~550 MB, one time). Speedup is 10×–20×. **Copy diagnostics** there gives a report to attach to a GitHub issue if it still fails.
- Or use a smaller model (edit `config.json` at `%LOCALAPPDATA%\WhisperTranscriberSuite\config.json` by hand).

### The model download stops or fails

- Start the transcription again: the download continues where it stopped (the zip mirror and
  huggingface.co both resume), it does not start from zero.
- A model folder without `model.bin` is an unfinished download, not a model; the app offers to
  download it again.
- The error box says why it failed. "Not enough free disk space" names the space needed: free it
  or choose another folder in **Advanced settings → Model folder**. "Could not reach huggingface.co"
  means the computer is offline or the site is blocked on that network (check the proxy or VPN).

### Use an existing Whisper model from elsewhere

If you've already downloaded the model on another machine or want to
keep it on a network share / portable drive, edit the **`model_path`**
key in:

```
%LOCALAPPDATA%\WhisperTranscriberSuite\config.json
```

Set it to the absolute path of the
`models--Systran--faster-whisper-large-v3` folder (the folder that
contains `model.bin`, `config.json`, `tokenizer.json`, …). Restart the
app. If the path is missing or its drive isn't mounted at launch, the
app silently falls back to the cache and re-downloads on demand.

### Where the configuration file lives

All app settings — model path, output formats, hotwords, theme,
diarization toggle, watched folder, usage-statistics switch — are stored in:

```
%LOCALAPPDATA%\WhisperTranscriberSuite\config.json
```

You can edit it by hand while the app is closed. If the file gets
corrupted (non-UTF8 bytes, malformed JSON), the app moves it aside as
`config.json.corrupt` on next launch and starts with defaults.

### YouTube downloads fail ("No supported JavaScript runtime", 403 Forbidden)

1. Click **Install YouTube helper** in the Download Videos tab if it is shown.
2. If the error then says yt-dlp is too old, or downloads stop with
   `HTTP Error 403: Forbidden`, click **Update it** on the bar above the tabs
   ("The video downloader may be out of date"). It updates a copy of yt-dlp in
   your user folder, so no administrator rights are needed, and never runs
   while a download runs. **Advanced → Downloads (yt-dlp)** can keep it up to
   date automatically instead, or turn the offer off. The macOS app cannot
   update its yt-dlp by itself; there, installing the newest app version
   updates it.

### The app crashes

Log path: `%LOCALAPPDATA%\WhisperTranscriberSuite\Logs\app.log`

Paste that file into a GitHub issue along with a short description of what you were doing.

---

## Build from source (for developers)

If you want to build it yourself from source:

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite
cd whisper-transcriber-suite

REM Prerequisites
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller

REM Download ffmpeg / ffprobe / yt-dlp into bin/
REM Files from:
REM   https://www.gyan.dev/ffmpeg/builds/  (release essentials)
REM   https://github.com/yt-dlp/yt-dlp/releases/latest

REM Build
build.bat clean
```

Output: `dist\WhisperTranscriberSuite\WhisperTranscriberSuite.exe`

More detail: [docs/BUILD.md](BUILD.md)

