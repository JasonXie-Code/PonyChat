package top.ponychat.webview.ui.chat

import android.os.SystemClock
import android.view.MotionEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.model.RelationshipPageContent
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

class RelationshipPullRefreshInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private fun nodes(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
    private fun allNodes(): List<AccessibilityNodeInfo> {
        if (android.os.Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.clearCache()
        return nodes(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun text(value: String) = allNodes().firstOrNull { it.text?.toString() == value }
    private fun screenshot(name: String) {
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
        val file = java.io.File(instrumentation.targetContext.getExternalFilesDir(null), "$name.png")
        file.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
    }
    private fun awaitText(value: String) {
        val end = SystemClock.uptimeMillis() + 5000
        while (text(value) == null && SystemClock.uptimeMillis() < end) SystemClock.sleep(50)
        assertNotNull(value, text(value))
    }

    @Test fun failedPageFollowsFingerAndRefreshReplacesCardsUntilNewPage() {
        val character = Character(id = "pull-fixture", name = "测试")
        var state by mutableStateOf(ChatUiState(character = character,
            hasLoadedRelationshipSnapshot = true, relationshipSnapshotError = "请下拉重试"))
        var refreshes = 0
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { host ->
                if (android.os.Build.VERSION.SDK_INT >= 33) host.setRecentsScreenshotEnabled(false)
                host.setContent {
                PonyChatTheme(darkTheme = true) {
                    ChatRelationshipPanel(character, AppPreferences(host), state, {
                        refreshes++
                        state = state.copy(isLoadingRelationshipSnapshot = true,
                            relationshipSnapshot = state.relationshipSnapshot?.copy(pageContent = null),
                            relationshipSnapshotError = null)
                    })
                }
            } }
            awaitText("加载失败")
            screenshot("relationship-failed")
            fun drag(assertFollows: Boolean) {
                val before = android.graphics.Rect().also { text(if (assertFollows) "加载失败" else "旧概述")!!.getBoundsInScreen(it) }
                val screenshot = instrumentation.uiAutomation.takeScreenshot()
                val x = screenshot.width / 2f
                val y = screenshot.height * 0.65f
                screenshot.recycle()
                val start = SystemClock.uptimeMillis()
                fun event(action: Int, distance: Float) {
                    val motion = MotionEvent.obtain(start, SystemClock.uptimeMillis(), action, x, y + distance, 0)
                    instrumentation.uiAutomation.injectInputEvent(motion, true)
                    motion.recycle()
                }
                event(MotionEvent.ACTION_DOWN, 0f)
                for (i in 1..12) { event(MotionEvent.ACTION_MOVE, i * 25f); SystemClock.sleep(20) }
                SystemClock.sleep(150)
                if (assertFollows) {
                    val after = android.graphics.Rect().also { text("加载失败")!!.getBoundsInScreen(it) }
                    assertTrue("Failure content must follow the held finger", after.top > before.top + 20)
                    screenshot("relationship-pulled")
                }
                event(MotionEvent.ACTION_UP, 300f)
            }
            drag(true)
            awaitText("加载中")
            assertEquals(1, refreshes)
            val snapshot = RelationshipSnapshot("pull-fixture", "conv", stageKey = "friend",
                stageLabel = "好友", conversationCount = 1, currentMessageCount = 1,
                totalMessageCount = 1, memoryCount = 1,
                pageContent = RelationshipPageContent(overview = "旧概述", mood = "旧卡片"))
            scenario.onActivity { state = state.copy(isLoadingRelationshipSnapshot = false, relationshipSnapshot = snapshot) }
            awaitText("旧卡片")
            drag(false)
            awaitText("加载中")
            assertEquals(2, refreshes)
            assertNull(text("旧卡片"))
            assertNull(text("旧概述"))
            screenshot("relationship-refresh-skeleton")
            scenario.onActivity { state = state.copy(isLoadingRelationshipSnapshot = false,
                relationshipSnapshot = snapshot.copy(pageContent = RelationshipPageContent(overview = "新概述", mood = "新卡片"))) }
            awaitText("新卡片")
            screenshot("relationship-refreshed")
            assertNull(text("旧卡片"))
        }
    }
}
