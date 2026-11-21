package top.ponychat.webview.data.api

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.graphics.Bitmap
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import java.io.File

class ProviderServiceNoticeTest {
    @Test fun incidentIsVisibleDeduplicatedAndReplacedByRecovery() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val stamp = System.currentTimeMillis()
        val id = "synthetic-$stamp"
        val message = "DeepSeek 单次请求超过 30 秒未返回，服务暂不可用，请等待修复。"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use {
            ProviderServiceNotice.receive(context, id, "unavailable", stamp, message)
            instrumentation.waitForIdleSync()
            val first = manager.activeNotifications.first { it.id == 7310042 }
            assertEquals(message, first.notification.extras.getString(Notification.EXTRA_TEXT))
            SystemClock.sleep(100)
            ProviderServiceNotice.receive(context, id, "unavailable", stamp, message)
            instrumentation.waitForIdleSync()
            assertEquals(first.postTime, manager.activeNotifications.first { it.id == 7310042 }.postTime)
            instrumentation.uiAutomation.executeShellCommand("cmd statusbar expand-notifications").close()
            SystemClock.sleep(500)
            val image = instrumentation.uiAutomation.takeScreenshot()
            File(context.getExternalFilesDir(null), "provider-outage.png").outputStream().use { stream ->
                image.compress(Bitmap.CompressFormat.PNG, 100, stream)
            }
            image.recycle()
            ProviderServiceNotice.receive(context, id, "recovered", stamp+1, "DeepSeek 已恢复正常响应，可以继续聊天。")
            instrumentation.waitForIdleSync()
            assertTrue(manager.activeNotifications.first { it.id == 7310042 }.notification.extras
                .getString(Notification.EXTRA_TEXT).orEmpty().contains("已恢复"))
            ProviderServiceNotice.receive(context, id, "unavailable", stamp, message)
            instrumentation.waitForIdleSync()
            assertTrue(manager.activeNotifications.first { it.id == 7310042 }.notification.extras
                .getString(Notification.EXTRA_TEXT).orEmpty().contains("已恢复"))
            instrumentation.uiAutomation.executeShellCommand("cmd statusbar collapse").close()
            manager.cancel(7310042)
        }
    }
}
