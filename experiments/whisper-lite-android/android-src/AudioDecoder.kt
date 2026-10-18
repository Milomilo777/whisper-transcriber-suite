package app.whisperlite.audio

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CancellationException

// VERIFY: Compile this adapter with an Android SDK and exercise real codecs on API 26 and 35.
class AudioDecoder(private val context: Context) {
    /**
     * Blocking worker-thread API with no coroutine dependency. Coroutine callers must
     * dispatch to their worker and pass their job's cancellation state in isCancelled.
     * CancellationException (including one from a callback) always propagates.
     */
    fun decodeTo16kMono(
        uri: Uri,
        out: File,
        onProgress: (Float) -> Unit,
        isCancelled: () -> Boolean
    ): DecodeResult {
        var extractor: MediaExtractor? = null
        var codec: MediaCodec? = null
        try {
            if (isCancelled()) throw CancellationException("Audio decoding cancelled")
            val input = MediaExtractor()
            extractor = input
            input.setDataSource(context, uri, null)
            val track = (0 until input.trackCount).firstOrNull {
                input.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: return DecodeResult.Failed("No audio track found")
            input.selectTrack(track)
            val format = input.getTrackFormat(track)
            val mime = format.getString(MediaFormat.KEY_MIME)
                ?: return DecodeResult.Failed("Missing MIME type")
            val durationUs = if (format.containsKey(MediaFormat.KEY_DURATION)) {
                format.getLong(MediaFormat.KEY_DURATION).coerceAtLeast(0)
            } else 0L
            val sourceBytes = if (durationUs > 0) -1L else sourceLength(uri)

            // On compressed tracks this is a decoder output preference. On audio/raw
            // the key describes the SOURCE representation, so it must be preserved.
            if (mime != "audio/raw") {
                format.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_FLOAT)
            }
            val decoder = MediaCodec.createDecoderByType(mime)
            codec = decoder
            decoder.configure(format, null, null, 0)
            decoder.start()
            return decodeToPcmFile(
                codec = AndroidCodec(decoder),
                source = EncodedSource { target ->
                    val size = input.readSampleData(target, 0)
                    if (size < 0) null else {
                        val packet = InputPacket(size, input.sampleTime)
                        input.advance()
                        packet
                    }
                },
                out = out,
                durationUs = durationUs,
                sourceBytes = sourceBytes,
                onProgress = onProgress,
                isCancelled = isCancelled,
                byteOrder = ByteOrder.nativeOrder()
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Exception) {
            return DecodeResult.Failed(failure.message ?: "Audio decoding failed")
        } finally {
            // stop() may fail on an unconfigured codec; release the other resources anyway.
            try { codec?.stop() } catch (_: Exception) {}
            try { codec?.release() } catch (_: Exception) {}
            try { extractor?.release() } catch (_: Exception) {}
        }
    }

    private fun sourceLength(uri: Uri): Long = try {
        context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        // Unknown provider length still gets the space floor and streaming checks.
        -1L
    }
}

private class AndroidCodec(private val codec: MediaCodec) : DecodeCodec {
    private val info = MediaCodec.BufferInfo()

    override fun dequeueInput(timeoutUs: Long): CodecInput? {
        val index = codec.dequeueInputBuffer(timeoutUs)
        return if (index < 0) null else CodecInput(index,
            checkNotNull(codec.getInputBuffer(index)) { "Missing codec input buffer" })
    }

    override fun queueInput(index: Int, size: Int, presentationTimeUs: Long, endOfStream: Boolean) {
        codec.queueInputBuffer(index, 0, size, presentationTimeUs,
            if (endOfStream) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0)
    }

    override fun dequeueOutput(timeoutUs: Long): CodecEvent = when (val index = codec.dequeueOutputBuffer(info, timeoutUs)) {
        MediaCodec.INFO_TRY_AGAIN_LATER -> CodecEvent.TryAgain
        MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> CodecEvent.FormatChanged
        MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> CodecEvent.BuffersChanged
        else -> {
            check(index >= 0) { "Unknown codec dequeue result: $index" }
            CodecEvent.Output(index, info.offset, info.size, info.presentationTimeUs,
                info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0,
                info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0)
        }
    }

    override fun outputFormat(): PcmFormat {
        val format = codec.outputFormat
        require(format.containsKey(MediaFormat.KEY_SAMPLE_RATE)) { "Missing output sample rate" }
        require(format.containsKey(MediaFormat.KEY_CHANNEL_COUNT)) { "Missing output channel count" }
        val encoding = if (format.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
            // VERIFY: Exercise 24/32-bit raw decoder output on devices that expose it.
            PcmEncoding.fromPlatformCode(format.getInteger(MediaFormat.KEY_PCM_ENCODING))
        } else PcmEncoding.SIGNED_16
        return PcmFormat(format.getInteger(MediaFormat.KEY_SAMPLE_RATE),
            format.getInteger(MediaFormat.KEY_CHANNEL_COUNT), encoding)
    }

    override fun outputBuffer(index: Int): ByteBuffer? = codec.getOutputBuffer(index)
    override fun releaseOutput(index: Int) = codec.releaseOutputBuffer(index, false)
}
