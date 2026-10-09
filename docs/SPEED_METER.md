# Speed and time left

While a file is transcribed, the Queue tab's **Speed and time left** column shows how fast the
engine is going and roughly how long is left, for example `about 4.8x, 6 min left`. When the file
is done, the column keeps the overall speed (`4.8x`) and the Transcribe tab's result card says,
for example:

> 42 min of audio transcribed in 3 min 40 s (11.5x) with small on CPU

`11.5x` means the engine got through 11.5 seconds of audio for every second it worked. It depends
on the model, the computer and the audio, so it is a measurement of this run, not a promise.
Below 1x the engine is slower than the recording plays, and the card says so. The time on the
card is transcribing time only, so it can be shorter than the queue's Elapsed column, which also
counts loading, speaker labels and writing the files. A run with under a second of work gets no
speed line.

## How it is measured

The numbers come from `core/speed_meter.py` (pure, tested with a fake clock in
`tests/core/test_speed_meter.py` and `tests/core/test_speed_meter_wiring.py`).

- **Audio done** is the end time of the last segment the engine produced (never the progress
  percent: speaker labelling reuses the top of the percent range). A segment that ends earlier
  than one already seen, as after a repetition-loop restart, never moves it back.
- **Time worked** is a monotonic clock that starts just before the engine call (after any
  time-range slice, vocal separation or denoise) and stops when the last segment arrives, so
  speaker labelling, alignment and writing the files do not count. The engine's own voice
  detection and language detection do count. While a job is paused, the clock is stopped.
- **Live speed** is the average since the first segment: audio done after it divided by the work
  time after it, shown as "about". The start-up work before the first segment (voice and
  language detection) is left out, because it would make every early estimate too slow; the final
  speed counts it. A 60-second sliding window was tried first and dropped: decode speed depends on
  the audio content, and on five recorded runs (tiny, small, large-v3-turbo) the window's swings
  made the time left worse (mean error 56 % against 35 %, worst 293 % against 147 %).
- **Time left** is the audio still ahead (up to the end of the file or of the selected time range)
  divided by the live speed, shown in whole minutes. It appears only after 30 seconds of audio and
  3 seconds of work (`measuring speed...` before that) and never goes below zero. After that, each
  update counts the previous estimate down by the work time since then and moves it toward the
  new estimate by the share `1 - exp(-seconds since then / 20)`: segments that arrive together
  cannot move it, and after a long gap it follows the new speed. It turns into `audio done` when the last segment is in (speaker
  labelling or writing may still be running). A live speed under 0.1x shows as `very slow`.
- **Final speed** is the length of the whole file or time range, as probed before the run, divided
  by the time worked. A file whose speech ends early still counts its silent end, because the
  engine got through it.
- **Resumed jobs** count only the part transcribed after the resume; the result card says so. The
  checkpoint stores no timing from the first run.
- **Other engines** (whisper.cpp, cloud engines and the like) hand back all segments at once, so
  they show no live speed or time left (the column says `shown when done`), only the final speed.
  Their clock stops while the engine reports the job paused.

The hardware wizard's benchmark (a silent clip with voice detection off) is never used for any of
these numbers.

## Where the numbers go

- Worker protocol (`core/worker.py`): `progress` events carry `speed_x` and `eta_s` once there is
  enough data, and `speed_live: false` from engines without a live speed; `done` carries `speed_x`, `speed_audio_s`, `speed_seconds`, `speed_resumed`,
  `model` and `device`. All are additive; an older parent ignores them.
- History (`history.db`, table `transcriptions`): `speed_x` (0 = not measured) and `device`,
  added by an idempotent migration; `model` is updated to the model the worker reports.
