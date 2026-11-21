package top.ponychat.companion.android

import org.junit.Assert.assertEquals
import org.junit.Test

class CompanionNotificationListenerProvisionerTest {
    private val companion =
        "top.ponychat.companion/top.ponychat.companion.reply.QqPrivateReplyService"

    @Test
    fun `adds Companion when no listener is configured`() {
        assertEquals(
            companion,
            CompanionNotificationListenerProvisioner.mergeEnabledListeners(null, companion),
        )
    }

    @Test
    fun `preserves existing listeners and removes duplicates`() {
        val current = "example.one/.Listener:$companion:example.one/.Listener"

        assertEquals(
            "example.one/.Listener:$companion",
            CompanionNotificationListenerProvisioner.mergeEnabledListeners(current, companion),
        )
    }
}
