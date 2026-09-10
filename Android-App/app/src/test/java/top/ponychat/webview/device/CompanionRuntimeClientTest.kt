package top.ponychat.webview.device

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionRuntimeClientTest {
    @Test
    fun ordinaryPhoneUsesMobileExperienceWithoutDeviceEnvironment() {
        assertFalse(
            shouldUseDeviceExperience(
                enteredFromDeviceHome = false,
                deviceHomeEnabled = false,
            ),
        )
    }

    @Test
    fun deviceEnvironmentEnablesDeviceExperienceFromNormalLauncher() {
        assertTrue(
            shouldUseDeviceExperience(
                enteredFromDeviceHome = false,
                deviceHomeEnabled = true,
            ),
        )
    }

    @Test
    fun deviceHomeRemainsAvailableDuringRuntimeMaintenance() {
        assertTrue(
            shouldUseDeviceExperience(
                enteredFromDeviceHome = true,
                deviceHomeEnabled = true,
            ),
        )
    }
}
