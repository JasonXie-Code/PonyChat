package top.ponychat.companion.reply

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatAppConversationNavigationPolicyTest {
    @Test
    fun `known chat editor identifies conversation detail`() {
        assertTrue(
            ChatAppConversationNavigationPolicy.isConversationDetail(
                hasKnownEditor = true,
                hasSemanticEditor = false,
                hasSemanticBack = false,
            ),
        )
    }

    @Test
    fun `version independent fallback requires editor and back`() {
        assertTrue(
            ChatAppConversationNavigationPolicy.isConversationDetail(
                hasKnownEditor = false,
                hasSemanticEditor = true,
                hasSemanticBack = true,
            ),
        )
    }

    @Test
    fun `list search box alone is not mistaken for chat detail`() {
        assertFalse(
            ChatAppConversationNavigationPolicy.isConversationDetail(
                hasKnownEditor = false,
                hasSemanticEditor = true,
                hasSemanticBack = false,
            ),
        )
    }
}
