package top.ponychat.webview.ui.chat

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.BlurredEdgeTreatment
import androidx.compose.ui.draw.blur
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

/** 好感度胶囊：心形 + 分数；破裂/胜利/锁分样式；可传入单击/长按。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun GalgameScoreCapsule(
    score: Int,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null
) {
    val safeScore = score.coerceIn(0, 100)
    val isBroken = safeScore <= 0
    val heartBpm = galgameScoreToHeartBpm(safeScore)
    val beatDurationMs = if (heartBpm > 0f) (60_000f / heartBpm).roundToInt().coerceAtLeast(320) else 600
    val scheme = MaterialTheme.colorScheme
    val isDark = scheme.background.luminance() < 0.5f
    val capsuleColor = when {
        isBroken -> if (isDark) Color(0xFFAAAAAA) else Color(0xFF5C5C5C)
        else -> galgameScoreToColor(safeScore, isDark)
    }
    val infiniteTransition = rememberInfiniteTransition(label = "gal_heart")
    val heartScale by infiniteTransition.animateFloat(
        initialValue = 0.92f,
        targetValue = 0.92f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = beatDurationMs
                val beat1PeakMs = (beatDurationMs * 0.12f).toInt()
                val beat1DropMs = (beatDurationMs * 0.22f).toInt()
                val reboundPeakMs = (beatDurationMs * 0.30f).toInt()
                val settleMs = (beatDurationMs * 0.45f).toInt()
                0.92f at 0
                1.06f at beat1PeakMs
                0.95f at beat1DropMs
                0.99f at reboundPeakMs
                0.92f at settleMs
                0.92f at beatDurationMs
            },
            repeatMode = RepeatMode.Restart
        ),
        label = "heart_scale"
    )
    val capsuleShape = RoundedCornerShape(20.dp)
    val capsuleBg = when {
        isBroken -> if (isDark) {
            Color(0xFF121212).copy(alpha = 0.73f)
        } else {
            scheme.surfaceVariant.copy(alpha = 0.94f)
        }
        isDark -> Color(0xFF0F1419).copy(alpha = 0.87f)
        else -> scheme.surfaceContainerHigh.copy(alpha = 0.96f)
    }
    val clickModifier = if (onClick != null || onLongClick != null) {
        Modifier.combinedClickable(onClick = onClick ?: {}, onLongClick = onLongClick)
    } else {
        Modifier
    }

    Box(
        modifier = Modifier.wrapContentWidth().padding(top = 12.dp).then(clickModifier),
        contentAlignment = Alignment.TopCenter
    ) {
        Surface(
            shape = capsuleShape,
            color = capsuleBg,
            border = BorderStroke(1.dp, capsuleColor),
            shadowElevation = 6.dp,
            tonalElevation = 0.dp
        ) {
            Box {
                Box(
                    modifier = Modifier
                        .matchParentSize()
                        .blur(10.dp, BlurredEdgeTreatment.Unbounded)
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    Color.White.copy(alpha = if (isDark) 0.14f else 0.22f),
                                    Color.Transparent
                                )
                            ),
                            shape = capsuleShape
                        )
                )
                Row(
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Icon(
                        Icons.Filled.Favorite,
                        contentDescription = "好感度",
                        tint = capsuleColor,
                        modifier = Modifier
                            .size(18.dp)
                            .then(
                                if (isBroken) Modifier
                                else Modifier.graphicsLayer { scaleX = heartScale; scaleY = heartScale }
                            )
                    )
                    Text(
                        text = "$safeScore",
                        style = MaterialTheme.typography.titleMedium,
                        color = capsuleColor,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}
