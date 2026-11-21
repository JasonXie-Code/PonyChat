package top.ponychat.webview.ui.chat

import top.ponychat.webview.data.model.Message

/** Keep the pending input anchor even when a refresh returns only the previous turn. */
internal fun hasRecoveredGameReply(
    messages: List<Message>,
    expectedUserId: String?,
    expectedUserTimestamp: Long,
): Boolean {
    val userIndex = messages.indexOfLast {
        it.isUser() && expectedUserId != null && (it.messageId ?: it.id) == expectedUserId
    }
    val lastUserIndex = messages.indexOfLast { it.isUser() }
    return messages.withIndex().any { (index, message) ->
        message.isAssistant() && !message.isStreaming && !message.isError &&
            index > lastUserIndex &&
            (if (userIndex >= 0) index > userIndex else message.timestamp >= expectedUserTimestamp) &&
            (message.rawContent?.isNotBlank() == true ||
                message.displayContent?.isNotBlank() == true || message.content.isNotBlank())
    }
}
