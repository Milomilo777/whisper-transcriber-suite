package app.whisperlite.audio

import org.junit.Assert.*
import org.junit.Test

class DownmixerTest {
    @Test
    fun stereoCarriesOddChunksIncludingEmptyBuffers() {
        val mixer = Downmixer(2)
        assertArrayEquals(floatArrayOf(0.3f), mixer.process(floatArrayOf(0.2f, 0.4f, -0.2f)), 1e-6f)
        assertEquals(0, mixer.process(floatArrayOf()).size)
        assertArrayEquals(floatArrayOf(-0.3f, 0f), mixer.process(floatArrayOf(-0.4f, 1f, -1f)), 1e-6f)
        mixer.finish()
    }

    @Test
    fun allChunkSizesPreserveMultichannelFrames() {
        val samples = FloatArray(60) { (it - 30) / 30f }
        for (channels in listOf(1, 2, 3, 5)) {
            for (size in 1..11) {
                val mixer = Downmixer(channels)
                val actual = samples.asList().chunked(size).flatMap { mixer.process(it.toFloatArray()).asList() }.toFloatArray()
                assertArrayEquals("channels=$channels chunk=$size", downmixToMono(samples, channels), actual, 1e-6f)
                mixer.finish()
            }
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectInvalidChannels() { Downmixer(0) }

    @Test(expected = IllegalArgumentException::class)
    fun rejectTruncatedFinalFrame() {
        val mixer = Downmixer(2)
        mixer.process(floatArrayOf(1f))
        mixer.finish()
    }

    @Test(expected = IllegalArgumentException::class)
    fun wholeBufferDownmixRejectsPartialFrame() { downmixToMono(floatArrayOf(1f), 2) }
}
