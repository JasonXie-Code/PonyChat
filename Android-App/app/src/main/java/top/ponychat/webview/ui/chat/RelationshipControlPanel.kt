package top.ponychat.webview.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.adaptivePopupMenuAccentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.theme.Primary

@Composable
internal fun RelationshipControlPanel(
    selectedStage: String?,
    currentStage: String,
    enabled: Boolean,
    onSelect: (String?) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val menuContainer = adaptivePopupMenuContainerColor()
    val menuContent = adaptivePopupMenuContentColor()
    val menuAccent = adaptivePopupMenuAccentColor()
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("关系控制", style = MaterialTheme.typography.labelLarge)
            Box {
                Row(
                    Modifier.fillMaxWidth().clickable(enabled = enabled, role = Role.Button,
                        onClickLabel = "选择当前关系") { expanded = true }.padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(selectedStage?.let(::relationshipStageCn) ?: "系统决定（默认）",
                        modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge, color = Primary)
                    Icon(Icons.Default.ExpandMore, contentDescription = "选择当前关系", tint = Primary)
                }
                DropdownMenu(
                    expanded = expanded && enabled,
                    onDismissRequest = { expanded = false },
                    modifier = Modifier.widthIn(min = 196.dp),
                    shape = RoundedCornerShape(12.dp),
                    containerColor = menuContainer,
                    border = adaptivePopupMenuBorder(),
                    tonalElevation = 2.dp,
                ) {
                    listOf<String?>(null).plus(RELATIONSHIP_STAGE_KEYS).forEach { stage ->
                        val isSelected = stage == selectedStage
                        DropdownMenuItem(
                            text = {
                                Text(
                                    stage?.let(::relationshipStageCn) ?: "系统决定（默认）",
                                    color = if (isSelected) menuAccent else menuContent,
                                    fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                                )
                            },
                            trailingIcon = if (isSelected) {
                                {
                                    Icon(
                                        Icons.Filled.Check,
                                        contentDescription = "当前关系",
                                        tint = menuAccent,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            } else null,
                            onClick = { onSelect(stage); expanded = false },
                        )
                    }
                }
            }
            Text(
                if (selectedStage == null) "当前：${relationshipStageCn(currentStage)} · 随互动由系统判断"
                else "由你指定，系统不会更改；选择“系统决定”可恢复自动判断。",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
