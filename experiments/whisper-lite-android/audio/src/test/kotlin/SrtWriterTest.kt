package app.whisperlite.audio

import org.junit.Assert.*
import org.junit.Test

class SrtWriterTest {

    @Test
    fun timestampsOverOneHour() {
        val segments = listOf(
            Segment(0, 1000, "First"),
            Segment(3600000, 3601000, "Second")
        )
        val srt = toSrt(segments)
        val expected = "1\n00:00:00,000 --> 00:00:01,000\nFirst\n\n" +
                "2\n01:00:00,000 --> 01:00:01,000\nSecond\n\n"
        assertEquals(expected, srt)
    }

    @Test
    fun skippedEmptyText() {
        val segments = listOf(
            Segment(0, 1000, "Hello"),
            Segment(1000, 2000, "   "),
            Segment(2000, 3000, "")
        )
        val srt = toSrt(segments)
        val expected = "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        assertEquals(expected, srt)
    }

    @Test
    fun clampedEnd() {
        val segments = listOf(
            Segment(1000, 500, "Clamped")
        )
        val srt = toSrt(segments)
        val expected = "1\n00:00:01,000 --> 00:00:01,001\nClamped\n\n"
        assertEquals(expected, srt)
    }
}
