package top.ponychat.webview.ui.chat

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.util.ChatCompletedEvent

internal data class NormalDeliveryNotice(
    val username: String, val characterId: String, val conversationId: String?, val messageId: String,
)

/** Fill recently released holes before deciding a foregrounded reply is complete. */
internal fun ChatViewModel.resumeReplyRecovery(reason: String) {
    val scope = _state.value.let { Triple(prefs.username, it.character?.id, it.conversationId) }
    viewModelScope.launch {
        if (_state.value.mode == "normal") {
            refreshNewMessagesFromServer(allowWhileStreaming = true, includeRecent = true)
            historyLoadJob?.join()
        }
        val current = _state.value
        if (current.isStreaming && scope == Triple(prefs.username, current.character?.id, current.conversationId)) {
            startReplyRecoveryPolling(reason, current.mode, null, System.currentTimeMillis() - 1200L)
        }
    }
}

/** Serialize notifications so an older outbox item cannot cancel a newer one. */
internal suspend fun ChatViewModel.refreshNormalMessageDelivery(event: ChatCompletedEvent) {
    if (_state.value.mode != "normal" || _state.value.character?.id != event.characterId) return
    val activeConversation = _state.value.conversationId
    if (activeConversation != null && event.conversationId != null && activeConversation != event.conversationId) return
    val notice = event.messageId?.let { NormalDeliveryNotice(prefs.username, event.characterId, event.conversationId, it) }
    if (notice != null) pendingNormalDeliveries.add(notice)
    repeat(2) {
        if (_state.value.character?.id != event.characterId || _state.value.mode != "normal") return
        if (notice != null && (prefs.username != notice.username ||
            (_state.value.conversationId != null && notice.conversationId != null && _state.value.conversationId != notice.conversationId))) return
        if (notice != null && _state.value.messages.any { it.messageId == notice.messageId || it.id == notice.messageId }) {
            pendingNormalDeliveries.remove(notice)
            return
        }
        refreshNewMessagesFromServer(allowWhileStreaming = true,
            throughMessageId = event.messageId, notifiedConversationId = event.conversationId)
        val refresh = historyLoadJob
        refresh?.join()
        if (refresh?.isCancelled != true) return
        // Resume/network refresh may replace the shared history job. Keep its
        // acknowledged message ID until an actual UI merge has repaired it.
    }
}

internal fun messagesThroughDeliveredId(messages: List<ChatMessage>, messageId: String?): List<ChatMessage> {
    if (messageId == null) return messages
    val target = messages.firstOrNull { it.messageId == messageId } ?: return emptyList()
    val sequence = target.sequenceNumber ?: return listOf(target)
    return messages.filter { (it.sequenceNumber ?: Int.MAX_VALUE) <= sequence }
}

/** normal 模式按 sequence_number 增量补拉；缺少序号或接口失败时回退全量刷新。 */
internal fun ChatViewModel.refreshNewMessagesFromServer(
    allowWhileStreaming: Boolean = false,
    throughMessageId: String? = null,
    notifiedConversationId: String? = null,
    includeRecent: Boolean = false,
) {
    if (_state.value.isStreaming && !allowWhileStreaming) return
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username
    val conversationId = notifiedConversationId?.takeIf { it.isNotBlank() }
        ?: _state.value.conversationId?.takeIf { it.isNotBlank() }
    val startSeq = _state.value.messages.mapNotNull { it.sequenceNumber }.maxOrNull()
    if (conversationId == null) {
        refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
        return
    }
    if (startSeq == null && throughMessageId == null) {
        refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
        return
    }
    _state.value = _state.value.copy(isBackgroundRefreshing = true, error = null, errorDebug = null)
    historyLoadJob?.cancel()
    historyLoadJob = viewModelScope.launch {
        val collected = mutableListOf<ChatMessage>()
        var afterSeq = startSeq ?: 0
        var ok = true
        var pages = 0
        var initialHasMore = false
        while (pages < 5) {
            pages++
            val page = if (startSeq == null) chatRepo.loadMessagesBefore(
                username = username, characterId = characterId, conversationId = conversationId,
                beforeSeq = null, limit = NORMAL_HISTORY_INITIAL_LIMIT,
            ) else chatRepo.loadMessagesAfter(
                username = username,
                characterId = characterId,
                conversationId = conversationId,
                afterSeq = afterSeq,
                limit = 100
            )
            coroutineContext.ensureActive()
            if (page == null) {
                ok = false
                break
            }
            val batch = page.messages
            initialHasMore = page.hasMore
            if (batch.isEmpty()) break
            collected.addAll(batch)
            afterSeq = page.maxSeq ?: batch.mapNotNull { it.sequenceNumber }.maxOrNull() ?: afterSeq
            if (startSeq == null || !page.hasMore || batch.any { it.messageId == throughMessageId }) break
        }
        // Guest turns can be committed in a different order from their delivery.
        // A released lower-sequence message must still be fetched by its real ID.
        if (includeRecent && startSeq != null) {
            chatRepo.loadMessagesBefore(username, characterId, conversationId, beforeSeq = null,
                limit = NORMAL_HISTORY_INITIAL_LIMIT)?.let { collected.addAll(it.messages) }
        }
        val repairIds = pendingNormalDeliveries.filter {
            it.username == username && it.characterId == characterId &&
                (it.conversationId == null || it.conversationId == conversationId)
        }.map { it.messageId }.toSet() + listOfNotNull(throughMessageId)
        for (messageId in repairIds) {
            if (collected.any { it.messageId == messageId }) continue
            if (throughMessageId != messageId && _state.value.messages.any { it.messageId == messageId || it.id == messageId }) continue
            chatRepo.loadDeliveredMessage(username, characterId, conversationId, messageId)?.let {
                collected.add(it)
                ok = true
            }
        }
        coroutineContext.ensureActive()
        if (prefs.username != username || _state.value.character?.id != characterId || _state.value.mode != "normal" ||
            (_state.value.conversationId != null && _state.value.conversationId != conversationId)) return@launch
        if (!ok) {
            _state.value = _state.value.copy(isBackgroundRefreshing = false)
            if (throughMessageId == null) refreshConversationFromServer(allowWhileStreaming = allowWhileStreaming)
            return@launch
        }
        if (collected.isEmpty()) {
            _state.value = _state.value.copy(isBackgroundRefreshing = false)
            return@launch
        }
        val released = messagesThroughDeliveredId(collected.distinctBy { chatMessageKey(it) }, throughMessageId)
        val deliverable = if (allowWhileStreaming && _state.value.mode == "normal" && _state.value.isStreaming) {
            released.filterNot { msg ->
                msg.role == "assistant" &&
                    effectiveVoiceState(msg)?.status?.equals("pending", ignoreCase = true) == true
            }
        } else {
            released
        }
        if (deliverable.isEmpty()) {
            _state.value = _state.value.copy(isBackgroundRefreshing = false)
            return@launch
        }
        val uiSpeakerFallback = _state.value.messages
        val runtimeSpeakerFallback = sentMessages.toList()
        val collectedWithSpeakers = preserveChatMessageSpeakers(deliverable, runtimeSpeakerFallback)
        val serverUiMessages = visibleMessagesForUi(
            collectedWithSpeakers,
            username,
            characterId,
            "normal",
            conversationId,
            uiSpeakerFallback
        )
        val serverUiByKey = serverUiMessages.associateBy { uiMessageKey(it) }
        val existingUiKeys = _state.value.messages.map { uiMessageKey(it) }.toSet()
        val mergedUiMessages = orderedUiMessages(_state.value.messages.map { msg ->
            val authoritative = serverUiByKey[uiMessageKey(msg)]
            if (msg.isRetracted && authoritative?.isRetracted != true) msg else authoritative ?: msg
        } + serverUiMessages.filter { uiMessageKey(it) !in existingUiKeys })
        val serverRuntimeMessages = runtimeMessagesForClientWithLocalImages(collectedWithSpeakers, runtimeSpeakerFallback)
        val serverSentByKey = serverRuntimeMessages.associateBy { chatMessageKey(it) }
        val existingSentKeys = sentMessages.map { chatMessageKey(it) }.toSet()
        for (i in sentMessages.indices) {
            serverSentByKey[chatMessageKey(sentMessages[i])]?.let { authoritative ->
                sentMessages[i] = authoritative
            }
        }
        val newSent = serverRuntimeMessages.filter { chatMessageKey(it) !in existingSentKeys }
        sentMessages.addAll(newSent)
        val orderedSent = orderedChatMessages(sentMessages.toList())
        sentMessages.clear()
        sentMessages.addAll(orderedSent)
        val currentState = _state.value
        val nextUiMessages = if (currentState.messages.isSameVisibleMessageListAs(mergedUiMessages)) {
            currentState.messages
        } else {
            mergedUiMessages
        }
        _state.value = currentState.copy(
            messages = nextUiMessages,
            conversationId = conversationId,
            isLoadingHistory = false,
            minLoadedSeq = if (startSeq == null) minSequenceOf(deliverable) else currentState.minLoadedSeq,
            hasMoreHistory = if (startSeq == null) initialHasMore else currentState.hasMoreHistory,
            isBackgroundRefreshing = false,
            error = null,
            errorDebug = null
        )
        pendingNormalDeliveries.removeAll { notice ->
            notice.username == username && notice.characterId == characterId &&
                (notice.conversationId == null || notice.conversationId == conversationId) &&
                nextUiMessages.any { it.messageId == notice.messageId || it.id == notice.messageId }
        }
        if (serverUiMessages.any { it.isAssistant() && !it.isStreaming && !it.isError }) {
            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
        }
        localCache.saveConversation(
            username = username,
            characterId = characterId,
            mode = "normal",
            conversationId = conversationId,
            messages = sentMessages.toList()
        )
        markNormalReplySucceeded("server_incremental_refresh")
    }
}
