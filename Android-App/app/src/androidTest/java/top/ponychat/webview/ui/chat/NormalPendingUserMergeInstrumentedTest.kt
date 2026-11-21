package top.ponychat.webview.ui.chat

import android.app.Application
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.Message

@RunWith(AndroidJUnit4::class)
class NormalPendingUserMergeInstrumentedTest {
    @Test
    fun normalHistoryRefreshKeepsLocalUserWhenServerSnapshotOnlyHasAssistant() {
        val app = InstrumentationRegistry
            .getInstrumentation()
            .targetContext
            .applicationContext as Application
        val viewModel = ChatViewModel(app)
        val username = viewModel.prefs.username
        val characterId = "android_test_pending_user_char_${System.nanoTime()}"
        val conversationId = "android_test_pending_user_conv_${System.nanoTime()}"
        val userText = "这条用户消息不能消失 ${System.nanoTime()}"

        viewModel._state.value = viewModel._state.value.copy(
            character = Character(id = characterId, name = "普通聊天测试"),
            mode = "normal",
            conversationId = conversationId,
            messages = emptyList(),
            inputText = "",
            isStreaming = false,
        )

        val userMessage = requireNotNull(viewModel.appendUserTextMessage(userText))
        assertTrue(viewModel.unconfirmedNormalUserKeys.contains(userMessage.id))
        val assistantId = "assistant_server_${System.nanoTime()}"
        val assistantTimestamp = userMessage.timestamp + 1_000
        val assistantMessage = Message(
            id = assistantId,
            role = "assistant",
            content = "服务端助手回复先到了",
            timestamp = assistantTimestamp,
            messageId = assistantId,
            sequenceNumber = 12,
        )
        viewModel._state.value = viewModel._state.value.copy(
            messages = viewModel._state.value.messages + assistantMessage
        )
        viewModel.sentMessages.add(
            ChatMessage(
                role = "assistant",
                content = assistantMessage.content,
                messageId = assistantId,
                sequenceNumber = 12,
                timestamp = assistantTimestamp,
            )
        )
        viewModel.onNormalReplyRoundFinished()

        val serverAssistantOnly = listOf(
            ChatMessage(
                role = "assistant",
                content = assistantMessage.content,
                messageId = assistantId,
                sequenceNumber = 12,
                timestamp = assistantTimestamp,
            )
        )
        val serverUiMessages = viewModel.visibleMessagesForUi(
            messages = serverAssistantOnly,
            username = username,
            characterId = characterId,
            mode = "normal",
            conversationId = conversationId,
            speakerFallbackMessages = viewModel._state.value.messages,
        )

        val mergedUiMessages = viewModel.mergePendingNormalLocalUsers(serverUiMessages)
        assertEquals(listOf("user", "assistant"), mergedUiMessages.map { it.role })
        assertEquals(userText, mergedUiMessages.first().content)
        assertEquals(userMessage.id, mergedUiMessages.first().messageId)
        assertTrue(viewModel.unconfirmedNormalUserKeys.contains(userMessage.id))

        val mergedRuntimeMessages = viewModel.mergePendingNormalRuntimeUsers(serverAssistantOnly)
        assertEquals(listOf("user", "assistant"), mergedRuntimeMessages.map { it.role })
        assertEquals(userMessage.id, mergedRuntimeMessages.first().messageId)
        assertTrue(viewModel.unconfirmedNormalUserKeys.contains(userMessage.id))

        viewModel.sentMessages.clear()
        viewModel.sentMessages.add(serverAssistantOnly.first())
        val mergedRuntimeMessagesAfterRuntimeUserWasLost =
            viewModel.mergePendingNormalRuntimeUsers(serverAssistantOnly)
        assertEquals(
            listOf("user", "assistant"),
            mergedRuntimeMessagesAfterRuntimeUserWasLost.map { it.role }
        )
        assertEquals(userText, mergedRuntimeMessagesAfterRuntimeUserWasLost.first().content)
        assertEquals(userMessage.id, mergedRuntimeMessagesAfterRuntimeUserWasLost.first().messageId)
        assertTrue(viewModel.unconfirmedNormalUserKeys.contains(userMessage.id))

        val serverWithUser = listOf(
            ChatMessage(
                role = "user",
                content = userText,
                messageId = userMessage.id,
                sequenceNumber = 11,
                timestamp = userMessage.timestamp,
            ),
            serverAssistantOnly.first(),
        )
        val authoritativeUiMessages = viewModel.visibleMessagesForUi(
            messages = serverWithUser,
            username = username,
            characterId = characterId,
            mode = "normal",
            conversationId = conversationId,
            speakerFallbackMessages = mergedUiMessages,
        )
        val mergedAuthoritativeUi = viewModel.mergePendingNormalLocalUsers(authoritativeUiMessages)
        assertEquals(2, mergedAuthoritativeUi.size)
        assertEquals(11, mergedAuthoritativeUi.first { it.isUser() }.sequenceNumber)
        assertTrue(mergedAuthoritativeUi.count { it.isUser() } == 1)
        assertFalse(viewModel.unconfirmedNormalUserKeys.contains(userMessage.id))
    }
}
