package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun MessageSearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
    focusRequester: FocusRequester,
    modifier: Modifier = Modifier
) {
    PonyTopSearchBar(
        value = query,
        onValueChange = onQueryChange,
        placeholder = "搜索聊天记录…",
        focusRequester = focusRequester,
        modifier = modifier
    )
}

@Composable
internal fun FiltersDropdownRow(
    senderFilter: String,
    onSenderChange: (String) -> Unit,
    dateFilter: String,
    onDateChange: (String) -> Unit,
    contentFilter: String = "all",
    onContentChange: ((String) -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    val senderOptions = listOf("all" to "全部人", "user" to "我", "character" to "角色")
    val dateOptions = listOf("all" to "全部时间", "today" to "今天", "week" to "本周", "month" to "本月")

    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        CompactDropdown(
            label = senderOptions.first { it.first == senderFilter }.second,
            options = senderOptions,
            selected = senderFilter,
            onSelect = onSenderChange
        )
        CompactDropdown(
            label = dateOptions.first { it.first == dateFilter }.second,
            options = dateOptions,
            selected = dateFilter,
            onSelect = onDateChange
        )
        if (onContentChange != null) {
            val options = listOf("all" to "全部", "text" to "文本", "image" to "图片")
            CompactDropdown(options.first { it.first == contentFilter }.second,
                options, contentFilter, onContentChange)
        }
    }
}

@Composable
private fun CompactDropdown(
    label: String,
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val isFiltered = options.first().first != selected

    Box {
        Surface(
            onClick = { expanded = true },
            shape = RoundedCornerShape(16.dp),
            color = if (isFiltered) Primary.copy(0.12f) else MaterialTheme.colorScheme.surfaceVariant.copy(0.6f),
            border = if (isFiltered) BorderStroke(1.dp, Primary.copy(0.4f)) else null
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(3.dp)
            ) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isFiltered) Primary else MaterialTheme.colorScheme.onSurfaceVariant
                )
                Icon(
                    Icons.Filled.ArrowDropDown,
                    contentDescription = null,
                    modifier = Modifier.size(14.dp),
                    tint = if (isFiltered) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(0.7f)
                )
            }
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            shape = RoundedCornerShape(12.dp),
            containerColor = historyActionMenuContainerColor(),
            border = historyActionMenuBorder(),
            tonalElevation = 2.dp
        ) {
            options.forEach { (value, text) ->
                DropdownMenuItem(
                    text = {
                        Text(
                            text,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (value == selected) adaptivePopupMenuAccentColor() else historyActionMenuContentColor(),
                            fontWeight = if (value == selected) FontWeight.SemiBold else FontWeight.Normal
                        )
                    },
                    onClick = { onSelect(value); expanded = false },
                    trailingIcon = if (value == selected) ({
                        Icon(Icons.Filled.Check, null, modifier = Modifier.size(14.dp), tint = adaptivePopupMenuAccentColor())
                    }) else null
                )
            }
        }
    }
}
