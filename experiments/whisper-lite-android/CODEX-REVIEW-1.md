# Whisper Lite audio review

Date: 2026-10-18. Branch: `codex/whisper-lite-audio`.

Implementation and JVM validation are complete. Android SDK compilation and real
device verification are NOT DONE. Git staging and commits are NOT DONE because
the worktree's Git metadata is outside the permitted folder and index writes are
denied. No commit was created, and no push was attempted.

## T1: strengthen the existing audio module

| Item | Status | Implementation and evidence |
| --- | --- | --- |
| T1a: direct resampler stop-band and length regression | DONE | Added `PcmMathTest.resampler_directPathStopbandAndLength`. It streams both 1 kHz and 12 kHz signals through 88201 -> 16000, checks both exact rounded lengths, requires the pass-band signal to survive, and requires at least 50 dB stop-band rejection. |
| T1a: kill the surviving Blackman mutant | DONE | Replaced only the direct path's Blackman expression with `1.0` temporarily. The new test failed its stop-band assertion: 1 test, 1 failure, 0 errors, 0 skipped; Maven exit 1. Restored the original source bytes in `finally`, then reran the entire suite successfully. The diagnostic log is under ignored `experiments/whisper-lite-android/audio/target/direct-mutant.log`. |
| T1b: stateful channel framing | DONE | Added `Downmixer(channels)` with per-frame carry between calls, including empty calls. Tests cover odd stereo chunks and every chunk size 1 through 11 for mono, stereo, three-channel and five-channel input. Final incomplete frames fail explicitly. `downmixToMono` remains available for whole buffers and rejects incomplete frames. |
| Preserve existing tests | DONE | All original 13 PCM-math tests and 3 SRT tests remain. The suite now has 71 tests, including 55 additions. |

The brief's suggested 44101 -> 16000 pair does **not** exercise the direct path
with the supplied implementation: it needs 16000 phases * 91 taps = 1,456,000
floats. The regression uses 88201 -> 16000: 16000 phases * 179 taps = 2,864,000
floats, exceeding the 2,000,000-float table limit.

## T2: findings in review-audiodecoder-argon.md

DONE below means the source fix is implemented and the non-Android behavior has
JVM coverage. It does not claim Android compilation or device validation.

| Review item | Status | Fix and evidence |
| --- | --- | --- |
| B1: output sample rate changes and missing input rate | DONE | The pipeline is initialized from the codec's output format, including a fallback read when PCM arrives before a format event. Each changed rate/channel/encoding finishes the old segment and constructs its replacement. Repeated identical events preserve carry state. No input sample-rate key is read for resampling. `PcmPipelineTest` checks rate changes using length, amplitude and frequency; it separately checks channel/encoding changes at the same rate. `DecodeLoopTest` covers missing initial format events and multiple transitions. Missing output keys fail with explicit messages. |
| B2: cancellation swallowed as failure | DONE | Android glue catches and rethrows `java.util.concurrent.CancellationException` before its general exception handler. Explicit cancellation and thread interruption also throw cancellation. Tests cover cancellation from the flag, source and progress observer; interrupted idle waits; unchanged exception identity; and cancellation surviving a throwing buffer release. |
| B3: partial output and output-buffer leaks | DONE | `withOutputTransaction` closes output through `use` before deleting partial output on failure, including cancellation and close errors. Every acquired output buffer is released in `finally`, including getter, range, PCM and observer failures. Cleanup failures are suppressed onto the original error. Tests check close/delete ordering, real partial-file deletion, final-buffer release and preservation of existing files. |
| B4: unsigned 8-bit, signed 16/24/32-bit and float PCM | DONE | `PcmDecoder` supports all five encodings, explicit byte order, sign extension and samples split across byte buffers. Tests exercise extrema, midpoints, arbitrary 24-bit values, every integer byte boundary, direct buffers, float splits, clipping, NaN and infinities. The adapter requests float output for compressed tracks while preserving raw input encoding metadata. Numeric encoding identifiers avoid linking API 31 fields on API 26. Unsupported values fail explicitly. |
| B5: boxing/copying/trigonometry and unbuffered writes | DONE | Kept the supplied primitive history/output buffers and precomputed polyphase table for normal rate pairs. The uncommon non-table path remains direct, as required by T1. Added a 64 KiB buffered file stream and reusable 16 KiB PCM byte buffer; removed intermediate ShortArray/ByteBuffer output serialization. Pipeline intermediates are limited to 16 KiB input slices. Tests verify bulk writes, buffer identity reuse, bounded write sizes, rounding, serialization and successful-write sample accounting. |
| B6: relative or missing output parent; zero usable space | DONE | `writePcmFile` resolves the parent, creates missing directories and checks usable space unconditionally. Zero space fails. Tests cover a bare relative filename, nested missing parents, zero/negative space, estimate boundaries and failure before file creation. Existing files are not overwritten or deleted. |
| B7: missing output EOS hang | DONE | A five-second monotonic activity watchdog aborts stalled decoding, including after input EOS. Format/config events cannot reset it. Fake-clock tests bound the number of polls/waits for missing EOS and reject a config-buffer storm. |
| B8: codec-config buffers, buffer limit ordering, timestamps and progress spam | DONE | Config buffers are skipped and still released. Output buffers are cleared before limit/position are set; ranges are validated. Input timestamps are nonnegative and nondecreasing, and input EOS uses the last timestamp. Progress keeps the maximum output timestamp, uses a 1% minimum increment and 100 ms minimum interval, and stays below 1 until output closes. Tests exercise stale limits with nonzero offsets, config bytes, negative/regressing timestamps, throttling and zero-timestamp nonempty EOS. |
| B9: rejected endorsement of stateless channel framing | DONE | The decoder uses the stateful downmixer for all channel counts. Whole-buffer downmixing now validates framing, and stream termination validates its remainder rather than dropping samples. See T1b. |
| C1: 10 ms stalls per packet | DONE | Inner loops drain ready input and output with zero dequeue timeouts. Only an iteration with neither input nor output activity waits, for 2 ms. Fake-codec tests assert zero timeouts, consecutive input draining, multiple output draining and waiting only when both sides are unavailable. |
| C2: absent duration and falling disk space | DONE | Unknown duration queries `AssetFileDescriptor.length`; unavailable length still gets a minimum estimate. `SpaceEstimator` uses duration-based PCM size plus 10%, or eight times source length with a 1 MiB estimate floor, plus an 8 MiB reserve. Every write checks space again with allowance for the pending buffered bytes. Tests cover missing duration/length, zero and falling space, exact thresholds and overflow-safe estimates. Compressed-length estimates are heuristic; streaming checks enforce the reserve independently. |
| C3: channel framing across buffers | DONE | `PcmDecoder` first carries incomplete bytes; `Downmixer` then carries incomplete channel frames. Both have explicit end checks. Tests split stereo PCM one byte at a time and exercise odd multichannel chunks. |
| C4: progress regresses at nonempty EOS | DONE | `ProgressTracker` retains the maximum presentation timestamp. A test writes a final nonempty buffer with timestamp zero after a 50% buffer and verifies both PCM samples and unchanged intermediate progress. Session tests verify that final progress 1 observes an already flushed file. |
| C5: nonpositive channels or rate bypass validation | DONE | `PcmFormat` rejects nonpositive rates and channel counts; `Downmixer` also validates channels. The adapter requires the decoder's rate/channel keys before constructing this validated format. Unit tests cover zero and negative values. |

The review's five prioritized fixes are covered by B1/B2/B3/B4/B5/B7/B8 and C1.

### Pure Kotlin extraction and completion ordering

The JVM module now owns `PcmDecoder`, `PcmFormat`, `Downmixer`, `PcmPipeline`,
`Pcm16Writer`, `ProgressTracker`, `SpaceEstimator`, output transactions,
`DecodeLoop` against `DecodeCodec`/`EncodedSource`, `DecodeResult`, and
`decodeToPcmFile`. Android glue owns extractor/codec/URI access and releases each
Android resource independently.

`decodeToPcmFile` finishes the resampler and closes buffered output before
reporting completion or returning `Ok`. Tests verify that a completion observer
can read the flushed tail, and that an exception or cancellation in that final
observer preserves the completed file.

The adapter is now a blocking worker-thread API, removing the prototype's
kotlinx-coroutines dependency. Coroutine hosts supply their own dispatcher and
job-state cancellation callback. There is no `DecodeResult.Cancelled`:
cancellation propagates as an exception. Integration details are in
`experiments/whisper-lite-android/README.md`.

### Remaining validation and commit blocker

| Item | Status | Why |
| --- | --- | --- |
| Android SDK compilation | NOT DONE | This environment has no Android SDK, as stated in the brief. The adapter contains `// VERIFY:` markers for compilation and device checks. It uses API 26 platform interfaces and avoids references to newer PCM constant fields. JVM buffer mutations use `java.nio.Buffer` signatures to avoid Java 9 covariant ByteBuffer methods on older Android versions. |
| Real hardware/data end-to-end validation | NOT DONE | No Android device validation was performed. Before shipping, verify API 26/35 devices, OEM codecs, URI metadata, actual 24/32-bit raw output where supported, cancellation and storage exhaustion. OEMs without a raw PCM decoder remain unsupported; no WAV parser fallback was requested or added. |
| Small coherent Git commits | NOT DONE | Both `git add` and the attempted baseline `git commit` failed with permission denied creating `index.lock`. This worktree stores Git metadata outside the allowed folder. No permission workaround, metadata relocation, configuration edit or history operation was attempted. The failed commit invocation included the required `Assisted-by: GPT-6.1 Sol (OpenAI)` trailer. The supplied experiment and BRIEF were already untracked at the start; they and the implementation remain uncommitted. |

## T3: test results and final command

Final successful command, run from the worktree root:

```powershell
Set-Location -LiteralPath experiments/whisper-lite-android/audio
mvn -q -B -o test
```

Exit code: **0**. Quiet Maven produced no final stdout lines. The final Surefire
reports contain these totals; no tests are skipped:

| Test class | Tests | Failures | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| DecodeLoopTest | 12 | 0 | 0 | 0 |
| DecodeSessionTest | 4 | 0 | 0 | 0 |
| DownmixerTest | 5 | 0 | 0 | 0 |
| PcmDecoderTest | 7 | 0 | 0 | 0 |
| PcmMathTest | 14 | 0 | 0 | 0 |
| PcmOutputFileTest | 8 | 0 | 0 | 0 |
| PcmPipelineTest | 8 | 0 | 0 | 0 |
| ProgressTrackerTest | 5 | 0 | 0 | 0 |
| SpaceEstimatorTest | 5 | 0 | 0 | 0 |
| SrtWriterTest | 3 | 0 | 0 | 0 |
| **Total** | **71** | **0** | **0** | **0** |

Aggregation from the final ten Surefire XML reports printed:

```text
Surefire totals: Tests run: 71, Failures: 0, Errors: 0, Skipped: 0; reports: 10
```

The direct-window mutation was deliberately tested separately and restored before
that successful full run. Existing resampler and SRT tests were not weakened or
deleted. Generated Maven output is ignored by the experiment's `audio/.gitignore`.
Source edits stay within `experiments/whisper-lite-android/`; this review is at the
permitted worktree root. No desktop code, release configuration or version was changed.

The unchanged last eight commits are:

```text
3852002 Website: fixes from an Argon review of the language code
d740b7f Website: an English button on every translated page
680aa6b Website: a usual web font per script; keep the header on one line
6a4d231 Website: allow the Cloudflare Web Analytics beacon in the CSP
40c1c72 Website: harden the "/" language redirect before the translations ship
62f9bbf Website: rebuild llms-full.txt for the admin@ contact line
a3d8b20 Website: Search Console verification tag for the .com property
9a54eab Add files for enrolment in Anthropic's OSS Scanner
```

The literal last shell command for this run is:

```powershell
git log --oneline -8
```
