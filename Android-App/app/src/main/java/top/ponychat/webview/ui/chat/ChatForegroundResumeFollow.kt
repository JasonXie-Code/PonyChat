package top.ponychat.webview.ui.chat

import android.util.Log
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.rememberUpdatedState
import kotlinx.coroutines.delay

internal data class ForegroundResumeAutoFollowSnapshot(
    val characterId: String,
    val mode: String,
    val conversationId: String,
    val messageCount: Int,
    val lastMessageKey: String?,
    val wasLastMessageVisible: Boolean,
    val pausedAtMs: Long,
    val resumeRequestedAtMs: Long = 0L,
)

/** A resume catch-up is revocable: a reader gesture always owns the viewport. */
@Composable
internal fun ChatForegroundResumeFollow(
    listState: LazyListState,
    state: ChatUiState,
    activeCharId: String,
    activeMode: String,
    activeConversationId: String,
    foregroundResumeAutoFollowSnapshotState: MutableState<ForegroundResumeAutoFollowSnapshot?>,
    foregroundResumeAutoFollowTickState: MutableIntState,
    listTouchActiveState: MutableState<Boolean>,
    listAutoFollowSuppressedState: MutableState<Boolean>,
    userScrolledUpState: MutableState<Boolean>,
    showLoadingOverlay: Boolean,
    scrollNaturalBottomPaddingPx: Int,
    scrollBottomAnchorTolerancePx: Float,
    currentLifecycleEffectiveViewportEndPx: () -> Int?,
    isForeground: () -> Boolean,
    awaitImeNotAnimating: suspend () -> Unit,
    scrollToLastAssistantInGalgame: suspend (Boolean) -> Unit,
) {
    val latestStateForLifecycle = rememberUpdatedState(state)
    val latestIsForeground = rememberUpdatedState(isForeground)
    fun shouldCancel() = listTouchActiveState.value || listAutoFollowSuppressedState.value ||
        userScrolledUpState.value || !latestIsForeground.value()
    fun messageTailChangedSince(snapshot: ForegroundResumeAutoFollowSnapshot, current: ChatUiState): Boolean =
        current.messages.size > snapshot.messageCount ||
            (current.messages.size == snapshot.messageCount &&
                current.messages.lastOrNull()?.stableChatItemKey() != snapshot.lastMessageKey)

    LaunchedEffect(
        foregroundResumeAutoFollowTickState.intValue,
        listTouchActiveState.value,
        listAutoFollowSuppressedState.value,
        userScrolledUpState.value,
        state.messages.size,
        state.messages.lastOrNull()?.stableChatItemKey(),
        state.isLoadingHistory,
        state.isBackgroundRefreshing,
        showLoadingOverlay,
    ) {
        val snapshot = foregroundResumeAutoFollowSnapshotState.value ?: return@LaunchedEffect
        if (snapshot.resumeRequestedAtMs <= 0L || !snapshot.wasLastMessageVisible) return@LaunchedEffect
        if (snapshot.characterId != activeCharId || snapshot.mode != activeMode) {
            foregroundResumeAutoFollowSnapshotState.value = null
            return@LaunchedEffect
        }
        if (
            snapshot.conversationId.isNotBlank() &&
            activeConversationId.isNotBlank() &&
            snapshot.conversationId != activeConversationId
        ) {
            foregroundResumeAutoFollowSnapshotState.value = null
            return@LaunchedEffect
        }
        if (shouldCancel()) {
            foregroundResumeAutoFollowSnapshotState.value = null
            return@LaunchedEffect
        }
        if (showLoadingOverlay || state.isLoadingHistory || state.isBackgroundRefreshing) {
            return@LaunchedEffect
        }
        if (!messageTailChangedSince(snapshot, state)) {
            delay(3500L)
            val latest = latestStateForLifecycle.value
            val stillPending = foregroundResumeAutoFollowSnapshotState.value
            if (
                stillPending == snapshot &&
                !latest.isLoadingHistory &&
                !latest.isBackgroundRefreshing &&
                !messageTailChangedSince(snapshot, latest)
            ) {
                foregroundResumeAutoFollowSnapshotState.value = null
                Log.d("GalScroll", "foreground-resume follow expired without tail change")
            }
            return@LaunchedEffect
        }
        if (listTouchActiveState.value) {
            return@LaunchedEffect
        }

        foregroundResumeAutoFollowSnapshotState.value = null
        awaitImeNotAnimating()
        if (shouldCancel()) return@LaunchedEffect
        if (activeMode.startsWith("galgame")) {
            scrollToLastAssistantInGalgame(false)
        } else {
            chatScrollToBottomAndRepair(
                listState = listState,
                lastMessageId = state.messages.lastOrNull()?.stableChatItemKey(),
                naturalBottomPaddingPx = scrollNaturalBottomPaddingPx,
                bottomAnchorTolerancePx = scrollBottomAnchorTolerancePx,
                reason = "foreground-resume-new-message",
                effectiveViewportEndOffsetPx = currentLifecycleEffectiveViewportEndPx(),
                expectedItemCount = state.messages.size,
                shouldSkipRepair = { shouldCancel() },
            )
        }
        Log.d(
            "GalScroll",
            "foreground-resume follow consumed mode=$activeMode count=${snapshot.messageCount}->${state.messages.size}"
        )
    }

}
