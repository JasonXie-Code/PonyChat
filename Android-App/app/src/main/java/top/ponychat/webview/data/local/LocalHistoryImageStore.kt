package top.ponychat.webview.data.local

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import top.ponychat.webview.data.api.HistoryImageIndex
import top.ponychat.webview.data.model.ChatMessage

internal data class LocalHistoryImage(val messageId: String, val urls: List<String>, val timestamp: Long)

/** Durable phone-only references, independent of the currently loaded text-history page. */
internal class LocalHistoryImageStore(context: Context) {
    private val prefs = context.getSharedPreferences("ponychat_history_image_index", Context.MODE_PRIVATE)
    private fun key(username: String, character: String, conversation: String) =
        JSONArray(listOf(username, character, conversation)).toString()

    fun read(username: String, character: String, conversation: String): List<LocalHistoryImage> = synchronized(lock) {
        runCatching {
            val rows = JSONArray(prefs.getString(key(username, character, conversation), "[]"))
            (0 until rows.length()).map { i ->
                val row = rows.getJSONObject(i)
                val urls = row.getJSONArray("urls")
                LocalHistoryImage(row.getString("message_id"),
                    (0 until urls.length()).map { urls.getString(it) }, row.optLong("timestamp"))
            }
        }.getOrDefault(emptyList())
    }

    fun record(username: String, character: String, conversation: String, messages: List<ChatMessage>) = synchronized(lock) {
        if (username.isBlank() || character.isBlank() || conversation.isBlank()) return@synchronized
        val rows = read(username, character, conversation).associateBy { it.messageId }.toMutableMap()
        var changed = false
        messages.forEach { message ->
            val id = message.messageId?.takeIf { it.isNotBlank() } ?: return@forEach
            if (message.isHidden == true) {
                if (rows.remove(id) != null) changed = true
            } else {
                val urls = (HistoryImageIndex.urls(message.content) + message.attachments.orEmpty()
                    .filter { it.type == "image" }.mapNotNull { it.url }
                    .flatMap { HistoryImageIndex.urls(it) }).distinct().take(4)
                if (urls.isNotEmpty()) {
                    val entry = LocalHistoryImage(id, urls, message.timestamp ?: rows[id]?.timestamp ?: 0)
                    if (rows[id] != entry) { rows[id] = entry; changed = true }
                }
            }
        }
        if (changed) {
            val array = JSONArray()
            rows.values.forEach { row -> array.put(JSONObject().put("message_id", row.messageId)
                .put("urls", JSONArray(row.urls)).put("timestamp", row.timestamp)) }
            prefs.edit().putString(key(username, character, conversation), array.toString()).apply()
        }
    }

    fun remove(username: String, character: String, conversation: String? = null) = synchronized(lock) {
        val edit = prefs.edit()
        prefs.all.keys.forEach { name ->
            val scope = runCatching { JSONArray(name) }.getOrNull() ?: return@forEach
            if (scope.optString(0) == username && scope.optString(1) == character &&
                (conversation == null || scope.optString(2) == conversation)) edit.remove(name)
        }
        edit.apply()
    }

    companion object { private val lock = Any() }
}
