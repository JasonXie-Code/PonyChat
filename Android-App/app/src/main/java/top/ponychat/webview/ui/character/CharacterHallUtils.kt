package top.ponychat.webview.ui.character

import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal fun formatPublishTime(raw: String?): String {
    if (raw.isNullOrBlank()) return "-"
    val instant = parsePublishedInstant(raw) ?: return "-"
    val now = Instant.now()
    val diff = Duration.between(instant, now)
    val minutes = diff.toMinutes()
    val hours = diff.toHours()
    val days = diff.toDays()
    return when {
        minutes < 60 -> "${minutes.coerceAtLeast(1)}分钟前"
        hours < 24 -> "${hours}小时前"
        days < 7 -> "${days}天前"
        else -> DateTimeFormatter.ofPattern("MM-dd")
            .withZone(ZoneId.systemDefault())
            .format(instant)
    }
}

internal fun parsePublishedInstant(raw: String): Instant? {
    return runCatching { Instant.parse(raw) }.getOrNull()
        ?: runCatching {
            LocalDateTime.parse(raw).atZone(ZoneId.systemDefault()).toInstant()
        }.getOrNull()
}
