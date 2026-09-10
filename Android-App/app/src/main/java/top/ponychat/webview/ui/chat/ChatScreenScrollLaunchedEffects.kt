package top.ponychat.webview.ui.chat

import android.util.Log
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import top.ponychat.webview.data.model.Message

private data class ChatHistoryRefreshBaseline(
    val visibleMessages: List<Message>,
    val wasAtBottom: Boolean,
    val visibleAnchorKey: String?,
    val visibleAnchorOffset: Int,
)

private data class ChatScrollSignal(
    val msgCount: Int,
    val lastRole: String,
    val streaming: Boolean,
    val mode: String,
    val canSeeLastItem: Boolean,
    val backgroundRefreshing: Boolean,
)

/**
 * 聊天页主列表滚动相关的 LaunchedEffect / snapshotFlow，从 [ChatScreenContentBody] 抽出以控制单文件行数。
 * 所有模式均为非流式输出，无需流式跟随滚动逻辑。
 */
@Composable
internal fun ChatScreenScrollLaunchedEffects(
    listState: LazyListState,
    state: ChatUiState,
    isNearBottom: State<Boolean>,
    userScrolledUpState: MutableState<Boolean>,
    listTouchActiveState: MutableState<Boolean>,
    listAutoFollowSuppressedState: MutableState<Boolean>,
    capsuleHeightPxState: MutableIntState,
    listEffectiveViewportEndPxState: MutableIntState,
    naturalBottomPaddingPx: Int,
    bottomAnchorTolerancePx: Float,
    initialPresentationSettled: Boolean,
    scrollToLastAssistantInGalgame: suspend (Boolean) -> Unit,
) {
    if (state.mode == "normal") {
        NormalChatAutoFollow(
            listState = listState,
            state = state,
            isNearBottom = isNearBottom,
            userScrolledUpState = userScrolledUpState,
            listTouchActiveState = listTouchActiveState,
            listAutoFollowSuppressedState = listAutoFollowSuppressedState,
            listEffectiveViewportEndPxState = listEffectiveViewportEndPxState,
            naturalBottomPaddingPx = naturalBottomPaddingPx,
            bottomAnchorTolerancePx = bottomAnchorTolerancePx,
            initialPresentationSettled = initialPresentationSettled,
        )
        return
    }
    // 长生命周期协程（LaunchedEffect(Unit)）中统一读取最新 state，
    // 避免捕获旧快照导致自动滚动分支"看起来消失"。
    val latestState = rememberUpdatedState(state)
    val latestInitialPresentationSettled = rememberUpdatedState(initialPresentationSettled)
    val historyRefreshBaselineState = remember(state.character?.id, state.mode) {
        mutableStateOf<ChatHistoryRefreshBaseline?>(null)
    }
    fun effectiveViewportEndPx(): Int? =
        listEffectiveViewportEndPxState.intValue
            .takeIf { it in 1 until Int.MAX_VALUE }
    fun shouldSkipAutoFollow(): Boolean =
        listTouchActiveState.value || listAutoFollowSuppressedState.value
    fun isAnchoredForAutoFollow(): Boolean =
        listState.canSeeLastItem(effectiveViewportEndPx())

    suspend fun scrollToBottomForNewUserMessage(branch: String) {
        val expectedItemCount = latestState.value.messages.size
        chatScrollToBottomAndRepair(
            listState = listState,
            lastMessageId = latestState.value.messages.lastOrNull()?.stableChatItemKey(),
            naturalBottomPaddingPx = naturalBottomPaddingPx,
            bottomAnchorTolerancePx = bottomAnchorTolerancePx,
            reason = branch,
            effectiveViewportEndOffsetPx = effectiveViewportEndPx(),
            expectedItemCount = expectedItemCount,
            shouldSkipRepair = { shouldSkipAutoFollow() },
        )
    }

    suspend fun scrollToSettledHistoryBottom(reason: String) {
        if (shouldSkipAutoFollow()) return
        val curState = latestState.value
        if (curState.messages.isEmpty()) return

        if (curState.mode.startsWith("galgame")) {
            if (capsuleHeightPxState.intValue == 0) delay(32)
            Log.d("TELEPORT", "$reason: galgame scrollToLastAssistant")
            scrollToLastAssistantInGalgame(false)
        } else {
            Log.d("TELEPORT", "$reason: normal scrollToBottomAndRepair")
            chatScrollToBottomAndRepair(
                listState = listState,
                lastMessageId = curState.messages.lastOrNull()?.stableChatItemKey(),
                naturalBottomPaddingPx = naturalBottomPaddingPx,
                bottomAnchorTolerancePx = bottomAnchorTolerancePx,
                reason = reason,
                effectiveViewportEndOffsetPx = effectiveViewportEndPx(),
                expectedItemCount = curState.messages.size,
                shouldSkipRepair = { shouldSkipAutoFollow() },
            )
        }
    }

    suspend fun restoreVisibleAnchor(baseline: ChatHistoryRefreshBaseline) {
        val key = baseline.visibleAnchorKey ?: return
        val anchorIndex = latestState.value.messages.indexOfFirst {
            it.stableChatItemKey() == key || it.id == key || it.messageId == key
        }
        if (anchorIndex >= 0) {
            listState.scrollToItem(anchorIndex, baseline.visibleAnchorOffset)
        }
    }

    // ── 切换对话 / 历史与后台刷新稳定后，做一次最终定位 ──
    LaunchedEffect(
        listState,
        state.conversationId,
        state.isLoadingHistory,
        state.isBackgroundRefreshing,
        initialPresentationSettled,
    ) {
        val curState = latestState.value
        if (curState.isLoadingHistory || curState.messages.isEmpty()) {
            if (curState.isLoadingHistory || !curState.isBackgroundRefreshing) {
                historyRefreshBaselineState.value = null
            }
            return@LaunchedEffect
        }

        if (curState.isBackgroundRefreshing) {
            if (historyRefreshBaselineState.value == null) {
                val firstVisibleIndex = listState.firstVisibleItemIndex
                historyRefreshBaselineState.value = ChatHistoryRefreshBaseline(
                    visibleMessages = curState.messages.toList(),
                    wasAtBottom = isAnchoredForAutoFollow(),
                    visibleAnchorKey = curState.messages.getOrNull(firstVisibleIndex)?.stableChatItemKey(),
                    visibleAnchorOffset = listState.firstVisibleItemScrollOffset,
                )
                Log.d(
                    "TELEPORT",
                    "history-cache-presented: baseline=${historyRefreshBaselineState.value}"
                )
            }
            return@LaunchedEffect
        }

        if (!latestInitialPresentationSettled.value) {
            Log.d("TELEPORT", "history-refresh-settled: initial presentation pending, keep baseline")
            return@LaunchedEffect
        }
        val baseline = historyRefreshBaselineState.value
        historyRefreshBaselineState.value = null
        if (baseline == null) {
            Log.d("TELEPORT", "history-settled: no refresh baseline, initial positioning owns scroll")
            return@LaunchedEffect
        }
        if (baseline.visibleMessages.isSameVisibleMessageListAs(curState.messages)) {
            Log.d("TELEPORT", "history-refresh-settled: unchanged, skip final scroll")
            return@LaunchedEffect
        }
        if (!baseline.wasAtBottom) {
            Log.d("TELEPORT", "history-refresh-settled: changed but old last was not visible, restore anchor")
            restoreVisibleAnchor(baseline)
            return@LaunchedEffect
        }
        if (shouldSkipAutoFollow()) {
            Log.d("TELEPORT", "history-refresh-settled: changed but auto-follow is suppressed, restore anchor")
            restoreVisibleAnchor(baseline)
            return@LaunchedEffect
        }
        scrollToSettledHistoryBottom(reason = "history-refresh-settled")
    }

    // ── 主滚动逻辑：新消息进入 / galgame 响应到达时自动滚动 ──
    LaunchedEffect(listState) {
        val scrollScope = this
        var prevMsgCount = latestState.value.messages.size
        var prevStreaming = latestState.value.isStreaming
        var prevBackgroundRefreshing = latestState.value.isBackgroundRefreshing
        var lastKnownCanSeeLastItem = listState.canSeeLastItem(effectiveViewportEndPx())
        var normalAssistantAutoFollowJob: Job? = null
        snapshotFlow {
            val cur = latestState.value
            ChatScrollSignal(
                msgCount = cur.messages.size,
                lastRole = cur.messages.lastOrNull()?.role ?: "",
                streaming = cur.isStreaming,
                mode = cur.mode,
                canSeeLastItem = listState.canSeeLastItem(effectiveViewportEndPx()),
                backgroundRefreshing = cur.isBackgroundRefreshing,
            )
        }.distinctUntilChanged().collect { signal ->
            val msgCount = signal.msgCount
            val lastRole = signal.lastRole
            val streaming = signal.streaming
            val mode = signal.mode
            val backgroundRefreshing = signal.backgroundRefreshing
            val curState = latestState.value
            val msgs = curState.messages
            if (msgs.isEmpty()) {
                prevMsgCount = 0
                prevStreaming = streaming
                prevBackgroundRefreshing = backgroundRefreshing
                lastKnownCanSeeLastItem = signal.canSeeLastItem
                return@collect
            }
            if (!latestInitialPresentationSettled.value) {
                prevMsgCount = msgCount
                prevStreaming = streaming
                prevBackgroundRefreshing = backgroundRefreshing
                lastKnownCanSeeLastItem = signal.canSeeLastItem
                return@collect
            }
            if (curState.isLoadingHistory || (curState.isBackgroundRefreshing && !curState.isStreaming)) {
                if (msgCount != prevMsgCount || streaming != prevStreaming) {
                    Log.d("GalScroll", "snapshotFlow: defer auto-follow during history refresh msgCnt=$msgCount(prev=$prevMsgCount) bg=${curState.isBackgroundRefreshing} loading=${curState.isLoadingHistory}")
                }
                prevMsgCount = msgCount
                prevStreaming = streaming
                prevBackgroundRefreshing = backgroundRefreshing
                lastKnownCanSeeLastItem = signal.canSeeLastItem
                return@collect
            }
            if (prevBackgroundRefreshing && !backgroundRefreshing) {
                if (msgCount != prevMsgCount || streaming != prevStreaming) {
                    Log.d(
                        "GalScroll",
                        "snapshotFlow: background refresh settled, hand off to history effect msgCnt=$msgCount(prev=$prevMsgCount)"
                    )
                }
                prevMsgCount = msgCount
                prevStreaming = streaming
                prevBackgroundRefreshing = backgroundRefreshing
                lastKnownCanSeeLastItem = signal.canSeeLastItem
                return@collect
            }
            val canSeeLastItemBeforeChange = lastKnownCanSeeLastItem
            val scrolling = listState.isScrollInProgress
            val isGalgame = mode.startsWith("galgame")
            val messagesAdded = (msgCount - prevMsgCount).coerceAtLeast(0)
            val newMessagesArrived = messagesAdded > 0
            val oldLastItemWasVisible = canSeeLastItemBeforeChange
            var keepFollowingAfterAppend = false
            val prevRole = if (msgs.size >= 2) msgs[msgs.size - 2].role else "N/A"
            fun scheduleNormalAssistantAutoFollow(reason: String, delayMs: Long = 200L) {
                normalAssistantAutoFollowJob?.cancel()
                normalAssistantAutoFollowJob = scrollScope.launch {
                    delay(delayMs)
                    if (shouldSkipAutoFollow()) {
                        Log.d("GalScroll", "  $reason: auto-follow SKIP (manual list interaction)")
                        return@launch
                    }
                    if (latestState.value.mode == "normal" && userScrolledUpState.value) {
                        Log.d("GalScroll", "  $reason: auto-follow SKIP (normal user now viewing history)")
                        return@launch
                    }
                    chatScrollToBottomAndRepair(
                        listState = listState,
                        lastMessageId = latestState.value.messages.lastOrNull()?.stableChatItemKey(),
                        naturalBottomPaddingPx = naturalBottomPaddingPx,
                        bottomAnchorTolerancePx = bottomAnchorTolerancePx,
                        reason = reason,
                        effectiveViewportEndOffsetPx = effectiveViewportEndPx(),
                        expectedItemCount = latestState.value.messages.size,
                        shouldSkipRepair = { shouldSkipAutoFollow() },
                    )
                }
            }
            if (msgCount != prevMsgCount || streaming != prevStreaming) {
                Log.d("GalScroll", "snapshotFlow: msgCnt=$msgCount(prev=$prevMsgCount) added=$messagesAdded lastRole=$lastRole prevRole=$prevRole streaming=$streaming(prev=$prevStreaming) near=${isNearBottom.value} oldLastVisible=$oldLastItemWasVisible userScrolledUp=${userScrolledUpState.value} suppressed=${listAutoFollowSuppressedState.value} scrolling=$scrolling mode=$mode")
            }
            when {
                // 任何模式：用户消息进入，瞬移到底部
                newMessagesArrived && lastRole == "user" -> {
                    listAutoFollowSuppressedState.value = false
                    normalAssistantAutoFollowJob?.cancel()
                    normalAssistantAutoFollowJob = null
                    userScrolledUpState.value = false
                    keepFollowingAfterAppend = true
                    Log.d("GalScroll", "  BRANCH[1]: user-sent -> scrollBy instant")
                    scrollScope.launch {
                        scrollToBottomForNewUserMessage("BRANCH[1]")
                    }
                }
                // galgame：用户发消息时，用户消息+空助手占位同时加入（lastRole=assistant），
                // Branch[1] 不会命中，需在此单独处理：瞬移到底部展示用户消息
                isGalgame && newMessagesArrived && lastRole == "assistant" &&
                    msgs.size >= 2 && msgs[msgs.size - 2].isUser() -> {
                    listAutoFollowSuppressedState.value = false
                    normalAssistantAutoFollowJob?.cancel()
                    normalAssistantAutoFollowJob = null
                    userScrolledUpState.value = false
                    keepFollowingAfterAppend = true
                    Log.d("GalScroll", "  BRANCH[2]: galgame-user-sent -> scrollBy instant")
                    scrollScope.launch {
                        scrollToBottomForNewUserMessage("BRANCH[2]")
                    }
                }
                // galgame：isStreaming true→false 表示角色响应到达。
                // 只有上一帧最后一条消息/打字动画仍可见时才接管视口；否则认为用户正在看历史。
                isGalgame && prevStreaming && !streaming -> {
                    val lastAssistant = msgs.lastOrNull { it.isAssistant() }
                    if (oldLastItemWasVisible && !userScrolledUpState.value && !shouldSkipAutoFollow()) {
                        Log.d("GalScroll", "  BRANCH[3]: galgame streaming-end -> scrollToLastAssistant lastId=${lastAssistant?.id?.take(8)} capsule=${capsuleHeightPxState.intValue}px")
                        scrollScope.launch {
                            delay(150)
                            Log.d("GalScroll", "  BRANCH[3]: after delay, executing scrollToLastAssistantInGalgame")
                            scrollToLastAssistantInGalgame(true)
                        }
                    } else {
                        Log.d(
                            "GalScroll",
                            "  BRANCH[3]: galgame streaming-end SKIP (oldLastVisible=$oldLastItemWasVisible userScrolledUp=${userScrolledUpState.value} suppressed=${listAutoFollowSuppressedState.value} touching=${listTouchActiveState.value})"
                        )
                    }
                }
                // normal：新 AI 消息进入（含打字延迟分段等连发场景），近底部时自动跟随
                newMessagesArrived && lastRole == "assistant" && !isGalgame -> {
                    if (oldLastItemWasVisible && !listAutoFollowSuppressedState.value) {
                        userScrolledUpState.value = false
                        keepFollowingAfterAppend = true
                        Log.d("GalScroll", "  BRANCH[4]: normal-assistant -> debounce follow added=$messagesAdded")
                        scheduleNormalAssistantAutoFollow("BRANCH[4]")
                    } else if (listAutoFollowSuppressedState.value) {
                        Log.d("GalScroll", "  BRANCH[4]: normal-assistant SKIP (auto-follow suppressed)")
                    } else {
                        Log.d("GalScroll", "  BRANCH[4]: normal-assistant SKIP (old last item was not visible)")
                    }
                }
                else -> {
                    if (msgCount != prevMsgCount || streaming != prevStreaming) {
                        Log.d("GalScroll", "  BRANCH[else]: no match | isGalgame=$isGalgame messagesAdded=$messagesAdded lastRole=$lastRole prevRole=$prevRole streaming=$streaming prevStreaming=$prevStreaming near=${isNearBottom.value} oldLastVisible=$oldLastItemWasVisible scrolling=$scrolling")
                    }
                }
            }
            prevMsgCount = msgCount
            prevStreaming = streaming
            prevBackgroundRefreshing = backgroundRefreshing
            lastKnownCanSeeLastItem = if (newMessagesArrived && keepFollowingAfterAppend) {
                true
            } else {
                signal.canSeeLastItem
            }
        }
    }

    // galgame deferred 机制已移除：
    // 原先通过 pendingGalgameAutoScrollAssistantIdState 在 deferred LaunchedEffect 中触发滚动，
    // 但由于 snapshotFlow collect 与 LaunchedEffect key 评估存在竞态，pendingId 写入后
    // LaunchedEffect 总在错误快照中读到 null，导致滚动永远无法触发。
    // 现改为在 snapshotFlow 直接监听 isStreaming true→false 事件触发滚动，无竞态。

    // ── 用户手动触摸滚动时更新 userScrolledUpState ──
    LaunchedEffect(listState) {
        snapshotFlow {
            val anchored = listState.canSeeLastItem(effectiveViewportEndPx())
            Triple(listTouchActiveState.value, listState.isScrollInProgress, anchored)
        }
            .distinctUntilChanged()
            .collect { (touching, scrolling, anchored) ->
                if (touching && scrolling) {
                    val newVal = !anchored
                    if (newVal != userScrolledUpState.value) Log.d("GalScroll", "userScrolledUp: ${userScrolledUpState.value} -> $newVal (touching+scrolling, anchored=$anchored mode=${latestState.value.mode})")
                    userScrolledUpState.value = newVal
                } else if (anchored) {
                    if (userScrolledUpState.value) {
                        Log.d("GalScroll", "userScrolledUp: true -> false (idle+anchored mode=${latestState.value.mode})")
                        userScrolledUpState.value = false
                    }
                    if (listAutoFollowSuppressedState.value) {
                        Log.d("GalScroll", "autoFollow suppression cleared (idle+anchored mode=${latestState.value.mode})")
                        listAutoFollowSuppressedState.value = false
                    }
                }
            }
    }

    LaunchedEffect(listState) {
        snapshotFlow { isNearBottom.value }
            .distinctUntilChanged()
            .collect { nearBottom ->
                Log.d("GalScroll", "isNearBottom: -> $nearBottom (scrollInProgress=${listState.isScrollInProgress} userScrolledUp=${userScrolledUpState.value} totalItems=${listState.layoutInfo.totalItemsCount})")
                if (nearBottom && userScrolledUpState.value) {
                    Log.d("GalScroll", "userScrolledUp: true -> false (isNearBottom toggled to true)")
                    userScrolledUpState.value = false
                }
                if (nearBottom && latestState.value.mode.startsWith("galgame") && listAutoFollowSuppressedState.value) {
                    Log.d("GalScroll", "autoFollow suppression cleared (galgame near bottom)")
                    listAutoFollowSuppressedState.value = false
                }
            }
    }
}
