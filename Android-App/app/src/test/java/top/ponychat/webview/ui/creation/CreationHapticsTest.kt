package top.ponychat.webview.ui.creation

import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CreationHapticsTest {
    @Test fun repeatedActivationKeepsOneTimerAndStoppingHasNoCompletionPulse() = runBlocking {
        val pulses = mutableListOf<Long>()
        val controller = CreationPulseController(this) { pulses += System.nanoTime() }
        try {
            controller.setActive(true)
            yield()
            assertEquals(1, pulses.size)
            repeat(10) {
                delay(105)
                controller.setActive(true)
            }
            assertTrue("Expected about twelve pulses per second: ${pulses.size}", pulses.size in 12..13)
            assertTrue(pulses.zipWithNext().all { (a, b) -> (b - a) / 1_000_000 >= 80 })
            controller.setActive(false)
            val stoppedCount = pulses.size
            delay(350)
            assertEquals("Stopping must not add a completion vibration", stoppedCount, pulses.size)
            controller.setActive(true)
            yield()
            assertEquals(stoppedCount + 1, pulses.size)
            controller.setActive(false)
            delay(300)
            assertEquals(stoppedCount + 1, pulses.size)
        } finally {
            controller.setActive(false)
        }
    }
}
