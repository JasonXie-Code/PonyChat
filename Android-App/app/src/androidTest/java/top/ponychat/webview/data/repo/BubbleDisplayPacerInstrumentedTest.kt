package top.ponychat.webview.data.repo

import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BubbleDisplayPacerInstrumentedTest {
    @Test
    fun serverPacedDeliveryDoesNotWaitAgainForModerateDeviceClockSkew() = runBlocking {
        for (skewMs in listOf(-30_000L, 30_000L)) {
            val delays = mutableListOf<Long>()
            val pacer = BubbleDisplayPacer({ 10_000L }, { 1_000_000L + skewMs }, { delays += it })
            val event = scheduledParagraph(1_000_000L, 1_000_000L)
                .put("delivery_paced", true).put("display_delay_ms", 2500L)
            pacer.pace(event, compensateElapsed = true)
            assertTrue("Server-paced SSE must not incur a second delay", delays.isEmpty())
        }
    }

    @Test
    fun bufferedJsonStillUsesItsClientDeliveryIntervals() = runBlocking {
        val delays = mutableListOf<Long>()
        val pacer = BubbleDisplayPacer({ 10_000L }, { 1_000_000L }, { delays += it })
        repeat(3) {
            pacer.pace(JSONObject().put("type", "assistant_paragraph")
                .put("delivery_paced", false).put("display_delay_ms", 400L), compensateElapsed = false)
        }
        assertEquals(listOf(400L, 400L), delays)
    }

    @Test
    fun healthyStreamDisplaysBubblesAtScheduledIntervals() = runBlocking {
        var elapsedMs = 10_000L
        var wallMs = 1_000_000L
        val delays = mutableListOf<Long>()
        val pacer = BubbleDisplayPacer(
            elapsedRealtimeMs = { elapsedMs },
            wallClockMs = { wallMs },
            suspendDelay = { delayMs ->
                delays += delayMs
                elapsedMs += delayMs
                wallMs += delayMs
            },
        )

        val first = scheduledParagraph(displayAtMs = 1_000_000L, serverNowMs = 1_000_000L)
        val second = scheduledParagraph(displayAtMs = 1_000_500L, serverNowMs = 1_000_000L)
        val third = scheduledParagraph(displayAtMs = 1_000_900L, serverNowMs = 1_000_000L)

        pacer.pace(first, compensateElapsed = true)
        pacer.pace(second, compensateElapsed = true)
        pacer.pace(third, compensateElapsed = true)

        assertEquals(listOf(500L, 400L), delays)
        assertFalse(first.getBoolean("client_display_overdue"))
        assertFalse(second.getBoolean("client_display_overdue"))
        assertFalse(third.getBoolean("client_display_overdue"))
    }

    @Test
    fun weakNetworkBatchDoesNotAddObsoleteTypingDelay() = runBlocking {
        var elapsedMs = 20_000L
        var wallMs = 2_005_000L
        val delays = mutableListOf<Long>()
        val pacer = BubbleDisplayPacer(
            elapsedRealtimeMs = { elapsedMs },
            wallClockMs = { wallMs },
            suspendDelay = { delayMs -> delays += delayMs },
        )

        val first = scheduledParagraph(displayAtMs = 2_000_000L, serverNowMs = 2_000_000L)
        val second = scheduledParagraph(displayAtMs = 2_000_500L, serverNowMs = 2_000_000L)

        pacer.pace(first, compensateElapsed = true)
        pacer.pace(second, compensateElapsed = true)

        assertTrue(delays.isEmpty())
        assertTrue(first.getBoolean("client_display_overdue"))
        assertTrue(second.getBoolean("client_display_overdue"))
    }

    @Test
    fun largeDeviceClockSkewFallsBackToMonotonicScheduling() = runBlocking {
        var elapsedMs = 30_000L
        var wallMs = 7_000_000L
        val delays = mutableListOf<Long>()
        val pacer = BubbleDisplayPacer(
            elapsedRealtimeMs = { elapsedMs },
            wallClockMs = { wallMs },
            suspendDelay = { delayMs ->
                delays += delayMs
                elapsedMs += delayMs
            },
        )

        pacer.pace(scheduledParagraph(3_000_000L, 3_000_000L), compensateElapsed = true)
        pacer.pace(scheduledParagraph(3_000_600L, 3_000_000L), compensateElapsed = true)

        assertEquals(listOf(600L), delays)
    }

    private fun scheduledParagraph(displayAtMs: Long, serverNowMs: Long) = JSONObject()
        .put("type", "assistant_paragraph")
        .put("display_at_server_ms", displayAtMs)
        .put("server_now_ms", serverNowMs)
}
