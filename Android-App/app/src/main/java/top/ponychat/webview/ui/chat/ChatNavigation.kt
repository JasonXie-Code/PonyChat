package top.ponychat.webview.ui.chat

import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController

/** Dismiss input before leaving chat; navigation can run during the IME animation. */
@Composable
internal fun rememberChatNavigation(): (() -> Unit) -> Unit {
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    return { destination ->
        focusManager.clearFocus(force = true)
        keyboard?.hide()
        destination()
    }
}
