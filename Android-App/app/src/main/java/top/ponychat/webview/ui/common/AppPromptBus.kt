package top.ponychat.webview.ui.common

import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow

/** Non-Compose callers use the same in-app prompt host as CustomToast. */
object AppPromptBus {
    internal val messages = MutableSharedFlow<String>(extraBufferCapacity = 32,
        onBufferOverflow = BufferOverflow.DROP_OLDEST)

    fun show(message: String) {
        if (message.isNotBlank()) messages.tryEmit(message)
    }
}

@Composable
fun CollectAppPrompts(host: SnackbarHostState) {
    val owner = LocalLifecycleOwner.current
    LaunchedEffect(owner, host) {
        owner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            AppPromptBus.messages.collect { host.showSnackbar(it) }
        }
    }
}
