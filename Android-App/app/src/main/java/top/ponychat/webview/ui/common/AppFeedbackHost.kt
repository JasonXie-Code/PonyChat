package top.ponychat.webview.ui.common

import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier

/** Long prompts leave the timed snackbar queue and remain until explicitly closed. */
@Composable
fun AppFeedbackHost(host: SnackbarHostState, modifier: Modifier = Modifier) {
    var dialogs by rememberSaveable { mutableStateOf(emptyList<String>()) }
    val current = host.currentSnackbarData
    LaunchedEffect(current) {
        if (current != null && shouldUsePromptDialog(current.visuals.message)) {
            dialogs = dialogs + current.visuals.message
            current.dismiss()
        }
    }
    SnackbarHost(host, modifier) { data ->
        if (!shouldUsePromptDialog(data.visuals.message)) PonyPromptBubble(data.visuals.message)
    }
    dialogs.firstOrNull()?.let { message ->
        PromptDetailsDialog(message = message, onClose = { dialogs = dialogs.drop(1) })
    }
}
