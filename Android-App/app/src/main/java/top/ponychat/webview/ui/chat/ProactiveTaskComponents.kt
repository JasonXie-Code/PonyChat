package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.ProactiveTask
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors
import top.ponychat.webview.ui.theme.ponyTintContainerColors

@Composable
internal fun TaskSummaryCard(tasks: List<ProactiveTask>, loading: Boolean) {
    val active = tasks.count { it.enabled }
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = Color.Transparent
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.horizontalGradient(
                        listOf(Color(0xFF4F46E5), Color(0xFF0E7490))
                    ),
                    RoundedCornerShape(18.dp)
                )
                .padding(16.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.NotificationsActive, contentDescription = null, tint = Color.White)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        "角色会按这些约定主动找你",
                        style = MaterialTheme.typography.titleSmall,
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        if (loading) "正在同步任务..." else "${active} 个启用，${tasks.size} 个任务",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.White.copy(alpha = 0.78f)
                    )
                }
            }
        }
    }
}

@Composable
internal fun AssistCreateButton(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(999.dp),
        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 12.dp)
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(17.dp))
        Spacer(Modifier.width(5.dp))
        Text(text, maxLines = 1)
    }
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
internal fun ScheduleTypeSelector(
    selected: String,
    onSelected: (String) -> Unit
) {
    val options = listOf(
        "once" to "单次",
        "daily" to "每日",
        "weekly" to "每周",
        "monthly" to "每月",
        "interval" to "间隔"
    )
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            "重复",
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            options.forEach { (value, label) ->
                SelectableTaskPill(
                    text = label,
                    selected = selected == value,
                    modifier = Modifier.weight(1f),
                    onClick = { onSelected(value) }
                )
            }
        }
    }
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
internal fun WeekdaySelector(
    selected: Int,
    onSelected: (Int) -> Unit
) {
    val weekdays = listOf(
        0 to "周一",
        1 to "周二",
        2 to "周三",
        3 to "周四",
        4 to "周五",
        5 to "周六",
        6 to "周日"
    )
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            "星期",
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            weekdays.forEach { (value, label) ->
                SelectableTaskPill(
                    text = label,
                    selected = selected == value,
                    onClick = { onSelected(value) }
                )
            }
        }
    }
}

@Composable
private fun SelectableTaskPill(
    text: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    val selectedColors = ponyTintContainerColors(Primary, strong = true)
    val normalColors = ponyNeutralContainerColors()
    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(999.dp),
        color = if (selected) selectedColors.container else normalColors.container,
        border = BorderStroke(
            1.dp,
            if (selected) selectedColors.border else normalColors.border
        )
    ) {
        Text(
            text,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 8.dp),
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) selectedColors.content else normalColors.content,
            maxLines = 1,
            textAlign = TextAlign.Center
        )
    }
}

@Composable
internal fun EmptyTasksState() {
    val emptyColors = ponyNeutralContainerColors(strong = true)
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = emptyColors.container,
        border = BorderStroke(1.dp, emptyColors.border)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 34.dp, horizontal = 18.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                Icons.Filled.NotificationsActive,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.45f)
            )
            Text("还没有定时任务", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                "在聊天里说“十分钟后提醒我”，也会自动整理到这里",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.75f)
            )
        }
    }
}

@Composable
internal fun TaskCardDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 16.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.08f)
    )
}

@Composable
internal fun TaskEditItem(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    keyboardType: KeyboardType = KeyboardType.Text
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.width(86.dp)
        )
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .weight(1f)
                .focusAwareBringIntoView(delayMillis = 120L),
            textStyle = MaterialTheme.typography.titleSmall.copy(
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.End
            ),
            singleLine = true,
            cursorBrush = SolidColor(Primary),
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
            decorationBox = { innerTextField ->
                Box(contentAlignment = Alignment.CenterEnd) {
                    if (value.isEmpty()) {
                        Text(
                            placeholder,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                            style = MaterialTheme.typography.titleSmall,
                            textAlign = TextAlign.End
                        )
                    }
                    innerTextField()
                }
            }
        )
    }
}

@Composable
internal fun TaskEditBlock(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = ""
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall
        )
        Spacer(Modifier.height(8.dp))
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 56.dp)
                .focusAwareBringIntoView(delayMillis = 120L),
            textStyle = MaterialTheme.typography.titleSmall.copy(
                color = MaterialTheme.colorScheme.onBackground
            ),
            cursorBrush = SolidColor(Primary),
            decorationBox = { innerTextField ->
                Box(modifier = Modifier.fillMaxWidth()) {
                    if (value.isEmpty()) {
                        Text(
                            placeholder,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                            style = MaterialTheme.typography.titleSmall
                        )
                    }
                    innerTextField()
                }
            }
        )
    }
}

@Composable
internal fun ProactiveTaskItem(
    task: ProactiveTask,
    busy: Boolean,
    onToggle: () -> Unit,
    onDelete: () -> Unit
) {
    val enabledIconColors = ponyTintContainerColors(Primary, strong = true)
    val pausedIconColors = ponyNeutralContainerColors()
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(verticalAlignment = Alignment.Top) {
                Box(
                    modifier = Modifier
                        .size(38.dp)
                        .background(
                            if (task.enabled) enabledIconColors.container else pausedIconColors.container,
                            CircleShape
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        if (task.enabled) Icons.Filled.NotificationsActive else Icons.Filled.PauseCircle,
                        contentDescription = null,
                        tint = if (task.enabled) enabledIconColors.content else pausedIconColors.content,
                        modifier = Modifier.size(21.dp)
                    )
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        task.title.ifBlank { task.taskTypeLabel() },
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(Modifier.height(3.dp))
                    Text(
                        task.prompt,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                IconButton(
                    onClick = onDelete,
                    enabled = !busy,
                    modifier = Modifier.size(38.dp)
                ) {
                    Icon(
                        Icons.Filled.Delete,
                        contentDescription = "删除",
                        tint = MaterialTheme.colorScheme.error.copy(alpha = if (busy) 0.35f else 0.85f)
                    )
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                TaskChip(text = task.scheduleTypeLabel())
                Spacer(Modifier.width(8.dp))
                TaskChip(text = "下次 ${formatTaskTime(task)}")
                Spacer(Modifier.weight(1f))
                Text(
                    if (task.runCount > 0) "已执行 ${task.runCount} 次" else if (task.enabled) "等待中" else "已暂停",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.width(8.dp))
                Switch(
                    checked = task.enabled,
                    onCheckedChange = { onToggle() },
                    enabled = !busy
                )
            }
        }
    }
}

@Composable
private fun TaskChip(text: String) {
    val chipColors = ponyNeutralContainerColors()
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = chipColors.container,
        border = BorderStroke(1.dp, chipColors.border)
    ) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp),
            style = MaterialTheme.typography.labelSmall,
            color = chipColors.content,
            maxLines = 1
        )
    }
}
