package top.ponychat.webview.ui.chat

import android.content.Context
import top.ponychat.webview.data.model.SearchMessageResult

internal fun SearchMessageResult.historyImageUrls(context: Context? = null): List<String> {
    val media = if (role == "user") splitUserMessageMedia(content, context) else splitMessageMedia(content, context)
    return (media.imageUrls + attachments.orEmpty()
        .filter { it.type in setOf("image", "sticker", "emoji_asset") }
        .mapNotNull(::stickerPreviewUrl)).filter { it.isNotBlank() }.distinct()
}

internal fun SearchMessageResult.matchesHistoryContent(filter: String, context: Context? = null): Boolean =
    when (filter) {
        "image" -> historyImageUrls(context).isNotEmpty()
        "text" -> {
            val media = if (role == "user") splitUserMessageMedia(content, context) else splitMessageMedia(content, context)
            media.text.trim().let { it.isNotBlank() && it !in setOf("[图片]", "【图片】", "[表情]", "【表情】") }
        }
        else -> true
    }
