package top.ponychat.webview.ui.common

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import top.ponychat.webview.util.ErrorFormatter

@Composable
fun PromptDetailsDialog(message: String, developerDetail: String? = null,
                        title: String = "提示", actionLabel: String? = null,
                        onAction: (() -> Unit)? = null, onClose: () -> Unit) {
    val formatted = remember(message) { ErrorFormatter.format(message) }
    val trimmed = message.trim()
    val userMessage = if (formatted.developerMessage == null && trimmed.isNotEmpty()) trimmed else formatted.userMessage
    val debug = developerDetail?.trim()?.takeIf { it.isNotEmpty() }
        ?: formatted.developerMessage?.takeIf { it.isNotBlank() }?.let { trimmed }
        ?: "未提供额外调试信息。"
    val clipboard = LocalClipboardManager.current
    AlertDialog(onDismissRequest = onClose, title = { Text(title) }, text = {
        Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("用户说明", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(userMessage, style = MaterialTheme.typography.bodyLarge)
            HorizontalDivider()
            Text("调试信息", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            SelectionContainer {
                Text(debug, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }, dismissButton = {
        TextButton(onClick = { clipboard.setText(AnnotatedString("用户说明：\n$userMessage\n\n调试信息：\n$debug")) },
            colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurfaceVariant)) { Text("复制") }
    }, confirmButton = {
        Row {
            if (actionLabel != null && onAction != null) {
                TextButton(onClick = onAction) { Text(actionLabel) }
            }
            TextButton(onClick = onClose) { Text("关闭") }
        }
    })
}
