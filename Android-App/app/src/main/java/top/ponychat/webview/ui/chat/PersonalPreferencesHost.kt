package top.ponychat.webview.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.zIndex
import top.ponychat.webview.data.prefs.AppPreferences

/** Like the @ picker, the editor occupies the chat body in-place, below its header. */
@Composable
internal fun PersonalPreferencesHost(
    prefs: AppPreferences,
    characterId: String,
    characterName: String,
    mode: String,
    topInset: Dp,
    onExitActionChanged: ((() -> Unit)?) -> Unit,
    onRelationshipChanged: () -> Unit = {},
    content: @Composable (openPreferences: () -> Unit) -> Unit,
) {
    var visible by remember(prefs.username, characterId, mode) { mutableStateOf(false) }
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val dismiss = {
        focus.clearFocus()
        keyboard?.hide()
        visible = false
    }
    Box(Modifier.fillMaxSize()) {
        content {
            focus.clearFocus()
            keyboard?.hide()
            visible = true
        }
        if (visible) {
            Surface(modifier = Modifier.matchParentSize().padding(top = topInset)
                .zIndex(20f),
                color = MaterialTheme.colorScheme.background) {
                // Keep the occluding surface outside animated IME/navigation
                // insets, so resizing never reveals the underlying chat.
                Box(Modifier.fillMaxSize().navigationBarsPadding().imePadding()) {
                    key(prefs.username, characterId, mode) {
                        PersonalPreferencesPanel(prefs, characterId, characterName, mode, dismiss,
                            onExitActionChanged, onRelationshipChanged)
                    }
                }
            }
        }
    }
}
