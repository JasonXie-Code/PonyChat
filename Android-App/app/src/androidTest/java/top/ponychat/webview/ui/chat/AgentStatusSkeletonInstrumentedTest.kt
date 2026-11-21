package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.AgentRunStatus
import top.ponychat.webview.data.model.ConversationActivity
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

@RunWith(AndroidJUnit4::class)
class AgentStatusSkeletonInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private fun texts(node: AccessibilityNodeInfo?): List<String> = if (node == null) emptyList() else
        listOfNotNull(node.text?.toString(), node.contentDescription?.toString()) +
            (0 until node.childCount).flatMap { texts(node.getChild(it)) }

    private fun visible(): List<String> {
        if (android.os.Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.clearCache()
        return texts(instrumentation.uiAutomation.rootInActiveWindow)
    }

    private fun screenshot(name: String) {
        val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        File(instrumentation.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    private fun await(label: String, predicate: (List<String>) -> Boolean) {
        repeat(60) {
            if (predicate(visible())) return
            SystemClock.sleep(100)
        }
        screenshot("agent-status-failure.png")
        fail("Timed out: $label; visible=${visible()}")
    }

    @Test fun initialSkeletonStopsOnSuccessEmptyOrErrorAndKeepsCachedData() {
        val state = mutableStateOf(AgentStatusSnapshot(null, "正在读取运行状态…", 0, isLoading = true))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme {
                        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                            Column {
                                AgentStatusContent(state.value, "fixture", "normal")
                                ConversationActivityContent(state.value, "normal")
                            }
                        }
                    }
                }
            }
            await("both status skeletons") { it.count { text -> text == "正在加载" } == 2 }
            assertEquals(2, visible().count { it == "正在加载" })
            assertFalse(visible().any { it.contains("暂无这个角色") })
            screenshot("agent-status-skeleton.png")
            val agent = AgentRunStatus(runId = "fixture", mode = "normal", status = "running",
                activity = "正在调用模型", model = "测试模型", currentTools = listOf("web_search"),
                modelCalls = 2, toolCalls = 1, points = 3, elapsedMs = 1234)
            scenario.onActivity {
                state.value = AgentStatusSnapshot(agent, null, 1234,
                    conversationActivity = ConversationActivity(state = "none", proactiveEnabled = true, memoryEnabled = true))
            }
            await("loaded status") { it.any { text -> text.contains("测试模型") } }
            SystemClock.sleep(400)
            assertFalse(visible().any { it == "正在加载" })
            assertTrue(visible().any { it.contains("测试模型") })
            screenshot("agent-status-loaded.png")
            scenario.onActivity { state.value = state.value.copy(notice = "暂时无法刷新运行状态", noticeIsError = true) }
            await("cached error notice") { it.any { text -> text.contains("暂时无法刷新运行状态") } }
            assertTrue(visible().any { it.contains("测试模型") })
            assertFalse(visible().any { it == "正在加载" })
            scenario.onActivity { state.value = AgentStatusSnapshot(null, null, 0) }
            await("empty status") { it.any { text -> text.contains("暂无这个角色的 Agent 运行记录") } }
            assertTrue(visible().any { it.contains("暂无这个角色的 Agent 运行记录") })
            assertFalse(visible().any { it == "正在加载" })
            scenario.onActivity {
                state.value = AgentStatusSnapshot(null, "状态读取超时，正在重试", 0, noticeIsError = true)
            }
            await("timeout notice") { it.any { text -> text.contains("状态读取超时") } }
            assertTrue(visible().any { it.contains("状态读取超时") })
            assertFalse(visible().any { it == "正在加载" })
            screenshot("agent-status-error.png")
        }
    }
}
