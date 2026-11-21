package top.ponychat.webview.ui.creation

import com.google.gson.annotations.SerializedName
import com.google.gson.Gson
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.prefs.AppPreferences
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class CreationMessage(val id: String, val role: String, val content: String, val timestamp: Long,
    @SerializedName("request_id") val requestId: String, val incomplete: Boolean = false)
data class CreationSession(val id: String, val title: String, val instructions: String = "",
    @SerializedName("character_setting") val characterSetting: String? = null,
    val version: Int = 0, val busy: Boolean = false, val messages: List<CreationMessage> = emptyList(),
    @SerializedName("last_error") val lastError: String? = null,
    @SerializedName("output_truncated") val outputTruncated: Boolean = false,
    @SerializedName("context_layout") val contextLayout: List<CreationContextBlock> = emptyList(),
    @SerializedName("reply_versions") val replyVersions: List<CreationMessage> = emptyList(),
    @SerializedName("selected_reply_version") val selectedReplyVersion: Int = 0,
    @SerializedName("context_usage") val contextUsage: CreationContextUsage? = null)
data class CreationContextUsage(
    @SerializedName("used_tokens") val usedTokens: Int? = null,
    @SerializedName("context_limit") val contextLimit: Int? = null,
    @SerializedName("prompt_tokens") val promptTokens: Int? = null,
    @SerializedName("completion_tokens") val completionTokens: Int? = null,
    @SerializedName("request_id") val requestId: String? = null,
    @SerializedName("recorded_ms") val recordedMs: Long? = null)

data class CreationContextBlock(val id: String, val kind: String, val title: String, val text: String = "")
data class CreationHistory(val id: String, val title: String)
private data class HistoryResponse(val sessions: List<CreationHistory>)

open class CreationRepository(private val prefs: AppPreferences) {
    private val gson = Gson()
    internal val cache = CreationLocalCache(prefs)
    // Metadata must not queue behind long-running generation streams.
    private val metadataClient = NetworkClient.chatJsonResponseHttpClient.newBuilder()
        .dispatcher(Dispatcher())
        .callTimeout(25, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(20, java.util.concurrent.TimeUnit.SECONDS)
        .build()
    @Volatile private var streamCall: Call? = null
    fun stop() { streamCall?.cancel() }

    open suspend fun stream(session: CreationSession, text: String, requestId: String, regenerate: Boolean,
        onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit, editMessageId: String? = null,
        continueStory: Boolean = false): CreationSession =
        suspendCancellableCoroutine { continuation ->
            val body = JSONObject().put("content", text).put("request_id", requestId)
                .put("regenerate", regenerate).put("version", session.version)
                .put("continue_story", continueStory)
                .put("edit_message_id", editMessageId ?: JSONObject.NULL).toString()
                .toRequestBody("application/json; charset=utf-8".toMediaType())
            val call = NetworkClient.chatJsonResponseHttpClient.newCall(Request.Builder()
                .url(prefs.effectiveApiBase().trimEnd('/') + "/api/creation/sessions/${session.id}/messages")
                .header("X-Chat-Auth", prefs.authToken).header("Accept", "text/event-stream").post(body).build())
            streamCall = call
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resumeWithException(e)
                }
                override fun onResponse(call: Call, response: Response) {
                    try {
                        response.use {
                            if (!it.isSuccessful) throw IOException(runCatching {
                                JSONObject(it.body?.string().orEmpty()).optString("detail")
                            }.getOrDefault("").ifBlank { "请求失败（${it.code}）" })
                            val source = it.body?.source() ?: throw IOException("没有收到回复")
                            while (continuation.isActive) {
                                val line = source.readUtf8Line() ?: break
                                if (!line.startsWith("data:")) continue
                                val event = JSONObject(line.substring(5).trim())
                                when (event.optString("type")) {
                                    "accepted" -> onSession(gson.fromJson(event.getJSONObject("session").toString(), CreationSession::class.java))
                                    "delta" -> onDelta(event.getString("text"))
                                    "complete" -> {
                                        val complete = gson.fromJson(event.getJSONObject("session").toString(), CreationSession::class.java)
                                        cache.save(complete)
                                        continuation.resume(complete)
                                        return
                                    }
                                    "error" -> throw IOException(event.optString("message", "生成中断"))
                                }
                            }
                            if (continuation.isActive) throw IOException("连接中断，已生成的内容已保留")
                        }
                    } catch (e: Exception) {
                        if (continuation.isActive) continuation.resumeWithException(e)
                    } finally { if (streamCall === call) streamCall = null }
                }
            })
        }
    private suspend fun request(method: String, path: String, json: JSONObject? = null): String =
        suspendCancellableCoroutine { continuation ->
            val url = prefs.effectiveApiBase().trimEnd('/') + "/api/creation" + path
            val body = json?.toString()?.toRequestBody("application/json; charset=utf-8".toMediaType())
            val client = if (method == "POST" && path.endsWith("/messages"))
                NetworkClient.chatJsonResponseHttpClient else metadataClient
            val call = client.newCall(Request.Builder().url(url)
                .header("X-Chat-Auth", prefs.authToken).method(method, body).build())
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resumeWithException(IOException("连接未完成，请重试", e))
                }
                override fun onResponse(call: Call, response: Response) {
                    try { response.use {
                        val text = it.body?.string().orEmpty()
                        if (!continuation.isActive) return
                        if (it.isSuccessful) continuation.resume(text)
                        else {
                            val detail = runCatching { JSONObject(text).optString("detail") }.getOrDefault("")
                            continuation.resumeWithException(IOException(detail.ifBlank { "请求失败（${it.code}），请重试" }))
                        }
                    } } catch (e: Exception) {
                        if (continuation.isActive) continuation.resumeWithException(
                            IOException("连接未完成，请重试", e))
                    }
                }
            })
        }

    open suspend fun history(characterId: String): List<CreationHistory> {
        val query = "http://localhost/".toHttpUrl().newBuilder().addQueryParameter("character_id", characterId).build().encodedQuery
        return gson.fromJson(request("GET", "/sessions?$query"), HistoryResponse::class.java).sessions.also { cache.saveHistory(characterId, it) }
    }
    suspend fun create(characterId: String): CreationSession = gson.fromJson(request("POST", "/sessions",
        JSONObject().put("character_id", characterId)), CreationSession::class.java)
    open suspend fun load(id: String): CreationSession = gson.fromJson(request("GET", "/sessions/$id"), CreationSession::class.java).also(cache::save)
    open suspend fun contextUsage(id: String): CreationContextUsage = gson.fromJson(
        request("GET", "/sessions/$id/context-usage"), CreationContextUsage::class.java)
    open suspend fun selectReplyVersion(session: CreationSession, replyId: String): CreationSession = gson.fromJson(
        request("PATCH", "/sessions/${session.id}/reply-version", JSONObject().put("reply_id", replyId)
            .put("version", session.version)), CreationSession::class.java)
    open suspend fun deleteSession(session: CreationSession) {
        request("DELETE", "/sessions/${session.id}?version=${session.version}")
        cache.remove(session.id)
    }
    open suspend fun deleteMessage(session: CreationSession, messageId: String): CreationSession = gson.fromJson(
        request("DELETE", "/sessions/${session.id}/messages/$messageId?version=${session.version}"), CreationSession::class.java)
    suspend fun configure(session: CreationSession, title: String, instructions: String, setting: String?): CreationSession =
        gson.fromJson(request("PATCH", "/sessions/${session.id}", JSONObject().put("title", title)
            .put("instructions", instructions).put("character_setting", setting ?: JSONObject.NULL)
            .put("version", session.version)), CreationSession::class.java)
    suspend fun configureContext(session: CreationSession, blocks: List<CreationContextBlock>): CreationSession =
        gson.fromJson(request("PATCH", "/sessions/${session.id}/context", JSONObject()
            .put("layout", org.json.JSONArray(gson.toJson(blocks))).put("version", session.version)), CreationSession::class.java)
    suspend fun send(session: CreationSession, text: String, requestId: String, regenerate: Boolean): CreationSession =
        gson.fromJson(request("POST", "/sessions/${session.id}/messages", JSONObject().put("content", text)
            .put("request_id", requestId).put("regenerate", regenerate).put("version", session.version)), CreationSession::class.java)
}
