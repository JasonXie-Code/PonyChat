package top.ponychat.webview.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.character.CharacterAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.PonyTopBarBackButton
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.ponyNeutralContainerColors
import top.ponychat.webview.ui.theme.ponyTintContainerColors

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MemoryTopBar(
    character: Character,
    prefs: AppPreferences,
    memoryCount: Int,
    selectedLayer: Int,
    onNavigateBack: () -> Unit
) {
    val layerCfg = LAYER_TABS[selectedLayer]
    PonyTopBar(containerColor = MaterialTheme.colorScheme.background) {
        PonyTopBarBackButton(
            onClick = onNavigateBack,
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.width(4.dp))
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically
        ) {
            CharacterAvatar(
                avatarUrl = character.avatarUrl(),
                name = character.displayName(),
                apiBase = prefs.effectiveApiBase(),
                size = 28
            )
            Spacer(Modifier.width(10.dp))
            Column {
                Text(
                    "长期记忆",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Surface(
                        shape = RoundedCornerShape(4.dp),
                        color = layerCfg.color.copy(0.15f)
                    ) {
                        Text(
                            layerCfg.label,
                            style = MaterialTheme.typography.labelSmall,
                            color = layerCfg.color,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp)
                        )
                    }
                    if (memoryCount > 0) {
                        Text(
                            "·",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(0.5f)
                        )
                        Text(
                            "$memoryCount 条",
                            style = MaterialTheme.typography.labelSmall,
                            color = Primary.copy(0.8f)
                        )
                    }
                }
            }
        }
    }
}

@Composable
internal fun LayerTabBar(
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(7.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        LAYER_TABS.forEach { cfg ->
            val sel = selected == cfg.layer
            val selectedColors = ponyTintContainerColors(cfg.color, strong = true)
            val normalColors = ponyNeutralContainerColors()
            Surface(
                onClick = { onSelect(cfg.layer) },
                shape = RoundedCornerShape(20.dp),
                color = if (sel) selectedColors.container else normalColors.container,
                border = BorderStroke(1.dp, if (sel) selectedColors.border else normalColors.border)
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    Icon(
                        cfg.icon,
                        contentDescription = null,
                        tint = if (sel) selectedColors.content else normalColors.content,
                        modifier = Modifier.size(13.dp)
                    )
                    Text(
                        cfg.label,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = if (sel) FontWeight.SemiBold else FontWeight.Normal,
                        color = if (sel) selectedColors.content else normalColors.content
                    )
                }
            }
        }
    }
}

@Composable
internal fun FragmentTypeFilterBar(
    selected: String?,
    onSelect: (String?) -> Unit,
    modifier: Modifier = Modifier
) {
    var expanded by remember { mutableStateOf(false) }
    val selectedCfg = if (selected == null) null else FRAGMENT_TYPES.find { it.key == selected }
    val isFiltered = selected != null
    val chipColor = selectedCfg?.color ?: Primary
    val selectedColors = ponyTintContainerColors(chipColor, strong = true)
    val normalColors = ponyNeutralContainerColors()

    Box(modifier = modifier) {
        Surface(
            onClick = { expanded = true },
            shape = RoundedCornerShape(16.dp),
            color = if (isFiltered) selectedColors.container else normalColors.container,
            border = BorderStroke(1.dp, if (isFiltered) selectedColors.border else normalColors.border)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Icon(
                    if (selectedCfg != null) selectedCfg.icon else Icons.Filled.Apps,
                    contentDescription = null,
                    tint = if (isFiltered) selectedColors.content else normalColors.content,
                    modifier = Modifier.size(14.dp)
                )
                Text(
                    text = selectedCfg?.label ?: "全部类型",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isFiltered) selectedColors.content else normalColors.content,
                    fontWeight = if (isFiltered) FontWeight.SemiBold else FontWeight.Normal
                )
                Icon(
                    Icons.Filled.ArrowDropDown,
                    contentDescription = null,
                    modifier = Modifier.size(14.dp),
                    tint = if (isFiltered) selectedColors.content else normalColors.content
                )
            }
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            shape = RoundedCornerShape(12.dp),
            containerColor = adaptivePopupMenuContainerColor(),
            border = adaptivePopupMenuBorder(),
            tonalElevation = 2.dp
        ) {
            DropdownMenuItem(
                text = {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(
                            Icons.Filled.Apps,
                            null,
                            modifier = Modifier.size(14.dp),
                            tint = if (!isFiltered) adaptivePopupMenuAccentColor() else adaptivePopupMenuContentColor()
                        )
                        Text(
                            "全部类型",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (!isFiltered) adaptivePopupMenuAccentColor() else adaptivePopupMenuContentColor(),
                            fontWeight = if (!isFiltered) FontWeight.SemiBold else FontWeight.Normal
                        )
                    }
                },
                onClick = {
                    onSelect(null)
                    expanded = false
                },
                trailingIcon = if (!isFiltered) {
                    {
                        Icon(
                            Icons.Filled.Check,
                            null,
                            modifier = Modifier.size(14.dp),
                            tint = adaptivePopupMenuAccentColor()
                        )
                    }
                } else {
                    null
                }
            )
            FRAGMENT_TYPES.forEach { cfg ->
                val isSelected = selected == cfg.key
                DropdownMenuItem(
                    text = {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(cfg.icon, null, modifier = Modifier.size(14.dp), tint = cfg.color)
                            Text(
                                cfg.label,
                                style = MaterialTheme.typography.bodySmall,
                                color = if (isSelected) cfg.color else adaptivePopupMenuContentColor(),
                                fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal
                            )
                        }
                    },
                    onClick = {
                        onSelect(if (isSelected) null else cfg.key)
                        expanded = false
                    },
                    trailingIcon = if (isSelected) {
                        {
                            Icon(
                                Icons.Filled.Check,
                                null,
                                modifier = Modifier.size(14.dp),
                                tint = cfg.color
                            )
                        }
                    } else {
                        null
                    }
                )
            }
        }
    }
}
