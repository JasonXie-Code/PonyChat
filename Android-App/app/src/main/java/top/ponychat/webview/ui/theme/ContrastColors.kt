package top.ponychat.webview.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance

data class PonyContrastColors(
    val container: Color,
    val content: Color,
    val border: Color
)

@Composable
fun ponyTintContainerColors(
    tint: Color,
    strong: Boolean = false
): PonyContrastColors {
    val scheme = MaterialTheme.colorScheme
    val isLight = scheme.background.luminance() > 0.5f
    val container = tint.mixWith(
        scheme.surface,
        when {
            strong && isLight -> 0.24f
            strong -> 0.32f
            isLight -> 0.18f
            else -> 0.26f
        }
    )
    val preferredContent = if (isLight) {
        tint.mixWith(Color.Black, 0.46f)
    } else {
        tint.mixWith(Color.White, 0.74f)
    }
    val fallbackContent = if (isLight) scheme.onSurface else Color.White
    val content = preferredContent.ensureContrast(container, fallbackContent)
    val border = tint.mixWith(
        if (isLight) scheme.outline else scheme.outlineVariant,
        if (isLight) 0.52f else 0.68f
    )
    return PonyContrastColors(container = container, content = content, border = border)
}

@Composable
fun ponyNeutralContainerColors(strong: Boolean = false): PonyContrastColors {
    val scheme = MaterialTheme.colorScheme
    val isLight = scheme.background.luminance() > 0.5f
    return PonyContrastColors(
        container = if (isLight) scheme.surface else scheme.surfaceVariant,
        content = if (strong) scheme.onSurface else scheme.onSurfaceVariant,
        border = if (isLight) {
            scheme.outline.copy(alpha = if (strong) 0.48f else 0.34f)
        } else {
            scheme.outline.copy(alpha = if (strong) 0.38f else 0.26f)
        }
    )
}

@Composable
fun ponySubtleOutlineColor(strong: Boolean = false): Color {
    val scheme = MaterialTheme.colorScheme
    val isLight = scheme.background.luminance() > 0.5f
    return if (isLight) {
        scheme.outline.copy(alpha = if (strong) 0.52f else 0.36f)
    } else {
        scheme.outline.copy(alpha = if (strong) 0.38f else 0.24f)
    }
}

fun contrastRatio(a: Color, b: Color): Float {
    val l1 = a.luminance()
    val l2 = b.luminance()
    val lighter = maxOf(l1, l2)
    val darker = minOf(l1, l2)
    return ((lighter + 0.05f) / (darker + 0.05f))
}

private fun Color.mixWith(other: Color, selfFraction: Float): Color {
    val fraction = selfFraction.coerceIn(0f, 1f)
    val otherFraction = 1f - fraction
    return Color(
        red = red * fraction + other.red * otherFraction,
        green = green * fraction + other.green * otherFraction,
        blue = blue * fraction + other.blue * otherFraction,
        alpha = alpha * fraction + other.alpha * otherFraction
    )
}

private fun Color.ensureContrast(
    background: Color,
    fallback: Color,
    minimumRatio: Float = 4.5f
): Color = if (contrastRatio(this, background) >= minimumRatio) this else fallback
