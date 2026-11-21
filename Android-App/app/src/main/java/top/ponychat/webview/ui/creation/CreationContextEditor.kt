package top.ponychat.webview.ui.creation

import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import kotlinx.coroutines.launch
import java.util.UUID
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyButtonStyle
import top.ponychat.webview.ui.common.PonyIconButton

/** Block positions are saved verbatim and determine the order sent to the model. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CreationContextEditor(session: CreationSession, error: String?, onDismiss: () -> Unit, saving: Boolean = false, usage: CreationContextUsage? = null,
    pageTitle: String = "上下文管理", headerChanged: Boolean = false,
    header: (@Composable () -> Unit)? = null,
    onSave: (List<CreationContextBlock>) -> Unit) {
    val feedback = creationHapticAction()
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    var blocks by remember(session.id) { mutableStateOf(session.contextLayout) }
    var expanded by remember { mutableStateOf<String?>(null) }
    var dragging by remember { mutableStateOf<String?>(null) }
    var displacement by remember { mutableFloatStateOf(0f) }
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    fun move(from: Int, to: Int) {
        if (to in blocks.indices && from != to) feedback { blocks = blocks.toMutableList().apply { add(to, removeAt(from)) } }
    }
    fun update(block: CreationContextBlock) { blocks = blocks.map { if (it.id == block.id) block else it } }
    val exit = creationExitAction(headerChanged || blocks != session.contextLayout, saving, onDismiss) { onSave(blocks) }
    CreationPage(pageTitle, exit, actions = {
        Text("${usage?.usedTokens?.toString() ?: "—"}/${usage?.contextLimit?.toString() ?: "—"}",
            modifier = Modifier.padding(end = 16.dp), style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }) {
        Column(Modifier.fillMaxSize()) {
            LazyColumn(state = list, modifier = Modifier.weight(1f), contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                item {
                    header?.invoke()
                    Text("上下文", style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
                    Text("长按拖动或用箭头调整发送顺序。", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                itemsIndexed(blocks.filter { it.kind != "character" }, key = { _, block -> block.id }) { visibleIndex, block ->
                    val index = blocks.indexOfFirst { it.id == block.id }
                    val visible = blocks.filter { it.kind != "character" }
                    val previous = visible.getOrNull(visibleIndex - 1)?.let { blocks.indexOf(it) }
                    val next = visible.getOrNull(visibleIndex + 1)?.let { blocks.indexOf(it) }
                    val active = dragging == block.id
                    CreationCard(modifier = Modifier.fillMaxWidth().zIndex(if (active) 1f else 0f)
                        .graphicsLayer { translationY = if (active) displacement else 0f }, selected = active) {
                        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.DragIndicator, "拖动${block.title}", modifier = Modifier.size(36.dp)
                                .pointerInput(block.id) {
                                    detectDragGesturesAfterLongPress(onDragStart = { haptic.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress); dragging = block.id; displacement = 0f },
                                        onDragCancel = { dragging = null; displacement = 0f },
                                        onDragEnd = { dragging = null; displacement = 0f }) { change, amount ->
                                        change.consume()
                                        displacement += amount.y
                                        val current = list.layoutInfo.visibleItemsInfo.firstOrNull { it.key == block.id }
                                        if (current != null) {
                                            val center = current.offset + current.size / 2f + displacement
                                            val target = list.layoutInfo.visibleItemsInfo.firstOrNull {
                                                it.key != block.id && center in it.offset.toFloat()..(it.offset + it.size).toFloat()
                                            }
                                            if (target != null) {
                                                val from = blocks.indexOfFirst { it.id == block.id }
                                                val to = blocks.indexOfFirst { it.id == target.key }
                                                if (from >= 0 && to >= 0) {
                                                    displacement -= (target.offset - current.offset)
                                                    move(from, to)
                                                }
                                            }
                                            val edge = list.layoutInfo.viewportEndOffset - 80
                                            if (center > edge) scope.launch { list.scrollBy(24f) }
                                            else if (center < 80) scope.launch { list.scrollBy(-24f) }
                                        }
                                    }
                                })
                            Column(Modifier.weight(1f)) {
                                Text("${visibleIndex + 1} · ${block.title}", style = MaterialTheme.typography.titleSmall)
                                Text(when (block.kind) {
                                    "history" -> "自动填入保留窗口内的对话"
                                    "input" -> "本次新消息 · 不重复放入历史"
                                    "character" -> "引用当前角色设定 · 在创作设定中修改"
                                    "instructions" -> "使用上方填写的创作指令"
                                    "system" -> "系统提示词 · 只读"
                                    else -> "文本块 · 点击铅笔编辑"
                                }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            PonyIconButton(onClick = { previous?.let { move(index, it) } }, enabled = previous != null,
                                icon = Icons.Default.KeyboardArrowUp, contentDescription = "上移${block.title}")
                            PonyIconButton(onClick = { next?.let { move(index, it) } }, enabled = next != null,
                                icon = Icons.Default.KeyboardArrowDown, contentDescription = "下移${block.title}")
                        }
                        if (block.kind == "custom") {
                            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(block.text.ifBlank { "空文本" }, maxLines = 2, modifier = Modifier.weight(1f),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                if (block.kind == "custom") PonyIconButton(onClick = { feedback { expanded = if (expanded == block.id) null else block.id } },
                                    icon = Icons.Default.Edit, contentDescription = "编辑${block.title}")
                                if (block.kind == "custom") PonyIconButton(onClick = { feedback { blocks = blocks.filterNot { it.id == block.id } } },
                                    icon = Icons.Default.Close, contentDescription = "移除${block.title}")
                            }
                            if (block.kind == "custom" && expanded == block.id) Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                if (block.kind == "custom") CreationTextField(block.title, { update(block.copy(title = it.take(80))) },
                                    label = "块名称", modifier = Modifier.fillMaxWidth())
                                CreationTextField(block.text, { update(block.copy(text = it)) }, label = "块内容",
                                    modifier = Modifier.fillMaxWidth(), minLines = 3, maxLines = 8)
                            }
                        }
                    }
                }
                item {
                    PonyButton("添加文本块", style = PonyButtonStyle.Secondary, onClick = {
                        feedback {}
                        val block = CreationContextBlock(UUID.randomUUID().toString(), "custom", "自定义文本", "")
                        blocks = blocks + block; expanded = block.id
                        scope.launch { list.animateScrollToItem(blocks.count { it.kind != "character" }) }
                    }, enabled = blocks.size < 25, modifier = Modifier.fillMaxWidth(), icon = { Icon(Icons.Default.Add, null) })
                }
            }
            if (error != null) CreationNoticeCard(error, title = "暂时无法保存", modifier = Modifier.padding(horizontal = 20.dp))
        }
    }
}
