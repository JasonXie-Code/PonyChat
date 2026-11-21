package top.ponychat.companion.reply

import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

object QqForegroundSafety {
    private val groupSignals = listOf("群聊", "交流群", "@全体成员", "群公告")
    private val groupMemberCountPattern = Regex("[（(]\\d+[）)](?:\\s*.*)?$")
    private val timePattern = Regex("^(上午|下午|晚上|凌晨)?(\\d{1,2}):(\\d{2})$")
    private val privateOnlineStatusPattern = Regex("^在线(?:\\s*[-·]\\s*.+)?$")

    fun hasGroupSignals(value: String): Boolean =
        groupSignals.any(value::contains) || groupMemberCountPattern.containsMatchIn(value.trim())

    fun isPrivateOnlineStatus(value: String): Boolean =
        privateOnlineStatusPattern.matches(value.trim())

    fun isSameMessageWithinSettleWindow(
        lastSender: String?,
        lastMessage: String?,
        lastHandledAtMs: Long,
        sender: String,
        message: String,
        nowMs: Long,
        settleWindowMs: Long,
    ): Boolean = lastSender == sender &&
        lastMessage == message &&
        lastHandledAtMs > 0L &&
        nowMs >= lastHandledAtMs &&
        nowMs - lastHandledAtMs < settleWindowMs

    fun isTimeLabel(value: String): Boolean = timePattern.matches(value.trim())

    fun isSameMessageRow(
        messageTop: Int,
        messageBottom: Int,
        profileTop: Int,
        profileBottom: Int,
    ): Boolean = messageTop < messageBottom &&
        profileTop < profileBottom &&
        messageTop < profileBottom &&
        profileTop < messageBottom

    fun isOwnOutgoingMessageRow(
        screenMidpointX: Int,
        avatarCenterX: Int,
        messageTop: Int,
        messageBottom: Int,
        avatarTop: Int,
        avatarBottom: Int,
    ): Boolean = avatarCenterX > screenMidpointX && isSameMessageRow(
        messageTop,
        messageBottom,
        avatarTop,
        avatarBottom,
    )

    fun isSentMessageVerified(
        editorCleared: Boolean,
        exactOutgoingTextVisible: Boolean,
        ownProfileVisible: Boolean,
        conversationSignatureChanged: Boolean,
    ): Boolean = editorCleared && (
        exactOutgoingTextVisible || (ownProfileVisible && conversationSignatureChanged)
    )

    fun isRecent(
        label: String,
        now: LocalDateTime,
        maxAgeMinutes: Long = 10,
    ): Boolean {
        val match = timePattern.matchEntire(label.trim()) ?: return false
        val period = match.groupValues[1]
        var hour = match.groupValues[2].toIntOrNull() ?: return false
        val minute = match.groupValues[3].toIntOrNull() ?: return false
        if (minute !in 0..59 || hour !in 0..23) return false
        if (period.isNotBlank()) {
            if (hour !in 1..12) return false
            hour = when (period) {
                "下午", "晚上" -> if (hour == 12) 12 else hour + 12
                "上午" -> if (hour == 12) 0 else hour
                "凌晨" -> if (hour == 12) 0 else hour
                else -> return false
            }
        }
        var candidate = now.withHour(hour).withMinute(minute).withSecond(0).withNano(0)
        if (candidate.isAfter(now.plusMinutes(1))) candidate = candidate.minusDays(1)
        val age = ChronoUnit.MINUTES.between(candidate, now)
        return age in 0..maxAgeMinutes
    }
}
