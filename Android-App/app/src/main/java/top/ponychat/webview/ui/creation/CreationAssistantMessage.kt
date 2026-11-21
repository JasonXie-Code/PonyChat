package top.ponychat.webview.ui.creation

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import top.ponychat.webview.ui.chat.PonyStyleAvatar
import top.ponychat.webview.ui.chat.formatAssistantHeaderTime
import top.ponychat.webview.ui.common.PonyIconButton

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CreationAssistantMessage(message: CreationMessage, latest: Boolean, session: CreationSession,
    busy: Boolean, sending: Boolean, characterName: String, characterAvatar: String, apiBase: String,
    modifier: Modifier = Modifier, onProfile: () -> Unit, onDelete: () -> Unit, onRegenerate: () -> Unit,
    onPrevious: () -> Unit, onNext: () -> Unit, showTimestamp: Boolean, minimumHeight: Dp = 0.dp,
    onContinue: () -> Unit = {}) {
    val context = LocalContext.current
    val feedback = creationHapticAction()
    Box(Modifier.fillMaxWidth().heightIn(min = minimumHeight)) {
    Column(modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.clickable(onClick = onProfile).semantics { contentDescription = "消息角色主页" }) {
                PonyStyleAvatar(characterAvatar, characterName, apiBase, size = 40)
            }
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(characterName, maxLines = 1, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (showTimestamp) Text(formatAssistantHeaderTime(message.timestamp), Modifier.weight(1f),
                    maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .7f))
            }
            if (latest && !sending && !message.incomplete && session.messages.any { it.role == "user" }) {
                val total = session.replyVersions.orEmpty().size.coerceAtLeast(1)
                val index = session.selectedReplyVersion.coerceIn(0, total - 1)
                androidx.compose.runtime.CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides 32.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton({ feedback(onPrevious) }, enabled = !busy && index > 0, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Default.ChevronLeft, "上一版本", Modifier.size(18.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = if (!busy && index > 0) 1f else .35f))
                        }
                        Text("${index + 1}/$total", style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        IconButton({ feedback { if (index < total - 1) onNext() else onRegenerate() } }, enabled = !busy,
                            modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Default.ChevronRight, if (index < total - 1) "下一版本" else "生成新版本",
                                Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = if (!busy) 1f else .35f))
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(18.dp))
        if (message.content.isEmpty() && sending) CreationPendingReplyBody()
        else CreationMarkdown(message.content, Modifier.fillMaxWidth(),
            streaming = sending && message.id.startsWith("stream-"))
        if (!sending && !session.busy) Row(Modifier.padding(top = 8.dp)) {
            PonyIconButton(onClick = { feedback {
                (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                    .setPrimaryClip(ClipData.newPlainText("Markdown", message.content))
            } }, icon = Icons.Default.ContentCopy, contentDescription = "复制 Markdown", iconSize = 15.dp,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .75f))
            PonyIconButton(onClick = { feedback(onDelete) }, enabled = !busy, icon = Icons.Default.DeleteOutline,
                contentDescription = "删除回复", iconSize = 18.dp,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .75f))
            if (latest) PonyIconButton(onClick = { feedback(onRegenerate) }, enabled = !busy, icon = Icons.Default.Refresh,
                contentDescription = "重新生成", iconSize = 18.dp,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .75f))
            if (latest) PonyIconButton(onClick = { feedback(onContinue) }, enabled = !busy, icon = Icons.Default.PlayArrow,
                contentDescription = "续写", iconSize = 22.dp,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .75f))
        }
    }
    }
}
