package top.ponychat.companion.reply

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqConversationClassifierTest {
    @Test
    fun `confirmed private QQ message can be replied`() {
        assertEquals(
            QqConversationKind.PRIVATE,
            QqConversationClassifier.classify(
                QqNotificationEnvelope(
                    packageName = "com.tencent.mobileqq",
                    sender = "Jason",
                    text = "你好",
                    isGroupConversation = false,
                ),
            ),
        )
    }

    @Test
    fun `group and ambiguous notifications are never replied`() {
        val group = QqNotificationEnvelope(
            "com.tencent.mobileqq", "成员", "你好", conversationTitle = "测试群",
        )
        val ambiguous = QqNotificationEnvelope("com.tencent.mobileqq", "Jason", "你好")

        assertEquals(QqConversationKind.GROUP, QqConversationClassifier.classify(group))
        assertEquals(QqConversationKind.UNKNOWN, QqConversationClassifier.classify(ambiguous))
        assertFalse(QqConversationClassifier.canVerifyInForeground(group))
        assertTrue(QqConversationClassifier.canVerifyInForeground(ambiguous))
    }

    @Test
    fun `foreground verification strips qq private unread count suffix`() {
        val notification = QqNotificationEnvelope(
            "com.tencent.mobileqq",
            "谢永鹏@JasonXie(2条新消息)",
            "晚上好",
        )

        assertEquals(
            "谢永鹏@JasonXie",
            QqConversationClassifier.foregroundVerificationSender(notification),
        )
    }

    @Test
    fun `qq security center and sensitive notices are never replied`() {
        val securityCenter = QqNotificationEnvelope(
            "com.tencent.mobileqq",
            "QQ安全中心",
            "已登录设备风险提醒",
            isGroupConversation = false,
        )
        val sensitiveNotice = QqNotificationEnvelope(
            "com.tencent.mobileqq",
            "普通联系人",
            "请把短信验证码发给我",
            isGroupConversation = false,
        )

        assertEquals(QqConversationKind.UNKNOWN, QqConversationClassifier.classify(securityCenter))
        assertEquals(QqConversationKind.UNKNOWN, QqConversationClassifier.classify(sensitiveNotice))
        assertFalse(QqConversationClassifier.canVerifyInForeground(securityCenter))
        assertFalse(QqConversationClassifier.canVerifyInForeground(sensitiveNotice))
    }
}
