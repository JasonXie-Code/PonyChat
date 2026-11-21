package top.ponychat.webview.ui.creation

import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.ViewModelStore
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File
import java.io.IOException

class CreationStopInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private fun nodes(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
    private fun find(text: String): AccessibilityNodeInfo? {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { nodes(it.root) }.firstOrNull {
            it.isVisibleToUser && (it.text?.toString()?.contains(text) == true || it.contentDescription?.toString() == text)
        }
    }
    private fun until(check: () -> Boolean) {
        repeat(100) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for creation state")
    }
    private fun click(text: String) {
        until { find(text) != null }
        var node = requireNotNull(find(text))
        while (!node.isClickable && node.parent != null) node = node.parent
        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        instrument.waitForIdleSync()
    }
    private fun capture(name: String) {
        val bitmap = instrument.uiAutomation.takeScreenshot()
        File(instrument.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    @Test fun stopThenRegenerateUsesNewIdentityAndScrollsAgain() = exercise(true, true)
    @Test fun stoppingBeforeFirstTokenIsSilent() = exercise(true, false)
    @Test fun genuineInterruptionStillShowsFailureDialog() = exercise(false, true)

    private fun exercise(userStop: Boolean, output: Boolean) {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        val character = "stop-test-$userStop-$output"
        var saved = CreationSession(character, "停止验证", messages = listOf(
            CreationMessage("user", "user", "请继续写故事", 0, "old"),
            CreationMessage("reply", "assistant", "之前的回复", 0, "old")))
        val ids = mutableListOf<String>()
        var pending = CompletableDeferred<CreationSession>()
        val generatedText = if (output) (1..18).joinToString("\n\n") { "第 $it 段：主动停止后，已经生成的故事内容仍然保留。" } else ""
        val repository = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(saved.id, saved.title))
            override suspend fun load(id: String) = saved
            override suspend fun stream(session: CreationSession, text: String, requestId: String,
                regenerate: Boolean, onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit,
                editMessageId: String?, continueStory: Boolean): CreationSession {
                assertTrue(regenerate)
                ids += requestId
                onSession(session.copy(lastError = null))
                if (output) onDelta(generatedText)
                return pending.await()
            }
        }
        lateinit var vm: CreationViewModel
        val owner = ViewModelStore()
        instrument.runOnMainSync { vm = CreationViewModel(prefs, character, repository); owner.put("vm", vm) }
        try {
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                    activity.setContent { PonyChatTheme(darkTheme = true) {
                        val state by vm.state.collectAsState()
                        CreationChatContent("停止验证", state, {}, vm::input, { vm.send() }, { vm.send(true) }, {},
                            { vm.load(it) }, onStop = {
                                vm.stop()
                                pending.completeExceptionally(IOException("Canceled"))
                            })
                    } }
                }
                until { !vm.state.value.loading && find("重新生成") != null }
                click("重新生成")
                until { ids.size == 1 && vm.state.value.sending }
                saved = if (output) saved.copy(messages = saved.messages.take(1) +
                    CreationMessage("stopped-reply", "assistant", generatedText, 1, ids.last(), true), lastError = "生成中断")
                    else saved.copy(lastError = "生成中断")
                if (userStop) click("停止生成")
                else pending.completeExceptionally(IOException("连接中断，已生成的内容已保留"))
                until { !vm.state.value.sending }
                instrument.waitForIdleSync()
                if (!userStop) {
                    until { find("本次请求未完成") != null }
                    capture("creation-genuine-interruption.png")
                    return
                }
                assertNull(vm.state.value.error)
                assertFalse(vm.state.value.streamVibrating)
                assertEquals(saved.messages, vm.state.value.session!!.messages)
                assertNull(find("本次请求未完成"))
                assertNull(find("已停止生成"))
                if (!output) {
                    instrument.runOnMainSync { vm.load(saved.id) }
                    until { !vm.state.value.loading && vm.state.value.session?.lastError == "生成中断" }
                    SystemClock.sleep(500)
                    assertNull("Refresh must not reopen stopped request failure", find("本次请求未完成"))
                }
                capture("creation-stopped-$output.png")
                if (output) {
                    // Reach the action below the long partial reply, then verify regeneration repositions its head.
                    val metrics = instrument.targetContext.resources.displayMetrics
                    repeat(12) {
                        if (find("重新生成") == null) {
                            instrument.uiAutomation.executeShellCommand("input swipe ${metrics.widthPixels / 2} ${metrics.heightPixels * 3 / 4} ${metrics.widthPixels / 2} ${metrics.heightPixels / 3} 250").close()
                            SystemClock.sleep(300)
                        }
                    }
                    pending = CompletableDeferred()
                    click("重新生成")
                    until { ids.size == 2 && find("消息角色主页") != null }
                    assertNotEquals("Stopped regeneration must not reuse the preceding request", ids[0], ids[1])
                    SystemClock.sleep(1000)
                    val header = Rect(); requireNotNull(find("消息角色主页")).getBoundsInScreen(header)
                    val topBar = Rect(); requireNotNull(find("创造模式")).getBoundsInScreen(topBar)
                    assertTrue("Reply head is aligned below the toolbar: $header / $topBar",
                        header.top > topBar.bottom && header.top - topBar.bottom < 100)
                    capture("creation-regenerated-after-stop.png")
                    // A failure on the new request must still be visible after a previous deliberate stop.
                    saved = saved.copy(messages = saved.messages.dropLast(1) + saved.messages.last().copy(requestId = ids.last()))
                    pending.completeExceptionally(IOException("新请求网络中断"))
                    until { !vm.state.value.sending && find("本次请求未完成") != null }
                }
            }
        } finally { instrument.runOnMainSync { owner.clear() } }
    }
}
