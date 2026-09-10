package top.ponychat.webview.ui.chat

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import top.ponychat.webview.data.model.Message

class GameReplyRecoveryTest {
    private val old = Message(id = "old", role = "assistant", content = "上一轮", timestamp = 100)
    private val input = Message(id = "input", role = "user", content = "继续", timestamp = 200)
    private val reply = Message(id = "reply", role = "assistant", content = "本轮", timestamp = 300)

    @Test fun previousReplyAndStreamingPlaceholderDoNotCompleteRecovery() {
        assertFalse(hasRecoveredGameReply(listOf(old, input), "input", 200))
        assertFalse(hasRecoveredGameReply(listOf(old, input, reply.copy(isStreaming = true)), "input", 200))
        assertFalse(hasRecoveredGameReply(listOf(old, input, reply.copy(isError = true)), "input", 200))
    }

    @Test fun RefreshWithOldHistoryMustNotLosePendingInputAnchor() {
        assertFalse(hasRecoveredGameReply(listOf(old), "input", 200))
        assertTrue(hasRecoveredGameReply(listOf(old, input, reply), "input", 200))
    }

    @Test fun ServerMessageIdAndOrderingSurviveClockSkew() {
        val serverUser = input.copy(id = "local-id-changed", messageId = "input")
        assertTrue(hasRecoveredGameReply(listOf(old, serverUser, reply.copy(timestamp = 199)), "input", 200))
    }

    @Test fun OpeningAndRepeatedPullsUseCurrentTurnOnly() {
        assertFalse(hasRecoveredGameReply(listOf(old), null, 200))
        repeat(2) { assertTrue(hasRecoveredGameReply(listOf(reply), null, 200)) }
        assertFalse(hasRecoveredGameReply(listOf(old, input, reply.copy(content = "")), "input", 200))
    }
}
