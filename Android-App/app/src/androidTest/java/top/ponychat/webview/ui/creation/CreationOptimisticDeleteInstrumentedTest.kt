package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.height
import androidx.compose.ui.unit.dp
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
import java.io.IOException

class CreationOptimisticDeleteInstrumentedTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private fun walk(n: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> = if (n == null) emptyList()
        else listOf(n) + (0 until n.childCount).flatMap { walk(n.getChild(it)) }
    private fun find(text: String): AccessibilityNodeInfo? {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { walk(it.root) }.firstOrNull {
            it.text?.toString() == text || it.contentDescription?.toString() == text
        }
    }
    private fun until(check: () -> Boolean) {
        repeat(40) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for UI state")
    }
    private fun click(text: String) {
        until { find(text) != null }
        var n = requireNotNull(find(text))
        while (!n.isClickable && n.parent != null) n = n.parent
        assertTrue(n.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        instrument.waitForIdleSync()
    }
    private fun capture(name: String) {
        SystemClock.sleep(500)
        val bitmap = instrument.uiAutomation.takeScreenshot()
        File(instrument.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    private fun exercise(failure: Boolean, userMessage: Boolean = false) {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        val seed = CreationSession("optimistic", "删除验证", version = 3, messages = listOf(
            CreationMessage("user", "user", "待删除的用户消息", System.currentTimeMillis(), "first"),
            CreationMessage("reply", "assistant", "这是一条用于验证删除的角色回复。", System.currentTimeMillis(), "first")))
        val pending = CompletableDeferred<CreationSession>()
        var calls = 0
        var streamCalls = 0
        val generated = CompletableDeferred<CreationSession>()
        val repository = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(seed.id, seed.title))
            override suspend fun load(id: String) = seed
            override suspend fun stream(session: CreationSession, text: String, requestId: String,
                regenerate: Boolean, onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit,
                editMessageId: String?, continueStory: Boolean): CreationSession {
                streamCalls++
                assertTrue(regenerate)
                assertEquals("", text)
                assertNull(editMessageId)
                assertEquals(listOf("user"), session.messages.map { it.id })
                return generated.await()
            }
            override suspend fun deleteMessage(session: CreationSession, messageId: String): CreationSession {
                assertEquals(3, session.version)
                calls++
                return pending.await()
            }
        }
        lateinit var vm: CreationViewModel
        val owner = ViewModelStore()
        instrument.runOnMainSync { vm = CreationViewModel(prefs, "optimistic-test", repository); owner.put("vm", vm) }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        val state by vm.state.collectAsState()
                        CreationChatContent("云杉", state, onBack = {}, onInput = vm::input, onSend = { vm.send() },
                            onRegenerate = {}, onNew = {}, onLoad = {}, onDeleteMessage = { vm.deleteMessage(it) })
                    }
                }
            }
            until { !vm.state.value.loading && find("删除回复") != null }
            instrument.runOnMainSync { vm.send() }
            assertEquals("Answered session cannot send blank input", 0, streamCalls)
            if (userMessage) {
                val n = requireNotNull(find("待删除的用户消息"))
                val bounds = android.graphics.Rect(); n.getBoundsInScreen(bounds)
                instrument.uiAutomation.executeShellCommand(
                    "input swipe ${bounds.centerX()} ${bounds.centerY()} ${bounds.centerX()} ${bounds.centerY()} 800").close()
                click("删除")
                assertNull(find("确认删除"))
            } else {
                click("删除回复")
                until { find("确认删除") != null }
                assertEquals(0, calls)
                assertEquals(seed.messages, vm.state.value.session?.messages)
                capture("creation-delete-confirm.png")
                click("取消")
                assertEquals(0, calls)
                click("删除回复")
                click("确认删除")
            }
            until { vm.state.value.deleting }
            val target = if (userMessage) "user" else "reply"
            assertFalse(vm.state.value.session!!.messages.any { it.id == target })
            assertFalse(pending.isCompleted)
            instrument.runOnMainSync { vm.send() }
            assertEquals("Deletion must finish before regenerating", 0, streamCalls)
            instrument.runOnMainSync {
                vm.input("删除等待期间写的草稿")
                vm.deleteMessage(seed.messages.first { it.id != target }.id)
            }
            assertEquals("Concurrent deletes are serialized", 1, calls)
            capture("creation-delete-pending.png")
            if (failure) pending.completeExceptionally(IOException("network unavailable"))
            else pending.complete(seed.copy(version = 4, messages = seed.messages.filterNot { it.id == target }))
            until { !vm.state.value.deleting }
            assertEquals("删除等待期间写的草稿", vm.state.value.input)
            if (failure) {
                assertEquals(seed.messages, vm.state.value.session!!.messages)
                assertNotNull(vm.state.value.error)
                capture("creation-delete-restored.png")
            } else {
                assertEquals(4, vm.state.value.session!!.version)
                assertFalse(vm.state.value.session!!.messages.any { it.id == target })
                if (!userMessage) {
                    instrument.runOnMainSync { vm.input("") }
                    until { find("发送") != null }
                    capture("creation-delete-send-ready.png")
                    click("发送")
                    until { streamCalls == 1 && vm.state.value.sending }
                    assertEquals(listOf("user"), vm.state.value.session!!.messages.filter { it.role == "user" }.map { it.id })
                    instrument.runOnMainSync { vm.send() }
                    assertEquals("In-flight regeneration cannot be duplicated", 1, streamCalls)
                    generated.complete(seed.copy(version = 5))
                    until { !vm.state.value.sending }
                }
            }
        }
        instrument.runOnMainSync { owner.clear() }
    }

    private fun verifyViewportAvoidance(shortContent: Boolean) {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val height = androidx.compose.runtime.mutableStateOf(700)
        val seed = CreationSession("keyboard", "键盘避让", messages = listOf(
            CreationMessage("reply", "assistant", if (shortContent) "下方有空白时消息保持原位" else (1..35).joinToString("\n\n") { "第 $it 行消息正文" }, 0, "request")))
        fun actionBottom(): Int {
            val rect = android.graphics.Rect()
            requireNotNull(find("复制 Markdown")).getBoundsInScreen(rect)
            return rect.bottom
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.height(height.value.dp)) {
                            CreationChatContent("键盘验证", CreationUiState(session = seed, loading = false),
                                onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                        }
                    }
                }
            }
            until { find("复制 Markdown") != null }
            instrument.waitForIdleSync()
            SystemClock.sleep(250)
            val before = actionBottom()
            scenario.onActivity { height.value = 450 }
            val delta = if (shortContent) 0f else 250 * instrument.targetContext.resources.displayMetrics.density
            SystemClock.sleep(400)
            until { find("复制 Markdown") != null && kotlin.math.abs(actionBottom() - (before - delta)) < 12 }
            capture(if (shortContent) "keyboard-short-stationary.png" else "keyboard-long-lifted.png")
            scenario.onActivity { height.value = 700 }
            SystemClock.sleep(400)
            until { find("复制 Markdown") != null && kotlin.math.abs(actionBottom() - before) < 12 }
            scenario.onActivity { height.value = 450 }
            SystemClock.sleep(400)
            until { find("复制 Markdown") != null && kotlin.math.abs(actionBottom() - (before - delta)) < 12 }
            if (!shortContent) {
                repeat(2) { instrument.uiAutomation.executeShellCommand("input swipe 540 280 540 900 300").close() }
                until { find("回到底部") != null }
                click("回到底部")
                until { find("复制 Markdown") != null && find("回到底部") == null }
            }
        }
    }

    @Test fun shrinkingViewportLiftsMessagesAboveInput() = verifyViewportAvoidance(false)
    @Test fun shrinkingViewportKeepsShortMessagesStationary() = verifyViewportAvoidance(true)

    @Test fun interruptedReplyCardRegeneratesInsteadOfRefreshing() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val seed = CreationSession("interrupted", "中断恢复", lastError = "回复已中断，已保留生成内容", messages = listOf(
            CreationMessage("user", "user", "请继续这个故事", 0, "request"),
            CreationMessage("reply", "assistant", "未完成的回复", 0, "request", incomplete = true)))
        var retries = 0
        var reloads = 0
        val state = androidx.compose.runtime.mutableStateOf(CreationUiState(session = seed, loading = false))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        CreationChatContent("恢复验证", state.value, onBack = {}, onInput = {}, onSend = {},
                            onRegenerate = { retries++; state.value = state.value.copy(sending = true) },
                            onNew = {}, onLoad = { reloads++ })
                    }
                }
            }
            until { find("本次回复未完成") != null }
            assertNull(find("刷新会话"))
            val action = instrument.uiAutomation.windows.flatMap { walk(it.root) }
                .first { it.text?.toString() == "重新生成" }
            var button = action
            while (!button.isClickable && button.parent != null) button = button.parent
            assertTrue(button.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            until { retries == 1 && find("本次回复未完成") == null }
            assertEquals(0, reloads)
        }
    }

    @Test fun actualKeyboardOpeningAndClosingKeepsTailVisible() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        val seed = CreationSession("ime", "键盘验证", messages = listOf(
            CreationMessage("reply", "assistant", (1..30).joinToString("\n\n") { "键盘避让消息 $it" }, 0, "r")))
        val repo = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(seed.id, seed.title))
            override suspend fun load(id: String) = seed
        }
        fun bottom(): Int {
            val rect = android.graphics.Rect()
            requireNotNull(find("复制 Markdown")).getBoundsInScreen(rect)
            return rect.bottom
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.viewModelStore.put("creation-${prefs.username}-ime-char", CreationViewModel(prefs, "ime-char", repo))
                activity.setContent { PonyChatTheme(darkTheme = true) {
                    CreationChatScreen(top.ponychat.webview.data.model.Character("ime-char", "键盘验证"), prefs, {})
                } }
            }
            until { find("复制 Markdown") != null }
            SystemClock.sleep(300)
            val initial = bottom()
            val input = instrument.uiAutomation.windows.flatMap { walk(it.root) }.first { it.isEditable }
            val bounds = android.graphics.Rect(); input.getBoundsInScreen(bounds)
            instrument.uiAutomation.executeShellCommand("input tap ${bounds.centerX()} ${bounds.centerY()}").close()
            SystemClock.sleep(1000)
            capture("creation-ime-open.png")
            until { find("复制 Markdown") != null && bottom() < initial - 200 }
            instrument.uiAutomation.executeShellCommand("input keyevent 4").close()
            SystemClock.sleep(500)
            capture("creation-ime-closing-check.png")
            until { find("复制 Markdown") != null && kotlin.math.abs(bottom() - initial) < 12 }
            capture("creation-ime-closed.png")
        }
    }

    @Test fun historyDeletesOnlyAfterConfirmation() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        val seed = CreationSession("delete-session", "待删除会话")
        var calls = 0
        val repo = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(seed.id, seed.title))
            override suspend fun load(id: String) = seed
            override suspend fun deleteSession(session: CreationSession) { assertEquals(seed.id, session.id); calls++ }
        }
        lateinit var vm: CreationViewModel
        val owner = ViewModelStore()
        instrument.runOnMainSync { vm = CreationViewModel(prefs, "session-delete", repo); owner.put("vm", vm) }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent {
                PonyChatTheme(darkTheme = true) {
                    val state by vm.state.collectAsState()
                    CreationHistoryPage(state.history, state.session?.id, {}, busy = state.deleting,
                        error = state.error, onDelete = { vm.deleteSession(it) }, onSelect = {})
                }
            } }
            click("删除会话待删除会话")
            assertEquals(0, calls)
            click("取消")
            assertEquals(0, calls)
            click("删除会话待删除会话")
            click("确认删除")
            until { calls == 1 && find("还没有创作历史") != null }
            assertNull(vm.state.value.session)
        }
        instrument.runOnMainSync { owner.clear() }
    }

    @Test fun editorsSubmitChangesOnBackWithoutSaveButtons() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val page = androidx.compose.runtime.mutableStateOf(0)
        var saves = 0
        val session = CreationSession("exit", "原始标题", contextLayout = listOf(
            CreationContextBlock("system", "system", "系统提示词", "原始提示"),
            CreationContextBlock("character", "character", "角色设定"),
            CreationContextBlock("history", "history", "对话历史")))
        fun edit(value: String) {
            val node = instrument.uiAutomation.windows.flatMap { walk(it.root) }.first { it.isEditable }
            assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
                android.os.Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value) }))
            instrument.waitForIdleSync()
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent {
                PonyChatTheme(darkTheme = true) {
                    when (page.value) {
                        0 -> CreationSettings(session, {}, null) { title, _, _ -> assertEquals("修改标题", title); saves++ }
                        1 -> CreationContextEditor(session, null, {}) { blocks ->
                            assertEquals("history", blocks.first().id)
                            assertTrue(blocks.any { it.kind == "character" }); saves++
                        }
                        else -> CreationMessageEditor(CreationMessage("user", "user", "旧消息", 0, "r"), false, {}) {
                            assertEquals("新消息", it); saves++
                        }
                    }
                }
            } }
            until { find("创作设定") != null }
            assertNull(find("保存设定"))
            assertNull(find("编辑系统提示词"))
            assertNull(find("原始提示"))
            assertNull(find("角色设定"))
            click("返回")
            assertEquals("Unchanged drafts do not save", 0, saves)
            edit("修改标题")
            click("返回")
            assertEquals(1, saves)
            scenario.onActivity { page.value = 1 }
            until { find("上移对话历史") != null }
            assertNull(find("角色设定"))
            assertNull(find("保存上下文排列"))
            click("上移对话历史")
            instrument.uiAutomation.executeShellCommand("input keyevent 4").close()
            until { saves == 2 }
            scenario.onActivity { page.value = 2 }
            until { find("编辑消息") != null }
            assertNull(find("保存并重新生成"))
            edit("新消息")
            click("返回")
            assertEquals(3, saves)
        }
    }

    @Test fun creationMorePanelAndReturnToBottom() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        var contextClicks = 0
        var settingsClicks = 0
        val seed = CreationSession("more", "更多验证", messages = (1..40).map {
            CreationMessage("user-$it", "user", "历史消息 $it", 0, "$it")
        })
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        CreationChatContent("功能验证", CreationUiState(session = seed, loading = false),
                            onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {},
                            onContext = { contextClicks++ }, onSettings = { settingsClicks++ })
                    }
                }
            }
            until { find("历史消息 40") != null }
            assertNull(find("上下文管理"))
            assertNull(find("创作设定"))
            click("更多功能")
            assertNull(find("上下文管理"))
            assertEquals(0, contextClicks)
            capture("creation-more-panel.png")
            click("创作设定")
            assertEquals(1, settingsClicks)
            until { find("创作设定") == null }
            instrument.uiAutomation.executeShellCommand("input swipe 540 500 540 1500 500").close()
            until { find("回到底部") != null }
            capture("creation-return-to-bottom.png")
            click("回到底部")
            until { find("历史消息 40") != null && find("回到底部") == null }
        }
    }

    @Test fun navigationObservesAsyncSessionLoading() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
        val prefs = AppPreferences(instrument.targetContext)
        CreationLocalCache(prefs).saveHistory("async-char", emptyList())
        prefs.setCreationSessionId("async-char", "")
        val pending = CompletableDeferred<CreationSession>()
        val repository = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory("async", "异步加载"))
            override suspend fun load(id: String) = pending.await()
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            lateinit var vm: CreationViewModel
            scenario.onActivity { activity ->
                vm = CreationViewModel(prefs, "async-char", repository)
                activity.viewModelStore.put("creation-${prefs.username}-async-char", vm)
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        CreationChatScreen(top.ponychat.webview.data.model.Character("async-char", "加载验证"), prefs, {})
                    }
                }
            }
            until { find("创造模式") != null }
            assertTrue(vm.state.value.loading)
            pending.complete(CreationSession("async", "异步加载", messages = listOf(
                CreationMessage("loaded", "assistant", "会话加载完成，骨架已退出。", 0, "request"))))
            until { !vm.state.value.loading }
            capture("creation-async-loaded.png")
            until { find("复制 Markdown") != null }
            assertNotNull(find("会话加载完成，骨架已退出。"))
        }
    }

    @Test fun loadingTimeoutExitsSkeletonAndCanRetry() {
        val prefs = AppPreferences(instrument.targetContext)
        CreationLocalCache(prefs).saveHistory("timeout-test", emptyList())
        prefs.setCreationSessionId("timeout-test", "")
        var stalled = true
        val repository = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String): List<CreationHistory> {
                if (stalled) CompletableDeferred<Unit>().await()
                return listOf(CreationHistory("recovered", "恢复的会话"))
            }
            override suspend fun load(id: String) = CreationSession(id, "恢复的会话")
        }
        lateinit var vm: CreationViewModel
        val owner = ViewModelStore()
        instrument.runOnMainSync {
            vm = CreationViewModel(prefs, "timeout-test", repository, loadTimeoutMillis = 150)
            owner.put("vm", vm)
        }
        until { !vm.state.value.loading }
        assertTrue(vm.state.value.error.orEmpty().contains("加载超时"))
        instrument.runOnMainSync { stalled = false; vm.load() }
        until { vm.state.value.session?.id == "recovered" && !vm.state.value.loading }
        assertNull(vm.state.value.error)
        instrument.runOnMainSync { owner.clear() }
    }

    @Test fun historyStartsAtTailWithMatchingMarkdownSize() {
        val seed = CreationSession("layout", "排版验证", messages = (1..30).map {
            CreationMessage("user-$it", "user", "历史消息 $it", 0, "$it")
        } + listOf(CreationMessage("last-user", "user", "用户消息与角色正文使用相同字号", 0, "last"),
            CreationMessage("last-reply", "assistant", "角色正文与用户消息一样大。\n\n**加粗文字**与普通正文保持相同字号。", 0, "last")))
        val expected = java.util.concurrent.atomic.AtomicReference<Float>()
        val firstDraw = java.util.concurrent.atomic.AtomicReference<Boolean>()
        fun views(view: android.view.View): List<android.view.View> = listOf(view) +
            if (view is android.view.ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                activity.window.decorView.viewTreeObserver.addOnDrawListener {
                    val markdown = views(activity.window.decorView).filterIsInstance<android.widget.TextView>()
                        .firstOrNull { it.text.startsWith("角色正文") }
                    if (markdown != null && firstDraw.get() == null) {
                        val bounds = android.graphics.Rect()
                        firstDraw.set(markdown.getGlobalVisibleRect(bounds) && bounds.height() > 0)
                        assertEquals(expected.get(), markdown.textSize, .01f)
                    }
                }
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        val density = androidx.compose.ui.platform.LocalDensity.current
                        expected.set(with(density) { androidx.compose.material3.MaterialTheme.typography.bodyLarge.fontSize.toPx() })
                        CreationChatContent("云杉", CreationUiState(session = seed, loading = false),
                            onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                    }
                }
            }
            until { firstDraw.get() != null }
            assertTrue("Last reply must be visible on its first draw", firstDraw.get())
            capture("creation-markdown-matching-size.png")
        }
    }

    @Test fun confirmThenOptimisticSuccess() = exercise(false)
    @Test fun failedDeleteRestoresMessageAndDraft() = exercise(true)
    @Test fun userMenuDeletesWithoutConfirmation() = exercise(false, userMessage = true)
}
