package top.ponychat.webview.data.api

import android.content.Context
import android.net.Uri
import android.util.Base64
import java.io.File
import okhttp3.WebSocket
import org.json.JSONArray
import org.json.JSONObject
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.local.LocalHistoryImageStore
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.loadOriginalPreviewBytes

/** Resolve only visible messages in the authenticated account's exact local conversation. */
internal object HistoryImageResponder {
    fun respond(context: Context, request: JSONObject, socket: WebSocket, username: String) {
        val id = request.optString("request_id")
        if (id.length !in 1..128 || username.isBlank()) return
        val result = JSONObject().put("type", "history_image_response").put("request_id", id)
            .put("status", "unavailable")
        try {
            if (AppPreferences(context).username != username) return
            val character = request.optString("character_id")
            val conversation = request.optString("conversation_id")
            if (character.isBlank() || conversation.isBlank()) return
            val cache = LocalCacheStore(context)
            val index = LocalHistoryImageStore(context)
            val cached = cache.loadConversation(username, character, "normal", conversation)
                ?.takeIf { it.conversationId == conversation }
            cached?.let { index.record(username, character, conversation, it.messages) }
            val hidden = cache.loadLocallyHiddenMessageIds(username, character, "normal", conversation)
            val images = index.read(username, character, conversation).filter { it.messageId !in hidden }
                .sortedByDescending { it.timestamp }
            when (request.optString("action")) {
                "list" -> {
                    val offset = request.optInt("offset", 0).coerceAtLeast(0)
                    val limit = request.optInt("limit", 20).coerceIn(1, 40)
                    val page = images.drop(offset).take(limit)
                    result.put("status", "ok").put("has_more", offset.toLong() + page.size < images.size)
                        .put("images", JSONArray().apply {
                            page.forEach { image -> put(JSONObject()
                                .put("message_id", image.messageId).put("image_count", image.urls.size)) }
                        })
                }
                "read" -> {
                    val entry = images.firstOrNull { it.messageId == request.optString("message_id") } ?: return
                    val url = entry.urls.getOrNull(request.optInt("image_index", 1) - 1) ?: return
                    if (url.startsWith("file://")) {
                        val file = File(Uri.parse(url).path ?: return).canonicalFile
                        val root = File(context.filesDir, "chat_images").canonicalFile
                        if (!file.toPath().startsWith(root.toPath())) return
                    } else if (!url.startsWith("/chat_images/") && !url.startsWith("data:image/")) return
                    val original = loadOriginalPreviewBytes(context, url) ?: return
                    if (original.bytes.isEmpty() || original.bytes.size > 8 * 1024 * 1024) return
                    result.put("status", "ok").put("data", Base64.encodeToString(original.bytes, Base64.NO_WRAP))
                }
            }
        } catch (_: Exception) {
            result.remove("data")
            result.put("status", "unavailable")
        } finally {
            if (AppPreferences(context).username == username) socket.send(result.toString())
        }
    }
}
