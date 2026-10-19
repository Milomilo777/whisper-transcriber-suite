package app.whisperlite.audio

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

class PcmMathTest {

    private fun concat(a: FloatArray, b: FloatArray): FloatArray {
        val res = FloatArray(a.size + b.size)
        System.arraycopy(a, 0, res, 0, a.size)
        System.arraycopy(b, 0, res, a.size, b.size)
        return res
    }

    private fun rms(arr: FloatArray, skip: Int = 64): Double {
        require(arr.size >= 2 * skip) { "Array size must be >= 2 * skip" }
        var sum = 0.0
        val count = arr.size - 2 * skip
        for (i in skip until arr.size - skip) {
            val v = arr[i].toDouble()
            sum += v * v
        }
        return sqrt(sum / count)
    }

    @Test
    fun downmixToMono_twoChannels() {
        val interleaved = floatArrayOf(0.2f, 0.4f, -0.2f, -0.4f, 1.0f, -1.0f)
        val mono = downmixToMono(interleaved, 2)
        assertArrayEquals(floatArrayOf(0.3f, -0.3f, 0.0f), mono, 1e-6f)
    }

    @Test
    fun downmixToMono_divisionCheck() {
        val interleaved = floatArrayOf(0.1f, 0.2f, 0.3f, 0.4f)
        val mono = downmixToMono(interleaved, 4)
        assertEquals(1, mono.size)
        assertEquals(0.25f, mono[0], 1e-6f)

        val single = floatArrayOf(0.5f, -0.5f)
        val monoSingle = downmixToMono(single, 1)
        assertArrayEquals(single, monoSingle, 1e-6f)
    }

    @Test
    fun pcm16RoundTrip_extremes() {
        val src = shortArrayOf(-32768, 32767, 0)
        val floats = pcm16ToFloat(src)
        assertArrayEquals(floatArrayOf(-1.0f, 1.0f, 0.0f), floats, 1e-6f)
        val back = floatToPcm16(floats)
        assertArrayEquals(src, back)
    }

    @Test
    fun pcm16ToFloat_negativeScale() {
        val src = shortArrayOf(-16384, -32768)
        val floats = pcm16ToFloat(src)
        assertEquals(-0.5f, floats[0], 1e-6f)
        assertEquals(-1.0f, floats[1], 1e-6f)
        assertNotEquals(-16384f / 32767f, floats[0], 1e-6f)
    }

    @Test
    fun floatToPcm16_roundsAwayFromZero() {
        val pos = floatToPcm16(floatArrayOf(0.5f / 32767f))
        assertEquals(1.toShort(), pos[0])
        val neg = floatToPcm16(floatArrayOf(-0.5f / 32768f))
        assertEquals((-1).toShort(), neg[0])
    }

    @Test
    fun resampler_frequencyAndAmplitude() {
        val inRate = 44100
        val outRate = 16000
        val freq = 1000.0
        val durationSec = 0.5
        val n = (inRate * durationSec).toInt()
        val input = FloatArray(n) { i -> sin(2.0 * PI * freq * i / inRate).toFloat() }
        val resampler = Resampler(inRate, outRate)
        val output = concat(resampler.process(input), resampler.flush())
        val expectedLen = round(n * outRate.toDouble() / inRate).toInt()
        assertEquals(expectedLen, output.size)

        var zeroCrossings = 0
        for (i in 1 until output.size) {
            if (output[i-1] < 0f && output[i] >= 0f || output[i-1] > 0f && output[i] <= 0f) {
                zeroCrossings++
            }
        }
        val expectedCrossings = (2 * freq * durationSec).toInt()
        assertTrue(abs(zeroCrossings - expectedCrossings) <= expectedCrossings * 0.01 + 1)

        val rmsVal = rms(output, 64)
        val expectedRms = 1.0 / sqrt(2.0)
        assertTrue(abs(rmsVal - expectedRms) <= expectedRms * 0.02)
    }

    @Test
    fun resampler_stopbandLeakage_window() {
        val inRate = 44100
        val outRate = 16000
        val durationSec = 0.2
        val n = (inRate * durationSec).toInt()
        val input9k = FloatArray(n) { i -> sin(2.0 * PI * 12000.0 * i / inRate).toFloat() } // well inside the stop band
        val input1k = FloatArray(n) { i -> sin(2.0 * PI * 1000.0 * i / inRate).toFloat() }

        val r9k = Resampler(inRate, outRate)
        val out9k = concat(r9k.process(input9k), r9k.flush())
        val r1k = Resampler(inRate, outRate)
        val out1k = concat(r1k.process(input1k), r1k.flush())

        val rms9k = rms(out9k, 64)
        val rms1k = rms(out1k, 64)
        val threshold50dB = 10.0.pow(-2.5)
        assertTrue("12 kHz at 44100->16000 must be at least 50 dB down", rms9k <= rms1k * threshold50dB)
    }

    @Test
    fun resampler_directPathStopbandAndLength() {
        // gcd(44101, 16000) = 1, so 16000 phases * 91 taps = 1,456,000
        // floats, BELOW the table cap. Use 88201: 16000 * 179 = 2,864,000.
        // This forces the non-table path without depending on implementation reflection.
        val inRate = 88201
        val outRate = 16000
        val n = inRate / 5
        fun resample(freq: Double): FloatArray {
            val input = FloatArray(n) { sin(2.0 * PI * freq * it / inRate).toFloat() }
            val resampler = Resampler(inRate, outRate)
            val parts = input.asList().chunked(997).map { resampler.process(it.toFloatArray()) } + resampler.flush()
            return parts.fold(FloatArray(0)) { result, part -> concat(result, part) }
        }
        val passband = resample(1000.0)
        val stopband = resample(12000.0)
        val expected = round(n.toDouble() * outRate / inRate).toInt()
        assertEquals(expected, passband.size)
        assertEquals(expected, stopband.size)
        assertTrue("1 kHz must survive", rms(passband) > 0.69)
        assertTrue("12 kHz on the direct path must be at least 50 dB down",
            rms(stopband) <= rms(passband) * 10.0.pow(-2.5))
    }

    @Test
    fun resampler_aliasing() {
        val inRate = 48000
        val durationSec = 0.2
        val n = (inRate * durationSec).toInt()
        val input1k = FloatArray(n) { i -> sin(2.0 * PI * 1000.0 * i / inRate).toFloat() }

        // 7 kHz sine at 48000 Hz resampled to 8000 Hz (Nyquist 4 kHz, where 7 kHz aliases to 1 kHz):
        // Anti-alias cutoff must attenuate it by at least 40 dB relative to 1 kHz sine
        val input7k = FloatArray(n) { i -> sin(2.0 * PI * 7000.0 * i / inRate).toFloat() }
        val r7k_8k = Resampler(inRate, 8000)
        val out7k_8k = concat(r7k_8k.process(input7k), r7k_8k.flush())
        val r1k_8k = Resampler(inRate, 8000)
        val out1k_8k = concat(r1k_8k.process(input1k), r1k_8k.flush())
        val rms7k_8k = rms(out7k_8k, 64)
        val rms1k_8k = rms(out1k_8k, 64)
        assertTrue("7 kHz at 48k->8k must be at least 40 dB below 1 kHz", rms7k_8k <= rms1k_8k * 0.01)

        // Resampling 48000 Hz -> 16000 Hz: frequency above Nyquist (e.g. 23 kHz, aliasing to 7 kHz)
        // must come out at least 40 dB below 1 kHz sine
        val input23k = FloatArray(n) { i -> sin(2.0 * PI * 23000.0 * i / inRate).toFloat() }
        val r23k = Resampler(inRate, 16000)
        val out23k = concat(r23k.process(input23k), r23k.flush())
        val r1k_16 = Resampler(inRate, 16000)
        val out1k_16 = concat(r1k_16.process(input1k), r1k_16.flush())
        val rms23k = rms(out23k, 64)
        val rms1k_16 = rms(out1k_16, 64)
        assertTrue("23 kHz at 48k->16k must be at least 40 dB below 1 kHz", rms23k <= rms1k_16 * 0.01)
    }

    @Test
    fun resampler_exactOutputLength() {
        val outRate = 16000
        val inRates = intArrayOf(44100, 48000, 22050, 8000)
        val testNs = intArrayOf(0, 1, 13, 64, 100, 1234, 10000, 44100)
        for (inRate in inRates) {
            for (n in testNs) {
                val input = FloatArray(n) { 0.1f }
                val resampler = Resampler(inRate, outRate)
                val out = concat(resampler.process(input), resampler.flush())
                val expected = round(n.toDouble() * outRate / inRate).toInt()
                assertEquals("Exact length mismatch for inRate=$inRate, n=$n", expected, out.size)
            }
        }
    }

    @Test
    fun resampler_chunkedEqualsOneShot_randomChunks() {
        val rng = java.util.Random(12345)
        val inRates = intArrayOf(44100, 48000, 22050, 8000)
        for (inRate in inRates) {
            val outRate = 16000
            val n = 10000
            val input = FloatArray(n) { i -> sin(2.0 * PI * 440.0 * i / inRate).toFloat() }

            val oneShot = Resampler(inRate, outRate)
            val out1 = concat(oneShot.process(input), oneShot.flush())

            val chunked = Resampler(inRate, outRate)
            var offset = 0
            val chunks = mutableListOf<FloatArray>()
            var totalProcessed = 0
            while (offset < n) {
                val chunkSize = rng.nextInt(500) + 1
                val size = minOf(chunkSize, n - offset)
                val outChunk = chunked.process(input.copyOfRange(offset, offset + size))
                chunks.add(outChunk)
                totalProcessed += outChunk.size
                offset += size
            }
            val flushChunk = chunked.flush()
            chunks.add(flushChunk)
            totalProcessed += flushChunk.size

            val out2 = FloatArray(totalProcessed)
            var destPos = 0
            for (c in chunks) {
                System.arraycopy(c, 0, out2, destPos, c.size)
                destPos += c.size
            }

            assertEquals(out1.size, out2.size)
            for (i in out1.indices) {
                assertEquals("Mismatch at $i for inRate=$inRate", out1[i], out2[i], 1e-4f)
            }
        }
    }

    @Test
    fun resampler_chunkedEqualsOneShot() {
        val inRate = 44100
        val outRate = 16000
        val n = 10000
        val input = FloatArray(n) { i -> sin(2.0 * PI * 440.0 * i / inRate).toFloat() }

        val oneShot = Resampler(inRate, outRate)
        val out1 = concat(oneShot.process(input), oneShot.flush())

        val chunked = Resampler(inRate, outRate)
        val chunkSize = 1234
        val outputs = mutableListOf<Float>()
        var offset = 0
        while (offset < n) {
            val size = minOf(chunkSize, n - offset)
            outputs.addAll(chunked.process(input.copyOfRange(offset, offset + size)).toList())
            offset += size
        }
        outputs.addAll(chunked.flush().toList())
        val out2 = outputs.toFloatArray()

        assertEquals(out1.size, out2.size)
        for (i in out1.indices) {
            assertEquals(out1[i], out2[i], 1e-4f)
        }
    }

    @Test
    fun resampler_identity() {
        val rate = 16000
        val input = FloatArray(1000) { i -> sin(2.0 * PI * 440.0 * i / rate).toFloat() }
        val resampler = Resampler(rate, rate)
        val out = concat(resampler.process(input), resampler.flush())
        assertArrayEquals(input, out, 1e-6f)
    }

    @Test
    fun resampler_outputLength() {
        val inRate = 44100
        val outRate = 16000
        val n = 12345
        val input = FloatArray(n) { 0.5f }
        val resampler = Resampler(inRate, outRate)
        val out = concat(resampler.process(input), resampler.flush())
        val expected = round(n * outRate.toDouble() / inRate).toInt()
        assertEquals(expected, out.size)
    }
}
