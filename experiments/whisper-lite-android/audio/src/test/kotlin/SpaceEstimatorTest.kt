package app.whisperlite.audio

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class SpaceEstimatorTest {
    private val space = SpaceEstimator()

    @Test
    fun durationUses16kMonoPcm16AndRoundsUp() {
        assertEquals(space.reserveBytes + 35_200, space.initialRequiredBytes(1_000_000, 0))
        assertEquals(space.reserveBytes + 17_600, space.initialRequiredBytes(500_000, 0))
        assertEquals(space.reserveBytes + 1, space.initialRequiredBytes(1, 0))
        assertEquals(space.reserveBytes + 70_401, space.initialRequiredBytes(2_000_001, Long.MAX_VALUE))
    }

    @Test
    fun unknownDurationUsesSourceLengthOrAnUnconditionalFloor() {
        assertEquals(space.reserveBytes + 16_000_000, space.initialRequiredBytes(0, 2_000_000))
        assertEquals(space.reserveBytes + 1024 * 1024, space.initialRequiredBytes(0, -1))
        assertEquals(space.reserveBytes + 1024 * 1024, space.initialRequiredBytes(-1, 0))
        assertThrows(IOException::class.java) { space.requireInitialSpace(0, 0, -1) }
        assertThrows(IOException::class.java) { space.requireInitialSpace(space.reserveBytes, 0, -1) }
    }

    @Test
    fun zeroAndFallingFreeSpaceFailDuringWrites() {
        val needed = space.reserveBytes + 100
        space.requireWriteSpace(needed, 100)
        assertThrows(IOException::class.java) { space.requireWriteSpace(needed - 1, 100) }
        assertThrows(IOException::class.java) { space.requireWriteSpace(0, 1) }
        assertThrows(IOException::class.java) { space.requireWriteSpace(-1, 1) }
    }

    @Test
    fun estimatesSaturateInsteadOfOverflowing() {
        assertTrue(space.initialRequiredBytes(Long.MAX_VALUE, -1) > space.reserveBytes)
        assertEquals(Long.MAX_VALUE, space.initialRequiredBytes(0, Long.MAX_VALUE))
        assertThrows(IOException::class.java) { space.requireWriteSpace(Long.MAX_VALUE - 1, Long.MAX_VALUE) }
    }

    @Test
    fun initialCheckAcceptsExactlyTheEstimate() {
        val required = space.initialRequiredBytes(1_000_000, -1)
        space.requireInitialSpace(required, 1_000_000, -1)
        assertThrows(IOException::class.java) { space.requireInitialSpace(required - 1, 1_000_000, -1) }
    }
}
