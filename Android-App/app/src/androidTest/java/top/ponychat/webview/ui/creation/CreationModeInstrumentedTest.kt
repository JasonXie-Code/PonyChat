package top.ponychat.webview.ui.creation

import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.AppNavigation
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

class CreationModeInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    init {
        instrumentation.uiAutomation.serviceInfo = instrumentation.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
    }
    private fun nodes(node: AccessibilityNodeInfo? = instrumentation.uiAutomation.rootInActiveWindow): List<AccessibilityNodeInfo> =
        if (node == null) emptyList() else listOf(node) + (0 until node.childCount).flatMap { nodes(node.getChild(it)) }
    private fun find(text: String): AccessibilityNodeInfo? {
        val current = instrumentation.uiAutomation.windows.flatMap { nodes(it.root) }.ifEmpty { nodes() }
        return current.firstOrNull { it.contentDescription?.toString() == text }
            ?: current.firstOrNull { it.text?.toString() == text }
            ?: current.firstOrNull { text != "创造模式" && it.text?.toString()?.contains(text) == true }
    }
    private fun await(text: String, seconds: Int = 30) {
        repeat(seconds * 5) {
            instrumentation.uiAutomation.clearCache()
            if (find(text) != null) return
            SystemClock.sleep(200)
        }
        screenshot("creation-failure.png")
        fail("Missing visible text: $text")
    }
    private fun click(text: String) {
        await(text)
        repeat(30) {
            instrumentation.uiAutomation.clearCache()
            var node = find(text)
            while (node != null && !node.isClickable && node.parent != null) node = node.parent
            if (node?.isClickable == true && node.isEnabled && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                instrumentation.waitForIdleSync()
                return
            }
            SystemClock.sleep(100)
        }
        fail("No actionable control: $text")
    }
    private fun awaitGone(text: String) {
        repeat(30) {
            instrumentation.uiAutomation.clearCache()
            if (nodes().none { it.text?.toString() == text }) return
            SystemClock.sleep(100)
        }
        fail("Previous page is still visible: $text")
    }
    private fun fill(index: Int, text: String) {
        var editors = nodes().filter { it.isEditable }
        repeat(15) {
            if (editors.size <= index) {
                SystemClock.sleep(100)
                instrumentation.uiAutomation.clearCache()
                editors = nodes().filter { it.isEditable }
            }
        }
        assertTrue("Editable field $index is present", editors.size > index)
        assertTrue(editors[index].performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }))
        instrumentation.waitForIdleSync()
        SystemClock.sleep(200)
    }
    private fun screenshot(name: String) {
        SystemClock.sleep(700)
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
        if (name == "creation-empty.png") {
            assertEquals("System navigation background matches input toolbar", bitmap.getPixel(8, bitmap.height - 150),
                bitmap.getPixel(8, bitmap.height - 12))
        }
        File(instrumentation.targetContext.getExternalFilesDir(null), name).outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    private fun awaitReplyBody(scenario: ActivityScenario<DialogPreviewActivity>, seconds: Int) {
        fun bodyPresent(view: android.view.View): Boolean =
            (view is android.widget.TextView && view.text.isNotBlank()) ||
                (view is android.view.ViewGroup && (0 until view.childCount).any { bodyPresent(view.getChildAt(it)) })
        repeat(seconds * 5) {
            var present = false
            scenario.onActivity { present = bodyPresent(it.window.decorView) }
            if (present) return
            SystemClock.sleep(200)
        }
        fail("Missing streamed Markdown body")
    }

    private fun drag(from: String, to: String) {
        val a = android.graphics.Rect(); val b = android.graphics.Rect()
        requireNotNull(find(from)).getBoundsInScreen(a)
        requireNotNull(find(to)).getBoundsInScreen(b)
        val start = SystemClock.uptimeMillis()
        fun inject(action: Int, x: Float, y: Float) {
            val event = android.view.MotionEvent.obtain(start, SystemClock.uptimeMillis(), action, x, y, 0)
            instrumentation.sendPointerSync(event); event.recycle()
        }
        inject(android.view.MotionEvent.ACTION_DOWN, a.centerX().toFloat(), a.centerY().toFloat())
        SystemClock.sleep(650)
        for (step in 1..12) {
            inject(android.view.MotionEvent.ACTION_MOVE, a.centerX().toFloat(),
                a.centerY() + (b.centerY() - a.centerY()) * step / 12f)
            SystemClock.sleep(40)
        }
        inject(android.view.MotionEvent.ACTION_UP, b.centerX().toFloat(), b.centerY().toFloat())
        instrumentation.waitForIdleSync()
    }

    private fun longPress(text: String) {
        await(text)
        val bounds = android.graphics.Rect()
        requireNotNull(find(text)).getBoundsInScreen(bounds)
        val started = SystemClock.uptimeMillis()
        val down = android.view.MotionEvent.obtain(started, started, android.view.MotionEvent.ACTION_DOWN,
            bounds.centerX().toFloat(), bounds.centerY().toFloat(), 0)
        instrumentation.sendPointerSync(down); down.recycle()
        SystemClock.sleep(700)
        val up = android.view.MotionEvent.obtain(started, SystemClock.uptimeMillis(), android.view.MotionEvent.ACTION_UP,
            bounds.centerX().toFloat(), bounds.centerY().toFloat(), 0)
        instrumentation.sendPointerSync(up); up.recycle()
    }

    @Test fun editTruncatesFutureAndDeleteRemovesSelectedMessage() {
        val prefs = AppPreferences(instrumentation.targetContext)
        prefs.username = "admin"
        prefs.authToken = requireNotNull(InstrumentationRegistry.getArguments().getString("previewToken"))
        prefs.debugMode = true; prefs.activeApiBase = "http://10.0.2.2:5017"
        prefs.chatMode = "creation"; prefs.isDarkTheme = true
        NetworkClient.bindPreferences(prefs)
        val first = "第一轮旧内容：仅回复甲"
        val second = "第二轮旧内容：仅回复乙"
        val edited = "修改后的消息：仅回复新内容"
        val repository = CreationRepository(prefs)
        kotlinx.coroutines.runBlocking {
            var session = repository.create("creation-preview-char")
            session = repository.send(session, first, java.util.UUID.randomUUID().toString(), false)
            session = repository.send(session, second, java.util.UUID.randomUUID().toString(), false)
            prefs.setCreationSessionId("creation-preview-char", session.id)
        }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        val toast = remember { SnackbarHostState() }
                        CompositionLocalProvider(CustomToast provides toast) { AppNavigation(prefs = prefs) }
                    }
                }
            }
            click("云杉")
            await(first)
            longPress(first)
            await("复制"); await("选择文字"); await("删除"); await("编辑")
            screenshot("creation-user-menu.png")
            click("选择文字")
            await("取消")
            screenshot("creation-user-selection.png")
            click("取消")
            longPress(first)
            click("编辑")
            await("消息内容")
            fill(0, edited)
            screenshot("creation-edit-message.png")
            click("返回")
            await(edited)
            repeat(300) {
                instrumentation.uiAutomation.clearCache()
                if (find("停止生成") != null) SystemClock.sleep(100)
            }
            awaitGone(second)
            awaitGone(first)
            await("复制 Markdown")
            screenshot("creation-edited-reply.png")
            click("删除回复")
            await("确认删除")
            click("确认删除")
            awaitGone("复制 Markdown")
            longPress(edited)
            click("删除")
            await("让想象自由展开")
            kotlinx.coroutines.runBlocking {
                assertTrue(repository.load(prefs.getCreationSessionId("creation-preview-char")).messages.isEmpty())
            }
        }
    }

    @Test fun roleMarkdownLongPressSelectsText() {
        val text = "这是一段供选择的角色正文。"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        CreationChatContent("云杉", CreationUiState(loading = false, session = CreationSession(
                            "selection", "选择验证", messages = listOf(CreationMessage("reply", "assistant", text,
                                System.currentTimeMillis(), "request")))), onBack = {}, onInput = {},
                            onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                    }
                }
            }
            await(text)
            longPress(text)
            SystemClock.sleep(300)
            scenario.onActivity { activity ->
                fun textViews(view: android.view.View): List<android.widget.TextView> =
                    (if (view is android.widget.TextView) listOf(view) else emptyList()) +
                        if (view is android.view.ViewGroup) (0 until view.childCount).flatMap { textViews(view.getChildAt(it)) } else emptyList()
                val body = textViews(activity.window.decorView).first { it.text.toString() == text }
                assertTrue("A range of role text is selected", body.selectionEnd > body.selectionStart)
            }
            screenshot("creation-role-selection.png")
        }
    }

    @Test fun creationLoadingUsesSkeleton() {
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent {
                    PonyChatTheme(darkTheme = true) {
                        CreationChatContent("云杉", CreationUiState(loading = true), onBack = {}, onInput = {},
                            onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                    }
                }
            }
            await("正在加载")
            screenshot("creation-loading-skeleton.png")
        }
    }

    @Test fun realQwenCreationFlow() {
        val token = InstrumentationRegistry.getArguments().getString("previewToken") ?: error("previewToken required")
        val prefs = AppPreferences(instrumentation.targetContext)
        prefs.username = "admin"; prefs.authToken = token
        prefs.debugMode = true; prefs.activeApiBase = "http://10.0.2.2:5017"
        prefs.chatMode = "normal"; prefs.isDarkTheme = true
        NetworkClient.bindPreferences(prefs)
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent {
                PonyChatTheme(darkTheme = true) {
                    val toast = remember { SnackbarHostState() }
                    CompositionLocalProvider(CustomToast provides toast) { AppNavigation(prefs = prefs) }
                }
            } }
            await("云杉", 45)
            await("聊天"); await("创造"); await("游戏")
            screenshot("creation-navigation.png")
            click("创造")
            click("云杉")
            await("创造模式")
            click("新建创作")
            await("设置你的创作风格")
            screenshot("creation-empty.png")
            var more = requireNotNull(find("更多功能"))
            while (!more.isClickable && more.parent != null) more = more.parent
            assertFalse("Creation plus button is disabled", more.isEnabled)
            click("表情符号")
            click("😀")
            SystemClock.sleep(300)
            instrumentation.uiAutomation.clearCache()
            assertTrue(nodes().any { it.isEditable && it.text?.contains("😀") == true })
            screenshot("creation-emoji.png")
            fill(0, "")
            click("表情符号")

            click("更多功能")
            click("创作设定")
            await("创作指令")
            awaitGone("创造模式")
            fill(1, "像旅行手记一样写作，用自然中文。允许标题、引用、列表、表格与代码块，不限制为短聊天气泡。")
            screenshot("creation-settings.png")
            click("返回")
            await("创造模式")
            click("更多功能")
            click("上下文管理")
            await("1 · 系统提示词")
            awaitGone("创造模式")
            drag("拖动系统提示词", "拖动角色设定")
            await("1 · 角色设定")
            screenshot("creation-context-order.png")
            click("添加文本块")
            await("块名称")
            fill(0, "世界观补充")
            fill(1, "故事发生在一座海边的图书馆。保留用户要求的Markdown排版。")
            screenshot("creation-context-custom.png")
            click("返回")
            await("创造模式")
            click("更多功能")
            click("上下文管理")
            await("1 · 角色设定")
            click("返回")
            await("创造模式")
            fill(0, "请用Markdown写一篇《雨夜的图书馆》，180字左右。用一级标题开头、两句开场白、一段引用；然后用一个两列三行表格列出窗边、书架、灯下的细节，最后用三个任务清单项目写下今晚的灵感。")
            click("发送")
            await("停止生成", 30)
            awaitReplyBody(scenario, 180)
            assertNotNull("Markdown appears before generation completes", find("停止生成"))
            screenshot("creation-streaming.png")
            repeat(900) {
                instrumentation.uiAutomation.clearCache()
                if (find("停止生成") != null) SystemClock.sleep(200)
            }
            assertNull("Generation completed", find("停止生成"))
            screenshot("creation-markdown.png")
            click("创作历史")
            await("创作历史")
            awaitGone("创造模式")
            screenshot("creation-history.png")
            instrumentation.uiAutomation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)
            await("新建创作")
            click("新建创作")
            await("设置你的创作风格")
            fill(0, "请创作一个至少3000字的长故事，使用Markdown标题、列表和代码块。")
            click("发送")
            awaitReplyBody(scenario, 60)
            assertNotNull(find("停止生成"))
            click("停止生成")
            awaitGone("停止生成")
            assertNull(find("已停止生成"))
            assertNull(find("本次请求未完成"))
            await("复制 Markdown")
            screenshot("creation-stopped.png")
            click("角色主页")
            await("开始聊天")
            screenshot("creation-character-profile.png")
            click("返回")
            await("创造模式")
            click("消息角色主页")
            await("开始聊天")
            click("返回")
            await("创造模式")
            click("用户主页")
            await("深色主题")
            screenshot("creation-user-settings.png")
            click("返回")
            await("创造模式")
            val editor = nodes().first { it.isEditable }
            val bounds = android.graphics.Rect()
            editor.getBoundsInScreen(bounds)
            instrumentation.uiAutomation.executeShellCommand("input tap ${bounds.centerX()} ${bounds.centerY()}").close()
            fill(0, "继续写下去，保持这个风格。")
            screenshot("creation-keyboard.png")
        }
    }
}
