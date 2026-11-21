package top.ponychat.webview.ui.chat

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.data.model.MemoryItem
import top.ponychat.webview.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*
// ==================== Fragment 层列表 ====================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FragmentMemoryList(
    memories: List<MemoryItem>,
    displayName: String,
    onEdit: (MemoryItem) -> Unit,
    onDelete: (MemoryItem) -> Unit
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item {
            Text(
                "${memories.size} 条记忆碎片",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f),
                modifier = Modifier.padding(bottom = 2.dp)
            )
        }
        items(memories, key = { it.id }) { item ->
            val dismissState = rememberSwipeToDismissBoxState(
                confirmValueChange = { value ->
                    if (value == SwipeToDismissBoxValue.EndToStart) onDelete(item)
                    false
                }
            )
            SwipeToDismissBox(
                state = dismissState,
                enableDismissFromStartToEnd = false,
                backgroundContent = {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .clip(RoundedCornerShape(16.dp))
                            .background(ErrorColor.copy(0.12f))
                            .padding(end = 20.dp),
                        contentAlignment = Alignment.CenterEnd
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text(
                                "删除",
                                color = ErrorColor,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold
                            )
                            Icon(
                                Icons.Filled.DeleteOutline, contentDescription = null,
                                tint = ErrorColor, modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }
            ) {
                FragmentMemoryCard(
                    item = item,
                    displayName = displayName,
                    onEdit = { onEdit(item) },
                    onDelete = { onDelete(item) }
                )
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun FragmentMemoryCard(
    item: MemoryItem,
    displayName: String,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    val cfg = fragmentTypeConfig(item.memoryType)
    val typeColors = ponyTintContainerColors(cfg.color)
    val manualColors = ponyNeutralContainerColors()

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        shadowElevation = 0.dp
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(32.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(typeColors.container)
                        .border(1.dp, typeColors.border, RoundedCornerShape(8.dp)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(cfg.icon, contentDescription = null, tint = typeColors.content,
                        modifier = Modifier.size(16.dp))
                }
                Spacer(Modifier.width(10.dp))
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = typeColors.container,
                    border = BorderStroke(1.dp, typeColors.border)
                ) {
                    Text(
                        cfg.label,
                        style = MaterialTheme.typography.labelSmall,
                        color = typeColors.content,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp)
                    )
                }
                if (item.source == "manual") {
                    Spacer(Modifier.width(6.dp))
                    Surface(
                        shape = RoundedCornerShape(6.dp),
                        color = manualColors.container,
                        border = BorderStroke(1.dp, manualColors.border)
                    ) {
                        Text(
                            "手动",
                            style = MaterialTheme.typography.labelSmall,
                            color = manualColors.content,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 3.dp)
                        )
                    }
                }
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onEdit, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Filled.Edit, contentDescription = "编辑",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f),
                        modifier = Modifier.size(16.dp))
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Filled.DeleteOutline, contentDescription = "删除",
                        tint = ErrorColor.copy(0.65f), modifier = Modifier.size(16.dp))
                }
            }

            Spacer(Modifier.height(10.dp))
            Text(
                text = item.content.replace("{{USER}}", displayName),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onBackground,
                lineHeight = 22.sp
            )
            Spacer(Modifier.height(12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                ImportanceStars(importance = item.importance)
                Spacer(Modifier.weight(1f))
                if (item.recallCount > 0) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                        Icon(Icons.Filled.Psychology, contentDescription = null,
                            tint = Primary.copy(0.5f), modifier = Modifier.size(11.dp))
                        Text(
                            "召回 ${item.recallCount} 次",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                            fontSize = 10.sp
                        )
                    }
                }
                item.createdAt?.takeIf { it.isNotBlank() }?.let { ts ->
                    Text(
                        formatMemoryTime(ts),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f),
                        fontSize = 10.sp
                    )
                }
            }
        }
    }
}

// ==================== 摘要层列表（Daily/Weekly/Monthly/Annual）====================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SummaryMemoryList(
    memories: List<MemoryItem>,
    layer: Int,
    displayName: String,
    onEdit: (MemoryItem) -> Unit,
    onDelete: (MemoryItem) -> Unit
) {
    val cfg = LAYER_TABS[layer]
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(bottom = 2.dp)
            ) {
                Icon(cfg.icon, contentDescription = null,
                    tint = cfg.color.copy(0.7f), modifier = Modifier.size(14.dp))
                Text(
                    "${memories.size} 条${cfg.label}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f)
                )
                if (layer == 4) {
                    Spacer(Modifier.width(4.dp))
                    val layerColors = ponyTintContainerColors(cfg.color)
                    Surface(
                        shape = RoundedCornerShape(4.dp),
                        color = layerColors.container,
                        border = BorderStroke(1.dp, layerColors.border)
                    ) {
                        Text(
                            "追加演化历史",
                            style = MaterialTheme.typography.labelSmall,
                            color = layerColors.content,
                            fontSize = 10.sp,
                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                        )
                    }
                }
            }
        }

        items(memories, key = { it.id }) { item ->
            val dismissState = rememberSwipeToDismissBoxState(
                confirmValueChange = { value ->
                    if (value == SwipeToDismissBoxValue.EndToStart) onDelete(item)
                    false
                }
            )
            SwipeToDismissBox(
                state = dismissState,
                enableDismissFromStartToEnd = false,
                backgroundContent = {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .clip(RoundedCornerShape(16.dp))
                            .background(ErrorColor.copy(0.12f))
                            .padding(end = 20.dp),
                        contentAlignment = Alignment.CenterEnd
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text("删除", color = ErrorColor,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold)
                            Icon(Icons.Filled.DeleteOutline, contentDescription = null,
                                tint = ErrorColor, modifier = Modifier.size(18.dp))
                        }
                    }
                }
            ) {
                SummaryMemoryCard(
                    item = item,
                    layerCfg = cfg,
                    displayName = displayName,
                    onEdit = { onEdit(item) },
                    onDelete = { onDelete(item) }
                )
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun SummaryMemoryCard(
    item: MemoryItem,
    layerCfg: LayerTabConfig,
    displayName: String,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        shadowElevation = 0.dp
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // 头部：层级图标 + period 标签 + 操作按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(
                            Brush.linearGradient(
                                listOf(layerCfg.color.copy(0.25f), layerCfg.color.copy(0.08f))
                            )
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(layerCfg.icon, contentDescription = null,
                        tint = layerCfg.color, modifier = Modifier.size(18.dp))
                }
                Spacer(Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    // period 可读标签
                    val periodText = item.periodLabel().ifBlank {
                        item.createdAt?.take(10) ?: ""
                    }
                    Text(
                        periodText,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = layerCfg.color,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(5.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Surface(shape = RoundedCornerShape(4.dp), color = layerCfg.color.copy(0.12f)) {
                            Text(
                                layerCfg.label,
                                style = MaterialTheme.typography.labelSmall,
                                color = layerCfg.color,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                            )
                        }
                        Surface(
                            shape = RoundedCornerShape(4.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(0.5f)
                        ) {
                            Text(
                                "AI 生成",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                            )
                        }
                    }
                }
                IconButton(onClick = onEdit, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Filled.Edit, contentDescription = "编辑",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.55f),
                        modifier = Modifier.size(16.dp))
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Filled.DeleteOutline, contentDescription = "删除",
                        tint = ErrorColor.copy(0.5f), modifier = Modifier.size(16.dp))
                }
            }

            Spacer(Modifier.height(12.dp))

            // 摘要内容
            Text(
                text = item.content.replace("{{USER}}", displayName),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onBackground,
                lineHeight = 22.sp
            )

            Spacer(Modifier.height(12.dp))

            // 底部：召回次数 + 时间
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Spacer(Modifier.weight(1f))
                if (item.recallCount > 0) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                        Icon(Icons.Filled.Psychology, contentDescription = null,
                            tint = layerCfg.color.copy(0.5f), modifier = Modifier.size(11.dp))
                        Text(
                            "召回 ${item.recallCount} 次",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
                            fontSize = 10.sp
                        )
                    }
                }
                item.createdAt?.takeIf { it.isNotBlank() }?.let { ts ->
                    Text(
                        formatMemoryTime(ts),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f),
                        fontSize = 10.sp
                    )
                }
            }
        }
    }
}

// ==================== 重要度星星 ====================

@Composable
private fun ImportanceStars(importance: Int) {
    val starColor = Color(0xFFFFBE0B)
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        repeat(5) { idx ->
            val filled = idx < (importance / 2.0).coerceAtLeast(1.0).toInt().coerceAtMost(5)
            Icon(
                if (filled) Icons.Filled.Star else Icons.Filled.StarBorder,
                contentDescription = null,
                tint = if (filled) starColor else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f),
                modifier = Modifier.size(12.dp)
            )
        }
        Text(
            " $importance",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f),
            fontSize = 10.sp
        )
    }
}

// ==================== 工具函数 ====================

private fun formatMemoryTime(raw: String): String {
    return try {
        val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val date = sdf.parse(raw.take(19)) ?: return raw.take(10)
        val diff = System.currentTimeMillis() - date.time
        when {
            diff < 86_400_000L -> SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
            diff < 7L * 86_400_000 -> "${diff / 86_400_000}天前"
            else -> SimpleDateFormat("M/d", Locale.getDefault()).format(date)
        }
    } catch (_: Exception) {
        raw.take(10)
    }
}
