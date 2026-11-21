package top.ponychat.webview.ui.chat

import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.CustomToast
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.common.AppPromptBus
import top.ponychat.webview.ui.common.CollectAppPrompts
import top.ponychat.webview.ui.common.PonyPromptBubble
import top.ponychat.webview.ui.common.AppFeedbackHost
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.first

class ChatFeedbackPreviewTest {
    @Test fun creationFailureUsesSharedDialogAndCanRetryAfterDismissal() {
        val session = top.ponychat.webview.ui.creation.CreationSession("failure-preview", "预览",
            messages = listOf(top.ponychat.webview.ui.creation.CreationMessage("user", "user", "写一个故事", 1, "request")),
            lastError = "服务暂时不可用，请重试")
        val state = mutableStateOf(top.ponychat.webview.ui.creation.CreationUiState(session = session, loading = false))
        var retries = 0
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent {
                PonyChatTheme(darkTheme = true) {
                    top.ponychat.webview.ui.creation.CreationChatContent("小呆", state.value,
                        {}, {}, {}, { retries++ }, {}, {})
                }
            } }
            awaitText("本次请求未完成")
            awaitText("用户说明")
            awaitText("调试信息")
            awaitText("重新生成")
            // Background recovery must not hide a failure the user has not dismissed.
            scenario.onActivity { state.value = state.value.copy(session = session.copy(lastError = null)) }
            awaitText("服务暂时不可用")
            awaitText("重新生成")
            screenshot("creation-failure-shared-dialog.png")
            click("关闭")
            instrumentation.waitForIdleSync()
            awaitAbsent("本次请求未完成")
            scenario.onActivity { state.value = state.value.copy(sending = true) }
            instrumentation.waitForIdleSync()
            scenario.onActivity { state.value = state.value.copy(sending = false, session = session) }
            awaitText("重新生成")
            click("重新生成")
            assertEquals(1, retries)
            awaitAbsent("本次请求未完成")
            scenario.onActivity { state.value = state.value.copy(session = session.copy(lastError = null), error = "已停止生成，已保留输出内容") }
            instrumentation.waitForIdleSync()
            awaitAbsent("本次请求未完成")
            awaitAbsent("已停止生成")
        }
    }

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private fun find(text: String, node: AccessibilityNodeInfo? = instrumentation.uiAutomation.rootInActiveWindow): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.text?.toString()?.contains(text) == true) return node
        return (0 until node.childCount).firstNotNullOfOrNull { find(text, node.getChild(it)) }
    }
    private fun awaitText(text: String) {
        repeat(40) {
            instrumentation.uiAutomation.clearCache()
            if (find(text) != null) return
            SystemClock.sleep(100)
        }
        fail("Missing visible text: $text")
    }
    private fun click(text: String) {
        var node = requireNotNull(find(text))
        while (!node.isClickable && node.parent != null) node = node.parent
        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        instrumentation.waitForIdleSync()
    }
    private fun awaitAbsent(text: String) {
        repeat(40) {
            instrumentation.uiAutomation.clearCache()
            if (find(text) == null) return
            SystemClock.sleep(100)
        }
        fail("Text still visible: $text")
    }
    private fun screenshot(name: String) {
        SystemClock.sleep(350)
        val image = instrumentation.uiAutomation.takeScreenshot()
        File(instrumentation.targetContext.getExternalFilesDir(null), name).outputStream().use {
            image.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        image.recycle()
    }

    @Test fun customPromptAndTwoSectionErrorDialog() {
        val showError = mutableStateOf(false)
        var previewHost: SnackbarHostState? = null
        val debug = "HTTP 504 · Gateway Timeout\n接口：POST /api/chat\n模型：deepseek-flash\n请求编号：preview-request-001\n阶段：模型响应\n等待时间：30 秒"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        val host = remember { SnackbarHostState() }
                        SideEffect { previewHost = host }
                        CollectAppPrompts(host)
                        CompositionLocalProvider(CustomToast provides host) {
                            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).statusBarsPadding()) {
                                Column(Modifier.fillMaxSize()) {
                                    Text("‹    小呆", style = MaterialTheme.typography.headlineSmall,
                                        color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.padding(22.dp))
                                    HorizontalDivider()
                                    ChatScreenStatusBanners(
                                        error = if (showError.value) "模型暂时未能回复，请稍后重试。你发送的消息已保留。" else null,
                                        errorDebug = debug, quotaExceeded = false, quotaExceededMessage = "",
                                        galgameSaveFailed = false, onClearError = { showError.value = false },
                                        onClearQuotaExceeded = {}, onDismissGalgameSaveFailed = {})
                                    Text("小呆", color = Color.Gray, modifier = Modifier.padding(start=24.dp, top=28.dp))
                                    Surface(shape=RoundedCornerShape(18.dp), color=MaterialTheme.colorScheme.surfaceVariant,
                                        modifier=Modifier.padding(horizontal=24.dp, vertical=10.dp)) {
                                        Text("今天过得怎么样？", modifier=Modifier.padding(18.dp), color=MaterialTheme.colorScheme.onSurface)
                                    }
                                    Spacer(Modifier.weight(1f))
                                    OutlinedTextField(value="", onValueChange={}, placeholder={Text("发送消息")},
                                        modifier=Modifier.fillMaxWidth().padding(16.dp).navigationBarsPadding())
                                }
                                AppFeedbackHost(host, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom=100.dp))
                            }
                        }
                    }
                }
            }
            instrumentation.waitForIdleSync()
            awaitText("今天过得怎么样")
            runBlocking { withTimeout(5000) { AppPromptBus.messages.subscriptionCount.first { it > 0 } } }
            AppPromptBus.show("已加入下载")
            awaitText("已加入下载")
            screenshot("custom-toast-preview.png")
            scenario.onActivity {
                previewHost?.currentSnackbarData?.dismiss()
                showError.value = true
            }
            awaitText("本次请求未完成")
            awaitText("用户说明")
            awaitText("调试信息")
            // Simulate the background refresh/recovery clearing transient state.
            scenario.onActivity { showError.value = false }
            SystemClock.sleep(2000)
            awaitText("本次请求未完成")
            awaitText("preview-request-001")
            screenshot("chat-error-dialog-preview.png")
            click("复制")
            scenario.onActivity { activity ->
                val clip = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val copied = clip.primaryClip!!.getItemAt(0).text.toString()
                assertTrue(copied.contains("用户说明："))
                assertTrue(copied.contains("preview-request-001"))
                assertTrue(copied.contains("等待时间：30 秒"))
            }
            click("关闭")
            instrumentation.uiAutomation.clearCache()
            awaitAbsent("本次请求未完成")
            // A later occurrence of the same error must still open a new dialog.
            scenario.onActivity { showError.value = true }
            awaitText("本次请求未完成")
            click("关闭")
            instrumentation.uiAutomation.clearCache()
            awaitAbsent("本次请求未完成")
            SystemClock.sleep(10000) // Let Android's clipboard preview close before the next screenshot.
            AppPromptBus.show("DeepSeek 单次请求超过 30 秒未返回，服务暂不可用，请等待修复。")
            awaitText("服务暂不可用")
            SystemClock.sleep(5000) // The old short snackbar duration must not dismiss this dialog.
            awaitText("服务暂不可用")
            screenshot("deepseek-long-dialog-preview.png")
            click("关闭")
        }
    }
}
