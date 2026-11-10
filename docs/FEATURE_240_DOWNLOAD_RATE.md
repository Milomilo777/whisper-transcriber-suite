# Download speed limit (v2.4.0)

## Using the setting

Open **Download Videos → More options → Speed limit (KiB/s)**. Enter a positive whole number and click **Apply** to remember it, or start a download to save and use it. Leave the field blank for unlimited downloads (the default). For example, `256` allows about 256 KiB per second, and `1024` means 1 MiB per second. These are bytes, not bits.

Each new queued download keeps the value it was created with, including its subtitle stage, retries and pause/resume. Changing the setting affects new downloads. A remembered nonzero limit opens More options on startup so the restriction is visible. Invalid text (including units, fractions, zero, negative numbers and extra command arguments) is rejected before saving preferences or adding a task.

The setting passes yt-dlp's `--limit-rate` option as a numeric byte count to audio, audio/video and existing-caption downloads. It is a limit on supported yt-dlp transfers, not a whole-computer network cap: format lookup, updates and model downloads are unaffected. yt-dlp may use ffmpeg for time ranges, live streams or certain protocols; ffmpeg does not implement this rate option. Such transfers can exceed the selected value. A limited time-range submission writes an explicit console warning and labels the queue entry as having no available speed limit. Sites using the custom direct streamer do not use yt-dlp; the Download Videos form asks you to clear a nonzero limit before submitting those links.
