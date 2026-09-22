package top.ponychat.webview.ui.chat

import android.graphics.Bitmap
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.compose.runtime.*
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.net.ServerSocket
import java.util.UUID
import kotlin.concurrent.thread
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme

/** Real Compose layout and controls, with a loopback-only settings fixture. */
@RunWith(AndroidJUnit4::class)
class RelationshipControlsInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: ActivityScenario<DialogPreviewActivity>
    private lateinit var host: DialogPreviewActivity
    private lateinit var prefs: AppPreferences
    private lateinit var server: ServerSocket
    @Volatile private var manual: String? = null
    @Volatile private var rejectSave = false

    @Before fun setup() {
        server = ServerSocket(0)
        prefs = AppPreferences(instrumentation.context).apply {
            username = "relationship-ui-fixture"
            debugMode = true
            activeApiBase = "http://127.0.0.1:${server.localPort}/"
        }
        thread(isDaemon = true) {
            while (!server.isClosed) {
                try {
                    server.accept().use { socket ->
                        val input = socket.getInputStream().buffered()
                        fun line(): String {
                            val bytes = ArrayList<Byte>()
                            while (true) {
                                val b = input.read()
                                if (b < 0 || b == 10) break
                                if (b != 13) bytes.add(b.toByte())
                            }
                            return bytes.toByteArray().toString(Charsets.UTF_8)
                        }
                        val request = line()
                        var length = 0
                        while (true) {
                            val header = line()
                            if (header.isBlank()) break
                            if (header.startsWith("Content-Length:", true)) length = header.substringAfter(':').trim().toInt()
                        }
                        val bytes = ByteArray(length)
                        var count = 0
                        while (count < length) {
                            val read = input.read(bytes, count, length - count)
                            if (read < 0) break
                            count += read
                        }
                        val save = request.startsWith("POST") && request.contains("relationship")
                        if (save && !rejectSave) {
                            val body = JSONObject(bytes.toString(Charsets.UTF_8))
                            manual = if (body.getString("relationship_mode") == "manual") body.getString("relationship_stage") else null
                        }
                        val json = if (request.contains("settings"))
                            """{"success":true,"settings":{"personal_preferences":{"pony":{"normal":"我们已经是稳定的伴侣。"}}}}"""
                        else JSONObject().put("status", "ok").put("relationship_mode", if (manual == null) "auto" else "manual")
                            .put("relationship_stage", manual ?: "familiar").put("manual_relationship_stage", manual ?: JSONObject.NULL).toString()
                        val content = json.toByteArray()
                        val code = if (save && rejectSave) 400 else 200
                        socket.getOutputStream().apply {
                            write("HTTP/1.1 $code OK\r\nContent-Type: application/json\r\nContent-Length: ${content.size}\r\nConnection: close\r\n\r\n".toByteArray())
                            write(content); flush()
                        }
                    }
                } catch (_: Exception) { if (server.isClosed) break }
            }
        }
        activity = ActivityScenario.launch(DialogPreviewActivity::class.java)
        activity.onActivity { host = it }
    }

    @After fun teardown() { onMain { it.setContent {} }; activity.close(); server.close() }

    private fun onMain(action: (DialogPreviewActivity) -> Unit) {
        instrumentation.runOnMainSync { action(host) }
    }

    private fun screen(content: @Composable () -> Unit) {
        val identity = UUID.randomUUID().toString()
        onMain { it.setContent { key(identity) { PonyChatTheme(darkTheme = true) { content() } } } }
        SystemClock.sleep(400)
    }

    private fun nodes(root: AccessibilityNodeInfo? = instrumentation.uiAutomation.rootInActiveWindow): List<AccessibilityNodeInfo> =
        if (root == null) emptyList() else listOf(root) + (0 until root.childCount).flatMap { nodes(root.getChild(it)) }

    private fun matching(text: String) = nodes().firstOrNull {
        it.text?.toString() == text || it.contentDescription?.toString() == text
    }

    private fun awaitText(text: String) {
        repeat(50) { if (matching(text) != null) return; SystemClock.sleep(100) }
        fail("Missing UI text: $text; found ${nodes().mapNotNull { it.text }}")
    }

    private fun click(text: String) {
        awaitText(text)
        var node = matching(text)
        while (node != null && !node.isClickable) node = node.parent
        assertTrue("Clickable $text", node?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true)
        SystemClock.sleep(300)
    }

    private fun screenshot(name: String) {
        SystemClock.sleep(100)
        val image = instrumentation.uiAutomation.takeScreenshot()
        val dir = File(instrumentation.targetContext.getExternalFilesDir(null), "relationship-qa").apply { mkdirs() }
        File(dir, "$name.png").outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun preferencesCoverChatWhileKeyboardOpensAndCloses() {
        onMain { WindowCompat.setDecorFitsSystemWindows(it.window, false) }
        screen {
            PersonalPreferencesHost(prefs, "pony", "碧琪", "normal", 0.dp, {}) { open ->
                Box(Modifier.fillMaxSize().background(Color.Magenta)) {
                    TextButton(onClick = open) { Text("打开测试偏好") }
                }
            }
        }
        click("打开测试偏好")
        awaitText("语言风格")
        assertNull(matching("自然成人表达，按情境决定细节，不强制露骨。"))
        screenshot("preferences-no-description")
        fun assertCovered() {
            val bitmap = instrumentation.uiAutomation.takeScreenshot()
            var leaked = 0
            for (y in 80 until bitmap.height - 100 step 4) {
                for (x in 16 until bitmap.width - 16 step 4) {
                    if ((bitmap.getPixel(x, y) and 0xffffff) == 0xff00ff) leaked++
                }
            }
            bitmap.recycle()
            assertEquals("Chat background leaked through preference overlay", 0, leaked)
        }
        val editor = nodes().first { it.isEditable }
        assertTrue(editor.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        var shown = false
        repeat(30) {
            assertCovered()
            onMain { shown = ViewCompat.getRootWindowInsets(it.window.decorView)
                ?.isVisible(WindowInsetsCompat.Type.ime()) == true }
            if (!shown) SystemClock.sleep(100)
        }
        assertTrue("Keyboard must actually be visible", shown)
        screenshot("preferences-keyboard-open")
        onMain { androidx.core.view.WindowInsetsControllerCompat(it.window, it.window.decorView)
            .hide(WindowInsetsCompat.Type.ime()) }
        repeat(10) { assertCovered(); SystemClock.sleep(50) }
        screenshot("preferences-keyboard-closed")
    }

    @Test fun longPreferenceCaretStaysAboveKeyboard() {
        onMain { WindowCompat.setDecorFitsSystemWindows(it.window, false) }
        screen {
            PersonalPreferencesHost(prefs, "pony", "碧琪", "normal", 0.dp, {}) { open ->
                TextButton(onClick = open) { Text("打开测试偏好") }
            }
        }
        click("打开测试偏好")
        awaitText("语言风格")
        awaitText("当前：好朋友 · 随互动由系统判断")
        val longText = (1..55).joinToString("\n") { "第${it}行：这是一段用于检查长文编辑位置的内容。" }
        val editor = nodes().first { it.isEditable }
        assertTrue(editor.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, android.os.Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, longText)
        }))
        awaitText(longText)
        assertTrue(nodes().first { it.isEditable }.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        SystemClock.sleep(500)
        fun select(offset: Int) {
            val node = nodes().first { it.isEditable }
            assertTrue("Set caret to $offset (text length ${node.text?.length})",
                (node.textSelectionStart == offset && node.textSelectionEnd == offset) ||
                node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, android.os.Bundle().apply {
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, offset)
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, offset)
            }))
            SystemClock.sleep(700)
        }
        fun assertVisibleCaret(name: String) {
            var keyboardHeight = 0
            onMain { keyboardHeight = ViewCompat.getRootWindowInsets(it.window.decorView)
                ?.getInsets(WindowInsetsCompat.Type.ime())?.bottom ?: 0 }
            assertTrue("Soft keyboard must be open", keyboardHeight > 0)
            var visible = false
            repeat(12) {
                val bitmap = instrumentation.uiAutomation.takeScreenshot()
                // The thin purple caret must have a visible vertical run above the IME.
                for (x in 24 until bitmap.width - 24) {
                    var run = 0
                    for (y in 100 until bitmap.height - keyboardHeight - 12) {
                        val pixel = bitmap.getPixel(x, y)
                        val red = android.graphics.Color.red(pixel)
                        val green = android.graphics.Color.green(pixel)
                        val blue = android.graphics.Color.blue(pixel)
                        run = if (blue > 180 && blue > red * 1.4 && blue > green * 1.4) run + 1 else 0
                        if (run >= 30) visible = true
                    }
                }
                bitmap.recycle()
                if (!visible) SystemClock.sleep(100)
            }
            assertTrue("Caret must remain above keyboard: $name", visible)
            screenshot(name)
        }
        select(longText.length)
        assertVisibleCaret("long-text-end")
        onMain { androidx.core.view.WindowInsetsControllerCompat(it.window, it.window.decorView)
            .hide(WindowInsetsCompat.Type.ime()) }
        SystemClock.sleep(500)
        onMain { androidx.core.view.WindowInsetsControllerCompat(it.window, it.window.decorView)
            .show(WindowInsetsCompat.Type.ime()) }
        SystemClock.sleep(700)
        assertVisibleCaret("long-text-keyboard-reopened")
        select(longText.indexOf("第28行"))
        assertVisibleCaret("long-text-middle")
    }

    @Test fun preferenceSelectionSavesRetriesAndRestoresAutomaticMode() {
        var exit: (() -> Unit)? = null
        var closed = false
        fun open() { screen {
            PersonalPreferencesPanel(prefs, "pony", "碧琪", "normal", { closed = true }, { exit = it })
        } }
        open()
        awaitText("当前：好朋友 · 随互动由系统判断")
        screenshot("preferences-auto")
        click("系统决定（默认）")
        awaitText("当前关系")
        screenshot("relationship-menu-auto")
        click("好朋友")
        screenshot("preferences-manual")
        rejectSave = true
        onMain { exit?.invoke() }
        // The error is below the tall editor; scroll it into the accessibility viewport.
        repeat(5) {
            if (matching("关系保存失败，请再次关闭以重试") == null) {
                nodes().firstOrNull { it.isScrollable }
                    ?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                SystemClock.sleep(200)
            }
        }
        awaitText("关系保存失败，请再次关闭以重试")
        assertFalse(closed)
        rejectSave = false
        onMain { exit?.invoke() }
        repeat(40) { if (!closed) SystemClock.sleep(100) }
        assertTrue(closed)
        assertEquals("familiar", manual)
        closed = false
        open()
        awaitText("由你指定，系统不会更改；选择“系统决定”可恢复自动判断。")
        click("好朋友")
        click("系统决定（默认）")
        onMain { exit?.invoke() }
        repeat(40) { if (!closed) SystemClock.sleep(100) }
        assertTrue(closed)
        assertNull(manual)
    }

    @Test fun loadingAndFailureKeepBothAvatarsVisible() {
        val snapshot = RelationshipSnapshot("pony", "conv", stageLabel = "好朋友", conversationCount = 1,
            currentMessageCount = 2, totalMessageCount = 2, memoryCount = 0,
            pageContent = RelationshipPageContent(overview = "旧关系说明", mood = "安心"))
        val state = mutableStateOf(ChatUiState(relationshipSnapshot = snapshot, hasLoadedRelationshipSnapshot = true))
        var retries = 0
        screen { ChatRelationshipPanel(Character("pony", "碧琪"), prefs, state.value, { retries++ }) }
        awaitText("旧关系说明")
        onMain { state.value = state.value.copy(isLoadingRelationshipSnapshot = true,
            relationshipSnapshot = null) }
        awaitText("加载中")
        assertNull(matching("关系内容加载中…"))
        awaitText("碧")
        awaitText("r")
        assertNull(matching("旧关系说明"))
        screenshot("relationship-loading")
        onMain { state.value = state.value.copy(isLoadingRelationshipSnapshot = false,
            relationshipSnapshot = null, relationshipSnapshotError = "关系信息加载失败，请下拉重试") }
        awaitText("加载失败")
        awaitText("关系信息加载失败，请下拉重试")
        awaitText("碧")
        awaitText("r")
        assertNull(matching("旧关系说明"))
        screenshot("relationship-failed")
        assertNull(matching("重新加载"))
        val metrics = instrumentation.targetContext.resources.displayMetrics
        val x = metrics.widthPixels / 2
        val from = metrics.heightPixels / 3
        val to = metrics.heightPixels * 2 / 3
        instrumentation.uiAutomation.executeShellCommand("input swipe $x $from $x $to 500").close()
        repeat(40) { if (retries == 0) SystemClock.sleep(100) }
        assertEquals(1, retries)
    }

    @Test fun relationshipRefreshKeepsContentAndUpdatesTextInPlace() {
        val snapshot = RelationshipSnapshot("pony", "conv", stageLabel = "好朋友", conversationCount = 1,
            currentMessageCount = 2, totalMessageCount = 2, memoryCount = 0,
            pageContent = RelationshipPageContent(overview = "旧关系说明", mood = "安心"))
        val state = mutableStateOf(ChatUiState(relationshipSnapshot = snapshot, hasLoadedRelationshipSnapshot = true))
        screen { ChatRelationshipPanel(Character("pony", "碧琪"), prefs, state.value, {}) }
        awaitText("旧关系说明")
        repeat(3) {
            onMain { state.value = state.value.copy(isLoadingRelationshipSnapshot = true) }
            SystemClock.sleep(150)
            awaitText("旧关系说明")
            assertNull(matching("加载中"))
            onMain { state.value = state.value.copy(isLoadingRelationshipSnapshot = false,
                relationshipSnapshotError = "关系信息加载失败，请下拉重试") }
            SystemClock.sleep(150)
            awaitText("旧关系说明")
            assertNull(matching("加载失败"))
        }
        onMain { state.value = state.value.copy(relationshipSnapshotError = null,
            relationshipSnapshot = snapshot.copy(pageContent = snapshot.pageContent!!.copy(overview = "新的关系说明"))) }
        awaitText("新的关系说明")
        assertNull(matching("旧关系说明"))
        assertNull(matching("加载中"))
        screenshot("relationship-silent-refresh")
    }

    @Test fun agentSwitchKeepsModelTaskToolRowsInOrder() {
        val foreground = AgentRunStatus(runId = "one", status = "running", activity = "正在调用模型",
            model = "chat-model", recentTools = listOf("read_memory", "web_search"),
            modelCalls = 3, toolCalls = 2, points = 5, elapsedMs = 18000)
        val background = AgentRunStatus(runId = "two", status = "running", activity = "正在整理记忆",
            model = "memory-model", phase = "background_memory", currentTools = listOf("read_history"))
        screen { AgentStatusContent(AgentStatusSnapshot(foreground, null, 0, listOf(foreground, background)), "fixture", "normal") }
        awaitText("最近调用：read_memory、web_search")
        screenshot("agent-recent-tools")
        fun top(label: String): Int {
            val rect = android.graphics.Rect()
            matching(label)!!.getBoundsInScreen(rect)
            return rect.top
        }
        assertTrue(top("模型") < top("任务") && top("任务") < top("工具"))
        click("切换 1/2")
        awaitText("当前 Agent")
        screenshot("agent-switch-menu")
        click("2. 普通聊天 · 后台记忆整理 · 运行中")
        awaitText("memory-model")
        awaitText("正在调用：read_history")
        screenshot("agent-switch")
    }

    @Test fun agentMenuOnlyShowsTheCurrentConversationMode() {
        val modes = listOf("normal" to "普通聊天", "galgame" to "游戏", "galgame_lock" to "锁分")
        val agents = modes.flatMap { (mode, _) ->
            listOf("foreground", "background_memory").map { phase ->
                AgentRunStatus(runId = "$mode-$phase", mode = mode, phase = phase,
                    status = "running", activity = "$mode activity", model = "$mode-$phase-model")
            }
        }
        val mode = mutableStateOf("normal")
        val snapshot = mutableStateOf(AgentStatusSnapshot(agents.first(), null, 0, agents))
        screen { AgentStatusContent(snapshot.value, "same-conversation", mode.value) }
        modes.forEach { (currentMode, label) ->
            onMain { mode.value = currentMode }
            awaitText("$currentMode-foreground-model")
            click("切换 1/2")
            awaitText("1. $label · 当前对话 · 运行中")
            awaitText("2. $label · 后台记忆整理 · 运行中")
            modes.filter { it.first != currentMode }.forEach { (_, otherLabel) ->
                assertFalse(nodes().any { it.text?.toString()?.contains("$otherLabel ·") == true })
            }
            click("2. $label · 后台记忆整理 · 运行中")
            awaitText("$currentMode-background_memory-model")
        }
        onMain {
            mode.value = "normal"
            snapshot.value = AgentStatusSnapshot(agents.last(), null, 0, listOf(agents.last()))
        }
        awaitText("暂无这个角色的 Agent 运行记录")
        assertNull(matching("切换 1/2"))
        assertNull(matching("galgame_lock-background_memory-model"))
    }

    @Test fun conversationActivityShowsCommittedPlansAndUnavailableStates() {
        val foreground = AgentRunStatus(runId = "reply", status = "running", model = "fixture-model")
        val memory = AgentRunStatus(runId = "memory", phase = "background_memory", status = "running")
        val plan = ConversationActivity(state = "pending", serverNowMs = 100_000,
            dueAtMs = 160_000, expiresAtMs = 300_000, proactiveEnabled = true, memoryEnabled = true,
            consecutiveCount = 1, consecutiveLimit = 5)
        val snapshot = mutableStateOf(AgentStatusSnapshot(foreground, null, 0,
            listOf(foreground, memory), conversationActivity = plan))
        val mode = mutableStateOf("normal")
        screen { ConversationActivityContent(snapshot.value, mode.value) }
        awaitText("已安排，稍后补一句")
        awaitText("约 1 分 0 秒后")
        awaitText("正在处理回复")
        awaitText("正在整理")
        awaitText("1 / 5 轮")
        screenshot("conversation-activity-pending")
        onMain { snapshot.value = snapshot.value.copy(elapsedSinceReceivedMs = 61_000) }
        awaitText("已到计划时间，等待执行")
        onMain { snapshot.value = snapshot.value.copy(elapsedSinceReceivedMs = 0,
            conversationActivity = plan.copy(state = "processing")) }
        awaitText("正在准备续聊")
        onMain { snapshot.value = snapshot.value.copy(elapsedSinceReceivedMs = 201_000) }
        awaitText("上次续聊已过期")
        for ((state, text) in listOf("none" to "暂未安排续聊", "sent" to "上次续聊已发出",
            "cancelled" to "上次续聊已取消", "failed" to "上次续聊未成功",
            "limit_reached" to "续聊已暂停，等你回应", "unavailable" to "续聊状态暂不可用")) {
            onMain { snapshot.value = snapshot.value.copy(elapsedSinceReceivedMs = 0,
                conversationActivity = plan.copy(state = state)) }
            awaitText(text)
            assertNull(matching("约 1 分 0 秒后"))
        }
        onMain { snapshot.value = snapshot.value.copy(conversationActivity = plan.copy(state = "disabled",
            proactiveEnabled = false, memoryEnabled = false)) }
        awaitText("自动续聊已关闭")
        awaitText("开启记忆与主动消息后，角色可安排稍后续聊。")
        onMain { snapshot.value = snapshot.value.copy(conversationActivity = plan,
            notice = "状态读取超时，正在重试", noticeIsError = true) }
        awaitText("状态读取超时，正在重试；有显示的数据为上次获取的状态")
        onMain { mode.value = "galgame_lock" }
        awaitText("当前模式不安排自动续聊")
        assertNull(matching("已安排，稍后补一句"))
        assertNull(matching("正在整理"))
        onMain { mode.value = "normal"; snapshot.value = AgentStatusSnapshot(null, null, 0) }
        awaitText("续聊状态暂不可用")
    }
}
