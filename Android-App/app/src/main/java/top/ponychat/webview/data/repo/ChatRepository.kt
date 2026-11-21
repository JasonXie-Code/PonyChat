package top.ponychat.webview.data.repo

import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.httpErrorForDisplay
import top.ponychat.webview.util.toUserMessage
import com.google.gson.Gson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.FlowCollector
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import org.json.JSONArray
import org.json.JSONObject
import kotlin.coroutines.coroutineContext
import java.io.File

class ChatRepository(private val prefs: AppPreferences) {

    private val TAG = "ChatRepository"
    private val gson = Gson()
    private fun api() = NetworkClient.createApiService(prefs)

    private suspend fun PagedMessagesResponse.visibleOnly(): PagedMessagesResponse =
        copy(messages = messages.filter { it.isHidden != true }.map { message ->
            message.copy(attachments = message.attachments?.map { WebImageReceiver.receive(prefs, it) })
        })

    private fun jsonArrayToList(arr: JSONArray): List<Any?> =
        (0 until arr.length()).map { i ->
            when (val v = arr.get(i)) {
                is JSONObject -> jsonObjectToMap(v)
                is JSONArray -> jsonArrayToList(v)
                JSONObject.NULL -> null
                else -> v
            }
        }

    /**
     * 将 JSONObject 递归转为 Map<String, Any?>。
     *
     * [excludeKeys] 仅对当前层级生效，不向子对象传播——
     * 这样可以精确过滤顶层 type 分类型字段（如 "type": "metadata"），
     * 同时保留嵌套业务对象里同名的字段（如 suggested_options[i].type = "action"）。
     */
    private fun jsonObjectToMap(
        jo: JSONObject,
        excludeKeys: Set<String> = emptySet()
    ): Map<String, Any?> {
        val out = linkedMapOf<String, Any?>()
        val keys = jo.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            if (k in excludeKeys) continue
            out[k] = when (val v = jo.get(k)) {
                is JSONObject -> jsonObjectToMap(v)   // 子对象不继承 excludeKeys
                is JSONArray  -> jsonArrayToList(v)
                JSONObject.NULL -> null
                else -> v
            }
        }
        return out
    }

    /**
     * 解析与后端 [data: …] 行等价的单条 JSON 文本（主对话的 OpenAI 兼容块、游戏/锁分事件等同）。
     * @return 若应停止消费后续 events（如模型错误包），为 true
     */
    private suspend fun FlowCollector<ChatDelta>.emitFromChatPayload(
        data: String,
        jobIdHolder: Array<String?>,
    ): Boolean {
        if (data.startsWith("{")) {
            try {
                val jo = JSONObject(data)
                when (jo.optString("type", "")) {
                    "step" -> {
                        val lab = jo.optString("label", "").trim()
                        if (lab.isNotEmpty()) emit(ChatDelta.GalgameStepProgress(lab))
                        return false
                    }
                    "plan" -> {
                        val arr = jo.optJSONArray("scene_fields")
                        val list = mutableListOf<String>()
                        if (arr != null) {
                            for (i in 0 until arr.length()) {
                                list.add(arr.optString(i))
                            }
                        }
                        emit(ChatDelta.GalgamePlan(list))
                        return false
                    }
                    "chunk" -> {
                        emit(
                            ChatDelta.GalgameChunk(
                                field = jo.optString("field"),
                                content = jo.optString("content"),
                            )
                        )
                        return false
                    }
                    "metadata" -> {
                        emit(
                            ChatDelta.GalgameMetadata(
                                jsonObjectToMap(jo, excludeKeys = setOf("type"))
                            )
                        )
                        return false
                    }
                    "options" -> {
                        val raw = jo.opt("options")
                        val opts: List<Any?>? = when (raw) {
                            is JSONArray -> jsonArrayToList(raw)
                            else -> null
                        }
                        emit(ChatDelta.GalgameOptions(opts))
                        return false
                    }
                    "result" -> {
                        val gr = jo.optJSONObject("galgame_result")
                        if (gr != null) {
                            emit(ChatDelta.GalgameStreamResult(jsonObjectToMap(gr)))
                        }
                        return false
                    }
                    "cancelled" -> {
                        emit(ChatDelta.Cancelled(jo.optString("reason").ifBlank { null }))
                        return false
                    }
                    "crisis_triggered" -> {
                        emit(ChatDelta.CrisisTriggered)
                        return false
                    }
                    "quota_exceeded" -> {
                        emit(ChatDelta.QuotaExceeded(jo.optString("message").ifBlank { "今日积分已用完" }))
                        return false
                    }
                    "no_reply" -> {
                        emit(ChatDelta.NoReply(jo.optString("reason").ifBlank { null }))
                        return false
                    }
                    "error" -> {
                        emit(ChatDelta.Error(jo.optString("message", "游戏生成失败")))
                        return true
                    }
                    "assistant_paragraph" -> {
                        val voiceObj = jo.optJSONObject("voice_state")
                        val audioObj = jo.optJSONObject("audio_transfer")
                        emit(
                            ChatDelta.AssistantParagraph(
                                id = jo.optString("id", "").ifBlank { null },
                                content = jo.optString("content", ""),
                                index = jo.optInt("index", 0),
                                total = jo.optInt("total", 1),
                                sequenceNumber = if (jo.has("sequence_number")) jo.optInt("sequence_number") else null,
                                timestamp = jo.optLong("timestamp", 0L).takeIf { it > 0L },
                                voiceState = voiceObj?.let {
                                    gson.fromJson(it.toString(), MessageVoiceState::class.java)
                                },
                                audioTransfer = audioObj?.let {
                                    gson.fromJson(it.toString(), VoiceAudioTransfer::class.java)
                                },
                                speakerCharacterId = jo.optString("speaker_character_id", "").ifBlank { null },
                                speakerName = jo.optString("speaker_name", "").ifBlank { null },
                                speakerAvatar = jo.optString("speaker_avatar", "").ifBlank { null },
                                displayOverdue = jo.optBoolean("client_display_overdue", false),
                            )
                        )
                        return false
                    }
                    "assistant_asset" -> {
                        val attObj = jo.optJSONObject("attachment")
                        if (attObj != null) {
                            emit(
                                ChatDelta.AssistantAsset(
                                    messageId = jo.optString("message_id", "").ifBlank { null },
                                    attachment = WebImageReceiver.receive(prefs,
                                        gson.fromJson(attObj.toString(), MessageAttachment::class.java)),
                                    index = jo.optInt("index", 0),
                                    total = jo.optInt("total", 1),
                                    sequenceNumber = if (jo.has("sequence_number")) jo.optInt("sequence_number") else null,
                                    timestamp = jo.optLong("timestamp", 0L).takeIf { it > 0L },
                                    speakerCharacterId = jo.optString("speaker_character_id", "").ifBlank { null },
                                    speakerName = jo.optString("speaker_name", "").ifBlank { null },
                                    speakerAvatar = jo.optString("speaker_avatar", "").ifBlank { null },
                                    displayOverdue = jo.optBoolean("client_display_overdue", false),
                                )
                            )
                        }
                        return false
                    }
                    "accepted" -> {
                        emit(
                            ChatDelta.Accepted(
                                jobId = jo.optString("job_id", "").ifBlank { null },
                                conversationId = jo.optString("conversation_id", "").ifBlank { null },
                                clientMessageId = jo.optString("client_message_id", "").ifBlank { null },
                                acceptedAtMs = jo.optLong("accepted_at_ms", 0L).takeIf { it > 0L },
                            )
                        )
                        return false
                    }
                    "save_status" -> {
                        val mids = jo.optJSONArray("assistant_message_ids")
                        if (mids != null && mids.length() > 0) {
                            val ids = (0 until mids.length()).map { mids.getString(it) }
                            emit(ChatDelta.ServerAssistantIds(ids))
                        } else {
                            val mid = jo.optString("assistant_message_id", "").trim()
                            if (mid.isNotEmpty()) emit(ChatDelta.ServerAssistantId(mid))
                        }
                        return false
                    }
                    "done" -> {
                        emit(ChatDelta.Done(jobIdHolder[0]))
                        return false
                    }
                }
            } catch (_: Exception) {
                // 回落到 OpenAI 兼容解析
            }
        }
        runCatching {
            val chunk = gson.fromJson(data, SseChunk::class.java)
            if (chunk.jobId != null) jobIdHolder[0] = chunk.jobId
            if (chunk.metadata != null) {
                val jid = chunk.metadata["job_id"]?.toString()
                if (!jid.isNullOrBlank()) jobIdHolder[0] = jid
                @Suppress("UNCHECKED_CAST")
                val usageMap = chunk.metadata["usage"] as? Map<String, Any?>
                if (usageMap != null) {
                    val total = (usageMap["total_tokens"] as? Number)?.toInt() ?: 0
                    val limit = (usageMap["limit_tokens"] as? Number)?.toInt() ?: 0
                    if (total > 0 && limit > 0) emit(ChatDelta.Usage(total, limit))
                }
            }
            if (chunk.error != null) {
                emit(ChatDelta.Error(chunk.error))
                return true
            }
            val content = chunk.choices?.firstOrNull()?.delta?.content
            if (!content.isNullOrEmpty()) {
                emit(ChatDelta.Token(content))
            }
        }.onFailure { e ->
            DebugLog.w(TAG, "聊天载荷解析: $data → ${e.message}", e)
        }
        return false
    }

    /**
     * 发送消息：
     * - 普通模式：单次 [application/json]，body 内 [events] 与历史线协议等价。
     * - 游戏/锁分：Accept [text/event-stream]，按行消费 `data:`（实时步骤状态）。
     */
    fun sendMessage(request: ChatRequest): Flow<ChatDelta> = flow {
        val baseUrl = prefs.effectiveApiBase().trimEnd('/')
        val url = "$baseUrl/api/chat"
        val bodyJson = gson.toJson(request)
        val reqBody = bodyJson.toRequestBody("application/json".toMediaType())

        val clientIdForRequest = request.clientId?.takeIf { it.isNotBlank() } ?: "single"
        val isGalgameStream = request.mode == "galgame" || request.mode == "galgame_lock"
        val isNormalMode = request.mode == "normal"
        // normal 与 galgame 均使用 SSE（实时逐段投递）；其他模式保留 JSON 批量
        val useSseAccept = isGalgameStream || isNormalMode
        val builder = Request.Builder()
            .url(url)
            .post(reqBody)
            .addHeader("Content-Type", "application/json")
            .addHeader(
                "Accept",
                if (useSseAccept) "text/event-stream" else "application/json",
            )
            .addHeader("X-Client-Id", clientIdForRequest)
            .addHeader("X-PonyChat-Web-Images", "receipt-v1")
        prefs.authToken.takeIf { it.isNotBlank() }?.let { builder.addHeader("X-Chat-Auth", it) }
        DebugLog.d(TAG, "🚀 [sendMessage] 发送请求 mode=${request.mode} client_id=$clientIdForRequest")
        val httpReq = builder.build()

        val call = NetworkClient.chatJsonResponseHttpClient.newCall(httpReq)
        val cancelHandle = coroutineContext[Job]?.invokeOnCompletion {
            runCatching { call.cancel() }
        }
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    if (isNormalMode && response.code in setOf(408, 502, 503, 504)) {
                        throw java.io.IOException("Chat transport HTTP ${response.code}")
                    }
                    if (response.code == 409) {
                        val body = response.body?.string() ?: ""
                        val busyMsg = try {
                            val json = JSONObject(body)
                            val detail = json.optJSONObject("detail")
                            detail?.optString("message")?.ifBlank { null }
                                ?: json.optString("message").ifBlank { null }
                                ?: "上一条回复仍在生成，请稍后再试"
                        } catch (_: Exception) {
                            "上一条回复仍在生成，请稍后再试"
                        }
                        emit(ChatDelta.Error(busyMsg))
                        return@flow
                    }
                    if (response.code == 429) {
                        val body = response.body?.string() ?: ""
                        val quotaMsg = try {
                            val json = org.json.JSONObject(body)
                            val detail = json.optJSONObject("detail")
                            detail?.optString("message")?.ifBlank { null }
                                ?: detail?.optString("reason")?.ifBlank { null }
                                ?: "今日积分已用完"
                        } catch (_: Exception) { "今日积分已用完" }
                        emit(ChatDelta.QuotaExceeded(quotaMsg))
                        return@flow
                    }
                    val errBody = response.body?.string()
                    val errText = httpErrorForDisplay(
                        fallback = "消息发送失败，请稍后重试",
                        code = response.code,
                        reason = response.message,
                        body = errBody
                    ).asSingleLine()
                    emit(ChatDelta.Error(errText))
                    return@flow
                }

                val respBody = response.body ?: run {
                    emit(ChatDelta.Error("空响应"))
                    return@flow
                }
                val jobIdHolder: Array<String?> = arrayOfNulls(1)
                var implicitNormalAcceptedEmitted = false
                suspend fun emitImplicitNormalAcceptedIfNeeded(jo: JSONObject) {
                    if (!isNormalMode || implicitNormalAcceptedEmitted) return
                    when (jo.optString("type", "")) {
                        "accepted" -> implicitNormalAcceptedEmitted = true
                        "assistant_paragraph",
                        "assistant_asset",
                        "save_status",
                        "no_reply" -> {
                            implicitNormalAcceptedEmitted = true
                            emit(
                                ChatDelta.Accepted(
                                    jobId = jobIdHolder[0],
                                    conversationId = request.conversationId,
                                    clientMessageId = request.messages
                                        .asReversed()
                                        .firstOrNull { it.role == "user" }
                                        ?.messageId,
                                    acceptedAtMs = System.currentTimeMillis(),
                                    implicit = true,
                                )
                            )
                        }
                    }
                }
                val bubbleDisplayPacer = BubbleDisplayPacer()
                val contentType = (response.header("Content-Type") ?: "").lowercase()
                val useSseLines = (isGalgameStream || isNormalMode) && !contentType.contains("application/json")
                if (useSseLines) {
                    respBody.charStream().buffered().use { reader ->
                        while (true) {
                            val line = reader.readLine() ?: break
                            if (!coroutineContext.isActive) return@flow
                            if (line.startsWith("data:")) {
                                val data = line.removePrefix("data:").trim()
                                if (data == "[DONE]") {
                                    emit(ChatDelta.Done(jobIdHolder[0]))
                                    break
                                }
                                var payload = data
                                try {
                                    if (data.startsWith("{")) {
                                        val jo = JSONObject(data)
                                        emitImplicitNormalAcceptedIfNeeded(jo)
                                        bubbleDisplayPacer.pace(jo, compensateElapsed = true)
                                        payload = jo.toString()
                                    }
                                } catch (e: CancellationException) {
                                    throw e
                                } catch (_: Exception) {
                                }
                                if (emitFromChatPayload(payload, jobIdHolder)) return@flow
                            }
                        }
                    }
                } else {
                    val raw = respBody.string()
                    val fromEventsEnvelope = runCatching {
                        val o = JSONObject(raw)
                        o.optJSONArray("events")
                    }.getOrNull() != null
                    if (fromEventsEnvelope) {
                        val o = JSONObject(raw)
                        val events = o.optJSONArray("events") ?: run {
                            emit(ChatDelta.Error("非法响应: 无 events"))
                            return@flow
                        }
                        for (i in 0 until events.length()) {
                            if (!coroutineContext.isActive) return@flow
                            val e = events.get(i)
                            if (e is JSONObject) {
                                emitImplicitNormalAcceptedIfNeeded(e)
                                bubbleDisplayPacer.pace(e, compensateElapsed = false)
                                if (emitFromChatPayload(e.toString(), jobIdHolder)) {
                                    return@flow
                                }
                            }
                        }
                    } else {
                        for (line in raw.lineSequence()) {
                            if (!coroutineContext.isActive) return@flow
                            if (line.startsWith("data:")) {
                                val data = line.removePrefix("data:").trim()
                                if (data == "[DONE]") {
                                    emit(ChatDelta.Done(jobIdHolder[0]))
                                    break
                                }
                                var payload = data
                                try {
                                    if (data.startsWith("{")) {
                                        val jo = JSONObject(data)
                                        emitImplicitNormalAcceptedIfNeeded(jo)
                                        bubbleDisplayPacer.pace(jo, compensateElapsed = false)
                                        payload = jo.toString()
                                    }
                                } catch (e: CancellationException) {
                                    throw e
                                } catch (_: Exception) {
                                }
                                if (emitFromChatPayload(payload, jobIdHolder)) return@flow
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            if (!coroutineContext.isActive) {
                // 协程已取消（如用户手动停止生成），不再向上层回传错误。
                return@flow
            }
            DebugLog.e(TAG, "聊天请求错误: ${e.message}", e)
            // Socket failure is not server rejection: retain normal mode recovery.
            if (e is CancellationException || (isNormalMode && e is java.io.IOException)) throw e
            emit(ChatDelta.Error(e.toUserMessage("消息发送失败，请检查网络后重试")))
        } finally {
            cancelHandle?.dispose()
        }
    }.flowOn(Dispatchers.IO)

    suspend fun searchMessages(
        username: String,
        characterId: String,
        query: String,
        sender: String = "all",
        dateFrom: Long? = null,
        dateTo: Long? = null,
        limit: Int = 20,
        offset: Int = 0
    ): top.ponychat.webview.data.model.MessageSearchResponse? {
        return try {
            val api = NetworkClient.createApiService(prefs)
            val resp = api.searchMessages(
                username = username,
                characterId = characterId,
                query = query,
                sender = sender,
                dateFrom = dateFrom,
                dateTo = dateTo,
                limit = limit,
                offset = offset
            )
            if (resp.isSuccessful) resp.body() else null
        } catch (e: Exception) {
            DebugLog.e(TAG, "searchMessages error: ${e.message}", e)
            null
        }
    }

    suspend fun loadMessagesBefore(
        username: String,
        characterId: String,
        conversationId: String?,
        beforeSeq: Int?,
        limit: Int = 50
    ): top.ponychat.webview.data.model.PagedMessagesResponse? {
        return try {
            val api = NetworkClient.createApiService(prefs)
            val resp = api.getConversationMessagesPaged(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                beforeSeq = beforeSeq,
                afterSeq = null,
                limit = limit
            )
            if (resp.isSuccessful) resp.body()?.visibleOnly() else null
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            DebugLog.e(TAG, "loadMessagesBefore error: ${e.message}", e)
            null
        }
    }

    suspend fun loadMessagesAfter(
        username: String,
        characterId: String,
        conversationId: String?,
        afterSeq: Int,
        limit: Int = 100
    ): top.ponychat.webview.data.model.PagedMessagesResponse? {
        return try {
            val api = NetworkClient.createApiService(prefs)
            val resp = api.getConversationMessagesPaged(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                beforeSeq = null,
                afterSeq = afterSeq,
                limit = limit
            )
            if (resp.isSuccessful) resp.body()?.visibleOnly() else null
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            DebugLog.e(TAG, "loadMessagesAfter error: ${e.message}", e)
            null
        }
    }

    suspend fun loadDeliveredMessage(
        username: String,
        characterId: String,
        conversationId: String,
        messageId: String,
    ): ChatMessage? = try {
        val response = NetworkClient.createApiService(prefs).getConversationMessagesPaged(
            username = username, characterId = characterId, conversationId = conversationId,
            messageId = messageId, limit = 1,
        )
        response.body()?.visibleOnly()?.messages?.firstOrNull { it.messageId == messageId }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        DebugLog.e(TAG, "loadDeliveredMessage error: ${e.message}", e)
        null
    }

    suspend fun cancelGeneration(
        username: String,
        characterId: String,
        conversationId: String?,
        clientId: String?,
        jobId: String? = null,
        reason: String = "用户取消生成",
    ): Result<Unit> {
        DebugLog.d(TAG, "🛑 [cancelGeneration] 准备取消: user=$username char=${characterId.take(8)}... jobId=${jobId ?: "null"} clientId=${clientId ?: "null"} reason=$reason")
        return runCatching {
            val baseUrl = prefs.effectiveApiBase().trimEnd('/')
            val url = "$baseUrl/api/chat/cancel"
            val payload = mutableMapOf(
                "username" to username,
                "character_id" to characterId,
                "conversation_id" to conversationId,
                "client_id" to clientId,
                "reason" to reason,
            )
            if (jobId != null) payload["job_id"] = jobId
            val reqBody = gson.toJson(payload).toRequestBody("application/json".toMediaType())
            val cancelReq = Request.Builder()
                .url(url)
                .post(reqBody)
                .addHeader("Content-Type", "application/json")
                .addHeader("X-Client-Id", clientId ?: "unknown")
            prefs.authToken.takeIf { it.isNotBlank() }?.let { cancelReq.addHeader("X-Chat-Auth", it) }
            DebugLog.d(TAG, "🛑 [cancelGeneration] 发送 POST $url  job_id=${jobId ?: "-"}  X-Client-Id=${clientId ?: "unknown"}")
            // OkHttp execute() 是阻塞调用，必须切到 IO 线程，避免 NetworkOnMainThreadException
            withContext(Dispatchers.IO) {
                NetworkClient.okHttpClient.newCall(cancelReq.build()).execute().use { response ->
                    DebugLog.d(TAG, "🛑 [cancelGeneration] 响应 HTTP ${response.code}  isSuccessful=${response.isSuccessful}")
                    if (!response.isSuccessful) {
                        throw IllegalStateException("取消生成失败: HTTP ${response.code}")
                    }
                }
            }
        }.onFailure { e ->
            DebugLog.e(TAG, "🛑 [cancelGeneration] 请求异常: ${e::class.simpleName} ${e.message}", e)
        }
    }

    /**
     * 上传聊天图片（本地压缩后的 JPEG 字节），成功返回临时 /chat_images/...，只供随后的聊天请求处理。
     */
    suspend fun uploadChatImage(jpegBytes: ByteArray): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val api = NetworkClient.createApiService(prefs)
            val body = jpegBytes.toRequestBody("image/jpeg".toMediaType())
            val part = MultipartBody.Part.createFormData("file", "upload.jpg", body)
            val resp = api.uploadChatImage(part)
            if (!resp.isSuccessful) {
                val err = resp.errorBody()?.string() ?: "HTTP ${resp.code()}"
                error("图片上传失败: $err")
            }
            val parsed = resp.body() ?: error("空响应体")
            val url = parsed.url
            if (url.isBlank()) error("无 url 字段")
            url
        }
    }

    suspend fun loadQuickMessages(username: String): Result<List<QuickMessage>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = api().getQuickMessages(username)
            if (!resp.isSuccessful) error("加载快捷消息失败 (${resp.code()})")
            resp.body()?.messages ?: emptyList()
        }
    }

    suspend fun addQuickMessage(username: String, title: String, content: String): Result<QuickMessage> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().addQuickMessage(QuickMessageCreateRequest(username, title, content))
                if (!resp.isSuccessful) error("添加快捷消息失败 (${resp.code()})")
                resp.body() ?: error("空响应")
            }
        }

    suspend fun updateQuickMessage(message: QuickMessage, username: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().updateQuickMessage(
                    message.id,
                    QuickMessageUpdateRequest(username, message.title, message.content, message.sortOrder)
                )
                if (!resp.isSuccessful) error("更新快捷消息失败 (${resp.code()})")
                Unit
            }
        }

    suspend fun deleteQuickMessage(username: String, messageId: Int): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().deleteQuickMessage(messageId, QuickMessageDeleteRequest(username))
                if (!resp.isSuccessful) error("删除快捷消息失败 (${resp.code()})")
                Unit
            }
        }

    suspend fun loadStickers(source: String = "all"): Result<List<StickerAsset>> =
        withContext(Dispatchers.IO) {
            runCatching {
                suspend fun loadSourcePages(src: String): List<StickerAsset> {
                    val out = mutableListOf<StickerAsset>()
                    val pageSize = 100
                    var page = 1
                    while (true) {
                        val resp = api().getStickers(source = src, page = page, pageSize = pageSize)
                        if (!resp.isSuccessful) error("加载表情失败 (${resp.code()})")
                        val items = resp.body()?.items ?: emptyList()
                        out += items
                        if (items.size < pageSize) break
                        page++
                    }
                    return out
                }

                if (source == "all") {
                    (loadSourcePages("user") + loadSourcePages("platform")).distinctBy { it.id }
                } else {
                    loadSourcePages(source)
                }
            }
        }

    suspend fun saveSticker(assetId: String): Result<StickerAsset?> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().saveSticker(StickerSaveRequest(assetId))
                if (!resp.isSuccessful) error("收藏表情失败 (${resp.code()})")
                resp.body()?.item
            }
        }

    suspend fun uploadSticker(file: File, displayName: String): Result<StickerAsset?> =
        withContext(Dispatchers.IO) {
            runCatching {
                val mime = when (file.extension.lowercase()) {
                    "jpg", "jpeg" -> "image/jpeg"
                    "png" -> "image/png"
                    "gif" -> "image/gif"
                    "webp" -> "image/webp"
                    else -> "image/png"
                }
                val part = MultipartBody.Part.createFormData(
                    "file",
                    file.name,
                    file.asRequestBody(mime.toMediaType())
                )
                val textType = "text/plain".toMediaType()
                val resp = api().uploadSticker(
                    file = part,
                    name = displayName.toRequestBody(textType),
                    intro = "".toRequestBody(textType),
                    detail = "".toRequestBody(textType),
                    imageText = "".toRequestBody(textType),
                    customTags = "[]".toRequestBody(textType)
                )
                if (!resp.isSuccessful) error("上传表情失败 (${resp.code()})")
                resp.body()?.item
            }
        }

    suspend fun deleteSticker(stickerId: String): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().deleteSticker(stickerId)
                if (!resp.isSuccessful) error("移除表情失败 (${resp.code()})")
                Unit
            }
        }

    suspend fun synthesizeMessageVoice(
        username: String,
        characterId: String,
        conversationId: String,
        messageId: String,
        content: String? = null,
        voiceSentences: List<Map<String, String>> = emptyList(),
        instruct: String? = null,
        replyLanguage: String? = null,
    ): Result<VoiceSynthesizeResponse> = withContext(Dispatchers.IO) {
        runCatching {
            val body = mutableMapOf<String, Any?>(
                "username" to username,
                "character_id" to characterId,
                "conversation_id" to conversationId,
                "message_id" to messageId,
            )
            if (!content.isNullOrBlank()) body["content"] = content
            if (voiceSentences.isNotEmpty()) body["voice_sentences"] = voiceSentences
            if (!instruct.isNullOrBlank()) body["instruct"] = instruct
            if (!replyLanguage.isNullOrBlank()) body["reply_language"] = replyLanguage
            val resp = api().synthesizeMessageVoice(body)
            val parsed = resp.body()
            if (!resp.isSuccessful) {
                error(parsed?.error?.ifBlank { parsed.message ?: "语音生成失败 (${resp.code()})" }
                    ?: parsed?.message
                    ?: "语音生成失败 (${resp.code()})")
            }
            parsed ?: error("空响应")
        }
    }

    suspend fun ackMessageVoiceAudio(
        username: String,
        characterId: String,
        conversationId: String,
        messageId: String,
        voiceCacheKey: String,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = mapOf(
                "username" to username,
                "character_id" to characterId,
                "conversation_id" to conversationId,
                "message_id" to messageId,
                "voice_cache_key" to voiceCacheKey,
            )
            val resp = api().ackMessageVoiceAudio(body)
            if (!resp.isSuccessful) {
                val parsed = resp.body()
                error(parsed?.message ?: "语音缓存确认失败 (${resp.code()})")
            }
            Unit
        }
    }

    suspend fun sendStickerMessage(request: ChatRequest): Result<Map<String, Any?>> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = api().sendStickerChat(request)
                if (!resp.isSuccessful) error("发送表情失败 (${resp.code()})")
                resp.body() ?: emptyMap()
            }
        }
}

sealed class ChatDelta {
    data class Accepted(
        val jobId: String?,
        val conversationId: String?,
        val clientMessageId: String?,
        val acceptedAtMs: Long?,
        val implicit: Boolean = false,
    ) : ChatDelta()
    data class Token(val text: String) : ChatDelta()
    data class Done(val jobId: String?) : ChatDelta()
    data class Error(val message: String) : ChatDelta()
    /** 今日配额已耗尽（HTTP 429 quota_exceeded） */
    data class QuotaExceeded(val message: String) : ChatDelta()
    /** 后端已保存用户消息，但本轮不会生成角色回复。 */
    data class NoReply(val reason: String?) : ChatDelta()
    /** 主对话元数据里携带的 token 用量，用于更新 UI 进度条 */
    data class Usage(val totalTokens: Int, val limitTokens: Int) : ChatDelta()

    /** 游戏/锁分：服务端推送的步骤名（导演策划、体征计算、…） */
    data class GalgameStepProgress(val label: String) : ChatDelta()

    /** 游戏/锁分：导演 plan（与后端 events 中 type=plan 对应） */
    data class GalgamePlan(val sceneFields: List<String>) : ChatDelta()
    /** 游戏/锁分：场景字段 chunk（与 events 中 type=chunk 对应） */
    data class GalgameChunk(val field: String, val content: String) : ChatDelta()
    /** 游戏/锁分：元数据快照 */
    data class GalgameMetadata(val payload: Map<String, Any?>) : ChatDelta()
    /** 游戏/锁分：选项 */
    data class GalgameOptions(val options: List<Any?>?) : ChatDelta()
    /** 游戏/锁分：与 Job 轮询 completed 时等价的 galgame_result */
    data class GalgameStreamResult(val galgameResult: Map<String, Any?>) : ChatDelta()
    /** 服务端取消本次生成：普通模式用于新用户消息覆盖旧请求，游戏/锁分用于手动取消。 */
    data class Cancelled(val reason: String?) : ChatDelta()
    /**
     * 主对话在 save_status 中返回的、与 outbox/WS 一致的助手 message_id，用于 [ChatEventBus] 与推送去重。
     */
    data class ServerAssistantId(val messageId: String) : ChatDelta()
    /**
     * 主对话在 save_status 中返回的多段落助手消息 ID 列表（按段落顺序排列）。
     * 每个 ID 对应一条独立 assistant 消息，与 UI 气泡一一对应。
     */
    data class ServerAssistantIds(val messageIds: List<String>) : ChatDelta()
    /** 后端检测到危机关键词，客户端应展示心理援助热线弹窗。 */
    object CrisisTriggered : ChatDelta()
    /**
     * normal 模式 SSE 路径：后端逐段推送的助手消息段落。
     * [index] 从 0 开始，[total] 为本轮总段落数。
     */
    data class AssistantParagraph(
        val id: String?,
        val content: String,
        val index: Int,
        val total: Int,
        val sequenceNumber: Int?,
        val timestamp: Long?,
        val voiceState: MessageVoiceState? = null,
        val audioTransfer: VoiceAudioTransfer? = null,
        val speakerCharacterId: String? = null,
        val speakerName: String? = null,
        val speakerAvatar: String? = null,
        val displayOverdue: Boolean = false,
    ) : ChatDelta()
    data class AssistantAsset(
        val messageId: String?,
        val attachment: MessageAttachment,
        val index: Int,
        val total: Int,
        val sequenceNumber: Int?,
        val timestamp: Long?,
        val speakerCharacterId: String? = null,
        val speakerName: String? = null,
        val speakerAvatar: String? = null,
        val displayOverdue: Boolean = false,
    ) : ChatDelta()
}
