package top.ponychat.webview.ui.common

import androidx.compose.animation.core.*
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Draw-only animation: placeholder bounds do not change on each frame. */
@Composable
fun SkeletonBlock(modifier: Modifier = Modifier, radius: Dp = 6.dp) {
    val transition = rememberInfiniteTransition(label = "skeleton")
    val phase by transition.animateFloat(
        initialValue = -1f, targetValue = 2f,
        animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing)),
        label = "shimmer",
    )
    val color = MaterialTheme.colorScheme.onSurface
    Spacer(modifier.drawBehind {
        val x = size.width * phase
        drawRoundRect(
            brush = Brush.linearGradient(
                listOf(color.copy(alpha = 0.07f), color.copy(alpha = 0.17f), color.copy(alpha = 0.07f)),
                start = Offset(x - size.width, 0f), end = Offset(x + size.width, size.height),
            ),
            cornerRadius = CornerRadius(radius.toPx()),
        )
    })
}

/** Inline card body, sized like its eventual heading and paragraphs. */
@Composable
fun SkeletonCard(modifier: Modifier = Modifier, lines: Int = 3, avatar: Boolean = false) {
    Row(modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        if (avatar) SkeletonBlock(Modifier.size(56.dp), radius = 28.dp)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SkeletonBlock(Modifier.fillMaxWidth(0.45f).height(18.dp))
            repeat(lines) { index ->
                SkeletonBlock(Modifier.fillMaxWidth(if (index == lines - 1) 0.66f else 1f).height(14.dp))
            }
        }
    }
}

@Composable
fun SkeletonList(modifier: Modifier = Modifier, rows: Int = 6, avatar: Boolean = true) {
    Column(modifier.fillMaxWidth().clipToBounds().loadingSemantics(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        repeat(rows) { SkeletonCard(lines = 2, avatar = avatar) }
    }
}

@Composable
fun SkeletonGrid(modifier: Modifier = Modifier, columns: Int = 2, rows: Int = 3) {
    Column(modifier.fillMaxWidth().clipToBounds().loadingSemantics().padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(rows) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                repeat(columns) { SkeletonBlock(Modifier.weight(1f).aspectRatio(1f), radius = 12.dp) }
            }
        }
    }
}

@Composable
fun ChatLoadingSkeleton(modifier: Modifier = Modifier) {
    Column(modifier.fillMaxSize().clipToBounds().loadingSemantics().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)) {
        repeat(6) { index ->
            val user = index % 2 == 1
            Row(Modifier.fillMaxWidth(), horizontalArrangement = if (user) Arrangement.End else Arrangement.Start) {
                if (!user) {
                    SkeletonBlock(Modifier.size(36.dp), radius = 18.dp)
                    Spacer(Modifier.width(10.dp))
                }
                SkeletonBlock(Modifier.fillMaxWidth(if (user) 0.55f else 0.70f)
                    .height(if (index % 3 == 0) 88.dp else 56.dp), radius = 16.dp)
            }
        }
    }
}

fun Modifier.loadingSemantics(): Modifier = semantics(mergeDescendants = true) {
    contentDescription = "正在加载"
    progressBarRangeInfo = ProgressBarRangeInfo.Indeterminate
}
