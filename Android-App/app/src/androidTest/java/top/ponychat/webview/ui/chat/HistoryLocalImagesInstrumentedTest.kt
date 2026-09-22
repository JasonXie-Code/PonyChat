package top.ponychat.webview.ui.chat

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.local.LocalHistoryImageStore
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.SearchMessageResult

class HistoryLocalImagesInstrumentedTest {
    @Test fun restoresTextOnlyServerRowsWithoutCrossingAccountCharacterOrConversation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = LocalHistoryImageStore(context)
        val user = "history-test-${System.nanoTime()}"
        val url = "data:image/png;base64,ZmFrZQ=="
        try {
            store.record(user, "pony", "conversation", listOf(
                ChatMessage(role = "user", content = "说明 ![]($url)", messageId = "message")))
            val rows = listOf(SearchMessageResult("message", 1, "conversation", "user", "说明", 1))
            val restored = rows.withLocalHistoryImages(context, user, "pony")
            assertEquals(listOf(url), restored.single().historyImageUrls(context))
            assertTrue(restored.single().matchesHistoryContent("image", context))
            assertEquals("说明", restored.single().content)
            assertEquals(restored, restored.withLocalHistoryImages(context, user, "pony"))
            assertEquals(rows, rows.withLocalHistoryImages(context, "$user-other", "pony"))
            assertEquals(rows, rows.withLocalHistoryImages(context, user, "other-pony"))
            val other = rows.map { it.copy(conversationId = "other-conversation") }
            assertEquals(other, other.withLocalHistoryImages(context, user, "pony"))
        } finally { store.remove(user, "pony") }
    }
}
