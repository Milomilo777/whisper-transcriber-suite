package app.whisperlite.audio

import org.junit.Assert.*
import org.junit.Test

class ProgressTrackerTest {
    @Test
    fun negativeRegressingAndZeroEosTimestampsNeverRegress() {
        val progress = ProgressTracker(1_000_000)
        assertNull(progress.update(-1, 0))
        assertEquals(0.25f, progress.update(250_000, 0))
        assertNull(progress.update(0, 100_000_000))
        assertNull(progress.update(100_000, 200_000_000))
        assertEquals(0.5f, progress.update(500_000, 300_000_000))
        assertNull(progress.update(0, 400_000_000))
        assertEquals(1f, progress.complete())
    }

    @Test
    fun throttleRequiresBothTimeAndMeaningfulDelta() {
        val progress = ProgressTracker(1_000_000)
        assertEquals(0.1f, progress.update(100_000, 0))
        assertNull(progress.update(500_000, 99_999_999))
        assertEquals(0.5f, progress.update(500_000, 100_000_000))
        assertNull(progress.update(505_000, 200_000_000))
        assertEquals(0.6f, progress.update(600_000, 200_000_000))
    }

    @Test
    fun manyUpdatesAreBoundedAndStrictlyIncreasing() {
        val tracker = ProgressTracker(1_000_000)
        val values = (0..1000).mapNotNull { tracker.update(it * 1000L, it * 1_000_000L) }
        assertTrue(values.isNotEmpty())
        assertTrue(values.size <= 11)
        assertTrue(values.zipWithNext().all { (a, b) -> b > a && b - a >= 0.01f })
        assertTrue(values.all { it < 1f })
    }

    @Test
    fun unknownDurationOnlyReportsCompletionOnce() {
        val tracker = ProgressTracker(-1)
        assertNull(tracker.update(Long.MAX_VALUE, 0))
        assertEquals(1f, tracker.complete())
        assertNull(tracker.complete())
        assertNull(tracker.update(Long.MAX_VALUE, 1_000_000_000))
    }

    @Test
    fun fullDurationIsCappedUntilOutputIsCommitted() {
        val tracker = ProgressTracker(1)
        assertEquals(0.99f, tracker.update(Long.MAX_VALUE, 0))
        assertEquals(1f, tracker.complete())
        assertNull(tracker.update(0, 1_000_000_000))
    }
}
