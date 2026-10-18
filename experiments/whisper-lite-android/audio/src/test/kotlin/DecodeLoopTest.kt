package app.whisperlite.audio

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.util.ArrayDeque
import java.util.concurrent.CancellationException
import org.junit.Assert.*
import org.junit.Test

/** No Android types: finite input slots, scripted output, and observable buffer ownership. */
internal class FakeCodec : DecodeCodec {
    val events = ArrayDeque<CodecEvent>()
    val formats = ArrayDeque<PcmFormat>()
    val buffers = mutableMapOf<Int, ByteBuffer>()
    val queued = mutableListOf<Triple<Int, Long, Boolean>>()
    val released = mutableListOf<Int>()
    val retrieved = mutableListOf<Int>()
    val timeouts = mutableListOf<Long>()
    val operations = mutableListOf<String>()
    var inputSlots = 1
    var currentFormat = PcmFormat(16000, 1, PcmEncoding.SIGNED_16)
    var getFailure: Throwable? = null
    var releaseFailure: Throwable? = null
    var outputPolls = 0
    private var nextInput = 0

    override fun dequeueInput(timeoutUs: Long): CodecInput? {
        timeouts.add(timeoutUs)
        operations.add("input")
        if (inputSlots-- <= 0) return null
        return CodecInput(nextInput++, ByteBuffer.allocate(32).apply { limit(0) })
    }

    override fun queueInput(index: Int, size: Int, presentationTimeUs: Long, endOfStream: Boolean) {
        queued.add(Triple(size, presentationTimeUs, endOfStream))
        operations.add("queued")
    }

    override fun dequeueOutput(timeoutUs: Long): CodecEvent {
        timeouts.add(timeoutUs)
        operations.add("output")
        outputPolls++
        return events.poll() ?: CodecEvent.TryAgain
    }

    override fun outputFormat(): PcmFormat {
        formats.poll()?.let { currentFormat = it }
        return currentFormat
    }

    override fun outputBuffer(index: Int): ByteBuffer? {
        retrieved.add(index)
        getFailure?.let { throw it }
        return buffers[index]
    }

    override fun releaseOutput(index: Int) {
        released.add(index)
        releaseFailure?.let { throw it }
    }

    fun pcm(index: Int, bytes: ByteArray, timeUs: Long = 0, eos: Boolean = false) {
        buffers[index] = ByteBuffer.wrap(bytes)
        events.add(CodecEvent.Output(index, 0, bytes.size, timeUs, endOfStream = eos))
    }
}

class DecodeLoopTest {
    private fun run(
        codec: FakeCodec,
        source: EncodedSource = EncodedSource { null },
        output: ByteArrayOutputStream = ByteArrayOutputStream(),
        progress: (Float) -> Unit = {},
        cancelled: () -> Boolean = { false },
        time: () -> Long = { 0L },
        wait: () -> Unit = { fail("Should drain ready buffers before waiting") }
    ): Long = DecodeLoop(codec, source, PcmPipeline(Pcm16Writer(output)),
        ProgressTracker(1_000_000), progress, cancelled, time, wait, 3_000_000_000L).run()

    @Test
    fun drainsAllInputAndOutputWithoutPerPacketWaits() {
        val codec = FakeCodec()
        codec.inputSlots = 4
        codec.events.add(CodecEvent.TryAgain)
        codec.events.add(CodecEvent.FormatChanged)
        codec.events.add(CodecEvent.BuffersChanged)
        codec.pcm(0, byteArrayOf(1, 0))
        codec.pcm(1, byteArrayOf(2, 0), eos = true)
        var packets = 0
        val result = run(codec, EncodedSource { target ->
            assertEquals(0, target.position())
            assertEquals(target.capacity(), target.limit())
            if (packets++ < 3) { target.put(7); InputPacket(1, 10) } else null
        })
        assertEquals(2L, result)
        assertEquals(4, codec.queued.size)
        assertTrue(codec.queued.last().third)
        assertEquals(listOf("input", "queued", "input", "queued", "input", "queued", "input", "queued", "output"),
            codec.operations.take(9))
        assertEquals(listOf(0, 1), codec.released)
        assertTrue(codec.timeouts.isNotEmpty() && codec.timeouts.all { it == 0L })
    }

    @Test
    fun clampsNegativeAndRegressingInputTimestampsAndUsesLastForEos() {
        val codec = FakeCodec()
        codec.inputSlots = 4
        codec.events.add(CodecEvent.Output(0, 0, 0, 0, endOfStream = true))
        val times = ArrayDeque(listOf(-1L, 20L, -4L))
        run(codec, EncodedSource { if (times.isEmpty()) null else InputPacket(1, times.remove()) })
        assertEquals(listOf(0L, 20L, 20L, 20L), codec.queued.map { it.second })
        assertEquals(listOf(false, false, false, true), codec.queued.map { it.third })
        assertTrue(codec.retrieved.isEmpty())
        assertEquals(listOf(0), codec.released)
    }

    @Test
    fun nonemptyZeroTimestampEosIsWrittenAndDoesNotRegressProgress() {
        val codec = FakeCodec()
        codec.pcm(0, byteArrayOf(1, 0), 500_000)
        codec.pcm(1, byteArrayOf(2, 0), 0, true)
        val bytes = ByteArrayOutputStream()
        val values = mutableListOf<Float>()
        assertEquals(2L, run(codec, output = bytes, progress = { values.add(it) }))
        assertArrayEquals(byteArrayOf(1, 0, 2, 0), bytes.toByteArray())
        assertEquals(listOf(0.5f), values)
        assertEquals(listOf(0, 1), codec.released)
    }

    @Test
    fun skipsConfigAndClearsOldLimitBeforeApplyingOffset() {
        val codec = FakeCodec()
        codec.events.add(CodecEvent.Output(0, 999, 100, 999, codecConfig = true))
        codec.buffers[1] = ByteBuffer.wrap(byteArrayOf(99, 99, 99, 99, 1, 0, 2, 0, 99)).apply { limit(1) }
        codec.events.add(CodecEvent.Output(1, 4, 4, 0, endOfStream = true))
        val bytes = ByteArrayOutputStream()
        assertEquals(2L, run(codec, output = bytes))
        assertArrayEquals(byteArrayOf(1, 0, 2, 0), bytes.toByteArray())
        assertEquals(listOf(1), codec.retrieved)
        assertEquals(listOf(0, 1), codec.released)
    }

    @Test
    fun handlesMultipleFormatChangesAndMissingInitialFormatEvent() {
        val codec = FakeCodec()
        codec.formats.add(PcmFormat(8000, 1, PcmEncoding.SIGNED_16))
        codec.formats.add(PcmFormat(16000, 2, PcmEncoding.UNSIGNED_8))
        codec.pcm(0, ByteArray(160))
        codec.events.add(CodecEvent.FormatChanged)
        codec.pcm(1, byteArrayOf(-1, -1, 0, 0), eos = true)
        val bytes = ByteArrayOutputStream()
        assertEquals(162L, run(codec, output = bytes))
        assertEquals(324, bytes.size())
        assertArrayEquals(byteArrayOf(-1, 127, 0, -128), bytes.toByteArray().takeLast(4).toByteArray())
    }

    @Test
    fun missingOutputEosTimesOutAfterIdleWaits() {
        val codec = FakeCodec()
        codec.pcm(0, byteArrayOf(1, 0))
        var now = 0L
        var waits = 0
        val failure = assertThrows(IOException::class.java) {
            run(codec, time = { now }, wait = { waits++; now += 1_000_000_000L })
        }
        assertTrue(failure.message!!.contains("after input EOS"))
        assertEquals(3, waits)
        assertTrue(codec.outputPolls <= 5)
        assertEquals(listOf(0), codec.released)
    }

    @Test
    fun onlyWaitsWhenBothSidesAreUnavailable() {
        val codec = FakeCodec()
        codec.events.add(CodecEvent.FormatChanged)
        var waits = 0
        val samples = run(codec, wait = {
            waits++
            assertEquals(3, codec.outputPolls)
            codec.pcm(1, byteArrayOf(0, 0), eos = true)
        })
        assertEquals(1L, samples)
        assertEquals(1, waits)
    }

    @Test
    fun releaseHappensForInvalidRangeMissingBufferAndGetterFailure() {
        for (scenario in 0..2) {
            val codec = FakeCodec()
            codec.pcm(7, byteArrayOf(1, 0), eos = true)
            if (scenario == 0) {
                codec.events.clear()
                codec.events.add(CodecEvent.Output(7, 3, 2, 0))
            }
            if (scenario == 1) codec.buffers.clear()
            if (scenario == 2) codec.getFailure = IOException("get buffer")
            assertThrows(Exception::class.java) { run(codec) }
            assertEquals(listOf(7), codec.released)
        }
    }

    @Test
    fun cancellationFromCallbackSurvivesReleaseFailure() {
        val codec = FakeCodec()
        codec.pcm(7, byteArrayOf(1, 0), 500_000)
        codec.releaseFailure = IOException("release")
        val cancellation = CancellationException("observer cancelled")
        val failure = assertThrows(CancellationException::class.java) {
            run(codec, progress = { throw cancellation })
        }
        assertSame(cancellation, failure)
        assertEquals("release", failure.suppressed.single().message)
        assertEquals(listOf(7), codec.released)
    }

    @Test
    fun cancellationFlagIsCheckedWhileDrainingAndSourceExceptionsPropagate() {
        val codec = FakeCodec()
        codec.inputSlots = 10
        var cancelled = false
        assertThrows(CancellationException::class.java) {
            run(codec, EncodedSource { cancelled = true; InputPacket(1, 0) }, cancelled = { cancelled })
        }
        assertEquals(1, codec.queued.size)
        val failure = CancellationException("source cancelled")
        assertSame(failure, assertThrows(CancellationException::class.java) {
            run(FakeCodec(), EncodedSource { throw failure })
        })
    }

    @Test
    fun interruptedIdleWaitBecomesCancellationAndKeepsInterruptFlag() {
        val codec = FakeCodec()
        try {
            val failure = assertThrows(CancellationException::class.java) {
                run(codec, wait = { throw InterruptedException("interrupted") })
            }
            assertTrue(failure.cause is InterruptedException)
            assertTrue(Thread.currentThread().isInterrupted)
        } finally {
            Thread.interrupted()
        }
    }

    @Test
    fun configStormCannotHideMissingEos() {
        val codec = FakeCodec()
        repeat(100) { codec.events.add(CodecEvent.Output(it, 0, 1, 0, codecConfig = true)) }
        var now = 0L
        assertThrows(IOException::class.java) { run(codec, time = { now.also { now += 100_000_000L } }) }
        assertTrue(codec.released.isNotEmpty())
        assertTrue(codec.released.size < 100)
        assertTrue(codec.retrieved.isEmpty())
    }
}
