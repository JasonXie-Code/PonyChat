package top.ponychat.webview.ui.chat

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.Color
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalContext
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.WebImageReceiver
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Real attachment UI -> HTTP download -> verified local receipt -> rendered pixels. */
@RunWith(AndroidJUnit4::class)
class HistoryRepeatDisplayInstrumentedTest {
    @Test fun historyRepeatDownloadsFromBubbleAndRendersOriginalImage() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val remote = "/chat_images/tmp_repeat_ui_${System.nanoTime()}.png"
        val bitmap = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.MAGENTA)
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        bitmap.recycle()
        val receipt = CountDownLatch(1)
        val server = ServerSocket(0)
        var context: Context? = null
        val worker = thread(isDaemon = true) {
            try {
                while (!server.isClosed) server.accept().use { socket ->
                    val input = socket.getInputStream().bufferedReader()
                    val request = input.readLine().orEmpty()
                    while (!input.readLine().isNullOrEmpty()) { /* headers; receipt has an empty body */ }
                    val isGet = request.startsWith("GET $remote ")
                    val isReceipt = request.startsWith("POST /api/chat_images/${remote.substringAfterLast('/')}/received ")
                    val body = if (isGet) bytes else "{}".toByteArray()
                    val headers = "HTTP/1.1 200 OK\r\nContent-Type: ${if (isGet) "image/png" else "application/json"}\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n"
                    socket.getOutputStream().apply { write(headers.toByteArray()); write(body); flush() }
                    if (isReceipt) receipt.countDown()
                }
            } catch (_: java.net.SocketException) { /* test closes the listening socket */ }
        }
        try {
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    val isolated = object : ContextWrapper(activity) {
                        override fun getApplicationContext(): Context = this
                        override fun getSharedPreferences(name: String, mode: Int) =
                            super.getSharedPreferences("repeat_ui_test_$name", mode)
                    }
                    context = isolated
                    val prefs = AppPreferences(isolated).apply {
                        username = "repeat_ui_test"
                        debugMode = true
                        activeApiBase = "http://127.0.0.1:${server.localPort}"
                    }
                    val attachment = MessageAttachment(type = "image", url = remote, name = "重发的图片",
                        metadata = mapOf("source" to "history_repeat", "sha256" to WebImageReceiver.sha256(bytes)))
                    activity.setContent {
                        CompositionLocalProvider(LocalContext provides isolated) {
                            PonyChatTheme {
                                MessageBubble(message = Message(role = "assistant", content = "原图再发给你", attachments = listOf(attachment)),
                                    characterName = "测试角色", characterAvatarUrl = "", userAvatarUrl = "",
                                    apiBase = prefs.effectiveApiBase(), onCopy = {}, onDelete = {})
                            }
                        }
                    }
                }
                assertTrue("Bubble must download and acknowledge history_repeat", receipt.await(15, TimeUnit.SECONDS))
                assertArrayEquals(bytes, loadChatImageBytesForUpload(context!!, remote))
                val deadline = SystemClock.uptimeMillis() + 5000
                var rendered = false
                while (!rendered && SystemClock.uptimeMillis() < deadline) {
                    val screen = instrumentation.uiAutomation.takeScreenshot()
                    if (screen != null) {
                        val pixels = IntArray(screen.width * screen.height)
                        screen.getPixels(pixels, 0, screen.width, 0, 0, screen.width, screen.height)
                        rendered = pixels.count { it == Color.MAGENTA } > 1000
                        screen.recycle()
                    }
                    if (!rendered) SystemClock.sleep(50)
                }
                assertTrue("Actual repeated-image bubble must contain original pixels", rendered)
            }
        } finally {
            server.close()
            worker.join(1000)
            context?.let { ctx ->
                localUrlForRemoteChatImage(ctx, remote)?.let { local ->
                    ctx.getSharedPreferences(LOCAL_IMAGE_REMOTE_PREFS, Context.MODE_PRIVATE).edit().remove(local).commit()
                    File(android.net.Uri.parse(local).path!!).delete()
                }
            }
        }
    }
}
