package top.ponychat.webview.ui.chat

import top.ponychat.webview.data.model.Message

internal fun stableChatMessageKey(
    role: String,
    messageId: String?,
    sequenceNumber: Int?,
    timestamp: Long?,
    fallbackId: String = ""
): String {
    messageId?.takeIf { it.isNotBlank() }?.let { return "message:$it" }
    return stableChatMessageId(role, messageId, sequenceNumber, timestamp, fallbackId)
}

internal fun stableChatMessageId(
    role: String,
    messageId: String?,
    sequenceNumber: Int?,
    timestamp: Long?,
    fallbackId: String = ""
): String {
    messageId?.takeIf { it.isNotBlank() }?.let { return it }
    sequenceNumber?.let { return "sequence:$role:$it" }
    timestamp?.takeIf { it > 0L }?.let { return "time:$role:$it" }
    return fallbackId.ifBlank { "fallback:$role" }
}

internal fun Message.stableChatItemKey(): String =
    stableChatMessageKey(
        role = role,
        messageId = messageId,
        sequenceNumber = sequenceNumber,
        timestamp = timestamp,
        fallbackId = id
    )
