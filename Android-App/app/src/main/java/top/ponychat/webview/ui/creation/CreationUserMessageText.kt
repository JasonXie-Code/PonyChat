package top.ponychat.webview.ui.creation

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.IntOffset
import top.ponychat.webview.ui.chat.FingerAnchoredDropdownMenu
import top.ponychat.webview.ui.chat.SelectableMessageText
import top.ponychat.webview.ui.chat.actionMenuContentColor
import top.ponychat.webview.ui.chat.actionMenuDangerColor
import top.ponychat.webview.ui.chat.findSentenceBounds
import kotlin.math.roundToInt

@Composable
internal fun CreationUserMessageText(message: CreationMessage, busy: Boolean, onDelete: () -> Unit, onEdit: () -> Unit) {
    val context = LocalContext.current
    val feedback = creationHapticAction()
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    var menu by remember(message.content) { mutableStateOf(false) }
    var anchor by remember { mutableStateOf(IntOffset.Zero) }
    var selection by remember(message.content) { mutableStateOf<IntRange?>(null) }
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
    var pressedOffset by remember { mutableIntStateOf(0) }
    val foreground = actionMenuContentColor()
    fun copy(value: String) = feedback {
        (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
            .setPrimaryClip(ClipData.newPlainText("消息", value))
        selection = null
    }
    SelectableMessageText(text = message.content, validMentionNames = emptySet(), color = Color.White,
        style = MaterialTheme.typography.bodyLarge, selectionRange = selection,
        onSelectionRangeChange = { selection = it }, onCopySelection = ::copy, onCancelSelection = { feedback { selection = null } },
        onTextLayout = { layout = it }, onLongPress = { local, window ->
            haptic.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress)
            pressedOffset = layout?.getOffsetForPosition(local) ?: 0
            anchor = IntOffset(window.x.roundToInt(), window.y.roundToInt())
            menu = true
        })
    FingerAnchoredDropdownMenu(menu, anchor, { menu = false }) {
        DropdownMenuItem(text = { Text("复制", color = foreground) }, leadingIcon = { Icon(Icons.Default.ContentCopy, null, tint = foreground) },
            onClick = { menu = false; copy(message.content) })
        DropdownMenuItem(text = { Text("选择文字", color = foreground) }, leadingIcon = { Icon(Icons.Default.FormatColorText, null, tint = foreground) },
            onClick = { feedback { menu = false; selection = findSentenceBounds(message.content, pressedOffset) } })
        DropdownMenuItem(text = { Text("删除", color = actionMenuDangerColor()) }, enabled = !busy,
            leadingIcon = { Icon(Icons.Default.Delete, null, tint = actionMenuDangerColor()) }, onClick = { feedback { menu = false; onDelete() } })
        DropdownMenuItem(text = { Text("编辑", color = foreground) }, enabled = !busy,
            leadingIcon = { Icon(Icons.Default.Edit, null, tint = foreground) }, onClick = { feedback { menu = false; onEdit() } })
    }
}
