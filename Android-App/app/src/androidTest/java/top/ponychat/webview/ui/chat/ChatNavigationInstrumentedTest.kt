package top.ponychat.webview.ui.chat

import android.os.SystemClock
import androidx.activity.compose.setContent
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.debug.DialogPreviewActivity

@RunWith(AndroidJUnit4::class)
class ChatNavigationInstrumentedTest {
    @Test
    fun navigationDismissesRealImeAndDoesNotRestoreFocus() {
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            val requester = FocusRequester()
            val draft = mutableStateOf("未发送的草稿")
            var focused = false
            var navigate: ((() -> Unit) -> Unit)? = null
            var calls = 0
            scenario.onActivity { activity ->
                activity.setContent {
                    val action = rememberChatNavigation()
                    SideEffect { navigate = action }
                    BasicTextField(
                        value = draft.value,
                        onValueChange = { draft.value = it },
                        modifier = Modifier.focusRequester(requester)
                            .onFocusChanged { focused = it.isFocused },
                    )
                }
            }
            waitUntil { navigate != null }
            scenario.onActivity { requester.requestFocus() }
            waitUntil {
                var visible = false
                scenario.onActivity { visible = ViewCompat.getRootWindowInsets(it.window.decorView)
                    ?.isVisible(WindowInsetsCompat.Type.ime()) == true }
                visible
            }
            scenario.onActivity {
                navigate!! {
                    assertFalse("Input focus must be cleared before navigation", focused)
                    calls++
                }
            }
            waitUntil {
                var hidden = false
                scenario.onActivity { hidden = ViewCompat.getRootWindowInsets(it.window.decorView)
                    ?.isVisible(WindowInsetsCompat.Type.ime()) == false }
                hidden
            }
            scenario.onActivity {
                assertFalse(focused)
                assertEquals("未发送的草稿", draft.value)
                // Navigation with the keyboard already closed must also execute immediately.
                navigate!! { calls++ }
                assertEquals(2, calls)
            }
        }
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 10_000
        while (!condition()) {
            check(SystemClock.uptimeMillis() < deadline) { "Timed out waiting for focus/IME" }
            SystemClock.sleep(50)
        }
    }
}
