package top.ponychat.webview.ui.chat

import android.app.Application
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ChatMessage

@RunWith(AndroidJUnit4::class)
class RetractedMessageEditInstrumentedTest {
    @Test
    fun retractedMessageEditRestoresOriginalTextAfterPlaceholderRefresh() = runBlocking {
        val app = InstrumentationRegistry
            .getInstrumentation()
            .targetContext
            .applicationContext as Application
        val viewModel = ChatViewModel(app)
        val username = viewModel.prefs.username
        val characterId = "android_test_retract_char_${System.nanoTime()}"
        val conversationId = "android_test_retract_conv_${System.nanoTime()}"
        val originalText = "撤回原文 ${System.nanoTime()}"

        viewModel._state.value = viewModel._state.value.copy(
            character = Character(id = characterId, name = "撤回测试"),
            mode = "unit_test",
            conversationId = conversationId,
            messages = emptyList(),
            inputText = "",
            isStreaming = false,
        )

        val userMessage = requireNotNull(viewModel.appendUserTextMessage(originalText))
        viewModel.retractMessage(userMessage.id)
        delay(50)
        viewModel.autoSaveJob?.cancel()

        val refreshedMessages = viewModel.visibleMessagesForUi(
            messages = listOf(
                ChatMessage(
                    role = "user",
                    content = RETRACTED_USER_MESSAGE_TEXT,
                    messageId = userMessage.id,
                    timestamp = userMessage.timestamp,
                ),
                ChatMessage(
                    role = "assistant",
                    content = "第一轮正常回复",
                    messageId = "assistant_round_1_${System.nanoTime()}",
                    timestamp = userMessage.timestamp + 1_000,
                ),
                ChatMessage(
                    role = "user",
                    content = "第一轮后续用户消息",
                    messageId = "user_round_1_${System.nanoTime()}",
                    timestamp = userMessage.timestamp + 2_000,
                ),
                ChatMessage(
                    role = "assistant",
                    content = "第二轮正常回复",
                    messageId = "assistant_round_2_${System.nanoTime()}",
                    timestamp = userMessage.timestamp + 3_000,
                ),
                ChatMessage(
                    role = "user",
                    content = "第二轮后续用户消息",
                    messageId = "user_round_2_${System.nanoTime()}",
                    timestamp = userMessage.timestamp + 4_000,
                ),
                ChatMessage(
                    role = "assistant",
                    content = "第二轮之后的正常回复",
                    messageId = "assistant_round_3_${System.nanoTime()}",
                    timestamp = userMessage.timestamp + 5_000,
                )
            ),
            username = username,
            characterId = characterId,
            mode = "unit_test",
            conversationId = conversationId,
        )

        val refreshedMessage = refreshedMessages.first()
        assertTrue(refreshedMessage.isRetracted)
        assertEquals(originalText, refreshedMessage.content)
        assertEquals(6, refreshedMessages.size)

        viewModel._state.value = viewModel._state.value.copy(
            messages = refreshedMessages,
            inputText = "",
        )
        viewModel.restoreRetractedMessageInput(refreshedMessage.id)

        assertEquals(originalText, viewModel.state.value.inputText)
    }
}
