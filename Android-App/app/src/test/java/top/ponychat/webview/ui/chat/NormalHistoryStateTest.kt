package top.ponychat.webview.ui.chat

import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.model.ResetCharacterChatResponse

class NormalHistoryStateTest {
    @Test
    fun emptyHistoryKeepsServerDiscoveryOpenUntilGreetingCreatesConversation() {
        val emptyId = normalHistoryConversationId(null, null)
        assertNull(emptyId)
        assertEquals("greeting-conversation", normalHistoryConversationId("greeting-conversation", emptyId))
    }

    @Test
    fun resetResponseReplacesStaleIdAndPagingState() {
        val response = Gson().fromJson(
            """{"status":"success","success":true,"conversation_id":"canonical"}""",
            ResetCharacterChatResponse::class.java,
        )
        val old = ChatUiState(conversationId = "stale", minLoadedSeq = 85,
            hasMoreHistory = true, isLoadingMoreHistory = true, isBackgroundRefreshing = true)
        val reset = old.afterNormalReset(response.conversationId)
        assertEquals("canonical", reset.conversationId)
        assertEquals(Int.MAX_VALUE, reset.minLoadedSeq)
        assertFalse(reset.hasMoreHistory)
        assertFalse(reset.isLoadingMoreHistory)
        assertFalse(reset.isBackgroundRefreshing)
    }

    @Test
    fun resetWithoutServerConversationDiscardsLocalProvisionalId() {
        val reset = ChatUiState(conversationId = "client-only").afterNormalReset(null)
        assertNull(reset.conversationId)
        assertNull(normalHistoryConversationId(null, reset.conversationId))
    }

    @Test
    fun historyRefreshKeepsIdAssignedToPendingUserMessage() {
        assertEquals("pending-user", normalHistoryConversationId(null, "pending-user"))
        assertEquals("server", normalHistoryConversationId("server", "pending-user"))
        assertNull(normalHistoryConversationId(" ", ""))
    }
}
