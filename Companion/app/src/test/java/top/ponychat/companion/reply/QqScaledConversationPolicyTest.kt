package top.ponychat.companion.reply

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqScaledConversationPolicyTest {
    @Test
    fun `enabled clickable full screen control is accepted`() {
        assertTrue(QqScaledConversationPolicy.isExpandControl("全屏", enabled = true, clickable = true))
    }

    @Test
    fun `chat settings sharing resource id semantics are not accepted`() {
        assertFalse(
            QqScaledConversationPolicy.isExpandControl(
                "聊天设置",
                enabled = true,
                clickable = true,
            ),
        )
    }

    @Test
    fun `disabled or non clickable controls are rejected`() {
        assertFalse(QqScaledConversationPolicy.isExpandControl("全屏", enabled = false, clickable = true))
        assertFalse(QqScaledConversationPolicy.isExpandControl("全屏", enabled = true, clickable = false))
    }
}
