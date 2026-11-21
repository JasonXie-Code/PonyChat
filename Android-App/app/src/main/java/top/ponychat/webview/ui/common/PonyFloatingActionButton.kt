package top.ponychat.webview.ui.common

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.FloatingActionButtonDefaults
import androidx.compose.material3.FloatingActionButtonElevation
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.LocalFontScale
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledIcon

@Composable
fun PonyFloatingActionButton(
    onClick: () -> Unit,
    icon: ImageVector,
    contentDescription: String? = null,
    modifier: Modifier = Modifier,
    isSmall: Boolean = false,
    containerColor: Color = top.ponychat.webview.ui.theme.Primary,
    contentColor: Color = Color.White,
    shape: Shape = CircleShape,
    elevation: FloatingActionButtonElevation = FloatingActionButtonDefaults.elevation(defaultElevation = 4.dp, pressedElevation = 8.dp)
) {
    val scale = LocalFontScale.current
    val finalIconSize = 24.dp * scale

    val content = @Composable {
        ScaledIcon(
            imageVector = icon,
            contentDescription = contentDescription,
            modifier = Modifier.size(finalIconSize),
            tint = contentColor
        )
    }

    if (isSmall) {
        val size = 40.dp * scale
        SmallFloatingActionButton(
            onClick = onClick,
            modifier = modifier.size(size),
            shape = shape,
            containerColor = containerColor,
            contentColor = contentColor,
            elevation = elevation,
            interactionSource = remember { MutableInteractionSource() },
            content = content
        )
    } else {
        val size = 56.dp * scale
        FloatingActionButton(
            onClick = onClick,
            modifier = modifier.size(size),
            shape = shape,
            containerColor = containerColor,
            contentColor = contentColor,
            elevation = elevation,
            interactionSource = remember { MutableInteractionSource() },
            content = content
        )
    }
}
