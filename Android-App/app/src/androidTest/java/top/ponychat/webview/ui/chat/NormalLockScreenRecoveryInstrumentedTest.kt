package top.ponychat.webview.ui.chat

import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.Gson
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ChatCompletedEvent
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ChatEventBus
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference

/** Real Retrofit/HTTP, history mapping and ViewModel merging, with isolated phone data. */
class NormalLockScreenRecoveryInstrumentedTest {
    private class TestApplication(base: Context) : Application() {
        private val prefix = "normal_delivery_${System.nanoTime()}_"
        init { attachBaseContext(base) }
        override fun getApplicationContext(): Context = this
        override fun getSharedPreferences(name: String, mode: Int) = super.getSharedPreferences(prefix + name, mode)
        override fun getFilesDir(): File = File(super.getFilesDir(), prefix).also { it.mkdirs() }
        override fun checkSelfPermission(permission: String) = PackageManager.PERMISSION_DENIED
        override fun checkPermission(permission: String, pid: Int, uid: Int) = PackageManager.PERMISSION_DENIED
    }

    private class HistoryServer : AutoCloseable {
        private val socket = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        val base = "http://127.0.0.1:${socket.localPort}"
        val rows = AtomicReference<List<ChatMessage>>(emptyList())
        val calls = CopyOnWriteArrayList<Uri>()
        @Volatile var slowMessageId: String? = null
        @Volatile var acceptFirst = false
        val posts = java.util.concurrent.atomic.AtomicInteger()
        val postedBodies = CopyOnWriteArrayList<String>()
        private val worker = Thread {
            while (!socket.isClosed) {
                try {
                    socket.accept().use { connection ->
                        val reader = connection.getInputStream().bufferedReader()
                        val line = reader.readLine() ?: return@use
                        val uri = Uri.parse(base + line.split(' ')[1])
                        var contentLength = 0
                        while (true) {
                            val header = reader.readLine() ?: break
                            if (header.isEmpty()) break
                            if (header.startsWith("Content-Length:", true)) contentLength = header.substringAfter(':').trim().toInt()
                        }
                        val payload = CharArray(contentLength)
                        var offset = 0
                        while (offset < contentLength) {
                            val count = reader.read(payload, offset, contentLength - offset)
                            if (count < 0) break
                            offset += count
                        }
                        if (uri.path == "/api/chat") {
                            postedBodies.add(String(payload))
                            val attempt = posts.incrementAndGet()
                            val accepted = "data: {\"type\":\"accepted\",\"job_id\":\"fixture-job\",\"client_message_id\":\"u\"}\n\n"
                            val paragraph = "data: {\"type\":\"assistant_paragraph\",\"id\":\"a\",\"content\":\"fixture reply\",\"sequence_number\":11}\n\n"
                            val first = if (acceptFirst) accepted else ""
                            val response = if (attempt == 1) first else accepted + paragraph + "data: [DONE]\n\n"
                            val bytes = response.toByteArray()
                            val announced = bytes.size + if (attempt == 1) 100 else 0
                            connection.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: $announced\r\nConnection: close\r\n\r\n").toByteArray() + bytes)
                            return@use
                        }
                        calls.add(uri)
                        val target = uri.getQueryParameter("message_id")
                        if (target != null && target == slowMessageId) {
                            slowMessageId = null
                            Thread.sleep(200)
                        }
                        val after = uri.getQueryParameter("after_seq")?.toInt()
                        val before = uri.getQueryParameter("before_seq")?.toInt()
                        val selected = rows.get().filter {
                            (target == null || it.messageId == target) &&
                                (after == null || (it.sequenceNumber ?: 0) > after) &&
                                (before == null || (it.sequenceNumber ?: 0) < before)
                        }
                        val body = Gson().toJson(mapOf("messages" to selected, "conversation_id" to "delivery-conv",
                            "has_more" to false, "min_seq" to selected.mapNotNull { it.sequenceNumber }.minOrNull(),
                            "max_seq" to selected.mapNotNull { it.sequenceNumber }.maxOrNull())).toByteArray()
                        val header = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n"
                        connection.getOutputStream().write(header.toByteArray() + body)
                    }
                } catch (_: IOException) {
                    // Cancelling a Retrofit request closes its socket mid-response.
                }
            }
        }.apply { isDaemon = true; start() }
        override fun close() { socket.close(); worker.join(2000) }
    }

    private fun shell(command: String) {
        InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command).use {
            java.io.FileInputStream(it.fileDescriptor).readBytes()
        }
    }

    private fun runLockScreenCase(acceptedBeforeDisconnect: Boolean) = runBlocking {
        val realApp = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext
        val app = TestApplication(realApp)
        val prefs = AppPreferences(app).apply {
            username = "lock-screen-test"
            debugMode = true
            authToken = ""
        }
        shell("input keyevent 224")
        try {
            HistoryServer().use { server ->
                server.acceptFirst = acceptedBeforeDisconnect
                prefs.activeApiBase = server.base
                NetworkClient.bindPreferences(prefs)
                withContext(Dispatchers.Main) {
                    val vm = ChatViewModel(app)
                    val now = System.currentTimeMillis()
                    val user = ChatMessage("user", "hello", messageId = "u", timestamp = now)
                    val reply = ChatMessage("assistant", "fixture reply", messageId = "a", sequenceNumber = 11, timestamp = now + 100)
                    vm._state.value = vm._state.value.copy(character = Character(id = "pony", name = "test"),
                        mode = "normal", conversationId = "delivery-conv", isLoadingHistory = false,
                        messages = listOf(vm.chatMessageToMessage(user)))
                    vm.sentMessages.add(user)
                    server.rows.set(if (acceptedBeforeDisconnect) listOf(user.copy(sequenceNumber = 10), reply) else emptyList())
                    try {
                        vm.startNormalReplyGeneration(requestMessagesOverride = listOf(user))
                        withContext(Dispatchers.IO) { shell("input keyevent 223") }
                        val power = app.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
                        withTimeout(3000) { while (power.isInteractive) delay(50) }
                        assertFalse("Emulator must really be asleep during recovery", power.isInteractive)
                        val recovered = withTimeoutOrNull(20000) {
                            while (vm._state.value.messages.none { it.messageId == "a" || it.id == "a" }) delay(100)
                            true
                        } ?: false
                        assertTrue("posts=${server.posts.get()} streaming=${vm._state.value.isStreaming} " +
                            "round=${vm.lastNormalGenerationStartedAtMs} retry=${vm.normalTransportRetryJob} " +
                            "ids=${vm._state.value.messages.map { it.id }} error=${vm._state.value.error}", recovered)
                        assertNull(vm._state.value.error)
                        assertEquals(1, vm._state.value.messages.count { it.messageId == "a" || it.id == "a" })
                        assertEquals(if (acceptedBeforeDisconnect) 1 else 2, server.posts.get())
                        server.postedBodies.forEach { body ->
                            val request = Gson().fromJson(body, top.ponychat.webview.data.model.ChatRequest::class.java)
                            assertEquals("u", request.messages.single().messageId)
                            assertEquals("delivery-conv", request.conversationId)
                        }
                        withContext(Dispatchers.IO) { shell("input keyevent 224") }
                        vm.onForegroundResume()
                        delay(1500)
                        assertEquals(1, vm._state.value.messages.count { it.messageId == "a" || it.id == "a" })
                        assertNull(vm._state.value.error)
                    } finally {
                        vm.resetNormalSendState()
                        vm.viewModelScope.cancel()
                    }
                }
            }
        } finally {
            shell("input keyevent 224")
            shell("wm dismiss-keyguard")
            NetworkClient.bindPreferences(AppPreferences(realApp))
        }
    }

    @Test fun immediateLockBeforeReceiptRetriesSameMessage() = runLockScreenCase(false)
    @Test fun immediateLockAfterReceiptRecoversWithoutResending() = runLockScreenCase(true)
}
