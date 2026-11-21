package top.ponychat.webview.ui.creation

import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

class CreationStreamingControlsInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private val actions = setOf("复制 Markdown", "删除回复", "重新生成", "续写")
    private fun nodes(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
    private fun descriptions(): List<String> {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { nodes(it.root) }.mapNotNull { it.contentDescription?.toString() }
    }
    private fun until(check: () -> Boolean) {
        repeat(60) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for reply actions")
    }
    private fun capture(name: String) {
        val bitmap = instrument.uiAutomation.takeScreenshot()
        File(instrument.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    @Test fun streamingHidesAllReplyActionsAndCompletionOrStopRestoresThem() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val session = CreationSession("stream-controls", "操作验证", messages = listOf(
            CreationMessage("old-user", "user", "第一段故事", 0, "old"),
            CreationMessage("old-reply", "assistant", "之前已经完成的回复。", 0, "old"),
            CreationMessage("user", "user", "请继续写故事", 0, "new"),
            CreationMessage("stream-new", "assistant", "正在生成的正文：雨声渐渐停了。", 0, "new", true)))
        val state = mutableStateOf(CreationUiState(session = session, loading = false, sending = true))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent { PonyChatTheme(darkTheme = true) {
                    CreationChatContent("云杉", state.value, {}, {}, {}, {}, {}, {})
                } }
            }
            until { descriptions().contains("停止生成") }
            assertTrue("No action controls, including historical reply actions", descriptions().none { it in actions })
            capture("creation-streaming-no-controls.png")
            scenario.onActivity { state.value = state.value.copy(sending = false, session = session.copy(busy = true)) }
            instrument.waitForIdleSync()
            assertTrue("Recovered server stream also hides actions", descriptions().none { it in actions })
            // Deliberate stop keeps the partial message and restores its operations.
            scenario.onActivity { state.value = state.value.copy(session = session, stoppedSessionId = session.id) }
            until { descriptions().containsAll(actions) }
            assertEquals("Both historical and current reply actions return", 2,
                descriptions().count { it == "复制 Markdown" })
            capture("creation-stopped-controls-restored.png")
            scenario.onActivity { state.value = state.value.copy(sending = true, stoppedSessionId = null) }
            until { descriptions().contains("停止生成") && descriptions().none { it in actions } }
            scenario.onActivity { state.value = state.value.copy(sending = false,
                session = session.copy(messages = session.messages.dropLast(1) + session.messages.last().copy(
                    id = "completed", incomplete = false))) }
            until { descriptions().containsAll(actions) }
            capture("creation-completed-controls-restored.png")
        }
    }
}
