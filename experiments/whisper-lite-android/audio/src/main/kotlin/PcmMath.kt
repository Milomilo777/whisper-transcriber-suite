package app.whisperlite.audio

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.round
import kotlin.math.sin

fun downmixToMono(interleaved: FloatArray, channels: Int): FloatArray {
    require(channels >= 1) { "channels must be >= 1" }
    require(interleaved.size % channels == 0) { "Buffer must contain complete channel frames" }
    if (channels == 1) return interleaved.copyOf()
    val frames = interleaved.size / channels
    val mono = FloatArray(frames)
    var idx = 0
    for (i in 0 until frames) {
        var sum = 0f
        for (c in 0 until channels) {
            sum += interleaved[idx++]
        }
        mono[i] = sum / channels
    }
    return mono
}

/** Streaming channel framing; an incomplete final frame is malformed PCM. */
class Downmixer(private val channels: Int) {
    init {
        require(channels >= 1) { "channels must be >= 1" }
    }

    private val remainder = FloatArray(channels)
    private var count = 0

    fun process(interleaved: FloatArray): FloatArray {
        val mono = FloatArray((count + interleaved.size) / channels)
        var output = 0
        for (sample in interleaved) {
            remainder[count++] = sample
            if (count == channels) {
                var sum = 0f
                for (value in remainder) sum += value
                mono[output++] = sum / channels
                count = 0
            }
        }
        return mono
    }

    fun finish() {
        require(count == 0) { "Incomplete channel frame: $count of $channels samples" }
    }
}

fun pcm16ToFloat(src: ShortArray): FloatArray {
    val dst = FloatArray(src.size)
    for (i in src.indices) {
        val s = src[i].toInt()
        dst[i] = if (s >= 0) s / 32767f else s / 32768f
    }
    return dst
}

fun floatToPcm16(src: FloatArray): ShortArray {
    val dst = ShortArray(src.size)
    for (i in src.indices) {
        val v = src[i].coerceIn(-1f, 1f)
        val scaled = if (v >= 0f) v * 32767f else v * 32768f
        val rounded = if (scaled >= 0f) floor(scaled + 0.5f) else ceil(scaled - 0.5f)
        dst[i] = rounded.toInt().coerceIn(-32768, 32767).toShort()
    }
    return dst
}

class Resampler(private val inRate: Int, private val outRate: Int = 16000) {
    init {
        require(inRate > 0 && outRate > 0) { "Rates must be positive" }
    }

    private val passthrough = inRate == outRate
    private val fc = 0.5 * min(1.0, outRate.toDouble() / inRate)
    private val twoFc = 2.0 * fc
    private val radius = if (passthrough) 0 else max(16.0, ceil(16.0 / twoFc)).toInt()
    private val numTaps = 2 * radius + 1

    private val inRateStep: Long
    private val outRateStep: Long
    private val polyphaseTable: FloatArray?

    private var historyBuffer = FloatArray(1024)
    private var historyStart = 0
    private var historyCount = 0
    private var inputBase = 0L
    private var nextOutput = 0L
    private var totalInputCount = 0L
    private var outBuffer = FloatArray(1024)

    init {
        if (passthrough) {
            inRateStep = 1L
            outRateStep = 1L
            polyphaseTable = null
        } else {
            val g = gcd(inRate.toLong(), outRate.toLong())
            val iStep = inRate.toLong() / g
            val oStep = outRate.toLong() / g
            inRateStep = iStep
            outRateStep = oStep
            val maxFloats = 2_000_000L
            if (oStep <= maxFloats / numTaps) {
                val table = FloatArray((oStep * numTaps).toInt())
                for (r in 0 until oStep.toInt()) {
                    val frac = r.toDouble() / oStep
                    val polyOffset = r * numTaps
                    for (k in 0 until numTaps) {
                        val tapK = k - radius
                        val x = frac - tapK
                        val absX = abs(x)
                        val tap = if (absX > radius) {
                            0.0
                        } else {
                            val w = 0.42 + 0.5 * cos(PI * x / radius) + 0.08 * cos(2.0 * PI * x / radius)
                            val sincVal = if (x == 0.0) 1.0 else sin(PI * twoFc * x) / (PI * twoFc * x)
                            twoFc * sincVal * w
                        }
                        table[polyOffset + k] = tap.toFloat()
                    }
                }
                polyphaseTable = table
            } else {
                polyphaseTable = null
            }
        }
    }

    private fun gcd(a: Long, b: Long): Long {
        var x = a
        var y = b
        while (y != 0L) {
            val t = x % y
            x = y
            y = t
        }
        return x
    }

    fun process(input: FloatArray): FloatArray {
        if (passthrough) return input.copyOf()
        if (input.isEmpty()) return FloatArray(0)

        val neededCap = historyCount + input.size
        if (neededCap > historyBuffer.size) {
            var newCap = historyBuffer.size * 2
            while (newCap < neededCap) newCap *= 2
            val newBuf = FloatArray(newCap)
            if (historyCount > 0) {
                System.arraycopy(historyBuffer, historyStart, newBuf, 0, historyCount)
            }
            historyBuffer = newBuf
            historyStart = 0
        } else if (historyStart > 0 && historyStart + historyCount + input.size > historyBuffer.size) {
            System.arraycopy(historyBuffer, historyStart, historyBuffer, 0, historyCount)
            historyStart = 0
        }

        System.arraycopy(input, 0, historyBuffer, historyStart + historyCount, input.size)
        historyCount += input.size
        totalInputCount = inputBase + historyCount

        var outCount = 0
        while (true) {
            val t = nextOutput.toDouble() * inRate / outRate
            val neededEnd = floor(t + radius).toLong()
            if (neededEnd < totalInputCount) {
                if (outCount == outBuffer.size) {
                    outBuffer = outBuffer.copyOf(outBuffer.size * 2)
                }
                outBuffer[outCount++] = computeSample(nextOutput)
                nextOutput++
            } else break
        }
        trim()
        return outBuffer.copyOf(outCount)
    }

    fun flush(): FloatArray {
        if (passthrough) return FloatArray(0)
        if (totalInputCount == 0L) return FloatArray(0)
        val totalOutput = round(totalInputCount.toDouble() * outRate / inRate).toLong()
        val numOut = (totalOutput - nextOutput).toInt().coerceAtLeast(0)
        val result = FloatArray(numOut)
        for (i in 0 until numOut) {
            result[i] = computeSample(nextOutput)
            nextOutput++
        }
        historyStart = 0
        historyCount = 0
        inputBase = 0L
        nextOutput = 0L
        totalInputCount = 0L
        return result
    }

    private fun computeSample(m: Long): Float {
        return if (polyphaseTable != null) {
            computeSamplePolyphase(m)
        } else {
            computeSampleDirect(m)
        }
    }

    private fun computeSamplePolyphase(m: Long): Float {
        val mStep = m * inRateStep
        val q = mStep / outRateStep
        val r = (mStep % outRateStep).toInt()
        val iStart = q - radius
        val iEnd = q + radius
        val table = polyphaseTable!!
        val polyOffset = r * numTaps
        val baseIdx = (q - inputBase).toInt()

        var sum = 0.0
        if (iStart >= 0 && iEnd < totalInputCount) {
            val bufStart = historyStart + baseIdx - radius
            for (k in 0 until numTaps) {
                sum += historyBuffer[bufStart + k] * table[polyOffset + k]
            }
        } else {
            for (k in 0 until numTaps) {
                val i = iStart + k
                if (i in 0 until totalInputCount) {
                    val idx = baseIdx - radius + k
                    if (idx in 0 until historyCount) {
                        sum += historyBuffer[historyStart + idx] * table[polyOffset + k]
                    }
                }
            }
        }
        return sum.toFloat()
    }

    private fun computeSampleDirect(m: Long): Float {
        val t = m.toDouble() * inRate / outRate
        val iStart = floor(t - radius).toLong()
        val iEnd = floor(t + radius).toLong()
        var sum = 0.0
        for (i in iStart..iEnd) {
            val sample = if (i < 0 || i >= totalInputCount) {
                0.0
            } else {
                val idx = (i - inputBase).toInt()
                if (idx in 0 until historyCount) historyBuffer[historyStart + idx].toDouble() else 0.0
            }
            val x = t - i
            val absX = abs(x)
            if (absX > radius) continue
            val w = 0.42 + 0.5 * cos(PI * x / radius) + 0.08 * cos(2.0 * PI * x / radius)
            val sincVal = if (x == 0.0) 1.0 else sin(PI * twoFc * x) / (PI * twoFc * x)
            sum += sample * twoFc * sincVal * w
        }
        return sum.toFloat()
    }

    private fun trim() {
        if (historyCount == 0) return
        val tNext = nextOutput.toDouble() * inRate / outRate
        val minIndex = floor(tNext - radius).toLong() - 1
        if (minIndex > inputBase) {
            val drop = (minIndex - inputBase).toInt()
            if (drop > 0 && drop <= historyCount) {
                historyStart += drop
                historyCount -= drop
                inputBase += drop
            }
        }
        if (historyCount == 0) {
            historyStart = 0
        } else if (historyStart >= 1024 || historyStart + historyCount + 1024 > historyBuffer.size) {
            System.arraycopy(historyBuffer, historyStart, historyBuffer, 0, historyCount)
            historyStart = 0
        }
    }
}
