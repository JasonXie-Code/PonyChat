package top.ponychat.webview

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionIdentityPolicyTest {
    @Test
    fun roleSwitchRequiresConfirmedMemoryPersistence() {
        assertTrue(isCompanionMemoryFlushConfirmed("ok", true))
        assertFalse(isCompanionMemoryFlushConfirmed("partial", false))
        assertFalse(isCompanionMemoryFlushConfirmed("error", true))
    }
}
