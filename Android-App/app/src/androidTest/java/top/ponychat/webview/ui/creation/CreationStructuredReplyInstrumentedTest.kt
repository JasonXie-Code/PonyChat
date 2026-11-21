package top.ponychat.webview.ui.creation

import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.HorizontalScrollView
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.collectAsState
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.debug.DialogPreviewActivity
import top.ponychat.webview.ui.theme.PonyChatTheme
import java.io.File

class CreationStructuredReplyInstrumentedTest {
    @Test fun generationVibrationWaitsForVisibleTextAndStopsImmediately() {
        setup()
        val prefs = top.ponychat.webview.data.prefs.AppPreferences(instrument.targetContext)
        val seed = CreationSession("haptics-start", "震动验证", messages = listOf(
            CreationMessage("u", "user", "测试", 0, "u")))
        val accepted = kotlinx.coroutines.CompletableDeferred<Unit>()
        val firstText = kotlinx.coroutines.CompletableDeferred<Unit>()
        val result = kotlinx.coroutines.CompletableDeferred<CreationSession>()
        val repo = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(seed.id, seed.title))
            override suspend fun load(id: String) = seed
            override suspend fun stream(session: CreationSession, text: String, requestId: String, regenerate: Boolean,
                onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit, editMessageId: String?, continueStory: Boolean): CreationSession {
                accepted.await()
                onSession(seed.copy(busy = true))
                onDelta(" ")
                firstText.await()
                onDelta("正文出现")
                return result.await()
            }
        }
        lateinit var vm: CreationViewModel
        val owner = androidx.lifecycle.ViewModelStore()
        instrument.runOnMainSync { vm = CreationViewModel(prefs, "haptics-start", repo); owner.put("vm", vm) }
        try {
            until { vm.state.value.session != null && !vm.state.value.loading }
            instrument.runOnMainSync { vm.input("测试"); vm.send() }
            until { vm.state.value.sending }
            assertFalse("Skeleton/waiting must be silent", vm.state.value.streamVibrating)
            accepted.complete(Unit)
            until { vm.state.value.session!!.messages.last().content == " " }
            assertFalse("Whitespace alone must be silent", vm.state.value.streamVibrating)
            SystemClock.sleep(70)
            firstText.complete(Unit)
            until { vm.state.value.session!!.messages.last().content.contains("正文出现") }
            assertTrue(vm.state.value.streamVibrating)
            instrument.runOnMainSync { vm.stop() }
            assertFalse("Stop must silence immediately", vm.state.value.streamVibrating)
            result.complete(seed)
            until { !vm.state.value.sending }
            assertFalse("No completion vibration", vm.state.value.streamVibrating)
        } finally { instrument.runOnMainSync { owner.clear() } }
    }

    @Test fun streamingLongMathKeepsDrawableAndReadingAnchorStable() {
        setup()
        val tex = """\frac{1}{1+\frac{1}{x}}+\sqrt{\frac{x^2+y^2}{1+z^2}}"""
        val source = mutableStateOf("推导过程：\n\n$$\n\\f")
        val streaming = mutableStateOf(true)
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("流式公式验证", CreationUiState(loading = false, sending = streaming.value,
                    alignReplyRequestId = "r", session = CreationSession("stable-math", "公式", messages = listOf(
                        CreationMessage("stream-r", "assistant", source.value, 0, "r")))),
                    onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { nodes().any { it.text?.toString()?.contains("公式生成中…") == true } }
            SystemClock.sleep(500)
            val anchor = bounds("消息角色主页").top
            var pendingHeight = 0
            for (length in 2..tex.length step 3) {
                scenario.onActivity { source.value = "推导过程：\n\n$$\n" + tex.take(length) }
                instrument.waitForIdleSync()
                scenario.onActivity { activity ->
                    val view = views(activity.window.decorView).filterIsInstance<android.widget.TextView>()
                        .single { it.text.contains("公式生成中…") }
                    if (pendingHeight == 0) pendingHeight = view.height
                    assertEquals("Partial TeX must not repeatedly resize", pendingHeight, view.height)
                }
                assertEquals(anchor, bounds("消息角色主页").top)
            }
            capture("creation-math-pending-stable.png")
            scenario.onActivity { source.value = "推导过程：\n\n$$\n$tex\n$$\n\n结论：" }
            fun spans(): List<io.noties.markwon.image.AsyncDrawableSpan> {
                var found = emptyList<io.noties.markwon.image.AsyncDrawableSpan>()
                scenario.onActivity { activity ->
                    found = views(activity.window.decorView).filterIsInstance<android.widget.TextView>().flatMap { view ->
                        val text = view.text as? android.text.Spanned
                        text?.getSpans(0, text.length, io.noties.markwon.image.AsyncDrawableSpan::class.java)?.toList().orEmpty()
                    }
                }
                return found
            }
            until { spans().singleOrNull()?.drawable?.hasResult() == true }
            val original = spans().single()
            val rendered = original.drawable.result
            repeat(25) {
                scenario.onActivity { source.value += " 后续文字" }
                instrument.waitForIdleSync()
                val current = spans().single()
                assertSame("Appending prose must reuse the loaded span", original, current)
                assertSame(rendered, current.drawable.result)
                assertTrue(current.drawable.hasResult())
                assertEquals(anchor, bounds("消息角色主页").top)
            }
            scenario.onActivity { streaming.value = false }
            instrument.waitForIdleSync()
            assertSame(original, spans().single())
            capture("creation-math-stream-stable.png")
        }
    }

    @Test fun complexMathRendersWithoutErrorsOrClipping() {
        setup()
        fun inline(tex: String) = "$" + tex + "$"
        fun block(tex: String) = "\n\n$$\n" + tex + "\n$$\n\n"
        val body = "复杂公式验证\n\n嵌套分数：" + inline("""\frac{1}{1+\frac{1}{x}}""") +
            "\n\n根号：" + inline("""\sqrt{\frac{x^2+y^2}{1+z^2}}""") +
            "\n\n多层上下标：" + inline("""x_{i_j}^{n+1}+a^{b^c}""") +
            "\n\n偏导数：" + inline("""\frac{\partial^2 f}{\partial x\partial y}""") +
            "\n\n求和与极限" + block("""\lim_{n\to\infty}\sum_{k=1}^{n}\frac{1}{k^2}=\frac{\pi^2}{6}""") +
            "积分" + block("""\int_{-\infty}^{\infty} e^{-x^2}\,dx=\sqrt{\pi}""") +
            "矩阵" + block("""A=\begin{pmatrix}1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9\end{pmatrix}""")
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                androidx.compose.material3.Surface(modifier = Modifier.fillMaxSize()) {
                    androidx.compose.foundation.layout.Column(Modifier
                        .verticalScroll(androidx.compose.foundation.rememberScrollState()).padding(16.dp)) {
                        CreationMarkdown(body)
                    }
                }
            } } }
            until {
                var loaded = 0
                scenario.onActivity { activity ->
                    views(activity.window.decorView).filterIsInstance<android.widget.TextView>().forEach { view ->
                        val text = view.text as? android.text.Spanned
                        text?.getSpans(0, text.length, io.noties.markwon.image.AsyncDrawableSpan::class.java)?.forEach { span ->
                            if (span.drawable.hasResult()) {
                                assertTrue("LaTeX must load a real math drawable", span.drawable.result is ru.noties.jlatexmath.JLatexMathDrawable)
                                assertTrue("Formula must fit the text width", span.drawable.bounds.width() <= view.width)
                                assertTrue(span.drawable.bounds.height() > 0)
                                loaded++
                            }
                        }
                    }
                }
                loaded == 7
            }
            SystemClock.sleep(500)
            capture("creation-complex-math-top.png")
            shell("input swipe 540 1800 540 500 600")
            SystemClock.sleep(500)
            capture("creation-complex-math-bottom.png")
        }
    }

    @Test fun inlineMathSharesTextBaselineWithoutClippingFractions() {
        setup()
        val scale = androidx.compose.runtime.mutableStateOf(1f)
        val body = "根据流体静力学原理，压强 $" + "P" + "$ 等于密度 $" + "\\rho" +
            "$ 乘以重力加速度 $" + "g" + "$，再乘以高度 $" + "h" + "$，即 $" +
            "P = \\rho gh" + "$。\n\n高度 $" + "h = \\frac{P}{\\rho g}" +
            "$，上下标 $" + "x_i^2" + "$ 都应该完整显示。"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true, fontScale = scale.value) {
                CreationChatContent("公式对齐验证", CreationUiState(loading = false, session = CreationSession(
                    "baseline", "公式", messages = listOf(CreationMessage("r", "assistant", body, 0, "r")))),
                    onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            for (fontScale in listOf(1f, 1.2f)) {
                scenario.onActivity { scale.value = fontScale }
                until {
                    var loaded = 0
                    scenario.onActivity { activity ->
                        views(activity.window.decorView).filterIsInstance<android.widget.TextView>().forEach { view ->
                            val text = view.text as? android.text.Spanned
                            text?.getSpans(0, text.length, CreationInlineMathSpan::class.java)?.forEach { span ->
                                if (span.drawable.hasResult()) {
                                    loaded++
                                    val fm = android.graphics.Paint.FontMetricsInt()
                                    span.getSize(view.paint, text, text.getSpanStart(span), text.getSpanEnd(span), fm)
                                    assertTrue(fm.ascent <= -span.baselineOffset())
                                    assertTrue(fm.descent >= span.drawable.bounds.height() - span.baselineOffset())
                                }
                            }
                        }
                    }
                    loaded == 7
                }
                SystemClock.sleep(400)
                capture("creation-math-baseline-${(fontScale * 100).toInt()}.png")
            }
        }
    }

    @Test fun singleDollarMathRendersDuringStreamingAndAfterCompletion() {
        setup()
        val source = androidx.compose.runtime.mutableStateOf("压强公式 $" + "P = \\rho gh")
        val streaming = androidx.compose.runtime.mutableStateOf(true)
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                androidx.compose.material3.Surface {
                    CreationMarkdown(source.value, streaming = streaming.value)
                }
            } } }
            fun mathSpans(): Int {
                var count = 0
                scenario.onActivity { activity ->
                    count = views(activity.window.decorView).filterIsInstance<android.widget.TextView>().sumOf { view ->
                        val text = view.text as? android.text.Spanned
                        text?.getSpans(0, text.length, Any::class.java)?.count {
                            it is CreationInlineMathSpan
                        } ?: 0
                    }
                }
                return count
            }
            until { nodes().any { it.text?.toString()?.startsWith("压强公式") == true } }
            assertEquals(0, mathSpans())
            scenario.onActivity {
                source.value += "$。\n\n代码：`$" + "x" + "$`\n\n价格：$5 和 $10"
            }
            until { mathSpans() == 1 }
            SystemClock.sleep(700)
            capture("creation-inline-math-streaming.png")
            scenario.onActivity { streaming.value = false }
            until { mathSpans() == 1 }
            capture("creation-inline-math-complete.png")
        }
    }

    @Test fun longChineseMermaidLabelsFitInsideTheirNodes() {
        setup()
        val source = "graph TD\n A[开始：检查环境与设备状态并确认今天的测试计划] --> B{检查各项准备工作是否已经全部完成}\n" +
            "B -->|状态良好并且全部检查通过| C[执行任务并记录每一个阶段的处理结果]\n" +
            "B -->|出现异常或者需要进一步确认| D[暂停任务并进行充分沟通后调整方案]\n D --> B\n C --> E[结束：整理完整记录并安排后续检查]"
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            lateinit var web: android.webkit.WebView
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("长文本验证", CreationUiState(session = CreationSession("long-diagram", "长文本", messages = listOf(
                    CreationMessage("r", "assistant", "```mermaid\n$source\n```", 0, "r"))), loading = false,
                    alignReplyRequestId = "r"), onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("Mermaid 流程图") != null }
            scenario.onActivity { activity -> web = views(activity.window.decorView).filterIsInstance<android.webkit.WebView>().single() }
            fun javascript(expression: String): String {
                val latch = java.util.concurrent.CountDownLatch(1)
                var result = ""
                scenario.onActivity { web.evaluateJavascript(expression) { result = it; latch.countDown() } }
                assertTrue(latch.await(5, java.util.concurrent.TimeUnit.SECONDS))
                return result
            }
            until { javascript("document.body.dataset.rendered") == "\"true\"" }
            SystemClock.sleep(700)
            assertEquals("true", javascript("document.querySelector('svg').textContent.includes('确认今天的测试计划')"))
            assertEquals("0", javascript("document.querySelectorAll('svg foreignObject').length"))
            val fit = "Array.from(document.querySelectorAll('svg .node')).every(n => {" +
                "const label=n.querySelector('.label'), shape=n.querySelector('.label-container');" +
                "if(!label || !shape) return false; const a=label.getBoundingClientRect(),b=shape.getBoundingClientRect();" +
                "return a.left>=b.left-1 && a.right<=b.right+1 && a.top>=b.top-1 && a.bottom<=b.bottom+1;})"
            assertEquals("Every long label must fit its node", "true", javascript(fit))
            capture("creation-mermaid-long-labels.png")
        }
    }

    @Test fun mermaidRendersOfflineAndIncompleteFenceStaysPending() {
        setup()
        val graph = "graph TD\n A[开始] --> B{准备好了？}\n B -->|是| C[执行任务]\n B -->|否| D[调整计划]\n D --> B\n C --> E[完成]"
        val unfinished = "```mermaid\n$graph"
        val pending = creationMarkdownBlocks(unfinished, true).single()
        assertEquals(CreationBlockKind.Diagram, pending.kind)
        assertTrue(pending.pending)
        val complete = "$unfinished\n```"
        assertFalse(creationMarkdownBlocks(complete, true).single().pending)
        val state = mutableStateOf(CreationUiState(session = CreationSession("diagram", "流程图", messages = listOf(
            CreationMessage("r", "assistant", complete, 0, "r"))), loading = false, alignReplyRequestId = "r"))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            lateinit var web: android.webkit.WebView
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("流程图验证", state.value, onBack = {}, onInput = {}, onSend = {},
                    onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("Mermaid 流程图") != null }
            scenario.onActivity { activity -> web = views(activity.window.decorView).filterIsInstance<android.webkit.WebView>().single() }
            fun javascript(expression: String): String {
                val latch = java.util.concurrent.CountDownLatch(1)
                var result = ""
                scenario.onActivity { web.evaluateJavascript(expression) { result = it; latch.countDown() } }
                assertTrue(latch.await(5, java.util.concurrent.TimeUnit.SECONDS))
                return result
            }
            until { javascript("document.body.dataset.rendered") == "\"true\"" }
            assertEquals("true", javascript("!!document.querySelector('svg') && document.querySelectorAll('svg .node').length >= 5"))
            assertEquals("true", javascript("document.querySelector('svg').textContent.includes('开始')"))
            SystemClock.sleep(700)
            File(instrument.targetContext.getExternalFilesDir(null), "creation-mermaid-metrics.json").writeText(
                javascript("JSON.stringify({width:innerWidth,height:innerHeight,svg:document.querySelector('svg').getBoundingClientRect().toJSON(),box:document.querySelector('svg').getAttribute('viewBox'),style:document.querySelector('svg').getAttribute('style')})"))
            capture("creation-mermaid-flowchart.png")
            var originalScale = 0f
            scenario.onActivity {
                assertTrue(web.settings.blockNetworkLoads)
                originalScale = web.scale
                assertTrue(web.zoomIn())
            }
            SystemClock.sleep(400)
            scenario.onActivity { assertTrue(web.scale > originalScale) }
            instrument.runOnMainSync { state.value = state.value.copy(session = state.value.session!!.copy(messages = listOf(
                CreationMessage("r", "assistant", "```mermaid\nthis is not a diagram\n```", 0, "r")))) }
            until { nodes().any { it.text?.toString()?.contains("流程图语法无法解析") == true } }
            assertTrue(nodes().any { it.text?.toString()?.contains("this is not a diagram") == true })
        }
    }

    @Test fun keyboardResizePreservesReadingAwayFromBottom() = verifyStationaryResize(false, false)
    @Test fun generatingReplyIgnoresKeyboardResizeAtStart() = verifyStationaryResize(true, false)
    @Test fun generatingReplyIgnoresKeyboardResizeAtBottom() = verifyStationaryResize(true, true)

    private fun verifyStationaryResize(sending: Boolean, atBottom: Boolean) {
        setup()
        val height = mutableStateOf(700)
        val body = (1..35).joinToString("\n\n") { "第 $it 段键盘位置验证。" }
        val seed = CreationSession("resize-policy", "键盘策略", messages = listOf(
            CreationMessage("u", "user", "请继续", 0, "u"), CreationMessage("r", "assistant", body, 0, "r")))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            lateinit var preview: DialogPreviewActivity
            fun textTop(): Int {
                var result = 0
                instrument.runOnMainSync {
                    val view = views(preview.window.decorView).filterIsInstance<android.widget.TextView>()
                        .first { it.text.toString().contains("第 30 段") }
                    val location = IntArray(2); view.getLocationOnScreen(location); result = location[1]
                }
                return result
            }
            scenario.onActivity { activity ->
                preview = activity
                activity.setContent { PonyChatTheme {
                    androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.height(height.value.dp)) {
                        CreationChatContent("键盘策略", CreationUiState(session = seed, loading = false, sending = sending,
                            alignReplyRequestId = "r"), onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                    }
                } }
            }
            until { find("消息角色主页") != null }
            SystemClock.sleep(800)
            if (atBottom) {
                val button = bounds("回到底部")
                shell("input tap ${button.centerX()} ${button.centerY()}")
                SystemClock.sleep(900)
            }
            val before = textTop()
            scenario.onActivity { height.value = 450 }
            SystemClock.sleep(500)
            assertEquals("Opening: sending=$sending bottom=$atBottom", before, textTop())
            scenario.onActivity { height.value = 700 }
            SystemClock.sleep(500)
            assertEquals("Closing: sending=$sending bottom=$atBottom", before, textTop())
        }
    }

    @Test fun messageTapDismissesEmojiAndMorePanels() {
        setup()
        val seed = CreationSession("panels", "面板", messages = listOf(
            CreationMessage("u", "user", "你好", 0, "u"), CreationMessage("r", "assistant", "点击这里收起面板", 0, "r")))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme {
                CreationChatContent("面板", CreationUiState(session = seed, loading = false), onBack = {}, onInput = {},
                    onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("消息角色主页") != null }
            for ((button, marker) in listOf("更多功能" to "创作设定", "表情符号" to "😀")) {
                val buttonRect = bounds(button)
                shell("input tap ${buttonRect.centerX()} ${buttonRect.centerY()}")
                until { find(marker) != null || nodes().any { it.text?.toString() == marker } }
                val message = nodes().first { it.text?.toString()?.contains("点击这里收起面板") == true }
                val rect = Rect(); message.getBoundsInScreen(rect)
                shell("input tap ${rect.centerX()} ${rect.centerY()}")
                until { find(marker) == null && nodes().none { it.text?.toString() == marker } }
            }
            capture("creation-panels-dismissed.png")
        }
    }

    @Test fun rapidRegenerationWithChangingReplyHeightAlwaysAlignsToStart() {
        setup()
        val user = CreationMessage("u", "user", "问题", 0, "u")
        val reply = CreationMessage("r", "assistant", "旧的长回复。".repeat(180), 0, "r")
        val state = mutableStateOf(CreationUiState(session = CreationSession("rapid", "对齐", messages = listOf(user, reply)),
            loading = false, alignReplyRequestId = "r"))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme {
                CreationChatContent("对齐验证", state.value, onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("消息角色主页") != null }
            SystemClock.sleep(800)
            val expected = bounds("消息角色主页").top
            repeat(6) { index ->
                shell("input swipe 540 1300 540 500 120")
                val id = "rapid-$index"
                instrument.runOnMainSync {
                    state.value = state.value.copy(session = state.value.session!!.copy(messages = listOf(user,
                        reply.copy(id = "stream-$id", requestId = id, content = ""))), sending = true, alignReplyRequestId = id)
                }
                SystemClock.sleep(30)
                instrument.runOnMainSync {
                    state.value = state.value.copy(session = state.value.session!!.copy(messages = listOf(user,
                        reply.copy(id = id, requestId = id, content = if (index % 2 == 0) "短回复" else "新的长回复。".repeat(180)))), sending = false)
                }
                SystemClock.sleep(750)
                assertEquals("Regeneration $index", expected, bounds("消息角色主页").top)
            }
            capture("creation-regeneration-aligned.png")
        }
    }
    @Test fun alignedShortReplyKeepsItsPositionOnKeyboardOpenAndClose() {
        setup()
        shell("settings put secure show_ime_with_hard_keyboard 1")
        val user = CreationMessage("u", "user", "问好", 0, "u")
        val state = mutableStateOf(CreationUiState(session = CreationSession("short-anchor", "短回复", messages = listOf(user)), loading = false))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
                activity.setContent { PonyChatTheme {
                    CreationChatContent("短回复", state.value, onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                } }
            }
            SystemClock.sleep(300)
            instrument.runOnMainSync {
                state.value = state.value.copy(session = state.value.session!!.copy(messages = listOf(user,
                    CreationMessage("short", "assistant", "你好。", 0, "short"))), alignReplyRequestId = "short")
            }
            until { find("消息角色主页") != null }
            SystemClock.sleep(800)
            val top = bounds("消息角色主页").top
            val input = nodes().first { it.isEditable }
            val rect = Rect(); input.getBoundsInScreen(rect)
            shell("input tap ${rect.centerX()} ${rect.centerY()}")
            SystemClock.sleep(800)
            assertEquals(top, bounds("消息角色主页").top)
            shell("input keyevent KEYCODE_BACK")
            SystemClock.sleep(800)
            assertEquals(top, bounds("消息角色主页").top)
        }
    }

    @Test fun delayedFirstTokenNeverMovesTheAlignedReplyStart() {
        setup()
        val user = CreationMessage("u", "user", "请介绍自己", 0, "u")
        val reply = CreationMessage("stream-delayed", "assistant", "", 0, "delayed")
        val state = mutableStateOf(CreationUiState(session = CreationSession("delayed", "首字验证", messages = listOf(user, reply)),
            loading = false, sending = true, alignReplyRequestId = "delayed"))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme {
                CreationChatContent("首字验证", state.value, onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("消息角色主页") != null }
            // The first token arrives after the 500ms alignment has finished.
            SystemClock.sleep(1100)
            val top = bounds("消息角色主页").top
            for (text in listOf("你", "你好。", "你好。\n\n我叫柔柔。", "你好。\n\n我叫柔柔。\n\n" + "慢慢介绍自己。".repeat(100))) {
                instrument.runOnMainSync {
                    state.value = state.value.copy(session = state.value.session!!.copy(messages = listOf(user, reply.copy(content = text))))
                }
                SystemClock.sleep(180)
                assertEquals("First-token and later layouts must keep the header fixed", top, bounds("消息角色主页").top)
            }
            capture("creation-delayed-first-token-aligned.png")
        }
    }

    @Test fun horizontalTableReadingKeepsPositionAndInputFocusesOnFirstTap() {
        setup()
        shell("settings put secure show_ime_with_hard_keyboard 1")
        val code = "import time\n# 注释\ndef greet(name):\n    print(\"你好\", name, 123)"
        val table = "| 第一列 | 第二列 | 第三列 | 第四列 |\n| --- | --- | --- | --- |\n| A | B | C | 最右内容 |"
        val reply = CreationMessage("r", "assistant", "$table\n\n```python\n$code\n```", 0, "r")
        val seed = CreationSession("reading-focus", "焦点验证", messages = listOf(CreationMessage("u", "user", "展示代码", 0, "u"), reply))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false); activity.window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING); activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("焦点验证", CreationUiState(session = seed, loading = false, alignReplyRequestId = "r"),
                    onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
            } } }
            until { find("表格横向滚动") != null }
            SystemClock.sleep(800)
            val top = bounds("表格横向滚动").top
            val rect = bounds("表格横向滚动")
            shell("input swipe 950 ${rect.centerY()} 100 ${rect.centerY()} 350")
            SystemClock.sleep(200)
            assertEquals("Table scroll must not request vertical focus", top, bounds("表格横向滚动").top)
            val input = nodes().first { it.className?.toString() == "android.widget.EditText" }
            val inputRect = Rect(); input.getBoundsInScreen(inputRect)
            shell("input tap ${inputRect.centerX()} ${inputRect.centerY()}")
            until { nodes().any { it.className?.toString() == "android.widget.EditText" && it.isFocused } }
            SystemClock.sleep(700)
            assertEquals("Horizontal reading should preserve the table's vertical anchor", top, bounds("表格横向滚动").top)
            scenario.onActivity { activity ->
                val view = views(activity.window.decorView).filterIsInstance<android.widget.TextView>().first { it.text.toString() == code }
                val spans = (view.text as android.text.Spanned).getSpans(0, code.length, android.text.style.ForegroundColorSpan::class.java)
                assertTrue(spans.map { it.foregroundColor }.toSet().size >= 4)
            }
            capture("creation-highlight-and-input-focus.png")
            shell("input keyevent KEYCODE_BACK")
        }
    }

    @Test fun cachedSessionsSurviveReloadAndAreIsolatedBetweenAccounts() {
        setup()
        val prefs = top.ponychat.webview.data.prefs.AppPreferences(instrument.targetContext)
        val old = prefs.username
        try {
            prefs.username = "cache-acceptance"
            val cache = CreationLocalCache(prefs)
            val reply = CreationMessage("cached-reply", "assistant", "离线缓存正文", 1, "r")
            val seed = CreationSession("cache-session", "离线会话", instructions = "保留创作指令", messages = listOf(reply),
                replyVersions = listOf(reply), contextUsage = CreationContextUsage(100, 65536))
            cache.save(seed); cache.saveHistory("cache-character", listOf(CreationHistory(seed.id, seed.title)))
            prefs.setCreationSessionId("cache-character", seed.id)
            val offline = object : CreationRepository(prefs) {
                override suspend fun history(characterId: String): List<CreationHistory> = throw java.io.IOException("离线")
            }
            lateinit var vm: CreationViewModel
            val owner = androidx.lifecycle.ViewModelStore()
            instrument.runOnMainSync { vm = CreationViewModel(prefs, "cache-character", offline); owner.put("vm", vm) }
            until { !vm.state.value.loading && vm.state.value.session?.messages?.lastOrNull()?.content == "离线缓存正文" }
            assertEquals("保留创作指令", vm.state.value.session!!.instructions)
            assertEquals(100, vm.state.value.session!!.contextUsage!!.usedTokens)
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity -> activity.setContent { PonyChatTheme {
                    val cachedState = vm.state.collectAsState().value
                    CreationChatContent("缓存验证", cachedState, onBack = {}, onInput = {}, onSend = {}, onRegenerate = {}, onNew = {}, onLoad = {})
                } } }
                until { find("离线缓存正文") != null }
                capture("creation-offline-cache.png")
            }
            instrument.runOnMainSync { owner.clear() }
            prefs.username = "another-cache-account"
            assertNull(CreationLocalCache(prefs).session(seed.id))
            prefs.username = "cache-acceptance"
            cache.remove(seed.id)
            assertNull(cache.session(seed.id))
        } finally { prefs.username = old }
    }

    @Test fun displaySettingsUsePonyChatControlsAndPersistImmediately() {
        setup()
        val prefs = top.ponychat.webview.data.prefs.AppPreferences(instrument.targetContext)
        val originalDark = prefs.isDarkTheme; val originalTimestamp = prefs.showTimestamp; val originalScale = prefs.fontScale
        val revision = mutableStateOf(0)
        try {
            ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
                scenario.onActivity { activity -> activity.setContent {
                    val appearance = remember(revision.value) { prefs.isDarkTheme to prefs.fontScale }
                    PonyChatTheme(darkTheme = appearance.first, fontScale = appearance.second) {
                        CreationDisplaySettings(prefs, {}) { revision.value++ }
                    }
                } }
                until { find("显示时间戳") != null }
                capture("creation-display-settings.png")
                val switches = nodes().filter { it.isCheckable }
                assertEquals(2, switches.size)
                assertTrue(switches.first().performAction(AccessibilityNodeInfo.ACTION_CLICK))
                until { prefs.isDarkTheme != originalDark }
                SystemClock.sleep(300)
                capture("creation-display-settings-light.png")
                assertTrue(nodes().filter { it.isCheckable }.last().performAction(AccessibilityNodeInfo.ACTION_CLICK))
                until { prefs.showTimestamp != originalTimestamp }
                val slider = nodes().first { it.className?.toString() == "android.widget.SeekBar" }
                val progress = android.os.Bundle().apply { putFloat(AccessibilityNodeInfo.ACTION_ARGUMENT_PROGRESS_VALUE, 1.25f) }
                assertTrue(slider.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS.id, progress))
                until { prefs.fontScale > 1.1f }
                SystemClock.sleep(300)
                capture("creation-display-settings-large.png")
            }
        } finally { prefs.isDarkTheme = originalDark; prefs.showTimestamp = originalTimestamp; prefs.fontScale = originalScale }
    }
    @Test fun contextUsageShowsOnlyKnownRealFields() {
        setup()
        val usage = mutableStateOf<CreationContextUsage?>(null)
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationContextEditor(CreationSession("usage", "上下文", contextLayout = listOf(
                    CreationContextBlock("system", "text", "系统提示词", "默认像角色发消息一样自然回复。"),
                    CreationContextBlock("character", "character", "角色设定"),
                    CreationContextBlock("history", "history", "对话历史"),
                    CreationContextBlock("instructions", "instructions", "创作指令"),
                    CreationContextBlock("input", "latest", "最新用户输入"))), null, {}, usage = usage.value, onSave = {})
            } } }
            until { find("—/—") != null }
            capture("creation-context-unknown.png")
            instrument.runOnMainSync { usage.value = CreationContextUsage(contextLimit = 64000) }
            until { find("—/64000") != null }
            capture("creation-context-limit.png")
            instrument.runOnMainSync { usage.value = CreationContextUsage(12345, 64000) }
            until { find("12345/64000") != null }
            capture("creation-context-real.png")
            instrument.runOnMainSync { usage.value = CreationContextUsage(12345) }
            until { find("12345/—") != null }
        }
    }
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private fun walk(n: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> = if (n == null) emptyList()
        else listOf(n) + (0 until n.childCount).flatMap { walk(n.getChild(it)) }
    private fun nodes(): List<AccessibilityNodeInfo> {
        instrument.uiAutomation.clearCache()
        return instrument.uiAutomation.windows.flatMap { walk(it.root) }
    }
    private fun find(text: String) = nodes().firstOrNull { it.text?.toString() == text || it.contentDescription?.toString() == text }
    private fun until(check: () -> Boolean) {
        repeat(70) { if (check()) return; SystemClock.sleep(100) }
        fail("Timed out waiting for structured reply UI")
    }
    private fun bounds(text: String): Rect = Rect().also { requireNotNull(find(text)).getBoundsInScreen(it) }
    private fun shell(command: String) { instrument.uiAutomation.executeShellCommand(command).close() }
    private fun setup() {
        instrument.uiAutomation.serviceInfo = instrument.uiAutomation.serviceInfo.apply {
            flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
    }
    private fun capture(name: String) {
        val bitmap = instrument.uiAutomation.takeScreenshot()
        File(instrument.targetContext.getExternalFilesDir(null), name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
    }
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    @Test fun retryRemovesOldReplyImmediatelyAndRestoresItOnFailure() {
        setup()
        val prefs = top.ponychat.webview.data.prefs.AppPreferences(instrument.targetContext)
        val seed = CreationSession("retry", "重试验证", messages = listOf(
            CreationMessage("user", "user", "用户问题", 0, "u"),
            CreationMessage("old", "assistant", "重试后应立即消失的旧回复", 0, "old-r")))
        val accept = kotlinx.coroutines.CompletableDeferred<Unit>()
        val result = kotlinx.coroutines.CompletableDeferred<CreationSession>()
        val repo = object : CreationRepository(prefs) {
            override suspend fun history(characterId: String) = listOf(CreationHistory(seed.id, seed.title))
            override suspend fun load(id: String) = seed
            override suspend fun stream(session: CreationSession, text: String, requestId: String, regenerate: Boolean,
                onSession: (CreationSession) -> Unit, onDelta: (String) -> Unit, editMessageId: String?, continueStory: Boolean): CreationSession {
                assertTrue(regenerate)
                accept.await()
                onSession(seed.copy(busy = true))
                return result.await()
            }
        }
        lateinit var vm: CreationViewModel
        val owner = androidx.lifecycle.ViewModelStore()
        instrument.runOnMainSync { vm = CreationViewModel(prefs, "retry", repo); owner.put("vm", vm) }
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                val state = vm.state.collectAsState().value
                CreationChatContent("重试验证", state, onBack = {}, onInput = vm::input, onSend = { vm.send() },
                    onRegenerate = { vm.send(true) }, onNew = {}, onLoad = {})
            } } }
            until { find("重试后应立即消失的旧回复") != null }
            var action = requireNotNull(find("重新生成"))
            while (!action.isClickable && action.parent != null) action = action.parent
            assertTrue(action.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            until { vm.state.value.sending && find("重试后应立即消失的旧回复") == null }
            assertFalse(accept.isCompleted)
            assertEquals(listOf("user", "assistant"), vm.state.value.session!!.messages.map { it.role })
            assertEquals("", vm.state.value.session!!.messages.last().content)
            accept.complete(Unit)
            SystemClock.sleep(300)
            assertNull(find("重试后应立即消失的旧回复"))
            capture("creation-optimistic-retry.png")
            result.completeExceptionally(java.io.IOException("连接失败"))
            until { !vm.state.value.sending && find("重试后应立即消失的旧回复") != null }
        }
        instrument.runOnMainSync { owner.clear() }
    }

    @Test fun streamBlocksStayPendingAndReplyStartDoesNotFollowTokens() {
        setup()
        val history = (1..25).map { CreationMessage("user-$it", "user", "历史 $it", 0, "$it") }
        val initial = CreationSession("stream-layout", "流式验证", messages = history)
        val state = mutableStateOf(CreationUiState(session = initial, loading = false))
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                androidx.core.view.WindowCompat.setDecorFitsSystemWindows(activity.window, false)
                activity.setContent { PonyChatTheme(darkTheme = true) {
                    CreationChatContent("结构验证", state.value, onBack = {}, onInput = {}, onSend = {},
                        onRegenerate = {}, onNew = {}, onLoad = {})
                } }
            }
            until { find("历史 25") != null }
            val prefix = "正文开头。\n\n"
            val table = "| 阶段 | 时间 | 内容 |\n| --- | --- | --- |\n"
            scenario.onActivity { state.value = state.value.copy(sending = true, alignReplyRequestId = "new",
                session = initial.copy(messages = history + CreationMessage("input", "user", "请生成表格", 0, "new") +
                    CreationMessage("stream-new", "assistant", prefix + table, 0, "new", true))) }
            SystemClock.sleep(100)
            shell("input swipe 540 500 540 1300 350")
            until { find("表格正在生成中…") != null && bounds("消息角色主页").top < 400 }
            SystemClock.sleep(400)
            val top = bounds("消息角色主页").top
            repeat(10) { index ->
                scenario.onActivity {
                    val old = state.value.session!!
                    val content = prefix + table + (1..index+1).joinToString("\n") { "| 阶段 $it | 时间 $it | 说明 $it |" }
                    state.value = state.value.copy(session = old.copy(messages = old.messages.dropLast(1) + old.messages.last().copy(content = content)))
                }
                SystemClock.sleep(40)
                assertNull(find("表格横向滚动"))
                assertEquals(top, bounds("消息角色主页").top)
            }
            capture("creation-table-pending.png")
            scenario.onActivity {
                val old = state.value.session!!
                state.value = state.value.copy(session = old.copy(messages = old.messages.dropLast(1) + old.messages.last().copy(
                    content = old.messages.last().content + "\n\n后续普通文字。\n\n```kotlin\nval result = 1")))
            }
            until { find("表格横向滚动") != null }
            assertTrue(creationMarkdownBlocks(state.value.session!!.messages.last().content, true).last().pending)
            assertNotNull(find("表格横向滚动"))
            assertEquals(top, bounds("消息角色主页").top)
            scenario.onActivity {
                val old = state.value.session!!
                state.value = state.value.copy(sending = false, session = old.copy(messages = old.messages.dropLast(1) +
                    old.messages.last().copy(id = "completed", incomplete = false, content = old.messages.last().content + "\n```\n\n" + "继续讲故事。".repeat(120))))
            }
            SystemClock.sleep(500)
            assertEquals("Completion must not scroll to the end", top, bounds("消息角色主页").top)
            capture("creation-table-complete-start.png")
        }
    }

    @Test fun arrowsCreateAndBrowseOnlyLatestReplyVersions() {
        setup()
        val user = CreationMessage("user", "user", "问题", 0, "u")
        val v1 = CreationMessage("v1", "assistant", "版本一：" + "这是用于验证滑动的角色消息。".repeat(4), 0, "r1")
        val v2 = v1.copy(id = "v2", requestId = "r2", content = v1.content.replace("版本一", "版本二"))
        val state = mutableStateOf(CreationUiState(session = CreationSession("versions", "版本验证", messages = listOf(user, v2),
            replyVersions = listOf(v1, v2), selectedReplyVersion = 1), loading = false, alignReplyRequestId = "r2"))
        var generates = 0
        var previous = 0
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("版本验证", state.value, onBack = {}, onInput = {}, onSend = {},
                    onRegenerate = {
                        generates++
                        val old = state.value.session!!
                        val n = old.replyVersions.size + 1
                        val reply = v2.copy(id = "v$n", requestId = "r$n", content = "版本$n：" + v2.content.substringAfter("："))
                        state.value = state.value.copy(session = old.copy(messages = listOf(user, reply),
                            replyVersions = old.replyVersions + reply, selectedReplyVersion = old.replyVersions.size), alignReplyRequestId = reply.requestId)
                    }, onNew = {}, onLoad = {}, onNextVersion = {
                        val old = state.value.session!!
                        val selected = old.selectedReplyVersion + 1
                        val reply = old.replyVersions[selected]
                        state.value = state.value.copy(session = old.copy(messages = listOf(user, reply), selectedReplyVersion = selected),
                            alignReplyRequestId = reply.requestId)
                    }, onPreviousVersion = {
                        previous++
                        val old = state.value.session!!
                        val selected = old.selectedReplyVersion - 1
                        val reply = old.replyVersions[selected]
                        state.value = state.value.copy(session = old.copy(messages = listOf(user, reply), selectedReplyVersion = selected),
                            alignReplyRequestId = reply.requestId)
                    })
            } } }
            until { find("2/2") != null }
            SystemClock.sleep(700)
            val prose = nodes().first { it.text?.toString()?.startsWith("版本二：") == true }
            val rect = Rect(); prose.getBoundsInScreen(rect)
            val y = rect.top + 25
            shell("input swipe 800 $y 620 $y 220")
            SystemClock.sleep(600)
            assertEquals(0, generates)
            assertNotNull(find("2/2"))
            shell("input swipe 980 $y 100 $y 280")
            SystemClock.sleep(600)
            assertEquals("Swiping must never generate", 0, generates)
            assertEquals(0, previous)
            fun clickArrow(label: String) {
                val target = bounds(label)
                shell("input tap ${target.centerX()} ${target.centerY()}")
            }
            clickArrow("生成新版本")
            until { generates == 1 && find("3/3") != null }
            SystemClock.sleep(700)
            clickArrow("上一版本")
            until { previous == 1 && find("2/3") != null }
            SystemClock.sleep(700)
            assertTrue(bounds("消息角色主页").top < 400)
            clickArrow("上一版本")
            until { previous == 2 && find("1/3") != null }
            SystemClock.sleep(700)
            clickArrow("上一版本")
            SystemClock.sleep(300)
            assertEquals("First version cannot go back", 2, previous)
            clickArrow("下一版本")
            until { find("2/3") != null }
            assertEquals(1, generates)
            SystemClock.sleep(700)
            clickArrow("下一版本")
            until { find("3/3") != null }
            assertEquals(1, generates)
            SystemClock.sleep(700)
            clickArrow("生成新版本")
            until { generates == 2 && find("4/4") != null }
            SystemClock.sleep(700)
            clickArrow("上一版本")
            until { find("3/4") != null }
            SystemClock.sleep(700)
            capture("creation-reply-version-arrows.png")
            scenario.onActivity {
                val old = state.value.session!!
                state.value = state.value.copy(session = old.copy(messages = listOf(user, v1,
                    user.copy(id = "next-user", requestId = "next"), v2.copy(id = "next-reply", requestId = "next-r")),
                    replyVersions = emptyList(), selectedReplyVersion = 0), alignReplyRequestId = null)
            }
            shell("input swipe 540 500 540 1700 350")
            SystemClock.sleep(500)
            assertNull(find("1/3"))
            val oldText = nodes().firstOrNull { it.text?.toString()?.startsWith("版本一：") == true }
            if (oldText != null) {
                val oldRect = Rect(); oldText.getBoundsInScreen(oldRect)
                shell("input swipe 980 ${oldRect.top+20} 100 ${oldRect.top+20} 280")
                SystemClock.sleep(600)
                assertEquals("Older replies cannot generate versions", 2, generates)
            } else fail("Older message must be visible for gesture verification")
        }
    }

    @Test fun tablesAndCodeScrollHorizontallyWithoutRegenerating() {
        setup()
        val text = "| 第一列 | 第二列 | 第三列 | 第四列 |\n| --- | --- | --- | --- |\n| 内容一 | 内容二 | 内容三 | 最右侧内容 |\n\n```text\n" +
            "very_long_code_".repeat(30) + "END\n```"
        val seed = CreationSession("horizontal", "横向验证", messages = listOf(CreationMessage("user", "user", "横向内容", 0, "u"),
            CreationMessage("reply", "assistant", text, 0, "r")))
        var generates = 0
        ActivityScenario.launch(DialogPreviewActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { PonyChatTheme(darkTheme = true) {
                CreationChatContent("横向验证", CreationUiState(session = seed, loading = false), onBack = {}, onInput = {},
                    onSend = {}, onRegenerate = { generates++ }, onNew = {}, onLoad = {})
            } } }
            until { find("表格横向滚动") != null && find("代码横向滚动") != null }
            for (description in listOf("表格横向滚动", "代码横向滚动")) {
                val rect = bounds(description)
                shell("input swipe 950 ${rect.centerY()} 100 ${rect.centerY()} 350")
                SystemClock.sleep(400)
                scenario.onActivity { activity ->
                    val scroller = views(activity.window.decorView).filterIsInstance<HorizontalScrollView>()
                        .first { it.contentDescription?.toString() == description }
                    assertTrue("$description must actually scroll", scroller.scrollX > 0)
                }
                assertEquals(0, generates)
            }
            capture("creation-horizontal-table-code.png")
        }
    }
}
