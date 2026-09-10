package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LocalLifecycleOwner
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.model.AgentRunStatus
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor

/** Only polls while this settings card is visible and the app is in the foreground. */
@Composable
internal fun AgentStatusCard(
    prefs: AppPreferences,
    characterId: String,
    mode: String,
    conversationId: String?,
) {
    val username = prefs.username
    val baseUrl = prefs.effectiveApiBase()
    val api = remember(baseUrl, username) { NetworkClient.createApiService(baseUrl) }
    val lifecycleOwner = LocalLifecycleOwner.current
    val snapshot = rememberAgentStatus(
        AgentStatusScope(username, baseUrl, characterId, mode, conversationId), lifecycleOwner, api,
    )
    AgentStatusContent(snapshot, "$username/$characterId/$mode/${conversationId.orEmpty()}")
}

@Composable
internal fun AgentStatusContent(snapshot: AgentStatusSnapshot, selectionScope: String) {
    var selectedRun by remember(selectionScope) { mutableStateOf<String?>(null) }
    var selecting by remember(selectionScope) { mutableStateOf(false) }
    val agents = snapshot.agents.ifEmpty { listOfNotNull(snapshot.agent) }
    val current = agents.firstOrNull { it.runId == selectedRun }
        ?: agents.firstOrNull { it.runId == snapshot.agent?.runId } ?: agents.firstOrNull()
    val notice = snapshot.notice
    val running = current?.status == "running" && notice == null
    val elapsed = (current?.elapsedMs ?: 0L) + if (running) snapshot.elapsedSinceReceivedMs else 0L
    val seconds = elapsed / 1000
    val duration = if (seconds >= 60) "${seconds / 60} 分 ${seconds % 60} 秒" else "$seconds 秒"
    val menuContainer = adaptivePopupMenuContainerColor()
    val menuContent = adaptivePopupMenuContentColor()
    val menuAccent = adaptivePopupMenuAccentColor()
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
        Text("Agent 状态", modifier = Modifier.padding(horizontal = 4.dp, vertical = 12.dp),
            style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surface,
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        ) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (running) CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Text(if (current == null) notice ?: "暂无这个角色的 Agent 运行记录" else current.activity,
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    if (agents.size > 1) {
                        Box {
                            TextButton(onClick = { selecting = true }) { Text("切换 ${agents.indexOf(current) + 1}/${agents.size}") }
                            DropdownMenu(
                                expanded = selecting,
                                onDismissRequest = { selecting = false },
                                modifier = Modifier.widthIn(min = 240.dp, max = 320.dp),
                                shape = RoundedCornerShape(12.dp),
                                containerColor = menuContainer,
                                border = adaptivePopupMenuBorder(),
                                tonalElevation = 2.dp,
                            ) {
                                agents.forEachIndexed { index, agent ->
                                    val isSelected = agent.runId == current?.runId
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                "${index + 1}. ${agent.taskLabel()} · " +
                                                    if (agent.status == "running") "运行中" else "已结束",
                                                color = if (isSelected) menuAccent else menuContent,
                                                fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                                                style = MaterialTheme.typography.bodySmall,
                                                maxLines = 2,
                                                overflow = TextOverflow.Ellipsis,
                                            )
                                        },
                                        trailingIcon = if (isSelected) {
                                            {
                                                Icon(
                                                    Icons.Filled.Check,
                                                    contentDescription = "当前 Agent",
                                                    tint = menuAccent,
                                                    modifier = Modifier.size(18.dp),
                                                )
                                            }
                                        } else null,
                                        onClick = { selectedRun = agent.runId; selecting = false },
                                    )
                                }
                            }
                        }
                    }
                }
                if (current != null) {
                    AgentStatusRow("模型", current.model.ifBlank { "未提供" })
                    AgentStatusRow("任务", current.taskLabel())
                    AgentStatusRow("工具", when {
                        current.currentTools.isNotEmpty() ->
                            "正在调用：${current.currentTools.joinToString("、")}"
                        current.recentTools.isNotEmpty() ->
                            "最近调用：${current.recentTools.joinToString("、")}"
                        current.status == "running" -> "本次尚未调用工具"
                        else -> "本次未调用工具"
                    })
                    AgentStatusRow("进度", "模型调用 ${current.modelCalls} 次 · 工具调用 ${current.toolCalls} 次")
                    AgentStatusRow("本次耗时", duration)
                    AgentStatusRow("本次积分", "${current.points} 分")
                    Text("每次模型调用、每次工具调用各消耗 1 分", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (notice != null) Text("$notice；以上为上次获取的状态", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

private fun AgentRunStatus.taskLabel(): String {
    val name = when (mode) { "galgame" -> "游戏"; "galgame_lock" -> "锁分"; else -> "普通聊天" }
    return "$name · " + if (phase == "background_memory") "后台记忆整理" else "当前对话"
}

@Composable
private fun AgentStatusRow(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, modifier = Modifier.width(64.dp), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
    }
}
