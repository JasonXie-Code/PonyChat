package top.ponychat.webview.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatScreenMediaOpsTest {
    @Test
    fun extractsAllMarkdownImagesFromFailedMessage() {
        assertEquals(
            listOf("file:///cache/a.jpg", "/chat_images/b.jpg"),
            chatImageUrlsInContent("原消息\n\n![](file:///cache/a.jpg)\n![](/chat_images/b.jpg)"),
        )
    }

    @Test
    fun retriesOnlyImagesThatStillNeedUploading() {
        assertTrue(chatImageNeedsUpload("file:///cache/a.jpg"))
        assertTrue(chatImageNeedsUpload("content://media/a"))
        assertFalse(chatImageNeedsUpload("/chat_images/a.jpg"))
        assertFalse(chatImageNeedsUpload("https://example.com/a.jpg"))
        assertFalse(chatImageNeedsUpload("data:image/png;base64,AA=="))
    }
}
