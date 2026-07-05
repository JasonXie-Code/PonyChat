package top.ponychat.webview.ui.chat

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import top.ponychat.webview.data.model.MemoryItem
import top.ponychat.webview.ui.theme.*
// ==================== 摘要编辑对话框 ====================

@Composable
internal fun SummaryEditDialog(
    item: MemoryItem,
    onDismiss: () -> Unit,
    onConfirm: (content: String) -> Unit
) {
    val layerCfg = LAYER_TABS[item.layer]
    var content by remember(item.id) { mutableStateOf(item.content) }
    var contentError by remember(item.id) { mutableStateOf(false) }
    val periodText = item.periodLabel().ifBlank {
        item.createdAt?.take(10) ?: item.layerLabel()
    }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 4.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(24.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(layerCfg.icon, contentDescription = null,
                        tint = layerCfg.color, modifier = Modifier.size(22.dp))
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text("编辑${item.layerLabel()}", style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onBackground)
                        Text(periodText, style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f))
                    }
                }

                Spacer(Modifier.height(20.dp))

                Text("摘要内容", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(8.dp))
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(0.4f),
                    border = if (contentError) BorderStroke(1.dp, ErrorColor.copy(0.7f)) else null
                ) {
                    Box(modifier = Modifier.padding(14.dp)) {
                        BasicTextField(
                            value = content,
                            onValueChange = { content = it; contentError = false },
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = 140.dp, max = 320.dp)
                                .verticalScroll(rememberScrollState()),
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                color = MaterialTheme.colorScheme.onBackground,
                                lineHeight = 22.sp
                            ),
                            decorationBox = { inner ->
                                if (content.isEmpty()) {
                                    Text(
                                        "填写这段摘要内容…",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f)
                                    )
                                }
                                inner()
                            }
                        )
                    }
                }
                if (contentError) {
                    Text("内容不能为空", style = MaterialTheme.typography.labelSmall,
                        color = ErrorColor, modifier = Modifier.padding(top = 4.dp, start = 4.dp))
                }

                Spacer(Modifier.height(20.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)
                ) {
                    OutlinedButton(
                        onClick = onDismiss,
                        shape = RoundedCornerShape(10.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f))
                    ) {
                        Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Button(
                        onClick = {
                            if (content.isBlank()) { contentError = true; return@Button }
                            onConfirm(content.trim())
                        },
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = layerCfg.color)
                    ) {
                        Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("保存")
                    }
                }
            }
        }
    }
}

// ==================== 编辑/新增对话框（仅碎片层）====================

@Composable
internal fun MemoryEditDialog(
    title: String,
    initial: MemoryItem?,
    onDismiss: () -> Unit,
    onConfirm: (type: String, content: String, importance: Int) -> Unit
) {
    var selectedType by remember { mutableStateOf(initial?.memoryType ?: "episode") }
    var content by remember { mutableStateOf(initial?.content ?: "") }
    var importance by remember { mutableIntStateOf(initial?.importance ?: 5) }
    var contentError by remember { mutableStateOf(false) }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 4.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(24.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Psychology, contentDescription = null,
                        tint = Primary, modifier = Modifier.size(22.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(title, style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onBackground)
                }

                Spacer(Modifier.height(20.dp))

                Text("记忆类型", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    FRAGMENT_TYPES.forEach { cfg ->
                        val sel = selectedType == cfg.key
                        Surface(
                            onClick = { selectedType = cfg.key },
                            shape = RoundedCornerShape(10.dp),
                            color = if (sel) cfg.color.copy(0.18f) else MaterialTheme.colorScheme.surfaceVariant.copy(0.4f),
                            border = if (sel) BorderStroke(1.dp, cfg.color.copy(0.5f)) else null
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp)
                            ) {
                                Icon(cfg.icon, contentDescription = null,
                                    tint = if (sel) cfg.color else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f),
                                    modifier = Modifier.size(13.dp))
                                Text(cfg.label, style = MaterialTheme.typography.labelSmall,
                                    color = if (sel) cfg.color else MaterialTheme.colorScheme.onSurfaceVariant,
                                    fontWeight = if (sel) FontWeight.SemiBold else FontWeight.Normal)
                            }
                        }
                    }
                }

                Spacer(Modifier.height(18.dp))

                Text("记忆内容", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(8.dp))
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(0.4f),
                    border = if (contentError) BorderStroke(1.dp, ErrorColor.copy(0.7f)) else null
                ) {
                    Box(modifier = Modifier.padding(14.dp)) {
                        BasicTextField(
                            value = content,
                            onValueChange = { content = it; contentError = false },
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = 80.dp),
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                color = MaterialTheme.colorScheme.onBackground
                            ),
                            decorationBox = { inner ->
                                if (content.isEmpty()) {
                                    Text(
                                        "例如：用户喜欢在雨天喝咖啡…",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f)
                                    )
                                }
                                inner()
                            }
                        )
                    }
                }
                if (contentError) {
                    Text("内容不能为空", style = MaterialTheme.typography.labelSmall,
                        color = ErrorColor, modifier = Modifier.padding(top = 4.dp, start = 4.dp))
                }

                Spacer(Modifier.height(18.dp))

                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("重要度", style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = FontWeight.Medium)
                    Spacer(Modifier.weight(1f))
                    Surface(shape = RoundedCornerShape(8.dp), color = Primary.copy(0.12f)) {
                        Text(
                            "$importance / 10",
                            style = MaterialTheme.typography.labelMedium,
                            color = Primary, fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                        )
                    }
                }
                Slider(
                    value = importance.toFloat(),
                    onValueChange = { importance = it.toInt() },
                    valueRange = 1f..10f, steps = 8,
                    colors = SliderDefaults.colors(
                        thumbColor = Primary,
                        activeTrackColor = Primary,
                        inactiveTrackColor = Primary.copy(0.2f)
                    )
                )

                Spacer(Modifier.height(20.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)
                ) {
                    OutlinedButton(
                        onClick = onDismiss,
                        shape = RoundedCornerShape(10.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.onSurfaceVariant.copy(0.25f))
                    ) {
                        Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Button(
                        onClick = {
                            if (content.isBlank()) { contentError = true; return@Button }
                            onConfirm(selectedType, content.trim(), importance)
                        },
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Primary)
                    ) {
                        Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("保存")
                    }
                }
            }
        }
    }
}
