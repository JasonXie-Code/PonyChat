package top.ponychat.webview.ui.chat

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import coil.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import top.ponychat.webview.ui.common.PonyPromptBubble
import kotlinx.coroutines.CoroutineScope

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun ChatScreenImagePreviewOverlay(
    previewImageUrl: String?,
    previewImages: List<String>,
    previewIndex: Int,
    onDismiss: () -> Unit,
    coroutineScope: CoroutineScope,
    context: Context,
) {
    if (previewImageUrl == null) return

    val pagerState = rememberPagerState(
        initialPage = previewIndex,
        pageCount = { previewImages.size.coerceAtLeast(1) }
    )
    // 使用 State 对象而非委托属性：在 graphicsLayer/pointerInput 中直接读 .floatValue/.value，
    // 避免在 Composition 阶段产生读取依赖，scale/offset 变化只触发 GPU 层重绘而非整体重组。
    val previewScaleState  = remember { mutableFloatStateOf(1f) }
    val previewOffsetState = remember { mutableStateOf(Offset.Zero) }
    var previewBoxSize by remember { mutableStateOf(Size.Zero) }
    var isSavingPreview by remember { mutableStateOf(false) }
    var previewPromptMessage by remember { mutableStateOf<String?>(null) }
    var previewPromptNonce by remember { mutableIntStateOf(0) }

    // derivedStateOf：只在跨越 1.01 阈值时才触发 HorizontalPager 重组，
    // 捏合过程中 scale 连续变化不会反复重组整个 Pager。
    val userScrollEnabled by remember { derivedStateOf { previewScaleState.floatValue <= 1.01f } }

    fun clampPreviewOffset(raw: Offset, scale: Float, extra: Float = 0f): Offset {
        if (scale <= 1f) return Offset.Zero
        val maxX = (previewBoxSize.width  * (scale - 1f) / 2f).coerceAtLeast(0f) + extra
        val maxY = (previewBoxSize.height * (scale - 1f) / 2f).coerceAtLeast(0f) + extra
        return Offset(raw.x.coerceIn(-maxX, maxX), raw.y.coerceIn(-maxY, maxY))
    }

    LaunchedEffect(pagerState.currentPage) {
        previewScaleState.floatValue  = 1f
        previewOffsetState.value = Offset.Zero
    }

    val showPreviewPrompt: (String, Boolean) -> Unit = remember(coroutineScope) {
        { msg, autoDismiss ->
            previewPromptMessage = msg
            previewPromptNonce += 1
            val currentNonce = previewPromptNonce
            if (autoDismiss) {
                coroutineScope.launch {
                    delay(1600)
                    if (previewPromptNonce == currentNonce) {
                        previewPromptMessage = null
                    }
                }
            }
        }
    }

    val saveCurrentPreview: () -> Unit = save@{
        if (isSavingPreview) return@save
        val target = if (previewImages.isNotEmpty()) previewImages.getOrNull(pagerState.currentPage) else previewImageUrl
        if (!target.isNullOrBlank()) {
            coroutineScope.launch {
                isSavingPreview = true
                try {
                    showPreviewPrompt("保存中...", false)
                    val ok = savePreviewImageToGallery(context, target)
                    showPreviewPrompt(if (ok) "已保存到相册" else "保存失败，请稍后重试", true)
                } finally { isSavingPreview = false }
            }
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnBackPress = true, dismissOnClickOutside = true)
    ) {
        Surface(color = Color.Black.copy(alpha = 0.92f), modifier = Modifier.fillMaxSize()) {
            Box(modifier = Modifier.fillMaxSize().padding(8.dp)) {
                if (previewImages.isEmpty()) {
                    AsyncImage(
                        model = rememberChatImageRequest(previewImageUrl),
                        contentDescription = "图片预览",
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Fit
                    )
                } else {
                    HorizontalPager(
                        state = pagerState,
                        userScrollEnabled = userScrollEnabled,   // 只在跨阈值时重组
                        modifier = Modifier.fillMaxSize()
                    ) { page ->
                        val reboundPx = with(LocalDensity.current) { 28.dp.toPx() }
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .onGloballyPositioned {
                                    previewBoxSize = Size(it.size.width.toFloat(), it.size.height.toFloat())
                                }
                        ) {
                            // ── 图片层：graphicsLayer 直接读 State.value，只 invalidate Draw，不触发 Composition ──
                            AsyncImage(
                                model = rememberChatImageRequest(previewImages[page]),
                                contentDescription = "图片预览 ${page + 1}",
                                contentScale = ContentScale.Fit,
                                modifier = Modifier
                                    .fillMaxSize()
                                    .graphicsLayer {
                                        scaleX       = previewScaleState.floatValue
                                        scaleY       = previewScaleState.floatValue
                                        translationX = previewOffsetState.value.x
                                        translationY = previewOffsetState.value.y
                                    }
                            )
                            // ── 手势捕获层：覆盖整个图片区域，单一 pointerInput(Unit) 处理全部手势 ──
                            // 核心设计：
                            //   • 单指 scale=1 → 不消费 → HorizontalPager 接管翻页
                            //   • 单指 scale>1 或多指转单指 → 消费 → 平移图片（1:1 跟手）
                            //   • 双指捏合 → 消费 → 实时缩放+平移（无黑屏，因为不重组）
                            //   • 双击 → 平滑动画缩放（消除闪烁）
                            //   • 长按 → 保存图片
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .pointerInput(Unit) {
                                        var lastTapMs  = 0L
                                        var lastTapPos = Offset.Zero

                                        awaitEachGesture {
                                            val touchSlop   = viewConfiguration.touchSlop
                                            // 等待第一个手指按下（不消费，等效于 awaitFirstDown(requireUnconsumed = false)）
                                            var initEvt = awaitPointerEvent()
                                            while (initEvt.changes.none { it.pressed }) {
                                                initEvt = awaitPointerEvent()
                                            }
                                            val firstDown = initEvt.changes.first { it.pressed }
                                            val downPos   = firstDown.position
                                            var didMove     = false
                                            var isMultiTouch = false
                                            var prevFocus   = downPos
                                            var prevSpan    = 0f
                                            val lpDeadline  = System.currentTimeMillis() + 500L

                                            eventLoop@ while (true) {
                                                val remaining = lpDeadline - System.currentTimeMillis()
                                                // 未移动时使用超时等待，超时即触发长按
                                                val event = if (!didMove && !isMultiTouch && remaining > 0) {
                                                    withTimeoutOrNull(remaining) { awaitPointerEvent() }
                                                } else {
                                                    awaitPointerEvent()
                                                }

                                                if (event == null) {
                                                    // ── 长按 ──
                                                    saveCurrentPreview()
                                                    while (true) {
                                                        val e = awaitPointerEvent()
                                                        e.changes.forEach { it.consume() }
                                                        if (e.changes.none { it.pressed }) break
                                                    }
                                                    break@eventLoop
                                                }

                                                val pressed = event.changes.filter { it.pressed }

                                                when {
                                                    // ── 所有手指抬起 ──
                                                    pressed.isEmpty() -> {
                                                        if (!didMove) {
                                                            // 判断双击
                                                            val nowMs = System.currentTimeMillis()
                                                            val timeSince = nowMs - lastTapMs
                                                            val distFromLast = (downPos - lastTapPos).getDistance()
                                                            if (timeSince < 300L && distFromLast < touchSlop * 4) {
                                                                // ── 双击：平滑动画缩放 ──
                                                                lastTapMs = 0L
                                                                val startScale = previewScaleState.floatValue
                                                                val targetScale = if (startScale > 1.1f) 1f else 2.5f
                                                                val startOff = previewOffsetState.value
                                                                coroutineScope.launch {
                                                                    val anim = Animatable(0f)
                                                                    anim.animateTo(1f, tween(180, easing = FastOutSlowInEasing)) {
                                                                        previewScaleState.floatValue = startScale + (targetScale - startScale) * value
                                                                        previewOffsetState.value = Offset(
                                                                            startOff.x * (1f - value),
                                                                            startOff.y * (1f - value)
                                                                        )
                                                                    }
                                                                }
                                                            } else {
                                                                lastTapMs  = System.currentTimeMillis()
                                                                lastTapPos = downPos
                                                            }
                                                        } else if (previewScaleState.floatValue > 1.01f) {
                                                            // ── 平移结束：回弹到边界内 ──
                                                            val snapTarget = clampPreviewOffset(previewOffsetState.value, previewScaleState.floatValue)
                                                            if (snapTarget != previewOffsetState.value) {
                                                                val startOff = previewOffsetState.value
                                                                coroutineScope.launch {
                                                                    val anim = Animatable(0f)
                                                                    anim.animateTo(1f, tween(170)) {
                                                                        previewOffsetState.value = Offset(
                                                                            startOff.x + (snapTarget.x - startOff.x) * value,
                                                                            startOff.y + (snapTarget.y - startOff.y) * value
                                                                        )
                                                                    }
                                                                }
                                                            }
                                                        }
                                                        break@eventLoop
                                                    }

                                                    // ── 双指捏合：实时缩放 + 平移 ──
                                                    pressed.size >= 2 -> {
                                                        isMultiTouch = true
                                                        didMove = true
                                                        val p0 = pressed[0].position
                                                        val p1 = pressed[1].position
                                                        val newFocus = Offset((p0.x + p1.x) / 2f, (p0.y + p1.y) / 2f)
                                                        val newSpan  = (p0 - p1).getDistance()
                                                        if (prevSpan > 0f) {
                                                            val zoomChange = newSpan / prevSpan
                                                            val panChange  = newFocus - prevFocus
                                                            val newScale = (previewScaleState.floatValue * zoomChange).coerceIn(1f, 4f)
                                                            previewScaleState.floatValue  = newScale
                                                            previewOffsetState.value = clampPreviewOffset(
                                                                previewOffsetState.value + panChange, newScale
                                                            )
                                                        }
                                                        prevSpan  = newSpan
                                                        prevFocus = newFocus
                                                        pressed.forEach { it.consume() }
                                                    }

                                                    // ── 单指 ──
                                                    pressed.size == 1 -> {
                                                        val ptr = pressed[0]
                                                        prevSpan = 0f  // 重置，为下次双指做准备
                                                        val delta = ptr.position - ptr.previousPosition
                                                        if (isMultiTouch || previewScaleState.floatValue > 1.01f) {
                                                            // 放大状态或双指转单指：平移，1:1 跟手
                                                            if (delta.x != 0f || delta.y != 0f) {
                                                                didMove = true
                                                                previewOffsetState.value = clampPreviewOffset(
                                                                    previewOffsetState.value + delta,
                                                                    previewScaleState.floatValue,
                                                                    extra = reboundPx
                                                                )
                                                                ptr.consume()
                                                            }
                                                        } else {
                                                            val totalMove = (ptr.position - downPos).getDistance()
                                                            if (totalMove > touchSlop) {
                                                                // 单指滑动 scale=1：不消费 → HorizontalPager 接管翻页
                                                                break@eventLoop
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                            )
                        }
                    }
                }

                if (previewImages.size > 1) {
                    Surface(
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(0.65f),
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 12.dp)
                    ) {
                        Text(
                            text = "${pagerState.currentPage + 1}/${previewImages.size}",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.labelSmall,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                        )
                    }
                }
                IconButton(
                    onClick = { saveCurrentPreview() },
                    enabled = !isSavingPreview,
                    modifier = Modifier.align(Alignment.TopStart)
                ) {
                    Icon(Icons.Filled.Download, contentDescription = "保存到相册", tint = MaterialTheme.colorScheme.onBackground)
                }
                IconButton(
                    onClick = onDismiss,
                    modifier = Modifier.align(Alignment.TopEnd)
                ) {
                    Icon(Icons.Filled.Close, contentDescription = "关闭", tint = MaterialTheme.colorScheme.onBackground)
                }
                AnimatedVisibility(
                    visible = previewPromptMessage != null,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .navigationBarsPadding()
                        .padding(bottom = 24.dp)
                        .zIndex(10f),
                    enter = fadeIn() + scaleIn(initialScale = 0.96f),
                    exit = fadeOut() + scaleOut(targetScale = 0.96f)
                ) {
                    PonyPromptBubble(message = previewPromptMessage.orEmpty())
                }
            }
        }
    }

}
