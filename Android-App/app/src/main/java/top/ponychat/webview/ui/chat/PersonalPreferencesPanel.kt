package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.semantics.Role
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyButtonStyle
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.theme.Primary
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.model.RelationshipControlRequest

/** 云端以账号 / 角色 / 模式隔离；仅提交当前项，避免覆盖其他设置。 */
@Composable
internal fun PersonalPreferencesPanel(
    prefs: AppPreferences,
    characterId: String,
    characterName: String,
    mode: String,
    onDismiss: () -> Unit,
    onExitActionChanged: ((() -> Unit)?) -> Unit,
    onRelationshipChanged: () -> Unit = {},
) {
    val username = prefs.username
    val api = remember(prefs, username) { NetworkClient.createApiService(prefs) }
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var originalText by remember { mutableStateOf("") }
    var selectedStage by remember { mutableStateOf<String?>(null) }
    var originalStage by remember { mutableStateOf<String?>(null) }
    var currentStage by remember { mutableStateOf("uncertain") }
    var languageStyle by remember { mutableStateOf("default") }
    var originalLanguageStyle by remember { mutableStateOf("default") }
    var loading by remember { mutableStateOf(true) }
    var loaded by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var retry by remember { mutableIntStateOf(0) }
    var helpExpanded by remember(prefs) { mutableStateOf(prefs.personalPreferencesHelpExpanded) }
    val modeName = when (mode) {
        "galgame" -> "游戏"
        "galgame_lock" -> "锁分"
        else -> "普通聊天"
    }
    LaunchedEffect(username, characterId, mode, retry) {
        loading = true
        error = null
        try {
            check(username.isNotBlank() && characterId.isNotBlank()) { "无法识别当前账号或角色" }
            val response = api.getSettings(username)
            val body = response.body()
            check(response.isSuccessful && body?.get("success") == true) { "加载失败，请重试" }
            val settings = body?.get("settings") as? Map<*, *>
            val characters = settings?.get("personal_preferences") as? Map<*, *>
            val modes = characters?.get(characterId) as? Map<*, *>
            text = modes?.get(mode) as? String ?: ""
            originalText = text
            val styles = settings?.get("sexual_language_style") as? Map<*, *>
            val characterStyles = styles?.get(characterId) as? Map<*, *>
            languageStyle = characterStyles?.get(mode) as? String ?: "default"
            if (languageStyle !in sexualLanguageStyleKeys) languageStyle = "default"
            originalLanguageStyle = languageStyle
            if (mode == "normal") {
                val relationship = api.getRelationshipState(username, characterId)
                val relation = relationship.body()
                check(relationship.isSuccessful && relation != null) { "关系设置加载失败，请重试" }
                currentStage = relation.relationshipStage
                selectedStage = if (relation.relationshipMode == "manual") relation.manualRelationshipStage else null
                originalStage = selectedStage
            }
            loaded = true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            error = e.message ?: "加载失败，请重试"
        } finally {
            loading = false
        }
    }
    val saveAndClose: () -> Unit = {
        if (!saving) {
            if (!loaded || (text.trim() == originalText.trim() && selectedStage == originalStage && languageStyle == originalLanguageStyle)) {
                onDismiss()
            } else {
                saving = true
                error = null
                scope.launch {
                    try {
                        if (text.trim() != originalText.trim()) {
                            val response = api.saveSettings(mapOf(
                                "username" to username,
                                "settings" to mapOf("personal_preferences" to mapOf(
                                    characterId to mapOf(mode to text.trim())
                                )),
                            ))
                            check(response.isSuccessful && response.body()?.success == true) { "保存失败，请再次关闭以重试" }
                            originalText = text
                        }
                        if (languageStyle != originalLanguageStyle) {
                            val response = api.saveSettings(mapOf("username" to username,
                                "settings" to mapOf("sexual_language_style" to mapOf(characterId to mapOf(mode to languageStyle)))))
                            check(response.isSuccessful && response.body()?.success == true) { "语言风格保存失败，请再次关闭以重试" }
                            originalLanguageStyle = languageStyle
                        }
                        if (mode == "normal" && selectedStage != originalStage) {
                            val response = api.updateRelationshipControl(RelationshipControlRequest(
                                username = username, characterId = characterId,
                                relationshipMode = if (selectedStage == null) "auto" else "manual",
                                relationshipStage = selectedStage,
                            ))
                            check(response.isSuccessful && response.body()?.status == "ok") { "关系保存失败，请再次关闭以重试" }
                            originalStage = selectedStage
                            onRelationshipChanged()
                        }
                        onDismiss()
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        error = e.message ?: "保存失败，请再次关闭以重试"
                    } finally {
                        saving = false
                    }
                }
            }
        }
    }
    val currentExit by rememberUpdatedState(saveAndClose)
    DisposableEffect(Unit) {
        onExitActionChanged { currentExit() }
        onDispose { onExitActionChanged(null) }
    }
    BackHandler { saveAndClose() }
    Column(
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
            .verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("个人偏好", style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onBackground)
                Text("$characterName · $modeName", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            PonyIconButton(onClick = saveAndClose, icon = Icons.Default.Close,
                contentDescription = "关闭个人偏好", enabled = !saving,
                tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (mode == "normal") {
            RelationshipControlPanel(selectedStage, currentStage, loaded && !saving) { selectedStage = it }
        }
        LanguageStyleControlPanel(languageStyle, loaded && !saving) { languageStyle = it }
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth().clickable(
                    role = Role.Button,
                    onClickLabel = if (helpExpanded) "收起填写说明" else "展开填写说明",
                ) {
                    helpExpanded = !helpExpanded
                    prefs.personalPreferencesHelpExpanded = helpExpanded
                }.padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("填写说明", modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(if (helpExpanded) "收起" else "展开", style = MaterialTheme.typography.labelLarge,
                    color = Primary)
                Icon(if (helpExpanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = null, tint = Primary, modifier = Modifier.size(20.dp))
            }
            if (helpExpanded) {
                Text("写下你的偏好，以及希望角色如何称呼你、说话和互动。仅对当前角色的当前模式生效，不同角色、不同模式分别保存。回复时优先参考，重置对话不会清除。",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (saving) LinearProgressIndicator(modifier = Modifier.fillMaxWidth(), color = Primary)
        PreferenceTextEditor(text, loaded && !saving) { text = it }
        Text("${text.length}/4000 · 退出自动保存，清空可取消偏好", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (!loaded && !loading) PonyButton(text = "重新加载", onClick = { retry++ }, style = PonyButtonStyle.Secondary)
    }
}
