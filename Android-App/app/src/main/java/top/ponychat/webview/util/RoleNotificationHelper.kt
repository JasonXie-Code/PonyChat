package top.ponychat.webview.util

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

/**
 * 角色消息类系统通知是否实际能展示（运行时「发送通知」权限 + 应用总开关）。
 * 与 [top.ponychat.webview.PonyChatApp.createNotificationChannels] 中「角色消息」渠道配合使用。
 */
object RoleNotificationHelper {

    fun canPostRoleNotifications(context: Context): Boolean {
        val app = context.applicationContext
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                return false
            }
        }
        return NotificationManagerCompat.from(app).areNotificationsEnabled()
    }

    /** 用于设置页提示：若无法发通知，返回简短原因（简体） */
    fun roleNotificationBlockHint(context: Context): String? {
        val app = context.applicationContext
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                return "未授予「通知」权限，无法在通知栏提醒"
            }
        }
        if (!NotificationManagerCompat.from(app).areNotificationsEnabled()) {
            return "系统已关闭本应用通知，请在系统设置中开启"
        }
        return null
    }

    fun openAppNotificationSettings(context: Context) {
        val app = context.applicationContext
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, app.packageName)
            }
        } else {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = Uri.fromParts("package", app.packageName, null)
            }
        }
        try {
            context.startActivity(intent)
        } catch (_: Exception) {
            try {
                app.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (_: Exception) {
            }
        }
    }
}
