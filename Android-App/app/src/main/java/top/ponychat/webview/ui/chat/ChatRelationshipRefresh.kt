package top.ponychat.webview.ui.chat

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun RelationshipPullRefreshIndicator(
    maxHeight: Dp,
    triggerPx: Float,
    offsetPxProvider: () -> Float,
    isRefreshing: Boolean,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "relationshipPullRefreshSpin")
    val refreshingRotation by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 720, easing = LinearEasing)
        ),
        label = "relationshipPullRefreshRefreshingRotation"
    )
    val density = LocalDensity.current
    val iconSizePx = with(density) { 36.dp.toPx() }
    val iconGapPx = with(density) { 10.dp.toPx() }
    val minVisiblePx = with(density) { 44.dp.toPx() }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(maxHeight)
            .background(MaterialTheme.colorScheme.background)
            .graphicsLayer {
                val offset = offsetPxProvider()
                alpha = if (offset <= minVisiblePx) {
                    0f
                } else {
                    ((offset - minVisiblePx) / (triggerPx - minVisiblePx).coerceAtLeast(1f))
                        .coerceIn(0f, 1f)
                }
            },
        contentAlignment = Alignment.TopCenter
    ) {
        Surface(
            modifier = Modifier
                .size(36.dp)
                .graphicsLayer {
                    val offset = offsetPxProvider()
                    val progress = (offset / triggerPx).coerceIn(0f, 1f)
                    alpha = if (isRefreshing) 1f else (0.25f + progress * 0.75f)
                    translationY = ((offset - iconSizePx - iconGapPx) / 2f).coerceAtLeast(0f)
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

internal fun vibrateBriefly(context: Context) {
    runCatching {
        val durationMs = 55L
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val vm = context.getSystemService(VibratorManager::class.java) ?: return
            vm.defaultVibrator.vibrate(
                VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE)
            )
        } else {
            @Suppress("DEPRECATION")
            val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator ?: return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(
                    VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE)
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(durationMs)
            }
        }
    }
}
