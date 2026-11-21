package top.ponychat.companion.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionAccessibilityProvisionerTest {

    @Test
    fun `default provisioning repairs a service cleared after it was applied`() {
        assertTrue(
            CompanionAccessibilityProvisioner.shouldApplyDefault(
                defaultApplied = true,
                configured = false,
            ),
        )
    }

    @Test
    fun `default provisioning leaves an already configured service unchanged`() {
        assertFalse(
            CompanionAccessibilityProvisioner.shouldApplyDefault(
                defaultApplied = true,
                configured = true,
            ),
        )
    }
    private val companion =
        "top.ponychat.companion/top.ponychat.companion.android.CompanionAccessibilityService"

    @Test
    fun `adds Companion when no service is configured`() {
        assertEquals(companion, CompanionAccessibilityProvisioner.mergeEnabledServices(null, companion))
    }

    @Test
    fun `preserves existing services when adding Companion`() {
        val existing = "example.one/.Reader:example.two/.Controller"

        assertEquals(
            "$existing:$companion",
            CompanionAccessibilityProvisioner.mergeEnabledServices(existing, companion),
        )
    }

    @Test
    fun `does not duplicate Companion or existing services`() {
        val current = "example.one/.Reader:$companion:example.one/.Reader"

        assertEquals(
            "example.one/.Reader:$companion",
            CompanionAccessibilityProvisioner.mergeEnabledServices(current, companion),
        )
    }
}
