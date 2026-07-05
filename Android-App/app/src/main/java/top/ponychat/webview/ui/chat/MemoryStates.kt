package top.ponychat.webview.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.util.formatErrorForDisplay

@Composable
internal fun MemoryEmptyState(
    selectedLayer: Int,
    fragmentTypeFilter: String?,
    modifier: Modifier = Modifier
) {
    val cfg = LAYER_TABS[selectedLayer]
    val typeCfg = fragmentTypeFilter?.let { fragmentTypeConfig(it) }

    Column(
        modifier = modifier.padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Box(
            modifier = Modifier
                .size(72.dp)
                .clip(CircleShape)
                .background(
                    Brush.radialGradient(
                        listOf(cfg.color.copy(0.15f), cfg.color.copy(0.04f))
                    )
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                if (typeCfg != null) typeCfg.icon else cfg.icon,
                contentDescription = null,
                modifier = Modifier.size(34.dp),
                tint = cfg.color.copy(0.55f)
            )
        }
        Spacer(Modifier.height(16.dp))
        Text(
            when {
                selectedLayer == 0 && fragmentTypeFilter != null -> "暂无「${typeCfg?.label}」类记忆碎片"
                selectedLayer == 0 -> "还没有记忆碎片"
                selectedLayer == 1 -> "暂无日摘要"
                selectedLayer == 2 -> "暂无周摘要"
                selectedLayer == 3 -> "暂无月摘要"
                else -> "暂无年度意识"
            },
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(6.dp))
        Text(
            when (selectedLayer) {
                0 -> "与角色多聊聊，AI 会自动提炼并记住重要的事"
                1 -> "系统会在次日自动将前一天的记忆碎片汇总为日摘要"
                2 -> "系统会在下周自动将上一周的日摘要汇总为周摘要"
                3 -> "系统会在下月自动将上个月的周摘要汇总为月摘要"
                else -> "系统在生成月摘要后会自动追加一条年度意识"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f)
        )
        if (selectedLayer == 0) {
            Spacer(Modifier.height(4.dp))
            Text(
                "也可以点击右下角 + 手动添加",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f)
            )
        }
    }
}

@Composable
internal fun MemoryLoadingState(modifier: Modifier = Modifier) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator(color = Primary, modifier = Modifier.size(36.dp))
        Spacer(Modifier.height(14.dp))
        Text(
            "加载记忆中…",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall
        )
    }
}

@Composable
internal fun MemoryErrorState(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            Icons.Filled.CloudOff,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
            modifier = Modifier.size(48.dp)
        )
        Spacer(Modifier.height(12.dp))
        Text(
            formatErrorForDisplay(message),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(Modifier.height(14.dp))
        OutlinedButton(onClick = onRetry, shape = RoundedCornerShape(10.dp)) {
            Icon(Icons.Filled.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("重试")
        }
    }
}
