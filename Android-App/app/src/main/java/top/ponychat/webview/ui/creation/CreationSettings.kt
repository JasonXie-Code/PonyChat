package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun CreationSettings(session: CreationSession, onDismiss: () -> Unit, error: String? = null,
    saving: Boolean = false, usage: CreationContextUsage? = null,
    onSave: (String, String, List<CreationContextBlock>) -> Unit) {
    var title by remember(session.id) { mutableStateOf(session.title) }
    var instructions by remember(session.id) { mutableStateOf(session.instructions) }
    CreationContextEditor(session, error, onDismiss, saving, usage,
        pageTitle = "创作设定",
        headerChanged = title != session.title || instructions != session.instructions,
        header = {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                CreationTextField(title, { title = it.take(80) }, label = "会话标题",
                    modifier = Modifier.fillMaxWidth())
                CreationTextField(instructions, { instructions = it }, label = "创作指令",
                    hint = "希望怎样创作？可以指定语气、视角和篇幅。",
                    minLines = 3, maxLines = 8, modifier = Modifier.fillMaxWidth())
            }
        }) { blocks -> onSave(title, instructions, blocks) }
}
