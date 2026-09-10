package top.ponychat.webview

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat

internal fun CompanionService.createNotificationChannel() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        val channel = NotificationChannel(
            CompanionService.CHANNEL_ID,
            "聊天陪玩",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "PonyChat 系统级 Companion 运行状态" }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
}

internal fun CompanionService.buildNotification(): Notification {
    val stopIntent = Intent(this, CompanionService::class.java).apply {
        action = CompanionService.ACTION_STOP
    }
    val stopPending = PendingIntent.getService(
        this,
        0,
        stopIntent,
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )
    return NotificationCompat.Builder(this, CompanionService.CHANNEL_ID)
        .setContentTitle("$characterName 正在使用设备")
        .setContentText("点击悬浮按钮与角色交互；设备操作由 Companion Runtime 执行")
        .setSmallIcon(android.R.drawable.ic_menu_view)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .addAction(android.R.drawable.ic_menu_close_clear_cancel, "停止", stopPending)
        .build()
}
