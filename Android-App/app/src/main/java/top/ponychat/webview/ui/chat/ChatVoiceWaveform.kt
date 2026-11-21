package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.pow

@Composable
internal fun VoiceTextCard(
    text: String,
    accent: Color,
    label: String?,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f),
        border = BorderStroke(1.dp, accent.copy(alpha = 0.18f)),
        tonalElevation = 0.dp
    ) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            if (!label.isNullOrBlank()) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = accent,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(bottom = 2.dp)
                )
            }
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall.copy(lineHeight = 20.sp),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
internal fun VoiceWaveBars(
    progress: Float,
    color: Color,
    waveform: List<Float>,
    modifier: Modifier = Modifier,
    onTogglePlayback: () -> Unit,
    onLongPress: () -> Unit,
    onSeek: (Float) -> Unit,
    onSeekStart: () -> Unit,
    onSeekEnd: () -> Unit,
) {
    val density = LocalDensity.current
    var waveWidthPx by remember { mutableFloatStateOf(1f) }
    BoxWithConstraints(
        modifier = modifier
            .onSizeChanged { waveWidthPx = it.width.toFloat().coerceAtLeast(1f) }
            .pointerInput(Unit) {
                detectTapGestures(
                    onTap = { onTogglePlayback() },
                    onLongPress = { onLongPress() }
                )
            }
            .pointerInput(waveWidthPx) {
                detectDragGestures(
                    onDragStart = { offset ->
                        onSeekStart()
                        onSeek((offset.x / waveWidthPx).coerceIn(0f, 1f))
                    },
                    onDragEnd = onSeekEnd,
                    onDragCancel = onSeekEnd,
                    onDrag = { change, _ ->
                        change.consume()
                        onSeek((change.position.x / waveWidthPx).coerceIn(0f, 1f))
                    }
                )
            }
    ) {
        val barWidth = 3.dp
        val barGap = 3.dp
        val barWidthPx = with(density) { barWidth.toPx() }
        val minGapPx = with(density) { barGap.toPx() }
        val availableWidthPx = with(density) { maxWidth.toPx() }.coerceAtLeast(barWidthPx)
        val barCount = ((availableWidthPx + minGapPx) / (barWidthPx + minGapPx))
            .toInt()
            .coerceAtLeast(1)
        val safeProgress = progress.coerceIn(0f, 1f)
        val heights = remember(barCount, waveform) {
            voiceBarHeights(barCount, waveform)
        }
        Canvas(modifier = Modifier.fillMaxSize()) {
            val safeBarWidth = barWidthPx.coerceAtMost(size.width)
            val gapPx = if (barCount > 1) {
                ((size.width - safeBarWidth * barCount) / (barCount - 1)).coerceAtLeast(0f)
            } else {
                0f
            }
            heights.forEachIndexed { index, heightFraction ->
                val barProgress = if (barCount <= 1) 1f else index / (barCount - 1).toFloat()
                val isPlayed = barProgress <= safeProgress
                val barHeight = (size.height * heightFraction).coerceAtLeast(1f)
                val x = if (index == barCount - 1) {
                    (size.width - safeBarWidth).coerceAtLeast(0f)
                } else {
                    (index * (safeBarWidth + gapPx)).coerceAtMost((size.width - safeBarWidth).coerceAtLeast(0f))
                }
                drawRoundRect(
                    color = color.copy(alpha = if (isPlayed) 0.96f else 0.26f),
                    topLeft = Offset(x, (size.height - barHeight) / 2f),
                    size = Size(safeBarWidth, barHeight),
                    cornerRadius = CornerRadius(safeBarWidth / 2f, safeBarWidth / 2f)
                )
            }
        }
    }
}

private fun voiceBarHeights(barCount: Int, waveform: List<Float>): List<Float> {
    val fallbackPattern = listOf(0.38f, 0.62f, 0.88f, 0.56f, 0.74f, 0.44f, 0.96f, 0.66f)
    if (waveform.isEmpty()) {
        return List(barCount) { index -> fallbackPattern[index % fallbackPattern.size] }
    }
    val safeWave = waveform
        .filter { it.isFinite() && it >= 0f }
        .map { it.coerceIn(0f, 1f) }
    if (safeWave.isEmpty()) {
        return List(barCount) { index -> fallbackPattern[index % fallbackPattern.size] }
    }
    return List(barCount) { index ->
        val start = (index * safeWave.size / barCount).coerceIn(0, safeWave.lastIndex)
        val endExclusive = (((index + 1) * safeWave.size + barCount - 1) / barCount)
            .coerceIn(start + 1, safeWave.size)
        val amplitude = safeWave.subList(start, endExclusive).maxOrNull() ?: safeWave[start]
        val shaped = amplitude.toDouble().pow(0.72).toFloat()
        (0.18f + shaped * 0.82f).coerceIn(0.18f, 1f)
    }
}
