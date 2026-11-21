package top.ponychat.webview.ui.chat

import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

/** Exercises the real top-right button and settings screen with chat still composed below. */
@RunWith(AndroidJUnit4::class)
class ChatDisplaySettingsImeInstrumentedTest {
    @Test
    fun settingsButtonClosesImeAndReturningKeepsDraftWithoutRefocusing() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            val requester = FocusRequester()
            val draft = mutableStateOf("对话设置草稿")
            val settingsOpen = mutableStateOf(false)
            var focused = false
            var ready = false
            scenario.onActivity { activity ->
                val prefs = AppPreferences(activity)
                activity.setContent {
                    PonyChatTheme {
                        SideEffect { ready = true }
                        Box(Modifier.fillMaxSize()) {
                            Column {
                                ChatScreenTopBar(
                                    state = ChatUiState(mode = "normal"),
                                    character = Character(id = "ime-test", name = "键盘测试"),
                                    prefs = prefs, isExporting = false,
                                    onBack = {}, onCancelExport = {}, onExport = {},
                                    onOpenCharacterEdit = {}, onResetGalgameProgress = {},
                                    onOpenHistory = {},
                                    onOpenDisplaySettings = { settingsOpen.value = true },
                                )
                                BasicTextField(
                                    value = draft.value, onValueChange = { draft.value = it },
                                    modifier = Modifier.focusRequester(requester)
                                        .onFocusChanged { focused = it.isFocused },
                                )
                            }
                            if (settingsOpen.value) {
                                ChatDisplaySettingsScreen(
                                    prefs = prefs, onDismiss = { settingsOpen.value = false },
                                    onSave = {},
                                )
                            }
                        }
                    }
                }
            }
            fun onMain(check: () -> Boolean): Boolean {
                var value = false
                scenario.onActivity { value = check() }
                return value
            }
            fun imeVisible(): Boolean {
                var visible = false
                scenario.onActivity { visible = ViewCompat.getRootWindowInsets(it.window.decorView)
                    ?.isVisible(WindowInsetsCompat.Type.ime()) == true }
                return visible
            }
            await("composition") { onMain { ready } }
            scenario.onActivity { requester.requestFocus() }
            await("keyboard shown") { imeVisible() }
            var settings: AccessibilityNodeInfo? = null
            await("settings button") {
                settings = findDescription(instrumentation.uiAutomation.rootInActiveWindow, "设置")
                settings != null
            }
            assertTrue("Actual settings button must be clickable",
                settings!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            await("settings opened") { onMain { settingsOpen.value } }
            await("keyboard hidden after opening settings") { !imeVisible() }
            scenario.onActivity {
                assertFalse("Underlying chat must lose focus", focused)
                assertEquals("对话设置草稿", draft.value)
            }
            val back = requireNotNull(findDescription(
                instrumentation.uiAutomation.rootInActiveWindow, "返回"))
            assertTrue(back.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            await("returned to chat") { onMain { !settingsOpen.value } }
            SystemClock.sleep(300)
            assertFalse("Returning must not reopen keyboard", imeVisible())
            scenario.onActivity {
                assertFalse(focused)
                assertEquals("对话设置草稿", draft.value)
            }
        }
    }

    private fun findDescription(node: AccessibilityNodeInfo?, description: String): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.contentDescription?.toString() == description) {
            var target: AccessibilityNodeInfo? = node
            while (target != null && !target.isClickable) target = target.parent
            return target
        }
        for (index in 0 until node.childCount) {
            findDescription(node.getChild(index), description)?.let { return it }
        }
        return null
    }

    private fun await(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 10_000
        while (!condition()) {
            check(SystemClock.uptimeMillis() < deadline) { "Timed out: $description" }
            SystemClock.sleep(50)
        }
    }
}
