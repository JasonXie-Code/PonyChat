package top.ponychat.webview.ui.creation

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyButtonStyle
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun CreationNoticeCard(message: String, modifier: Modifier = Modifier, enabled: Boolean = true,
    title: String? = null, actionLabel: String = "刷新会话", onRefresh: (() -> Unit)? = null) {
    val heading = title ?: when {
        message.startsWith("正在显示本地缓存") -> "正在显示本地缓存"
        message.startsWith("已停止生成") -> "已停止生成"
        message.startsWith("删除未确认") -> "删除未确认"
        else -> "本次回复未完成"
    }
    val detail = message.removePrefix("$heading，")
    CreationCard(modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Outlined.Info, null, tint = Primary, modifier = Modifier.size(18.dp))
                Text(heading, color = MaterialTheme.colorScheme.onSurface, style = MaterialTheme.typography.titleSmall)
            }
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium.copy(lineHeight = 22.sp))
            if (onRefresh != null) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                PonyButton(actionLabel, onClick = onRefresh, enabled = enabled, style = PonyButtonStyle.Secondary,
                    modifier = Modifier.width(124.dp), height = 38.dp)
            }
        }
    }
}
