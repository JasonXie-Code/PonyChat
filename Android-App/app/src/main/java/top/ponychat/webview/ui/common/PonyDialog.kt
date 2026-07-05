package top.ponychat.webview.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.util.formatErrorForDisplay

enum class PonyDialogActionStyle {
    Primary,
    Danger,
    Neutral
}

data class PonyDialogOption(
    val title: String,
    val subtitle: String? = null,
    val icon: ImageVector? = null,
    val iconTint: Color? = null,
    val onClick: () -> Unit
)

@Composable
fun PonyAlertDialog(
    title: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    message: String? = null,
    confirmButton: (@Composable () -> Unit)? = null,
    dismissButton: (@Composable () -> Unit)? = null,
    content: (@Composable () -> Unit)? = null
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        modifier = modifier,
        containerColor = MaterialTheme.colorScheme.surface,
        title = {
            Text(
                title,
                color = MaterialTheme.colorScheme.onBackground,
                fontWeight = FontWeight.SemiBold
            )
        },
        text = {
            when {
                content != null -> content()
                message != null -> Text(
                    formatErrorForDisplay(message),
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
        },
        confirmButton = { confirmButton?.invoke() },
        dismissButton = { dismissButton?.invoke() }
    )
}

@Composable
fun PonyConfirmDialog(
    title: String,
    message: String,
    confirmText: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    dismissText: String = "取消",
    actionStyle: PonyDialogActionStyle = PonyDialogActionStyle.Primary,
    confirmEnabled: Boolean = true,
    isLoading: Boolean = false
) {
    val actionColor = when (actionStyle) {
        PonyDialogActionStyle.Primary -> Primary
        PonyDialogActionStyle.Danger -> ErrorColor
        PonyDialogActionStyle.Neutral -> MaterialTheme.colorScheme.onSurface
    }

    PonyAlertDialog(
        title = title,
        message = message,
        onDismiss = onDismiss,
        modifier = modifier,
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                enabled = confirmEnabled && !isLoading
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp
                    )
                } else {
                    Text(confirmText, color = actionColor, fontWeight = FontWeight.Bold)
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isLoading) {
                Text(dismissText, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    )
}

@Composable
fun PonyDangerCountdownConfirmDialog(
    title: String,
    message: String,
    confirmText: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    dismissText: String = "取消",
    countdownSeconds: Int = 5,
    isLoading: Boolean = false
) {
    var countdown by remember { mutableIntStateOf(countdownSeconds.coerceAtLeast(0)) }

    LaunchedEffect(countdownSeconds) {
        countdown = countdownSeconds.coerceAtLeast(0)
        while (countdown > 0) {
            delay(1000)
            countdown--
        }
    }

    PonyAlertDialog(
        title = title,
        message = message,
        onDismiss = { if (!isLoading) onDismiss() },
        modifier = modifier,
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                enabled = !isLoading && countdown == 0
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp
                    )
                } else if (countdown > 0) {
                    Text(
                        "$confirmText ($countdown)",
                        color = ErrorColor.copy(alpha = 0.4f),
                        fontWeight = FontWeight.Bold
                    )
                } else {
                    Text(confirmText, color = ErrorColor, fontWeight = FontWeight.Bold)
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isLoading) {
                Text(dismissText, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    )
}

@Composable
fun PonyOptionDialog(
    title: String,
    options: List<PonyDialogOption>,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    dismissText: String = "取消"
) {
    PonyAlertDialog(
        title = title,
        onDismiss = onDismiss,
        modifier = modifier,
        content = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                options.forEach { option ->
                    Surface(
                        onClick = option.onClick,
                        shape = RoundedCornerShape(10.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(14.dp)
                        ) {
                            option.icon?.let { icon ->
                                Icon(
                                    icon,
                                    contentDescription = null,
                                    tint = option.iconTint ?: Primary,
                                    modifier = Modifier.size(24.dp)
                                )
                            }
                            Column {
                                Text(
                                    option.title,
                                    style = MaterialTheme.typography.bodyMedium,
                                    fontWeight = FontWeight.Medium,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                                option.subtitle?.let { subtitle ->
                                    Text(
                                        subtitle,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(dismissText, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    )
}
