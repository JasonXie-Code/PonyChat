package top.ponychat.webview.ui.creation

import androidx.compose.animation.core.animate
import androidx.compose.animation.core.tween
import androidx.compose.foundation.MutatePriority
import androidx.compose.foundation.lazy.LazyListState

/** Finish the complete 500ms scroll even if a user touches or drags the list. */
internal suspend fun alignCreationReply(list: LazyListState, index: Int) {
    list.scroll(MutatePriority.PreventUserInput) {
        var previousProgress = 0f
        animate(0f, 1f, animationSpec = tween(500)) { progress, _ ->
            val info = list.layoutInfo
            val target = info.visibleItemsInfo.firstOrNull { it.index == index }
            val first = info.visibleItemsInfo.firstOrNull()
            val average = info.visibleItemsInfo.map { it.size }.average().takeIf { it.isFinite() }?.toFloat() ?: 100f
            val remaining = target?.offset?.toFloat()
                ?: ((index - (first?.index ?: 0)) * (average + info.mainAxisItemSpacing) + (first?.offset ?: 0))
            val fraction = ((progress - previousProgress) / (1f - previousProgress).coerceAtLeast(.001f)).coerceIn(0f, 1f)
            scrollBy(remaining * fraction)
            previousProgress = progress
        }
    }
    // AndroidView replacement and footer measurement can arrive after the last animation frame.
    repeat(3) {
        androidx.compose.runtime.withFrameNanos { }
        list.scrollToItem(index)
    }
}
