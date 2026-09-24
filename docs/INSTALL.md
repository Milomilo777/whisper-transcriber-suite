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

v1.0.3 ships two independent installers. Pick the one that fits.

| Method | File | Size | What it is |
|---|---|---|---|
| **Portable** | [`WhisperTranscriberSuite-v1.0.3-Portable.exe`](https://github.com/Milomilo777/whisper_project_direct_download_v2/releases/download/v1.0.3/WhisperTranscriberSuite-v1.0.3-Portable.exe) | 447 MB | A single file. Double-click and it runs. Nothing is installed; no shortcut, no Start Menu entry. Best for USB sticks or one-off use. |
| **Standard** | [`WhisperTranscriberSuite-v1.0.3-Setup-Standard.exe`](https://github.com/Milomilo777/whisper_project_direct_download_v2/releases/download/v1.0.3/WhisperTranscriberSuite-v1.0.3-Setup-Standard.exe) | 349 MB | A real installer — Program Files, Start Menu shortcut, Add/Remove Programs entry. Ships a full Python interpreter on disk so the entire source tree is browsable after install. Best for everyday Windows users and anyone who wants transparency for debugging. |

Both transcribe a real video end-to-end on a clean Windows 10/11 x64 machine.

🔗 Releases page (both assets):
**https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest**

### If you picked Portable

Move `WhisperTranscriberSuite-v1.0.3-Portable.exe` anywhere convenient
(`C:\Apps\`, your Desktop, a USB stick). Double-click to launch.
The first launch unpacks to a temporary folder under `%TEMP%`
(takes about 5–10 seconds). Subsequent launches feel about the
same — every launch re-unpacks.

### If you picked Standard

Double-click the `…-Setup-….exe` file. The installer:

1. Asks for admin rights (Yes).
2. Confirms an install location (`C:\Program Files\WhisperTranscriberSuite\`
   by default — change it if you like).
3. Optionally creates a desktop icon (checkbox on the wizard).
4. Installs (~45 seconds).

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

#### ⚠️ Model download dialog (one time, 3 GB)
On first launch, a "Whisper model required" dialog appears. Click **Download**.

The model is fetched from a CDN (≈3 GB). At average speeds this takes 10–30 minutes.

If the CDN download fails, you can install the model manually (see Troubleshooting below).

Once the download finishes, the app is ready to use.

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

### Download Videos (from YouTube and other sites)

1. **Download Videos** tab
2. Paste the video URL
3. **Browse** next to "Folder" → choose the destination
4. For audio only, change format to mp3/m4a
5. Click **Download**

If "Auto-transcribe after download" is enabled in Advanced, the downloaded file is transcribed automatically.

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
diarization toggle, watched folder, telemetry opt-in — are stored in:

```
%LOCALAPPDATA%\WhisperTranscriberSuite\config.json
```

You can edit it by hand while the app is closed. If the file gets
corrupted (non-UTF8 bytes, malformed JSON), the app moves it aside as
`config.json.corrupt` on next launch and starts with defaults.

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

