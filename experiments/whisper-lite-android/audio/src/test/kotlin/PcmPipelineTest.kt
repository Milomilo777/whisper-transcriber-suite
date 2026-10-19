package app.whisperlite.audio

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

class PcmPipelineTest {
    private val mono16k = PcmFormat(16000, 1, PcmEncoding.SIGNED_16)

    @Test
    fun writerClampsRoundsAndSerializesLittleEndianInBulk() {
        val bytes = ByteArrayOutputStream()
        val checks = mutableListOf<Int>()
        val writer = Pcm16Writer(bytes) { checks.add(it) }
        writer.write(floatArrayOf(-2f, -0.5f / 32768, 0f, 0.5f / 32767, 2f, Float.NaN))
        assertArrayEquals(byteArrayOf(0, -128, -1, -1, 0, 0, 1, 0, -1, 127, 0, 0), bytes.toByteArray())
        assertEquals(6L, writer.samplesWritten)
        assertEquals(listOf(12), checks)
    }

    @Test
    fun writerReusesBoundedBufferAndCountsOnlySuccessfulWrites() {
        var calls = 0
        var count = 0
        var firstBuffer: ByteArray? = null
        val output = object : OutputStream() {
            override fun write(value: Int) { fail("Must write in bulk") }
            override fun write(data: ByteArray, offset: Int, length: Int) {
                if (firstBuffer == null) firstBuffer = data else assertSame(firstBuffer, data)
                assertTrue(length <= 16 * 1024)
                assertEquals(0, offset)
                calls++
                count += length
            }
        }
        val writer = Pcm16Writer(output)
        writer.write(FloatArray(20_000))
        assertEquals(3, calls)
        assertEquals(40_000, count)
        assertEquals(20_000L, writer.samplesWritten)
        val failing = Pcm16Writer(ByteArrayOutputStream()) { throw IOException("disk full") }
        assertThrows(IOException::class.java) { failing.write(floatArrayOf(1f)) }
        assertEquals(0L, failing.samplesWritten)
    }

    @Test
    fun oddByteAndChannelChunksEqualCompleteFrames() {
        val format = PcmFormat(16000, 2, PcmEncoding.SIGNED_16)
        val data = byteArrayOf(0, 32, 0, 96, 0, -96, 0, -32)
        val bytes = ByteArrayOutputStream()
        val pipeline = PcmPipeline(Pcm16Writer(bytes))
        pipeline.setFormat(format)
        data.forEach { pipeline.process(ByteBuffer.wrap(byteArrayOf(it))) }
        pipeline.finish()
        assertEquals(2L, pipeline.samplesWritten)
        assertArrayEquals(byteArrayOf(0, 64, 0, -64), bytes.toByteArray())
    }

    @Test
    fun rateAndChannelChangesFlushOldRateBeforeNewSegment() {
        val bytes = ByteArrayOutputStream()
        val pipeline = PcmPipeline(Pcm16Writer(bytes))
        for ((rate, channels) in listOf(44100 to 2, 48000 to 1)) {
            pipeline.setFormat(PcmFormat(rate, channels, PcmEncoding.FLOAT_32))
            val frames = rate / 10
            val input = ByteBuffer.allocate(frames * channels * 4).order(ByteOrder.LITTLE_ENDIAN)
            repeat(frames) { frame -> repeat(channels) { input.putFloat(sin(2 * PI * 1000 * frame / rate).toFloat()) } }
            input.flip()
            pipeline.process(input)
        }
        pipeline.finish()
        assertEquals(3200L, pipeline.samplesWritten)
        val decoded = PcmDecoder(PcmEncoding.SIGNED_16).process(ByteBuffer.wrap(bytes.toByteArray()))
        for (start in listOf(0, 1600)) {
            val rms = kotlin.math.sqrt((start + 64 until start + 1536).sumOf { decoded[it].toDouble() * decoded[it] } / 1472)
            assertEquals(1 / kotlin.math.sqrt(2.0), rms, 0.01)
            val crossings = (start + 65 until start + 1536).count { decoded[it - 1] < 0 && decoded[it] >= 0 }
            assertTrue("Both segments must remain 1 kHz", crossings in 90..93)
        }
    }

    @Test
    fun channelAndEncodingChangesAtTheSameRateAreApplied() {
        val bytes = ByteArrayOutputStream()
        val pipeline = PcmPipeline(Pcm16Writer(bytes))
        pipeline.setFormat(mono16k)
        pipeline.process(ByteBuffer.wrap(byteArrayOf(1, 0)))
        pipeline.setFormat(PcmFormat(16000, 2, PcmEncoding.SIGNED_16))
        pipeline.process(ByteBuffer.wrap(byteArrayOf(0, 0, 0, -128)))
        pipeline.setFormat(PcmFormat(16000, 1, PcmEncoding.UNSIGNED_8))
        pipeline.process(ByteBuffer.wrap(byteArrayOf(-1)))
        pipeline.finish()
        assertEquals(3L, pipeline.samplesWritten)
        assertArrayEquals(byteArrayOf(1, 0, 0, -64, -1, 127), bytes.toByteArray())
    }

    @Test
    fun repeatedFormatPreservesPartialSampleAndFinishIsIdempotent() {
        val bytes = ByteArrayOutputStream()
        val pipeline = PcmPipeline(Pcm16Writer(bytes))
        pipeline.setFormat(mono16k)
        pipeline.process(ByteBuffer.wrap(byteArrayOf(-1)))
        pipeline.setFormat(mono16k)
        pipeline.process(ByteBuffer.wrap(byteArrayOf(127)))
        pipeline.finish()
        pipeline.finish()
        assertEquals(1L, pipeline.samplesWritten)
        assertArrayEquals(byteArrayOf(-1, 127), bytes.toByteArray())
        assertThrows(IllegalStateException::class.java) { pipeline.process(ByteBuffer.allocate(0)) }
    }

    @Test
    fun incompleteSampleOrFrameFailsAtFormatChangeAndEos() {
        val partialSample = PcmPipeline(Pcm16Writer(ByteArrayOutputStream()))
        partialSample.setFormat(mono16k)
        partialSample.process(ByteBuffer.wrap(byteArrayOf(1)))
        assertThrows(IllegalArgumentException::class.java) { partialSample.finish() }
        assertThrows(IllegalArgumentException::class.java) {
            partialSample.setFormat(PcmFormat(48000, 1, PcmEncoding.SIGNED_16))
        }
        val partialFrame = PcmPipeline(Pcm16Writer(ByteArrayOutputStream()))
        partialFrame.setFormat(PcmFormat(16000, 2, PcmEncoding.SIGNED_16))
        partialFrame.process(ByteBuffer.wrap(byteArrayOf(0, 0)))
        assertThrows(IllegalArgumentException::class.java) { partialFrame.finish() }
    }

    @Test
    fun outputBeforeAnyFormatIsRejected() {
        val pipeline = PcmPipeline(Pcm16Writer(ByteArrayOutputStream()))
        assertThrows(IllegalStateException::class.java) { pipeline.process(ByteBuffer.wrap(byteArrayOf(0))) }
    }
}
