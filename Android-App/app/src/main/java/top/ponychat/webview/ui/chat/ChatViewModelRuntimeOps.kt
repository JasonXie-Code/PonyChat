package top.ponychat.webview.ui.chat

import android.app.Application
import android.util.Log
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.repo.ChatDelta
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ClientContextHelper
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.GalgameNotificationPreview
import top.ponychat.webview.util.MessageVibrationHelper
import top.ponychat.webview.util.toUserMessage
import java.util.UUID

fun ChatViewModel.dismissGalgameSaveFailedDialog() {
    _state.value = _state.value.copy(galgameSaveFailed = false)
}

/** 手动触发立即同步（用于调试面板与恢复链路）。 */
fun ChatViewModel.forceSaveNow(reason: String = "manual_sync") {
    if (_state.value.character == null || _state.value.isStreaming) return
    _state.value = _state.value.copy(galgameSaveFailed = false, error = null, errorDebug = null)
    DebugLog.d(TAG, "[HistoryDebug] force server refresh: $reason")
    if (_state.value.mode == "normal") {
        refreshNewMessagesFromServer()
    } else {
        refreshConversationFromServer()
    }
}
// ==================== 对话参数（后端托管） ====================

fun ChatViewModel.updateChatSettings(settings: ChatSettings) {
    _state.value = _state.value.copy(chatSettings = settings)
}

fun ChatViewModel.summarizeContext() {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    if (_state.value.isSummarizingContext) return
    // 流式生成期间不执行总结，避免 sentMessages 被意外清空
    if (_state.value.isStreaming) return
    _state.value = _state.value.copy(isSummarizingContext = true, error = null)
    viewModelScope.launch {
        charRepo.summarizeContext(
            username = prefs.username,
            characterId = characterId,
            mode = _state.value.mode,
            conversationId = _state.value.conversationId
        ).onSuccess {
            _state.value = _state.value.copy(
                isSummarizingContext = false,
                error = null
            )
            // 摘要结果已持久化到后端，下次请求时会自动注入。
            // 仅在用户当前未流式生成时才刷新历史，避免清空 sentMessages 干扰进行中的对话。
            if (!_state.value.isStreaming) {
                loadConversationHistory(character)
            }
        }.onFailure { err ->
            DebugLog.w(TAG, "summarizeContext failed: ${err.message}", err)
            val msg = when {
                err.message?.contains("timeout", ignoreCase = true) == true ||
                err.message?.contains("timed out", ignoreCase = true) == true ->
                    "Summary timed out; it will continue in background."
                else -> err.toUserMessage("Summary failed")
            }
            _state.value = _state.value.copy(
                isSummarizingContext = false,
                error = msg
            )
        }
    }
}

fun ChatViewModel.debugForceSummarize() {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    if (_state.value.isSummarizingContext) return
    if (_state.value.isStreaming) return
    _state.value = _state.value.copy(isSummarizingContext = true, error = null)
    viewModelScope.launch {
        charRepo.summarizeContext(
            username = prefs.username,
            characterId = characterId,
            mode = _state.value.mode,
            conversationId = _state.value.conversationId,
            force = true
        ).onSuccess { result ->
            _state.value = _state.value.copy(isSummarizingContext = false, error = null)
            if (result["skipped"] == true) {
                val reason = result["reason"]?.toString().orEmpty()
                _snackbarMessages.emit(debugSummarizeSkippedMessage(reason))
                return@onSuccess
            }
            val mode = _state.value.mode
            val message = if (mode == "galgame" || mode == "galgame_lock") {
                "剧情记忆已折叠"
            } else {
                "上下文摘要已生成"
            }
            _snackbarMessages.emit(message)
            if (!_state.value.isStreaming) loadConversationHistory(character)
        }.onFailure { err ->
            DebugLog.w(TAG, "debugForceSummarize failed: ${err.message}", err)
            val msg = when {
                err.message?.contains("timeout", ignoreCase = true) == true ||
                err.message?.contains("timed out", ignoreCase = true) == true ->
                    "Summary timed out; please retry later."
                else -> err.toUserMessage("强制总结失败")
            }
            _state.value = _state.value.copy(
                isSummarizingContext = false,
                error = msg
            )
        }
    }
}

fun ChatViewModel.loadRelationshipSnapshot(force: Boolean = false) {
    val stateNow = _state.value
    val character = stateNow.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val conversationId = stateNow.conversationId?.takeIf { it.isNotBlank() }
    val existing = stateNow.relationshipSnapshot
    if (!force &&
        existing != null &&
        existing.characterId == characterId &&
        existing.conversationId == conversationId &&
        existing.currentMessageCount == stateNow.messages.size &&
        !stateNow.isLoadingRelationshipSnapshot
    ) {
        return
    }
    if (stateNow.isLoadingRelationshipSnapshot) return

    _state.value = stateNow.copy(
        isLoadingRelationshipSnapshot = true,
        hasLoadedRelationshipSnapshot = stateNow.hasLoadedRelationshipSnapshot || stateNow.relationshipSnapshot != null,
        relationshipSnapshotError = null
    )

    viewModelScope.launch {
        val username = prefs.username
        val api = NetworkClient.createApiService(prefs)
        val currentMessages = _state.value.messages

        val relationshipState = runCatching {
            val resp = if (force) {
                api.refreshRelationshipState(
                    RelationshipRefreshRequest(
                        username = username,
                        characterId = characterId,
                        conversationId = conversationId
                    )
                )
            } else {
                api.getRelationshipState(
                    username = username,
                    characterId = characterId
                )
            }
            if (!resp.isSuccessful) null else resp.body()
        }.getOrNull()
        val serverRelationshipStage = relationshipState
            ?.takeIf { it.updatedAtMs > 0L || it.relationshipPageUpdatedAtMs > 0L }
            ?.relationshipStage
            ?.let(::normalizeRelationshipStageKey)
        val pageContent = relationshipState
            ?.relationshipPage
            ?.takeIf { it.hasRelationshipPageContent() }

        val fragmentMemories = runCatching {
            val resp = api.getMemories(
                username = username,
                characterId = characterId,
                memoryType = null,
                layer = 0
            )
            if (!resp.isSuccessful) throw Exception("记忆加载失败 (${resp.code()})")
            resp.body()?.memories ?: emptyList()
        }

        val summaryMemories = runCatching {
            val resp = api.getMemories(
                username = username,
                characterId = characterId,
                memoryType = null,
                layer = 1
            )
            if (!resp.isSuccessful) emptyList() else resp.body()?.memories ?: emptyList()
        }.getOrDefault(emptyList())

        val conversations = charRepo.loadAllConversations(username, characterId, mode = "normal")
            .getOrElse { emptyList() }
        val currentConversation = conversationId?.let { id ->
            conversations.firstOrNull { it.id == id }
        } ?: conversations.firstOrNull()

        val fragments = fragmentMemories.getOrDefault(emptyList())
        val totalMessageCount = conversations.sumOf { it.messages.size }
            .takeIf { it > 0 }
            ?: currentMessages.size
        val currentMessageCount = when {
            currentMessages.isNotEmpty() -> currentMessages.size
            currentConversation != null -> currentConversation.messages.size
            else -> 0
        }
        val conversationCount = conversations.size
            .takeIf { it > 0 }
            ?: if (currentMessageCount > 0) 1 else 0
        val latestSummary = currentConversation?.effectiveSummary()
            ?.takeIf { it.isNotBlank() }
            ?: summaryMemories.firstOrNull()?.content.orEmpty()
        val fallbackStageKey = relationshipStageKey(totalMessageCount, fragments.size)
        val snapshotStageKey = serverRelationshipStage ?: fallbackStageKey

        if (_state.value.character?.id != characterId) return@launch

        fragmentMemories.fold(
            onSuccess = {
                _state.value = _state.value.copy(
                    isLoadingRelationshipSnapshot = false,
                    hasLoadedRelationshipSnapshot = true,
                    relationshipSnapshotError = null,
                    relationshipSnapshot = RelationshipSnapshot(
                        characterId = characterId,
                        conversationId = conversationId,
                        stageKey = snapshotStageKey,
                        stageLabel = relationshipStageCn(snapshotStageKey),
                        conversationCount = conversationCount,
                        currentMessageCount = currentMessageCount,
                        totalMessageCount = totalMessageCount,
                        memoryCount = fragments.size,
                        relationshipMemories = fragments.filter { it.memoryType == "relationship" },
                        preferenceMemories = fragments.filter { it.memoryType == "preference" },
                        episodeMemories = fragments.filter { it.memoryType == "episode" },
                        activityMemories = fragments.filter { it.memoryType == "activity" },
                        summaryMemories = summaryMemories,
                        latestSummary = latestSummary,
                        updatedAt = currentConversation?.updatedAt.orEmpty(),
                        pageContent = pageContent,
                        pageUpdatedAtMs = relationshipState?.relationshipPageUpdatedAtMs ?: 0L
                    )
                )
            },
            onFailure = { err ->
                _state.value = _state.value.copy(
                    isLoadingRelationshipSnapshot = false,
                    hasLoadedRelationshipSnapshot = true,
                    relationshipSnapshotError = err.toUserMessage("关系信息加载失败"),
                    relationshipSnapshot = RelationshipSnapshot(
                        characterId = characterId,
                        conversationId = conversationId,
                        stageKey = snapshotStageKey,
                        stageLabel = relationshipStageCn(snapshotStageKey),
                        conversationCount = conversationCount,
                        currentMessageCount = currentMessageCount,
                        totalMessageCount = totalMessageCount,
                        memoryCount = fragments.size,
                        summaryMemories = summaryMemories,
                        latestSummary = latestSummary,
                        updatedAt = currentConversation?.updatedAt.orEmpty(),
                        pageContent = pageContent,
                        pageUpdatedAtMs = relationshipState?.relationshipPageUpdatedAtMs ?: 0L
                    )
                )
            }
        )
    }
}

private fun relationshipStageKey(totalMessages: Int, memoryCount: Int): String = when {
    totalMessages >= 50 || memoryCount >= 12 -> "familiar"
    totalMessages > 0 || memoryCount > 0 -> "new_contact"
    else -> "uncertain"
}

private fun RelationshipPageContent.hasRelationshipPageContent(): Boolean =
    overview.isNotBlank() ||
        mood.isNotBlank() ||
        selfPortrait.isNotBlank() ||
        betweenPortrait.isNotBlank() ||
        rememberedItems.any { it.isNotBlank() } ||
        timelineItems.any { it.isNotBlank() } ||
        suggestions.any { it.isNotBlank() }

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

internal fun ChatViewModel.checkAndAutoSummarize() {
    val used = _state.value.contextUsedTokens
    val limit = _state.value.contextLimitTokens
    if (limit <= 0 || used <= 0) return
    // 正在流式生成时不触发，避免干扰 sentMessages 状态
    if (_state.value.isStreaming) return
    val ratio = used.toFloat() / limit.toFloat()
    if (ratio >= 0.92f && !_state.value.isSummarizingContext) {
        DebugLog.d(TAG, "Auto summarize triggered: $used/$limit tokens (${(ratio * 100).toInt()}%)")
        summarizeContext()
    }
}

/** 满分庆祝层展示后写入服务端，失败时回退 ack 以便重试 */
fun ChatViewModel.postGalgameVictoryAck() {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val mode = _state.value.mode
    if (!mode.startsWith("galgame")) return
    if (_state.value.galgameVictoryCelebrationAck) return
    _state.value = _state.value.copy(galgameVictoryCelebrationAck = true)
    viewModelScope.launch(Dispatchers.IO) {
        charRepo.postGalgameVictoryAck(prefs.username, characterId, mode).onFailure { err ->
            DebugLog.w(TAG, "postGalgameVictoryAck: ${err.message}", err)
            // 保持本地 ack=true，避免用户已看到庆祝层后因网络失败再次自动弹出
        }
    }
}

fun ChatViewModel.resetGalgameProgress() {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val mode = _state.value.mode
    if (!mode.startsWith("galgame")) return

    viewModelScope.launch(Dispatchers.IO) {
        charRepo.resetGalgame(
            username = prefs.username,
            characterId = characterId,
            mode = mode
        ).onSuccess {
            withContext(Dispatchers.Main) {
                newConversation()
                reloadConversation() // 使用 reloadConversation 以正确设置 isLoadingHistory 并触发 UI 更新
            }
        }.onFailure { err ->
            DebugLog.w(TAG, "resetGalgameProgress failed: ${err.message}", err)
            withContext(Dispatchers.Main) {
                val msg = err.toUserMessage("重置进度失败，请稍后重试")
                _state.value = _state.value.copy(error = msg)
                _snackbarMessages.tryEmit(msg)
            }
        }
    }
}

/** 本机调试：设置当前游戏分数（不请求后端）。 */
fun ChatViewModel.debugApplyLocalGalgameScore(target: Int, forceZeroInLock: Boolean = false) {
    val mode = _state.value.mode
    if (!mode.startsWith("galgame")) return
    var score = target.coerceIn(0, 100)
    if (mode == "galgame_lock" && score <= 0 && !forceZeroInLock) {
        score = 1
    }
    _state.value = _state.value.copy(
        galgameScore = score,
        error = null
    )
}

/** 本机调试：在当前分数基础上增减（不请求后端）。 */
fun ChatViewModel.debugAdjustLocalGalgameScore(delta: Int, forceZeroInLock: Boolean = false) {
    val current = (_state.value.galgameScore ?: 40)
    debugApplyLocalGalgameScore(current + delta, forceZeroInLock = forceZeroInLock)
}

/** 本机调试：向 UI 状态注入一条错误消息。 */
fun ChatViewModel.debugTriggerError(msg: String = "这是一条调试注入的错误消息") {
    _state.value = _state.value.copy(error = msg)
}

/** 本机调试：清除当前错误状态。 */
fun ChatViewModel.debugClearError() {
    _state.value = _state.value.copy(error = null)
}

/** 本机调试：在消息列表末尾注入一条 AI 消息（不请求后端）。 */
fun ChatViewModel.debugInjectAssistantMessage(content: String = "[debug] injected local assistant message, not saved to server") {
    val id = "debug_${System.currentTimeMillis()}"
    val fakeMsg = Message(
        id = id,
        role = "assistant",
        content = content,
        timestamp = System.currentTimeMillis(),
        messageId = id
    )
    val msgs = _state.value.messages.toMutableList()
    msgs.add(fakeMsg)
    _state.value = _state.value.copy(messages = msgs)
}

/** 本机调试：注入一条尚未被服务端 accepted 的用户消息，用于验证发送指示器。 */
fun ChatViewModel.debugInjectPendingUserAcceptMessage(timedOut: Boolean = false) {
    if (_state.value.mode != "normal") {
        _snackbarMessages.tryEmit("发送指示器仅用于普通对话模式")
        return
    }
    sentMessages.removeAll { it.messageId?.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) == true }
    unconfirmedNormalUserKeys.removeAll { it.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) }
    val now = System.currentTimeMillis()
    val startedAt = if (timedOut) now - 11_000L else now
    val id = "$DEBUG_PENDING_USER_ACCEPT_PREFIX$now"
    val content = if (timedOut) {
        "[debug] 这条用户消息模拟超过 10 秒仍未被服务器接受，点击左下角警示符号会重发。"
    } else {
        "[debug] 这条用户消息模拟正在等待服务器接受，10 秒后会变成警示符号。"
    }
    val msg = Message(
        id = id,
        role = "user",
        content = content,
        timestamp = now,
        messageId = id,
        isPendingServerAccept = true,
        pendingServerAcceptStartedAt = startedAt
    )
    _state.value = _state.value.copy(messages = _state.value.messages + msg)
    sentMessages.removeAll { it.messageId == id }
    unconfirmedNormalUserKeys.remove(id)
    _snackbarMessages.tryEmit(if (timedOut) "已注入超时警示用户消息" else "已注入发送中用户消息")
}

/** 本机调试：把当前等待 accepted 的用户消息标记为已接受，用于验证指示器消失。 */
fun ChatViewModel.debugAcceptPendingUserMessages() {
    sentMessages.removeAll { it.messageId?.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) == true }
    unconfirmedNormalUserKeys.removeAll { it.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) }
    markAllPendingUserMessagesAcceptedForDebug()
    _snackbarMessages.tryEmit("已标记待确认用户消息为已接受")
}

/** 本机调试：延时注入一条普通回复，用于验证底部自动跟随。 */
fun ChatViewModel.debugInjectDelayedNormalSingleMessage() {
    debugInjectDelayedAssistantScrollMessages(
        label = "普通回复",
        key = "normal",
        delivery = DebugScrollTestDelivery.Single
    )
}

/** 本机调试：延时瞬发三条普通回复，用于验证批量到达只滚动一次。 */
fun ChatViewModel.debugInjectDelayedNormalInstantTripleMessages() {
    debugInjectDelayedAssistantScrollMessages(
        label = "普通回复",
        key = "normal",
        delivery = DebugScrollTestDelivery.InstantTriple
    )
}

/** 本机调试：延时按 3 秒间隔注入三条普通回复，用于验证正常分条自动跟随。 */
fun ChatViewModel.debugInjectDelayedNormalIntervalTripleMessages() {
    debugInjectDelayedAssistantScrollMessages(
        label = "普通回复",
        key = "normal",
        delivery = DebugScrollTestDelivery.IntervalTriple
    )
}

/** 本机调试：延时注入一条主动消息，用于验证主动消息底部自动跟随。 */
fun ChatViewModel.debugInjectDelayedProactiveSingleMessage() {
    debugInjectDelayedAssistantScrollMessages(
        label = "主动消息",
        key = "proactive",
        delivery = DebugScrollTestDelivery.Single
    )
}

/** 本机调试：延时瞬发三条主动消息，用于验证批量到达只滚动一次。 */
fun ChatViewModel.debugInjectDelayedProactiveInstantTripleMessages() {
    debugInjectDelayedAssistantScrollMessages(
        label = "主动消息",
        key = "proactive",
        delivery = DebugScrollTestDelivery.InstantTriple
    )
}

/** 本机调试：延时按 3 秒间隔注入三条主动消息，用于验证正常分条自动跟随。 */
fun ChatViewModel.debugInjectDelayedProactiveIntervalTripleMessages() {
    debugInjectDelayedAssistantScrollMessages(
        label = "主动消息",
        key = "proactive",
        delivery = DebugScrollTestDelivery.IntervalTriple
    )
}

private fun ChatViewModel.debugInjectDelayedAssistantScrollMessages(
    label: String,
    key: String,
    delivery: DebugScrollTestDelivery
) {
    val startedAt = System.currentTimeMillis()
    val deliveryLabel = when (delivery) {
        DebugScrollTestDelivery.Single -> "1 条"
        DebugScrollTestDelivery.InstantTriple -> "3 条瞬发"
        DebugScrollTestDelivery.IntervalTriple -> "3 条间隔 3 秒"
    }
    _snackbarMessages.tryEmit("将在 10 秒后注入${label}${deliveryLabel}滚动测试")
    viewModelScope.launch {
        delay(10_000)
        when (delivery) {
            DebugScrollTestDelivery.Single -> {
                debugAppendScrollTestMessage(
                    id = "debug_scroll_${key}_${startedAt}_single",
                    content = "[调试｜${label}｜1 条] 延时出现，用来确认用户在底部时会自动滚到新消息。"
                )
            }
            DebugScrollTestDelivery.InstantTriple -> {
                val batchNow = System.currentTimeMillis()
                val batch = listOf(
                    debugScrollTestMessage(
                        id = "debug_scroll_${key}_${startedAt}_instant_1",
                        timestamp = batchNow,
                        content = "[调试｜${label}｜3 条瞬发 1/3] 与另外两条同一时刻追加，用来确认只触发一次滚动。",
                        autoScrollBatchIndex = 0,
                        autoScrollBatchTotal = 3
                    ),
                    debugScrollTestMessage(
                        id = "debug_scroll_${key}_${startedAt}_instant_2",
                        timestamp = batchNow + 1,
                        content = "[调试｜${label}｜3 条瞬发 2/3] 与另外两条同一时刻追加。",
                        autoScrollBatchIndex = 1,
                        autoScrollBatchTotal = 3
                    ),
                    debugScrollTestMessage(
                        id = "debug_scroll_${key}_${startedAt}_instant_3",
                        timestamp = batchNow + 2,
                        content = "[调试｜${label}｜3 条瞬发 3/3] 批量完成后不应该出现后续迟到滚动。",
                        autoScrollBatchIndex = 2,
                        autoScrollBatchTotal = 3
                    )
                )
                _state.value = _state.value.copy(messages = _state.value.messages + batch)
            }
            DebugScrollTestDelivery.IntervalTriple -> {
                debugAppendScrollTestMessage(
                    id = "debug_scroll_${key}_${startedAt}_interval_1",
                    content = "[调试｜${label}｜3 条间隔 1/3] 首条在 10 秒后出现，用户在底部时应自动跟随。"
                )
                delay(3_000)
                debugAppendScrollTestMessage(
                    id = "debug_scroll_${key}_${startedAt}_interval_2",
                    content = "[调试｜${label}｜3 条间隔 2/3] 与上一条间隔 3 秒，属于正常分条。"
                )
                delay(3_000)
                debugAppendScrollTestMessage(
                    id = "debug_scroll_${key}_${startedAt}_interval_3",
                    content = "[调试｜${label}｜3 条间隔 3/3] 与上一条间隔 3 秒，应按正常单条逻辑处理。"
                )
            }
        }
    }
}

private fun ChatViewModel.debugAppendScrollTestMessage(id: String, content: String) {
    val msg = debugScrollTestMessage(
        id = id,
        timestamp = System.currentTimeMillis(),
        content = content
    )
    _state.value = _state.value.copy(messages = _state.value.messages + msg)
}

private enum class DebugScrollTestDelivery {
    Single,
    InstantTriple,
    IntervalTriple
}

private fun debugScrollTestMessage(
    id: String,
    timestamp: Long,
    content: String,
    autoScrollBatchIndex: Int? = null,
    autoScrollBatchTotal: Int? = null
): Message = Message(
    id = id,
    role = "assistant",
    content = content,
    timestamp = timestamp,
    messageId = id,
    autoScrollBatchIndex = autoScrollBatchIndex,
    autoScrollBatchTotal = autoScrollBatchTotal
)

/** 本机调试：注入普通对话长按菜单覆盖用的混合内容。 */
fun ChatViewModel.debugInjectLongPressMenuSamples() {
    val now = System.currentTimeMillis()
    val imageDataUrl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAXElEQVR4nO3PQQ0AIBDAMMC/5+ONAvZoFSzZ3bO7B9w6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6kDqQOpA6uPoB5/5B6rH+mcMAAAAASUVORK5CYII="
    val base = "debug_long_press_$now"
    val sourceUserId = "${base}_user_text"
    val sourceAssistantId = "${base}_assistant_text"
    val samples = listOf(
        top.ponychat.webview.data.model.Message(
            id = sourceUserId,
            role = "user",
            content = "长按测试：用户纯文字消息",
            timestamp = now,
            messageId = sourceUserId
        ),
        top.ponychat.webview.data.model.Message(
            id = sourceAssistantId,
            role = "assistant",
            content = "长按测试：助手纯文字消息\n\n第二段也应该能单独弹出菜单。",
            timestamp = now + 1,
            messageId = sourceAssistantId
        ),
        top.ponychat.webview.data.model.Message(
            id = "${base}_assistant_image",
            role = "assistant",
            content = "长按测试：助手图片 + 文字\n$imageDataUrl",
            timestamp = now + 2,
            messageId = "${base}_assistant_image"
        ),
        top.ponychat.webview.data.model.Message(
            id = "${base}_user_image",
            role = "user",
            content = "长按测试：用户图片 + 文字\n$imageDataUrl",
            timestamp = now + 3,
            messageId = "${base}_user_image"
        ),
        top.ponychat.webview.data.model.Message(
            id = "${base}_user_quote",
            role = "user",
            content = "长按测试：这条消息带引用卡片",
            timestamp = now + 4,
            messageId = "${base}_user_quote",
            quotedMessage = top.ponychat.webview.data.model.QuotedMessage(
                messageId = sourceAssistantId,
                role = "assistant",
                sender = _state.value.character?.name ?: "角色",
                content = "被引用的助手消息，用来测试引用卡片长按菜单。",
                timestamp = now + 1
            )
        ),
        top.ponychat.webview.data.model.Message(
            id = "${base}_sticker",
            role = "assistant",
            content = "",
            timestamp = now + 5,
            messageId = "${base}_sticker",
            attachments = listOf(
                top.ponychat.webview.data.model.MessageAttachment(
                    id = "${base}_sticker_attachment",
                    type = "sticker",
                    url = imageDataUrl,
                    name = "长按测试表情"
                )
            )
        )
    )
    _state.value = _state.value.copy(messages = _state.value.messages + samples)
    _snackbarMessages.tryEmit("已注入长按菜单测试内容")
}

/** 本机调试：注入普通对话图片布局样例，验证用户右对齐、角色左对齐和多图网格。 */
fun ChatViewModel.debugInjectImagePreviewSamples() {
    val now = System.currentTimeMillis()
    val images = listOf(
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAACI0lEQVR42u3dQU4DMQyFYZ+OLWdizzV7B5ZFYs3YSRz7PdvSrBATog91mr+ZtvL1/aMenx8v9ag3zt/vyAA9nz5AyrkDpJw4QE9n/f5kgJ50BkjRGSBFZ4AUHSuQZU6kQOrIViDjupMLyDKsnA9RA+i/ccTrbzB2luUQr4EYO8sByD4cY2f5ABXurAFSSmKAlJIYIKUkBkgpiQF6LT3u7gIB9trqZfs6EFSveT3ri/uEiDrLBBS5bEfrLMt8BG1CaP8wCbv6AnZWHBBpZzUC2uusLkDbndUC6KSz6gMddlZxoPPOggNy7DWXzkIEclx2nj/rgwI5LoUPF40mIK7lf3zWCFFApoRx3CuKAQ8ZbiDAzioCdK+zKgBd7Sx6oNudxQ0U0FnEQDGdRQm0cdluDZQ+H2gghPmgvB4Eez/kADEAZWUEB1BiZxEA5XYWOlB6Z0EDIXQWLhBIZ4EC4XQWIpBLZ0XeDymMnRV5P6Qwdlbk/ZCz7QNQ87NxGNpZpYDAOysZCL+zMoEoOisNiKWzcoCIOisBiKuzooGg9rO8VgxSdT/La9kpVfezvJb483aoyzU/b6ij3M+CACrQWReBanTWLaAynXUFqFJn+QMV6yxnoHqd5QkE1VmRvSaMnRXZa8LYWZG9Nh8TeFDz80GTT0DlM+IIqElnbQL16awdoFadtQzUrbPWgBp21gJQz86yApXsrFvv9mnyzU+bQH2+Gss+zhuQtAAn//OPwgAAAABJRU5ErkJggg==",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAKAAAABgCAIAAAAVRe7OAAACk0lEQVR42u2d0W3DQAxDOUTn63idoYN0ik7RfhlFiyJxfLqI1APyaSiOnn1nyhKj18+Pm5+X97ebH+L0ifPzIxIKYBIKYMBYA77nuwHTEPD38Tp1NAl1AXwcr7O3PAn1inMa8H+nQkKjAP89GxJaHecxNI8D/hULMKVxHr73rgI+IgKmKM7FxVUL+QFmbZwledZa7QW8nRLonjiqqJ4Apk+cEsBXthPAeABGSlXUetsBRkqVSqAugI/TAnDR3rcDMFKqorjbC/Da9TwY8M78yP0HeMXZv8LJfQkyivOUZxRVJwLAz1UZcpcB1oB3FDqaXMWRUqrD6qU++1DSXd7nd2nCk2SqBGoKOFhKNbxwxVK2Yevp3nTnXo9NlUAegAOkVOdXpb1mk2IAm/VF0x3h264k04Q2BGw82dB5eo4LLhkwHZz7+qJTpZR7r5mMruJWgMe1zXaesEuVQIGA2e8BvL6u0uqJHcDrF3xGV1haAUx9GMA73/DMaQKcBXhgnzaAAZw4STAIMEUMjNCoUgE4Yp8GcJrfxQRfkTTAyx+eAWzcFDBhGC4EcKnFJoDth70AnO93AeARfhcAHjHsBeD8Ya8cwPhdZEspBUsg3kp1B9wnoQAe4XcB4HC/C0cppWkSaJqviAZKoFFSygDwzP9aGAGYYbhYwAzDJQPO7v9CJtHBmegXzV/mJLxNcve7cJRSQgLl+Yq0AMw+nQwYMNsUhJBA2TUA3GbDpRSAw+vwcn9K5M+zagGPmpZ3LATJvVIzyldkE+CxfheOHZxCAmVLKd4mhUspAIf7imjb+gzgp0gpIYGypZSQQElS6i7ASKAkKaUJNgaRcc4BxrQz1YBGdX4XgOkwDKdRnY7Bcc4BJqExHZxfmTsojqCyxAEAAAAASUVORK5CYII=",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAACgCAIAAAB8Ev7bAAAC1UlEQVR42u3dS07EQAxFUc97YeyStbEJhkiAkBjwifNxOfbzlRg1SSl9Op2kXrmq7e3lyf17fX64f3rtfG1jAG3vDpCzL0AAHWznxzYAAXSknd/bALS1y8eLAAG0r53//gvQ39t/vw7Q1unzCeQ2KtnP2t+OndhnNNBpI4AAumYEkBrQzvdlF/efC3TUqGOcCtBioEMNdcybAQq4tlrUxUwWKOqxsCPinqYsqvOl+jC5N+4A6DCQm8jNAnKNAHKSN4Cckwgg5yQCaGhubYseeUYDjYplAfKAMvs1yf2skI/ZYg+oLFBwaL8oWgSoKFD8sM+NB1TtAwPoDqAr3/lqNw2rdlsFqFDefDOQRixrgQcE0MTcWqGIc2k+1R5odcKpBlQlD6pf3wzQI+eGAJAoUNozl3V8/N+4NgOU3e+zjj3szGjFOoZYABVKLy3hDhU4uJg/SGk5t/D8k2sc0F3D3Jb2EAhQ3nIRAAHUp9TGJsepAKkDVaiotcl5c2+gIlX9VufrU7Pe2kpdgAtWy9rkZxyAJEY1AAIofar2OKDKy2AABBDXIIAk5oup1ls3ALq3nLhi3AFQp3rrooFZnXVCSBSFgAjtGdVomFv3Gzhk6Jmx+V5AHftZmeuE3AnUYp2QxkA5y2DcBtRlnRAKyQFiMgtAk6ZDMV9MLbdmzuoYoFWznlXrm0v35iskgZ2AWD9IedVyWz2exQpUALGGWbv1NESWCQSIpUr7A72xGvByoI7raWSWE1u1A6r2gdnqrwxAFeubSwAVn8YEED9d0xdIJk4F6A4gpbw5A6h11hMPJJY3t5wvVq3eegTQlSH/KUCnjQAC6JqRZfaMAWpwJgYDSXZEAcoCEo4yAoC0sx6AwnJri3r/GuXEgj+ftbreejTQnpomgJz2pwO5RgA5SSlAzkkEkHMSAeScRAA5uwDk7AXQcSDhTDqgiFM7tAdoMZD8sM+Jdt4BtUq5tTKDwo4AAAAASUVORK5CYII=",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJYAAABuCAIAAABKon3BAAAC4UlEQVR42u2dwXHFIAwFX2fpJD2kiHScWy4pIMk3Biz0pJ35x1jjsAazgGR9f3xe/r7e3i9/xDkVRzQZCGn6uDh/XgVCmzj/XQVCjzgvrhpCON3Hafr1OJdXjSKc7uYgXIkzctUNhNM9HYQTccah3EO40t9BOB7nFo4ZhNNdHoQjcV7/wTaEv++bpl+PM9dB9VxoEO5CeLE6Q7Nm1vaROCA8HGd9FqKNgwAIn5jGhyJE/7fP4Q8gXB800PYUCNH/Xdp+EiH6P2Ll41J/BuHcAIK2p0OI/j/9iEcgXBwoqiLcdT+KGet3aUkZhBvvR/lnXPUQ7r0fxf8b5bU9+PFVjSexqranRlhS/4+8RHR8Yo222yMsoP9nnVh9/tWqo0sWhLfkso+2J02Lqaf/Z6dp6jNzC0DYKzmtHsKm+YVlELZOEWUddRUhE/TM2m55jjSb/ud3WRmtdBx56vMvCpohjNf//Me6kh7Iz6P/+TfIxMaNe4Zz9rSYJAgzi4dBZhNncCokp4GwSH4hCCukiG5EWOZR8MvyDZuA2CCsd9xo5Wg5xSzN9L/GuVbvSohP8wNhdv2vUeKhSD3SzvpfqqQsCItXzwVhR/0HIQhByLuwFUKkoqNU1EgcL1vMctf5f3Yq0H8QMuUBYXn9b7rly649vQeEvMM4hNgk/ZPT3Jzm7lfPjLSYymkxaevGZURIimiLc6QITMadioRNBkK0vQ1CtJ3qT1R/6qrtlNGjjF4K/c9Vj5TPiBggTF7PjMLO1OY+UDeOjxzY1407jLD2h+1i3vHPLnNTL8Z7p4KqTTFbx0Lb3fWf7xfa67/QdvepnNB2d6Hio+j2+i+03V3/hbZ71Y0LQoiSP1c3LgIhqyrB0rUTIQtjR5Y+hLa7bx0LbXfXf+3qWCA8JWZC2y3c8RGENH0S/ddzr1kQxui/0HZ3/Rfa7p7hLLTdXf9JEbWvGwdC+5o7ILRPHBfa7u6OYqvWHeEP5DK/40/BjuMAAAAASUVORK5CYII=",
    )
    fun imageContent(label: String, count: Int): String =
        buildString {
            append(label)
            append('\n')
            images.take(count).forEach {
                append(it)
                append('\n')
            }
        }.trim()

    val base = "debug_image_preview_$now"
    val samples = listOf(
        Message(
            id = "${base}_user_1",
            role = "user",
            content = imageContent("图片布局样例：用户 1 图，应靠右对齐", 1),
            timestamp = now,
            messageId = "${base}_user_1",
        ),
        Message(
            id = "${base}_assistant_2",
            role = "assistant",
            content = imageContent("图片布局样例：角色 2 图，应靠左对齐", 2),
            timestamp = now + 1,
            messageId = "${base}_assistant_2",
        ),
        Message(
            id = "${base}_user_3",
            role = "user",
            content = imageContent("图片布局样例：用户 3 图，右侧小网格", 3),
            timestamp = now + 2,
            messageId = "${base}_user_3",
        ),
        Message(
            id = "${base}_assistant_4",
            role = "assistant",
            content = imageContent("图片布局样例：角色 4 图，左侧小网格", 4),
            timestamp = now + 3,
            messageId = "${base}_assistant_4",
        ),
    )
    _state.value = _state.value.copy(messages = _state.value.messages + samples)
    _snackbarMessages.tryEmit("已注入图片布局样例")
}

/** 本机调试：注入短、中、最长三条可播放样式的角色语音消息。 */
fun ChatViewModel.debugInjectVoiceMessage() {
    val now = System.currentTimeMillis()
    _state.value = _state.value.copy(messages = _state.value.messages + buildDebugAssistantVoiceMessages(now))
    _snackbarMessages.tryEmit("已注入长短语音气泡样例")
}

/** 本机调试：注入短、中、最长三条用户端可播放语音消息。 */
fun ChatViewModel.debugInjectUserVoiceMessage() {
    val now = System.currentTimeMillis()
    _state.value = _state.value.copy(messages = _state.value.messages + buildDebugUserVoiceMessages(now))
    _snackbarMessages.tryEmit("已注入用户端语音样例")
}

/** 本机调试：注入一条缓存缺失的角色语音状态，UI 应回退为文本消息。 */
fun ChatViewModel.debugInjectVoiceCacheMissingMessage() {
    val now = System.currentTimeMillis()
    _state.value = _state.value.copy(messages = _state.value.messages + buildDebugVoiceCacheMissingMessage(now))
    _snackbarMessages.tryEmit("已注入缓存缺失回退样例")
}

/** 本机调试：注入一条语音生成失败后的文本回退消息。 */
fun ChatViewModel.debugInjectVoiceFailedMessage() {
    val now = System.currentTimeMillis()
    _state.value = _state.value.copy(messages = _state.value.messages + buildDebugVoiceFailedMessage(now))
    _snackbarMessages.tryEmit("已注入语音失败回退样例")
}

/** 本机调试：模拟配额耗尽，触发黄色提示横幅。 */
fun ChatViewModel.debugSimulateQuotaExceeded() {
    val limit = _state.value.quotaInfo?.dailyLimit ?: 100
    _state.value = _state.value.copy(
        quotaExceeded = true,
        quotaExceededMessage = "今日积分已用完（上限 ${limit} 分）[debug simulation]"
    )
}

/** 本机调试：清除配额耗尽状态。 */
fun ChatViewModel.debugClearQuotaExceeded() {
    _state.value = _state.value.copy(quotaExceeded = false, quotaExceededMessage = "")
}

/** 本机调试：将当前对话 ID 复制到系统剪贴板并 Toast 提示。 */
fun ChatViewModel.debugCopyConversationId() {
    val convId = _state.value.conversationId
    if (convId.isNullOrBlank()) {
        viewModelScope.launch { _snackbarMessages.emit("对话 ID 为空") }
        return
    }
    val clipboard = getApplication<Application>()
        .getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
    clipboard.setPrimaryClip(android.content.ClipData.newPlainText("conversationId", convId))
    viewModelScope.launch { _snackbarMessages.emit("已复制：$convId") }
}

/** 本机调试：将当前 ChatUiState 关键字段打印到 Logcat（tag: ChatDebug）。 */
fun ChatViewModel.debugPrintStateSnapshot() {
    val s = _state.value
    val snapshot = buildString {
        appendLine("=== ChatUiState Snapshot ===")
        appendLine("conversationId : ${s.conversationId}")
        appendLine("mode           : ${s.mode}")
        appendLine("messages       : ${s.messages.size}")
        appendLine("sentMessages   : ${sentMessages.size}")
        appendLine("isStreaming    : ${s.isStreaming}")
        appendLine("isLoading      : ${s.isLoadingHistory}")
        appendLine("bgRefreshing   : ${s.isBackgroundRefreshing}")
        appendLine("galgameScore   : ${s.galgameScore}")
        appendLine("quotaExceeded  : ${s.quotaExceeded}")
        appendLine("relationship   : ${relationshipStageCn(s.relationshipStageOverride ?: s.relationshipSnapshot?.stageKey ?: "uncertain")}")
        appendLine("error          : ${s.error}")
        appendLine("errorDebug     : ${s.errorDebug}")
        appendLine("contextTokens  : ${s.contextUsedTokens}/${s.contextLimitTokens}")
        appendLine("supportsVision : ${s.character?.effectiveSupportsVision()}")
        appendLine("retryCount     : ${s.retryCount}")
        append("============================")
    }
    Log.d("ChatDebug", snapshot)
    viewModelScope.launch { _snackbarMessages.emit("Snapshot printed to Logcat: ChatDebug") }
}

/** 本机调试：清除当前角色+模式的本地缓存，下次进入强制从服务端拉取。 */
fun ChatViewModel.debugClearLocalCache() {
    val username = prefs.username.ifBlank {
        viewModelScope.launch { _snackbarMessages.emit("用户名为空，无法清除缓存") }
        return
    }
    val charId = _state.value.character?.id?.ifBlank { null } ?: run {
        viewModelScope.launch { _snackbarMessages.emit("角色 ID 为空") }
        return
    }
    val mode = _state.value.mode
    viewModelScope.launch(Dispatchers.IO) {
        localCache.clearForCharacterMode(username, charId, mode)
        withContext(kotlinx.coroutines.Dispatchers.Main) {
            _snackbarMessages.emit("Local cache cleared ($mode)")
        }
    }
}

/** 从服务端拉取真实配额信息，填充到 state.quotaInfo（调试用面板展示）。 */
fun ChatViewModel.debugLoadQuota() {
    val username = prefs.username.ifBlank { return }
    if (prefs.authToken.isBlank()) return
    viewModelScope.launch {
        runCatching {
            top.ponychat.webview.data.repo.AuthRepository(prefs).getUserQuota(username)
        }.onSuccess { result ->
            result.onSuccess { data ->
                val rawType = data["membership_type"] ?: data["membershipType"]
                val mType = when (rawType) {
                    is String -> rawType.trim().ifBlank { "free" }
                    null -> "free"
                    else -> rawType.toString().trim().ifBlank { "free" }
                }
                val rawLabel = data["membership_label"] ?: data["membershipLabel"]
                val mLabel = when (rawLabel) {
                    is String -> rawLabel.ifBlank { "免费" }
                    null -> "免费"
                    else -> rawLabel.toString().ifBlank { "免费" }
                }
                val info = top.ponychat.webview.data.model.QuotaInfo(
                    membershipType  = mType,
                    membershipLabel = mLabel,
                    dailyLimit      = (data["daily_limit"]  as? Number)?.toInt() ?: 100,
                    usedToday       = (data["used_today"]   as? Number)?.toInt() ?: 0,
                    remaining       = (data["remaining"]    as? Number)?.toInt() ?: 100,
                    expireAt        = (data["expire_at"] ?: data["expireAt"]) as? String
                )
                prefs.membershipType = info.membershipType
                _state.value = _state.value.copy(quotaInfo = info)
            }
        }
    }
}

// ==================== 语音 ====================

fun ChatViewModel.onVoiceFinal(text: String) {
    _state.value = _state.value.copy(
        inputText = _state.value.inputText + text,
        voiceState = VoiceState.Idle
    )
}

fun ChatViewModel.onVoicePartial(text: String) {
    _state.value = _state.value.copy(voiceState = VoiceState.Partial(text))
}

fun ChatViewModel.onVoiceStart() {
    _state.value = _state.value.copy(voiceState = VoiceState.Listening)
}

fun ChatViewModel.onVoiceEnd() {
    _state.value = _state.value.copy(voiceState = VoiceState.Idle)
}

fun ChatViewModel.onVoiceError(code: String) {
    _state.value = _state.value.copy(
        voiceState = VoiceState.Idle,
        error = when (code) {
            "permission_denied" -> "需要麦克风权限"
            "network_error" -> "网络错误"
            else -> "语音识别失败"
        }
    )
}

fun ChatViewModel.clearError() {
    _state.value = _state.value.copy(error = null, errorDebug = null)
}

/**
 * 普通 / 游戏 / 锁分：本轮请求失败（助手气泡 isError、或审核仅横幅、或配额用尽气泡）时，
 * 在用户离开聊天页再进入、或再次发送前，移除顶部错误提示与本轮失败配对的一条用户消息（及错误助手气泡），
 * 并同步 [sentMessages]（含游戏开局隐藏 user）。
 */
fun ChatViewModel.clearFailedChatRoundIfNeeded() {
    if (!shouldStripFailedChatRound()) return
    stripFailedChatRoundInternal()
}

internal fun ChatViewModel.shouldStripFailedChatRound(): Boolean {
    val s = _state.value
    if (s.isStreaming || s.isLoadingHistory) return false
    val mode = s.mode
    if (mode != "normal" && mode != "galgame" && mode != "galgame_lock") return false
    val last = s.messages.lastOrNull() ?: return false
    if (last.isAssistant() && last.isError) return true
    // 审核失败：仅横幅，用户气泡仍显示
    if (last.isUser() && s.error == GALGAME_POLICY_ERROR_TEXT) return true
    return false
}

internal fun ChatViewModel.stripFailedChatRoundInternal() {
    val character = _state.value.character ?: return
    val msgs = _state.value.messages.toMutableList()

    if (msgs.lastOrNull()?.isAssistant() == true && msgs.last().isError) {
        msgs.removeAt(msgs.lastIndex)
        if (sentMessages.isNotEmpty() && sentMessages.last().role == "assistant") {
            sentMessages.removeAt(sentMessages.lastIndex)
        }
    }

    if (msgs.lastOrNull()?.isUser() == true) {
        msgs.removeAt(msgs.lastIndex)
        if (sentMessages.isNotEmpty() && sentMessages.last().role == "user") {
            sentMessages.removeAt(sentMessages.lastIndex)
        }
    }

    // 游戏开局失败：仅有 error assistant 占位，sentMessages 尾部仍留隐藏 user
    if (sentMessages.isNotEmpty() && sentMessages.last().role == "user" && sentMessages.last().isHidden == true) {
        val tailUi = msgs.lastOrNull()
        if (tailUi == null || !tailUi.isUser()) {
            sentMessages.removeAt(sentMessages.lastIndex)
        }
    }

    _state.value = _state.value.copy(
        messages = msgs,
        error = null,
        errorDebug = null,
        quotaExceeded = false,
        quotaExceededMessage = ""
    )
    viewModelScope.launch { triggerAutoSave(character, saveIntent = "user_edit") }
}

fun ChatViewModel.clearQuotaExceeded() {
    _state.value = _state.value.copy(quotaExceeded = false, quotaExceededMessage = "")
}

fun ChatViewModel.fillInput(text: String) {
    _state.value = _state.value.copy(inputText = text)
}

// ==================== 内部方法 ====================

internal fun ChatViewModel.removeLastStreamingPlaceholder() {
    val msgs = _state.value.messages.toMutableList()
    val lastIdx = msgs.indexOfLast { it.isAssistant() && it.isStreaming }
    if (lastIdx >= 0 && msgs[lastIdx].content.isEmpty()) {
        msgs.removeAt(lastIdx)
        _state.value = _state.value.copy(messages = msgs)
    }
}

internal fun ChatViewModel.updateStreamingMessage(content: String) {
    val msgs = _state.value.messages.toMutableList()
    val lastIdx = msgs.indexOfLast { it.isAssistant() }
    if (lastIdx >= 0) {
        val current = msgs[lastIdx]
        if (current.content == content && current.isStreaming) return
        msgs[lastIdx] = current.copy(content = content, isStreaming = true)
        _state.value = _state.value.copy(messages = msgs)
    }
}

internal fun ChatViewModel.finalizeAssistantMessage(content: String) {
    val msgs = _state.value.messages.toMutableList()
    val lastIdx = msgs.indexOfLast { it.isAssistant() }
    val generatedAt = System.currentTimeMillis()
    val generationDurationMs = currentGenerationDurationMs()
    if (lastIdx >= 0) {
        val current = msgs[lastIdx]
        msgs[lastIdx] = if (current.content == content && !current.isStreaming) current
        else current.copy(
            content = content,
            isStreaming = false,
            timestamp = generatedAt,
            generationDurationMs = generationDurationMs
        )
    }
    _state.value = _state.value.copy(
        messages = msgs,
        isStreaming = false
    )

    if (content.isNotBlank()) {
        val messageId = msgs.getOrNull(lastIdx)?.id ?: UUID.randomUUID().toString()
        sentMessages.add(
            ChatMessage(
                role = "assistant",
                content = content,
                messageId = messageId,
                timestamp = generatedAt,
                generationDurationMs = generationDurationMs
            )
        )
    }
}

/**
 * normal 模式：将 AI 回复按 \n\n+ 拆成多条独立助手消息插入列表。
 * [serverIds] 为服务端按段落顺序返回的 message_id 列表；不足时用 UUID 补齐。
 * 消息整体出现，无逐字打印效果。
 */
internal fun ChatViewModel.insertFinalNormalModeMessages(content: String, serverIds: List<String> = emptyList()) {
    markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
    val generatedAt = System.currentTimeMillis()
    val generationDurationMs = currentGenerationDurationMs()
    val paragraphs = content.split(Regex("\\n{2,}"))
        .map { it.trim() }.filter { it.isNotBlank() }
        .ifEmpty { if (content.isNotBlank()) listOf(content.trim()) else emptyList() }

    val msgs = _state.value.messages.toMutableList()
    paragraphs.forEachIndexed { idx, para ->
        val id = serverIds.getOrNull(idx) ?: UUID.randomUUID().toString()
        val newMsg = Message(
            id = id,
            role = "assistant",
            content = para,
            timestamp = generatedAt + idx,
            isStreaming = false,
            generationDurationMs = if (idx == 0) generationDurationMs else null,
            autoScrollBatchIndex = idx.takeIf { paragraphs.size > 1 },
            autoScrollBatchTotal = paragraphs.size.takeIf { it > 1 }
        )
        msgs.add(newMsg)
        if (para.isNotBlank()) {
            sentMessages.add(
                ChatMessage(
                    role = "assistant",
                    content = para,
                    messageId = id,
                    timestamp = generatedAt + idx,
                    generationDurationMs = if (idx == 0) generationDurationMs else null
                )
            )
            MessageVibrationHelper.vibrateForMessage(getApplication(), prefs)
        }
    }
    _state.value = _state.value.copy(messages = msgs, isStreaming = false)
    markNormalReplySucceeded("normal_final_messages")
}

/**
 * 兼容旧调用（无服务端 ID 列表），转发到 [insertFinalNormalModeMessages]。
 */
internal fun ChatViewModel.insertFinalNormalModeMessage(content: String) {
    insertFinalNormalModeMessages(content, emptyList())
}

/** 移除本轮游戏/锁分「待完成」的 AI 占位 + 最后一条用户消息（与手动取消一致，不弹错误）。 */
internal fun ChatViewModel.removeGalgamePendingRoundSilently() {
    val msgs = _state.value.messages.toMutableList()
    val lastAiIdx = msgs.indexOfLast { it.isAssistant() && it.isStreaming }
    if (lastAiIdx >= 0) msgs.removeAt(lastAiIdx)
    val lastUserIdx = msgs.indexOfLast { it.isUser() }
    if (lastUserIdx >= 0) msgs.removeAt(lastUserIdx)
    if (sentMessages.isNotEmpty() && sentMessages.last().role == "assistant") sentMessages.removeAt(sentMessages.lastIndex)
    if (sentMessages.isNotEmpty() && sentMessages.last().role == "user") sentMessages.removeAt(sentMessages.lastIndex)
    _state.value = _state.value.copy(
        messages = msgs,
        isStreaming = false,
        galgameStreamingStep = null,
        error = null
    )
}

/** 将后端 galgame_result（与 SSE `result` 事件相同结构）应用到 UI 与 sentMessages。 */
@Suppress("UNCHECKED_CAST")
internal suspend fun ChatViewModel.applyGalgameSuccessFromResultMap(gal: Map<String, Any?>) {
        replyRecoveryPollJob?.cancel()
        replyRecoveryPollJob = null
        if ((gal["status"]?.toString() ?: "") != "success") {
            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
            stopReplyTimer()
            return
        }
        val serverMid = gal["assistant_message_id"]?.toString()?.trim()?.takeIf { it.isNotBlank() }
        val data = gal["data"] as? Map<String, Any?> ?: run {
            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
            stopReplyTimer()
            return
        }
        val scene = (data["scene"] as? Map<String, Any?>) ?: emptyMap()
        val optsRaw = data["suggested_options"] as? List<Any>
        val opts = parseGalgameOptionsFromPayload(optsRaw)
        val scoreObj = data["score"]
        val newScore = when (scoreObj) {
            is Number -> scoreObj.toInt().coerceIn(0, 100)
            is Map<*, *> -> (scoreObj["current"] as? Number)?.toInt()?.coerceIn(0, 100)
            else -> (gal["score"] as? Number)?.toInt()?.coerceIn(0, 100)
        }
        val mode = _state.value.mode
        val adjustedScore = if (mode == "galgame_lock" && (newScore ?: 0) <= 0) 1 else newScore

        fun Map<String, Any?>?.toIntMap(): Map<String, Int> = this
            ?.mapNotNull { (k, v) -> (v as? Number)?.toInt()?.let { k to it } }
            ?.toMap() ?: emptyMap()
        val charVitalsRaw = data["char_vitals"] as? Map<String, Any?>
        val charMoodRaw   = data["char_mood"]   as? Map<String, Any?>
        val organFillRaw  = data["organ_fill"]  as? Map<String, Any?>

        val displayHtml = buildGalgameDisplayHtml(scene)
        val msgContent = (gal["message"] as? Map<String, Any?>)?.get("content")?.toString() ?: ""
        val rawContent = (gal["message"] as? Map<String, Any?>)?.get("rawContent")?.toString()
        val generatedAt = System.currentTimeMillis()
        val generationDurationMs = currentGenerationDurationMs()

        val msgs = _state.value.messages.toMutableList()
        val lastIdx = msgs.indexOfLast { it.isAssistant() }
        if (lastIdx >= 0) {
            val old = msgs[lastIdx]
            msgs[lastIdx] = old.copy(
                content = msgContent.ifBlank { old.content },
                displayContent = displayHtml.ifBlank { null } ?: old.displayContent,
                rawContent = rawContent ?: old.rawContent,
                sceneMetadata = null,
                galgameOptions = if (opts.isNotEmpty()) opts else old.galgameOptions,
                timestamp = generatedAt,
                generationDurationMs = generationDurationMs,
                isStreaming = false
            )
        }
        val newVitals = if (mode == "galgame_lock") charVitalsRaw.toIntMap() else emptyMap()
        val newMood   = if (mode == "galgame_lock") charMoodRaw.toIntMap()   else emptyMap()
        val newOrgan  = if (mode == "galgame_lock") organFillRaw.toIntMap()  else emptyMap()
        fun computeDelta(newMap: Map<String, Int>, oldMap: Map<String, Int>): Map<String, Int> {
            if (oldMap.isEmpty()) return emptyMap()
            return newMap.mapValues { (k, v) -> v - (oldMap[k] ?: v) }.filter { it.value != 0 }
        }
        val vitalsDelta = computeDelta(newVitals, _state.value.lockCharVitals)
        val moodDelta   = computeDelta(newMood,   _state.value.lockCharMood)
        val organDelta  = computeDelta(newOrgan,  _state.value.lockOrganFill)

        Log.d("GalScroll", "[VM] applyGalgameResult COMPLETED: lastIdx=$lastIdx msgSize=${msgs.size} hasDisplay=${displayHtml.isNotBlank()} msgId=${msgs.getOrNull(lastIdx)?.id} prevIsStreaming=${_state.value.isStreaming}")
        Log.d("GalDebug", "[applyGalgame] newScore=$newScore adjustedScore=$adjustedScore mode=$mode" +
            " rawContentLen=${rawContent?.length} sceneBodyState=${scene["body_state"]?.toString()?.take(15)}")
        _state.value = _state.value.copy(
            messages = msgs,
            galgameScore = adjustedScore,
            isStreaming = false,
            galgameStreamingStep = null,
            lockCharVitals = if (mode == "galgame_lock") newVitals else _state.value.lockCharVitals,
            lockCharMood   = if (mode == "galgame_lock") newMood   else _state.value.lockCharMood,
            lockOrganFill  = if (mode == "galgame_lock") newOrgan  else _state.value.lockOrganFill,
            lockCharGender = if (mode == "galgame_lock") {
                val g = data["character_gender"]?.toString()?.trim() ?: ""
                g.ifBlank { _state.value.lockCharGender }
            } else _state.value.lockCharGender,
            lockCharVitalsDelta = if (mode == "galgame_lock") vitalsDelta else _state.value.lockCharVitalsDelta,
            lockCharMoodDelta   = if (mode == "galgame_lock") moodDelta   else _state.value.lockCharMoodDelta,
            lockOrganFillDelta  = if (mode == "galgame_lock") organDelta  else _state.value.lockOrganFillDelta
        )
        Log.d("GalScroll", "[VM] applyGalgameResult state updated: isStreaming=${_state.value.isStreaming} msgCount=${_state.value.messages.size}")
        stopReplyTimer()
        val asstContent = msgContent.ifBlank { msgs.getOrNull(lastIdx)?.content ?: "" }
        if (asstContent.isNotBlank()) {
            val msgId = serverMid ?: (msgs.getOrNull(lastIdx)?.id ?: UUID.randomUUID().toString())
            val asstEntry = ChatMessage(
                role = "assistant",
                content = asstContent,
                messageId = msgId,
                timestamp = generatedAt,
                generationDurationMs = generationDurationMs,
                rawContent = rawContent,
                sceneMetadata = null,
                displayContent = displayHtml.ifBlank { null },
                galgameOptions = optsRaw
            )
            val existingAsstIdx = sentMessages.indexOfLast { it.role == "assistant" }
            if (existingAsstIdx >= 0) sentMessages[existingAsstIdx] = asstEntry
            else sentMessages.add(asstEntry)
        }
        val charId = _state.value.character?.id?.takeIf { it.isNotBlank() }
        if (charId != null) {
            prefs.setModeLastChatTime(charId, _state.value.mode, generatedAt)
            emitForegroundChatCompleted(
                charId,
                _state.value.mode,
                generatedAt,
                serverMid ?: msgs.getOrNull(lastIdx)?.id,
            )
            // 游戏模式 SSE 完成时可能没有 WS chat_complete；用户回桌面后需系统通知兜底（与 WS 同 notificationId）
            if (!ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
                val preview = GalgameNotificationPreview.buildPlainPreview(
                    scene,
                    msgContent,
                    displayHtml,
                    data["score_delta_reason"]?.toString(),
                ).ifBlank { msgContent.ifBlank { displayHtml } }
                SyncWebSocketManager.postChatCompleteFallbackFromGalgame(
                    getApplication(),
                    charId,
                    _state.value.mode,
                    preview,
                )
            }
        }
        _state.value.character?.let { triggerAutoSave(it) }
        // 与后端 galgame 落库对齐：服务端已在 SSE 成功回调前写入 DB；此处延迟拉取一次完整历史，
        // 使 sentMessages / message_id 与服务端一致，避免仅依赖内存合并与 Web 端「整包保存」交叉时出现漂移。
        val ch = _state.value.character
        if (ch != null && (mode == "galgame" || mode == "galgame_lock")) {
            viewModelScope.launch {
                delay(450)
                if (!_state.value.isStreaming &&
                    (_state.value.mode == "galgame" || _state.value.mode == "galgame_lock") &&
                    _state.value.character?.id == ch.id
                ) {
                    loadConversationHistory(ch)
                }
            }
        }
}

/** SSE metadata 事件：提前更新好感条（可选）。 */
internal fun ChatViewModel.applyGalgameMetadataPreview(payload: Map<String, Any?>) {
    val scoreObj = payload["score"] ?: return
    val cur = when (scoreObj) {
        is Map<*, *> -> (scoreObj["current"] as? Number)?.toInt()?.coerceIn(0, 100)
        is Number -> scoreObj.toInt().coerceIn(0, 100)
        else -> null
    } ?: return
    val mode = _state.value.mode
    val adj = if (mode == "galgame_lock" && cur <= 0) 1 else cur
    _state.value = _state.value.copy(galgameScore = adj)
}

internal fun ChatViewModel.updateLastAssistantMessage(content: String, isError: Boolean = false) {
    val msgs = _state.value.messages.toMutableList()
    val lastIdx = msgs.indexOfLast { it.isAssistant() }
    val generatedAt = System.currentTimeMillis()
    val generationDurationMs = currentGenerationDurationMs()
    if (lastIdx >= 0) {
        val current = msgs[lastIdx]
        msgs[lastIdx] = if (current.content == content && !current.isStreaming && current.isError == isError) current
        else current.copy(
            content = content,
            isStreaming = false,
            isError = isError,
            timestamp = generatedAt,
            generationDurationMs = generationDurationMs
        )
    }
    _state.value = _state.value.copy(messages = msgs, isStreaming = false)
    
    if (content.isNotBlank() && !isError) {
        val messageId = msgs.getOrNull(lastIdx)?.id ?: UUID.randomUUID().toString()
        sentMessages.add(
            ChatMessage(
                role = "assistant",
                content = content,
                messageId = messageId,
                timestamp = generatedAt,
                generationDurationMs = generationDurationMs
            )
        )
    }
}

internal fun ChatViewModel.currentGenerationDurationMs(): Long? {
    val fromTimer = _timerState.value.first
    if (fromTimer > 0L) return fromTimer
    if (startTime > 0L) {
        val elapsed = System.currentTimeMillis() - startTime
        if (elapsed > 0L) return elapsed
    }
    return null
}

internal fun ChatViewModel.startReplyTimer() {
    startTime = System.currentTimeMillis()
    currentRetryCount = 0
    _timerState.value = Triple(0L, 0, true)
    
    timerJob?.cancel()
    timerJob = viewModelScope.launch {
        while (true) {
            delay(1000)
            val elapsed = System.currentTimeMillis() - startTime
            _timerState.value = Triple(elapsed, currentRetryCount, true)
        }
    }
}

internal fun ChatViewModel.stopReplyTimer() {
    timerJob?.cancel()
    timerJob = null
    val (elapsed, retryCount, _) = _timerState.value
    _timerState.value = Triple(elapsed, retryCount, false)
}

internal fun ChatViewModel.incrementRetryCount() {
    currentRetryCount++
    val (elapsed, _, isRunning) = _timerState.value
    _timerState.value = Triple(elapsed, currentRetryCount, isRunning)
}

fun ChatViewModel.stopStreaming() {
    val hadStreamJob = streamJob != null
    val snapJobId = currentJobId
    val snapMode = _state.value.mode
    android.util.Log.d("PonyStop", "[stopStreaming] 开始 mode=$snapMode currentJobId=${snapJobId ?: "null"} streamJob=$hadStreamJob")
    streamJob?.cancel()
    streamJob = null
    stopReplyTimer()
    val character = _state.value.character
    val characterId = character?.id?.takeIf { it.isNotBlank() }
    if (characterId != null) {
        val jobIdToCancel = currentJobId
        android.util.Log.d("PonyStop", "[stopStreaming] 发起取消请求 char=${characterId.take(8)}... jobId=${jobIdToCancel ?: "null"} clientId=$clientId")
        viewModelScope.launch {
            val result = chatRepo.cancelGeneration(
                username = prefs.username,
                characterId = characterId,
                conversationId = _state.value.conversationId,
                clientId = clientId,
                jobId = jobIdToCancel,
            )
            if (result.isSuccess) {
                android.util.Log.d("PonyStop", "[stopStreaming] 取消请求成功 jobId=${jobIdToCancel ?: "null"}")
            } else {
                android.util.Log.e("PonyStop", "[stopStreaming] 取消请求失败: ${result.exceptionOrNull()?.message}")
            }
        }
    } else {
        android.util.Log.w("PonyStop", "[stopStreaming] characterId is empty, skip cancel request")
    }
    val msgs = _state.value.messages.toMutableList()
    val lastIdx = msgs.indexOfLast { it.isAssistant() && it.isStreaming }
    val hadContent = lastIdx >= 0 && msgs[lastIdx].content.isNotBlank()
    if (hadContent) {
        val content = stripThinkBlocksForDisplay(msgs[lastIdx].content)
        msgs[lastIdx] = msgs[lastIdx].copy(content = content, isStreaming = false)
        // 流式已有内容时：将截断的 AI 消息补入 sentMessages（finalize 未被调用故此处补全），
        // 以便 triggerAutoSave 能把完整对话轮次持久化到数据库
        val msgId = msgs[lastIdx].id
        val generatedAt = System.currentTimeMillis()
        if (sentMessages.none { it.messageId == msgId }) {
            sentMessages.add(
                ChatMessage(
                    role = "assistant",
                    content = content,
                    messageId = msgId,
                    timestamp = generatedAt
                )
            )
        }
    } else if (lastIdx >= 0) {
        // AI 尚未生成任何内容就被停止：移除 AI 占位气泡和末尾用户消息，恢复到发送前状态
        msgs.removeAt(lastIdx)
        val lastUserIdx = msgs.indexOfLast { it.isUser() }
        if (lastUserIdx >= 0) msgs.removeAt(lastUserIdx)
        if (sentMessages.isNotEmpty() && sentMessages.last().role == "assistant") sentMessages.removeAt(sentMessages.lastIndex)
        if (sentMessages.isNotEmpty() && sentMessages.last().role == "user") sentMessages.removeAt(sentMessages.lastIndex)
    }
    _state.value = _state.value.copy(
        messages = msgs,
        isStreaming = false,
        galgameStreamingStep = null
    )
    if (_state.value.mode == "normal") {
        resetNormalSendState()
    }
    // 有截断内容时保存到数据库（仅普通对话模式；游戏/锁分用 SSE result 与历史拉取对齐）
    if (hadContent && _state.value.mode == "normal") {
        character?.let { triggerAutoSave(it) }
    }
}

internal fun ChatViewModel.triggerAutoSave(character: Character, saveIntent: String = "auto_sync") {
    character.id?.takeIf { it.isNotBlank() } ?: return
    if (_state.value.isStreaming) return
    autoSaveJob = viewModelScope.launch {
        delay(300)
        DebugLog.d(TAG, "[HistoryDebug] triggerAutoSave skipped ($saveIntent); refreshing from authoritative server history")
        if (_state.value.mode == "normal") {
            refreshNewMessagesFromServer()
        } else {
            refreshConversationFromServer()
        }
    }
}

internal fun ChatViewModel.persistAcceptedUserRound(characterId: String, mode: String) {
    val snapshot = sentMessages.toList()
    if (snapshot.isEmpty()) return
    val visibleSnapshot = snapshot.filter { it.isHidden != true }
    localCache.saveConversation(
        username = prefs.username,
        characterId = characterId,
        mode = mode,
        conversationId = _state.value.conversationId,
        messages = snapshot,
        lockCharVitals = if (mode == "galgame_lock") _state.value.lockCharVitals.ifEmpty { null } else null,
        lockCharMood = if (mode == "galgame_lock") _state.value.lockCharMood.ifEmpty { null } else null,
        lockOrganFill = if (mode == "galgame_lock") _state.value.lockOrganFill.ifEmpty { null } else null,
        lockCharGender = if (mode == "galgame_lock") _state.value.lockCharGender.ifBlank { null } else null
    )
    val lastMsgTime = visibleSnapshot.lastOrNull()?.timestamp ?: return
    prefs.setModeLastChatTime(characterId, mode, lastMsgTime)
}

internal fun ChatViewModel.removeUnacceptedUserMessage(messageId: String) {
    val msgs = _state.value.messages.filterNot { it.id == messageId || it.messageId == messageId }
    _state.value = _state.value.copy(messages = msgs)
    val idx = sentMessages.indexOfLast { it.messageId == messageId && it.role == "user" }
    if (idx >= 0) sentMessages.removeAt(idx)
    unconfirmedNormalUserKeys.remove(messageId)
}

internal suspend fun ChatViewModel.warmupOtherGalgameModeCache(
    username: String,
    characterId: String,
    currentMode: String,
    includeCurrent: Boolean = false
) {
    if (!currentMode.startsWith("galgame")) return
    val modes = if (includeCurrent) listOf("galgame", "galgame_lock")
    else listOf(if (currentMode == "galgame") "galgame_lock" else "galgame")
    modes.forEach { mode ->
        runCatching {
            val detail = charRepo.loadConversationDetail(username, characterId, mode = mode).getOrThrow()
            if (detail.messages.isNotEmpty()) {
                localCache.saveConversation(
                    username = username,
                    characterId = characterId,
                    mode = mode,
                    conversationId = detail.conversationId ?: characterId,
                    messages = detail.messages,
                    lockCharVitals = if (mode == "galgame_lock") detail.charVitals else null,
                    lockCharMood   = if (mode == "galgame_lock") detail.charMood   else null,
                    lockOrganFill  = if (mode == "galgame_lock") detail.organFill  else null,
                    lockCharGender = if (mode == "galgame_lock") detail.characterGender?.takeIf { it.isNotBlank() } else null
                )
            }
        }.onFailure { err ->
            DebugLog.w(TAG, "Warmup cache failed for $mode: ${err.message}", err)
        }
    }
}
