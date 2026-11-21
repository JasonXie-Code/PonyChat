package top.ponychat.companion.android

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Build

/** Only a physical device with the system runtime installed gets the host experience. */
internal object DeviceProvisioningPolicy {
    fun isProvisioned(context: Context): Boolean = isProvisioned(
        context.applicationInfo.flags,
        Build.HARDWARE,
        Build.MODEL,
    )

    internal fun isProvisioned(flags: Int, hardware: String, model: String): Boolean {
        val emulator = hardware.equals("ranchu", ignoreCase = true) ||
            hardware.equals("goldfish", ignoreCase = true) ||
            model.startsWith("sdk_", ignoreCase = true) ||
            model.contains("Android SDK", ignoreCase = true)
        val systemInstalled = flags and
            (ApplicationInfo.FLAG_SYSTEM or ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) != 0
        return systemInstalled && !emulator
    }
}
