package top.ponychat.webview.ui.chat

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.RelationshipRefreshRequest
import top.ponychat.webview.util.toUserMessage

fun ChatViewModel.loadRelationshipSnapshot(force: Boolean = false) {
    val stateNow = _state.value
    val characterId = stateNow.character?.id?.takeIf { it.isNotBlank() } ?: return
    val conversationId = stateNow.conversationId?.takeIf { it.isNotBlank() }
    val existing = stateNow.relationshipSnapshot
    if (!force && existing?.pageContent != null &&
        existing.characterId == characterId && existing.conversationId == conversationId &&
        existing.currentMessageCount == stateNow.messages.size &&
        !stateNow.isLoadingRelationshipSnapshot
    ) return
    if (stateNow.isLoadingRelationshipSnapshot) return

    _state.value = stateNow.copy(
        isLoadingRelationshipSnapshot = true,
        hasLoadedRelationshipSnapshot = stateNow.hasLoadedRelationshipSnapshot || existing != null,
        relationshipSnapshotError = null
    )
    relationshipSnapshotJob?.cancel()
    relationshipSnapshotJob = viewModelScope.launch {
        try {
            val api = NetworkClient.createApiService(prefs)
            val body = withTimeout(35_000L) {
                var response = if (force) {
                    api.refreshRelationshipState(RelationshipRefreshRequest(
                        username = prefs.username, characterId = characterId, conversationId = conversationId))
                } else {
                    api.getRelationshipState(username = prefs.username, characterId = characterId)
                }
                check(response.isSuccessful) { "关系信息加载失败，请下拉重试" }
                var result = checkNotNull(response.body()) { "关系信息加载失败，请下拉重试" }
                while (result.generationStatus in setOf("queued", "running")) {
                    delay(750)
                    if (_state.value.character?.id != characterId) {
                        throw CancellationException("Relationship character changed")
                    }
                    response = api.getRelationshipState(username = prefs.username, characterId = characterId)
                    check(response.isSuccessful) { "关系信息加载失败，请下拉重试" }
                    result = checkNotNull(response.body()) { "关系信息加载失败，请下拉重试" }
                }
                result
            }
            if (_state.value.character?.id != characterId) return@launch
            val stage = normalizeRelationshipStageKey(body.relationshipStage)
            val error = when (body.generationStatus) {
                "failed" -> "关系内容暂未整理完成，请下拉重试"
                "disabled" -> "开启记忆功能后可整理关系内容"
                "no_history" -> "聊一聊之后，这里会记录我们的关系"
                else -> null
            }
            // The server page contains every displayed section. Fetching all
            // memories and full conversations here only delays its presentation.
            val snapshot = existing?.takeIf { it.characterId == characterId } ?: RelationshipSnapshot(
                characterId = characterId, conversationId = conversationId,
                stageLabel = relationshipStageCn(stage),
                conversationCount = if (conversationId != null) 1 else 0,
                currentMessageCount = stateNow.messages.size,
                totalMessageCount = stateNow.messages.size, memoryCount = 0
            )
            _state.value = _state.value.copy(
                isLoadingRelationshipSnapshot = false,
                hasLoadedRelationshipSnapshot = true,
                relationshipSnapshotError = error,
                relationshipSnapshot = snapshot.copy(
                    conversationId = conversationId, stageKey = stage,
                    stageLabel = relationshipStageCn(stage),
                    currentMessageCount = stateNow.messages.size,
                    pageContent = body.relationshipPage,
                    pageUpdatedAtMs = body.relationshipPageUpdatedAtMs
                )
            )
        } catch (error: Exception) {
            if (error is CancellationException && error !is TimeoutCancellationException) throw error
            if (_state.value.character?.id == characterId) {
                _state.value = _state.value.copy(
                    isLoadingRelationshipSnapshot = false,
                    hasLoadedRelationshipSnapshot = true,
                    relationshipSnapshot = null,
                    relationshipSnapshotError = if (error is TimeoutCancellationException)
                        "关系内容仍在整理，请稍后下拉刷新" else error.toUserMessage("关系信息加载失败，请下拉重试")
                )
            }
        }
    }
}

/** 本机调试：切换关系页阶段预览（只改当前 App 内存状态，不请求后端、不写服务器）。 */
fun ChatViewModel.debugSetLocalRelationshipStage(stage: String) {
    val normalized = normalizeRelationshipStageKey(stage)
    _state.value = _state.value.copy(relationshipStageOverride = normalized)
    viewModelScope.launch {
        _snackbarMessages.emit("本地关系阶段：${relationshipStageCn(normalized)}")
    }
}

fun ChatViewModel.debugUseServerRelationshipStage() {
    _state.value = _state.value.copy(relationshipStageOverride = null)
    viewModelScope.launch {
        _snackbarMessages.emit("已恢复服务器关系数据")
    }
}
