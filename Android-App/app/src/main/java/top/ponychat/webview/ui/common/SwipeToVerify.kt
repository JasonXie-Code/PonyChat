package top.ponychat.webview.ui.common

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import top.ponychat.webview.ui.theme.Primary
import kotlin.math.roundToInt

@Composable
fun SwipeToVerify(
    isVerified: Boolean,
    onVerifySuccess: () -> Unit,
    modifier: Modifier = Modifier
) {
    val height = 48.dp
    val thumbWidth = 48.dp
    val shape = RoundedCornerShape(12.dp)

    val thumbWidthPx = with(LocalDensity.current) { thumbWidth.toPx() }
    var containerWidthPx by remember { mutableFloatStateOf(0f) }

    val offsetX = remember { Animatable(0f) }
    val coroutineScope = rememberCoroutineScope()

    // 如果状态被外部重置为 false，对应的 UI offset 也要自动归零
    LaunchedEffect(isVerified) {
        if (!isVerified && offsetX.value > 0f) {
            offsetX.animateTo(0f)
        } else if (isVerified && containerWidthPx > 0f) {
            val target = containerWidthPx - thumbWidthPx
            if (target > 0f) {
                offsetX.snapTo(target)
            }
        }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .clip(shape)
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .onGloballyPositioned { coordinates ->
                containerWidthPx = coordinates.size.width.toFloat()
            },
        contentAlignment = Alignment.CenterStart
    ) {
        // 背景成功填充区
        val trackPrimaryAlpha = if (isVerified) 0.15f else 0.25f
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .width(with(LocalDensity.current) { (offsetX.value + thumbWidthPx).toDp() })
                .background(Primary.copy(alpha = trackPrimaryAlpha))
        )

        // 提示文本 (居中)
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = if (isVerified) "验证完成" else "请向右滑动验证",
                style = MaterialTheme.typography.bodyMedium,
                color = if (isVerified) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
            )
        }

        // 拖动滑块
        val dragMaxWidth = (containerWidthPx - thumbWidthPx).coerceAtLeast(0f)

        Box(
            modifier = Modifier
                .offset { IntOffset(offsetX.value.roundToInt(), 0) }
                .width(thumbWidth)
                .fillMaxHeight()
                .padding(4.dp)
                .shadow(2.dp, RoundedCornerShape(8.dp))
                .clip(RoundedCornerShape(8.dp))
                .background(if (isVerified) Primary else MaterialTheme.colorScheme.surface)
                .draggable(
                    orientation = Orientation.Horizontal,
                    state = rememberDraggableState { delta ->
                        if (!isVerified && dragMaxWidth > 0f) {
                            coroutineScope.launch {
                                offsetX.snapTo((offsetX.value + delta).coerceIn(0f, dragMaxWidth))
                            }
                        }
                    },
                    onDragStopped = {
                        if (!isVerified) {
                            coroutineScope.launch {
                                if (offsetX.value >= dragMaxWidth * 0.95f) {
                                    // 验证成功，吸附到最右侧
                                    offsetX.animateTo(dragMaxWidth)
                                    onVerifySuccess()
                                } else {
                                    // 失败，回弹
                                    offsetX.animateTo(0f)
                                }
                            }
                        }
                    }
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isVerified) Icons.Filled.Check else Icons.AutoMirrored.Filled.ArrowForward,
                contentDescription = if (isVerified) "验证成功" else "滑动验证",
                tint = if (isVerified) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}
