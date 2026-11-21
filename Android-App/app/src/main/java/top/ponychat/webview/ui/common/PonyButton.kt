package top.ponychat.webview.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.theme.Primary

enum class PonyButtonStyle {
    Primary,
    Secondary,
    Danger,
    Warning,
    Gradient
}

@Composable
fun PonyButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    style: PonyButtonStyle = PonyButtonStyle.Primary,
    isLoading: Boolean = false,
    icon: (@Composable () -> Unit)? = null,
    shape: Shape = RoundedCornerShape(16.dp),
    height: Dp = 54.dp
) {
    val containerColor = when (style) {
        PonyButtonStyle.Primary -> Primary
        PonyButtonStyle.Secondary -> MaterialTheme.colorScheme.surfaceVariant
        PonyButtonStyle.Danger -> top.ponychat.webview.ui.theme.ErrorColor
        PonyButtonStyle.Warning -> top.ponychat.webview.ui.theme.AccentAmber
        PonyButtonStyle.Gradient -> Color.Transparent
    }

    val contentColor = when (style) {
        PonyButtonStyle.Primary, PonyButtonStyle.Danger -> Color.White
        PonyButtonStyle.Secondary -> MaterialTheme.colorScheme.onSurfaceVariant
        PonyButtonStyle.Warning -> Color.Black
        PonyButtonStyle.Gradient -> Color.White
    }

    if (style == PonyButtonStyle.Gradient) {
        Button(
            onClick = onClick,
            modifier = modifier
                .fillMaxWidth()
                .height(height),
            enabled = enabled && !isLoading,
            shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = Color.Transparent,
                disabledContainerColor = Color.Transparent
            ),
            contentPadding = PaddingValues(0.dp),
            elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp, pressedElevation = 4.dp)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(
                        brush = Brush.horizontalGradient(
                            colors = listOf(
                                Color(0xFF44ADFF),
                                Color(0xFF00C9A7),
                                Color(0xFF00E676)
                            )
                        ),
                        shape = shape,
                        alpha = if (enabled) 1f else 0.5f
                    ),
                contentAlignment = Alignment.Center
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        color = Color.White,
                        strokeWidth = 2.5.dp
                    )
                } else {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        icon?.invoke()
                        if (icon != null) Spacer(Modifier.width(8.dp))
                        Text(
                            text = text,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White,
                            letterSpacing = 0.5.sp
                        )
                    }
                }
            }
        }
    } else {
        Button(
            onClick = onClick,
            modifier = modifier
                .fillMaxWidth()
                .height(height),
            enabled = enabled && !isLoading,
            shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = containerColor,
                contentColor = contentColor,
                disabledContainerColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f),
                disabledContentColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
            ),
            elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp, pressedElevation = 4.dp)
        ) {
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(24.dp),
                    color = if (style == PonyButtonStyle.Secondary) Primary else Color.White,
                    strokeWidth = 2.5.dp
                )
            } else {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    icon?.invoke()
                    if (icon != null) Spacer(Modifier.width(8.dp))
                    Text(
                        text = text,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 0.5.sp
                    )
                }
            }
        }
    }
}
