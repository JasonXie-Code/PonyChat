package top.ponychat.webview.ui.chat

import androidx.compose.runtime.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.collect
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.ConversationSceneResponse
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ChatEventBus

/** The server scene card describes the story, never the device's real time or location. */
@Composable
internal fun SceneStatusCard(
    prefs: AppPreferences,
    characterId: String,
    conversationId: String?,
    userName: String,
    characterName: String,
    preview: ConversationSceneResponse? = null,
) {
    val baseUrl = prefs.effectiveApiBase()
    val username = prefs.username
    val api = remember(baseUrl, username) {
        NetworkClient.createApiService(prefs)
    }
    var scene by remember(baseUrl, username, characterId, conversationId) { mutableStateOf<ConversationSceneResponse?>(null) }
    var loading by remember(baseUrl, username, characterId, conversationId) { mutableStateOf(preview == null && !conversationId.isNullOrBlank() && characterId.isNotBlank()) }
    var error by remember(baseUrl, username, characterId, conversationId) { mutableStateOf<String?>(null) }
    var completedRevision by remember(baseUrl, username, characterId, conversationId) { mutableStateOf(0) }

    LaunchedEffect(baseUrl, username, characterId, conversationId, preview) {
        if (preview != null) return@LaunchedEffect
        ChatEventBus.completedFlow.collect { event ->
            if (event.characterId == characterId && event.mode == "normal" &&
                (event.conversationId == null || event.conversationId == conversationId)) {
                completedRevision += 1
            }
        }
    }

    LaunchedEffect(baseUrl, username, characterId, conversationId, preview, completedRevision) {
        if (preview != null) return@LaunchedEffect
        if (characterId.isBlank() || conversationId.isNullOrBlank()) return@LaunchedEffect
        loading = true
        error = null
        try {
            val result = withTimeout(10_000L) {
                api.getConversationScene(characterId, conversationId)
            }
            if (result.isSuccessful) {
                scene = result.body()
                if (scene == null) error = "暂时无法读取场景状态"
            } else {
                scene = null
                error = if (result.code() == 404) "当前对话没有可用的场景状态" else "暂时无法读取场景状态"
            }
        } catch (_: TimeoutCancellationException) {
            scene = null
            error = "场景状态读取超时，请稍后重新打开对话设置"
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            scene = null
            error = "暂时无法读取场景状态"
        } finally {
            loading = false
        }
    }

    SceneStatusContent(preview ?: scene, loading, error, conversationId, userName, characterName)
}
