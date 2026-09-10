package top.ponychat.webview.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.SaveAlt
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.util.formatErrorForDisplay

@Composable
internal fun ChatScreenTopBar(
    state: ChatUiState,
    character: Character,
    prefs: AppPreferences,
    isExporting: Boolean,
    onBack: () -> Unit,
    onCancelExport: () -> Unit,
    onExport: () -> Unit,
    onOpenCharacterEdit: () -> Unit,
    onResetGalgameProgress: () -> Unit,
    onOpenHistory: () -> Unit,
    onOpenDisplaySettings: () -> Unit,
) {
    PonyTopBar {
        if (state.isExportMode) {
            IconButton(onClick = onCancelExport) {
                Icon(Icons.Filled.Close, contentDescription = "取消", tint = MaterialTheme.colorScheme.onSurface)
            }
        } else {
            IconButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "返回",
                    tint = MaterialTheme.colorScheme.onSurface
                )
            }
        }
        Spacer(Modifier.width(4.dp))
        if (state.isExportMode) {
            Text(
                text = if (state.exportSelectedIds.isEmpty()) "点击消息以选择"
                else "已选 ${state.exportSelectedIds.size} 条消息",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        } else {
            ChatScreenCharacterTitle(
                state = state,
                character = character,
                prefs = prefs,
                onOpenCharacterEdit = onOpenCharacterEdit,
                modifier = Modifier.weight(1f)
            )
        }
        if (state.isExportMode) {
            IconButton(
                onClick = onExport,
                enabled = state.exportSelectedIds.isNotEmpty() && !isExporting
            ) {
                if (isExporting) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = Primary
                    )
                } else {
                    Icon(
                        Icons.Filled.SaveAlt,
                        contentDescription = "生成分享图",
                        tint = if (state.exportSelectedIds.isNotEmpty()) {
                            Primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        }
                    )
                }
            }
        } else {
            if (state.mode.startsWith("galgame") && !state.isStreaming) {
                GalgameResetTopBarAction(onResetGalgameProgress)
            }
            if (!state.mode.startsWith("galgame")) {
                IconButton(onClick = onOpenHistory) {
                    Icon(
                        Icons.Filled.History,
                        contentDescription = "历史对话",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            IconButton(onClick = onOpenDisplaySettings) {
                Icon(
                    Icons.Filled.Settings,
                    contentDescription = "设置",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun ChatScreenCharacterTitle(
    state: ChatUiState,
    character: Character,
    prefs: AppPreferences,
    onOpenCharacterEdit: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.clickable { onOpenCharacterEdit() },
        verticalAlignment = Alignment.CenterVertically
    ) {
        CharacterAvatar(
            avatarUrl = character.avatarUrl(),
            name = character.displayName(),
            apiBase = prefs.effectiveApiBase(),
            size = 36
        )
        Spacer(Modifier.width(10.dp))
        Column {
            Text(
                character.displayName(),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            if (state.isStreaming && state.mode.startsWith("galgame")) {
                Text(
                    state.galgameStreamingStep ?: "正在回复...",
                    style = MaterialTheme.typography.labelSmall,
                    color = Primary
                )
            } else if (state.mode.startsWith("galgame")) {
                Text(
                    if (state.mode == "galgame_lock") "Galgame 锁分模式" else "Galgame 模式",
                    style = MaterialTheme.typography.labelSmall,
                    color = Primary
                )
            }
        }
    }
}

@Composable
private fun GalgameResetTopBarAction(onResetGalgameProgress: () -> Unit) {
    var showResetConfirm by remember { mutableStateOf(false) }
    IconButton(onClick = { showResetConfirm = true }) {
        Icon(
            Icons.Filled.RestartAlt,
            contentDescription = "重置对话",
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
    if (showResetConfirm) {
        AlertDialog(
            onDismissRequest = { showResetConfirm = false },
            containerColor = MaterialTheme.colorScheme.surface,
            title = { Text("重置对话", color = MaterialTheme.colorScheme.onBackground) },
            text = { Text("确认要重置当前对话？", color = MaterialTheme.colorScheme.onSurface) },
            confirmButton = {
                TextButton(onClick = {
                    onResetGalgameProgress()
                    showResetConfirm = false
                }) {
                    Text("重置", color = ErrorColor, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = { showResetConfirm = false }) {
                    Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        )
    }
}

@Composable
internal fun GalgameBrokenBottomBar(
    characterName: String,
    isDeath: Boolean,
    onResetGalgameProgress: () -> Unit,
) {
    val iconBg = if (isDeath) Color(0xFF8B0000) else Color(0xFFFA5151)
    var showResetConfirmDialog by remember { mutableStateOf(false) }
    Surface(
        modifier = Modifier.fillMaxWidth().navigationBarsPadding(),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shadowElevation = 8.dp
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Surface(
                shape = RoundedCornerShape(50),
                color = iconBg,
                modifier = Modifier.size(28.dp)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text(
                        text = if (isDeath) "✕" else "!",
                        color = Color.White,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
            Text(
                text = if (isDeath) "角色已经死亡，游戏结束。" else "${characterName}开启了朋友验证，你还不是他(她)朋友。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(1f)
            )
            TextButton(onClick = { showResetConfirmDialog = true }) {
                Text(
                    text = if (isDeath) "重新开始" else "发送朋友验证",
                    color = Primary,
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelLarge
                )
            }
        }
    }
    if (showResetConfirmDialog) {
        AlertDialog(
            onDismissRequest = { showResetConfirmDialog = false },
            containerColor = MaterialTheme.colorScheme.surface,
            title = {
                Text(
                    if (isDeath) "重新开始游戏" else "发送朋友验证",
                    color = MaterialTheme.colorScheme.onBackground
                )
            },
            text = {
                Text(
                    if (isDeath) {
                        "确定要重新开始吗？当前游戏进度将被清除，好感度重置为初始值。"
                    } else {
                        "确定要发送朋友验证吗？当前游戏进度将被清除，好感度重置为初始值。"
                    },
                    color = MaterialTheme.colorScheme.onSurface
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showResetConfirmDialog = false
                    onResetGalgameProgress()
                }) {
                    Text(
                        if (isDeath) "重新开始" else "发送",
                        color = Primary,
                        fontWeight = FontWeight.Bold
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { showResetConfirmDialog = false }) {
                    Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        )
    }
}

@Composable
internal fun ChatScreenStatusBanners(
    error: String?,
    errorDebug: String?,
    quotaExceeded: Boolean,
    quotaExceededMessage: String,
    galgameSaveFailed: Boolean,
    onClearError: () -> Unit,
    onClearQuotaExceeded: () -> Unit,
    onDismissGalgameSaveFailed: () -> Unit,
) {
    AnimatedVisibility(
        visible = error != null,
        modifier = Modifier.zIndex(20f)
    ) {
        error?.let { err ->
            val displayError = formatErrorForDisplay(err, developerDetail = errorDebug)
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                colors = CardDefaults.cardColors(containerColor = ErrorColor.copy(0.12f)),
                shape = RoundedCornerShape(8.dp)
            ) {
                Row(
                    modifier = Modifier.padding(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        displayError,
                        color = ErrorColor,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.weight(1f)
                    )
                    IconButton(onClick = onClearError, modifier = Modifier.size(24.dp)) {
                        Icon(
                            Icons.Filled.Close,
                            contentDescription = null,
                            tint = ErrorColor,
                            modifier = Modifier.size(16.dp)
                        )
                    }
                }
            }
        }
    }

    AnimatedVisibility(visible = quotaExceeded) {
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp, vertical = 4.dp),
            colors = CardDefaults.cardColors(
                containerColor = Color(0xFFF59E0B).copy(alpha = 0.13f)
            ),
            shape = RoundedCornerShape(10.dp)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    Icons.Filled.HourglassEmpty,
                    contentDescription = null,
                    tint = Color(0xFFF59E0B),
                    modifier = Modifier.size(18.dp)
                )
                Spacer(Modifier.width(8.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        quotaExceededMessage.ifBlank { "今日积分已用完" },
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.SemiBold,
                        color = Color(0xFFF59E0B)
                    )
                    Text(
                        "明日零点自动重置，升级会员可获得更多积分",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(0xFFF59E0B).copy(alpha = 0.75f)
                    )
                }
                IconButton(
                    onClick = onClearQuotaExceeded,
                    modifier = Modifier.size(24.dp)
                ) {
                    Icon(
                        Icons.Filled.Close,
                        contentDescription = null,
                        tint = Color(0xFFF59E0B),
                        modifier = Modifier.size(14.dp)
                    )
                }
            }
        }
    }

    if (galgameSaveFailed) {
        AlertDialog(
            onDismissRequest = onDismissGalgameSaveFailed,
            containerColor = MaterialTheme.colorScheme.surface,
            icon = {
                Icon(
                    Icons.Filled.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error
                )
            },
            title = { Text("游戏进度保存失败", color = MaterialTheme.colorScheme.onSurface) },
            text = { Text("请勿关闭页面，稍后切回将自动重试同步。", color = MaterialTheme.colorScheme.onSurfaceVariant) },
            confirmButton = {
                TextButton(onClick = onDismissGalgameSaveFailed) {
                    Text("知道了", color = Primary)
                }
            }
        )
    }
}
