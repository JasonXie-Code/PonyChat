package top.ponychat.webview.ui.theme

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp

private val DarkColorScheme = darkColorScheme(
    primary            = Primary,
    onPrimary          = DarkOnPrimary,
    primaryContainer   = PrimaryContainer,
    onPrimaryContainer = PrimaryLight,
    secondary          = Secondary,
    onSecondary        = Color.Black,
    background         = DarkBackground,
    onBackground       = DarkOnBackground,
    surface            = DarkSurface,
    onSurface          = DarkOnSurface,
    surfaceVariant     = DarkSurfaceVariant,
    onSurfaceVariant   = DarkOnSurfaceVariant,
    error              = ErrorColor,
    onError            = Color.White,
    outline            = Color(0xFF3E4A5C),
    outlineVariant     = Color(0xFF252D3A)
)

private val LightColorScheme = lightColorScheme(
    primary            = PrimaryVariant,
    onPrimary          = Color.White,
    primaryContainer   = Color(0xFFEDE9FE),
    onPrimaryContainer = PrimaryVariant,
    secondary          = SecondaryVariant,
    onSecondary        = Color.White,
    background         = LightBackground,
    onBackground       = LightOnBackground,
    surface            = LightSurface,
    onSurface          = LightOnSurface,
    surfaceVariant     = LightSurfaceVariant,
    onSurfaceVariant   = LightOnSurfaceVariant,
    error              = ErrorColor,
    onError            = Color.White,
    outline            = Color(0xFFCBD5E1),
    outlineVariant     = Color(0xFFE2E8F0)
)

@Composable
fun PonyChatTheme(
    darkTheme: Boolean = true,
    fontScale: Float = 1f,
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val scale = fontScale.coerceIn(0.85f, 1.25f)

    val currentDensity = LocalDensity.current
    val systemFontScale = LocalConfiguration.current.fontScale
    // 仅缩放 fontScale（文字），不缩放 density，避免开关等控件变形
    val scaledDensity = Density(
        density = currentDensity.density,
        fontScale = systemFontScale * scale
    )
    val effectiveUiScale = systemFontScale * scale

    CompositionLocalProvider(
        LocalDensity provides scaledDensity,
        LocalFontScale provides effectiveUiScale
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography  = Typography,
            content     = content
        )
    }
}

/** 当前生效缩放比例（系统字体缩放 × 应用字体缩放），用于开关等控件的等比例缩放 */
val LocalFontScale = compositionLocalOf { 1f }

/** 调试模式配置（通过 CompositionLocal 传递，避免在每个组件签名中添加参数） */
data class DebugSettings(
    val showMessageIds: Boolean = false,
    val showRawContent: Boolean = false
)

val LocalDebugSettings = compositionLocalOf { DebugSettings() }

/** Material3 Switch 默认尺寸 */
private val SwitchTrackWidth = 52.dp
private val SwitchTrackHeight = 32.dp

/**
 * 随字体大小等比例缩放的开关，使用 graphicsLayer 缩放避免变形。
 * 替代直接使用 Switch，使开关既能变大变小又保持比例。
 */
@Composable
fun ScaledSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    colors: SwitchColors = SwitchDefaults.colors()
) {
    val scale = LocalFontScale.current
    val haptic = LocalHapticFeedback.current
    Box(
        modifier = modifier.size(SwitchTrackWidth * scale, SwitchTrackHeight * scale),
        contentAlignment = Alignment.Center
    ) {
        Switch(
            checked = checked,
            onCheckedChange = { newValue ->
                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                onCheckedChange(newValue)
            },
            modifier = Modifier.graphicsLayer {
                scaleX = scale
                scaleY = scale
                transformOrigin = TransformOrigin.Center
            },
            enabled = enabled,
            colors = colors
        )
    }
}

@Composable
fun ScaledIcon(
    imageVector: ImageVector,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current
) {
    val scale = LocalFontScale.current
    Icon(
        imageVector = imageVector,
        contentDescription = contentDescription,
        modifier = modifier.graphicsLayer {
            scaleX = scale
            scaleY = scale
            transformOrigin = TransformOrigin.Center
        },
        tint = tint
    )
}
