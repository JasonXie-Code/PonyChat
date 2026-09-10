package top.ponychat.companion.android

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.util.Log

object CompanionAccessibilityProvisioner {
    private const val TAG = "CompanionAccessibility"
    private const val PREFERENCES = "accessibility_provisioning"
    private const val KEY_DEFAULT_APPLIED = "default_applied"

    fun ensureDefaultEnabled(context: Context): Boolean = apply(context, force = false)

    fun repair(context: Context): Boolean = apply(context, force = true)

    fun isConfigured(context: Context): Boolean {
        val current = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        )
        return ProvisionedServiceList.contains(current, componentName(context)) &&
            Settings.Secure.getInt(
                context.contentResolver,
                Settings.Secure.ACCESSIBILITY_ENABLED,
                0,
            ) == 1
    }

    private fun apply(context: Context, force: Boolean): Boolean {
        val storageContext = context.createDeviceProtectedStorageContext()
        val preferences = storageContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!force && !shouldApplyDefault(
                defaultApplied = preferences.getBoolean(KEY_DEFAULT_APPLIED, false),
                configured = isConfigured(context),
            )
        ) return false

        val component = componentName(context)
        val resolver = context.contentResolver
        val current = Settings.Secure.getString(
            resolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        )
        val merged = ProvisionedServiceList.merge(current, component)

        return try {
            if (merged != current) {
                check(Settings.Secure.putString(
                    resolver,
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
                    merged,
                ))
            }
            check(Settings.Secure.putInt(resolver, Settings.Secure.ACCESSIBILITY_ENABLED, 1))
            preferences.edit().putBoolean(KEY_DEFAULT_APPLIED, true).apply()
            Log.i(TAG, "Applied default Companion accessibility service state")
            true
        } catch (error: SecurityException) {
            Log.e(TAG, "Unable to apply default accessibility state", error)
            false
        } catch (error: IllegalStateException) {
            Log.e(TAG, "Unable to persist default accessibility state", error)
            false
        }
    }

    internal fun mergeEnabledServices(current: String?, component: String): String =
        ProvisionedServiceList.merge(current, component)

    internal fun shouldApplyDefault(defaultApplied: Boolean, configured: Boolean): Boolean =
        !defaultApplied || !configured

    private fun componentName(context: Context): String =
        ComponentName(context, CompanionAccessibilityService::class.java).flattenToString()
}
