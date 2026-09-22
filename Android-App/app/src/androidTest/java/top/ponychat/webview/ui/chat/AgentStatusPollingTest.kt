package top.ponychat.webview.ui.chat

import androidx.compose.runtime.AbstractApplier
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Composition
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.snapshots.Snapshot
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import top.ponychat.webview.data.api.ApiService
import java.io.IOException
import java.util.concurrent.atomic.AtomicInteger

/** Actual Compose recomposition and Retrofit proxy, without production accounts or HTTP. */
class AgentStatusPollingTest {
    private class EmptyApplier : AbstractApplier<Unit>(Unit) {
        override fun insertBottomUp(index: Int, instance: Unit) = Unit
        override fun insertTopDown(index: Int, instance: Unit) = Unit
        override fun move(from: Int, to: Int, count: Int) = Unit
        override fun remove(index: Int, count: Int) = Unit
        override fun onClear() = Unit
    }

    private class Owner : LifecycleOwner {
        override val lifecycle = LifecycleRegistry(this)
    }

    private class Probe {
        val owner = Owner()
        val scope = mutableStateOf(AgentStatusScope("synthetic", "http://127.0.0.1/", "pony", "normal", "first"))
        var latest: AgentStatusSnapshot? = null
        val notices = mutableListOf<String?>()
    }

    private suspend fun mounted(
        delayRequest: (Int, String) -> Long,
        scenario: suspend (Probe, AtomicInteger) -> Unit,
    ) = withContext(Dispatchers.Main) {
        coroutineScope {
            val requests = AtomicInteger()
            val client = OkHttpClient.Builder().addInterceptor { chain ->
                val count = requests.incrementAndGet()
                val conversation = chain.request().url.queryParameter("conversation_id").orEmpty()
                try {
                    Thread.sleep(delayRequest(count, conversation))
                } catch (interrupted: InterruptedException) {
                    throw IOException("Test request cancelled", interrupted)
                }
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("OK").body(("""{"success":true,"agent":{
                        "run_id":"$conversation","status":"running","activity":"正在调用模型",
                        "model_calls":$count,"tool_calls":$count,"points":${count * 2},"elapsed_ms":10},
                        "conversation_activity":{"state":"pending","server_now_ms":100000,"due_at_ms":160000,
                        "proactive_enabled":true,"consecutive_count":$count}}
                    """).toResponseBody("application/json".toMediaType())).build()
            }.build()
            val api = Retrofit.Builder().baseUrl("http://127.0.0.1/").client(client)
                .addConverterFactory(GsonConverterFactory.create()).build().create(ApiService::class.java)
            // This behavior in the pinned Retrofit version caused the original effect-key bug.
            assertFalse(api.equals(api))
            val probe = Probe()
            probe.owner.lifecycle.currentState = Lifecycle.State.STARTED
            val clock = BroadcastFrameClock()
            val recomposer = Recomposer(coroutineContext + clock)
            val composition = Composition(EmptyApplier(), recomposer)
            val runner = launch(clock) { recomposer.runRecomposeAndApplyChanges() }
            val frames = launch {
                while (isActive) {
                    // A runtime-only Composition has no ComposeView to drive
                    // global snapshot notifications; deliver them with frames.
                    Snapshot.sendApplyNotifications()
                    clock.sendFrame(System.nanoTime())
                    delay(16)
                }
            }
            try {
                composition.setContent {
                    val result = rememberAgentStatus(probe.scope.value, probe.owner, api)
                    probe.latest = result
                    probe.notices.add(result.notice)
                }
                scenario(probe, requests)
            } finally {
                probe.owner.lifecycle.currentState = Lifecycle.State.DESTROYED
                composition.dispose()
                recomposer.close()
                runner.join()
                frames.cancelAndJoin()
                client.dispatcher.executorService.shutdownNow()
            }
        }
    }

    @Test fun updatesWithoutReopeningAndDoesNotRestartOnClockOrResponseRecomposition() = runBlocking {
        mounted({ _, _ -> 150 }) { probe, requests ->
            delay(3400)
            assertTrue("Counters must update without reopening", (probe.latest?.agent?.modelCalls ?: 0) >= 3)
            assertTrue("Responses and clock ticks must not cause request storms: ${requests.get()}", requests.get() in 3..4)
            assertNull(probe.latest?.notice)
            assertEquals(probe.latest?.agent?.modelCalls, probe.latest?.conversationActivity?.consecutiveCount)
            assertEquals(160000L, probe.latest?.conversationActivity?.dueAtMs)
            probe.owner.lifecycle.currentState = Lifecycle.State.CREATED
            delay(250)
            val pausedCount = requests.get()
            delay(1400)
            assertEquals("No background polling", pausedCount, requests.get())
            probe.owner.lifecycle.currentState = Lifecycle.State.STARTED
            delay(500)
            assertTrue("Foregrounding resumes automatically", requests.get() > pausedCount)
        }
    }

    @Test fun timeoutKeepsLastStateAndRecoversWithoutReopening() = runBlocking {
        mounted({ count, _ -> if (count == 2) 5500 else 100 }) { probe, requests ->
            delay(6600)
            assertEquals(1, probe.latest?.agent?.modelCalls)
            assertEquals(1, probe.latest?.conversationActivity?.consecutiveCount)
            assertTrue(probe.notices.any { it?.contains("超时") == true })
            delay(2200)
            assertTrue((probe.latest?.agent?.modelCalls ?: 0) >= 3)
            assertNull(probe.latest?.notice)
            assertTrue("Retries remain bounded", requests.get() <= 4)
        }
    }

    @Test fun switchingConversationCancelsOldRequestAndDoesNotLeakItsResult() = runBlocking {
        mounted({ _, conversation -> if (conversation == "first") 700 else 100 }) { probe, _ ->
            delay(100)
            probe.scope.value = probe.scope.value.copy(username = "other-synthetic", conversationId = "second")
            delay(900)
            assertEquals("second", probe.latest?.agent?.runId)
            assertEquals(probe.latest?.agent?.modelCalls, probe.latest?.conversationActivity?.consecutiveCount)
            assertNull(probe.latest?.notice)
        }
    }
}
