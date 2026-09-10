package top.ponychat.companion.overlay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import top.ponychat.companion.android.CompanionAccessibilityProvisioner
import top.ponychat.companion.android.CompanionNotificationListenerProvisioner
import top.ponychat.companion.reply.CompanionSessionStore

class CompanionBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        CompanionAccessibilityProvisioner.ensureDefaultEnabled(context)
        CompanionNotificationListenerProvisioner.ensureDefaultEnabled(context)
        when (intent?.action) {
            Intent.ACTION_LOCKED_BOOT_COMPLETED -> AgentOverlayController.ensureStarted(context)
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_USER_UNLOCKED -> {
                CompanionSessionStore.initialize(context)
                AgentOverlayController.ensureStarted(context)
            }
            Intent.ACTION_MY_PACKAGE_REPLACED -> Unit
        }
    }
}
