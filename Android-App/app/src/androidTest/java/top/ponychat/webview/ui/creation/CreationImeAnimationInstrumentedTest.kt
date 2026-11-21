package top.ponychat.webview.ui.creation

import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.view.Choreographer
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.TextView
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

class CreationImeAnimationInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private fun views(v: View): List<View> = listOf(v) + if (v is ViewGroup)
        (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
    private fun walk(n: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> = if (n == null) emptyList()
        else listOf(n) + (0 until n.childCount).flatMap { walk(n.getChild(it)) }
    private fun nodes(): List<AccessibilityNodeInfo> {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { walk(it.root) }
    }
    private fun until(check: () -> Boolean) {
        repeat(80) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for keyboard/send state")
    }
    private fun shell(command: String) = instrument.uiAutomation.executeShellCommand(command).close()

    @Test fun sendingThenClosingKeyboardKeepsReplyMotionAndBackgroundStable() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        shell("settings put secure show_ime_with_hard_keyboard 1")
        for (closeDelay in listOf(0L, 350L, 650L)) {
            val history = (1..10).map { CreationMessage("u-$it", "user", "历史消息 $it", 0, "u-$it") }
            val state = mutableStateOf(CreationUiState(session = CreationSession("ime-send-$closeDelay", "键盘", messages = history),
                loading = false, input = "新的问题"))
            val samples = mutableListOf<Triple<Int, Int, Int>>()
            var recording = true
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                    activity.window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
                    activity.setContent { PonyChatTheme(darkTheme = true) {
                        CreationChatContent("键盘动画验证", state.value, onBack = {}, onInput = { state.value = state.value.copy(input = it) },
                            onSend = { state.value = state.value.copy(input = "", sending = true, alignReplyRequestId = "new",
                                session = state.value.session!!.copy(messages = history + listOf(
                                    CreationMessage("new-user", "user", "新的问题", 0, "new"),
                                    CreationMessage("stream-new", "assistant", "首字验证，正在生成回复。", 0, "new")))) },
                            onRegenerate = {}, onNew = {}, onLoad = {})
                    } }
                }
                until { nodes().any { it.isEditable } }
                val input = nodes().first { it.isEditable }
                val inputBounds = Rect(); input.getBoundsInScreen(inputBounds)
                shell("input tap ${inputBounds.centerX()} ${inputBounds.centerY()}")
                SystemClock.sleep(650)
                scenario.onActivity { activity ->
                    assertTrue(ViewCompat.getRootWindowInsets(activity.window.decorView)!!.isVisible(WindowInsetsCompat.Type.ime()))
                    val bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888)
                    var copying = false
                    var color: Int? = null
                    val frame = object : Choreographer.FrameCallback {
                        override fun doFrame(time: Long) {
                            if (!recording) { if (!copying && !bitmap.isRecycled) bitmap.recycle(); return }
                            if (!copying) {
                                copying = true
                                android.view.PixelCopy.request(activity.window, Rect(8, 400, 9, 401), bitmap, { result ->
                                    if (result == android.view.PixelCopy.SUCCESS) color = bitmap.getPixel(0, 0)
                                    copying = false
                                    if (!recording && !bitmap.isRecycled) bitmap.recycle()
                                }, android.os.Handler(android.os.Looper.getMainLooper()))
                            }
                            val view = views(activity.window.decorView).filterIsInstance<TextView>()
                                .firstOrNull { it.text.toString().startsWith("首字验证") && it.width > 0 }
                            if (view != null) {
                                val pos = IntArray(2); view.getLocationOnScreen(pos)
                                val ime = ViewCompat.getRootWindowInsets(activity.window.decorView)?.getInsets(WindowInsetsCompat.Type.ime())?.bottom ?: 0
                                samples += Triple(pos[1], ime, color ?: 0)
                            }
                            Choreographer.getInstance().postFrameCallback(this)
                        }
                    }
                    Choreographer.getInstance().postFrameCallback(frame)
                }
                val send = nodes().first { it.contentDescription?.toString() == "发送" }
                val sendBounds = Rect(); send.getBoundsInScreen(sendBounds)
                shell("input tap ${sendBounds.centerX()} ${sendBounds.centerY()}")
                SystemClock.sleep(closeDelay)
                fun settled(): Boolean {
                    var stable = false
                    scenario.onActivity {
                        if (samples.size >= 8 && samples.last().first < samples.first().first) {
                            val tail = samples.takeLast(8).map { it.first }
                            stable = tail.maxOrNull()!! - tail.minOrNull()!! <= 2
                        }
                    }
                    return stable
                }
                if (closeDelay == 650L) until(::settled)
                val beforeClose = samples.lastOrNull()?.first
                shell("input keyevent KEYCODE_BACK")
                SystemClock.sleep(1000)
                until(::settled)
                scenario.onActivity { recording = false }
                File(instrument.targetContext.getExternalFilesDir(null), "ime-send-$closeDelay.csv")
                    .writeText("reply_top,ime_bottom,background\n" + samples.joinToString("\n") { "${it.first},${it.second},${it.third}" })
                assertTrue("Must sample animation frames", samples.size >= 10)
                val down = samples.zipWithNext().maxOf { (a, b) -> b.first - a.first }
                assertTrue("Reply must move only toward its header, never rebound: delay=$closeDelay down=$down", down <= 3)
                assertEquals("Background must remain the same during IME hiding", 1, samples.map { it.third }.filter { it != 0 }.distinct().size)
                val settled = samples.takeLast(8).map { it.first }
                assertTrue(settled.maxOrNull()!! - settled.minOrNull()!! <= 2)
                if (closeDelay == 650L) assertEquals("An already aligned reply must stay in place", beforeClose, samples.last().first)
                if (closeDelay == 650L) {
                    val screenshot = instrument.uiAutomation.takeScreenshot()
                    File(instrument.targetContext.getExternalFilesDir(null), "ime-send-fixed.png").outputStream()
                        .use { screenshot.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    screenshot.recycle()
                }
            }
        }
    }
}
