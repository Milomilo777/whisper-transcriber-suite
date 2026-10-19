package app.whisperlite.audio

/** Completion is reserved for the caller after the output has been closed successfully. */
class ProgressTracker(
    private val durationUs: Long,
    private val minDelta: Float = 0.01f,
    private val minIntervalNanos: Long = 100_000_000L
) {
    init {
        require(minDelta > 0f && minDelta <= 1f)
        require(minIntervalNanos >= 0)
    }

    private var presentationTimeUs = 0L
    private var lastValue = 0f
    private var lastEmissionNanos: Long? = null

    fun update(timeUs: Long, nowNanos: Long): Float? {
        presentationTimeUs = maxOf(presentationTimeUs, timeUs)
        if (durationUs <= 0 || lastValue == 1f) return null
        val value = (presentationTimeUs.toDouble() / durationUs).coerceIn(0.0, 0.99).toFloat()
        val last = lastEmissionNanos
        if (value - lastValue < minDelta || (last != null && nowNanos - last < minIntervalNanos)) return null
        lastValue = value
        lastEmissionNanos = nowNanos
        return value
    }

    fun complete(): Float? {
        if (lastValue == 1f) return null
        lastValue = 1f
        return 1f
    }
}
