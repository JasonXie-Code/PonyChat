package top.ponychat.webview.ui.chat

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.ConversationSceneResponse
import top.ponychat.webview.ui.common.SkeletonBlock
import top.ponychat.webview.ui.common.loadingSemantics

@Composable
internal fun SceneStatusContent(
    visible: ConversationSceneResponse?,
    loading: Boolean,
    error: String?,
    conversationId: String?,
    userName: String,
    characterName: String,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(top = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 12.dp)
                .heightIn(min = 48.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("当前场景", modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Surface(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surface,
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        ) {
            Column(modifier = Modifier.animateContentSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("对话类型：${sceneInteractionLabel(visible?.fields?.get("interaction_mode"))}",
                    style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                when {
                    visible != null && visible.fields.keys.any { it != "interaction_mode" } ->
                        SceneStatusRows(visible.fields, userName, characterName)
                    loading -> Column(Modifier.loadingSemantics(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        repeat(6) {
                            Row(modifier = Modifier.heightIn(min = 40.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                SkeletonBlock(Modifier.width(120.dp).height(16.dp))
                                SkeletonBlock(Modifier.weight(1f).height(40.dp))
                            }
                        }
                    }
                    error != null -> Text(error!!, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    conversationId.isNullOrBlank() -> Text("开始对话后显示场景状态", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else -> Text("暂无已确认的场景状态", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Text("剧情时间与地点来自已确认的对话内容，与设备时间或定位无关。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun SceneStatusRows(fields: Map<String, String?>, userName: String, characterName: String) {
    val user = userName.trim().ifBlank { "用户" }
    val character = characterName.trim().ifBlank { "角色" }
    val rows = listOf(
        "scene_time" to "剧情时间", "location" to "地点",
        "user_position" to "${user}姿势", "character_position" to "${character}姿势",
        "contact" to "接触状态", "surroundings" to "周围环境",
    )
    rows.forEach { (key, label) ->
        SceneStatusRow(label, objectiveSceneValue(fields[key], user, character))
    }
    fields.filterKeys { it.startsWith("item:") }.toSortedMap().forEach { (key, value) ->
        SceneStatusRow(objectiveSceneValue(key.removePrefix("item:"), user, character),
            objectiveSceneValue(value, user, character))
    }
}

@Composable
private fun SceneStatusRow(label: String, value: String) {
    Row(modifier = Modifier.heightIn(min = 40.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, modifier = Modifier.width(120.dp), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
    }
}
