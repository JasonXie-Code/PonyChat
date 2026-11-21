package top.ponychat.companion.reply

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqAutomaticReplyGateTest {
    @Test
    fun `limits one sender without blocking normal traffic forever`() {
        val limiter = QqReplyRateLimiter(windowMs = 1_000, maxTotal = 5, maxPerSender = 2)

        assertTrue(limiter.tryAcquire("A", 0))
        assertTrue(limiter.tryAcquire("A", 100))
        assertFalse(limiter.tryAcquire("A", 200))
        assertTrue(limiter.tryAcquire("A", 1_000))
    }

    @Test
    fun `limits aggregate automatic replies across senders`() {
        val limiter = QqReplyRateLimiter(windowMs = 1_000, maxTotal = 2, maxPerSender = 2)

        assertTrue(limiter.tryAcquire("A", 0))
        assertTrue(limiter.tryAcquire("B", 100))
        assertFalse(limiter.tryAcquire("C", 200))
    }
}
