# Whisper Lite audio experiment

This experiment contains a pure Kotlin audio module and an Android platform adapter.
It is not a shipped Android app. No third-party runtime library is required beyond
the Kotlin standard library. The JVM tests use JUnit 4.

## Run the tests

From the worktree root, in PowerShell:

```powershell
Set-Location experiments/whisper-lite-android/audio
mvn -q -B -o test
```

Dependencies are supplied by the existing Maven cache. Surefire summaries are in
`audio/target/surefire-reports/`; generated files under `audio/target/` are ignored.

## Integration contract

Include the sources in `audio/src/main/kotlin/` together with
`android-src/AudioDecoder.kt` in the Android project. The adapter uses platform APIs
available on API 26. An Android build must use the usual Kotlin/Java desugaring
configuration for its selected toolchain; the Maven module alone does not package
an Android application.

`AudioDecoder.decodeTo16kMono` is a **blocking worker-thread call**. The original
prototype's `suspend`/`Dispatchers.IO` wrapper was removed so this module does not
require kotlinx-coroutines. A coroutine host supplies its own worker dispatcher
and passes its cancellation state through `isCancelled`. Cancellation throws
`java.util.concurrent.CancellationException`; it is never converted to `Failed`.
Thread interruption also cancels decoding.

The output path must be unused. Parent directories are created as needed. A
failed decode closes and deletes its newly created partial output, while existing
files are preserved. A successful decode flushes and closes the PCM file before
reporting progress `1.0` or returning `Ok`. Failure in that final callback preserves
the completed file. The output is headerless, little-endian, 16 kHz mono PCM16.

The output format is read from the codec, including when a buffer arrives before
the format-change event. Rate, channels, and encoding changes finish the previous
segment before replacing its decoder/downmixer/resampler. Repeated identical
format events preserve carry state. Incomplete final samples or channel frames
fail rather than silently dropping audio. Signed 16/24/32-bit, unsigned 8-bit,
and float PCM are supported; float NaNs become silence and out-of-range values
are clamped. Input PCM uses the platform's native byte order.

Nonblocking codec polls drain ready input and output before a 2 ms idle wait. Five
seconds without packet/PCM activity aborts a stalled decoder, including a codec
that consumes input EOS without producing output EOS. Format/config events do
not reset that watchdog. Progress uses the maximum observed timestamp, a 1%
minimum increment, and at least 100 ms between intermediate callbacks. Unknown
duration reports completion only.

Space estimates use the 16 kHz PCM size plus 10% when duration is known. Otherwise
the adapter queries the URI's asset length and estimates eight times that length,
with a 1 MiB estimate when length is unavailable or small. This is a heuristic;
compressed length cannot guarantee decoded length. Every write also enforces an
8 MiB free-space reserve plus allowance for buffered data. A zero space reading
fails the check.

## Test coverage and remaining platform validation

The JVM suite covers the PCM encodings and byte framing, channel framing,
resampling attenuation/length/continuity, format transitions, progress, storage
estimation, close-before-delete cleanup, persistence before completion, and codec
loop behavior through a scripted fake. The direct resampler regression uses
88201 -> 16000: 16000 phases times 179 taps exceeds the 2,000,000-float table cap.
The brief's example 44101 -> 16000 uses only 1,456,000 floats and stays on the
table path. Replacing the direct path's Blackman window with `1.0` has been checked
to fail the new 50 dB stop-band assertion.

The Android adapter has not been compiled or run here: no Android SDK or device
is available. Its `// VERIFY:` comments identify the platform checks. Before
shipping, compile and run on real API 26 and API 35 devices with compressed audio,
24/32-bit raw audio where supported by the device, format changes, cancellation,
relative and nested output paths, unknown URI duration/length, and disk exhaustion.
An OEM without a raw PCM decoder may reject `audio/raw`; there is no WAV parser
or software codec fallback in this experiment.
