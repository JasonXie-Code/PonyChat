package top.ponychat.webview.ui.chat

import android.content.Context
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.local.LocalHistoryImageStore
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.SearchMessageResult

/** Restore phone-only uploads after the server returns its text-only history. */
internal fun List<SearchMessageResult>.withLocalHistoryImages(
    context: Context, username: String, characterId: String
): List<SearchMessageResult> {
    if (isEmpty() || username.isBlank() || characterId.isBlank()) return this
    val cache = LocalCacheStore(context)
    val index = LocalHistoryImageStore(context)
    val imagesByConversation = map { it.conversationId }.distinct().filter { it.isNotBlank() }
        .associateWith { conversation ->
            cache.loadConversation(username, characterId, "normal", conversation)
                ?.takeIf { it.conversationId == conversation }
                ?.let { index.record(username, characterId, conversation, it.messages) }
            val hidden = cache.loadLocallyHiddenMessageIds(username, characterId, "normal", conversation)
            index.read(username, characterId, conversation)
                .filter { it.messageId !in hidden }.associateBy { it.messageId }
        }
    return map { row ->
        val urls = imagesByConversation[row.conversationId]?.get(row.messageId)?.urls.orEmpty()
        fun imageKey(url: String) = localUrlForRemoteChatImage(context, url) ?: url
        val existing = row.historyImageUrls(context).map(::imageKey).toSet()
        val restored = urls.distinctBy(::imageKey).filter { imageKey(it) !in existing }.map {
            MessageAttachment(type = "image", url = it, name = "图片")
        }
        if (restored.isEmpty()) row else row.copy(attachments = row.attachments.orEmpty() + restored)
    }
}
