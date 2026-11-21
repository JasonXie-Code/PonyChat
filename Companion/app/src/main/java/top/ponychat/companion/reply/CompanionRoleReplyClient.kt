package top.ponychat.companion.reply

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

data class CompanionRoleReplyPart(
    val text: String,
    val displayDelayMs: Long,
)

data class CompanionRoleReply(
    val parts: List<CompanionRoleReplyPart>,
    val conversationId: String?,
) {
    val displayText: String
        get() = parts.joinToString("\n") { it.text }
}

/** Uses the same normal-chat pipeline and persisted conversation as the PonyChat app. */
class CompanionRoleReplyClient {
    fun generate(
        session: CompanionSession,
        message: String,
    ): CompanionRoleReply? {
        if (!session.isReady || message.isBlank()) return null
        val connection = URL("${session.apiBase}/api/chat").openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15_000
            connection.readTimeout = 120_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("X-Chat-Auth", session.authToken)
            connection.setRequestProperty(
                "X-Client-Id",
                CompanionRoleReplyRequestBuilder.EXTERNAL_CLIENT_ID,
            )
            val now = System.currentTimeMillis()
            val body = CompanionRoleReplyRequestBuilder.build(
                session = session,
                message = message,
                timestampMs = now,
                messageId = "msg_external_${now}_${UUID.randomUUID().toString().take(8)}",
            )
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val responseCode = connection.responseCode
            val response = (if (responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            })?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (responseCode !in 200..299) {
                val serverMessage = CompanionRoleReplyResponseParser.diagnosticMessage(response)
                Log.w(TAG, "Normal chat HTTP failure code=$responseCode message=$serverMessage")
                throw CompanionRoleReplyException(
                    "普通对话接口 HTTP $responseCode" +
                        serverMessage?.let { ": $it" }.orEmpty(),
                )
            }
            CompanionRoleReplyResponseParser.parse(response).also { reply ->
                if (reply == null) Log.i(TAG, "Normal chat completed without a character reply")
            }
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        const val TAG = "CompanionRoleReply"
    }
}

internal object CompanionRoleReplyRequestBuilder {
    fun build(
        session: CompanionSession,
        message: String,
        timestampMs: Long,
        messageId: String,
    ): String {
        val userMessage = JSONObject()
            .put("role", "user")
            .put("content", message.trim())
            .put("timestamp", timestampMs)
            .put("message_id", messageId)
            .put("client_id", EXTERNAL_CLIENT_ID)
        return JSONObject()
            .put("username", session.username)
            .put("character_id", session.characterId)
            .put("messages", JSONArray().put(userMessage))
            .put("mode", "normal")
            .put("client_id", EXTERNAL_CLIENT_ID)
            .put("memory_enabled", true)
            .put("crisis_hotline_enabled", true)
            .toString()
    }

    const val EXTERNAL_CLIENT_ID = "companion_external"
}

class CompanionRoleReplyException(message: String) : IllegalStateException(message)

internal object CompanionRoleReplyResponseParser {
    fun parse(response: String): CompanionRoleReply? {
        val payload = runCatching { JSONObject(response) }.getOrElse {
            throw CompanionRoleReplyException("普通对话接口响应格式无效")
        }
        val events = payload.optJSONArray("events")
            ?: throw CompanionRoleReplyException("普通对话接口缺少事件列表")
        val parts = mutableListOf<CompanionRoleReplyPart>()
        var conversationId: String? = null
        var noReply = false
        for (index in 0 until events.length()) {
            val event = events.optJSONObject(index) ?: continue
            when (event.optString("type")) {
                "accepted" -> conversationId = event.optString("conversation_id")
                    .trim()
                    .takeIf(String::isNotBlank)
                "assistant_paragraph" -> {
                    val text = event.optString("content").trim()
                    if (text.isNotBlank()) {
                        parts += CompanionRoleReplyPart(
                            text = text,
                            displayDelayMs = event.optLong("display_delay_ms", 0L)
                                .coerceIn(0L, MAX_DISPLAY_DELAY_MS),
                        )
                    }
                }
                "no_reply" -> noReply = true
                "error" -> throw CompanionRoleReplyException(
                    "普通对话接口失败" + diagnosticMessage(event)?.let { ": $it" }.orEmpty(),
                )
            }
            if (event.has("error")) {
                throw CompanionRoleReplyException(
                    "普通对话接口失败" + diagnosticMessage(event)?.let { ": $it" }.orEmpty(),
                )
            }
        }
        if (parts.isNotEmpty()) return CompanionRoleReply(parts, conversationId)
        if (noReply) return null
        throw CompanionRoleReplyException("普通对话接口未返回角色消息")
    }

    fun diagnosticMessage(response: String): String? =
        runCatching { diagnosticMessage(JSONObject(response)) }.getOrNull()

    private fun diagnosticMessage(payload: JSONObject): String? {
        val detail = payload.opt("detail")
        val raw = when (detail) {
            is JSONObject -> detail.optString("message").ifBlank { detail.optString("reason") }
            is String -> detail
            else -> payload.optString("message").ifBlank { payload.optString("error") }
        }
        return raw.trim()
            .take(120)
            .replace(Regex("[^\\p{L}\\p{N}_\\- ,.，。！？!?：:；;]"), "?")
            .takeIf { it.isNotBlank() }
    }

    private const val MAX_DISPLAY_DELAY_MS = 15_000L
}
