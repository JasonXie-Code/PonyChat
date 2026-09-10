package top.ponychat.companion.android

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProvisionedServiceListTest {
    @Test
    fun `contains matches a complete flattened component only`() {
        val component = "top.ponychat/.Service"
        val current = "other.package/.Service:$component"

        assertTrue(ProvisionedServiceList.contains(current, component))
        assertFalse(ProvisionedServiceList.contains(current, "ponychat/.Service"))
    }
}
