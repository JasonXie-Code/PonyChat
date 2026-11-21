package top.ponychat.webview.util

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import top.ponychat.webview.data.prefs.AppPreferences
import java.util.concurrent.ConcurrentHashMap

/** 聊天完成事件的来源，用于跨通道去重（同一条完成可能经前台流式 + WS 各到达一次）。 */
enum class ChatCompletionSource {
    FOREGROUND,
    WS,
    HTTP_PULL,
}

data class ChatCompletedEvent(
    val characterId: String,
    val mode: String,
    val timestamp: Long,
    val source: ChatCompletionSource,
    val messageCount: Int = 1,
    val messageId: String? = null,
    val conversationId: String? = null,
)

/**
 * 全局聊天完成 / 未读计数总线。
 * - 列表页订阅 [completedFlow] 以立即刷新「最近对话」排序；
 * - 订阅 [unreadCounts] 展示角色卡角标；
 * - [ChatScreen] 在 ON_RESUME 时 [setActiveChat] + [markRead]，ON_PAUSE 时 [clearActiveChat]。
 * - 角色主动消息与「普通对话」一致，经 [notifyCompleted] 且 **mode 固定为 `normal`**（与跳转 `open_mode` 一致）。
 */
object ChatEventBus {

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var prefs: AppPreferences? = null

    private val _completed = MutableSharedFlow<ChatCompletedEvent>(
        extraBufferCapacity = 32,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val completedFlow: SharedFlow<ChatCompletedEvent> = _completed.asSharedFlow()

    private val _networkAvailable = MutableSharedFlow<Long>(
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val networkAvailableFlow: SharedFlow<Long> = _networkAvailable.asSharedFlow()

    private val _unread = MutableStateFlow<Map<String, Int>>(emptyMap())
    val unreadCounts: StateFlow<Map<String, Int>> = _unread.asStateFlow()

    @Volatile
    private var activeCharId: String? = null

    @Volatile
    private var activeMode: String? = null

    private val dedupeCorr = ConcurrentHashMap<String, Long>()
    private data class LastEmit(val time: Long, val source: ChatCompletionSource, val corr: String?)
    private val lastEmitByKey = ConcurrentHashMap<String, LastEmit>()

    private var persistJob: Job? = null

    fun attach(preferences: AppPreferences) {
        prefs = preferences
        _unread.value = preferences.readUnreadMap()
    }

    fun setActiveChat(characterId: String, mode: String) {
        activeCharId = characterId.takeIf { it.isNotBlank() }
        activeMode = normMode(mode)
    }

    fun clearActiveChat() {
        activeCharId = null
        activeMode = null
    }

    /**
     * 用户正停留在此角色+模式的聊天页且 App 处于前台时，不应再弹系统通知（已在当前界面可见）。
     * 与 [ChatScreen] 的 ON_RESUME [setActiveChat] / ON_PAUSE [clearActiveChat] 配套。
     */
    fun shouldSuppressRoleNotification(characterId: String, mode: String): Boolean {
        val cid = characterId.trim().ifBlank { return false }
        val md = normMode(mode)
        val a = activeCharId ?: return false
        val am = activeMode ?: return false
        if (a != cid || am != md) return false
        return ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
    }

    private fun normMode(m: String): String {
        val t = m.ifBlank { "normal" }.trim()
        return when (t) {
            "normal", "galgame", "galgame_lock" -> t
            else -> t
        }
    }

    private fun sourcePri(s: ChatCompletionSource): Int = when (s) {
        ChatCompletionSource.FOREGROUND -> 3
        ChatCompletionSource.WS -> 2
        ChatCompletionSource.HTTP_PULL -> 1
    }

    private fun chatKey(characterId: String, mode: String): String {
        val cid = characterId.trim()
        return "$cid#${normMode(mode)}"
    }

    /**
     * @param correlationId 建议非空：前台用助手消息 id，WS/HTTP 用 outbox_id，用于精确去重。
     * @param messageCount 本次完成对应的用户可见气泡数；普通对话后端拆成多气泡时用于未读角标按气泡计数。
     */
    fun notifyCompleted(
        characterId: String,
        mode: String,
        timestamp: Long,
        source: ChatCompletionSource,
        correlationId: String? = null,
        messageCount: Int = 1,
        messageId: String? = null,
        conversationId: String? = null,
    ) {
        val cid = characterId.trim().ifBlank { return }
        val md = normMode(mode)
        val key = chatKey(cid, md)
        val now = System.currentTimeMillis()
        val corr = correlationId?.trim()?.takeIf { it.isNotBlank() }
        val unreadIncrement = messageCount.coerceAtLeast(1)

        if (corr != null) {
            dedupeCorr.entries.removeIf { (_, t) -> now - t > 60_000L }
            val prev = dedupeCorr[corr]
            if (prev != null && now - prev < 60_000L) {
                return
            }
            dedupeCorr[corr] = now
        }

        val last = lastEmitByKey[key]
        if (last != null && now - last.time < 5000L) {
            if (corr != null && last.corr != null && corr == last.corr) {
                return
            }
            if (!(corr != null && last.corr != null && corr != last.corr)) {
                if (sourcePri(source) < sourcePri(last.source)) {
                    return
                }
            }
            if (corr == null && last.corr == null && source == last.source) {
                return
            }
        }
        lastEmitByKey[key] = LastEmit(now, source, corr)

        appScope.launch {
            _completed.emit(ChatCompletedEvent(cid, md, timestamp, source, unreadIncrement,
                messageId?.takeIf { it.isNotBlank() }, conversationId?.takeIf { it.isNotBlank() }))
        }

        val am = activeMode
        val active = activeCharId != null && am != null && cid == activeCharId && md == am
        if (!active) {
            val map = _unread.value.toMutableMap()
            map[key] = (map[key] ?: 0) + unreadIncrement
            _unread.value = map
            schedulePersist()
        }
    }

    fun notifyNetworkAvailable() {
        appScope.launch { _networkAvailable.emit(System.currentTimeMillis()) }
    }

    fun markRead(characterId: String, mode: String) {
        val cid = characterId.trim().ifBlank { return }
        val key = chatKey(cid, mode)
        val map = _unread.value.toMutableMap()
        if (!map.containsKey(key) || (map[key] ?: 0) <= 0) return
        map.remove(key)
        _unread.value = map
        schedulePersist()
    }

    private fun schedulePersist() {
        val p = prefs ?: return
        persistJob?.cancel()
        persistJob = appScope.launch {
            delay(300)
            p.writeUnreadMap(_unread.value)
        }
    }
}
