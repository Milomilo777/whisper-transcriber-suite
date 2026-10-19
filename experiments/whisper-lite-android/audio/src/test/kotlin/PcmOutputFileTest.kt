package app.whisperlite.audio

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.util.concurrent.CancellationException
import java.util.UUID
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class PcmOutputFileTest {
    @get:Rule val temporary = TemporaryFolder(File("target"))

    @Test
    fun closePrecedesDeleteOnCancellation() {
        val events = mutableListOf<String>()
        val cancellation = CancellationException("cancelled")
        val output = object : ByteArrayOutputStream() {
            override fun close() { events.add("close") }
        }
        val actual = assertThrows(CancellationException::class.java) {
            withOutputTransaction({ output }, { events.add("delete") }) { throw cancellation }
        }
        assertSame(cancellation, actual)
        assertEquals(listOf("close", "delete"), events)
    }

    @Test
    fun writeAndCloseFailuresStillCloseThenDelete() {
        for (failOnWrite in listOf(true, false)) {
            val events = mutableListOf<String>()
            val output = object : OutputStream() {
                override fun write(value: Int) { if (failOnWrite) throw IOException("write") }
                override fun close() { events.add("close"); throw IOException("close") }
            }
            val failure = assertThrows(IOException::class.java) {
                withOutputTransaction({ output }, { events.add("delete") }) { it.write(1) }
            }
            assertEquals(if (failOnWrite) "write" else "close", failure.message)
            if (failOnWrite) assertEquals("close", failure.suppressed.single().message)
            assertEquals(listOf("close", "delete"), events)
        }
    }

    @Test
    fun openAndCleanupFailuresPreserveTheOriginalException() {
        val failure = IOException("open")
        val actual = assertThrows(IOException::class.java) {
            withOutputTransaction({ throw failure }, { throw IOException("delete") }) { fail("Must not run") }
        }
        assertSame(failure, actual)
        assertEquals("delete", actual.suppressed.single().message)
    }

    @Test
    fun successClosesBeforeReturningAndNeverDeletes() {
        val events = mutableListOf<String>()
        val output = object : ByteArrayOutputStream() {
            override fun close() { events.add("close") }
        }
        val value = withOutputTransaction({ output }, { fail("Successful output must survive") }) {
            it.write(byteArrayOf(1, 2))
            7
        }
        events.add("return")
        assertEquals(7, value)
        assertArrayEquals(byteArrayOf(1, 2), output.toByteArray())
        assertEquals(listOf("close", "return"), events)
    }

    @Test
    fun relativeNestedOutputCreatesParentsAndFlushesBufferedTail() {
        val file = File(temporary.root, "nested/deeper/out.pcm")
        assertFalse(file.parentFile.exists())
        writePcmFile(file, 0, -1) { it.write(floatArrayOf(1f, -1f)) }
        assertArrayEquals(byteArrayOf(-1, 127, 0, -128), file.readBytes())
    }

    @Test
    fun realPartialFileIsDeletedAndExistingResultsSurvive() {
        val file = File(temporary.root, "out.pcm")
        assertThrows(CancellationException::class.java) {
            writePcmFile(file, 0, -1) {
                it.write(floatArrayOf(1f))
                throw CancellationException("cancelled")
            }
        }
        assertFalse(file.exists())
        file.writeBytes(byteArrayOf(5, 6))
        assertThrows(IOException::class.java) { writePcmFile(file, 0, -1) { fail("Existing file must not open") } }
        assertArrayEquals(byteArrayOf(5, 6), file.readBytes())
    }

    @Test
    fun bareRelativeOutputUsesTheWorkingDirectoryForSpaceChecks() {
        val file = File("whisper-lite-test-${UUID.randomUUID()}.pcm")
        assertNull(file.parentFile)
        try {
            writePcmFile(file, 0, -1) { it.write(floatArrayOf(0f)) }
            assertArrayEquals(byteArrayOf(0, 0), file.readBytes())
        } finally {
            if (file.exists()) assertTrue(file.delete())
        }
    }

    @Test
    fun impossibleSpaceEstimateFailsBeforeCreatingTheFile() {
        val file = File(temporary.root, "out.pcm")
        assertThrows(IOException::class.java) {
            writePcmFile(file, 0, Long.MAX_VALUE) { fail("No output should open") }
        }
        assertFalse(file.exists())
    }
}
