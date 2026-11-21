package top.ponychat.webview.data.api

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import top.ponychat.webview.ui.common.AppPromptBus
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/** Service incidents are separate from character messages and unread counts. */
internal object ProviderServiceNotice {
    private const val CHANNEL = "provider_service_status"
    private const val NOTIFICATION_ID = 7310042

    @Synchronized
    fun receive(context: Context?, incident: String, state: String, timestamp: Long, message: String) {
        if (context == null || incident.isBlank() || message.isBlank() ||
            state !in setOf("unavailable", "recovered")) return
        val prefs = context.getSharedPreferences(CHANNEL, Context.MODE_PRIVATE)
        val eventKey = "$incident:$state"
        if (prefs.getString("last_event", "") == eventKey || timestamp < prefs.getLong("last_time", 0)) return
        prefs.edit().putString("last_event", eventKey).putLong("last_time", timestamp).apply()
        Handler(Looper.getMainLooper()).post {
            AppPromptBus.show(message)
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                manager.createNotificationChannel(NotificationChannel(CHANNEL, "服务状态通知", NotificationManager.IMPORTANCE_HIGH))
            }
            val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)
            val pending = intent?.let { PendingIntent.getActivity(context, NOTIFICATION_ID, it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE) }
            val notification = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_error)
                .setContentTitle("PonyChat 服务通知")
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pending)
                .build()
            try {
                NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
            } catch (_: SecurityException) {
                // The in-app CustomToast still works when system notifications are disabled.
            }
        }
    }
}
