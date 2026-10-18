package app.whisperlite.audio

import java.io.File
import java.nio.ByteOrder

sealed interface DecodeResult {
    data class Ok(val samples: Long, val durationSec: Double) : DecodeResult
    data class Failed(val reason: String) : DecodeResult
}

/** Completion callbacks run only after all PCM and buffered bytes have closed successfully. */
fun decodeToPcmFile(
    codec: DecodeCodec,
    source: EncodedSource,
    out: File,
    durationUs: Long,
    sourceBytes: Long,
    onProgress: (Float) -> Unit,
    isCancelled: () -> Boolean,
    byteOrder: ByteOrder = ByteOrder.LITTLE_ENDIAN
): DecodeResult.Ok {
    val progress = ProgressTracker(durationUs)
    val samples = writePcmFile(out, durationUs, sourceBytes) { writer ->
        DecodeLoop(codec, source, PcmPipeline(writer, byteOrder), progress, onProgress, isCancelled).run()
    }
    progress.complete()?.let(onProgress)
    return DecodeResult.Ok(samples, samples / 16000.0)
}
