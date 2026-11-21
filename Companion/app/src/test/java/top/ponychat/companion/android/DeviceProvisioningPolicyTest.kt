package top.ponychat.companion.android

import android.content.pm.ApplicationInfo
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceProvisioningPolicyTest {
    @Test
    fun debugInstallDoesNotProvisionAnEmulatorOrPhone() {
        assertFalse(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_DEBUGGABLE, "ranchu", "sdk_gphone64_x86_64"))
        assertFalse(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_DEBUGGABLE, "qcom", "Phone"))
        assertFalse(DeviceProvisioningPolicy.isProvisioned(0, "qcom", "Phone"))
    }

    @Test
    fun systemRuntimeAndItsUpdatesProvisionPhysicalDevices() {
        assertTrue(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_SYSTEM, "sun50iw9", "QUAD-CORE H618 p2"))
        assertTrue(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_UPDATED_SYSTEM_APP or ApplicationInfo.FLAG_DEBUGGABLE, "sun50iw9", "QUAD-CORE H618 p2"))
    }

    @Test
    fun systemImageDoesNotTurnAnEmulatorIntoAHost() {
        assertFalse(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_SYSTEM, "ranchu", "sdk_gphone64_x86_64"))
        assertFalse(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_SYSTEM, "goldfish", "Emulator"))
        assertFalse(DeviceProvisioningPolicy.isProvisioned(ApplicationInfo.FLAG_SYSTEM, "other", "Android SDK built for x86"))
    }
}
