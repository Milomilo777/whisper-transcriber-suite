package app.whisperlite.audio

import java.io.IOException

/** Estimates are conservative heuristics; every streaming write also protects the reserve. */
class SpaceEstimator(val reserveBytes: Long = 8L * 1024 * 1024) {
    init { require(reserveBytes > 0) }

    fun initialRequiredBytes(durationUs: Long, sourceBytes: Long): Long {
        val estimate = if (durationUs > 0) {
            // 16000 mono samples/s * 2 bytes, with 10% headroom; round upward.
            val seconds = durationUs / 1_000_000
            val remainderUs = durationUs % 1_000_000
            add(multiply(seconds, 35_200), (remainderUs * 35_200 + 999_999) / 1_000_000)
        } else {
            // Container length does not bound decompressed audio. Enforce a floor when
            // neither duration nor length is supplied, and keep checking while writing.
            maxOf(1024L * 1024, multiply(sourceBytes.coerceAtLeast(0), 8))
        }
        return add(reserveBytes, estimate)
    }

    fun requireInitialSpace(freeBytes: Long, durationUs: Long, sourceBytes: Long) {
        requireAvailable(freeBytes, initialRequiredBytes(durationUs, sourceBytes))
    }

    fun requireWriteSpace(freeBytes: Long, nextBytes: Long) {
        require(nextBytes >= 0)
        requireAvailable(freeBytes, add(reserveBytes, nextBytes))
    }

    private fun requireAvailable(freeBytes: Long, required: Long) {
        if (freeBytes < required) throw IOException("Not enough free space: need $required bytes, have $freeBytes")
    }

    private fun add(a: Long, b: Long): Long = if (a > Long.MAX_VALUE - b) Long.MAX_VALUE else a + b
    private fun multiply(a: Long, b: Long): Long = if (a > Long.MAX_VALUE / b) Long.MAX_VALUE else a * b
}
