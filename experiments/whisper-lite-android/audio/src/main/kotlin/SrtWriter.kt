package app.whisperlite.audio

data class Segment(val startMs: Long, val endMs: Long, val text: String)

fun toSrt(segments: List<Segment>): String {
    val sb = StringBuilder()
    var index = 1
    for (seg in segments) {
        val text = seg.text.trim()
        if (text.isEmpty()) continue
        val start = seg.startMs.coerceAtLeast(0)
        val end = seg.endMs.coerceAtLeast(start + 1)
        sb.append(index).append('\n')
        sb.append(formatTime(start)).append(" --> ").append(formatTime(end)).append('\n')
        sb.append(text).append('\n')
        sb.append('\n')
        index++
    }
    return sb.toString()
}

private fun formatTime(ms: Long): String {
    val hours = ms / 3600000
    val minutes = (ms % 3600000) / 60000
    val seconds = (ms % 60000) / 1000
    val millis = ms % 1000
    return "%02d:%02d:%02d,%03d".format(hours, minutes, seconds, millis)
}
