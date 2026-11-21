package top.ponychat.webview.data.repo

import android.content.Context
import android.content.ContextWrapper
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.data.model.ChatRequest
import top.ponychat.webview.data.prefs.AppPreferences
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket

/** Exercises the actual OkHttp/SSE path, without production accounts or messages. */
class ChatTransportRecoveryInstrumentedTest {
    private fun checkResponse(status: Int, body: String, truncated: Boolean,
                              verify: (List<ChatDelta>, Throwable?) -> Unit) = runBlocking {
        val realContext = InstrumentationRegistry.getInstrumentation().targetContext
        val prefix = "transport_test_${System.nanoTime()}_"
        val context = object : ContextWrapper(realContext) {
            override fun getApplicationContext(): Context = this
            override fun getSharedPreferences(name: String, mode: Int) =
                super.getSharedPreferences(prefix + name, mode)
        }
        ServerSocket(0, 8, InetAddress.getByName("127.0.0.1")).use { server ->
            val worker = Thread {
                server.accept().use { socket ->
                    socket.soTimeout = 5000
                    val input = socket.getInputStream().bufferedReader()
                    input.readLine()
                    var length = 0
                    while (true) {
                        val line = input.readLine() ?: break
                        if (line.isEmpty()) break
                        if (line.startsWith("Content-Length:", ignoreCase = true))
                            length = line.substringAfter(':').trim().toInt()
                    }
                    repeat(length) { input.read() }
                    val bytes = body.toByteArray(Charsets.UTF_8)
                    val headers = "HTTP/1.1 $status Test\r\nContent-Type: text/event-stream\r\n" +
                        "Content-Length: ${bytes.size + if (truncated) 100 else 0}\r\nConnection: close\r\n\r\n"
                    socket.getOutputStream().apply { write(headers.toByteArray()); write(bytes); flush() }
                }
            }.apply { isDaemon = true; start() }
            val prefs = AppPreferences(context).apply {
                debugMode = true
                activeApiBase = "http://127.0.0.1:${server.localPort}"
                username = "transport_test"
            }
            NetworkClient.bindPreferences(prefs)
            val events = mutableListOf<ChatDelta>()
            try {
                val failure = runCatching {
                    ChatRepository(prefs).sendMessage(ChatRequest(
                        username = "transport_test", characterId = "test", clientId = "single",
                        conversationId = "test-conversation",
                        messages = listOf(ChatMessage(role = "user", content = "test", messageId = "stable-id")),
                    )).toList(events)
                }.exceptionOrNull()
                verify(events, failure)
            } finally {
                NetworkClient.bindPreferences(AppPreferences(realContext))
                worker.join(5000)
            }
        }
    }

    @Test fun disconnectBeforeAcceptanceRemainsRetryable() = checkResponse(200, "", true) { events, failure ->
        assertTrue(failure is IOException)
        assertTrue(events.none { it is ChatDelta.Error || it is ChatDelta.Accepted })
    }

    @Test fun disconnectAfterAcceptancePreservesReceiptForRecovery() = checkResponse(200,
        "data: {\"type\":\"accepted\",\"job_id\":\"job-1\",\"client_message_id\":\"stable-id\"}\n\n", true
    ) { events, failure ->
        assertTrue(failure is IOException)
        assertEquals("stable-id", events.filterIsInstance<ChatDelta.Accepted>().single().clientMessageId)
        assertTrue(events.none { it is ChatDelta.Error || it is ChatDelta.Done })
    }

    @Test fun gatewayTimeoutIsTransportFailure() = checkResponse(504, "", false) { events, failure ->
        assertTrue(failure is IOException)
        assertTrue(events.isEmpty())
    }

    @Test fun quotaIsNotAutomaticallyRetried() = checkResponse(429, "{}", false) { events, failure ->
        assertNull(failure)
        assertTrue(events.single() is ChatDelta.QuotaExceeded)
    }

    @Test fun serverRejectionIsNotTransportFailure() = checkResponse(200,
        "data: {\"error\":\"test rejection\"}\n\n", false
    ) { events, failure ->
        assertNull(failure)
        assertTrue(events.any { it is ChatDelta.Error })
    }

    @Test fun completeStreamStillDeliversReceiptAndDone() = checkResponse(200,
        "data: {\"type\":\"accepted\",\"client_message_id\":\"stable-id\"}\n\ndata: [DONE]\n\n", false
    ) { events, failure ->
        assertNull(failure)
        assertTrue(events.first() is ChatDelta.Accepted)
        assertTrue(events.last() is ChatDelta.Done)
    }
}
