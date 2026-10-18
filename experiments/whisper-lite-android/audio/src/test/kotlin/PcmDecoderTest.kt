package app.whisperlite.audio

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class PcmDecoderTest {
    private fun bytes(vararg values: Int) = ByteArray(values.size) { values[it].toByte() }

    private val integers = listOf(
        PcmEncoding.UNSIGNED_8 to bytes(0, 64, 128, 192, 255),
        PcmEncoding.SIGNED_16 to bytes(0, 128, 0, 192, 0, 0, 0, 64, 255, 127),
        PcmEncoding.SIGNED_24 to bytes(0, 0, 128, 0, 0, 192, 0, 0, 0, 0, 0, 64, 255, 255, 127),
        PcmEncoding.SIGNED_32 to bytes(0, 0, 0, 128, 0, 0, 0, 192, 0, 0, 0, 0, 0, 0, 0, 64, 255, 255, 255, 127)
    )

    @Test
    fun integerExtremaAndMidpointsAcrossEveryByteBoundary() {
        for ((encoding, data) in integers) {
            for (chunkSize in 1..data.size) {
                val decoder = PcmDecoder(encoding)
                val actual = data.asList().chunked(chunkSize).flatMap {
                    val decoded = decoder.process(ByteBuffer.wrap(it.toByteArray()))
                    assertEquals(0, decoder.process(ByteBuffer.allocate(0)).size)
                    decoded.asList()
                }.toFloatArray()
                val positiveHalf = when (encoding) {
                    PcmEncoding.UNSIGNED_8 -> 64 / 127f
                    PcmEncoding.SIGNED_16 -> 16384 / 32767f
                    else -> 0.5f
                }
                assertArrayEquals("$encoding chunk=$chunkSize", floatArrayOf(-1f, -0.5f, 0f, positiveHalf, 1f), actual, 1e-7f)
                decoder.finish()
            }
        }
    }

    @Test
    fun signed24SignExtensionUsesAllThreeBytes() {
        val data = bytes(255, 255, 255, 1, 0, 0, 0x56, 0x34, 0x12, 0xaa, 0xcb, 0xed)
        assertArrayEquals(floatArrayOf(-1 / 8388608f, 1 / 8388607f, 0x123456 / 8388607f, -0x123456 / 8388608f),
            PcmDecoder(PcmEncoding.SIGNED_24).process(ByteBuffer.wrap(data)), 1e-8f)
    }

    @Test
    fun bigEndianAndDirectBuffersRespectTheirRange() {
        for ((encoding, littleEndian) in integers) {
            val bigEndian = littleEndian.asList().chunked(encoding.bytesPerSample).flatMap { it.reversed() }.toByteArray()
            val buffer = ByteBuffer.allocateDirect(bigEndian.size + 4)
            buffer.position(2)
            buffer.put(bigEndian)
            buffer.limit(buffer.position())
            buffer.position(2)
            val expected = PcmDecoder(encoding).process(ByteBuffer.wrap(littleEndian))
            val actual = PcmDecoder(encoding, ByteOrder.BIG_ENDIAN).process(buffer)
            assertArrayEquals(expected, actual, 0f)
            assertEquals(buffer.limit(), buffer.position())
        }
    }

    @Test
    fun floatClampingNanAndSplitWords() {
        for (order in listOf(ByteOrder.LITTLE_ENDIAN, ByteOrder.BIG_ENDIAN)) {
            val values = floatArrayOf(-2f, -1f, -0.25f, 0f, 0.25f, 1f, 2f, Float.NaN, Float.NEGATIVE_INFINITY, Float.POSITIVE_INFINITY)
            val buffer = ByteBuffer.allocate(values.size * 4).order(order)
            values.forEach { buffer.putFloat(it) }
            val decoder = PcmDecoder(PcmEncoding.FLOAT_32, order)
            val actual = buffer.array().asList().chunked(3).flatMap {
                decoder.process(ByteBuffer.wrap(it.toByteArray())).asList()
            }.toFloatArray()
            assertArrayEquals(floatArrayOf(-1f, -1f, -0.25f, 0f, 0.25f, 1f, 1f, 0f, -1f, 1f), actual, 0f)
            decoder.finish()
        }
    }

    @Test
    fun incompleteSamplesFailAtEnd() {
        for (encoding in PcmEncoding.entries.filter { it.bytesPerSample > 1 }) {
            val decoder = PcmDecoder(encoding)
            decoder.process(ByteBuffer.wrap(byteArrayOf(1)))
            assertThrows(IllegalArgumentException::class.java) { decoder.finish() }
        }
    }

    @Test
    fun platformEncodingCodesAndUnsupportedValues() {
        assertEquals(PcmEncoding.UNSIGNED_8, PcmEncoding.fromPlatformCode(3))
        assertEquals(PcmEncoding.SIGNED_16, PcmEncoding.fromPlatformCode(2))
        assertEquals(PcmEncoding.SIGNED_24, PcmEncoding.fromPlatformCode(21))
        assertEquals(PcmEncoding.SIGNED_32, PcmEncoding.fromPlatformCode(22))
        assertEquals(PcmEncoding.FLOAT_32, PcmEncoding.fromPlatformCode(4))
        assertThrows(IllegalArgumentException::class.java) { PcmEncoding.fromPlatformCode(999) }
    }

    @Test
    fun validateOutputFormatBeforeAllocating() {
        assertThrows(IllegalArgumentException::class.java) { PcmFormat(0, 1, PcmEncoding.SIGNED_16) }
        assertThrows(IllegalArgumentException::class.java) { PcmFormat(-1, 1, PcmEncoding.SIGNED_16) }
        assertThrows(IllegalArgumentException::class.java) { PcmFormat(16000, 0, PcmEncoding.SIGNED_16) }
        assertThrows(IllegalArgumentException::class.java) { PcmFormat(16000, -1, PcmEncoding.SIGNED_16) }
    }
}
