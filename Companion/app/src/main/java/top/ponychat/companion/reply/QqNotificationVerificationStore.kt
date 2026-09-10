package top.ponychat.companion.reply

import android.content.Context

data class QqNotificationVerificationCandidate(
    val sender: String,
    val messageFingerprint: String,
    val postTime: Long,
) {
    fun matches(sender: String, message: String): Boolean =
        this.sender == sender.trim() &&
            messageFingerprint == QqReplyEventId.messageFingerprint(sender, message)

    fun isExpired(now: Long, ttlMs: Long = DEFAULT_TTL_MS): Boolean =
        postTime <= 0L || now - postTime !in 0..ttlMs

    companion object {
        const val DEFAULT_TTL_MS = 45_000L
    }
}

object QqNotificationVerificationStore {
    private const val PREFERENCES = "qq_notification_verification"
    private const val KEY_SENDER = "sender"
    private const val KEY_MESSAGE_FINGERPRINT = "message_fingerprint"
    private const val KEY_POST_TIME = "post_time"

    fun publish(context: Context, sender: String, message: String, postTime: Long): Boolean {
        val normalizedSender = sender.trim()
        if (normalizedSender.isBlank() || message.isBlank() || postTime <= 0L) return false
        val next = QqNotificationVerificationCandidate(
            sender = normalizedSender,
            messageFingerprint = QqReplyEventId.messageFingerprint(normalizedSender, message),
            postTime = postTime,
        )
        if (next.isExpired(System.currentTimeMillis())) return false
        val current = peek(context)
        if (current == next) return false
        return preferences(context).edit()
            .putString(KEY_SENDER, next.sender)
            .putString(KEY_MESSAGE_FINGERPRINT, next.messageFingerprint)
            .putLong(KEY_POST_TIME, next.postTime)
            .commit()
    }

    fun peek(context: Context, now: Long = System.currentTimeMillis()):
        QqNotificationVerificationCandidate? {
        val preferences = preferences(context)
        val candidate = QqNotificationVerificationCandidate(
            sender = preferences.getString(KEY_SENDER, "").orEmpty(),
            messageFingerprint = preferences.getString(KEY_MESSAGE_FINGERPRINT, "").orEmpty(),
            postTime = preferences.getLong(KEY_POST_TIME, 0L),
        ).takeIf { it.sender.isNotBlank() && it.messageFingerprint.isNotBlank() }
        if (candidate?.isExpired(now) == true) {
            preferences.edit().clear().commit()
            return null
        }
        return candidate
    }

    fun consume(context: Context, candidate: QqNotificationVerificationCandidate) {
        if (peek(context) == candidate) preferences(context).edit().clear().commit()
    }

    private fun preferences(context: Context) =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
}
