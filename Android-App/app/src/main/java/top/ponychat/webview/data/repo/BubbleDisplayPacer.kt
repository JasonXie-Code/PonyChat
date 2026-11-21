package top.ponychat.webview.data.repo

import android.os.SystemClock
import kotlinx.coroutines.delay
import org.json.JSONObject
import kotlin.math.abs

/** Keeps assistant bubbles paced on a healthy stream while letting overdue batches catch up. */
internal class BubbleDisplayPacer(
    private val elapsedRealtimeMs: () -> Long = SystemClock::elapsedRealtime,
    private val wallClockMs: () -> Long = System::currentTimeMillis,
    private val suspendDelay: suspend (Long) -> Unit = { delay(it) },
) {
    private val overdueGraceMs = 1_000L
    private val trustedClockSkewMs = 5 * 60_000L
    private var lastDisplayAtMs = 0L
    private var firstDisplayEventPending = true
    private var serverClockBaseMs = 0L
    private var clientClockBaseMs = 0L

    suspend fun pace(event: JSONObject, compensateElapsed: Boolean) {
        if (!isDisplayPacedEvent(event)) return
        if (event.optBoolean("delivery_paced", false)) {
            // The server has already waited before releasing this event. Device
            // clock skew must not add a second typing delay.
            firstDisplayEventPending = false
            lastDisplayAtMs = elapsedRealtimeMs()
            event.put("client_display_overdue", false)
            return
        }
        val displayAtServerMs = event.optLong("display_at_server_ms", 0L).takeIf { it > 0L }
        if (displayAtServerMs != null) {
            paceScheduledEvent(event, displayAtServerMs)
            return
        }
        paceRelativeEvent(event, compensateElapsed)
    }

    private suspend fun paceScheduledEvent(event: JSONObject, displayAtServerMs: Long) {
        val eventServerNowMs = event.optLong("server_now_ms", 0L).takeIf { it > 0L }
        val clientWallNowMs = wallClockMs()
        val serverNowEstimate = when {
            eventServerNowMs != null && abs(clientWallNowMs - eventServerNowMs) <= trustedClockSkewMs -> {
                clientWallNowMs
            }
            else -> {
                if (serverClockBaseMs <= 0L && eventServerNowMs != null) {
                    serverClockBaseMs = eventServerNowMs
                    clientClockBaseMs = elapsedRealtimeMs()
                }
                estimatedServerNowMs() ?: eventServerNowMs ?: clientWallNowMs
            }
        }
        val remainingDelayMs = (displayAtServerMs - serverNowEstimate).coerceAtLeast(0L)
        if (remainingDelayMs > 0L) suspendDelay(remainingDelayMs)
        val afterServerNowMs = when {
            eventServerNowMs != null && abs(wallClockMs() - eventServerNowMs) <= trustedClockSkewMs -> wallClockMs()
            else -> estimatedServerNowMs() ?: eventServerNowMs ?: wallClockMs()
        }
        event.put("client_display_overdue", afterServerNowMs - displayAtServerMs > overdueGraceMs)
        firstDisplayEventPending = false
        lastDisplayAtMs = elapsedRealtimeMs()
    }

    private suspend fun paceRelativeEvent(event: JSONObject, compensateElapsed: Boolean) {
        if (firstDisplayEventPending) {
            firstDisplayEventPending = false
            lastDisplayAtMs = elapsedRealtimeMs()
            event.put("client_display_overdue", false)
            return
        }
        val delayMs = when {
            event.has("display_delay_ms") -> event.optLong("display_delay_ms", 0L)
            event.has("display_delay_seconds") -> (event.optDouble("display_delay_seconds", 0.0) * 1000.0).toLong()
            else -> 0L
        }.coerceAtLeast(0L)
        val nowMs = elapsedRealtimeMs()
        val elapsedSinceLastDisplayMs = if (lastDisplayAtMs > 0L) nowMs - lastDisplayAtMs else 0L
        val remainingDelayMs = if (compensateElapsed && lastDisplayAtMs > 0L) {
            (delayMs - elapsedSinceLastDisplayMs).coerceAtLeast(0L)
        } else {
            delayMs
        }
        if (remainingDelayMs > 0L) suspendDelay(remainingDelayMs)
        lastDisplayAtMs = elapsedRealtimeMs()
        event.put("client_display_overdue", false)
    }

    private fun estimatedServerNowMs(): Long? {
        if (serverClockBaseMs <= 0L || clientClockBaseMs <= 0L) return null
        return serverClockBaseMs + (elapsedRealtimeMs() - clientClockBaseMs).coerceAtLeast(0L)
    }

    private fun isDisplayPacedEvent(event: JSONObject): Boolean =
        event.optString("type", "") in setOf("assistant_paragraph", "assistant_asset")
}
