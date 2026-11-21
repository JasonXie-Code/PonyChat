package top.ponychat.webview.ui.creation

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.material.icons.filled.DeleteOutline
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

@Composable
fun CreationHistoryPage(history: List<CreationHistory>, selectedId: String?, onBack: () -> Unit, busy: Boolean = false, error: String? = null,
    onDelete: (String) -> Unit = {}, onSelect: (String) -> Unit) {
    val feedback = creationHapticAction()
    var target by remember { mutableStateOf<CreationHistory?>(null) }
    CreationPage("创作历史", onBack) {
        Text("选择一个会话继续创作", color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(20.dp), style = MaterialTheme.typography.bodyMedium)
        if (error != null) CreationNoticeCard(error, title = "暂时无法删除", modifier = Modifier.padding(horizontal = 16.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (history.isEmpty()) item { Text("还没有创作历史", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            items(history, key = { it.id }) { item ->
                CreationCard(Modifier.fillMaxWidth().clickable(enabled = !busy) { feedback { onSelect(item.id) } }, selected = item.id == selectedId) {
                    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Icon(Icons.Default.ChatBubbleOutline, null, tint = Primary)
                        Column(Modifier.weight(1f)) {
                            Text(item.title, style = MaterialTheme.typography.titleSmall)
                            if (item.id == selectedId) Text("当前会话", color = Primary, style = MaterialTheme.typography.labelSmall)
                        }
                        PonyIconButton(onClick = { feedback { target = item } }, enabled = !busy,
                            icon = Icons.Default.DeleteOutline, contentDescription = "删除会话${item.title}")
                        Icon(Icons.Default.ChevronRight, "打开会话", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
    target?.let { item ->
        PonyConfirmDialog(title = "删除这个会话？", message = "会话中的全部消息和创作设定将被删除，无法恢复。",
            confirmText = "确认删除", confirmEnabled = !busy, actionStyle = PonyDialogActionStyle.Danger,
            onDismiss = { target = null }, onConfirm = { target = null; onDelete(item.id) })
    }

}
