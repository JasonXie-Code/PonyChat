package top.ponychat.webview.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.SearchMessageResult
import top.ponychat.webview.ui.theme.Primary

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun SearchStickerPreviewRow(attachments: List<MessageAttachment>, onClick: (String) -> Unit, onLongClick: () -> Unit) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        attachments.take(3).forEach { att ->
            val stickerUrl = att.stickerPreviewUrl()
            if (!stickerUrl.isNullOrBlank()) {
                AsyncImage(
                    model = rememberThumbnailImageRequest(stickerUrl),
                    contentDescription = att.name.ifBlank { "表情" },
                    contentScale = ContentScale.Fit,
                    modifier = Modifier
                        .size(56.dp)
                        .combinedClickable(onClick = { onClick(stickerUrl) }, onLongClick = onLongClick)
                        .clip(RoundedCornerShape(10.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(0.55f))
                        .padding(3.dp)
                )
            }
        }
    }
}

internal fun SearchMessageResult.searchPreviewText(
    stickerAttachments: List<MessageAttachment>, text: String = content,
): String {
    val raw = text.trim()
    if (stickerAttachments.isEmpty()) return raw
    val label = stickerAttachments.firstNotNullOfOrNull { it.stickerDescriptionText() } ?: "表情包"
    return if (raw.isBlank() || raw == "[表情]" || raw.equals("[sticker]", ignoreCase = true)) {
        "表情包：$label"
    } else {
        raw
    }
}

private fun MessageAttachment.stickerPreviewUrl(): String? =
    url ?: assetId?.let { "/api/admin/assets/$it/file" }
        ?: userStickerId?.let { "/api/assets/stickers/$it/file" }

private fun MessageAttachment.stickerDescriptionText(): String? {
    val direct = name.trim().takeIf { it.isNotBlank() }
    if (direct != null) return direct
    val meta = metadata ?: return null
    fun valueText(key: String): String? {
        val value = meta[key] ?: return null
        return when (value) {
            is String -> value.trim().takeIf { it.isNotBlank() }
            is List<*> -> value.joinToString("、") { it.toString().trim() }.trim().takeIf { it.isNotBlank() }
            else -> value.toString().trim().takeIf { it.isNotBlank() }
        }
    }
    return valueText("intro")
        ?: valueText("detail")
        ?: valueText("image_text")
        ?: valueText("custom_tags")
}

internal fun buildHighlightedText(text: String, keyword: String): androidx.compose.ui.text.AnnotatedString {
    if (keyword.isBlank()) return buildAnnotatedString { append(text) }
    return buildAnnotatedString {
        var start = 0
        val lower = text.lowercase()
        val kw = keyword.trim().lowercase()
        while (start < text.length) {
            val idx = lower.indexOf(kw, start)
            if (idx < 0) {
                append(text.substring(start))
                break
            }
            if (idx > start) append(text.substring(start, idx))
            withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = Primary)) {
                append(text.substring(idx, idx + kw.length))
            }
            start = idx + kw.length
        }
    }
}

internal fun computeDateRange(filter: String): Pair<Long?, Long?> {
    val now = System.currentTimeMillis()
    return when (filter) {
        "today" -> {
            val cal = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, 0)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }
            cal.timeInMillis to now
        }
        "week" -> {
            val cal = Calendar.getInstance().apply {
                set(Calendar.DAY_OF_WEEK, firstDayOfWeek)
                set(Calendar.HOUR_OF_DAY, 0)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }
            cal.timeInMillis to now
        }
        "month" -> {
            val cal = Calendar.getInstance().apply {
                set(Calendar.DAY_OF_MONTH, 1)
                set(Calendar.HOUR_OF_DAY, 0)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }
            cal.timeInMillis to now
        }
        else -> null to null
    }
}

internal fun formatTimestampMs(ms: Long): String {
    if (ms <= 0) return ""
    val diff = System.currentTimeMillis() - ms
    return when {
        diff < 60_000 -> "刚刚"
        diff < 3_600_000 -> "${diff / 60_000} 分钟前"
        diff < 86_400_000 -> "${diff / 3_600_000} 小时前"
        diff < 7L * 86_400_000 -> "${diff / 86_400_000} 天前"
        else -> SimpleDateFormat("yyyy/M/d", Locale.getDefault()).format(Date(ms))
    }
}
