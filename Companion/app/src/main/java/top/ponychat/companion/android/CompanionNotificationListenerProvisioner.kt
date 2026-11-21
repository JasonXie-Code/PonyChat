package top.ponychat.companion.android

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.util.Log
import top.ponychat.companion.reply.QqPrivateReplyService

object CompanionNotificationListenerProvisioner {
    private const val TAG = "CompanionNotification"
    private const val PREFERENCES = "notification_listener_provisioning"
    private const val KEY_DEFAULT_APPLIED = "default_applied"

    fun ensureDefaultEnabled(context: Context): Boolean = apply(context, force = false)

    fun repair(context: Context): Boolean = apply(context, force = true)

    fun isConfigured(context: Context): Boolean {
        val current = Settings.Secure.getString(
            context.contentResolver,
            ENABLED_NOTIFICATION_LISTENERS,
        )
        return ProvisionedServiceList.contains(current, componentName(context))
    }

    private fun apply(context: Context, force: Boolean): Boolean {
        val storageContext = context.createDeviceProtectedStorageContext()
        val preferences = storageContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!force && !shouldApplyDefault(
                defaultApplied = preferences.getBoolean(KEY_DEFAULT_APPLIED, false),
                configured = isConfigured(context),
            )
        ) return false

        val resolver = context.contentResolver
        val current = Settings.Secure.getString(
            resolver,
            ENABLED_NOTIFICATION_LISTENERS,
        )
        val merged = ProvisionedServiceList.merge(current, componentName(context))

        return try {
            if (merged != current) {
                check(
                    Settings.Secure.putString(
                        resolver,
                        ENABLED_NOTIFICATION_LISTENERS,
                        merged,
                    ),
                )
            }
            preferences.edit().putBoolean(KEY_DEFAULT_APPLIED, true).apply()
            Log.i(TAG, "Applied default Companion notification listener state")
            true
        } catch (error: SecurityException) {
            Log.e(TAG, "Unable to apply default notification listener state", error)
            false
        } catch (error: IllegalStateException) {
            Log.e(TAG, "Unable to persist default notification listener state", error)
            false
        }
    }

    internal fun mergeEnabledListeners(current: String?, component: String): String =
        ProvisionedServiceList.merge(current, component)

    internal fun shouldApplyDefault(defaultApplied: Boolean, configured: Boolean): Boolean =
        !defaultApplied || !configured

    private fun componentName(context: Context): String =
        ComponentName(context, QqPrivateReplyService::class.java).flattenToString()

    private const val ENABLED_NOTIFICATION_LISTENERS = "enabled_notification_listeners"
}
