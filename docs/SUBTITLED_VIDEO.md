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

The result is `<title>-subbed.mp4` next to the download. If that name is taken (an earlier run),
the new file is `<title>-subbed (2).mp4`; an existing file is never replaced.

## What is kept

- The downloaded video and every transcript file are always kept, whatever happens later.
- **Cancel** stops the stage that is running. During the burn it stops ffmpeg and removes only its
  half-written temp file (`.burn-*.mp4`).
- A failed transcription or burn ends the row as `error` with the reason in the log; no partial
  video is left behind. History records the downloaded file and, after a successful burn, the
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
- The re-encode takes about 2x the video's length on an 8-thread CPU. The time limit is three
  times the video's length, at least one hour.
- The download queue moves on to the next link while an earlier one transcribes or burns.

Not in this version: translation into languages other than English, other styles (big text, word
highlight), a vertical 9:16 reframe, GPU encoding and batch presets.

Code: `app/services/subbed_video.py` (the stages), `core/burn_subs.py` (ffmpeg, progress, cancel).
