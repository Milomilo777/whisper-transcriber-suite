# Whisper Transcriber Suite — Install & Use Guide

A plain-English, step-by-step guide for new users. It doubles as the
outline for the YouTube tutorial (see `VIDEO_SCRIPT.md` in this folder).

> Whisper Transcriber Suite turns audio/video into text and subtitles — **offline**,
> on your own computer. No account, no API key, nothing uploaded.

---

## 1. Install

### Windows (easiest)

1. Open the **Releases** page and download the latest
   **`WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe`**.
2. Run it. If Windows SmartScreen warns ("unknown publisher"), click
   **More info → Run anyway** (the app is unsigned but safe).
3. Pick the install folder, finish, and launch **Whisper Transcriber Suite** from the
   Start menu / desktop shortcut.

Prefer no install? Download **`...-Portable.zip`**, extract it anywhere, and
double-click **`Run Whisper Transcriber Suite.bat`**.

### macOS

See **`platform/macos/README.md`**. Shortest path: `git clone` the repo, then
`bash platform/macos/install.command`. (Unsigned app — the README shows the
one-time "Open Anyway" step.)

### Linux

See **`platform/linux/README.md`**: `bash platform/linux/install.sh` gives a
desktop launcher plus a headless `whisper-transcribe` command for servers.

### First launch — one-time model download

The first time you transcribe, the app downloads the Whisper speech model
(**~3 GB, once**). You'll see a "Downloading model…" progress dialog. After
that it's fully offline.

---

## 2. Transcribe a file (the main job)

1. Open the **Transcribe** tab.
2. Add audio/video either way:
   - **Drag-and-drop** files onto the window, or
   - click **Browse…** (Ctrl+O) and select one or several files.
3. (Optional) set a **language** — leave it on **Auto** to auto-detect.
4. (Optional) set a **time range** (Start / End) to transcribe only part of
   a long file.
5. Click **Transcribe**.
6. Watch progress in the **Transcription Queue** tab. When done, the output
   files appear **next to the original file**, and a "Last result" card
   shows them with an **Open** button.

**Output formats** (srt, vtt, txt, json, docx, pdf, …) are chosen in
**Advanced settings**. Default is `srt` + `json`.

---

## 3. Download a video and transcribe it

1. Open the **Download Videos** tab.
2. Paste a video URL (YouTube, X/Twitter, and many more sites).
3. (Optional) drag the **Start/End** sliders for a clip.
4. Tick **Auto-transcribe after download** if you want subtitles
   automatically.
5. Click **Download**. The row shows progress, then "transcribing" if
   auto-transcribe is on.

If a site needs a login, the queue shows the real error plus a hint to enable
**"Cookies from browser"** in Advanced settings.

---

## 4. Video Tiling (optional)

The **Video Tiling** tab plays one live stream as a full-screen N×N grid (a
"video wall"). Paste a stream URL, pick the grid size, and click **Start
tiling**. (This feature needs **ffplay**; if it's missing the tab tells you
how to add it.)

---

## 5. View & edit a transcript

After a transcription, open the result to review it in the built-in viewer:
click a segment to jump, edit text, remove filler words, and (if VLC is
installed) play the media with the words highlighting as it plays.

---

## 6. Tips

- **Speed:** the default model is the most accurate but heaviest. For faster
  results pick a smaller/faster model in **Advanced settings**.
- **Where are my files?** Right next to the input media, same name, new
  extension (e.g. `talk.mp4` → `talk.srt`).
- **Advanced settings** also hold: model + backend choice, speaker
  diarization, word timestamps, and the output formats.
- Optional extras (word-timestamp alignment, the openai-whisper backend)
  download what they need the first time you turn them on.
