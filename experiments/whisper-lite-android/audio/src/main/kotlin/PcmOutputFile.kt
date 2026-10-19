package app.whisperlite.audio

import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream

/** Owns only newly created output, preserving any existing result at the requested path. */
fun <T> writePcmFile(
    out: File,
    durationUs: Long,
    sourceBytes: Long,
    space: SpaceEstimator = SpaceEstimator(),
    work: (Pcm16Writer) -> T
): T {
    val file = out.absoluteFile
    val parent = file.parentFile ?: throw IOException("Output has no parent directory")
    if (!parent.isDirectory && !parent.mkdirs() && !parent.isDirectory) {
        throw IOException("Cannot create output directory")
    }
    space.requireInitialSpace(parent.usableSpace, durationUs, sourceBytes)
    if (!file.createNewFile()) throw IOException("Output already exists")
    val bufferSize = 64 * 1024
    return withOutputTransaction(
        open = { BufferedOutputStream(FileOutputStream(file), bufferSize) },
        deletePartial = { if (file.exists() && !file.delete()) throw IOException("Cannot delete partial output") }
    ) { output ->
        work(Pcm16Writer(output) { bytes ->
            // Include the entire userspace buffer in case its pending bytes are not
            // reflected in usableSpace yet. Zero available bytes always fails.
            space.requireWriteSpace(parent.usableSpace, bytes.toLong() + bufferSize)
        })
    }
}

/** use() closes before the failure cleanup, including cancellation and close failures. */
fun <T> withOutputTransaction(
    open: () -> OutputStream,
    deletePartial: () -> Unit,
    work: (OutputStream) -> T
): T {
    try {
        return open().use(work)
    } catch (failure: Throwable) {
        try { deletePartial() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
        throw failure
    }
}
