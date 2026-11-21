package top.ponychat.companion.reply

import java.time.LocalDateTime
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqForegroundSafetyTest {
    @Test
    fun `group member count in title is a group signal`() {
        assertTrue(QqForegroundSafety.hasGroupSignals("小马工作室粉丝群(135)"))
        assertTrue(QqForegroundSafety.hasGroupSignals("兴趣小组（42）"))
        assertFalse(QqForegroundSafety.hasGroupSignals("谢永鹏@JasonXie"))
    }

    @Test
    fun `detects known group signals`() {
        assertTrue(QqForegroundSafety.hasGroupSignals("PonyChat交流群, 3条未读"))
        assertTrue(QqForegroundSafety.hasGroupSignals("[@全体成员]晚上开会"))
        assertFalse(QqForegroundSafety.hasGroupSignals("谢永鹏@JasonXie, 1条未读, 晚上好"))
    }

    @Test
    fun `accepts current qq private online status variants`() {
        assertTrue(QqForegroundSafety.isPrivateOnlineStatus("在线"))
        assertTrue(QqForegroundSafety.isPrivateOnlineStatus("在线 - WiFi"))
        assertTrue(QqForegroundSafety.isPrivateOnlineStatus("在线·手机在线"))
        assertFalse(QqForegroundSafety.isPrivateOnlineStatus("3人在线"))
        assertFalse(QqForegroundSafety.isPrivateOnlineStatus("离线"))
    }

    @Test
    fun `suppresses only the same sender and message during qq layout settling`() {
        val handledAt = 1_000L
        assertTrue(
            QqForegroundSafety.isSameMessageWithinSettleWindow(
                "谢永鹏@JasonXie",
                "发送",
                handledAt,
                "谢永鹏@JasonXie",
                "发送",
                15_000L,
                30_000L,
            ),
        )
        assertFalse(
            QqForegroundSafety.isSameMessageWithinSettleWindow(
                "谢永鹏@JasonXie",
                "发送",
                handledAt,
                "谢永鹏@JasonXie",
                "再发一次",
                15_000L,
                30_000L,
            ),
        )
        assertFalse(
            QqForegroundSafety.isSameMessageWithinSettleWindow(
                "谢永鹏@JasonXie",
                "发送",
                handledAt,
                "谢永鹏@Another",
                "发送",
                15_000L,
                30_000L,
            ),
        )
        assertFalse(
            QqForegroundSafety.isSameMessageWithinSettleWindow(
                "谢永鹏@JasonXie",
                "发送",
                handledAt,
                "谢永鹏@JasonXie",
                "发送",
                31_000L,
                30_000L,
            ),
        )
    }

    @Test
    fun `accepts a recent chinese twelve hour label`() {
        val now = LocalDateTime.of(2026, 8, 8, 18, 58)
        assertTrue(QqForegroundSafety.isRecent("晚上6:55", now))
        assertFalse(QqForegroundSafety.isRecent("晚上6:30", now))
    }

    @Test
    fun `accepts recent twenty four hour label and rejects malformed time`() {
        val now = LocalDateTime.of(2026, 8, 8, 18, 58)
        assertTrue(QqForegroundSafety.isRecent("18:57", now))
        assertFalse(QqForegroundSafety.isRecent("晚上18:57", now))
        assertFalse(QqForegroundSafety.isRecent("刚刚", now))
    }

    @Test
    fun `message text must vertically overlap its sender profile row`() {
        assertTrue(QqForegroundSafety.isSameMessageRow(388, 549, 409, 514))
        assertFalse(QqForegroundSafety.isSameMessageRow(844, 954, 409, 514))
        assertFalse(QqForegroundSafety.isSameMessageRow(844, 954, 666, 771))
    }

    @Test
    fun `sent message verification requires an overlapping avatar on the right`() {
        assertTrue(QqForegroundSafety.isOwnOutgoingMessageRow(540, 996, 268, 624, 289, 394))
        assertFalse(QqForegroundSafety.isOwnOutgoingMessageRow(540, 84, 268, 624, 289, 394))
        assertFalse(QqForegroundSafety.isOwnOutgoingMessageRow(540, 996, 268, 624, 700, 805))
    }

    @Test
    fun `supports exact text and opaque qq bubble verification`() {
        assertTrue(QqForegroundSafety.isSentMessageVerified(true, true, false, false))
        assertTrue(QqForegroundSafety.isSentMessageVerified(true, false, true, true))
        assertFalse(QqForegroundSafety.isSentMessageVerified(false, true, true, true))
        assertFalse(QqForegroundSafety.isSentMessageVerified(true, false, true, false))
        assertFalse(QqForegroundSafety.isSentMessageVerified(true, false, false, true))
    }
}
