package top.ponychat.webview.data.repo

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.local.LocalHistoryImageStore
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.loadChatImageBytesForUpload
import top.ponychat.webview.ui.chat.localUrlForRemoteChatImage
import top.ponychat.webview.ui.chat.messagePreviewImages
import java.io.ByteArrayOutputStream
import java.io.File

class WebImageReceiverTest {
    private fun testContext(): Context = object : ContextWrapper(
        InstrumentationRegistry.getInstrumentation().targetContext) {
        override fun getApplicationContext(): Context = this
        override fun getFilesDir(): File = File(super.getFilesDir(), "web_image_receipt_tests").also { it.mkdirs() }
        override fun getSharedPreferences(name: String, mode: Int) =
            super.getSharedPreferences("web_image_receipt_test_$name", mode)
    }

    @Test fun savesPhoneBytesBeforeReceiptAndReplaysFromLocalStorage() = runBlocking {
        val context = testContext()
        val prefs = AppPreferences(context).apply { username = "web_image_test" }
        val bitmap = Bitmap.createBitmap(32, 24, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.BLUE)
        val output = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 90, output)
        bitmap.recycle()
        val bytes = output.toByteArray()
        val url = "/chat_images/tmp_android_test.jpg"
        val metadata = mapOf("source" to "web_search", "sha256" to WebImageReceiver.sha256(bytes))
        val attachment = MessageAttachment(type = "image", url = url, metadata = metadata)
        val existingImage = File(context.filesDir, "chat_images/gallery_existing.jpg").apply {
            parentFile!!.mkdirs()
            writeBytes(bytes)
        }
        val firstThree = listOf("https://example.test/gallery/first.jpg",
            "https://example.test/gallery/second.jpg", android.net.Uri.fromFile(existingImage).toString())
        val messages = listOf(
            Message(role = "user", content = firstThree.joinToString("\n") { "![]($it)" }),
            Message(role = "assistant", content = "", attachments = listOf(attachment)),
        )
        fun assertGallery(expectedLast: String) {
            val gallery = messagePreviewImages(context, messages)
            // Match the thumbnail's local URL after receipt and its original
            // reference during the asynchronous display-URL transition.
            val clicked = localUrlForRemoteChatImage(context, url) ?: url
            assertEquals(3, gallery.indexOf(clicked))
            assertEquals(2, gallery.indexOf(firstThree[2]))
            assertEquals(firstThree + expectedLast, gallery)
        }
        val calls = mutableListOf<String>()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val request = chain.request()
            calls.add(request.method)
            if (request.method == "POST") {
                assertEquals("/api/chat_images/tmp_android_test.jpg/received", request.url.encodedPath)
                // Receipt can only happen once the persisted phone mapping and
                // complete bytes can be read back through the real history path.
                assertArrayEquals(bytes, loadChatImageBytesForUpload(context, url))
                assertGallery(requireNotNull(localUrlForRemoteChatImage(context, url)))
            }
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body(if (request.method == "GET") bytes.toResponseBody("image/jpeg".toMediaType())
                      else "{\"deleted\":true}".toResponseBody("application/json".toMediaType())).build()
        }.build()
        try {
            cleanup(context, prefs.username, url)
            assertGallery(url) // A not-yet-downloaded attachment keeps its own page.
            WebImageReceiver.receive(prefs, attachment, client)
            assertEquals(listOf("GET", "POST"), calls)
            val localUrl = localUrlForRemoteChatImage(context, url)
            assertNotNull(localUrl)
            assertGallery(localUrl!!)
            WebImageReceiver.receive(AppPreferences(context), attachment, client)
            assertEquals(listOf("GET", "POST", "POST"), calls)
            assertGallery(localUrl)
            assertArrayEquals(bytes, loadChatImageBytesForUpload(context, url))
            val index = LocalHistoryImageStore(context)
            index.record(prefs.username, "synthetic", "synthetic-conv", listOf(
                ChatMessage("assistant", "", messageId = "synthetic-image", attachments = listOf(attachment))))
            assertEquals(listOf(url), index.read(prefs.username, "synthetic", "synthetic-conv").single().urls)
            index.remove(prefs.username, "synthetic")
        } finally {
            cleanup(context, prefs.username, url)
            existingImage.delete()
        }
    }

    @Test fun corruptDownloadNeverAcknowledgesDeletion() = runBlocking {
        val context = testContext()
        val prefs = AppPreferences(context).apply { username = "web_image_test" }
        val url = "/chat_images/tmp_android_corrupt.jpg"
        val attachment = MessageAttachment(type = "image", url = url,
            metadata = mapOf("source" to "web_search", "sha256" to "a".repeat(64)))
        val calls = mutableListOf<String>()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            calls.add(chain.request().method)
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body("corrupt".toResponseBody("image/jpeg".toMediaType())).build()
        }.build()
        try {
            WebImageReceiver.receive(prefs, attachment, client)
            assertEquals(listOf("GET"), calls)
            assertNull(loadChatImageBytesForUpload(context, url))
        } finally {
            cleanup(context, prefs.username, url)
        }
    }

    private fun cleanup(context: Context, username: String, url: String) {
        val key = WebImageReceiver.sha256("$username\n$url".toByteArray())
        val file = File(context.filesDir, "chat_images/web_$key.jpg")
        context.getSharedPreferences("ponychat_local_image_remote", Context.MODE_PRIVATE).edit()
            .remove(android.net.Uri.fromFile(file).toString()).commit()
        file.delete()
    }
}
