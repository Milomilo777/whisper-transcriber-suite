# Make subtitled video (link to a video with burned-in subtitles)

One choice on the **Download Videos** tab turns a link into a video file with the subtitles drawn
into the picture, ready to share or play anywhere.

## How to use it

1. Paste a link (any site yt-dlp supports, or a Supreme Master TV page) and wait for the formats.
2. Keep **Audio and video** as the mode (an audio-only download has no picture to draw on).
3. Tick **Make subtitled video** and click **Download**.

The download row then goes through three stages, with one percent that only rises:

| Row status | Stage | Share of the percent |
|---|---|---|
| running | the download | 0-40 |
| transcribing | Whisper, with the Transcribe tab's settings (model, language, translation) | 40-85 |
| burning | ffmpeg draws the SRT into a new video | 85-100 |

The result is `<title>-subbed.mp4` next to the download. If that name is taken (an earlier run,
or another job of the same title still burning), the new file is `<title>-subbed (2).mp4`; an
existing file is never replaced. The name is reserved with an empty file the moment the burn
starts, and that placeholder is removed again if no video is made.

## What is kept

- The downloaded video and every transcript file are always kept, whatever happens later.
- **Cancel** stops the stage that is running. During the burn it stops ffmpeg and removes only its
  half-written temp file (`.burn-*.mp4`).
- A failed transcription or burn ends the row as `error` with the reason in the log; no partial
  video is left behind. A download that turns out to have no picture (an audio-only source) ends
  as `error` right after the download, before any transcription. History records the downloaded file and, after a successful burn, the
  subtitled video too.

## Details

- The transcription always runs, even with **Transcribe after download** off, and it skips the
  "use the site's captions instead" offer: the burn needs Whisper's timings. For a Supreme Master
  TV link the article text is not used (it has no timings); Whisper transcribes the video.
- The SRT is always written for this job, even when SRT is not among the chosen output formats.
- The burn uses the SRT the transcription really wrote (for example `name (1).srt` on a re-run),
  never a guessed name.
- Style: the classic look of the existing **Burn subtitles into video** action. On Windows,
  Persian and Arabic lines use Tahoma and Chinese uses Microsoft YaHei, and right-to-left lines
  keep their final punctuation on the correct side.
- Text is drawn exactly as transcribed: braces, backslashes (`\N`) and HTML-like tags (`<i>`) in
  the transcript are escaped, so libass does not read them as style commands.
- The output is H.264 in 8-bit 4:2:0 with the MP4 index at the front, so phones, TVs and browsers
  play it. The audio is copied when it is AAC, MP3, AC-3, E-AC-3 or ALAC, and re-encoded to AAC
  otherwise (Opus, Vorbis, FLAC and PCM in MP4 play in few players).
- When ffprobe cannot read the video's length, the burn shows no percent (the row stays at 85%
  with a moving bar) until it ends.
- The re-encode takes about 2x the video's length on an 8-thread CPU. The time limit is three
  times the video's length, at least one hour.
- The download queue moves on to the next link while an earlier one transcribes or burns.

Not in this version: translation into languages other than English, other styles (big text, word
highlight), a vertical 9:16 reframe, GPU encoding and batch presets.

Code: `app/services/subbed_video.py` (the stages), `core/burn_subs.py` (ffmpeg, progress, cancel).
