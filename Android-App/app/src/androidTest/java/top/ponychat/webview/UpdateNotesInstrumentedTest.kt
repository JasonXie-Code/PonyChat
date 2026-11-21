package top.ponychat.webview

import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

class UpdateNotesInstrumentedTest {
    @Test fun updateDialogShowsReleaseNotesAndInstallAction() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val encoded = InstrumentationRegistry.getArguments().getString("release_notes_b64")
        val releaseNotes = encoded?.let {
            String(android.util.Base64.decode(it, android.util.Base64.DEFAULT), Charsets.UTF_8)
        } ?: "为角色列表、聊天记录、记忆、主动任务、场景卡片和个人偏好等内容加载加入骨架动画。"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme {
                        UpdateAvailableDialog(
                            currentVersion = "6.0.39", latestVersion = BuildConfig.VERSION_NAME,
                            releaseNotes = releaseNotes,
                            downloadUrl = "https://example.invalid/test.apk", onDismiss = {},
                        )
                    }
                }
            }
            instrumentation.waitForIdleSync()
            var texts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            repeat(20) {
                if (texts.any { it.contains(releaseNotes.substringBefore('\n')) }) return@repeat
                SystemClock.sleep(250)
                texts = collectTexts(instrumentation.uiAutomation.rootInActiveWindow)
            }
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            val target = File(instrumentation.targetContext.getExternalFilesDir(null), "update-notes.png")
            target.outputStream().use { screenshot.compress(Bitmap.CompressFormat.PNG, 100, it) }
            screenshot.recycle()
            assertTrue(texts.toString(), texts.any { it.contains("更新内容") })
            assertTrue(texts.any { it.contains(releaseNotes.substringBefore('\n')) })
            assertTrue(texts.any { it.contains(BuildConfig.VERSION_NAME) })
        }
    }

    private fun collectTexts(node: AccessibilityNodeInfo?): List<String> {
        if (node == null) return emptyList()
        val texts = mutableListOf<String>()
        node.text?.toString()?.let(texts::add)
        node.contentDescription?.toString()?.let(texts::add)
        for (index in 0 until node.childCount) texts += collectTexts(node.getChild(index))
        return texts
    }
}
