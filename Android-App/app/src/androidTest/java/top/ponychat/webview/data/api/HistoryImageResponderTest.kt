package top.ponychat.webview.data.api

import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import okhttp3.Request
import okhttp3.WebSocket
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.prefs.AppPreferences

class HistoryImageResponderTest {
    private class Socket : WebSocket {
        var response: JSONObject? = null
        override fun request() = Request.Builder().url("https://localhost/").build()
        override fun queueSize() = 0L
        override fun send(text: String): Boolean { response = JSONObject(text); return true }
        override fun send(bytes: ByteString) = false
        override fun close(code: Int, reason: String?) = true
        override fun cancel() {}
    }

    @Test fun retrievesLocalLegacyImageAndReportsDeletedImageWithoutCrossConversationFallback() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val username = AppPreferences(context).username
        assertTrue("Test requires the existing emulator login", username.isNotBlank())
        val character = "history_image_instrumentation"
        val conversation = "history_image_instrumentation_conv"
        val cache = LocalCacheStore(context)
        val file = File(context.filesDir, "chat_images/history_image_instrumentation.png")
        file.parentFile!!.mkdirs()
        try {
            val bitmap = Bitmap.createBitmap(48, 32, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(android.graphics.Color.RED)
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
            val imageMessage = ChatMessage("user", "![旧图片](${file.toURI()})", messageId = "old-image", timestamp = 1)
            // Java's file URI uses one slash; real app uses file:// plus absolute path.
            cache.saveConversation(username, character, "normal", conversation,
                listOf(imageMessage.copy(content = "![旧图片](file://${file.absolutePath})")) +
                    (2..45).map { ChatMessage("user", "后续文本", messageId = "text-$it", timestamp = it.toLong()) })
            fun request(action: String, conv: String = conversation): JSONObject = JSONObject()
                .put("request_id", "instrumentation-request").put("action", action)
                .put("character_id", character).put("conversation_id", conv)
                .put("message_id", "old-image").put("image_index", 1)
            val socket = Socket()
            HistoryImageResponder.respond(context, request("list"), socket, username)
            assertEquals("old-image", socket.response!!.getJSONArray("images").getJSONObject(0).getString("message_id"))
            // Loading a newer text-only page must not lose the older picture's edge-storage index.
            cache.saveConversation(username, character, "normal", conversation,
                listOf(ChatMessage("user", "最新一页文本", messageId = "latest", timestamp = 1000)))
            HistoryImageResponder.respond(context, request("read"), socket, username)
            assertEquals("ok", socket.response!!.getString("status"))
            assertTrue(socket.response!!.getString("data").length > 100)
            HistoryImageResponder.respond(context, request("read", "other-conversation"), socket, username)
            assertEquals("unavailable", socket.response!!.getString("status"))
            assertTrue(file.delete())
            HistoryImageResponder.respond(context, request("read"), socket, username)
            assertEquals("unavailable", socket.response!!.getString("status"))
            assertFalse(socket.response!!.has("data"))
        } finally {
            file.delete()
            cache.clearForCharacter(username, character)
        }
    }
}
