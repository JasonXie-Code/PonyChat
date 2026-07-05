package top.ponychat.webview.util

import java.util.concurrent.ConcurrentHashMap

/**
 * 跨 WebSocket 与 HTTP outbox 拉取的系统通知去重。
 *
 * 同一逻辑消息可能经 WS 与 `pullUndelivered` 各到达一次；仅依赖 outbox id 时，若某一端
 * 缺少 `outbox_id` 会无法与 `message_id` 对齐，导致通知重复。
 */
object MessageNotifyDeduper {

    private val lastPostedAt = ConcurrentHashMap<String, Long>()
    private const val WINDOW_MS = 180_000L

    fun clear() {
        lastPostedAt.clear()
    }

    /**
     * @return true 表示本窗口内首次投递（应展示通知 / 推流）；false 表示短时间重复（应跳过通知与重复 tryEmit）。
     */
    fun markIfFirst(
        channel: String,
        kind: String,
        outboxId: String?,
        messageId: String?,
    ): Boolean {
        val keys = buildSet {
            outboxId?.trim()?.takeIf { it.isNotEmpty() }?.let { add("o:$it") }
            messageId?.trim()?.takeIf { it.isNotEmpty() }?.let { add("m:$kind:$it") }
        }
        if (keys.isEmpty()) {
            NotificationTrace.log("notify_dedupe", "no_keys kind=$kind ch=$channel -> allow")
            return true
        }
        val now = System.currentTimeMillis()
        prune(now)
        synchronized(this) {
            for (k in keys) {
                val prev = lastPostedAt[k]
                if (prev != null && now - prev < WINDOW_MS) {
                    NotificationTrace.log(
                        "notify_dedupe",
                        "skip_dup key=$k ageMs=${now - prev} kind=$kind ch=$channel",
                    )
                    return false
                }
            }
            for (k in keys) lastPostedAt[k] = now
        }
        return true
    }

    private fun prune(now: Long) {
        if (lastPostedAt.size < 500) return
        lastPostedAt.entries.removeIf { (_, t) -> now - t > WINDOW_MS }
    }
}
