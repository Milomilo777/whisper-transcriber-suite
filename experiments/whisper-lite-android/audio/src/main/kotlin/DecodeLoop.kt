package app.whisperlite.audio

import java.io.IOException
import java.nio.Buffer
import java.nio.ByteBuffer
import java.util.concurrent.CancellationException

data class CodecInput(val index: Int, val data: ByteBuffer)
data class InputPacket(val size: Int, val presentationTimeUs: Long)

fun interface EncodedSource {
    /** Read one packet and advance, or return null at input EOS. */
    fun read(target: ByteBuffer): InputPacket?
}

sealed interface CodecEvent {
    object TryAgain : CodecEvent
    object FormatChanged : CodecEvent
    object BuffersChanged : CodecEvent
    data class Output(
        val index: Int,
        val offset: Int,
        val size: Int,
        val presentationTimeUs: Long,
        val codecConfig: Boolean = false,
        val endOfStream: Boolean = false
    ) : CodecEvent
}

/** Platform adapter: dequeue calls must honor timeoutUs, including zero (nonblocking). */
interface DecodeCodec {
    fun dequeueInput(timeoutUs: Long): CodecInput?
    fun queueInput(index: Int, size: Int, presentationTimeUs: Long, endOfStream: Boolean)
    fun dequeueOutput(timeoutUs: Long): CodecEvent
    fun outputFormat(): PcmFormat
    fun outputBuffer(index: Int): ByteBuffer?
    fun releaseOutput(index: Int)
}

/** Synchronous worker-thread loop; cancellation exceptions propagate to the caller. */
class DecodeLoop(
    private val codec: DecodeCodec,
    private val source: EncodedSource,
    private val pipeline: PcmPipeline,
    private val progress: ProgressTracker,
    private val onProgress: (Float) -> Unit,
    private val isCancelled: () -> Boolean,
    private val nanoTime: () -> Long = System::nanoTime,
    private val waitForWork: () -> Unit = { Thread.sleep(2) },
    private val stallTimeoutNanos: Long = 5_000_000_000L
) {
    init { require(stallTimeoutNanos > 0) }

    fun run(): Long {
        var inputDone = false
        var outputDone = false
        var lastInputTimeUs = 0L
        var lastActivity = nanoTime()

        fun checkActive() {
            if (isCancelled() || Thread.currentThread().isInterrupted) {
                throw CancellationException("Audio decoding cancelled")
            }
            if (nanoTime() - lastActivity >= stallTimeoutNanos) {
                throw IOException(if (inputDone) "Decoder stalled after input EOS" else "Decoder stalled")
            }
        }

        while (!outputDone) {
            checkActive()
            var madeProgress = false
            while (!inputDone) {
                checkActive()
                val input = codec.dequeueInput(0L) ?: break
                // Use Buffer's original signatures, avoiding Java 9 covariant
                // ByteBuffer methods in this JVM-built module on Android API 26.
                (input.data as Buffer).clear()
                val packet = source.read(input.data)
                if (packet == null) {
                    codec.queueInput(input.index, 0, lastInputTimeUs, true)
                    inputDone = true
                } else {
                    require(packet.size in 0..input.data.capacity()) { "Invalid encoded packet size" }
                    lastInputTimeUs = maxOf(lastInputTimeUs, packet.presentationTimeUs)
                    codec.queueInput(input.index, packet.size, lastInputTimeUs, false)
                }
                lastActivity = nanoTime()
                madeProgress = true
            }
            while (!outputDone) {
                checkActive()
                when (val event = codec.dequeueOutput(0L)) {
                    CodecEvent.TryAgain -> break
                    CodecEvent.FormatChanged -> {
                        pipeline.setFormat(codec.outputFormat())
                        // Repeated format/config events are not PCM activity and must
                        // not keep a decoder without output EOS alive forever.
                        madeProgress = true
                    }
                    CodecEvent.BuffersChanged -> madeProgress = true
                    is CodecEvent.Output -> {
                        var failure: Throwable? = null
                        try {
                            if (!event.codecConfig && event.size > 0) {
                                if (!pipeline.hasFormat) pipeline.setFormat(codec.outputFormat())
                                val buffer = codec.outputBuffer(event.index)
                                    ?: throw IOException("Missing codec output buffer")
                                require(event.offset >= 0 && event.size <= buffer.capacity() - event.offset) {
                                    "Invalid codec output range"
                                }
                                // A reused codec buffer can still have a short old limit.
                                val cursor: Buffer = buffer
                                cursor.clear()
                                cursor.limit(event.offset + event.size)
                                cursor.position(event.offset)
                                pipeline.process(buffer)
                                lastActivity = nanoTime()
                                progress.update(event.presentationTimeUs, lastActivity)?.let(onProgress)
                            } else {
                                require(event.size >= 0) { "Negative codec output size" }
                            }
                        } catch (error: Throwable) {
                            failure = error
                            throw error
                        } finally {
                            try {
                                codec.releaseOutput(event.index)
                            } catch (cleanup: Throwable) {
                                if (failure == null) throw cleanup else failure.addSuppressed(cleanup)
                            }
                        }
                        outputDone = event.endOfStream
                        madeProgress = true
                    }
                }
            }
            if (!outputDone && !madeProgress) {
                try {
                    waitForWork()
                } catch (interrupted: InterruptedException) {
                    Thread.currentThread().interrupt()
                    throw CancellationException("Audio decoding interrupted").apply { initCause(interrupted) }
                }
            }
        }
        checkActive()
        pipeline.finish()
        return pipeline.samplesWritten
    }
}
