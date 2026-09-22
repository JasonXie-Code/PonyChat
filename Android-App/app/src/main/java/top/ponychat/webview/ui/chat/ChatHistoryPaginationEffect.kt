package top.ponychat.webview.ui.chat

import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember

/** Request older messages without taking scroll ownership away from the reader. */
@Composable
internal fun ChatHistoryPaginationEffect(
    listState: LazyListState,
    state: ChatUiState,
    onLoadMore: () -> Unit,
) {
    val firstVisibleMessageKey by remember(listState) {
        derivedStateOf {
            listState.layoutInfo.visibleItemsInfo.firstOrNull {
                it.key != "__load_more_indicator__"
            }?.key
        }
    }
    val headKey = state.messages.firstOrNull()?.stableChatItemKey()
    LaunchedEffect(listState, state.conversationId, firstVisibleMessageKey, headKey) {
        // Resolve against the current data, not an index from the previous layout.
        // Loading-row insertion/removal alone must not start another request.
        val messageIndex = state.messages.indexOfFirst { it.stableChatItemKey() == firstVisibleMessageKey }
        if (messageIndex in 0..2 && state.hasMoreHistory &&
            !state.isLoadingHistory && !state.isLoadingMoreHistory && !state.mode.startsWith("galgame")) {
            onLoadMore()
        }
    }
    // LazyColumn's stable message keys preserve the CURRENT visible item and offset
    // during prepends and loading-row changes, including an ongoing fling. Restoring
    // an anchor captured before the request would rewind later user movement and
    // scrollToItem would also cancel the user's scroll, even when the request failed.
}
