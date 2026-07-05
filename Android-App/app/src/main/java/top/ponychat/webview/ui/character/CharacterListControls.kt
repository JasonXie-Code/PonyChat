package top.ponychat.webview.ui.character

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.theme.AppFontSizes
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledIcon as Icon

@Composable
internal fun PullRefreshIndicator(
    maxHeight: Dp,
    triggerPx: Float,
    offsetPxProvider: () -> Float,
    isRefreshing: Boolean
) {
    val infiniteTransition = rememberInfiniteTransition(label = "pullRefreshSpin")
    val refreshingRotation by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 720, easing = LinearEasing)
        ),
        label = "pullRefreshRefreshingRotation"
    )
    val density = LocalDensity.current
    val iconSizePx = with(density) { 36.dp.toPx() }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(maxHeight)
            .background(MaterialTheme.colorScheme.background)
            .graphicsLayer {
                alpha = if (offsetPxProvider() > 0.5f) 1f else 0f
            },
        contentAlignment = Alignment.TopCenter
    ) {
        Surface(
            modifier = Modifier
                .size(36.dp)
                .graphicsLayer {
                    val progress = (offsetPxProvider() / triggerPx).coerceIn(0f, 1f)
                    alpha = if (isRefreshing) 1f else (0.25f + progress * 0.75f)
                    translationY = ((offsetPxProvider() - iconSizePx) / 2f).coerceAtLeast(0f)
                    rotationZ = if (isRefreshing || progress >= 1f) {
                        refreshingRotation
                    } else {
                        progress * 180f
                    }
                },
            shape = CircleShape,
            color = Primary.copy(alpha = 0.12f),
            contentColor = Primary
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    Icons.Filled.Refresh,
                    contentDescription = "下拉刷新",
                    modifier = Modifier.size(21.dp),
                    tint = Primary
                )
            }
        }
    }
}

internal fun LazyListState.isAtRefreshTop(): Boolean =
    !canScrollBackward || (firstVisibleItemIndex == 0 && firstVisibleItemScrollOffset <= 2)

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun RowScope.CompactModeNavItem(
    selected: Boolean,
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    onLongClick: (() -> Unit)? = null
) {
    val animatedColor by animateColorAsState(
        targetValue = if (selected) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
        animationSpec = tween(200),
        label = "navColor"
    )
    val animatedScale by animateFloatAsState(
        targetValue = if (selected) 1.1f else 1f,
        animationSpec = spring(dampingRatio = 0.6f),
        label = "navScale"
    )

    Box(
        modifier = Modifier
            .weight(1f)
            .fillMaxHeight()
            .combinedClickable(
                onClick = { onClick() },
                onLongClick = onLongClick
            )
            .padding(vertical = 4.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.graphicsLayer {
                scaleX = animatedScale
                scaleY = animatedScale
            }
        ) {
            Box(
                modifier = Modifier
                    .size(28.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(
                        if (selected) Primary.copy(alpha = 0.12f) else Color.Transparent
                    ),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = label,
                    tint = animatedColor,
                    modifier = Modifier.size(20.dp)
                )
            }
            Spacer(Modifier.height(2.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall.copy(fontSize = AppFontSizes.caption, lineHeight = 12.sp),
                color = animatedColor,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                maxLines = 1,
                textAlign = TextAlign.Center
            )
        }
    }
}
