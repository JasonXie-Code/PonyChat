package top.ponychat.companion.reply

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqNotificationVerificationCandidateTest {
    private val candidate = QqNotificationVerificationCandidate(
        sender = "谢永鹏@JasonXie",
        messageFingerprint = QqReplyEventId.messageFingerprint("谢永鹏@JasonXie", "后台测试"),
        postTime = 1_000L,
    )

    @Test
    fun `requires exact sender and message fingerprint`() {
        assertTrue(candidate.matches("谢永鹏@JasonXie", "后台测试"))
        assertFalse(candidate.matches("其他联系人", "后台测试"))
        assertFalse(candidate.matches("谢永鹏@JasonXie", "另一条消息"))
    }

    @Test
    fun `expires outside short foreground verification window`() {
        assertFalse(candidate.isExpired(now = 45_000L))
        assertTrue(candidate.isExpired(now = 46_001L))
        assertTrue(candidate.copy(postTime = 0L).isExpired(now = 1_000L))
    }
}
