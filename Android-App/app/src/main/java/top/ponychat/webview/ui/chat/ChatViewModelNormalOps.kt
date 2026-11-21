package top.ponychat.webview.ui.chat

import android.app.Application
import android.content.SharedPreferences
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import top.ponychat.webview.data.local.CachedVoiceAudio
import top.ponychat.webview.data.local.LocalCacheStore
import top.ponychat.webview.data.local.ChatVoiceCache
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.data.repo.CharacterRepository
import top.ponychat.webview.data.repo.ChatDelta
import top.ponychat.webview.data.repo.ChatRepository
import top.ponychat.webview.data.api.SyncWebSocketManager
import top.ponychat.webview.util.ChatCompletionSource
import top.ponychat.webview.util.ChatEventBus
import top.ponychat.webview.util.ClientContextHelper
import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.util.GalgameNotificationPreview
import top.ponychat.webview.util.MessageVibrationHelper
import top.ponychat.webview.util.toUserMessage
import java.util.UUID

internal const val DEBUG_PENDING_USER_ACCEPT_PREFIX = "debug_pending_user_"

fun ChatViewModel.loadStickers(source: String = "all") {
    _state.value = _state.value.copy(isLoadingStickers = true)
    viewModelScope.launch {
        val result = chatRepo.loadStickers(source)
        _state.value = _state.value.copy(
            stickers = result.getOrElse { _state.value.stickers },
            isLoadingStickers = false
        )
        result.exceptionOrNull()?.let { _snackbarMessages.tryEmit(it.message ?: "加载表情失败") }
    }
}

fun ChatViewModel.saveStickerToMine(assetId: String) {
    viewModelScope.launch {
        val result = chatRepo.saveSticker(assetId)
        result.onSuccess {
            loadStickers()
            _snackbarMessages.tryEmit("已添加到我的表情")
        }.onFailure {
            _snackbarMessages.tryEmit(it.message ?: "收藏表情失败")
        }
    }
}

fun ChatViewModel.uploadSticker(file: java.io.File, displayName: String) {
    _state.value = _state.value.copy(isLoadingStickers = true)
    viewModelScope.launch {
        val result = chatRepo.uploadSticker(file, displayName)
        result.onSuccess {
            loadStickers()
            _snackbarMessages.tryEmit("表情已上传并自动打标签")
        }.onFailure {
            _state.value = _state.value.copy(isLoadingStickers = false)
            _snackbarMessages.tryEmit(it.message ?: "上传表情失败")
        }
    }
}

fun ChatViewModel.deleteSticker(sticker: StickerAsset) {
    val stickerId = sticker.userStickerId?.takeIf { it.isNotBlank() }
    if (stickerId == null) {
        _snackbarMessages.tryEmit("平台表情暂不支持移除")
        return
    }
    viewModelScope.launch {
        val result = chatRepo.deleteSticker(stickerId)
        result.onSuccess {
            _state.value = _state.value.copy(
                stickers = _state.value.stickers.filterNot { it.userStickerId == stickerId }
            )
            _snackbarMessages.tryEmit("已移除表情")
        }.onFailure {
            _snackbarMessages.tryEmit(it.message ?: "移除表情失败")
        }
    }
}

internal fun ChatViewModel.resetNormalSendState(
    cancelRecoveryJobs: Boolean = true,
    clearUnconfirmedUsers: Boolean = true,
) {
    normalTransportRetryJob?.cancel()
    normalTransportRetryJob = null
    if (cancelRecoveryJobs) {
        replyRecoveryPollJob?.cancel()
        replyRecoveryPollJob = null
        normalAcceptedRecoveryJob?.cancel()
        normalAcceptedRecoveryJob = null
    }
    normalAssistantVisible = false
    normalGenerationStarted = false
    lastNormalGenerationStartedAtMs = 0L
    lastNormalGenerationStartSeq = null
    normalGenerationUserIds.clear()
    normalUploadingUserMessageIds.clear()
    if (clearUnconfirmedUsers) {
        unconfirmedNormalUserKeys.clear()
    }
    deferredNormalReplyCharacterIds.clear()
    currentJobId = null
    _state.value = _state.value.copy(isStreaming = false)
}

internal fun ChatViewModel.ensureConversationId(): String {
    val existing = _state.value.conversationId
    if (!existing.isNullOrBlank()) return existing
    val cid = newConversationId()
    _state.value = _state.value.copy(conversationId = cid)
    return cid
}

internal fun ChatViewModel.appendUserTextMessage(text: String): Message? {
    val quotedMessage = _state.value.quotedMessage
    val conversationId = ensureConversationId()
    val messageId = UUID.randomUUID().toString()
    val now = System.currentTimeMillis()
    val userMsg = Message(
        id = messageId,
        role = "user",
        content = text,
        timestamp = now,
        messageId = messageId,
        quotedMessage = quotedMessage,
        isPendingServerAccept = true,
        pendingServerAcceptStartedAt = now
    )
    _state.value = _state.value.copy(
        conversationId = conversationId,
        messages = _state.value.messages + userMsg,
        inputText = "",
        error = null,
        errorDebug = null,
        quotedMessage = null
    )
    sentMessages.add(
        ChatMessage(
            role = "user",
            content = text,
            messageId = userMsg.id,
            timestamp = userMsg.timestamp,
            quotedMessage = quotedMessage
        )
    )
    rememberUnconfirmedNormalUser(messageId)
    return userMsg
}

fun ChatViewModel.appendUploadingUserMessage(content: String): String? {
    val text = content.trim()
    if (text.isBlank()) return null
    if (_state.value.mode != "normal") return null
    clearFailedChatRoundIfNeeded()
    startUsageTracking()
    val quotedMessage = _state.value.quotedMessage
    val conversationId = ensureConversationId()
    val messageId = UUID.randomUUID().toString()
    val now = System.currentTimeMillis()
    val userMsg = Message(
        id = messageId,
        role = "user",
        content = text,
        timestamp = now,
        messageId = messageId,
        quotedMessage = quotedMessage,
        isPendingServerAccept = true,
        pendingServerAcceptStartedAt = now
    )
    _state.value = _state.value.copy(
        conversationId = conversationId,
        messages = _state.value.messages + userMsg,
        inputText = "",
        error = null,
        errorDebug = null,
        quotedMessage = null
    )
    sentMessages.add(
        ChatMessage(
            role = "user",
            content = text,
            messageId = messageId,
            timestamp = userMsg.timestamp,
            quotedMessage = quotedMessage
        )
    )
    normalUploadingUserMessageIds.add(messageId)
    rememberUnconfirmedNormalUser(messageId)
    interruptProactiveGenerationForUserMessage()
    return messageId
}

fun ChatViewModel.completeUploadingUserMessage(
    messageId: String,
    content: String,
    replyCharacterIds: List<String> = emptyList(),
) {
    val finalContent = content.trim()
    if (messageId.isBlank() || finalContent.isBlank()) return
    val msgs = _state.value.messages.map { msg ->
        if (msg.id == messageId || msg.messageId == messageId) {
            msg.copy(content = finalContent, isStreaming = false, isError = false)
        } else {
            msg
        }
    }
    _state.value = _state.value.copy(messages = msgs, error = null, errorDebug = null)
    val sentIdx = sentMessages.indexOfLast { it.messageId == messageId && it.role == "user" }
    if (sentIdx >= 0) {
        sentMessages[sentIdx] = sentMessages[sentIdx].copy(content = finalContent)
    }
    rememberDeferredNormalReplyCharacters(replyCharacterIds)
    normalUploadingUserMessageIds.remove(messageId)
    if (normalUploadingUserMessageIds.isEmpty() && hasNormalUserMessagesAfterLastAssistant()) {
        scheduleNormalReplyAfterUserInterrupt()
    }
}

fun ChatViewModel.failUploadingUserMessage(messageId: String, reason: String) {
    if (messageId.isBlank()) return
    val label = reason.ifBlank { "图片上传失败，未发送" }
    markNormalUserMessageForRetry(messageId)
    _state.value = _state.value.copy(error = null, errorDebug = null)
    normalGenerationUserIds.remove(messageId)
    normalUploadingUserMessageIds.remove(messageId)
    DebugLog.w(TAG, "Pending image message failed: $label")
    if (normalUploadingUserMessageIds.isEmpty() && hasNormalUserMessagesAfterLastAssistant()) {
        // 失败图片仍保留在消息中，等待用户点击左下角警示后重传，不能自动发出残缺内容。
        normalGenerationStarted = false
    }
}

internal fun ChatViewModel.appendUserStickerMessage(sticker: StickerAsset): Message? {
    val quotedMessage = _state.value.quotedMessage
    val conversationId = ensureConversationId()
    val mid = UUID.randomUUID().toString()
    val attachment = sticker.toAttachment()
    val now = System.currentTimeMillis()
    val uiMsg = Message(
        id = mid,
        role = "user",
        content = "",
        messageId = mid,
        timestamp = now,
        quotedMessage = quotedMessage,
        attachments = listOf(attachment),
        isPendingServerAccept = true,
        pendingServerAcceptStartedAt = now
    )
    _state.value = _state.value.copy(
        conversationId = conversationId,
        messages = _state.value.messages + uiMsg,
        error = null,
        errorDebug = null,
        quotedMessage = null
    )
    sentMessages.add(
        ChatMessage(
            role = "user",
            content = "",
            messageId = mid,
            timestamp = uiMsg.timestamp,
            quotedMessage = quotedMessage,
            attachments = listOf(attachment)
        )
    )
    rememberUnconfirmedNormalUser(mid)
    return uiMsg
}

internal fun ChatViewModel.latestNormalUserMessagesForServer(): List<ChatMessage> {
    val app = androidApplication
    val lastAssistantIndex = sentMessages.indexOfLast {
        it.role == "assistant" && it.isHidden != true
    }
    val pendingUsers = sentMessages
        .drop(lastAssistantIndex + 1)
        .filter { it.role == "user" && it.isHidden != true }
    return (pendingUsers.ifEmpty {
        sentMessages.lastOrNull {
            it.role == "user" && it.isHidden != true
        }?.let { listOf(it) } ?: emptyList()
    }).mapForServerImages(app)
}

private fun ChatViewModel.hasNormalUserMessagesAfterLastAssistant(): Boolean {
    val lastAssistantIndex = sentMessages.indexOfLast {
        it.role == "assistant" && it.isHidden != true
    }
    return sentMessages
        .drop(lastAssistantIndex + 1)
        .any { it.role == "user" && it.isHidden != true }
}

internal fun ChatViewModel.latestUserMessageForServer(includeHidden: Boolean = false): List<ChatMessage> {
    val app = androidApplication
    return (sentMessages.lastOrNull {
        it.role == "user" && (includeHidden || it.isHidden != true)
    }?.let { listOf(it) } ?: emptyList()).mapForServerImages(app)
}

private fun List<ChatMessage>.mapForServerImages(app: Application): List<ChatMessage> {
    return map { msg ->
        val converted = replaceLocalChatImagesForServer(app, msg.content)
        if (converted == msg.content) msg else msg.copy(content = converted)
    }
}

internal fun ChatViewModel.runtimeMessagesForClientWithLocalImages(
    messages: List<ChatMessage>,
    speakerFallbackMessages: List<ChatMessage> = emptyList()
): List<ChatMessage> {
    val app = androidApplication
    return runtimeMessagesForClient(messages, speakerFallbackMessages).map { msg ->
        val restored = restoreRemoteChatImagesForDisplay(app, msg.content)
        if (restored == msg.content) msg else msg.copy(content = restored)
    }
}

internal fun ChatViewModel.pendingNormalLocalUserKeys(): Set<String> {
    if (_state.value.mode != "normal") return emptySet()
    val unresolvedUiUserKeys = _state.value.messages
        .filter { it.isUser() && it.sequenceNumber == null && it.isPendingServerAccept }
        .map { uiMessageKey(it) }
    return (
        unresolvedUiUserKeys +
            unconfirmedNormalUserKeys +
            normalGenerationUserIds +
            normalUploadingUserMessageIds
        )
        .filter { it.isNotBlank() }
        .toSet()
}

internal fun ChatViewModel.rememberUnconfirmedNormalUser(messageId: String?) {
    val key = messageId?.takeIf { it.isNotBlank() } ?: return
    if (_state.value.mode != "normal") return
    unconfirmedNormalUserKeys.add(key)
}

internal fun ChatViewModel.markNormalUsersAcceptedByServer(
    messageIds: Collection<String> = normalGenerationUserIds.toList(),
    acceptAllPendingOnServerSignal: Boolean = false,
) {
    val currentState = _state.value
    val explicitAcceptedKeys = messageIds
        .asSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .toSet()
    val pendingUiKeys = if (acceptAllPendingOnServerSignal) {
        currentState.messages
            .asSequence()
            .filter { it.isUser() && it.isPendingServerAccept }
            .map { uiMessageKey(it) }
            .filter { it.isNotBlank() && !it.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) }
            .toSet()
    } else {
        emptySet()
    }
    val acceptedKeys = explicitAcceptedKeys + pendingUiKeys
    if (acceptedKeys.isEmpty() && !acceptAllPendingOnServerSignal) return

    acceptedKeys.forEach { unconfirmedNormalUserKeys.remove(it) }
    if (acceptAllPendingOnServerSignal) {
        unconfirmedNormalUserKeys.removeAll { key -> !key.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) }
        normalGenerationUserIds.clear()
    } else {
        normalGenerationUserIds.removeAll(acceptedKeys)
    }

    var changed = false
    val nextMessages = currentState.messages.map { msg ->
        val key = uiMessageKey(msg)
        if (
            msg.isUser() &&
            msg.isPendingServerAccept &&
            !(acceptAllPendingOnServerSignal && key.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX)) &&
            (
                acceptAllPendingOnServerSignal ||
                    key in acceptedKeys ||
                    msg.id in acceptedKeys ||
                    msg.messageId in acceptedKeys
                )
        ) {
            changed = true
            msg.copy(
                isPendingServerAccept = false,
                pendingServerAcceptStartedAt = 0L
            )
        } else {
            msg
        }
    }
    if (changed) {
        _state.value = currentState.copy(messages = nextMessages)
    }
}

internal fun ChatViewModel.markAllPendingUserMessagesAcceptedForDebug() {
    val pendingKeys = _state.value.messages
        .asSequence()
        .filter { it.isUser() && it.isPendingServerAccept }
        .map { uiMessageKey(it) }
        .toList()
    markNormalUsersAcceptedByServer(pendingKeys)
}

fun ChatViewModel.retryPendingNormalUserMessage(messageId: String) {
    if (_state.value.mode != "normal") return
    val currentState = _state.value
    val target = currentState.messages.firstOrNull { msg ->
        msg.isUser() &&
            msg.isPendingServerAccept &&
            (msg.id == messageId || msg.messageId == messageId || uiMessageKey(msg) == messageId)
    } ?: return
    val targetKey = uiMessageKey(target)
    if (targetKey.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX)) {
        resetDebugPendingUserAcceptMessage(targetKey)
        return
    }
    val runtimeMessage = sentMessages.lastOrNull { msg ->
        msg.role == "user" &&
            msg.isHidden != true &&
            (msg.messageId == target.id || msg.messageId == target.messageId || chatMessageKey(msg) == targetKey)
    } ?: normalUserRuntimeFromUi(target)

    cancelNormalGenerationForReschedule()
    val restartedAt = System.currentTimeMillis()
    rememberUnconfirmedNormalUser(targetKey)
    val nextMessages = _state.value.messages.map { msg ->
        if (msg.id == target.id || msg.messageId == target.messageId || uiMessageKey(msg) == targetKey) {
            msg.copy(
                isPendingServerAccept = true,
                pendingServerAcceptStartedAt = restartedAt,
                isError = false
            )
        } else {
            msg
        }
    }
    _state.value = _state.value.copy(
        messages = nextMessages,
        error = null,
        errorDebug = null
    )
    if (sentMessages.none { chatMessageKey(it) == chatMessageKey(runtimeMessage) }) {
        sentMessages.add(runtimeMessage)
    }
    val imageUrls = chatImageUrlsInContent(runtimeMessage.content)
    val needsImageUpload = imageUrls.any(::chatImageNeedsUpload)
    if (!needsImageUpload) {
        startNormalReplyGeneration(requestMessagesOverride = listOf(runtimeMessage))
        return
    }
    viewModelScope.launch {
        val uploaded = uploadPendingChatImages(
            context = androidApplication,
            viewModel = this@retryPendingNormalUserMessage,
            imageUrls = imageUrls,
            showErrors = false,
            showPrompt = {},
        )
        if (uploaded == null) {
            markNormalUserMessageForRetry(targetKey)
            _state.value = _state.value.copy(isStreaming = false, error = null, errorDebug = null)
            DebugLog.w(TAG, "Retry pending image message upload failed: $targetKey")
            return@launch
        }
        startNormalReplyGeneration(requestMessagesOverride = listOf(runtimeMessage))
    }
}

private fun ChatViewModel.resetDebugPendingUserAcceptMessage(messageKey: String) {
    val restartedAt = System.currentTimeMillis()
    sentMessages.removeAll { it.messageId == messageKey }
    unconfirmedNormalUserKeys.remove(messageKey)
    val nextMessages = _state.value.messages.map { msg ->
        if (msg.isUser() && uiMessageKey(msg) == messageKey) {
            msg.copy(
                isPendingServerAccept = true,
                pendingServerAcceptStartedAt = restartedAt,
                isError = false
            )
        } else {
            msg
        }
    }
    _state.value = _state.value.copy(messages = nextMessages, error = null, errorDebug = null)
    _snackbarMessages.tryEmit("已本地模拟重新发送")
}

private fun ChatViewModel.forgetConfirmedNormalUserKeys(serverKeys: Set<String>) {
    if (serverKeys.isEmpty()) return
    serverKeys.forEach { unconfirmedNormalUserKeys.remove(it) }
}

private fun ChatViewModel.normalUserRuntimeFromUi(message: Message): ChatMessage {
    return ChatMessage(
        role = "user",
        content = message.content,
        messageId = message.messageId?.takeIf { it.isNotBlank() } ?: message.id,
        sequenceNumber = message.sequenceNumber,
        timestamp = message.timestamp,
        quotedMessage = message.quotedMessage,
        attachments = message.attachments.takeIf { it.isNotEmpty() }
    )
}

internal fun ChatViewModel.mergePendingNormalLocalUsers(
    serverUiMessages: List<Message>,
    localUiMessages: List<Message> = _state.value.messages,
): List<Message> {
    val pendingKeys = pendingNormalLocalUserKeys()
    if (pendingKeys.isEmpty()) return serverUiMessages
    val serverKeys = serverUiMessages.map { uiMessageKey(it) }.toSet()
    forgetConfirmedNormalUserKeys(serverKeys)
    val pendingLocalUsers = localUiMessages.filter { msg ->
        val key = uiMessageKey(msg)
        msg.isUser() &&
            msg.sequenceNumber == null &&
            key in pendingKeys &&
            key !in serverKeys
    }
    if (pendingLocalUsers.isEmpty()) return serverUiMessages
    return orderedUiMessages(serverUiMessages + pendingLocalUsers)
}

internal fun ChatViewModel.mergePendingNormalRuntimeUsers(
    serverRuntimeMessages: List<ChatMessage>,
    localUiMessages: List<Message> = _state.value.messages,
): List<ChatMessage> {
    val pendingKeys = pendingNormalLocalUserKeys()
    if (pendingKeys.isEmpty()) return serverRuntimeMessages
    val serverKeys = serverRuntimeMessages.map { chatMessageKey(it) }.toSet()
    forgetConfirmedNormalUserKeys(serverKeys)
    val pendingRuntimeUsers = sentMessages.filter { msg ->
        val key = chatMessageKey(msg)
        msg.role == "user" &&
            msg.isHidden != true &&
            msg.sequenceNumber == null &&
            !key.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) &&
            key in pendingKeys &&
            key !in serverKeys
    }
    val runtimeKeys = (serverKeys + pendingRuntimeUsers.map { chatMessageKey(it) }).toSet()
    val pendingRuntimeUsersFromUi = localUiMessages.mapNotNull { msg ->
        val key = uiMessageKey(msg)
        if (
            msg.isUser() &&
            msg.sequenceNumber == null &&
            !key.startsWith(DEBUG_PENDING_USER_ACCEPT_PREFIX) &&
            key in pendingKeys &&
            key !in runtimeKeys
        ) {
            normalUserRuntimeFromUi(msg)
        } else {
            null
        }
    }
    if (pendingRuntimeUsers.isEmpty() && pendingRuntimeUsersFromUi.isEmpty()) return serverRuntimeMessages
    return orderedChatMessages(serverRuntimeMessages + pendingRuntimeUsers + pendingRuntimeUsersFromUi)
}

internal fun ChatViewModel.cancelNormalGenerationForReschedule() {
    streamJob?.cancel()
    streamJob = null
    normalAcceptedRecoveryJob?.cancel()
    normalAcceptedRecoveryJob = null
    replyRecoveryPollJob?.cancel()
    replyRecoveryPollJob = null
    stopReplyTimer()
    normalGenerationStarted = false
    normalAssistantVisible = false
    lastNormalGenerationStartedAtMs = 0L
    lastNormalGenerationStartSeq = null
    normalGenerationUserIds.clear()
    currentJobId = null
    _state.value = _state.value.copy(isStreaming = false)
}

private fun ChatViewModel.rememberDeferredNormalReplyCharacters(replyCharacterIds: List<String>) {
    replyCharacterIds
        .asSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .forEach { deferredNormalReplyCharacterIds.add(it) }
}

private fun ChatViewModel.consumeNormalReplyCharacters(replyCharacterIds: List<String>): List<String> {
    rememberDeferredNormalReplyCharacters(replyCharacterIds)
    val result = deferredNormalReplyCharacterIds.toList()
    deferredNormalReplyCharacterIds.clear()
    return result
}

internal fun ChatViewModel.scheduleNormalReply(replyCharacterIds: List<String> = emptyList()) {
    if (_state.value.mode != "normal") return
    if (normalUploadingUserMessageIds.isNotEmpty()) {
        rememberDeferredNormalReplyCharacters(replyCharacterIds)
        return
    }
    val effectiveReplyCharacterIds = consumeNormalReplyCharacters(replyCharacterIds)
    if (normalGenerationStarted || _state.value.isStreaming) {
        cancelNormalGenerationForReschedule()
    }
    startNormalReplyGeneration(replyCharacterIds = effectiveReplyCharacterIds)
}

internal fun ChatViewModel.scheduleNormalReplyAfterUserInterrupt(replyCharacterIds: List<String> = emptyList()) {
    if (_state.value.mode != "normal") return
    if (normalUploadingUserMessageIds.isNotEmpty()) {
        rememberDeferredNormalReplyCharacters(replyCharacterIds)
        return
    }
    val effectiveReplyCharacterIds = consumeNormalReplyCharacters(replyCharacterIds)
    viewModelScope.launch {
        cancelProactiveGenerationForUserMessage()
        if (_state.value.mode == "normal") {
            scheduleNormalReply(effectiveReplyCharacterIds)
        }
    }
}

internal fun ChatViewModel.interruptProactiveGenerationForUserMessage() {
    if (_state.value.mode != "normal") return
    viewModelScope.launch {
        cancelProactiveGenerationForUserMessage()
    }
}

private suspend fun ChatViewModel.cancelProactiveGenerationForUserMessage() {
    val snapshot = _state.value
    val characterId = snapshot.character?.id?.takeIf { it.isNotBlank() } ?: return
    val result = chatRepo.cancelGeneration(
        username = prefs.username,
        characterId = characterId,
        conversationId = snapshot.conversationId,
        clientId = clientId,
        jobId = null,
        reason = "normal_user_interrupt_proactive",
    )
    result.onFailure { e ->
        DebugLog.w(TAG, "Interrupt proactive generation failed before normal reply: ${e.message}", e)
    }
}

internal fun ChatViewModel.onNormalReplyRoundFinished() {
    normalTransportRetryJob?.cancel()
    normalTransportRetryJob = null
    normalAcceptedRecoveryJob?.cancel()
    normalAcceptedRecoveryJob = null
    normalGenerationStarted = false
    normalAssistantVisible = false
    lastNormalGenerationStartedAtMs = 0L
    lastNormalGenerationStartSeq = null
    normalGenerationUserIds.clear()
    currentJobId = null
}

internal fun ChatViewModel.recoverNormalSendState(
    reason: String,
    markOptimisticMessagesForRetry: Boolean = false,
    cancelRecoveryJobs: Boolean = true,
) {
    if (_state.value.mode != "normal") return
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val conversationId = _state.value.conversationId
    val jobId = currentJobId
    DebugLog.w(
        TAG,
        "Normal send recovery reason=$reason characterId=${characterId.take(12)} jobId=${jobId ?: "null"}"
    )
    streamJob?.cancel()
    streamJob = null
    if (markOptimisticMessagesForRetry) {
        markPendingNormalUserMessagesForRetry()
    }
    stopReplyTimer()
    resetNormalSendState(
        cancelRecoveryJobs = cancelRecoveryJobs,
        clearUnconfirmedUsers = false,
    )
    viewModelScope.launch {
        chatRepo.cancelGeneration(
            username = prefs.username,
            characterId = characterId,
            conversationId = conversationId,
            clientId = clientId,
            jobId = jobId,
            reason = "normal_send_recovery:$reason",
        )
    }
}

private fun ChatViewModel.markNormalUserMessageForRetry(messageId: String): Boolean {
    val failedAt = System.currentTimeMillis() - 10_001L
    var found = false
    val nextMessages = _state.value.messages.map { message ->
        if (
            message.isUser() &&
            (message.id == messageId || message.messageId == messageId || uiMessageKey(message) == messageId)
        ) {
            found = true
            message.copy(
                isPendingServerAccept = true,
                pendingServerAcceptStartedAt = failedAt,
            )
        } else {
            message
        }
    }
    if (sentMessages.any { it.role == "user" && it.messageId == messageId }) found = true
    if (found) {
        rememberUnconfirmedNormalUser(messageId)
        _state.value = _state.value.copy(messages = nextMessages)
    }
    return found
}

internal fun ChatViewModel.markPendingNormalUserMessagesForRetry(): Boolean {
    var marked = false
    for (id in normalGenerationUserIds.toList()) {
        if (_state.value.messages.any { it.id == id || it.messageId == id } ||
            sentMessages.any { it.messageId == id && it.role == "user" }
        ) {
            marked = true
        }
        markNormalUserMessageForRetry(id)
        normalUploadingUserMessageIds.remove(id)
    }
    normalGenerationUserIds.clear()
    normalGenerationStarted = false
    return marked
}

internal fun ChatViewModel.startNormalReplyGeneration(
    retryAttempt: Int = 0,
    replyCharacterIds: List<String> = emptyList(),
    requestMessagesOverride: List<ChatMessage>? = null,
) {
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    if (_state.value.mode != "normal") return
    if (sentMessages.none { it.role == "user" }) return
    val requestedReplyCharacterIds = replyCharacterIds
        .asSequence()
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .toList()
    val requestedReplyCharacterId = requestedReplyCharacterIds.firstOrNull()
    DebugLog.d(
        TAG,
        "Normal reply speakers main=${characterId.take(12)} requested=${requestedReplyCharacterIds.map { it.take(12) }}"
    )

    val conversationId = ensureConversationId()
    val requestMessages = requestMessagesOverride?.mapForServerImages(androidApplication)
        ?: latestNormalUserMessagesForServer()
    if (requestMessages.isEmpty()) return
    normalTransportRetryJob?.cancel()
    normalTransportRetryJob = null
    normalGenerationUserIds.clear()
    normalGenerationUserIds.addAll(requestMessages.mapNotNull { it.messageId })
    normalGenerationUserIds.forEach { rememberUnconfirmedNormalUser(it) }
    val recoveryStartSeq = _state.value.messages.mapNotNull { it.sequenceNumber }.maxOrNull()
    val recoveryStartedAt = System.currentTimeMillis()
    normalGenerationStarted = true
    normalAssistantVisible = false
    lastNormalGenerationStartedAtMs = recoveryStartedAt
    lastNormalGenerationStartSeq = recoveryStartSeq
    val request = ChatRequest(
        username = prefs.username,
        characterId = characterId,
        messages = requestMessages,
        mode = "normal",
        normalEngine = prefs.normalEngine,
        conversationId = conversationId,
        clientId = clientId,
        memoryEnabled = prefs.memoryEnabled,
        crisisHotlineEnabled = prefs.crisisHotlineEnabled,
        clientContext = ClientContextHelper.buildContext(getApplication()),
        replyCharacterId = requestedReplyCharacterId,
        replyCharacterIds = requestedReplyCharacterIds.takeIf { it.isNotEmpty() }
    )

    _state.value = _state.value.copy(isStreaming = true, error = null, errorDebug = null)
    startReplyTimer()
    streamJob?.cancel()
    streamJob = viewModelScope.launch {
        var accumulatedContent = ""
        var serverAssistantMessageId: String? = null
        var serverAssistantMessageIds: List<String> = emptyList()
        var receivedNormalParagraphCount = 0
        var lastNormalParagraphId: String? = null
        var acceptedByServer = false
        var failureHandled = false
        var doneReceived = false
        var cancelledByServer = false
        var noReplyReceived = false

        fun handleNormalStreamFailure(err: Throwable, source: String) {
            if (failureHandled) return
            failureHandled = true
            DebugLog.e(TAG, "Normal stream $source error: ${err.message}", err)
            if (acceptedByServer) {
                startReplyRecoveryPolling("stream_error", "normal", recoveryStartSeq, recoveryStartedAt)
            } else if (retryAttempt < 5) {
                scheduleNormalTransportRetry(
                    "stream_${source}",
                    retryAttempt,
                    recoveryStartSeq,
                    recoveryStartedAt,
                    requestedReplyCharacterIds,
                    requestMessages
                )
            } else {
                val markedForRetry = markPendingNormalUserMessagesForRetry()
                val parsed = parseErrorForDisplay(err.message)
                _state.value = _state.value.copy(
                    isStreaming = false,
                    error = if (markedForRetry) null else parsed.first,
                    errorDebug = if (markedForRetry) null else parsed.second
                )
                stopReplyTimer()
                onNormalReplyRoundFinished()
            }
        }

        try {
            chatRepo.sendMessage(request)
                .catch { err -> handleNormalStreamFailure(err, "upstream") }
                .collect { delta ->
                when (delta) {
                    is ChatDelta.Accepted -> {
                        acceptedByServer = true
                        delta.jobId?.let { currentJobId = it }
                        _state.value = _state.value.copy(
                            quotaExceeded = false,
                            quotaExceededMessage = "",
                        )
                        markNormalUsersAcceptedByServer(
                            messageIds = normalGenerationUserIds + listOfNotNull(delta.clientMessageId),
                            acceptAllPendingOnServerSignal = true,
                        )
                        if (!delta.implicit) persistAcceptedUserRound(characterId, "normal")
                    }
                    is ChatDelta.ServerAssistantId -> {
                        serverAssistantMessageId = delta.messageId
                    }
                    is ChatDelta.ServerAssistantIds -> {
                        serverAssistantMessageIds = delta.messageIds
                        serverAssistantMessageId = delta.messageIds.lastOrNull()
                    }
                    is ChatDelta.AssistantParagraph -> {
                        stopNormalRecoveryAfterAssistantArrived()
                        markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        normalAssistantVisible = true
                        val paraId = delta.id ?: UUID.randomUUID().toString()
                        val isFirstPara = receivedNormalParagraphCount == 0
                        upsertRealtimeAssistantParagraph(delta, paraId, isFirstPara, characterId)
                        receivedNormalParagraphCount++
                        lastNormalParagraphId = paraId
                    }
                    is ChatDelta.AssistantAsset -> {
                        stopNormalRecoveryAfterAssistantArrived()
                        markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        normalAssistantVisible = true
                        val assetId = delta.messageId ?: UUID.randomUUID().toString()
                        val newMsg = Message(
                            id = assetId,
                            role = "assistant",
                            content = "",
                            timestamp = delta.timestamp ?: System.currentTimeMillis(),
                            isStreaming = false,
                            messageId = assetId,
                            sequenceNumber = delta.sequenceNumber,
                            attachments = listOf(delta.attachment),
                            speakerCharacterId = delta.speakerCharacterId,
                            speakerName = delta.speakerName,
                            speakerAvatar = delta.speakerAvatar,
                            autoScrollBatchIndex = delta.index,
                            autoScrollBatchTotal = delta.total,
                            allowRealtimeAnimation = !delta.displayOverdue
                        )
                        upsertRealtimeAssistantMessage(
                            newMsg,
                            ChatMessage(
                                role = "assistant",
                                content = "",
                                messageId = assetId,
                                timestamp = newMsg.timestamp,
                                sequenceNumber = delta.sequenceNumber,
                                attachments = listOf(delta.attachment),
                                speakerCharacterId = delta.speakerCharacterId,
                                speakerName = delta.speakerName,
                                speakerAvatar = delta.speakerAvatar
                            )
                        )
                        lastNormalParagraphId = assetId
                    }
                    is ChatDelta.Token -> {
                        markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        accumulatedContent += delta.text
                    }
                    is ChatDelta.Cancelled -> {
                        cancelledByServer = true
                        doneReceived = true
                        normalAcceptedRecoveryJob?.cancel()
                        normalAcceptedRecoveryJob = null
                        replyRecoveryPollJob?.cancel()
                        replyRecoveryPollJob = null
                        currentJobId = null
                        _state.value = _state.value.copy(isStreaming = false)
                        stopReplyTimer()
                        onNormalReplyRoundFinished()
                    }
                    is ChatDelta.NoReply -> {
                        noReplyReceived = true
                        doneReceived = true
                        normalAcceptedRecoveryJob?.cancel()
                        normalAcceptedRecoveryJob = null
                        replyRecoveryPollJob?.cancel()
                        replyRecoveryPollJob = null
                        currentJobId = null
                        _state.value = _state.value.copy(isStreaming = false)
                        stopReplyTimer()
                        onNormalReplyRoundFinished()
                        triggerAutoSave(character, saveIntent = "user_edit")
                    }
                    is ChatDelta.Done -> {
                        if (cancelledByServer || noReplyReceived) {
                            currentJobId = delta.jobId
                            return@collect
                        }
                        doneReceived = true
                        normalGenerationUserIds.clear()
                        replyRecoveryPollJob?.cancel()
                        replyRecoveryPollJob = null
                        currentJobId = delta.jobId
                        if (receivedNormalParagraphCount > 0) {
                            _state.value = _state.value.copy(isStreaming = false)
                        } else {
                            insertFinalNormalModeMessages(accumulatedContent, serverAssistantMessageIds)
                        }
                        val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                            ?: System.currentTimeMillis()
                        prefs.setModeLastChatTime(characterId, "normal", immediateMsgTs)
                        stopReplyTimer()
                        emitForegroundChatCompleted(
                            characterId,
                            "normal",
                            immediateMsgTs,
                            lastNormalParagraphId
                                ?: serverAssistantMessageId
                                ?: sentMessages.lastOrNull { it.role == "assistant" }?.messageId,
                            messageCount = serverAssistantMessageIds.size.takeIf { it > 0 }
                                ?: receivedNormalParagraphCount.takeIf { it > 0 }
                                ?: 1,
                        )
                        triggerAutoSave(character)
                        onNormalReplyRoundFinished()
                    }
                    is ChatDelta.Error -> {
                        failureHandled = true
                        doneReceived = true
                        val parsed = parseErrorForDisplay(delta.message)
                        val markedForRetry = if (!acceptedByServer) {
                            markPendingNormalUserMessagesForRetry()
                        } else {
                            false
                        }
                        _state.value = _state.value.copy(
                            isStreaming = false,
                            error = if (markedForRetry) null else parsed.first,
                            errorDebug = if (markedForRetry) null else parsed.second
                        )
                        incrementRetryCount()
                        stopReplyTimer()
                        onNormalReplyRoundFinished()
                    }
                    is ChatDelta.QuotaExceeded -> {
                        noReplyReceived = true
                        doneReceived = true
                        val markedForRetry = if (!acceptedByServer) {
                            markPendingNormalUserMessagesForRetry()
                        } else {
                            false
                        }
                        _state.value = _state.value.copy(
                            isStreaming = false,
                            error = null,
                            quotaExceeded = !markedForRetry,
                            quotaExceededMessage = if (markedForRetry) "" else delta.message
                        )
                        stopReplyTimer()
                        onNormalReplyRoundFinished()
                        if (!markedForRetry) {
                            triggerAutoSave(character, saveIntent = "user_edit")
                        }
                    }
                    is ChatDelta.Usage -> {
                        _state.value = _state.value.copy(
                            contextUsedTokens = delta.totalTokens,
                            contextLimitTokens = delta.limitTokens
                        )
                        checkAndAutoSummarize()
                    }
                    is ChatDelta.CrisisTriggered -> {
                        if (prefs.crisisHotlineEnabled) _showCrisisHotlineDialog.value = true
                    }
                    else -> Unit
                }
            }
            if (!failureHandled && !doneReceived) {
                DebugLog.w(
                    TAG,
                    "Normal stream completed without done; accepted=$acceptedByServer paragraphs=$receivedNormalParagraphCount"
                )
                if (!acceptedByServer && receivedNormalParagraphCount <= 0) {
                    scheduleNormalTransportRetry(
                        "completed_without_accept",
                        retryAttempt,
                        recoveryStartSeq,
                        recoveryStartedAt,
                        requestedReplyCharacterIds,
                        requestMessages
                    )
                    return@launch
                }
                startReplyRecoveryPolling("completed_without_done", "normal", recoveryStartSeq, recoveryStartedAt)
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (err: Throwable) {
            handleNormalStreamFailure(err, "collector")
        }
    }
}

internal fun ChatViewModel.scheduleNormalTransportRetry(
    reason: String,
    retryAttempt: Int,
    startSeq: Int?,
    startedAt: Long,
    replyCharacterIds: List<String> = emptyList(),
    requestMessagesOverride: List<ChatMessage>? = null,
) {
    if (_state.value.mode != "normal") return
    if (retryAttempt >= 5) {
        val markedForRetry = markPendingNormalUserMessagesForRetry()
        val parsed = parseErrorForDisplay("normal_stream_not_accepted")
        _state.value = _state.value.copy(
            isStreaming = false,
            galgameStreamingStep = null,
            error = if (markedForRetry) null else parsed.first,
            errorDebug = if (markedForRetry) null else parsed.second
        )
        stopReplyTimer()
        onNormalReplyRoundFinished()
        return
    }
    DebugLog.w(TAG, "Normal transport retry scheduled reason=$reason attempt=${retryAttempt + 1}")
    val retryUsername = prefs.username
    val retryCharacterId = _state.value.character?.id
    val retryConversationId = _state.value.conversationId
    normalTransportRetryJob?.cancel()
    normalTransportRetryJob = viewModelScope.launch {
        delay(5200L)
        if (_state.value.mode != "normal" || prefs.username != retryUsername ||
            _state.value.character?.id != retryCharacterId ||
            _state.value.conversationId != retryConversationId ||
            lastNormalGenerationStartedAtMs != startedAt) {
            DebugLog.d(TAG, "Normal transport retry skipped: scope or round changed")
            return@launch
        }
        if (!_state.value.isStreaming || normalAssistantArrivedAfter(startSeq, startedAt)) {
            DebugLog.d(TAG, "Normal transport retry skipped: streaming=${_state.value.isStreaming} replyArrived=${normalAssistantArrivedAfter(startSeq, startedAt)}")
            return@launch
        }
        DebugLog.d(TAG, "Normal transport retry executing attempt=${retryAttempt + 1}")
        normalTransportRetryJob = null
        startNormalReplyGeneration(retryAttempt + 1, replyCharacterIds, requestMessagesOverride)
    }
}

internal fun ChatViewModel.startReplyRecoveryPolling(
    reason: String,
    mode: String = _state.value.mode,
    startSeq: Int?,
    startedAt: Long,
    maxAttempts: Int = if (mode == "normal") 60 else 420,
) {
    if (mode != "normal" && mode != "galgame" && mode != "galgame_lock") return
    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val conversationId = _state.value.conversationId?.takeIf { it.isNotBlank() }
    val pendingGameUser = _state.value.messages.lastOrNull { it.isUser() }
    val gameUserId = pendingGameUser?.let { it.messageId ?: it.id }
    val gameUserTimestamp = pendingGameUser?.timestamp ?: startedAt
    val generationStartedAt = lastNormalGenerationStartedAtMs
    replyRecoveryPollJob?.cancel()
    replyRecoveryPollJob = viewModelScope.launch {
        var attempts = 0
        while ((mode == "normal" || attempts < maxAttempts) && _state.value.isStreaming &&
            (mode != "normal" || lastNormalGenerationStartedAtMs == generationStartedAt) && _state.value.mode == mode &&
            _state.value.character?.id == characterId &&
            (conversationId == null || _state.value.conversationId == conversationId)) {
            val recovered = when (mode) {
                "normal" -> normalAssistantArrivedAfter(startSeq, startedAt)
                "galgame", "galgame_lock" -> hasRecoveredGameReply(
                    _state.value.messages, gameUserId, gameUserTimestamp)
                else -> false
            }
            if (recovered) {
                if (mode == "normal") {
                    markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                    markNormalReplySucceeded("reply_recovery:$reason")
                }
                _state.value = _state.value.copy(
                    isStreaming = false,
                    galgameStreamingStep = null,
                    error = null,
                    errorDebug = null
                )
                stopReplyTimer()
                if (mode == "normal") onNormalReplyRoundFinished()
                triggerAutoSave(character)
                replyRecoveryPollJob = null
                return@launch
            }
            if (attempts % 5 == 0) {
                SyncWebSocketManager.pullUndeliveredOnce(prefs, "${mode}_recovery_$reason")
            }
            if (!_state.value.isBackgroundRefreshing) {
                if (mode == "normal") {
                    refreshNewMessagesFromServer(allowWhileStreaming = true, includeRecent = true)
                } else {
                    refreshConversationFromServer(allowWhileStreaming = true)
                }
            }
            delay(if (attempts == 0) 700L else 1500L)
            attempts++
        }
        replyRecoveryPollJob = null
    }
}

internal fun ChatViewModel.stopNormalRecoveryAfterAssistantArrived() {
    normalAcceptedRecoveryJob?.cancel()
    normalAcceptedRecoveryJob = null
    replyRecoveryPollJob?.cancel()
    replyRecoveryPollJob = null
}

internal fun ChatViewModel.normalAssistantArrivedAfter(startSeq: Int?, startedAt: Long): Boolean {
    val lowerBound = startedAt - 1500L
    val lastUserTimestamp = _state.value.messages.lastOrNull { it.isUser() }?.timestamp ?: 0L
    return _state.value.messages.any { message ->
        message.isAssistant() &&
            !message.isStreaming &&
            when {
                startSeq != null && message.sequenceNumber != null -> message.sequenceNumber > startSeq
                lastUserTimestamp > 0L -> message.timestamp >= lastUserTimestamp - 1500L
                else -> message.timestamp >= lowerBound
            }
    }
}

fun ChatViewModel.sendSticker(sticker: StickerAsset) {
    if (_state.value.character == null) return
    if (_state.value.mode != "normal") return
    clearFailedChatRoundIfNeeded()
    startUsageTracking()
    appendUserStickerMessage(sticker) ?: return
    scheduleNormalReplyAfterUserInterrupt()
}

internal fun ChatViewModel.newConversationId(): String {
    return "conv_${System.currentTimeMillis()}_${UUID.randomUUID().toString().take(8)}"
}

/**
 * 前台完成：驱动列表排序与未读；[correlationId] 需与 WebSocket/HTTP 的 `message_id` 一致以便 [ChatEventBus] 去重。
 */
internal fun ChatViewModel.emitForegroundChatCompleted(
    characterId: String,
    mode: String,
    timestamp: Long,
    correlationId: String?,
    messageCount: Int = 1,
) {
    val snapshot = sentMessages.toList()
    if (snapshot.isNotEmpty()) {
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
    }
    if (
        (mode == "galgame" || mode == "galgame_lock") &&
        ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
    ) {
        MessageVibrationHelper.vibrateForMessage(getApplication(), prefs)
    }
    ChatEventBus.notifyCompleted(
        characterId,
        mode,
        timestamp,
        ChatCompletionSource.FOREGROUND,
        correlationId,
        messageCount = messageCount,
    )
}
