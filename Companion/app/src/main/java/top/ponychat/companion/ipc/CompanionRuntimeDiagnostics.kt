package top.ponychat.companion.ipc

import android.Manifest
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import org.json.JSONObject
import top.ponychat.companion.android.CompanionAccessibilityProvisioner
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.android.CompanionNotificationListenerProvisioner

internal object CompanionRuntimeDiagnostics {
    fun snapshot(context: Context, protocolVersion: Int): String =
        baseSnapshot(context, protocolVersion).toString()

    fun repairProvisioning(context: Context, protocolVersion: Int): String {
        val accessibilityApplied = CompanionAccessibilityProvisioner.repair(context)
        val notificationApplied = CompanionNotificationListenerProvisioner.repair(context)
        return baseSnapshot(context, protocolVersion)
            .put("repairRequested", true)
            .put("accessibilityRepairApplied", accessibilityApplied)
            .put("notificationRepairApplied", notificationApplied)
            .toString()
    }

    private fun baseSnapshot(context: Context, protocolVersion: Int): JSONObject {
        val flags = context.applicationInfo.flags
        val isSystemApp = flags and ApplicationInfo.FLAG_SYSTEM != 0 ||
            flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0
        val isDebuggable = flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        val hasSecureSettings = context.checkSelfPermission(Manifest.permission.WRITE_SECURE_SETTINGS) ==
            PackageManager.PERMISSION_GRANTED

        return JSONObject()
            .put("schemaVersion", 1)
            .put("protocolVersion", protocolVersion)
            .put("packageName", context.packageName)
            .put("runtimeVersion", runtimeVersion(context))
            .put("buildType", Build.TYPE)
            .put("buildTags", Build.TAGS.orEmpty())
            .put("systemApp", isSystemApp)
            .put("debuggable", isDebuggable)
            .put("productionBuild", Build.TYPE == "user" && !isDebuggable)
            .put("secureSettingsGranted", hasSecureSettings)
            .put(
                "accessibilityConfigured",
                CompanionAccessibilityProvisioner.isConfigured(context),
            )
            .put("accessibilityBound", CompanionAccessibilityService.instance != null)
            .put(
                "notificationListenerConfigured",
                CompanionNotificationListenerProvisioner.isConfigured(context),
            )
            .put("overlayAllowed", Settings.canDrawOverlays(context))
            .put("uptimeMillis", SystemClock.elapsedRealtime())
    }

    private fun runtimeVersion(context: Context): String = runCatching {
        @Suppress("DEPRECATION")
        context.packageManager.getPackageInfo(context.packageName, 0).versionName.orEmpty()
    }.getOrDefault("")
}
