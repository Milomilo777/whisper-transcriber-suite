package app.whisperlite.audio

import java.io.OutputStream
import java.nio.Buffer
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.ceil
import kotlin.math.floor

/** Uses bounded reusable bytes and emits little-endian PCM16 in bulk writes. */
class Pcm16Writer(
    private val output: OutputStream,
    private val beforeWrite: (Int) -> Unit = {}
) {
    private val bytes = ByteArray(16 * 1024)
    var samplesWritten = 0L
        private set

    fun write(samples: FloatArray) {
        var offset = 0
        while (offset < samples.size) {
            val size = minOf(bytes.size / 2, samples.size - offset)
            for (i in 0 until size) {
                val sample = samples[offset + i].let { if (it.isNaN()) 0f else it.coerceIn(-1f, 1f) }
                val scaled = if (sample >= 0) sample * 32767f else sample * 32768f
                val rounded = if (scaled >= 0) floor(scaled + 0.5f) else ceil(scaled - 0.5f)
                val value = rounded.toInt().coerceIn(-32768, 32767)
                bytes[2 * i] = value.toByte()
                bytes[2 * i + 1] = (value shr 8).toByte()
            }
            beforeWrite(size * 2)
            output.write(bytes, 0, size * 2)
            samplesWritten += size
            offset += size
        }
    }
}

/** Changes of output format flush the old resampler before starting a new segment. */
class PcmPipeline(
    private val writer: Pcm16Writer,
    private val byteOrder: ByteOrder = ByteOrder.LITTLE_ENDIAN
) {
    private var format: PcmFormat? = null
    private var decoder: PcmDecoder? = null
    private var downmixer: Downmixer? = null
    private var resampler: Resampler? = null
    private var finished = false

    val samplesWritten: Long get() = writer.samplesWritten
    val hasFormat: Boolean get() = format != null

    fun setFormat(next: PcmFormat) {
        check(!finished) { "PCM pipeline already finished" }
        if (next == format) return
        finishSegment()
        format = next
        decoder = PcmDecoder(next.encoding, byteOrder)
        downmixer = Downmixer(next.channels)
        resampler = Resampler(next.sampleRate, 16000)
    }

    fun process(input: ByteBuffer) {
        check(!finished) { "PCM pipeline already finished" }
        check(format != null) { "Missing decoder output format" }
        // Bound intermediates even if a codec exposes a very large output buffer.
        while (input.hasRemaining()) {
            val chunk = input.slice()
            (chunk as Buffer).limit(minOf(chunk.remaining(), 16 * 1024))
            writer.write(resampler!!.process(downmixer!!.process(decoder!!.process(chunk))))
            (input as Buffer).position(input.position() + chunk.limit())
        }
    }

    fun finish() {
        if (finished) return
        finishSegment()
        finished = true
    }

    private fun finishSegment() {
        decoder?.finish()
        downmixer?.finish()
        resampler?.let { writer.write(it.flush()) }
    }
}
