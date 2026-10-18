# BRIEF for Codex: Whisper Lite (Android companion) audio module

You work in a git worktree of the Whisper Transcriber Suite repo, on branch `codex/whisper-lite-audio`.
Work ONLY inside `experiments/whisper-lite-android/` (plus this BRIEF.md and REVIEW.md at the worktree root).

## Hard rules
- Use relative paths only. Never read or write anything outside this worktree: no home folder, no other
  directories, no environment dumps. A guard stops the run on any outside path.
- No secrets exist here; never create or ask for any.
- Git: only `git status`, `git diff`, `git add`, `git commit`, `git log` on this branch. Never push, never
  reset/checkout/switch/stash/clean, never edit remotes or config.
- Windows PowerShell runs your commands. For prose files avoid single-quoted here-strings; after two failed
  patch attempts on a file, write it with a short script instead.
- Commit in small, coherent commits with imperative subjects (end each message with the line
  `Assisted-by: GPT-6.1 Sol (OpenAI)`).

## Context
`experiments/whisper-lite-android/` holds the first pieces of an offline Android transcription app (Kotlin,
minSdk 26, targetSdk 35, no third-party libraries, no GPL code):
- `audio/`: pure Kotlin JVM module (Maven, Kotlin 2.0.21, JUnit 4): `PcmMath.kt` (downmix, PCM16 <-> float,
  a streaming windowed-sinc `Resampler` with a polyphase table), `SrtWriter.kt`, and their tests. Build and test:
  `cd experiments/whisper-lite-android/audio; mvn -q -B -o test` (the local Maven cache has the dependencies;
  if one is missing, run once without `-o`).
- `android-src/AudioDecoder.kt`: MediaExtractor/MediaCodec decoder to 16 kHz mono PCM16 (cannot be compiled
  here: there is no Android SDK).
- `inputs/`: two independent reviews of AudioDecoder (`review-audiodecoder-argon.md` verifies the web one and
  adds more), the mutation results of `audio/`, the MVP design and the summary of its design review.

## Tasks
T1. `audio/` stays green and gets stronger:
  a. Kill the surviving mutant in `inputs/mutation-results.txt`: add a test that drives the direct (non-table)
     path of `Resampler` (a rate pair whose polyphase table would exceed the 2 million float limit, for example
     44101 -> 16000), with a stop-band check (12 kHz input at least 50 dB below a 1 kHz input) and a length check.
  b. Channel framing across buffers (review item): add a stateful `Downmixer(channels)` that carries leftover
     samples between calls (keep `downmixToMono` for whole buffers), with tests for odd-sized chunks.
T2. Rewrite `android-src/AudioDecoder.kt` so that every item marked CONFIRMED in
    `inputs/review-audiodecoder-argon.md` is fixed (output format changes incl. sample rate, cancellation
    rethrown, partial file deleted after close, 8/16/24/32-bit and float PCM, buffered output, free-space check
    with a fallback when the duration is unknown, no hang after input EOS, codec-config buffers skipped,
    clear()+position/limit order, monotonic and throttled progress, drain loops without 10 ms stalls).
    Move every piece of logic that does not need Android into pure Kotlin under `audio/` with unit tests
    (for example `PcmDecoder` for the PCM encodings, `ProgressTracker`, `SpaceEstimator`, and a decode-loop state
    machine written against a small codec interface that a fake implements in the tests). `AudioDecoder.kt` then
    becomes thin glue over those classes. Use only Android APIs that exist on API 26; mark any API you are unsure
    about with a `// VERIFY:` comment.
T3. Write `REVIEW.md` at the worktree root: per review item DONE / NOT DONE (+ why), the number of tests, the last
    lines of `mvn -q -B -o test` (or the surefire totals), and `git log --oneline -8` as your literal last command.

The supervisor reruns the tests, runs mutants against your code, and reads every diff. A test that cannot fail
or asserts nothing counts as missing. Do not weaken or delete existing tests.
