package top.ponychat.webview.ui.chat

import androidx.compose.runtime.Composable
import top.ponychat.webview.ui.common.PromptDetailsDialog

@Composable
internal fun ChatErrorDialog(error: String, developerDetail: String?,
    actionLabel: String? = null, onAction: (() -> Unit)? = null, onClose: () -> Unit) {
    PromptDetailsDialog(message = error, developerDetail = developerDetail ?: error,
        title = "本次请求未完成", actionLabel = actionLabel, onAction = onAction, onClose = onClose)
}
