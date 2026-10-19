package app.whisperlite.audio

import java.nio.ByteBuffer
import java.nio.ByteOrder

enum class PcmEncoding(val bytesPerSample: Int) {
    UNSIGNED_8(1), SIGNED_16(2), SIGNED_24(3), SIGNED_32(4), FLOAT_32(4);

    companion object {
        /** Stable platform PCM wire identifiers; no dependency on newer SDK fields. */
        fun fromPlatformCode(value: Int): PcmEncoding = when (value) {
            3 -> UNSIGNED_8
            2 -> SIGNED_16
            21 -> SIGNED_24
            22 -> SIGNED_32
            4 -> FLOAT_32
            else -> throw IllegalArgumentException("Unsupported PCM encoding: $value")
        }
    }
}

data class PcmFormat(val sampleRate: Int, val channels: Int, val encoding: PcmEncoding) {
    init {
        require(sampleRate > 0) { "Sample rate must be positive" }
        require(channels in 1..256) { "Channel count must be between 1 and 256" }
    }
}

/** Decodes PCM without losing samples split across byte-buffer boundaries. */
class PcmDecoder(
    private val encoding: PcmEncoding,
    private val byteOrder: ByteOrder = ByteOrder.LITTLE_ENDIAN
) {
    private val remainder = ByteArray(4)
    private var count = 0

    fun process(input: ByteBuffer): FloatArray {
        val width = encoding.bytesPerSample
        val result = FloatArray(((input.remaining().toLong() + count) / width).toInt())
        var output = 0
        while (input.hasRemaining()) {
            remainder[count++] = input.get()
            if (count == width) {
                var bits = 0
                for (i in 0 until width) {
                    val shift = if (byteOrder == ByteOrder.LITTLE_ENDIAN) i * 8 else (width - i - 1) * 8
                    bits = bits or ((remainder[i].toInt() and 0xff) shl shift)
                }
                result[output++] = when (encoding) {
                    PcmEncoding.UNSIGNED_8 -> {
                        val value = bits - 128
                        if (value >= 0) value / 127f else value / 128f
                    }
                    PcmEncoding.SIGNED_16 -> scale((bits shl 16) shr 16, 32767.0, 32768.0)
                    PcmEncoding.SIGNED_24 -> scale((bits shl 8) shr 8, 8388607.0, 8388608.0)
                    PcmEncoding.SIGNED_32 -> scale(bits, 2147483647.0, 2147483648.0)
                    PcmEncoding.FLOAT_32 -> Float.fromBits(bits).let {
                        if (it.isNaN()) 0f else it.coerceIn(-1f, 1f)
                    }
                }
                count = 0
            }
        }
        return result
    }

    fun finish() {
        require(count == 0) { "Incomplete ${encoding.name} sample: $count bytes" }
    }

    private fun scale(value: Int, positive: Double, negative: Double): Float =
        (value / if (value >= 0) positive else negative).toFloat()
}
