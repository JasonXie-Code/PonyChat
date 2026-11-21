package top.ponychat.webview.ui.creation

import android.graphics.Bitmap
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

class CreationContinueInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private fun walk(node: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { walk(node.getChild(it)) }
    private fun find(description: String): AccessibilityNodeInfo? {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { walk(it.root) }.firstOrNull {
            it.isVisibleToUser && it.contentDescription?.toString() == description
        }
    }
    private fun until(check: () -> Boolean) {
        repeat(80) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for continuation")
    }
    private fun click(description: String) {
        until { find(description) != null }
        var node = requireNotNull(find(description))
        while (!node.isClickable && node.parent != null) node = node.parent
        assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        instrument.waitForIdleSync()
    }
    private fun capture(name: String) {
        SystemClock.sleep(600)
        val bitmap = instrument.uiAutomation.takeScreenshot()
        File(instrument.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    @Test fun continueAppendsReplyKeepsDraftAndRegenerateReplacesOnlyLastStep() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        val character = "continue-preview"
        var saved = CreationSession(character, "雨后的小小冒险", messages = listOf(
            CreationMessage("user", "user", "采妮，雨停了，我们去看看窗外吧。", 0, "first"),
            CreationMessage("first-reply", "assistant", "采妮轻轻推开窗，雨后的空气带着青草的香气。\n\n“你看，云缝里已经透出阳光了。”她回过头，眼睛亮晶晶的，像是忽然想到了什么。\n\n“等一等……花园里的那条小路，昨天还没有这些脚印呢。”", 0, "first")))
        var pending = CompletableDeferred<CreationSession>()
        val calls = mutableListOf<Pair<Boolean, Boolean>>()
        val ids = mutableListOf<String>()
        val repository = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(saved.id, saved.title))
            override suspend fun load(id: String) = saved
            override suspend fun stream(session: CreationSession, text: String, requestId: String,
                regenerate: Boolean, onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit,
                editMessageId: String?, continueStory: Boolean): CreationSession {
                calls += regenerate to continueStory
                ids += requestId
                assertEquals("", text)
                assertNull(editMessageId)
                onSession(session)
                onDelta("她沿着脚印走到花园门口，却发现一封被雨水打湿的信。")
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
                        CreationChatContent("采妮", state, {}, vm::input, { vm.send() }, { vm.send(true) }, {}, {},
                            onContinue = { vm.continueStory() }, showTimestamp = false)
                    } }
                }
                until { !vm.state.value.loading && find("续写") != null }
                capture("creation-continue-button.png")
                instrument.runOnMainSync { vm.input("还没发出的草稿") }
                click("续写")
                until { calls.size == 1 && vm.state.value.sending }
                assertEquals(false to true, calls[0])
                assertEquals("还没发出的草稿", vm.state.value.input)
                assertEquals(saved.messages, vm.state.value.session!!.messages.dropLast(1))
                assertNull("Controls hidden during continuation", find("续写"))
                // Duplicate actions while generating must not create another request.
                instrument.runOnMainSync { vm.continueStory(); vm.send(true) }
                instrument.waitForIdleSync()
                assertEquals(1, calls.size)
                saved = saved.copy(version = 1, messages = saved.messages +
                    CreationMessage("continued", "assistant", "她沿着脚印走到花园门口，却发现一封被雨水打湿的信。\n\n信封上没有名字，只有一枚小小的星星印章。采妮伸出的手停在半空。\n\n“这个印章……我好像在哪里见过。”", 1, ids.last()))
                pending.complete(saved)
                until { !vm.state.value.sending && find("续写") != null }
                capture("creation-continued-reply.png")
                assertEquals(1, saved.messages.count { it.role == "user" })
                pending = CompletableDeferred()
                click("重新生成")
                until { calls.size == 2 && vm.state.value.sending }
                assertEquals(true to false, calls[1])
                assertEquals(saved.messages.dropLast(1), vm.state.value.session!!.messages.dropLast(1))
                assertNotEquals(ids[0], ids[1])
                saved = saved.copy(version = 2, messages = saved.messages.dropLast(1) +
                    saved.messages.last().copy(id = "regenerated", content = "另一条发展线索。", requestId = ids.last()))
                pending.complete(saved)
                until { !vm.state.value.sending }
            }
        } finally { instrument.runOnMainSync { owner.clear() } }
    }
}
