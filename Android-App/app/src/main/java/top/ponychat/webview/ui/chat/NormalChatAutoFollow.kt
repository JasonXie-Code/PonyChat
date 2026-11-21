package top.ponychat.webview.ui.chat

import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

private data class NormalScrollSnapshot(
    val ready: Boolean,
    val tailKey: String?,
    val tailRole: String?,
    val viewportEnd: Int,
    val effectiveEnd: Int,
    val bottomPadding: Int,
    val firstKey: Any?,
    val firstIndex: Int,
    val tailSize: Int?,
    val firstOffset: Int,
    val atBottom: Boolean,
    val nearBottom: Boolean,
    val canScrollForward: Boolean,
    val touching: Boolean,
    val scrolling: Boolean,
    val suppressed: Boolean,
    val readingHistory: Boolean,
    val completedScrolls: Int,
)

/**
 * Normal replies arrive as separately paced bubbles. Keep the reader's follow intent across
 * appends and remeasurement; a bubble moving below the viewport is not a user scroll.
 */
@Composable
internal fun NormalChatAutoFollow(
    listState: LazyListState,
    state: ChatUiState,
    isNearBottom: State<Boolean>,
    userScrolledUpState: MutableState<Boolean>,
    listTouchActiveState: MutableState<Boolean>,
    listAutoFollowSuppressedState: MutableState<Boolean>,
    listEffectiveViewportEndPxState: MutableIntState,
    naturalBottomPaddingPx: Int,
    bottomAnchorTolerancePx: Float,
    initialPresentationSettled: Boolean,
) {
    val latestState = rememberUpdatedState(state)
    val latestReady = rememberUpdatedState(initialPresentationSettled && !state.isLoadingHistory)
    fun effectiveEnd(): Int? = listEffectiveViewportEndPxState.intValue.takeIf { it in 1 until Int.MAX_VALUE }
    fun shouldPause(): Boolean = !latestReady.value || userScrolledUpState.value

    LaunchedEffect(listState, state.character?.id, state.conversationId) {
        val scrollScope = this
        var previous: NormalScrollSnapshot? = null
        var followJob: Job? = null
        var pendingFollow = false
        var initialized = false
        val completedScrolls = mutableIntStateOf(0)
        snapshotFlow {
            val current = latestState.value
            val info = listState.layoutInfo
            val tail = current.messages.lastOrNull()
            val visibleTail = info.visibleItemsInfo.lastOrNull()
                ?.takeIf { it.key == tail?.stableChatItemKey() }
            val end = effectiveEnd()?.coerceIn(info.viewportStartOffset, info.viewportEndOffset)
                ?: info.viewportEndOffset
            val inset = if (effectiveEnd() != null) naturalBottomPaddingPx
                else maxOf(naturalBottomPaddingPx, info.afterContentPadding)
            NormalScrollSnapshot(
                ready = latestReady.value,
                tailKey = tail?.stableChatItemKey(),
                tailRole = tail?.role,
                viewportEnd = info.viewportEndOffset,
                effectiveEnd = end,
                bottomPadding = info.afterContentPadding,
                firstKey = info.visibleItemsInfo.firstOrNull()?.key,
                firstIndex = listState.firstVisibleItemIndex,
                tailSize = visibleTail?.size,
                firstOffset = listState.firstVisibleItemScrollOffset,
                atBottom = visibleTail != null &&
                    visibleTail.offset + visibleTail.size <= end - inset + bottomAnchorTolerancePx,
                nearBottom = isNearBottom.value,
                canScrollForward = listState.canScrollForward,
                touching = listTouchActiveState.value,
                scrolling = listState.isScrollInProgress,
                suppressed = listAutoFollowSuppressedState.value,
                readingHistory = userScrolledUpState.value,
                completedScrolls = completedScrolls.intValue,
            )
        }.collect { signal ->
            val before = previous
            previous = signal
            val viewportMoved = before != null &&
                (signal.firstKey != before.firstKey || signal.firstOffset != before.firstOffset)
            val viewportResized = before != null &&
                (signal.viewportEnd != before.viewportEnd || signal.effectiveEnd != before.effectiveEnd ||
                    signal.bottomPadding != before.bottomPadding)
            // Touch alone never pauses following. Only a viewport move beyond the tail
            // region changes reading position; appended content cannot revoke follow intent.
            val movingAway = before != null && (signal.firstIndex < before.firstIndex ||
                (signal.firstKey == before.firstKey && signal.firstOffset < before.firstOffset))
            if (viewportMoved && signal.tailKey == before?.tailKey && !viewportResized &&
                (signal.tailSize == before?.tailSize || signal.touching || movingAway) &&
                ((signal.touching && movingAway) || (!pendingFollow && followJob?.isActive != true))) {
                userScrolledUpState.value = !signal.nearBottom
                if (userScrolledUpState.value) pendingFollow = false
            }
            if (signal.nearBottom && (viewportMoved ||
                    (signal.tailSize != null && !signal.canScrollForward))) {
                userScrolledUpState.value = false
            }
            // Sending a new user message explicitly returns to the live conversation. A
            // history prepend or deletion does not count as a newly sent message.
            val appended = signal.tailKey != before?.tailKey && before?.tailKey != null &&
                latestState.value.messages.any { it.stableChatItemKey() == before.tailKey }
            if (appended && signal.tailRole == "user") {
                userScrolledUpState.value = false
                listAutoFollowSuppressedState.value = false
            }
            if (appended && !userScrolledUpState.value) pendingFollow = true
            listAutoFollowSuppressedState.value = false
            if (!signal.ready || signal.tailKey == null) {
                followJob?.cancel()
                return@collect
            }
            if (!initialized) {
                initialized = true
                userScrolledUpState.value = !signal.nearBottom
                pendingFollow = before?.tailKey == null
            }

            // Closing a quick-message panel releases its padding and reverses the
            // panel's earlier scroll compensation. That may move an already visible
            // sent message below the input bar after the first follow has completed.
            // Recheck on geometry changes even if the viewport moved at the same time;
            // ordinary jumps to quoted history still preserve their chosen position.
            val tailGrew = signal.tailKey == before?.tailKey && signal.tailSize != null &&
                before.tailSize != null && signal.tailSize > before.tailSize
            if (appended || viewportResized || tailGrew ||
                    (!viewportMoved && before?.atBottom == true && !signal.atBottom)) {
                pendingFollow = !userScrolledUpState.value
            }
            if (signal.atBottom || (signal.tailSize != null && !signal.canScrollForward)) pendingFollow = false
            if (shouldPause()) {
                followJob?.cancel()
                return@collect
            }
            if (pendingFollow && !signal.atBottom && followJob?.isActive != true) {
                followJob = scrollScope.launch {
                    try {
                        chatScrollToBottomAndRepair(
                            listState = listState,
                            lastMessageId = latestState.value.messages.lastOrNull()?.stableChatItemKey(),
                            naturalBottomPaddingPx = naturalBottomPaddingPx,
                            bottomAnchorTolerancePx = bottomAnchorTolerancePx,
                            reason = "normal-follow",
                            effectiveViewportEndOffsetPx = effectiveEnd(),
                            expectedItemCount = latestState.value.messages.size,
                            shouldSkipRepair = { shouldPause() },
                        )
                    } finally {
                        followJob = null
                        // A second bubble can arrive while the first scroll is repairing
                        // its anchor. Re-evaluate that pending append after the job ends.
                        completedScrolls.intValue++
                    }
                }
            }
        }
    }
}
