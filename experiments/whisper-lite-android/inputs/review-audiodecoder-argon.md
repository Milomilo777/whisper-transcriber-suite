### (B) Verification of Earlier Review

1. **[CRITICAL] Output sample rate changes ignored (`AudioDecoder.kt:62, 99–120`):** **CONFIRMED** — `Resampler` is created once from `inputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)` (`line 62`), which throws `NullPointerException` if absent and ignores `decoder.outputFormat` rate changes (e.g., HE-AAC SBR doubling rate) in `INFO_OUTPUT_FORMAT_CHANGED` (`lines 99–107`).
2. **[HIGH] Coroutine cancellation swallowed as failure (`AudioDecoder.kt:71, 183`):** **CONFIRMED** — `catch (e: Exception)` (`line 183`) catches `CancellationException` (which extends `IllegalStateException`) and returns `DecodeResult.Failed` instead of rethrowing or returning `DecodeResult.Cancelled`.
3. **[HIGH] Partial output file leaked on disk (`AudioDecoder.kt:142, 183–191`):** **CONFIRMED** — Early return at `line 142` (`return@withContext DecodeResult.Failed(...)`) bypasses `out.delete()` and `decoder.releaseOutputBuffer(outputBufferIndex, false)` (`line 159`), and `catch (e: Exception)` (`line 184`) calls `out.delete()` before `fos?.close()` (`line 190`).
4. **[HIGH] 8-bit, 24-bit, and 32-bit WAV files fail (`AudioDecoder.kt:55–57, 126–144`):** **CONFIRMED** — `when (currentPcmEncoding)` (`lines 126–144`) only handles `ENCODING_PCM_16BIT` and `ENCODING_PCM_FLOAT`, failing at `line 142` for `ENCODING_PCM_8BIT`, `ENCODING_PCM_24BIT_PACKED`, and `ENCODING_PCM_32BIT`.
5. **[HIGH] Extreme boxing, array copying, trig CPU burn, and unbuffered I/O (`PcmMath.kt:59, 69–72, 102–116, 125`; `AudioDecoder.kt:61, 146–150`):** **CONFIRMED** — `ArrayList<Float>` (`PcmMath.kt:59`) boxes every output sample, `computeSample` (`lines 110–111`) runs `cos`/`sin` per tap, `process`/`trim` (`lines 64, 124`) reallocate `history` per chunk, and `FileOutputStream(out)` (`AudioDecoder.kt:60`) is unbuffered.
6. **[MEDIUM] Free-space check silently skipped or crashes on relative/missing parent path (`AudioDecoder.kt:47–53, 60`):** **CONFIRMED** — `out.parentFile?.usableSpace ?: 0L` (`line 49`) is `0L` when `out` has no parent component (`File("out.pcm")`) or parent directory does not exist, and `if (freeBytes > 0 && ...)` (`line 50`) skips the check on `0L`.
7. **[MEDIUM] Infinite loop risk if decoder drops output EOS (`AudioDecoder.kt:71, 96–98`):** **CONFIRMED** — `while (!outputDone)` (`line 71`) has no timeout or retry cap if `dequeueOutputBuffer` (`line 94`) repeatedly returns `INFO_TRY_AGAIN_LATER` after `inputDone = true` (`line 85`).
8. **[LOW] Codec-config output buffers, ByteBuffer limit ordering, and `onProgress` spam (`AudioDecoder.kt:86, 121–124, 155–157`):** **CONFIRMED** — `outputBuffer.position(bufferInfo.offset)` before `outputBuffer.limit(...)` (`lines 122–123`) throws `IllegalArgumentException` if a buffer's previous `limit < offset`, `BUFFER_FLAG_CODEC_CONFIG` is not filtered at `line 121`, `extractor.sampleTime` (`line 86`) can be `-1L`, and `onProgress` (`line 156`) is unthrottled.
9. **Earlier Review "What Is Fine" — Endianness & PCM math (`PcmMath.kt:13–26`):** **REJECTED** — `downmixToMono` (`lines 13–26`) silently drops `interleaved.size % channels` trailing samples and permanently swaps channels on subsequent buffers if a buffer is not frame-aligned.

---

### (C) Real Issues the Earlier Review Missed

1. **[HIGH] 10 ms blocking stalls per packet destroy decode throughput (`AudioDecoder.kt:78–98`)**
   * **Line/Function:** `decodeTo16kMono`, `decoder.dequeueInputBuffer(10_000L)` (`line 79`) and `decoder.dequeueOutputBuffer(bufferInfo, 10_000L)` (`line 94`).
   * **Failing scenario:** Because the loop processes at most one input buffer and one output buffer per iteration with 10 ms timeouts on both, every initial input packet before the codec emits output sleeps 10 ms in `dequeueOutputBuffer`, and whenever input buffers are full while multiple output buffers are queued (or after `INFO_OUTPUT_FORMAT_CHANGED`), `dequeueInputBuffer(10_000L)` sleeps 10 ms per frame. A 1-hour file incurs minutes of idle wait time.
   * **Fix:** Drain all available input buffers in an inner `while` loop with timeout `0L` (only blocking when no output is available), and drain all available output buffers in an inner loop before waiting.

2. **[HIGH] Free-space check bypassed when `KEY_DURATION` is absent or during write (`AudioDecoder.kt:44–53, 150`)**
   * **Line/Function:** `decodeTo16kMono`, `lines 44–53` and `outputStream.write(bytes)` (`line 150`).
   * **Failing scenario:** Ogg/Opus streams, VBR MP3s without Xing headers, or `content://` streams lacking `MediaFormat.KEY_DURATION` yield `durationUs = 0L` (`line 44`), skipping `if (durationSec > 0)` (`line 47`) entirely so decoding fills the disk until `write()` throws `IOException`.
   * **Fix:** Fallback to estimating minimum required space from `AssetFileDescriptor.length` (via `context.contentResolver.openAssetFileDescriptor(uri, "r")`) and enforce a minimum free-space floor during streaming writes.

3. **[MEDIUM] Channel mis-framing across chunk boundaries (`PcmMath.kt:13–26`, `AudioDecoder.kt:138–140`)**
   * **Line/Function:** `downmixToMono` (`PcmMath.kt:16`) called at `AudioDecoder.kt:139`.
   * **Failing scenario:** If a raw/WAV decoder buffer has `samples.size` not divisible by `currentChannels` (e.g., an odd number of 16-bit samples in stereo), `val frames = interleaved.size / channels` drops the remainder sample and shifts L/R channel alignment for all subsequent buffers.
   * **Fix:** Carry over leftover `interleaved.size % channels` samples into a small per-channel remainder buffer before the next `downmixToMono` call, or validate `currentChannels >= 1`.

4. **[MEDIUM] Progress jumps backward to `0.0f` on non-empty EOS buffer (`AudioDecoder.kt:84, 153–157`)**
   * **Line/Function:** `decodeTo16kMono`, `lines 84, 153–157`.
   * **Failing scenario:** Input EOS is queued with `presentationTimeUs = 0L` (`line 84`). If the codec attaches `BUFFER_FLAG_END_OF_STREAM` to the final non-empty PCM buffer (`bufferInfo.size > 0`) with `bufferInfo.presentationTimeUs == 0L`, `line 155` computes `0.0f` and calls `onProgress(0.0f)` right before `onProgress(1.0f)` (`line 178`), causing UI progress bars to flash back to 0%.
   * **Fix:** Use `lastPresentationTimeUs = maxOf(lastPresentationTimeUs, bufferInfo.presentationTimeUs)` so progress is strictly monotonic.

5. **[LOW] Invalid `currentChannels <= 0` bypasses validation (`AudioDecoder.kt:101, 112, 138`)**
   * **Line/Function:** `decodeTo16kMono`, `if (currentChannels > 1)` (`line 138`).
   * **Failing scenario:** A malformed track reporting `KEY_CHANNEL_COUNT = 0` skips `downmixToMono` (`line 138`) instead of failing fast.
   * **Fix:** Fail immediately with `DecodeResult.Failed` if `currentChannels < 1` or `sampleRate <= 0`.

---

### Top 5 Fixes in Order

1. **Handle dynamic output sample rate & missing `inputFormat` keys (`AudioDecoder.kt:62, 99–120`):** Initialize and recreate/flush `Resampler` from `decoder.outputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)` on `INFO_OUTPUT_FORMAT_CHANGED` and validate `sampleRate > 0` and `channels >= 1`.
2. **Eliminate allocations, trig calls, and unbuffered writes (`PcmMath.kt:59–128`, `AudioDecoder.kt:60, 146–150`):** Replace `ArrayList<Float>` and per-sample `sin`/`cos` in `Resampler` with a precomputed polyphase sinc table and primitive ring buffer; wrap `FileOutputStream` in `BufferedOutputStream` and reuse output byte buffers.
3. **Fix coroutine cancellation and guaranteed file/buffer cleanup (`AudioDecoder.kt:71–76, 142, 183–191`):** Rethrow `CancellationException` (or check `coroutineContext.ensureActive()`), release `outputBufferIndex` in a `try/finally`, and delete `out` in the outer `finally` after `fos?.close()` whenever `succeeded == false`.
4. **Fix MediaCodec loop stalls and EOS hang (`AudioDecoder.kt:78–98, 122–123`):** Drain all ready input and output buffers with `0L` timeouts before waiting, call `outputBuffer.clear()` before setting `position`/`limit`, skip `BUFFER_FLAG_CODEC_CONFIG`, and cap consecutive `INFO_TRY_AGAIN_LATER` retries after `inputDone`.
5. **Support all WAV/raw PCM encodings (`AudioDecoder.kt:56, 126–144`):** Request `ENCODING_PCM_FLOAT` on `inputFormat` prior to `decoder.configure()` and implement fallback conversions for `ENCODING_PCM_8BIT`, `ENCODING_PCM_24BIT_PACKED`, and `ENCODING_PCM_32BIT`.

---

### What Is Fine

* Both files compile on SDK 26–35 with standard `kotlinx-coroutines` imports and no missing symbols.
* `pcm16ToFloat` and `floatToPcm16` clamping, scaling, and little-endian byte serialization (`AudioDecoder.kt:148–149`) are accurate.
* Final `resampler.flush()` output is written after the decode loop (`AudioDecoder.kt:167–175`).
* Independent `try/catch` blocks in `finally` (`AudioDecoder.kt:187–190`) prevent `codec.stop()` exceptions from skipping `codec.release()` or `extractor.release()`.
