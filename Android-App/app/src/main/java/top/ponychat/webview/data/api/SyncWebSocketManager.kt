package top.ponychat.webview.data.api

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import top.ponychat.webview.MainActivity
import top.ponychat.webview.R
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ChatEventBus
import top.ponychat.webview.util.GalgameNotificationPreview
import top.ponychat.webview.util.MessageVibrationHelper
import top.ponychat.webview.util.MessageNotifyDeduper
import top.ponychat.webview.util.NotificationTrace
import top.ponychat.webview.util.RoleNotificationHelper
import androidx.core.app.NotificationManagerCompat
import com.google.gson.Gson
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.model.MessageVoiceUpdate
import top.ponychat.webview.data.model.VoiceAudioTransfer

/**
 * 与后端 /ws/{username} 保持长连接，用于：
 *  1. 让管理控制台看到 App 用户"在线"状态
 *  2. 接收服务端推送的实时消息（角色更新、galgame 同步等）
 *
 * 使用方式：
 *   SyncWebSocketManager.start(prefs)   // 登录后调用
 *   SyncWebSocketManager.stop()         // 退出登录时调用
 */
object SyncWebSocketManager {

    private const val TAG = "SyncWS"
    /** 角色主动消息与 AI 回复完成共用，与 [PonyChatApp.createNotificationChannels] 一致 */
    private const val ROLE_MESSAGE_CHANNEL_ID = "ai_message_v3"

    /** 本会话已处理过的 outbox_id，避免 WS 补推与 HTTP 兜底重复通知 */
    private val seenOutboxIds = java.util.Collections.synchronizedSet(mutableSetOf<String>())

    /** 客户端发送 ping 的间隔（秒） */
    private const val PING_EVERY_SEC = 25

    /** 长时间未收到任何帧则主动断开并重连（毫秒） */
    private const val RX_IDLE_DISCONNECT_MS = 60_000L

    /** 重连退避上限（毫秒） */
    private const val MAX_RECONNECT_DELAY_MS = 30_000L

    /**
     * 每次 [nudgeReconnect] 自增。当前会话的保活循环在 [sessionEpoch] 上捕获；
     * 值变化时立即退出内层循环，避免在已被 nudge 关闭的套接字上发 ping 误报「ping failed」。
     */
    private val nudgeEpoch = AtomicInteger(0)
    @Volatile
    private var lastNudgeWallMs: Long = 0L
    private val nudgeLock = Any()
    /** 两次 nudge 至少间隔，合并短时间多次 ON_START/网络可用（毫秒） */
    private const val NUDGE_MIN_INTERVAL_MS = 5_000L

    private fun nextBackoffMs(current: Long): Long {
        val cap = (current * 2).coerceAtMost(MAX_RECONNECT_DELAY_MS)
        val jitter = 0.8 + kotlin.random.Random.nextDouble() * 0.4
        return (cap * jitter).toLong().coerceAtLeast(1_000L)
    }

    private fun parseMessageCountValue(value: Any?): Int {
        return when (value) {
            is Number -> value.toInt()
            is String -> value.trim().toIntOrNull() ?: 0
            is JSONArray -> value.length()
            is Collection<*> -> value.size
            else -> 0
        }.coerceAtLeast(0)
    }

    private fun chatCompleteMessageCount(payload: Map<*, *>): Int {
        val explicit = parseMessageCountValue(
            payload["message_count"]
                ?: payload["bubble_count"]
                ?: payload["assistant_message_count"]
        )
        if (explicit > 0) return explicit
        return parseMessageCountValue(payload["assistant_message_ids"]).takeIf { it > 0 } ?: 1
    }

    private fun chatCompleteMessageCount(json: JSONObject): Int {
        val explicit = parseMessageCountValue(
            json.opt("message_count")
                ?: json.opt("bubble_count")
                ?: json.opt("assistant_message_count")
        )
        if (explicit > 0) return explicit
        return parseMessageCountValue(json.opt("assistant_message_ids")).takeIf { it > 0 } ?: 1
    }

    private var scope: CoroutineScope? = null
    private var ws: WebSocket? = null
    private val running = AtomicBoolean(false)
    private var currentPrefs: AppPreferences? = null
    private var appContext: Context? = null
    private val gson = Gson()
    @Volatile
    private var activeChatPayload: String? = null
    @Volatile
    private var activeCharacterId: String? = null
    @Volatile
    private var activeMode: String? = null
    @Volatile
    private var activeConversationId: String? = null

    private val _messageUpdateFlow = MutableSharedFlow<MessageVoiceUpdate>(extraBufferCapacity = 16)
    val messageUpdateFlow: SharedFlow<MessageVoiceUpdate> = _messageUpdateFlow.asSharedFlow()

    /**
     * 尽早设置 [appContext]，避免登录后、前台服务 [onStartCommand] 尚未执行时调用
     * [pullUndeliveredOnce] 导致无法弹出角色消息系统通知。
     */
    fun bindNotificationContext(context: Context) {
        appContext = context.applicationContext
        NotificationTrace.log("bind_ctx", "appContext set")
    }

    /**
     * 登录后启动，传入 prefs 用于读取 username 和 baseUrl；context 用于发送系统通知。
     * [force] 为 true 时总是取消并重连（内部或排障用）；默认在同一会话且保活协程仍在跑时直接返回，
     * 避免 [ConnectionService.onStartCommand] 等重复进入时误杀已有 WebSocket。
     */
    fun start(prefs: AppPreferences, context: Context? = null, force: Boolean = false) {
        if (!prefs.isLoggedIn()) {
            NotificationTrace.log("ws_start", "skip not_logged_in")
            return
        }
        if (context != null) appContext = context.applicationContext

        val sameSession = !force &&
            running.get() &&
            scope?.isActive == true &&
            currentPrefs?.username == prefs.username &&
            currentPrefs?.effectiveApiBase() == prefs.effectiveApiBase()

        if (sameSession) {
            NotificationTrace.log("ws_start", "skip_already_running user=${prefs.username}")
            return
        }

        currentPrefs = prefs
        running.set(true)
        scope?.cancel()
        scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        NotificationTrace.log("ws_start", "user=${prefs.username} hasCtx=${appContext != null} force=$force")
        scope!!.launch { connectLoop() }
    }

    /** 退出登录时停止 */
    fun stop() {
        running.set(false)
        ws?.close(1000, "logout")
        ws = null
        scope?.cancel()
        scope = null
        currentPrefs = null
        appContext = null
        activeChatPayload = null
        seenOutboxIds.clear()
        MessageNotifyDeduper.clear()
        NotificationTrace.log("ws_stop", "cleared")
        Log.i(TAG, "stopped")
    }

    fun setActiveChat(characterId: String, mode: String, conversationId: String?) {
        val cid = characterId.trim()
        val conv = conversationId?.trim().orEmpty()
        if (cid.isBlank() || conv.isBlank()) {
            clearActiveChat(characterId, mode, conversationId)
            return
        }
        val payload = JSONObject()
            .put("type", "active_chat")
            .put("character_id", cid)
            .put("mode", mode.ifBlank { "normal" })
            .put("conversation_id", conv)
            .toString()
        activeChatPayload = payload
        activeCharacterId = cid
        activeMode = mode.ifBlank { "normal" }
        activeConversationId = conv
        ws?.send(payload)
    }

    fun clearActiveChat(characterId: String? = null, mode: String? = null, conversationId: String? = null) {
        activeChatPayload = null
        activeCharacterId = null
        activeMode = null
        activeConversationId = null
        val payload = JSONObject().put("type", "chat_inactive")
        characterId?.trim()?.takeIf { it.isNotBlank() }?.let { payload.put("character_id", it) }
        mode?.trim()?.takeIf { it.isNotBlank() }?.let { payload.put("mode", it) }
        conversationId?.trim()?.takeIf { it.isNotBlank() }?.let { payload.put("conversation_id", it) }
        ws?.send(payload.toString())
    }

    private fun chatCompleteTsFromPayload(payload: Map<*, *>): Long {
        val n = payload["completed_at_ms"] ?: return System.currentTimeMillis()
        val v = (n as? Number)?.toLong() ?: n.toString().toLongOrNull() ?: 0L
        return v.takeIf { it > 0L } ?: System.currentTimeMillis()
    }

    private fun chatCompleteTsFromJson(json: JSONObject): Long {
        val v = json.optLong("completed_at_ms", 0L)
        return v.takeIf { it > 0L } ?: System.currentTimeMillis()
    }

    private fun emitVoiceUpdateFromChatCompletePayload(payload: Map<*, *>) {
        if (payload["voice_state"] == null && payload["voiceState"] == null) return
        runCatching {
            emitVoiceUpdateFromChatCompleteJson(JSONObject(gson.toJson(payload)))
        }.onFailure {
            Log.d(TAG, "chat_complete voice payload parse failed: ${it.message}")
        }
    }

    private fun emitVoiceUpdateFromChatCompleteJson(json: JSONObject) {
        val messageId = json.optString("message_id", "").trim()
        if (messageId.isBlank()) return
        val voiceObj = json.optJSONObject("voice_state") ?: json.optJSONObject("voiceState") ?: return
        val patch = JSONObject(voiceObj.toString())
        val audioObj = json.optJSONObject("audio_transfer") ?: json.optJSONObject("audioTransfer")
        val characterId = json.optString("character_id", "").trim()
        val conversationId = json.optString("conversation_id", "").trim()
        val cacheKey = voiceObj.optString("voice_cache_key", "").trim().ifBlank { null }
            ?: voiceObj.optString("voiceCacheKey", "").trim().ifBlank { null }
        if (audioObj != null) {
            val ctx = appContext
            val transfer = runCatching {
                gson.fromJson(audioObj.toString(), VoiceAudioTransfer::class.java)
            }.getOrNull()
            val cached = if (ctx != null && cacheKey != null && transfer != null) {
                ChatVoiceCache.save(ctx, cacheKey, transfer)
            } else {
                null
            }
            if (cached != null) {
                patch.put("local_file", cached.localFile)
                patch.put("duration_ms", cached.durationMs)
                patch.put("waveform", JSONArray().apply {
                    cached.waveform.forEach { put(it.toDouble()) }
                })
                if (cacheKey != null) {
                    ackCachedVoiceAudio(characterId, conversationId, messageId, cacheKey)
                }
            } else {
                patch.put("audio_transfer", audioObj)
            }
        }
        val updateJson = JSONObject()
            .put("character_id", characterId)
            .put("conversation_id", conversationId)
            .put("message_id", messageId)
            .put("updated_at_ms", chatCompleteTsFromJson(json))
            .put("patch", patch)
        val update = gson.fromJson(updateJson.toString(), MessageVoiceUpdate::class.java)
        if (!update.messageId.isNullOrBlank()) {
            _messageUpdateFlow.tryEmit(update)
        }
    }

    private fun ackCachedVoiceAudio(
        characterId: String,
        conversationId: String,
        messageId: String,
        voiceCacheKey: String,
    ) {
        val prefs = currentPrefs ?: return
        if (prefs.username.isBlank() || characterId.isBlank() || conversationId.isBlank() || messageId.isBlank()) return
        val runner = scope ?: CoroutineScope(Dispatchers.IO + SupervisorJob())
        runner.launch {
            runCatching {
                NetworkClient.createApiService(prefs).ackMessageVoiceAudio(
                    mapOf(
                        "username" to prefs.username,
                        "character_id" to characterId,
                        "conversation_id" to conversationId,
                        "message_id" to messageId,
                        "voice_cache_key" to voiceCacheKey,
                    )
                )
            }.onFailure {
                Log.d(TAG, "voice audio ack failed: ${it.message}")
            }
        }
    }

    private fun tryConsumeOutbox(id: String): Boolean {
        if (id.isBlank()) return true
        synchronized(seenOutboxIds) {
            if (seenOutboxIds.contains(id)) return false
            seenOutboxIds.add(id)
            return true
        }
    }

    private fun sendWsAck(outboxId: String) {
        if (outboxId.isBlank()) return
        try {
            val j = JSONObject()
            j.put("type", "msg_ack")
            val arr = JSONArray()
            arr.put(outboxId)
            j.put("outbox_ids", arr)
            ws?.send(j.toString())
        } catch (e: Exception) {
            Log.d(TAG, "sendWsAck failed: ${e.message}")
        }
    }

    private fun notificationTitleFromPayload(
        context: Context,
        payload: Map<*, *>,
        characterId: String,
    ): String {
        val direct = listOf("character_name", "characterName", "display_name", "displayName", "name")
            .firstNotNullOfOrNull { key -> payload[key]?.toString()?.trim()?.takeIf { it.isNotBlank() } }
        return resolveCharacterNotificationTitle(context, characterId, direct)
    }

    private fun notificationTitleFromJson(
        context: Context,
        json: JSONObject,
        characterId: String,
    ): String {
        val direct = listOf("character_name", "characterName", "display_name", "displayName", "name")
            .firstNotNullOfOrNull { key -> json.optString(key, "").trim().takeIf { it.isNotBlank() } }
        return resolveCharacterNotificationTitle(context, characterId, direct)
    }

    private fun conversationIdFromPayload(payload: Map<*, *>): String? {
        return listOf("conversation_id", "conversationId", "conversation")
            .firstNotNullOfOrNull { key ->
                payload[key]?.toString()?.trim()?.takeIf { it.isNotBlank() }
            }
    }

    private fun conversationIdFromJson(json: JSONObject): String? {
        return listOf("conversation_id", "conversationId", "conversation")
            .firstNotNullOfOrNull { key ->
                json.optString(key, "").trim().takeIf { it.isNotBlank() }
            }
    }

    private fun resolveCharacterNotificationTitle(
        context: Context,
        characterId: String,
        explicitName: String? = null,
    ): String {
        explicitName?.trim()?.takeIf { it.isNotBlank() }?.let { return it }
        val ctx = context.applicationContext
        val prefs = currentPrefs ?: AppPreferences(ctx)
        val username = prefs.username.trim()
        if (username.isNotBlank() && characterId.isNotBlank()) {
            runCatching {
                LocalCacheStore(ctx).loadCharacters(username)
                    .firstOrNull { it.id == characterId || it.stableId() == characterId }
                    ?.displayName()
                    ?.trim()
                    ?.takeIf { it.isNotBlank() }
            }.getOrNull()?.let { return it }
        }
        return characterId.ifBlank { "角色" }
    }

    private fun isCurrentActiveChat(characterId: String, mode: String, conversationId: String?): Boolean {
        val cid = characterId.trim()
        if (cid.isBlank()) return false
        val md = mode.ifBlank { "normal" }.trim()
        if (activeCharacterId != cid || activeMode != md) return false
        val activeConv = activeConversationId?.trim().orEmpty()
        val incomingConv = conversationId?.trim().orEmpty()
        if (activeConv.isNotBlank() && incomingConv.isNotBlank() && activeConv != incomingConv) return false
        return ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
    }

    /**
     * HTTP 兜底：拉取未送达 outbox，展示后批量 ACK（由 ConnectionService 延迟调用）。
     */
    @Suppress("UNCHECKED_CAST")
    fun pullUndeliveredOnce(prefs: AppPreferences, trigger: String = "unspecified") {
        if (!prefs.isLoggedIn()) {
            NotificationTrace.log("pull_skip", "trigger=$trigger reason=not_logged_in")
            return
        }
        NotificationTrace.log("pull_begin", "trigger=$trigger user=${prefs.username}")
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val api = NetworkClient.createApiService(prefs)
                val resp = api.getUndeliveredMessages()
                if (!resp.isSuccessful) {
                    NotificationTrace.log("pull_http", "trigger=$trigger code=${resp.code()}")
                    return@launch
                }
                val body = resp.body() ?: run {
                    NotificationTrace.log("pull_http", "trigger=$trigger empty_body")
                    return@launch
                }
                val list = body["messages"] as? List<*> ?: run {
                    NotificationTrace.log("pull_http", "trigger=$trigger no_messages_key")
                    return@launch
                }
                NotificationTrace.log("pull_batch", "trigger=$trigger msg_count=${list.size}")
                val toAck = mutableListOf<String>()
                for (item in list) {
                    val m = item as? Map<*, *> ?: continue
                    val oid = m["outbox_id"]?.toString()?.trim().orEmpty()
                    if (oid.isNotBlank() && !tryConsumeOutbox(oid)) {
                        NotificationTrace.log("pull_dup", "trigger=$trigger outbox_id=$oid skip_duplicate")
                        continue
                    }
                    val msgType = m["msg_type"]?.toString().orEmpty()
                    val payload = m["payload"] as? Map<*, *> ?: emptyMap<String, Any>()
                    if (msgType == "chat_complete") {
                        NotificationTrace.log("pull_item", "trigger=$trigger chat_complete oid=$oid char=${payload["character_id"]}")
                        val previewRaw = payload["preview"]?.toString().orEmpty()
                        val characterId = payload["character_id"]?.toString().orEmpty()
                        val mode = payload["mode"]?.toString()?.ifBlank { "normal" } ?: "normal"
                        val sceneMap = GalgameNotificationPreview.normalizeSceneMap(payload["scene"])
                        val scoreReason = payload["score_delta_reason"]?.toString()?.trim()?.ifBlank { null }
                        val preview = GalgameNotificationPreview.resolveForChatComplete(mode, previewRaw, sceneMap, scoreReason)
                        val messageId = payload["message_id"]?.toString()?.trim().orEmpty()
                        emitVoiceUpdateFromChatCompletePayload(payload)
                        val ts = chatCompleteTsFromPayload(payload)
                        val messageCount = if (mode.startsWith("galgame")) 1 else chatCompleteMessageCount(payload)
                        val skipDup = characterId.isNotBlank() &&
                            !MessageNotifyDeduper.markIfFirst(
                                "pull",
                                "chat_complete",
                                oid.ifBlank { null },
                                messageId.ifBlank { null },
                            )
                        if (skipDup) {
                            NotificationTrace.log("pull_dup", "trigger=$trigger chat_complete deduped oid=$oid")
                        } else {
                            if (characterId.isNotBlank()) {
                                prefs.setModeLastChatSnippet(
                                    characterId,
                                    mode,
                                    GalgameNotificationPreview.stripMarkdownForListPreview(preview),
                                )
                            }
                            // 与前台 [ChatViewModel.emitForegroundChatCompleted] 使用同一 message_id，避免与 outbox_id 不一致导致未读 +2
                            ChatEventBus.notifyCompleted(
                                characterId,
                                mode,
                                ts,
                                ChatCompletionSource.HTTP_PULL,
                                messageId.ifBlank { oid }.ifBlank { null },
                                messageCount = messageCount,
                            )
                            showChatCompleteNotification(
                                appContext?.let { notificationTitleFromPayload(it, payload, characterId) }
                                    ?: characterId.ifBlank { "角色" },
                                preview,
                                characterId,
                                mode,
                                messageId.ifBlank { null },
                                oid.ifBlank { null },
                                conversationId = conversationIdFromPayload(payload),
                                notificationCount = messageCount,
                            )
                        }
                    }
                    if (oid.isNotBlank()) toAck.add(oid)
                }
                if (toAck.isNotEmpty()) {
                    api.ackOutbox(mapOf("outbox_ids" to toAck))
                    NotificationTrace.log("pull_ack", "trigger=$trigger count=${toAck.size}")
                } else {
                    NotificationTrace.log("pull_done", "trigger=$trigger nothing_to_ack")
                }
            } catch (e: Exception) {
                NotificationTrace.log("pull_err", "trigger=$trigger ${e.message}")
                Log.w(TAG, "pullUndelivered: ${e.message}")
            }
        }
    }

    private suspend fun connectLoop() {
        var delayMs = 1_000L
        var connectAttempt = 0
        while (running.get()) {
            val prefs = currentPrefs ?: break
            val username = prefs.username
            if (username.isBlank()) break
            val wsUrl = buildWsUrl(prefs, username)
            if (wsUrl == null) {
                Log.w(TAG, "no valid base url, retry later")
                NotificationTrace.log("ws_connect_skip", "reason=no_url user=$username")
                delay(10_000)
                continue
            }
            connectAttempt++
            NotificationTrace.log("ws_connect_try", "attempt=$connectAttempt url=$wsUrl nudgeEp=${nudgeEpoch.get()}")

            val connected = CompletableDeferred<Boolean>()
            val lastRxAt = AtomicLong(System.currentTimeMillis())
            val client = NetworkClient.createTrustAllClient(
                connectTimeoutSec = 15,
                readTimeoutSec = 90,
                writeTimeoutSec = 15,
                // WebSocket 层 RFC ping，利于穿越 NAT/代理；与下文应用层 "ping"/"pong" 文本并存
                pingIntervalSec = PING_EVERY_SEC.toLong()
            )
            val request = Request.Builder().url(wsUrl).build()

            ws = client.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    val code = response.code
                    val proto = response.protocol
                    Log.i(TAG, "connected: $wsUrl")
                    lastRxAt.set(System.currentTimeMillis())
                    delayMs = 1_000L
                    connected.complete(true)
                    NotificationTrace.log("ws_open", "code=$code protocol=$proto url=$wsUrl")
                    activeChatPayload?.let { webSocket.send(it) }
                    // 连接一建立即 HTTP 补拉：新安装时 WS 晚于首条回复完成，防漏通知与未读
                    currentPrefs?.let { pullUndeliveredOnce(it, "ws_onOpen") }
                    ChatEventBus.notifyNetworkAvailable()
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    lastRxAt.set(System.currentTimeMillis())
                    if (text == "ping") {
                        webSocket.send("pong")
                        return
                    }
                    // 服务端对客户端 ping 的文本回应；勿当 JSON 解析（否则会 handleServerMessage failed）
                    if (text == "pong") return
                    handleServerMessage(text, webSocket)
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, reason)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    Log.i(TAG, "closed code=$code reason=$reason")
                    if (!connected.isCompleted) connected.complete(false)
                    NotificationTrace.log("ws_closed", "code=$code reason=${reason.ifBlank { "(empty)" }} url=$wsUrl")
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    val http = response?.code
                    Log.w(TAG, "failure: ${t.message} http=$http", t)
                    if (!connected.isCompleted) connected.complete(false)
                    NotificationTrace.log("ws_fail", "http=$http ex=${t.javaClass.simpleName} msg=${t.message}")
                }
            })

            val ok = withTimeoutOrNull(20_000L) { connected.await() } ?: false
            if (!ok || !running.get()) {
                ws?.cancel()
                ws = null
                if (!running.get()) break
                NotificationTrace.log("ws_handshake_fail", "ok=$ok open_timeout_or_failed backoff=${delayMs}ms")
                Log.i(TAG, "reconnect in ${delayMs}ms")
                delay(delayMs)
                delayMs = nextBackoffMs(delayMs)
                continue
            }

            // 与本次 TCP 建连绑定的 nudge 世代：nudge 自增后与此不等则立刻退出，不发 ping
            val sessionEpoch = nudgeEpoch.get()
            // 连接成功：每秒检查读超时，每 25s 发 ping
            var loopExit: String? = null
            try {
                var sec = 0
                var tick = 0
                while (running.get()) {
                    delay(1_000L)
                    if (!running.get()) {
                        loopExit = "stop_running"
                        break
                    }
                    if (nudgeEpoch.get() != sessionEpoch) {
                        loopExit = "nudge_epoch"
                        NotificationTrace.log("ws_loop_exit", "reason=$loopExit sessionEp=$sessionEpoch nowEp=${nudgeEpoch.get()}")
                        break
                    }
                    val now = System.currentTimeMillis()
                    val idle = now - lastRxAt.get()
                    if (tick % 30 == 0 && tick > 0) {
                        NotificationTrace.log("ws_tick", "idle_ms=$idle url=$wsUrl ep=$sessionEpoch")
                    }
                    tick++
                    if (idle > RX_IDLE_DISCONNECT_MS) {
                        loopExit = "rx_idle"
                        Log.w(TAG, "rx idle timeout, reconnecting idleMs=$idle")
                        NotificationTrace.log("ws_loop_exit", "reason=$loopExit idleMs=$idle")
                        break
                    }
                    sec++
                    if (sec >= PING_EVERY_SEC) {
                        sec = 0
                        if (nudgeEpoch.get() != sessionEpoch) {
                            loopExit = "nudge_epoch_before_ping"
                            NotificationTrace.log("ws_loop_exit", "reason=$loopExit")
                            break
                        }
                        val sent = ws?.send("ping") ?: false
                        if (!sent) {
                            loopExit = "ping_send_failed"
                            Log.w(TAG, "ping send returned false, reconnecting (socket likely closed)")
                            NotificationTrace.log("ws_loop_exit", "reason=$loopExit ep=$sessionEpoch")
                            break
                        }
                        // 后台/厂商节电时下行文本可能长时间不到，但 ping 已入队；避免仅靠收不到 pong 误判 rx_idle
                        lastRxAt.set(System.currentTimeMillis())
                        NotificationTrace.log("ws_ping_out", "ok=true ep=$sessionEpoch")
                    }
                }
            } catch (e: CancellationException) {
                throw e
            }

            if (loopExit == "nudge_epoch" || loopExit == "nudge_epoch_before_ping") {
                // nudge 已或即将关闭，不再二次 close，避免与正常重连竟态
                ws = null
                if (!running.get()) break
                NotificationTrace.log("ws_reconnect", "after=$loopExit delay=400ms")
                delay(400L)
                delayMs = 1_000L
                continue
            }

            if (loopExit == "stop_running") {
                ws = null
                break
            }

            try {
                ws?.close(1001, "reconnect")
            } catch (_: Exception) { }
            ws = null
            if (!running.get()) break
            if (loopExit == "ping_send_failed" || loopExit == "rx_idle") {
                delayMs = 1_000L
            }
            NotificationTrace.log("ws_reconnect", "after=${loopExit ?: "unknown"} backoff=${delayMs}ms")
            Log.i(TAG, "reconnect backoff ${delayMs}ms exit=$loopExit")
            delay(delayMs)
            delayMs = nextBackoffMs(delayMs)
        }
        Log.i(TAG, "connectLoop exited")
        NotificationTrace.log("ws_connect_loop_end", "running=${running.get()}")
    }

    /** 网络恢复或进程回到前台时可调用，尽快重连并补拉 outbox。带防抖，减少短时间重复 nudge 导致的无意义断连。 */
    fun nudgeReconnect() {
        val s = scope ?: return
        if (!running.get()) return
        val now = System.currentTimeMillis()
        val ep = synchronized(nudgeLock) {
            if (now - lastNudgeWallMs < NUDGE_MIN_INTERVAL_MS) {
                NotificationTrace.log("ws_nudge", "debounced ageMs=${now - lastNudgeWallMs} min=$NUDGE_MIN_INTERVAL_MS")
                return
            }
            lastNudgeWallMs = now
            nudgeEpoch.incrementAndGet()
        }
        NotificationTrace.log("ws_nudge", "epoch=$ep close_pending")
        s.launch(Dispatchers.IO) {
            try {
                ws?.close(1001, "nudge")
            } catch (e: Exception) {
                NotificationTrace.log("ws_nudge", "close_err=${e.message}")
            }
        }
    }

    /** 处理服务端推送的 JSON 消息 */
    private fun handleServerMessage(text: String, receivingSocket: WebSocket) {
        try {
            val json = JSONObject(text)
            val t = json.optString("type", "?")
            NotificationTrace.log("ws_frame", "type=$t len=${text.length}")
            when (t) {
                "force_logout" -> {
                    val reason = json.optString("reason", "logged_in_elsewhere")
                    // Stale-socket 守卫：nudge 重连时，服务端会对旧连接推送 force_logout。
                    // 此时 connectLoop 已将 ws 更新为新 socket（或 null），旧 socket 的回调
                    // 不应触发真实登出，否则就是「同一设备重进 App 被误判重复登录」。
                    // 只有当消息来自当前活跃 socket 时，才视为真实的新登录踢出。
                    if (receivingSocket !== ws) {
                        NotificationTrace.log("ws_force_logout_stale", "reason=$reason stale_socket=true")
                        Log.d(TAG, "忽略旧连接上的 force_logout（stale socket），不触发登出: reason=$reason")
                        return
                    }
                    Log.w(TAG, "收到强制登出指令: reason=$reason")
                    val prefs = currentPrefs
                    if (prefs != null) {
                        prefs.logout()
                    }
                    // 停止 WS 重连循环
                    running.set(false)
                    ws?.cancel()
                    ws = null
                    scope?.cancel()
                    scope = null
                    // 通知 UI 跳转到登录页
                    AuthEventBus.emitForceLogout(reason)
                }
                "chat_complete" -> {
                    val prefs = currentPrefs ?: return
                    val outboxId = json.optString("outbox_id", "")
                    if (outboxId.isNotBlank() && !tryConsumeOutbox(outboxId)) {
                        NotificationTrace.log("ws_dup", "chat_complete outbox=$outboxId already_seen")
                        sendWsAck(outboxId)
                        return
                    }
                    NotificationTrace.log("ws_chat_done", "char=${json.optString("character_id")} mode=${json.optString("mode")} outbox=$outboxId")
                    val previewRaw = json.optString("preview", "")
                    val characterId = json.optString("character_id", "")
                    val mode = json.optString("mode", "normal").ifBlank { "normal" }
                    val scoreReason = json.optString("score_delta_reason", "").trim().ifBlank { null }
                    val preview = GalgameNotificationPreview.resolveForChatCompleteJson(
                        mode,
                        previewRaw,
                        json.optJSONObject("scene"),
                        scoreReason,
                    )
                    val messageId = json.optString("message_id", "").trim()
                    emitVoiceUpdateFromChatCompleteJson(json)
                    val messageCount = if (mode.startsWith("galgame")) 1 else chatCompleteMessageCount(json)
                    if (characterId.isNotBlank()) {
                        if (!MessageNotifyDeduper.markIfFirst(
                                "ws",
                                "chat_complete",
                                outboxId.ifBlank { null },
                                messageId.ifBlank { null },
                            )
                        ) {
                            NotificationTrace.log("ws_dup", "chat_complete deduped (cross-channel or replay)")
                            if (outboxId.isNotBlank()) sendWsAck(outboxId)
                            return
                        }
                    }
                    if (characterId.isNotBlank()) {
                        prefs.setModeLastChatSnippet(
                            characterId,
                            mode,
                            GalgameNotificationPreview.stripMarkdownForListPreview(preview),
                        )
                    }
                    ChatEventBus.notifyCompleted(
                        characterId,
                        mode,
                        chatCompleteTsFromJson(json),
                        ChatCompletionSource.WS,
                        messageId.ifBlank { outboxId }.ifBlank { null },
                        messageCount = messageCount,
                    )
                    showChatCompleteNotification(
                        appContext?.let { notificationTitleFromJson(it, json, characterId) }
                            ?: characterId.ifBlank { "角色" },
                        preview,
                        characterId,
                        mode,
                        messageId.ifBlank { null },
                        outboxId.ifBlank { null },
                        conversationId = conversationIdFromJson(json),
                        notificationCount = messageCount,
                    )
                    if (outboxId.isNotBlank()) sendWsAck(outboxId)
                }
                "message_updated" -> {
                    val update = gson.fromJson(text, MessageVoiceUpdate::class.java)
                    if (!update.messageId.isNullOrBlank()) {
                        _messageUpdateFlow.tryEmit(update)
                    }
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "handleServerMessage failed: ${e.message}")
        }
    }

    /** 与角色列表第二行一致的去 MD/HTML，再截断为 10 字 + 省略号（系统通知栏宽度有限）。 */
    private fun stripNotificationPreview(text: String): String {
        val clean = GalgameNotificationPreview.stripMarkdownForListPreview(text)
        return if (clean.length > 10) "${clean.take(10)}…" else clean
    }

    /** AI 回复已写入会话后的提醒（后台/锁屏时可见） */
    private fun showChatCompleteNotification(
        title: String,
        preview: String,
        characterId: String,
        mode: String = "normal",
        messageId: String? = null,
        outboxId: String? = null,
        conversationId: String? = null,
        notificationCount: Int = 1,
    ) {
        val ctx = appContext ?: run {
            NotificationTrace.log("notify_skip", "chat_complete no_appContext char=$characterId")
            return
        }
        postChatCompleteNotificationWithContext(
            ctx,
            title,
            preview,
            characterId,
            mode,
            "ws_or_pull",
            messageId,
            outboxId,
            conversationId,
            notificationCount
        )
    }

    /**
     * 游戏/锁分 SSE 在后台完成时，WS `chat_complete` 可能未触发通知；
     * 与 WS 路径共用同一 notificationId，避免重复响铃。
     */
    fun postChatCompleteFallbackFromGalgame(
        context: Context,
        characterId: String,
        mode: String,
        preview: String,
    ) {
        if (characterId.isBlank()) return
        val ctx = context.applicationContext
        postChatCompleteNotificationWithContext(
            ctx,
            resolveCharacterNotificationTitle(ctx, characterId),
            preview,
            characterId,
            mode.ifBlank { "normal" },
            "galgame_sse_bg",
            null,
            null,
            null,
            1,
        )
    }

    private fun postChatCompleteNotificationWithContext(
        ctx: Context,
        title: String,
        preview: String,
        characterId: String,
        mode: String,
        traceSource: String,
        messageId: String? = null,
        outboxId: String? = null,
        conversationId: String? = null,
        notificationCount: Int = 1,
    ) {
        val key = messageId?.takeIf { it.isNotBlank() }
            ?: outboxId?.takeIf { it.isNotBlank() }
            ?: "${preview.hashCode()}_${System.currentTimeMillis()}"
        val nid = ("cc_${characterId}_${mode}_$key").hashCode()
        NotificationTrace.log("notify_show", "chat_complete char=$characterId mode=$mode mid=${messageId.orEmpty()} oid=${outboxId.orEmpty()} nid=$nid src=$traceSource")
        deliverRoleMessageNotification(
            ctx = ctx,
            pendingIntentRequestCode = nid,
            notificationId = nid,
            title = title,
            rawBody = preview,
            characterId = characterId,
            mode = mode,
            conversationId = conversationId,
            notificationCount = notificationCount,
        )
    }

    private fun deliverRoleMessageNotification(
        ctx: Context,
        pendingIntentRequestCode: Int,
        notificationId: Int,
        title: String,
        rawBody: String,
        characterId: String,
        mode: String,
        conversationId: String? = null,
        notificationCount: Int = 1,
    ) {
        if (
            ChatEventBus.shouldSuppressRoleNotification(characterId, mode) ||
            isCurrentActiveChat(characterId, mode, conversationId)
        ) {
            MessageVibrationHelper.vibrateForMessage(ctx)
            NotificationTrace.log("notify_skip", "foreground_same_chat_vibrate char=$characterId mode=$mode nid=$notificationId")
            return
        }
        if (!RoleNotificationHelper.canPostRoleNotifications(ctx)) {
            val why = RoleNotificationHelper.roleNotificationBlockHint(ctx) ?: "canPost=false"
            NotificationTrace.log("notify_blocked", "nid=$notificationId title=$title reason=$why")
            Log.w(TAG, "role notification skipped: $why")
            return
        }
        val intent = Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_character_id", characterId)
            putExtra("open_mode", mode.ifBlank { "normal" })
        }
        val pi = PendingIntent.getActivity(
            ctx, pendingIntentRequestCode, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val text = stripNotificationPreview(rawBody).ifBlank { "点击查看" }
        val n = NotificationCompat.Builder(ctx, ROLE_MESSAGE_CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setNumber(notificationCount.coerceAtLeast(1))
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        NotificationManagerCompat.from(ctx).notify(notificationId, n)
        MessageVibrationHelper.vibrateForMessage(ctx)
        NotificationTrace.log("notify_posted", "nid=$notificationId title=$title char=$characterId mode=$mode")
    }

    /**
     * 将 http(s)://host:port 转换为 ws(s)://host:port/ws/{username}
     */
    private fun buildWsUrl(prefs: AppPreferences, username: String): String? {
        val base = prefs.effectiveApiBase().trimEnd('/')
        if (base.isBlank()) return null
        val wsBase = when {
            base.startsWith("https://") -> base.replace("https://", "wss://")
            base.startsWith("http://")  -> base.replace("http://", "ws://")
            else -> return null
        }
        return "$wsBase/ws/$username?client_id=android"
    }
}
