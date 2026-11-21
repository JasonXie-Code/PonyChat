package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
internal fun CreationMessageEditor(message: CreationMessage?, busy: Boolean, onBack: () -> Unit, error: String? = null, onSave: (String) -> Unit) {
    var text by rememberSaveable(message?.id) { mutableStateOf(message?.content.orEmpty()) }
    var invalid by rememberSaveable(message?.id) { mutableStateOf(false) }
    val exit = creationExitAction(text != message?.content, busy, onBack) {
        if (message != null && text.isNotBlank()) onSave(text) else invalid = true
    }
    CreationPage("编辑消息", exit) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp)) {
            Text("修改后返回即提交，这条消息之后的全部对话将被清除，并从修改后的消息重新生成回复。",
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
            CreationTextField(text, { text = it }, "消息内容", minLines = 6, maxLines = 18)
            if (error != null) CreationNoticeCard(error, title = "暂时无法保存")
            if (invalid) CreationNoticeCard("消息内容不能为空，请填写后返回。", title = "暂时无法保存")
        }
    }
}
