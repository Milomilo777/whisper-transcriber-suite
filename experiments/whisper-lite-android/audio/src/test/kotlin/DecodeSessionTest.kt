package app.whisperlite.audio

import java.io.File
import java.io.IOException
import java.util.concurrent.CancellationException
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class DecodeSessionTest {
    @get:Rule val temporary = TemporaryFolder(File("target"))

    @Test
    fun completionObservesClosedFlushedFileAndCorrectSampleCount() {
        val codec = FakeCodec()
        codec.currentFormat = PcmFormat(8000, 1, PcmEncoding.SIGNED_16)
        codec.pcm(0, ByteArray(160), 0, true)
        val file = File(temporary.root, "out.pcm")
        val progress = mutableListOf<Float>()
        val result = decodeToPcmFile(codec, EncodedSource { null }, file, 10_000, -1, {
            progress.add(it)
            if (it == 1f) {
                assertEquals(320L, file.length())
                // The final sample comes from resampler.flush(), and even the
                // buffered stream's sub-64KB tail must already be on disk.
                assertArrayEquals(ByteArray(320), file.readBytes())
            }
        }, { false })
        assertEquals(DecodeResult.Ok(160, 0.01), result)
        assertEquals(listOf(1f), progress)
        assertEquals(listOf(0), codec.released)
    }

    @Test
    fun cancelledSessionDeletesPartialAndNeverReportsCompletion() {
        val codec = FakeCodec()
        codec.pcm(0, byteArrayOf(1, 0), 500_000)
        val file = File(temporary.root, "out.pcm")
        val cancellation = CancellationException("cancelled by observer")
        val values = mutableListOf<Float>()
        val failure = assertThrows(CancellationException::class.java) {
            decodeToPcmFile(codec, EncodedSource { null }, file, 1_000_000, -1, {
                values.add(it)
                throw cancellation
            }, { false })
        }
        assertSame(cancellation, failure)
        assertEquals(listOf(0.5f), values)
        assertFalse(file.exists())
        assertEquals(listOf(0), codec.released)
    }

    @Test
    fun deliveryFailureAfterCompletionPreservesFinishedWork() {
        for (failure in listOf(IOException("observer failed"), CancellationException("observer cancelled"))) {
            val codec = FakeCodec()
            codec.pcm(0, byteArrayOf(1, 0), eos = true)
            val file = File(temporary.root, "${failure.javaClass.simpleName}.pcm")
            val actual = assertThrows(Exception::class.java) {
                decodeToPcmFile(codec, EncodedSource { null }, file, 0, -1, {
                    assertEquals(1f, it)
                    throw failure
                }, { false })
            }
            assertSame(failure, actual)
            assertArrayEquals(byteArrayOf(1, 0), file.readBytes())
        }
    }

    @Test
    fun malformedPcmDeletesPartialAfterReleasingFinalBuffer() {
        val codec = FakeCodec()
        codec.pcm(7, byteArrayOf(1), eos = true)
        val file = File(temporary.root, "out.pcm")
        assertThrows(IllegalArgumentException::class.java) {
            decodeToPcmFile(codec, EncodedSource { null }, file, 0, -1, { fail("Must not finish") }, { false })
        }
        assertFalse(file.exists())
        assertEquals(listOf(7), codec.released)
    }
}
