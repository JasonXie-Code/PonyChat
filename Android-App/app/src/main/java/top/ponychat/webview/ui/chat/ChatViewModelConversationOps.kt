package top.ponychat.webview.ui.chat

import android.app.Application
import android.util.Log
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.repo.ChatDelta
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ClientContextHelper
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.GalgameNotificationPreview
import top.ponychat.webview.util.toUserMessage
import java.util.UUID
fun ChatViewModel.newConversation() {
    val prevCid = _state.value.conversationId
    if (_state.value.mode == "normal") {
        viewModelScope.launch { _snackbarMessages.emit("普通对话只保留一个对话，可在历史页重置角色内容") }
        return
    }
    if (_state.value.isStreaming) {
        stopStreaming()
    }
    // 新建会话时终止进行中的历史/切换请求，防止旧请求晚到覆盖新会话状态。
    historyLoadJob?.cancel()
    switchConversationJob?.cancel()

    // [防抖自动保存] 取消待定的防抖自动保存，防止它在 sentMessages 清空、conversationId 已切换后
    // 仍以「新 ID + 空消息」写入 localCache，污染新会话的 __latest 条目或丢弃旧会话数据。
    // 若当前有未保存消息，先快照并立即触发一次保存（fire-and-forget），确保旧对话数据不丢失。
    autoSaveJob?.cancel()
    autoSaveJob = null
    val character = _state.value.character
    val characterId = character?.id?.takeIf { it.isNotBlank() }
    val mode = _state.value.mode
    if (character != null && characterId != null && !mode.startsWith("galgame") && sentMessages.isNotEmpty()) {
        val snapshotCid = prevCid
        val snapshotMsgs = sentMessages.toList()
        viewModelScope.launch {
            try {
                localCache.saveConversation(
                    username = prefs.username,
                    characterId = characterId,
                    mode = mode,
                    conversationId = snapshotCid,
                    messages = snapshotMsgs
                )
            } catch (e: Exception) {
                DebugLog.w(TAG, "[HistoryDebug] newConversation pre-save failed: ${e.message}", e)
            }
        }
    }

    sentMessages.clear()
    resetNormalSendState()
    val newCid = newConversationId()
    DebugLog.d(TAG, "[HistoryDebug] newConversation: prevCid=$prevCid -> newCid=$newCid")
    // 立即分配新的对话 ID，确保本会话所有消息都属于同一会话，
    // 避免每条消息携带 null 被后端各自生成随机 ID，造成对话碎片化。
    _state.value = _state.value.copy(
        messages = emptyList(),
        inputText = "",
        isStreaming = false,
        isLoadingHistory = false,
        error = null,
        conversationId = newCid
    )
}

/** 角色重置后清除本机普通对话缓存，避免离线兜底重新显示已隐藏内容。 */
fun ChatViewModel.clearCurrentNormalLocalCache() {
    val username = prefs.username.ifBlank { return }
    val charId = _state.value.character?.id?.takeIf { it.isNotBlank() } ?: return
    viewModelScope.launch(Dispatchers.IO) {
        localCache.clearForCharacterMode(username, charId, "normal")
    }
}

/** 角色重置成功后立即清空普通对话本地可见状态，让页面可立刻返回聊天页。 */
fun ChatViewModel.applyNormalResetLocally() {
    if (_state.value.mode != "normal") {
        clearCurrentNormalLocalCache()
        return
    }
    if (_state.value.isStreaming) {
        stopStreaming()
    }
    historyLoadJob?.cancel()
    switchConversationJob?.cancel()
    autoSaveJob?.cancel()
    autoSaveJob = null
    sentMessages.clear()
    resetNormalSendState()
    _state.value = _state.value.copy(
        messages = emptyList(),
        inputText = "",
        isStreaming = false,
        isLoadingHistory = false,
        isBackgroundRefreshing = false,
        error = null,
        errorDebug = null,
        quotedMessage = null
    )
    clearCurrentNormalLocalCache()
}

/** 加载该角色的所有历史对话 */
fun ChatViewModel.loadConversationList() {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username
    DebugLog.d(TAG, "[HistoryDebug] loadConversationList START: char=$characterId mode=${_state.value.mode} currentCid=${_state.value.conversationId}")

    conversationListJob?.cancel()
    conversationListJob = viewModelScope.launch {
        // 取消防抖定时器，立即把当前会话同步到后端，避免刚聊完就打开历史时出现竞态条件
        val mode = _state.value.mode
        if (!mode.startsWith("galgame") && sentMessages.isNotEmpty()) {
            DebugLog.d(TAG, "[HistoryDebug] Skip pre-list save; server message history is authoritative")
        }
        _state.value = _state.value.copy(isLoadingConversations = true)
        charRepo.loadAllConversations(username, characterId, _state.value.mode).fold(
            onSuccess = { list ->
                DebugLog.d(TAG, "[HistoryDebug] loadAllConversations SUCCESS: count=${list.size} ids=${list.map { it.id.take(20) }}")
                val summaries = list.map { conv ->
                    val createdAt = conv.timestamp.takeIf { it > 0 }?.toString() ?: conv.updatedAt
                    ConversationSummary(
                        id = conv.id,
                        title = conv.title.ifBlank {
                            conv.messages.lastOrNull { it.role == "user" }?.content
                                ?.take(30) ?: "对话 ${conv.id.takeLast(6)}"
                        },
                        updatedAt = conv.updatedAt,
                        createdAt = createdAt,
                        messageCount = conv.messages.size,
                        totalChars = conversationTextCharsFromChatMessage(conv.messages)
                    )
                }
                val sorted = sortConversations(summaries, _state.value.historySortField, _state.value.historySortOrder)
                DebugLog.d(TAG, "[HistoryDebug] set conversations: size=${sorted.size} ids=${sorted.map { it.id.take(20) }}")
                _state.value = _state.value.copy(
                    conversations = sorted,
                    isLoadingConversations = false,
                    error = null
                )
            },
            onFailure = { err ->
                DebugLog.w(TAG, "loadConversationList failed: ${err.message}", err)
                DebugLog.d(TAG, "[HistoryDebug] loadAllConversations FAILED, fallback to localCache")
                val cachedList = localCache.loadConversationList(username, characterId, _state.value.mode)
                DebugLog.d(TAG, "[HistoryDebug] localCache.loadConversationList: count=${cachedList.size}")
                if (cachedList.isNotEmpty()) {
                    val summaries = cachedList.mapNotNull { conv ->
                        val convId = conv.conversationId?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
                        val title = conv.messages.lastOrNull { it.role == "user" }?.content
                            ?.take(30)
                            ?.ifBlank { null }
                            ?: "对话 ${convId.takeLast(6)}"
                        val chars = conversationTextCharsFromChatMessage(conv.messages)
                        ConversationSummary(
                            id = convId,
                            title = title,
                            updatedAt = conv.updatedAt.toString(),
                            createdAt = conv.updatedAt.toString(),
                            messageCount = conv.messageCount,
                            totalChars = chars
                        )
                    }
                    if (summaries.isNotEmpty()) {
                        val sorted = sortConversations(summaries, _state.value.historySortField, _state.value.historySortOrder)
                        _state.value = _state.value.copy(
                            conversations = sorted,
                            isLoadingConversations = false,
                            error = "当前使用本地历史，可到设置检查网络与服务器地址",
                        )
                    } else {
                        _state.value = _state.value.copy(
                            isLoadingConversations = false,
                            error = "加载历史失败"
                        )
                    }
                } else {
                    _state.value = _state.value.copy(
                        isLoadingConversations = false,
                        error = "加载历史失败",
                    )
                }
            }
        )
    }
}

// 向上翻页：加载比当前最小 sequence_number 更早的消息（仅 normal 模式）
fun ChatViewModel.loadMoreHistory() {
    val mode = _state.value.mode
    if (mode.startsWith("galgame")) return
    if (_state.value.isLoadingHistory || _state.value.isLoadingMoreHistory) return
    if (!_state.value.hasMoreHistory) return
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username
    val beforeSeq = _state.value.minLoadedSeq.takeIf { it != Int.MAX_VALUE }

    _state.value = _state.value.copy(isLoadingMoreHistory = true)
    viewModelScope.launch {
        val result = chatRepo.loadMessagesBefore(
            username = username,
            characterId = characterId,
            conversationId = _state.value.conversationId,
            beforeSeq = beforeSeq,
            limit = NORMAL_HISTORY_PAGE_LIMIT
        )
        if (result != null) {
            val runtimeSpeakerFallback = sentMessages.toList()
            val olderChatMessages = preserveChatMessageSpeakers(result.messages, runtimeSpeakerFallback)
            val olderUiMessages = visibleMessagesForUi(
                olderChatMessages,
                username,
                characterId,
                mode,
                _state.value.conversationId,
                _state.value.messages
            )
            val existingUiIds = _state.value.messages.map { it.id }.toSet()
            val newMessages = olderUiMessages.filter { it.id !in existingUiIds } + _state.value.messages
            // 同步更新 sentMessages（在头部插入历史消息，避免上下文丢失）
            val existingIds = sentMessages.map { it.messageId }.toSet()
            val newSent = runtimeMessagesForClientWithLocalImages(olderChatMessages, runtimeSpeakerFallback).filter { it.messageId !in existingIds }
            sentMessages.addAll(0, newSent)
            _state.value = _state.value.copy(
                messages = newMessages,
                hasMoreHistory = result.hasMore,
                minLoadedSeq = minOf(minSequenceOf(olderChatMessages, result.minSeq), _state.value.minLoadedSeq),
                isLoadingMoreHistory = false
            )
        } else {
            _state.value = _state.value.copy(isLoadingMoreHistory = false)
        }
    }
}

suspend fun ChatViewModel.ensureMessageLoaded(messageId: String, maxPages: Int = 20): Boolean {
    if (messageId.isBlank()) return false
    if (_state.value.messages.any { it.id == messageId || it.messageId == messageId }) return true
    val mode = _state.value.mode
    if (mode.startsWith("galgame")) return false
    if (_state.value.isLoadingHistory || _state.value.isLoadingMoreHistory) return false
    val character = _state.value.character ?: return false
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return false
    val username = prefs.username

    var pagesLoaded = 0
    while (pagesLoaded < maxPages && _state.value.hasMoreHistory) {
        val beforeSeq = _state.value.minLoadedSeq.takeIf { it != Int.MAX_VALUE }
        _state.value = _state.value.copy(isLoadingMoreHistory = true)
        val result = chatRepo.loadMessagesBefore(
            username = username,
            characterId = characterId,
            conversationId = _state.value.conversationId,
            beforeSeq = beforeSeq,
            limit = NORMAL_HISTORY_PAGE_LIMIT
        )
        if (result == null) {
            _state.value = _state.value.copy(isLoadingMoreHistory = false)
            return false
        }
        val runtimeSpeakerFallback = sentMessages.toList()
        val olderChatMessages = preserveChatMessageSpeakers(result.messages, runtimeSpeakerFallback)
        val olderUiMessages = visibleMessagesForUi(
            olderChatMessages,
            username,
            characterId,
            mode,
            _state.value.conversationId,
            _state.value.messages
        )
        val existingUiIds = _state.value.messages.map { it.id }.toSet()
        val newMessages = olderUiMessages.filter { it.id !in existingUiIds } + _state.value.messages
        val existingSentIds = sentMessages.map { it.messageId }.toSet()
        val newSent = runtimeMessagesForClientWithLocalImages(olderChatMessages, runtimeSpeakerFallback).filter { it.messageId !in existingSentIds }
        sentMessages.addAll(0, newSent)
        _state.value = _state.value.copy(
            messages = newMessages,
            hasMoreHistory = result.hasMore,
            minLoadedSeq = minOf(minSequenceOf(olderChatMessages, result.minSeq), _state.value.minLoadedSeq),
            isLoadingMoreHistory = false
        )
        if (newMessages.any { it.id == messageId || it.messageId == messageId }) return true
        pagesLoaded++
    }
    return _state.value.messages.any { it.id == messageId || it.messageId == messageId }
}

/** 切换到指定对话 */
fun ChatViewModel.switchConversation(conversationId: String) {
    if (_state.value.isStreaming) return
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username

    sentMessages.clear()
    // 立即清空 messages，避免切换时短暂显示旧对话内容（中间态）
    _state.value = _state.value.copy(
        isLoadingHistory = true,
        conversationId = conversationId,
        messages = emptyList()
    )

    switchConversationJob?.cancel()
    switchConversationJob = viewModelScope.launch {
        val switchMode = _state.value.mode
        if (switchMode == "normal") {
            val result = chatRepo.loadMessagesBefore(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                beforeSeq = null,
                limit = NORMAL_HISTORY_INITIAL_LIMIT
            )
            if (result != null) {
                if (!_state.value.isLoadingHistory) {
                    DebugLog.d(TAG, "[HistoryDebug] switchConversation page STALE, discarding")
                    return@launch
                }
                val serverMessages = result.messages
                val uiMessages = visibleMessagesForUi(serverMessages, username, characterId, switchMode, conversationId)
                sentMessages.clear()
                sentMessages.addAll(runtimeMessagesForClientWithLocalImages(serverMessages))
                _state.value = _state.value.copy(
                    messages = uiMessages,
                    conversationId = result.conversationId?.takeIf { it.isNotBlank() } ?: conversationId,
                    isLoadingHistory = false,
                    isLoadingMoreHistory = false,
                    minLoadedSeq = minSequenceOf(serverMessages, result.minSeq),
                    hasMoreHistory = result.hasMore,
                    error = null,
                    errorDebug = null
                )
                localCache.saveConversation(
                    username = username,
                    characterId = characterId,
                    mode = switchMode,
                    conversationId = result.conversationId?.takeIf { it.isNotBlank() } ?: conversationId,
                    messages = serverMessages
                )
                return@launch
            }
        }
        charRepo.loadConversationDetail(username, characterId, conversationId, switchMode).fold(
            onSuccess = { detail ->
                // [过期加载守卫] newConversation() 在请求期间抢先执行时丢弃结果
                if (!_state.value.isLoadingHistory) {
                    DebugLog.d(TAG, "[HistoryDebug] switchConversation STALE, discarding")
                    return@fold
                }
                val serverMessages = detail.messages
                val usage = detail.usage
                val uiMessages = visibleMessagesForUi(serverMessages, username, characterId, switchMode, conversationId)
                sentMessages.clear()
                sentMessages.addAll(runtimeMessagesForClientWithLocalImages(serverMessages))
                val newScore = if (switchMode == "galgame" || switchMode == "galgame_lock") detail.score else null
                _state.value = _state.value.copy(
                    messages = uiMessages,
                    isLoadingHistory = false,
                    contextUsedTokens = usage?.totalTokens ?: 0,
                    contextLimitTokens = usage?.limitTokens?.takeIf { it > 0 } ?: 64000,
                    galgameScore = newScore,
                    galgameVictoryCelebrationAck = if (switchMode == "galgame" || switchMode == "galgame_lock") {
                        detail.victoryCelebrationAck
                    } else false,
                    error = null
                )
                checkAndAutoSummarize()
                localCache.saveConversation(
                    username = username,
                    characterId = characterId,
                    mode = switchMode,
                    conversationId = conversationId,
                    messages = serverMessages
                )
            },
            onFailure = { err ->
                if (err is CancellationException) {
                    _state.value = _state.value.copy(isLoadingHistory = false)
                    return@fold
                }
                DebugLog.w(TAG, "switchConversation failed: ${err.message}", err)
                val cached = localCache.loadConversation(
                    username = username,
                    characterId = characterId,
                    mode = switchMode,
                    conversationId = conversationId
                )
                if (cached != null && cached.messages.isNotEmpty()) {
                    val uiMessages = visibleMessagesForUi(cached.messages, username, characterId, switchMode, conversationId)
                    sentMessages.clear()
                    sentMessages.addAll(runtimeMessagesForClientWithLocalImages(cached.messages))
                    _state.value = _state.value.copy(
                        messages = uiMessages,
                        isLoadingHistory = false,
                        error = "当前使用本地缓存，可到设置检查网络与服务器地址",
                        galgameScore = if (switchMode == "galgame" || switchMode == "galgame_lock") parseScoreFromLastMessage(cached.messages) else null,
                        galgameVictoryCelebrationAck = false,
                        errorDebug = "switchConversation fallback cache"
                    )
                } else {
                    _state.value = _state.value.copy(
                        isLoadingHistory = false,
                        error = "加载对话失败",
                        errorDebug = "switchConversation failed without cache"
                    )
                }
            }
        )
    }
}

/** 删除某个历史对话 */
fun ChatViewModel.deleteConversation(conversationId: String) {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username
    val isDeletingCurrent = _state.value.conversationId == conversationId

    viewModelScope.launch {
        charRepo.deleteConversation(username, characterId, conversationId).fold(
            onSuccess = {
                localCache.removeConversation(username, characterId, _state.value.mode, conversationId)
                val updatedConversations = _state.value.conversations.filter { it.id != conversationId }
                if (isDeletingCurrent) {
                    // 删除的是当前对话：清空消息并分配新 ID，
                    // 防止后续 triggerAutoSave 用旧 ID 把软删除的对话恢复。
                    sentMessages.clear()
                    _state.value = _state.value.copy(
                        messages = emptyList(),
                        inputText = "",
                        isStreaming = false,
                        error = null,
                        conversationId = newConversationId(),
                        conversations = updatedConversations
                    )
                } else {
                    _state.value = _state.value.copy(
                        conversations = updatedConversations,
                        error = null
                    )
                }
            },
            onFailure = { err ->
                DebugLog.w(TAG, "deleteConversation failed: ${err.message}", err)
                _state.value = _state.value.copy(error = err.toUserMessage("删除对话失败"))
            }
        )
    }
}

/** 设置历史对话排序并重新排序当前列表 */
fun ChatViewModel.setHistorySort(field: String, order: String) {
    val current = _state.value.conversations
    if (current.isEmpty()) {
        _state.value = _state.value.copy(historySortField = field, historySortOrder = order)
        return
    }
    val sorted = sortConversations(current, field, order)
    _state.value = _state.value.copy(
        historySortField = field,
        historySortOrder = order,
        conversations = sorted
    )
}
