package top.ponychat.webview.ui.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp

private val conversationModes = listOf(
    "normal" to "普通对话",
    "creation" to "创造模式",
    "galgame" to "游戏模式",
    "galgame_lock" to "锁分模式",
)

@Composable
internal fun ConversationModeOptions(
    currentMode: String,
    canUseLockMode: Boolean,
    onModeSelected: (String) -> Unit,
) {
    Column(Modifier.selectableGroup()) {
        for ((mode, label) in conversationModes) {
            val isSelected = mode == currentMode
            val enabled = mode != "galgame_lock" || canUseLockMode
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .selectable(
                        selected = isSelected,
                        enabled = enabled,
                        role = Role.RadioButton,
                        onClick = { onModeSelected(mode) },
                    )
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = isSelected, onClick = null, enabled = enabled)
                Column(Modifier.padding(start = 12.dp)) {
                    Text(label, style = MaterialTheme.typography.titleSmall)
                    if (!enabled) {
                        Text("仅开发者或管理员可用", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}
