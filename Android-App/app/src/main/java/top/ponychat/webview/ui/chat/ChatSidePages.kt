package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import kotlin.math.abs

internal const val CHARACTER_HOME_PAGE = 0
internal const val CHAT_PAGE = 1

/** Both side pages share the chat header and slide the composer out of view. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun rememberChatSidePager(
    enabled: Boolean,
    dismissInput: () -> Unit,
): PagerState {
    val pager = rememberPagerState(initialPage = CHAT_PAGE, pageCount = { 3 })
    val scope = rememberCoroutineScope()
    LaunchedEffect(enabled) {
        if (!enabled) pager.scrollToPage(CHAT_PAGE)
    }
    LaunchedEffect(enabled, pager.currentPage) {
        if (enabled && pager.currentPage != CHAT_PAGE) dismissInput()
    }
    BackHandler(enabled = enabled &&
        (pager.currentPage != CHAT_PAGE || abs(pager.currentPageOffsetFraction) > 0.01f)
    ) {
        scope.launch { pager.animateScrollToPage(CHAT_PAGE) }
    }
    return pager
}
