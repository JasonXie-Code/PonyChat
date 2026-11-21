package top.ponychat.webview.ui.creation

import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import top.ponychat.webview.ui.chat.ChatErrorDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import top.ponychat.webview.ui.common.PonyAlertDialog

internal fun isCreationStatusNotice(message: String): Boolean =
    message.startsWith("正在显示本地缓存")

/** Retain failures until dismissed, even when background synchronization clears them. */
@Composable
internal fun CreationFailureFeedback(state: CreationUiState, onRegenerate: () -> Unit,
    onLoad: (String?) -> Unit) {
    val session = state.session
    // The server may report a disconnected stream after the user deliberately stopped it.
    val stoppedReply = state.stoppedSessionId != null && session?.id == state.stoppedSessionId
    val error = (state.error ?: session?.lastError?.takeUnless { stoppedReply })?.takeIf {
        it.isNotBlank() && !it.startsWith("已停止生成")
    }
    var displayedError by rememberSaveable(session?.id) { mutableStateOf<String?>(null) }
    var displayedRetry by rememberSaveable(session?.id) { mutableStateOf(false) }
    LaunchedEffect(error, state.sending) {
        if (state.sending) displayedError = null
        else if (error != null) {
            displayedError = error
            displayedRetry = session?.messages?.any { it.role == "user" } == true &&
                (session.lastError != null || session.messages.lastOrNull()?.incomplete == true) &&
                !error.startsWith("删除未确认")
        }
    }
    displayedError?.let { message ->
        val busy = state.loading || state.sending || state.deleting || state.saving ||
            state.switchingVersion || session?.busy == true
        if (isCreationStatusNotice(message)) {
            PonyAlertDialog(
                title = "正在显示本地缓存",
                message = message,
                onDismiss = { displayedError = null },
                confirmButton = {
                    TextButton(onClick = { displayedError = null }) { Text("关闭") }
                },
                dismissButton = {
                    TextButton(enabled = !busy, onClick = {
                        displayedError = null
                        onLoad(session?.id)
                    }) { Text("刷新会话") }
                }
            )
        } else ChatErrorDialog(error = message, developerDetail = message,
            actionLabel = if (busy) null else if (displayedRetry) "重新生成" else "刷新会话",
            onAction = if (busy) null else ({
                displayedError = null
                if (displayedRetry) onRegenerate() else onLoad(session?.id)
            }), onClose = { displayedError = null })
    }
}
