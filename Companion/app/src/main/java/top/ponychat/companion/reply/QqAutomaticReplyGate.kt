package top.ponychat.companion.reply

import java.util.ArrayDeque

class QqReplyRateLimiter(
    private val windowMs: Long = 5 * 60_000L,
    private val maxTotal: Int = 8,
    private val maxPerSender: Int = 4,
) {
    private data class Reply(val sender: String, val timestampMs: Long)

    private val replies = ArrayDeque<Reply>()

    @Synchronized
    fun tryAcquire(sender: String, nowMs: Long = System.currentTimeMillis()): Boolean {
        while (replies.isNotEmpty() && nowMs - replies.first.timestampMs >= windowMs) {
            replies.removeFirst()
        }
        if (replies.size >= maxTotal) return false
        if (replies.count { it.sender == sender } >= maxPerSender) return false
        replies.addLast(Reply(sender, nowMs))
        return true
    }
}

object QqAutomaticReplyGate {
    private val limiter = QqReplyRateLimiter()

    fun tryAcquire(sender: String): Boolean = limiter.tryAcquire(sender)
}
