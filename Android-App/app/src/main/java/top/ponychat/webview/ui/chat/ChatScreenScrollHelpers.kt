package top.ponychat.webview.ui.chat

import android.util.Log
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.lazy.LazyListState
import kotlinx.coroutines.delay
import top.ponychat.webview.data.model.Message
import kotlin.math.abs
import kotlin.math.max

internal fun LazyListState.canSeeLastItem(effectiveViewportEndOffsetPx: Int? = null): Boolean {
    val info = layoutInfo
    val lastItemIndex = info.totalItemsCount - 1
    if (lastItemIndex < 0) return true
    val effectiveEnd = effectiveViewportEndOffsetPx
        ?.coerceIn(info.viewportStartOffset, info.viewportEndOffset)
        ?: info.viewportEndOffset
    return info.visibleItemsInfo.any { item ->
        item.index == lastItemIndex &&
            item.offset < effectiveEnd &&
            item.offset + item.size > info.viewportStartOffset
    }
}

internal suspend fun chatRepairLastMessageBottomAnchor(
    listState: LazyListState,
    lastMessageId: String?,
    naturalBottomPaddingPx: Int,
    bottomAnchorTolerancePx: Float,
    reason: String,
    effectiveViewportEndOffsetPx: Int? = null,
    maxPasses: Int = 4,
    settleDelayMs: Long = 32L,
    shouldSkip: () -> Boolean = { false },
): Boolean {
    if (lastMessageId == null || shouldSkip()) return false

    var repaired = false
    repeat(maxPasses) { pass ->
        if (settleDelayMs > 0L) delay(settleDelayMs)
        if (shouldSkip()) return repaired

        val layoutInfo = listState.layoutInfo
        val lastListIndex = layoutInfo.totalItemsCount - 1
        if (lastListIndex < 0) return repaired

        val lastVisible = layoutInfo.visibleItemsInfo.maxByOrNull { it.index } ?: return repaired
        if (lastVisible.index != lastListIndex) {
            if (effectiveViewportEndOffsetPx == null) return repaired
            listState.scrollToItem(lastListIndex, 0)
            Log.d(
                "ChatBottomScroll",
                "repair[$reason] pass=$pass snapToLast index=$lastListIndex lastVisible=${lastVisible.index} lastId=${lastMessageId.take(8)}"
            )
            repaired = true
            return@repeat
        }
        if (listState.firstVisibleItemIndex == 0 && listState.firstVisibleItemScrollOffset == 0) {
            return repaired
        }

        val lastVisibleBottomPx = lastVisible.offset + lastVisible.size
        val effectiveEndPx = effectiveViewportEndOffsetPx
            ?.coerceIn(layoutInfo.viewportStartOffset, layoutInfo.viewportEndOffset)
            ?: layoutInfo.viewportEndOffset
        val desiredBottomInsetPx = if (effectiveViewportEndOffsetPx != null) {
            naturalBottomPaddingPx
        } else {
            max(naturalBottomPaddingPx, layoutInfo.afterContentPadding)
        }
        val desiredBottomPx = effectiveEndPx - desiredBottomInsetPx
        val gapPx = desiredBottomPx - lastVisibleBottomPx
        if (abs(gapPx) <= bottomAnchorTolerancePx) return repaired

        val consumedPx = listState.scrollBy(-gapPx.toFloat())
        Log.d(
            "ChatBottomScroll",
            "repair[$reason] pass=$pass gap=$gapPx effectiveEnd=$effectiveEndPx inset=$desiredBottomInsetPx consumed=${consumedPx.toInt()} lastId=${lastMessageId.take(8)}"
        )
        if (abs(consumedPx) <= 0.5f) return repaired
        repaired = true
    }
    return repaired
}

internal suspend fun chatScrollToBottomAndRepair(
    listState: LazyListState,
    lastMessageId: String?,
    naturalBottomPaddingPx: Int,
    bottomAnchorTolerancePx: Float,
    reason: String,
    animated: Boolean = false,
    settleDelayMs: Long = 32L,
    effectiveViewportEndOffsetPx: Int? = null,
    expectedItemCount: Int? = null,
    shouldSkipRepair: () -> Boolean = { false },
) {
    if (shouldSkipRepair()) return
    if (expectedItemCount != null) {
        var waitedMs = 0L
        while (listState.layoutInfo.totalItemsCount < expectedItemCount && waitedMs < 500L) {
            if (shouldSkipRepair()) return
            delay(16L)
            waitedMs += 16L
        }
    }
    if (settleDelayMs > 0L) delay(settleDelayMs)
    if (shouldSkipRepair()) return
    if (animated) {
        listState.animateScrollBy(100_000f)
        if (settleDelayMs > 0L) delay(settleDelayMs)
    }
    if (shouldSkipRepair()) return
    val consumedPx = listState.scrollBy(100_000f)
    val layoutInfo = listState.layoutInfo
    val visibleRange = layoutInfo.visibleItemsInfo.let { items ->
        "${items.firstOrNull()?.index}-${items.lastOrNull()?.index}"
    }
    Log.d(
        "ChatBottomScroll",
        "toBottom[$reason] consumed=${consumedPx.toInt()} " +
            "items=${layoutInfo.totalItemsCount} expected=$expectedItemCount " +
            "visible=$visibleRange viewport=${layoutInfo.viewportStartOffset}-${layoutInfo.viewportEndOffset} " +
            "afterPad=${layoutInfo.afterContentPadding} effectiveEnd=$effectiveViewportEndOffsetPx " +
            "lastId=${lastMessageId?.take(8)}"
    )
    chatRepairLastMessageBottomAnchor(
        listState = listState,
        lastMessageId = lastMessageId,
        naturalBottomPaddingPx = naturalBottomPaddingPx,
        bottomAnchorTolerancePx = bottomAnchorTolerancePx,
        reason = reason,
        effectiveViewportEndOffsetPx = effectiveViewportEndOffsetPx,
        settleDelayMs = settleDelayMs,
        shouldSkip = shouldSkipRepair,
    )
}

internal suspend fun chatScrollToLastAssistantInGalgame(
    listState: LazyListState,
    messages: List<Message>,
    topAnchorPx: Int,
    awaitImeNotAnimating: suspend () -> Unit,
    animated: Boolean = true,
) {
    awaitImeNotAnimating()
    val lastAssistantIdx = messages.indexOfLast { it.isAssistant() }
    val lastAssistantKey = messages.getOrNull(lastAssistantIdx)?.stableChatItemKey()
    val totalItems = listState.layoutInfo.totalItemsCount
    val visibleItems = listState.layoutInfo.visibleItemsInfo.map { it.index }
    Log.d("GalScroll", "scrollToLastAssistant: ENTER animated=$animated lastAssistantIdx=$lastAssistantIdx topAnchor=${topAnchorPx}px totalItems=$totalItems visibleRange=${visibleItems.firstOrNull()}-${visibleItems.lastOrNull()}")
    if (lastAssistantIdx < 0) {
        Log.d("GalScroll", "scrollToLastAssistant: SKIP no assistant (msgSize=${messages.size})")
        return
    }

    suspend fun repairTopAnchor(reason: String) {
        repeat(4) { pass ->
            delay(32)
            val itemInfo = listState.layoutInfo.visibleItemsInfo.find { item ->
                item.key == lastAssistantKey || item.index == lastAssistantIdx
            } ?: return@repeat
            val delta = (itemInfo.offset - topAnchorPx).toFloat()
            if (abs(delta) <= 1f) return
            val consumed = listState.scrollBy(delta)
            Log.d(
                "GalScroll",
                "scrollToLastAssistant: repair[$reason] pass=$pass offset=${itemInfo.offset} target=$topAnchorPx delta=${delta.toInt()} consumed=${consumed.toInt()}"
            )
            if (abs(consumed) <= 0.5f) return
        }
    }

    if (!animated) {
        Log.d("GalScroll", "scrollToLastAssistant: instant snap idx=$lastAssistantIdx topAnchor=${topAnchorPx}px")
        listState.scrollToItem(lastAssistantIdx, -topAnchorPx)
        repairTopAnchor("instant")
        Log.d("GalScroll", "scrollToLastAssistant: instant snap DONE")
        return
    }
    val itemInfo = listState.layoutInfo.visibleItemsInfo.find { item ->
        item.key == lastAssistantKey || item.index == lastAssistantIdx
    }
    if (itemInfo != null) {
        val targetY = topAnchorPx
        val delta = (itemInfo.offset - targetY).toFloat()
        Log.d("GalScroll", "scrollToLastAssistant: item in viewport offset=${itemInfo.offset} size=${itemInfo.size} targetY=$targetY delta=${delta.toInt()}px")
        if (abs(delta) > 1f) {
            listState.animateScrollBy(delta, tween(400, easing = FastOutSlowInEasing))
            repairTopAnchor("animated")
            Log.d("GalScroll", "scrollToLastAssistant: animateScrollBy DONE")
        } else {
            Log.d("GalScroll", "scrollToLastAssistant: SKIP delta<=1 already aligned")
        }
    } else {
        Log.d("GalScroll", "scrollToLastAssistant: item NOT in viewport -> fallback snap idx=$lastAssistantIdx topAnchor=${topAnchorPx}px")
        listState.scrollToItem(lastAssistantIdx, -topAnchorPx)
        repairTopAnchor("fallback")
        Log.d("GalScroll", "scrollToLastAssistant: fallback snap DONE")
    }
}
