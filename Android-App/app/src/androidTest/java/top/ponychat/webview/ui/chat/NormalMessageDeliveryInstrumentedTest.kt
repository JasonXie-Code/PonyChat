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
class NormalMessageDeliveryInstrumentedTest {
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
        private val worker = Thread {
            while (!socket.isClosed) {
                try {
                    socket.accept().use { connection ->
                        val reader = connection.getInputStream().bufferedReader()
                        val line = reader.readLine() ?: return@use
                        val uri = Uri.parse(base + line.split(' ')[1])
                        while (!reader.readLine().isNullOrEmpty()) Unit
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

    @Test fun normalDeliveryAndRecoveryMatrix() = runBlocking {
        val realApp = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext
        val app = TestApplication(realApp)
        val prefs = AppPreferences(app).apply {
            username = "delivery-test"
            debugMode = true
            authToken = ""
        }
        try {
        HistoryServer().use { server ->
            prefs.activeApiBase = server.base
            NetworkClient.bindPreferences(prefs)
            withContext(Dispatchers.Main) {
                val vm = ChatViewModel(app)
                val user = ChatMessage("user", "hello", messageId = "u", sequenceNumber = 10, timestamp = 1000)
                val first = ChatMessage("assistant", "first", messageId = "a", sequenceNumber = 11, timestamp = 1100)
                val second = ChatMessage("assistant", "second", messageId = "b", sequenceNumber = 12, timestamp = 1200)
                val third = ChatMessage("assistant", "third", messageId = "c", sequenceNumber = 13, timestamp = 1300)
                fun reset(streaming: Boolean = false, history: List<ChatMessage> = listOf(user), conversation: String? = "delivery-conv") {
                    vm.historyLoadJob?.cancel()
                    vm.pendingNormalDeliveries.clear()
                    vm.sentMessages.clear()
                    vm.sentMessages.addAll(history)
                    vm._state.value = vm._state.value.copy(character = Character(id = "pony", name = "测试角色"),
                        mode = "normal", conversationId = conversation, isStreaming = streaming,
                        messages = history.map(vm::chatMessageToMessage), isLoadingHistory = false)
                }
                fun event(id: String, source: ChatCompletionSource = ChatCompletionSource.WS) =
                    ChatCompletedEvent("pony", "normal", 1500, source, messageId = id, conversationId = "delivery-conv")
                fun ids() = vm._state.value.messages.map { it.messageId }
                try {
                    // Reproduces the old first-WS-read-whole-round bug, even if a
                    // server response incorrectly contains later unpublished rows.
                    for (streaming in listOf(false, true)) {
                        reset(streaming)
                        server.rows.set(listOf(user, first, second, third))
                        vm.refreshNormalMessageDelivery(event("a"))
                        assertEquals(listOf("u", "a"), ids())
                        vm.refreshNormalMessageDelivery(event("b", ChatCompletionSource.HTTP_PULL))
                        assertEquals(listOf("u", "a", "b"), ids())
                        val beforeDuplicate = server.calls.size
                        vm.refreshNormalMessageDelivery(event("b"))
                        assertEquals(beforeDuplicate, server.calls.size)
                        assertEquals(streaming, vm._state.value.isStreaming)
                    }

                    // Reset has no conversation or sequence yet; the real notice
                    // identifies its canonical conversation and appears immediately.
                    reset(history = emptyList(), conversation = null)
                    server.rows.set(listOf(first, second, third))
                    vm.refreshNormalMessageDelivery(event("a"))
                    assertEquals(listOf("a"), ids())
                    assertEquals("delivery-conv", vm._state.value.conversationId)

                    // A high sequence was emitted first; low sequence release
                    // requires the exact-ID endpoint, not after(maxSequence).
                    reset(history = listOf(user, second))
                    server.rows.set(listOf(user, first, second))
                    vm.refreshNormalMessageDelivery(event("a"))
                    assertEquals(listOf("u", "a", "b"), ids())
                    assertTrue(server.calls.any { it.getQueryParameter("message_id") == "a" })

                    // A concurrent network/history refresh cancels an already
                    // acknowledged low-ID notice. The pending repair must survive.
                    reset(history = listOf(user, second))
                    server.slowMessageId = "a"
                    val startCalls = server.calls.size
                    val delivery = launch { vm.refreshNormalMessageDelivery(event("a")) }
                    withTimeout(5000) {
                        while (server.calls.drop(startCalls).none { it.getQueryParameter("message_id") == "a" }) delay(10)
                    }
                    vm.refreshNewMessagesFromServer(allowWhileStreaming = true)
                    delivery.join()
                    vm.historyLoadJob?.join()
                    assertEquals(listOf("u", "a", "b"), ids())
                    assertTrue(vm.pendingNormalDeliveries.isEmpty())

                    // Resume/reconnect without a retained notice also fills
                    // low-sequence holes from the server's published recent page.
                    reset(streaming = true, history = listOf(user, second))
                    vm.refreshNewMessagesFromServer(allowWhileStreaming = true, includeRecent = true)
                    vm.historyLoadJob?.join()
                    assertEquals(listOf("u", "a", "b"), ids())
                    assertFalse(ids().contains("c"))

                    val busEvent = async(start = CoroutineStart.UNDISPATCHED) {
                        withTimeout(2000) { ChatEventBus.completedFlow.first { it.characterId == "bus-test" } }
                    }
                    ChatEventBus.notifyCompleted("bus-test", "normal", 1000, ChatCompletionSource.WS,
                        correlationId = "outbox-${System.nanoTime()}", messageId = "real-message", conversationId = "real-conv")
                    assertEquals("real-message", busEvent.await().messageId)
                    assertEquals("real-conv", busEvent.await().conversationId)
                } finally {
                    vm.viewModelScope.cancel()
                }
            }
        }
        } finally {
            NetworkClient.bindPreferences(AppPreferences(realApp))
            app.filesDir.deleteRecursively()
        }
    }
}
