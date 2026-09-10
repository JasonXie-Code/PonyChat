package top.ponychat.webview.ui.chat

import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Text
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import top.ponychat.webview.data.model.Message
import top.ponychat.webview.debug.DialogPreviewActivity

/** Runs the production scroll effects against a real measured Compose LazyColumn. */
@RunWith(AndroidJUnit4::class)
class NormalChatAutoFollowInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var scenario: ActivityScenario<DialogPreviewActivity>
    private lateinit var list: LazyListState
    private val state = mutableStateOf(ChatUiState(
        conversationId = "scroll-regression",
        messages = (0 until 12).map { message("initial-$it") },
    ))
    private val settled = mutableStateOf(false)
    private val touching = mutableStateOf(false)
    private val suppressed = mutableStateOf(false)
    private val readingHistory = mutableStateOf(false)
    private val tailHeight = mutableIntStateOf(80)
    private val panelHeight = mutableIntStateOf(0)
    private val bottomPadding = mutableIntStateOf(0)
    private val effectiveEnd = mutableIntStateOf(Int.MAX_VALUE)
    private var panelHeightPx = 0

    @Before
    fun openActivity() {
        scenario = ActivityScenario.launch(DialogPreviewActivity::class.java)
        scenario.onActivity { activity ->
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            if (android.os.Build.VERSION.SDK_INT >= 33) activity.setRecentsScreenshotEnabled(false)
        }
    }

    @After
    fun closeActivity() { scenario.close() }

    private fun openList(initialPanelHeight: Int = 0) {
        main {
            settled.value = false
            touching.value = false
            suppressed.value = false
            readingHistory.value = false
            tailHeight.intValue = 80
            panelHeight.intValue = initialPanelHeight
            bottomPadding.intValue = initialPanelHeight
            state.value = ChatUiState(conversationId = "scroll-regression",
                messages = (0 until 12).map { message("initial-$it") })
        }
        scenario.onActivity { activity ->
            // Avoid API 36.1 emulator task-snapshot GPU readback on ActivityScenario.close().
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            activity.setContent {
                list = rememberLazyListState()
                val density = LocalDensity.current
                panelHeightPx = with(density) { 160.dp.roundToPx() }
                val viewportEnd = list.layoutInfo.viewportEndOffset -
                    with(density) { panelHeight.intValue.dp.roundToPx() }
                SideEffect { effectiveEnd.intValue = viewportEnd.coerceAtLeast(1) }
                val near = remember {
                    derivedStateOf {
                        list.layoutInfo.totalItemsCount == 0 ||
                            (list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1) >=
                            list.layoutInfo.totalItemsCount - 2
                    }
                }
                ChatScreenScrollLaunchedEffects(
                    listState = list,
                    state = state.value,
                    isNearBottom = near,
                    userScrolledUpState = readingHistory,
                    listTouchActiveState = touching,
                    listAutoFollowSuppressedState = suppressed,
                    capsuleHeightPxState = remember { mutableIntStateOf(0) },
                    listEffectiveViewportEndPxState = effectiveEnd,
                    naturalBottomPaddingPx = 0,
                    bottomAnchorTolerancePx = 2f,
                    initialPresentationSettled = settled.value,
                    scrollToLastAssistantInGalgame = {},
                )
                LazyColumn(Modifier.width(300.dp).height(320.dp), state = list,
                    contentPadding = PaddingValues(bottom = bottomPadding.intValue.dp)) {
                    items(state.value.messages, key = { it.stableChatItemKey() }) { message ->
                        val height = if (message.id == state.value.messages.last().id) tailHeight.intValue else 80
                        Box(Modifier.height(height.dp)) { Text(message.content) }
                    }
                }
            }
        }
        await("list measured") { ::list.isInitialized && list.layoutInfo.totalItemsCount == 12 }
        scrollTo(11)
        main { settled.value = true }
        SystemClock.sleep(300)
    }

    @Test
    fun normalAutoFollowBehaviorMatrix() {
        // One Activity for the whole matrix: API 36.1 emulator task-snapshot persistence
        // crashes system_server between separately launched instrumentation cases.
        val cases = linkedMapOf<String, () -> Unit>(
            "each bubble" to ::followsEveryBubbleInAnOrdinaryReply,
            "near bottom" to ::followsFromNearBottomAfterASmallDrag,
            "touch release" to ::resumesAfterFingerLiftWhenMessageArrivesDuringTouch,
            "bubble growth" to ::repairsBottomAfterLastBubbleGrowsWithoutANewMessage,
            "background refresh" to ::followsBackgroundRefreshFromNearBottom,
            "history reader" to ::incomingMessagesDoNotMoveAReaderOfOlderHistory,
            "history prepend" to ::prependingHistoryPreservesTheVisibleMessage,
            "quick message panel dismissal" to ::quickMessageRemainsVisibleAfterPanelCompensationReverts,
            "quick message from history" to ::quickMessageReturnsFromHistoryAfterPanelDismissal,
            "panel history reader" to ::dismissingPanelWithoutSendingDoesNotPullHistoryToBottom,
            "programmatic history jump" to ::programmaticHistoryJumpIsNotUndone,
        )
        val failures = mutableListOf<String>()
        cases.forEach { (name, check) ->
            try {
                openList(initialPanelHeight = if (name.startsWith("quick") || name == "panel history reader") 160 else 0)
                check()
                println("SCROLL_CASE $name PASS")
            } catch (error: AssertionError) {
                failures += "$name: ${error.message}"
                println("SCROLL_CASE $name FAIL: ${error.message}")
            }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    fun followsEveryBubbleInAnOrdinaryReply() {
        repeat(4) {
            main { append("bubble-$it") }
            await("bubble $it reaches viewport bottom") { atBottom() }
        }
    }

    fun followsFromNearBottomAfterASmallDrag() {
        dragTo(7) // Rows 7..10 visible: near the bottom, but row 11 is below the viewport.
        assertFalse(read { list.canSeeLastItem() })
        main { append("near-bottom") }
        await("near-bottom incoming bubble is visible") { atBottom() }
    }

    fun resumesAfterFingerLiftWhenMessageArrivesDuringTouch() {
        main { touching.value = true; append("during-touch") }
        SystemClock.sleep(450)
        main { touching.value = false }
        await("pending bubble follows after release") { atBottom() }
    }

    fun repairsBottomAfterLastBubbleGrowsWithoutANewMessage() {
        main { tailHeight.intValue = 280 }
        await("expanded image or text remains above input") { atBottom() }
    }

    fun followsBackgroundRefreshFromNearBottom() {
        dragTo(7)
        main { state.value = state.value.copy(isBackgroundRefreshing = true) }
        SystemClock.sleep(100)
        main {
            append("background-1")
            append("background-2")
            state.value = state.value.copy(isBackgroundRefreshing = false)
        }
        await("background messages follow near-bottom reader") { atBottom() }
    }

    fun incomingMessagesDoNotMoveAReaderOfOlderHistory() {
        dragTo(2)
        val before = read { list.firstVisibleItemIndex to list.firstVisibleItemScrollOffset }
        main { append("history-reader") }
        SystemClock.sleep(600)
        assertEquals(before, read { list.firstVisibleItemIndex to list.firstVisibleItemScrollOffset })
        assertTrue(read { readingHistory.value })
    }

    fun prependingHistoryPreservesTheVisibleMessage() {
        dragTo(2)
        val anchor = read { list.layoutInfo.visibleItemsInfo.first().key }
        main {
            state.value = state.value.copy(messages =
                (0 until 4).map { message("older-$it") } + state.value.messages)
        }
        SystemClock.sleep(600)
        assertEquals(anchor, read { list.layoutInfo.visibleItemsInfo.first().key })
    }

    fun quickMessageRemainsVisibleAfterPanelCompensationReverts() {
        main {
            // QuickMessagePanel closes before invoking its send callback. Padding is
            // released later when Scaffold settles the previous panel compensation.
            panelHeight.intValue = 0
            state.value = state.value.copy(messages = state.value.messages +
                message("quick-user").copy(role = "user", content = "（请推进剧情发展）"))
        }
        await("quick message laid out before compensation settlement") { atBottom() }
        settlePanelDismissal()
        await("quick message stays visible after panel compensation") { atBottom() }
        main { append("quick-reply") }
        await("reply after quick message follows too") { atBottom() }
    }

    fun quickMessageReturnsFromHistoryAfterPanelDismissal() {
        dragTo(2)
        assertTrue(read { readingHistory.value })
        quickMessageRemainsVisibleAfterPanelCompensationReverts()
        assertFalse(read { readingHistory.value })
    }

    fun dismissingPanelWithoutSendingDoesNotPullHistoryToBottom() {
        dragTo(2)
        main { panelHeight.intValue = 0 }
        settlePanelDismissal()
        SystemClock.sleep(500)
        assertTrue(read { readingHistory.value })
        assertFalse(read { list.canSeeLastItem() })
    }

    fun programmaticHistoryJumpIsNotUndone() {
        scrollTo(2) // Like jumping to an older quoted message, without a list drag.
        SystemClock.sleep(500)
        assertEquals(2, read { list.firstVisibleItemIndex })
    }

    private fun settlePanelDismissal() {
        main {
            // Same ordering as Scaffold's pendingBottomRevert: move the list first,
            // then remove its previously engaged bottom padding on the next layout.
            list.dispatchRawDelta(-panelHeightPx.toFloat())
            bottomPadding.intValue = 0
        }
        await("panel padding removed") { list.layoutInfo.afterContentPadding == 0 }
    }

    private fun dragTo(index: Int) {
        main { touching.value = true; suppressed.value = true }
        var finished = false
        main {
            CoroutineScope(Dispatchers.Main).launch {
                val rowHeight = list.layoutInfo.visibleItemsInfo.first().size
                list.scroll {
                    scrollBy(((index - list.firstVisibleItemIndex) * rowHeight -
                        list.firstVisibleItemScrollOffset).toFloat())
                    delay(100) // Keep the gesture active for measured frames.
                }
                finished = true
            }
        }
        await("drag to row $index") { finished }
        main { touching.value = false }
        SystemClock.sleep(200)
    }

    private fun scrollTo(index: Int) {
        var finished = false
        main {
            CoroutineScope(Dispatchers.Main).launch {
                list.scrollToItem(index)
                finished = true
            }
        }
        await("scrollTo($index)") { finished }
        SystemClock.sleep(100)
    }

    private fun append(id: String) {
        state.value = state.value.copy(messages = state.value.messages + message(id))
    }

    private fun atBottom(): Boolean {
        val info = list.layoutInfo
        val tail = info.visibleItemsInfo.lastOrNull() ?: return false
        return info.totalItemsCount == state.value.messages.size &&
            tail.key == state.value.messages.last().stableChatItemKey() &&
            tail.offset + tail.size <= effectiveEnd.intValue + 2
    }

    private fun main(block: () -> Unit) = instrumentation.runOnMainSync(block)

    private fun <T> read(block: () -> T): T {
        var value: T? = null
        main { value = block() }
        @Suppress("UNCHECKED_CAST")
        return value as T
    }

    private fun await(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 3_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (read(condition)) return
            SystemClock.sleep(30)
        }
        assertTrue(description, read(condition))
    }

    companion object {
        private fun message(id: String) = Message(id = id, messageId = id, role = "assistant", content = id)
    }
}
