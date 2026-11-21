package top.ponychat.webview.ui.common

import android.os.SystemClock
import android.view.MotionEvent
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

class InputFocusInstrumentedTest {
    @Test fun pageBackgroundClearsFocusAndControlsStillWork() = verify(false)
    @Test fun dialogBackgroundClearsFocusAndControlsStillWork() = verify(true)

    private fun verify(dialog: Boolean) {
        val instrument = InstrumentationRegistry.getInstrumentation()
        val bounds = mutableMapOf<String, Rect>()
        val focused = mutableMapOf<String, Boolean>()
        var clicked = false
        @Composable fun node(name: String): Modifier {
            val view = LocalView.current
            return Modifier.onGloballyPositioned {
                val screen = IntArray(2)
                val window = IntArray(2)
                view.getLocationOnScreen(screen)
                view.getLocationInWindow(window)
                bounds[name] = it.boundsInWindow().translate(Offset(
                    (screen[0] - window[0]).toFloat(), (screen[1] - window[1]).toFloat()))
            }
        }
        @Composable fun form() {
            Column(Modifier.fillMaxWidth().padding(16.dp)) {
                for (name in listOf("first", "second")) {
                    OutlinedTextField("", {}, modifier = node(name).onFocusChanged { focused[name] = it.isFocused })
                }
                Button(onClick = { clicked = true }, modifier = node("button")) { Text("Action") }
                Spacer(node("blank").fillMaxWidth().height(64.dp))
            }
        }
        fun tap(name: String) {
            instrument.waitForIdleSync()
            lateinit var rect: Rect
            instrument.runOnMainSync { rect = bounds.getValue(name) }
            val now = SystemClock.uptimeMillis()
            for (action in listOf(MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP)) {
                val event = MotionEvent.obtain(now, SystemClock.uptimeMillis(), action,
                    rect.center.x, rect.center.y, 0)
                instrument.uiAutomation.injectInputEvent(event, true)
                event.recycle()
            }
            instrument.waitForIdleSync()
            SystemClock.sleep(150)
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme {
                        if (dialog) PonyAlertDialog("Editor", {}, content = { form() }) else form()
                    }
                }
            }
            SystemClock.sleep(500)
            tap("first")
            instrument.runOnMainSync { assertTrue(focused["first"] == true) }
            tap("second")
            instrument.runOnMainSync { assertTrue(focused["second"] == true) }
            tap("blank")
            instrument.runOnMainSync { assertFalse(focused.values.any { it }) }
            tap("first")
            tap("button")
            instrument.runOnMainSync { assertTrue(clicked) }
        }
    }
}
