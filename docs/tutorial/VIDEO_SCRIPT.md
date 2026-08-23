# YouTube tutorial — screencast script

A ready-to-record script for a ~6–8 minute "Install & Use Whisper Transcriber Suite"
video. Record your screen (OBS / built-in recorder) following the SHOW
column; read the SAY column as narration. Keep it relaxed — pause while
things download/process and cut those waits in editing.

Tip: record at 1080p, hide personal info, and zoom in on small UI bits.

---

## 0. Intro  (~20s)

- **SHOW:** app open on the Transcribe tab; title bar shows the version.
- **SAY:** "This is Whisper Transcriber Suite — it turns audio and video into text and
  subtitles, completely offline on your own PC. No account, no upload. I'll
  show you how to install it and how to use it."

## 1. Install (Windows)  (~60s)

- **SHOW:** the GitHub Releases page → click `…-Setup-Standard.exe` → run it
  → if SmartScreen appears, **More info → Run anyway** → installer wizard →
  finish → launch from the desktop shortcut.
- **SAY:** "Grab the Setup file from the Releases page and run it. Windows
  may warn that the publisher is unknown — that's normal for a free app like
  this; click More info, then Run anyway. Finish the wizard and open it."
- **TEXT overlay:** "Portable option: download the ZIP, extract, run 'Run
  Whisper Transcriber Suite.bat'."

## 2. First launch — model download  (~30s)

- **SHOW:** click Transcribe the first time → the "Downloading model…"
  dialog → let it finish (cut the wait).
- **SAY:** "The first time only, it downloads the speech model — about three
  gigabytes. This happens once; after that everything runs offline."

## 3. Transcribe a file  (~90s)

- **SHOW:** drag a video onto the window (or Browse) → leave Language on
  **Auto** → click **Transcribe** → switch to **Transcription Queue** to show
  progress → back to Transcribe, the **Last result** card with **Open**.
- **SAY:** "To transcribe, just drag a file in — or use Browse. Leave the
  language on Auto to detect it. Click Transcribe and watch the queue. When
  it's done, the subtitle and text files are saved right next to your video,
  and this card lets you open them."
- **SHOW:** open the produced `.srt` in Notepad to prove it worked.

## 4. Output formats & a time range  (~40s)

- **SHOW:** Advanced settings → output formats (tick `docx`/`txt`) → close →
  the Transcribe tab Start/End fields → set e.g. 0:00:00 to 0:01:00.
- **SAY:** "In Advanced settings you choose the output formats — SRT, text,
  Word, PDF and more. And you can transcribe just part of a long file with
  the Start and End time fields."

## 5. Download a video + auto-transcribe  (~60s)

- **SHOW:** Download Videos tab → paste a YouTube URL → tick **Auto-
  transcribe after download** → Download → the row goes to "transcribing".
- **SAY:** "You can also paste a video link — YouTube, X, and lots of other
  sites. Tick auto-transcribe, hit Download, and it fetches the video and
  subtitles it automatically."

## 6. (Optional) Video Tiling  (~30s)

- **SHOW:** Video Tiling tab → paste a live-stream URL → set grid to 3 →
  Start tiling → the full-screen grid → Stop.
- **SAY:** "There's also a Video Tiling tab that fills the screen with a grid
  of one live stream — handy as a video wall."

## 7. View / edit the transcript  (~40s)

- **SHOW:** open the transcript viewer → click a segment → edit a word →
  (if VLC installed) play with word highlighting.
- **SAY:** "You can review and tidy the transcript right in the app — click a
  line to jump, fix words, and play along with the media."

## 8. Outro  (~20s)

- **SAY:** "That's it — install, transcribe, download, done. Everything stays
  on your machine. Links and the written guide are in the description."
- **TEXT overlay / description:** link to the Releases page + a link to
  `docs/tutorial/INSTALL_AND_USE.md`.

---

### Shot checklist
- [ ] Releases page + Setup download + SmartScreen "Run anyway"
- [ ] First-run model download dialog
- [ ] Drag-drop + Transcribe + queue progress + Last-result card
- [ ] Open the resulting .srt/.txt
- [ ] Advanced settings (formats) + time range
- [ ] Download tab: paste URL + auto-transcribe
- [ ] (optional) Video Tiling grid
- [ ] Transcript viewer edit/playback
