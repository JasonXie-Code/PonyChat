package top.ponychat.webview.ui.character

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.focusAwareBringIntoView
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ScaledIcon as Icon

@Composable
internal fun SettingsCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
        )
    ) {
        Column(content = content)
    }
}

@Composable
internal fun CardDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 16.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.08f)
    )
}

@Composable
internal fun CardSectionTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f),
        modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp)
    )
}

@Composable
internal fun CardSectionTitleWithCount(text: String, charCount: Int) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
        )
        Text(
            text = "$charCount 字",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.6f)
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MbtiSelector(
    value: String,
    enabled: Boolean,
    onValueChange: (String) -> Unit,
    onDisabledClick: () -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val selected = mbtiDisplay(value)
    val selectedCode = value.trim().uppercase()
    val menuContainer = adaptivePopupMenuContainerColor()
    val menuContent = adaptivePopupMenuContentColor()
    val menuAccent = adaptivePopupMenuAccentColor()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable {
                if (enabled) expanded = true else onDisabledClick()
            }
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "16人格",
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.width(80.dp)
        )
        ExposedDropdownMenuBox(
            expanded = expanded,
            onExpandedChange = { if (enabled) expanded = !expanded },
            modifier = Modifier.weight(1f)
        ) {
            Text(
                text = selected.ifBlank { "选择人格类型" },
                color = if (selected.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant.copy(0.45f)
                    else MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.titleSmall,
                textAlign = TextAlign.End,
                modifier = Modifier
                    .fillMaxWidth()
                    .menuAnchor()
            )
            ExposedDropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                shape = RoundedCornerShape(14.dp),
                containerColor = menuContainer,
                border = adaptivePopupMenuBorder()
            ) {
                DropdownMenuItem(
                    text = {
                        Text(
                            "不展示",
                            color = if (selectedCode.isBlank()) menuAccent else menuContent,
                            fontWeight = if (selectedCode.isBlank()) FontWeight.SemiBold else FontWeight.Normal
                        )
                    },
                    leadingIcon = {
                        Icon(
                            Icons.Filled.VisibilityOff,
                            contentDescription = null,
                            tint = if (selectedCode.isBlank()) menuAccent else menuContent.copy(alpha = 0.75f)
                        )
                    },
                    trailingIcon = if (selectedCode.isBlank()) {
                        { Icon(Icons.Filled.Check, contentDescription = null, tint = menuAccent, modifier = Modifier.size(18.dp)) }
                    } else null,
                    onClick = {
                        onValueChange("")
                        expanded = false
                    }
                )
                mbtiOptions.forEach { option ->
                    val isSelected = selectedCode == option.code
                    DropdownMenuItem(
                        text = {
                            Column {
                                Text(
                                    "${option.code} · ${option.name}",
                                    color = if (isSelected) menuAccent else menuContent,
                                    fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal
                                )
                                Text(
                                    option.traits,
                                    color = if (isSelected) menuAccent.copy(alpha = 0.82f) else menuContent.copy(alpha = 0.62f),
                                    style = MaterialTheme.typography.labelSmall
                                )
                            }
                        },
                        leadingIcon = {
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = if (isSelected) menuAccent.copy(alpha = 0.16f) else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.08f)
                            ) {
                                Text(
                                    option.code.take(2),
                                    modifier = Modifier.padding(horizontal = 7.dp, vertical = 4.dp),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = if (isSelected) menuAccent else menuContent.copy(alpha = 0.75f),
                                    fontWeight = FontWeight.Bold
                                )
                            }
                        },
                        trailingIcon = if (isSelected) {
                            { Icon(Icons.Filled.Check, contentDescription = null, tint = menuAccent, modifier = Modifier.size(18.dp)) }
                        } else null,
                        onClick = {
                            onValueChange(option.code)
                            expanded = false
                        }
                    )

}
            }
        }
    }
}


@Composable
internal fun EditItem(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    isError: Boolean = false,
    enabled: Boolean = true,
    onDisabledClick: () -> Unit = {}
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!enabled) Modifier.clickable { onDisabledClick() } else Modifier)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            color = if (isError) ErrorColor else MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.width(80.dp)
        )
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            enabled = enabled,
            modifier = Modifier
                .weight(1f)
                .focusAwareBringIntoView(),
            textStyle = MaterialTheme.typography.titleSmall.copy(
                color = if (enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f),
                textAlign = TextAlign.End
            ),
            singleLine = true,
            cursorBrush = SolidColor(Primary),
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


private data class MbtiOption(val code: String, val name: String, val traits: String)

private val mbtiOptions = listOf(
    MbtiOption("INTJ", "建筑师", "战略 / 独立 / 洞察"),
    MbtiOption("INTP", "逻辑学家", "理性 / 好奇 / 分析"),
    MbtiOption("ENTJ", "指挥官", "果断 / 目标感 / 领导"),
    MbtiOption("ENTP", "辩论家", "机敏 / 创意 / 挑战"),
    MbtiOption("INFJ", "提倡者", "理想 / 共情 / 深刻"),
    MbtiOption("INFP", "调停者", "温柔 / 理想主义 / 共情"),
    MbtiOption("ENFJ", "主人公", "热忱 / 鼓舞 / 亲和"),
    MbtiOption("ENFP", "竞选者", "自由 / 热情 / 想象力"),
    MbtiOption("ISTJ", "物流师", "可靠 / 秩序 / 负责"),
    MbtiOption("ISFJ", "守卫者", "体贴 / 稳定 / 守护"),
    MbtiOption("ESTJ", "总经理", "务实 / 组织 / 执行"),
    MbtiOption("ESFJ", "执政官", "友善 / 照顾 / 合群"),
    MbtiOption("ISTP", "鉴赏家", "冷静 / 动手 / 灵活"),
    MbtiOption("ISFP", "探险家", "敏感 / 审美 / 自由"),
    MbtiOption("ESTP", "企业家", "行动 / 直接 / 冒险"),
    MbtiOption("ESFP", "表演者", "活泼 / 感受力 / 快乐")
)

private fun mbtiDisplay(code: String): String {
    val normalized = code.trim().uppercase()
    val option = mbtiOptions.firstOrNull { it.code == normalized } ?: return ""
    return "${option.code} · ${option.name}"
}

@Composable
internal fun MultilineEditItem(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    minLines: Int = 2,
    maxLines: Int = Int.MAX_VALUE,
    enabled: Boolean = true,
    onDisabledClick: () -> Unit = {}
) {
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!enabled) Modifier.clickable { onDisabledClick() } else Modifier)
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .focusAwareBringIntoView(),
        textStyle = MaterialTheme.typography.bodyMedium.copy(
            color = if (enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.65f),
            lineHeight = 20.sp
        ),
        cursorBrush = SolidColor(Primary),
        minLines = minLines,
        maxLines = maxLines,
        decorationBox = { innerTextField ->
            Box {
                if (value.isEmpty()) {
                    Text(
                        placeholder,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.4f),
                        style = MaterialTheme.typography.bodyMedium,
                        lineHeight = 20.sp
                    )
                }
                innerTextField()
            }
        }
    )
}

