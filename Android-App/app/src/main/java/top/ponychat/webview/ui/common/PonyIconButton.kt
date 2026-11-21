package top.ponychat.webview.ui.common

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonColors
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.ScaledIcon

@Composable
fun PonyIconButton(
    onClick: () -> Unit,
    icon: ImageVector,
    contentDescription: String? = null,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    size: Dp = 40.dp,
    iconSize: Dp = 24.dp,
    tint: Color = LocalContentColor.current,
    colors: IconButtonColors = IconButtonDefaults.iconButtonColors()
) {
    val scale = LocalFontScale.current
    val finalSize = size * scale
    val finalIconSize = iconSize * scale

    IconButton(
        onClick = onClick,
        modifier = modifier.size(finalSize),
        enabled = enabled,
        colors = colors,
        interactionSource = remember { MutableInteractionSource() }
    ) {
        ScaledIcon(
            imageVector = icon,
            contentDescription = contentDescription,
            modifier = Modifier.size(finalIconSize),
            tint = tint
        )
    }
}
