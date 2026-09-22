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
    fun shouldPause(): Boolean = !latestReady.value || listTouchActiveState.value ||
        listAutoFollowSuppressedState.value || userScrolledUpState.value

    LaunchedEffect(listState, state.character?.id, state.conversationId) {
        val scrollScope = this
        var previous: NormalScrollSnapshot? = null
        var followJob: Job? = null
        var manualDrag = false
        var manualViewportObserved = false
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
            // A resume refresh can pause presentation while the user is already
            // dragging. Remember that intent before the readiness gate; otherwise
            // suppression survives but the gesture that can release it is lost.
            if (signal.touching && signal.suppressed && !manualDrag) {
                manualDrag = true
                manualViewportObserved = false
            }
            if (!signal.ready || signal.tailKey == null) {
                followJob?.cancel()
                pendingFollow = false
                return@collect
            }
            if (!initialized) {
                initialized = true
                userScrolledUpState.value = userScrolledUpState.value || !signal.nearBottom
                pendingFollow = before?.tailKey == null
            }

            // Pointer input marks a drag as suppressed. Track actual viewport movement, not
            // last-item visibility, so incoming content during a held touch cannot change intent.
            val viewportMoved = before != null &&
                (signal.firstKey != before.firstKey || signal.firstOffset != before.firstOffset)
            val viewportResized = before != null &&
                (signal.viewportEnd != before.viewportEnd || signal.effectiveEnd != before.effectiveEnd ||
                    signal.bottomPadding != before.bottomPadding)
            if (manualDrag && viewportMoved) {
                manualViewportObserved = true
                // Being within the last two rows does not mean the user wants to
                // follow. A deliberate drag away from the actual bottom wins
                // over every later bubble, even while the tail is still visible.
                // A rapid return gesture can finish before the final tail layout is
                // measured against the input inset. The scroll boundary has already
                // settled in that frame, though, so use it as the authoritative
                // "returned to bottom" signal instead of leaving suppression stuck.
                val returnedToBottom = signal.atBottom || !signal.canScrollForward
                userScrolledUpState.value = !returnedToBottom
                if (returnedToBottom) listAutoFollowSuppressedState.value = false
                if (userScrolledUpState.value) pendingFollow = false
            }
            if (manualDrag && !signal.touching && !signal.scrolling) {
                // The final layout may settle after the last offset change, or a
                // forward drag may already be clamped at the physical bottom.
                // Neither produces viewportMoved, but both restore live follow.
                val returnedToBottom = signal.atBottom || !signal.canScrollForward
                if (!manualViewportObserved || returnedToBottom) {
                    userScrolledUpState.value = !returnedToBottom
                    if (!returnedToBottom) pendingFollow = false
                }
                manualDrag = false
                if (!userScrolledUpState.value) listAutoFollowSuppressedState.value = false
            }

            // Sending a new user message explicitly returns to the live conversation. A
            // history prepend or deletion does not count as a newly sent message.
            val appended = signal.tailKey != before?.tailKey && before?.tailKey != null &&
                latestState.value.messages.any { it.stableChatItemKey() == before.tailKey }
            if (appended && signal.tailRole == "user") {
                userScrolledUpState.value = false
                listAutoFollowSuppressedState.value = false
            }
            // Closing a quick-message panel releases its padding and reverses the
            // panel's earlier scroll compensation. That may move an already visible
            // sent message below the input bar after the first follow has completed.
            // Recheck on geometry changes even if the viewport moved at the same time;
            // ordinary jumps to quoted history still preserve their chosen position.
            if (appended || (!manualDrag && (viewportResized ||
                    (!viewportMoved && before?.atBottom == true && !signal.atBottom)))) {
                pendingFollow = !userScrolledUpState.value
            }
            if (signal.atBottom || !signal.canScrollForward) pendingFollow = false
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
