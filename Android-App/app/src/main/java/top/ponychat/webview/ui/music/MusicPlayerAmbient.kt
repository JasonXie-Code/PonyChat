package top.ponychat.webview.ui.music

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.MotionDurationScale
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.luminance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

private const val MUSIC_GLOW_CYCLE_MS = 78_000

@Composable
internal fun Modifier.musicPlayerAmbient(colors: List<Color>, background: Color, playing: Boolean): Modifier {
    val phase = remember { Animatable(0f) }
    val opacity = animateFloatAsState(if (playing) 1f else 0.55f, tween(1500), label = "musicGlowOpacity")
    val animatedColors = colors.map { animateColorAsState(it, tween(900), label = "musicGlowColor") }

    LaunchedEffect(playing) {
        if (!playing) return@LaunchedEffect
        val motionScale = coroutineContext[MotionDurationScale]
        while (isActive) {
            snapshotFlow { motionScale?.scaleFactor ?: 1f }.first { it > 0f }
            val remaining = ((1f - phase.value) * MUSIC_GLOW_CYCLE_MS).roundToInt().coerceAtLeast(1)
            phase.animateTo(1f, tween(remaining, easing = LinearEasing))
            phase.snapTo(0f)
        }
    }

    return drawWithCache {
        val width = size.width
        val height = size.height
        val strength = if (background.luminance() < 0.5f) 0.18f else 0.11f
        val brushes = animatedColors.map {
            val color = it.value
            Brush.radialGradient(
                0f to color.copy(alpha = strength),
                0.45f to color.copy(alpha = strength * 0.46f),
                1f to color.copy(alpha = 0f),
                center = Offset.Zero,
                radius = 1f,
            )
        }
        onDrawBehind {
            val angle = phase.value * 2 * PI
            val alpha = opacity.value
            clipRect {
                brushes.forEachIndexed { index, brush ->
                    val step = angle + index * 2 * PI / brushes.size
                    val centerX = width * (0.26f + index * 0.24f + 0.17f * sin(step).toFloat())
                    val centerY = height * (0.42f + 0.17f * cos(step).toFloat())
                    withTransform({
                        translate(centerX, centerY)
                        scale(width * 0.62f, height * 0.43f, pivot = Offset.Zero)
                    }) {
                        drawCircle(brush, radius = 1f, center = Offset.Zero, alpha = alpha)
                    }
                }
            }
        }
    }
}
