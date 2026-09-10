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
suspend fun ChatViewModel.uploadChatImageForMessage(jpegBytes: ByteArray): Result<String> {
    return chatRepo.uploadChatImage(jpegBytes)
}

fun ChatViewModel.sendMessage(
    retryRequest: ChatRequest? = null,
    retryAttempt: Int = 0,
    replyCharacterId: String? = null,
    replyCharacterIds: List<String> = emptyList(),
) {
    val text = _state.value.inputText.trim()
    val currentMode = retryRequest?.mode ?: _state.value.mode
    if (currentMode == "normal") {
        if (text.isBlank()) return
        clearFailedChatRoundIfNeeded()
        startUsageTracking()
        if (appendUserTextMessage(text) != null) {
            val orderedReplyCharacterIds = buildList {
                replyCharacterIds
                    .map { it.trim() }
                    .filter { it.isNotBlank() }
                    .forEach { if (it !in this) add(it) }
                replyCharacterId
                    ?.trim()
                    ?.takeIf { it.isNotBlank() && it !in this }
                    ?.let { add(it) }
            }
            scheduleNormalReplyAfterUserInterrupt(orderedReplyCharacterIds)
        }
        return
    }

    val isRetry = retryRequest != null
    if (!isRetry && (text.isBlank() || _state.value.isStreaming)) return
    if (isRetry && _state.value.mode != currentMode) return
    if (!isRetry) {
        clearFailedChatRoundIfNeeded()
        startUsageTracking()
    }

    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: run {
        _state.value = _state.value.copy(error = "角色数据异常：缺少角色 ID")
        return
    }
    val username = prefs.username
    val quotedMessage = null
    val recoveryStartedAt = System.currentTimeMillis()

    val userMsg = Message(
        id = UUID.randomUUID().toString(),
        role = "user",
        content = text,
        timestamp = System.currentTimeMillis(),
        quotedMessage = quotedMessage
    )

    // galgame 模式：保持原有行为，需要占位消息配合流式步骤显示
    val assistantMsg = Message(
        id = UUID.randomUUID().toString(),
        role = "assistant",
        content = "",
        timestamp = System.currentTimeMillis(),
        isStreaming = true
    )
    if (!isRetry) {
        val newMessages = _state.value.messages + userMsg + assistantMsg

        _state.value = _state.value.copy(
            messages = newMessages,
            inputText = "",
            isStreaming = true,
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
    } else {
        val msgs = _state.value.messages.toMutableList()
        val assistantIdx = msgs.indexOfLast { it.isAssistant() }
        if (assistantIdx >= 0) {
            msgs[assistantIdx] = msgs[assistantIdx].copy(
                content = "",
                isStreaming = true,
                isError = false
            )
        }
        _state.value = _state.value.copy(
            messages = msgs,
            isStreaming = true,
            error = null,
            errorDebug = null,
            galgameStreamingStep = null
        )
    }

    val request = retryRequest ?: ChatRequest(
        username = username,
        characterId = characterId,
        messages = latestUserMessageForServer(includeHidden = false),
        mode = currentMode,
        conversationId = _state.value.conversationId,
        clientId = clientId,
        memoryEnabled = prefs.memoryEnabled,
        crisisHotlineEnabled = prefs.crisisHotlineEnabled,
        clientContext = null
    )

    if (!isRetry) {
        // 开始回复计时器
        startReplyTimer()
    }

    streamJob?.cancel()
    streamJob = viewModelScope.launch {
        var accumulatedContent = ""
        var lastUiUpdateAt = 0L
        var galgameStreamResultReceived = false
        var serverAssistantMessageId: String? = null
        var serverAssistantMessageIds: List<String> = emptyList()
        var receivedNormalParagraphCount = 0
        var lastNormalParagraphId: String? = null
        var acceptedByServer = false
        val isNormalMode = false

        chatRepo.sendMessage(request)
            .catch { err ->
                DebugLog.e(TAG, "Stream error: ${err.message}", err)
                if (isNormalMode && acceptedByServer) {
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = null,
                        errorDebug = null
                    )
                } else if (isNormalMode) {
                    // normal 模式无占位消息：直接显示错误状态，不插入错误消息
                    removeUnacceptedUserMessage(userMsg.id)
                    val parsed = parseErrorForDisplay(err.message)
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = parsed.first,
                        errorDebug = parsed.second
                    )
                } else if (!isNormalMode && acceptedByServer) {
                    startReplyRecoveryPolling("stream_error", currentMode, null, recoveryStartedAt)
                } else if (!isNormalMode && retryAttempt < 5) {
                    DebugLog.w(TAG, "Galgame transport retry scheduled attempt=${retryAttempt + 1}: ${err.message}")
                    incrementRetryCount()
                    viewModelScope.launch {
                        delay(5200L)
                        if (_state.value.mode == currentMode && _state.value.isStreaming) {
                            sendMessage(request, retryAttempt + 1)
                        }
                    }
                } else {
                    updateLastAssistantMessage(accumulatedContent, isError = true)
                    val parsed = parseErrorForDisplay(err.message)
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = parsed.first,
                        errorDebug = parsed.second
                    )
                }
                if (acceptedByServer || retryAttempt >= 5) {
                    stopReplyTimer()
                }
            }
            .collect { delta ->
                when (delta) {
                    is ChatDelta.Accepted -> {
                        acceptedByServer = true
                        delta.jobId?.let { currentJobId = it }
                        if (currentMode == "normal") {
                            _state.value = _state.value.copy(
                                quotaExceeded = false,
                                quotaExceededMessage = "",
                            )
                            markNormalUsersAcceptedByServer(
                                messageIds = listOfNotNull(delta.clientMessageId),
                                acceptAllPendingOnServerSignal = true,
                            )
                        }
                        if (!delta.implicit) {
                            persistAcceptedUserRound(characterId, currentMode)
                            if (currentMode != "normal") {
                                startReplyRecoveryPolling("accepted", currentMode, null, recoveryStartedAt)
                            }
                        }
                    }
                    is ChatDelta.ServerAssistantId -> {
                        serverAssistantMessageId = delta.messageId
                    }
                    is ChatDelta.ServerAssistantIds -> {
                        serverAssistantMessageIds = delta.messageIds
                        serverAssistantMessageId = delta.messageIds.lastOrNull()
                    }
                    is ChatDelta.GalgameStepProgress -> {
                        _state.value = _state.value.copy(galgameStreamingStep = delta.label)
                    }
                    is ChatDelta.GalgamePlan -> {
                        // 本段文案由 GalgameStepProgress / chunk / metadata / options 驱动
                    }
                    is ChatDelta.GalgameChunk -> {
                        _state.value = _state.value.copy(galgameStreamingStep = galgameChunkStepLabel(delta.field))
                    }
                    is ChatDelta.GalgameMetadata -> {
                        _state.value = _state.value.copy(galgameStreamingStep = "场景字段")
                        applyGalgameMetadataPreview(delta.payload)
                    }
                    is ChatDelta.GalgameOptions -> {
                        _state.value = _state.value.copy(galgameStreamingStep = "选项生成")
                    }
                    is ChatDelta.GalgameStreamResult -> {
                        applyGalgameSuccessFromResultMap(delta.galgameResult)
                        galgameStreamResultReceived = true
                    }
                    is ChatDelta.Cancelled -> {
                        if (currentMode == "normal") {
                            normalAcceptedRecoveryJob?.cancel()
                            normalAcceptedRecoveryJob = null
                            replyRecoveryPollJob?.cancel()
                            replyRecoveryPollJob = null
                            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
                            onNormalReplyRoundFinished()
                        } else {
                            removeGalgamePendingRoundSilently()
                        }
                        stopReplyTimer()
                        currentJobId = null
                    }
                    is ChatDelta.NoReply -> {
                        if (currentMode == "normal") {
                            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
                            stopReplyTimer()
                            onNormalReplyRoundFinished()
                        }
                    }
                    is ChatDelta.AssistantParagraph -> {
                        // normal SSE 路径：逐段插入，每次仅 +1 条消息，触发自动滚动
                        stopNormalRecoveryAfterAssistantArrived()
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
                        val paraId = delta.id ?: UUID.randomUUID().toString()
                        val isFirstPara = receivedNormalParagraphCount == 0
                        upsertRealtimeAssistantParagraph(delta, paraId, isFirstPara, characterId)
                        receivedNormalParagraphCount++
                        lastNormalParagraphId = paraId
                    }
                    is ChatDelta.AssistantAsset -> {
                        stopNormalRecoveryAfterAssistantArrived()
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
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
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
                        accumulatedContent += delta.text
                        if (!isNormalMode) {
                            // normal 模式无占位消息，不做逐 token UI 更新
                            // 节流 UI 刷新：80ms ≈ 12fps，对阅读速度无感，但将 Compose 重组频率
                            // 从 ~60fps 降至 12fps，大幅减少每字符触发的 requestLayout/重绘开销
                            val now = System.currentTimeMillis()
                            if (now - lastUiUpdateAt >= 80L) {
                                updateStreamingMessage(accumulatedContent)
                                lastUiUpdateAt = now
                            }
                        }
                    }
                    is ChatDelta.Done -> {
                        currentJobId = delta.jobId
                        // 用发送时捕获的 currentMode 而非当前状态，防止模式切换后旧流式响应串入新模式列表
                        val isGalgameMode = currentMode == "galgame" || currentMode == "galgame_lock"

                        if (isGalgameMode) {
                            if (!galgameStreamResultReceived) {
                                startReplyRecoveryPolling("done_without_result", currentMode, null, recoveryStartedAt)
                            }
                        } else if (isNormalMode) {
                            if (receivedNormalParagraphCount > 0) {
                                // SSE 路径：段落已逐条插入，只需收尾
                                _state.value = _state.value.copy(isStreaming = false)
                            } else {
                                // JSON 批量回退路径（旧服务端或降级场景）
                                insertFinalNormalModeMessages(accumulatedContent, serverAssistantMessageIds)
                            }
                            val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                                ?: System.currentTimeMillis()
                            prefs.setModeLastChatTime(characterId, currentMode, immediateMsgTs)
                            stopReplyTimer()
                            emitForegroundChatCompleted(
                                characterId,
                                currentMode,
                                immediateMsgTs,
                                lastNormalParagraphId
                                    ?: serverAssistantMessageId
                                    ?: sentMessages.lastOrNull { it.role == "assistant" }?.messageId,
                                messageCount = serverAssistantMessageIds.size.takeIf { it > 0 }
                                    ?: receivedNormalParagraphCount.takeIf { it > 0 }
                                    ?: 1,
                            )
                        } else {
                            finalizeAssistantMessage(accumulatedContent)
                            val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                                ?: System.currentTimeMillis()
                            prefs.setModeLastChatTime(characterId, currentMode, immediateMsgTs)
                            stopReplyTimer()
                            emitForegroundChatCompleted(
                                characterId,
                                currentMode,
                                immediateMsgTs,
                                serverAssistantMessageId
                                    ?: sentMessages.lastOrNull { it.role == "assistant" }?.messageId,
                            )
                        }

                        triggerAutoSave(character)
                    }
                    is ChatDelta.Error -> {
                        if (
                            !isNormalMode &&
                            !acceptedByServer &&
                            retryAttempt < 5 &&
                            isRetryableGalgameTransportError(delta.message)
                        ) {
                            DebugLog.w(TAG, "Galgame delta error retry scheduled attempt=${retryAttempt + 1}: ${delta.message}")
                            incrementRetryCount()
                            viewModelScope.launch {
                                delay(5200L)
                                if (_state.value.mode == currentMode && _state.value.isStreaming) {
                                    sendMessage(request, retryAttempt + 1)
                                }
                            }
                            return@collect
                        }
                        val parsed = parseErrorForDisplay(delta.message)
                        if (isNormalMode) {
                            // normal 模式无占位消息：只显示错误状态
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                galgameStreamingStep = null,
                                error = parsed.first,
                                errorDebug = parsed.second
                            )
                        } else {
                            updateLastAssistantMessage(
                                accumulatedContent.ifBlank { "⚠️ ${parsed.first}" },
                                isError = accumulatedContent.isBlank()
                            )
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                galgameStreamingStep = null,
                                error = if (accumulatedContent.isBlank()) parsed.first else null,
                                errorDebug = parsed.second
                            )
                        }
                        incrementRetryCount()
                    }
                    is ChatDelta.QuotaExceeded -> {
                        if (isNormalMode) {
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                error = null,
                                quotaExceeded = true,
                                quotaExceededMessage = delta.message
                            )
                        } else {
                            updateLastAssistantMessage(
                                accumulatedContent.ifBlank { "⚠️ ${delta.message}" },
                                isError = accumulatedContent.isBlank()
                            )
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                error = null,
                                quotaExceeded = true,
                                quotaExceededMessage = delta.message
                            )
                        }
                        stopReplyTimer()
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
                }
            }
        if (!isNormalMode && acceptedByServer && !galgameStreamResultReceived) {
            startReplyRecoveryPolling("completed_without_result", currentMode, null, recoveryStartedAt)
        }
    }
}

fun ChatViewModel.sendMessageAsGuest(replyCharacterId: String?) {
    sendMessage(replyCharacterId = replyCharacterId?.takeIf { it.isNotBlank() })
}

fun ChatViewModel.sendMessageAsGuest(replyCharacterIds: List<String>) {
    sendMessage(replyCharacterIds = replyCharacterIds)
}

private fun isRetryableGalgameTransportError(message: String): Boolean {
    val text = message.lowercase()
    return text.contains("网络请求失败") ||
        text.contains("检查网络") ||
        text.contains("debug_weak_network") ||
        text.contains("timeout") ||
        text.contains("failed to connect") ||
        text.contains("connection reset")
}

/**
 * 最后一条是用户消息时，直接触发 AI 生成，不重复添加用户消息。
 * 适用场景：显式的“重新生成/重试”入口；不要接到输入框空发送路径上。
 */
fun ChatViewModel.resendLastUserMessage() {
    if (_state.value.mode == "normal") {
        val lastMsg = _state.value.messages.lastOrNull()
        if (lastMsg == null || !lastMsg.isUser()) return
        startUsageTracking()
        _state.value = _state.value.copy(error = null, errorDebug = null)
        if (normalGenerationStarted || _state.value.isStreaming) {
            cancelNormalGenerationForReschedule()
        }
        startNormalReplyGeneration()
        return
    }

    if (_state.value.isStreaming) return
    val lastMsg = _state.value.messages.lastOrNull()
    if (lastMsg == null || !lastMsg.isUser()) return

    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: run {
        _state.value = _state.value.copy(error = "角色数据异常：缺少角色 ID")
        return
    }
    startUsageTracking()

    val username = prefs.username

    val currentMode = _state.value.mode
    val isNormalMode = currentMode == "normal"

    val nextMessages = if (isNormalMode) {
        // normal 模式与正常发送分支一致：不添加空助手占位，完整内容到达后一次性插入。
        _state.value.messages
    } else {
        val assistantMsg = Message(
            id = UUID.randomUUID().toString(),
            role = "assistant",
            content = "",
            timestamp = System.currentTimeMillis(),
            isStreaming = true
        )
        _state.value.messages + assistantMsg
    }

    _state.value = _state.value.copy(
        messages = nextMessages,
        isStreaming = true,
        error = null,
        errorDebug = null
    )

    // sentMessages 里已有该用户消息，直接用于构造请求
    val request = ChatRequest(
        username = username,
        characterId = characterId,
        messages = latestUserMessageForServer(includeHidden = false),
        mode = currentMode,
        conversationId = _state.value.conversationId,
        clientId = clientId,
        memoryEnabled = prefs.memoryEnabled,
        crisisHotlineEnabled = prefs.crisisHotlineEnabled,
        clientContext = if (currentMode == "normal") ClientContextHelper.buildContext(getApplication()) else null
    )

    startReplyTimer()

    streamJob?.cancel()
    streamJob = viewModelScope.launch {
        var accumulatedContent = ""
        var lastUiUpdateAt = 0L
        var galgameStreamResultReceived = false
        var serverAssistantMessageId: String? = null
        var serverAssistantMessageIds: List<String> = emptyList()
        var receivedNormalParagraphCount = 0
        var lastNormalParagraphId: String? = null
        var acceptedByServer = false
        var doneReceived = false
        var streamFailed = false
        var noReplyReceived = false
        val recoveryStartSeq = _state.value.messages.mapNotNull { it.sequenceNumber }.maxOrNull()
        val recoveryStartedAt = System.currentTimeMillis()

        chatRepo.sendMessage(request)
            .catch { err ->
                streamFailed = true
                DebugLog.e(TAG, "Stream error: ${err.message}", err)
                val parsed = parseErrorForDisplay(err.message)
                if (isNormalMode && acceptedByServer) {
                    startReplyRecoveryPolling("resend_stream_error", currentMode, recoveryStartSeq, recoveryStartedAt)
                } else if (!isNormalMode && acceptedByServer) {
                    startReplyRecoveryPolling("resend_stream_error", currentMode, null, recoveryStartedAt)
                } else if (!isNormalMode) {
                    updateLastAssistantMessage(accumulatedContent, isError = true)
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = parsed.first,
                        errorDebug = parsed.second
                    )
                } else {
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = parsed.first,
                        errorDebug = parsed.second
                    )
                }
                stopReplyTimer()
            }
            .collect { delta ->
                when (delta) {
                    is ChatDelta.Accepted -> {
                        acceptedByServer = true
                        delta.jobId?.let { currentJobId = it }
                        if (currentMode == "normal") {
                            _state.value = _state.value.copy(
                                quotaExceeded = false,
                                quotaExceededMessage = "",
                            )
                            markNormalUsersAcceptedByServer(
                                messageIds = listOfNotNull(delta.clientMessageId),
                                acceptAllPendingOnServerSignal = true,
                            )
                        }
                        if (!delta.implicit) {
                            persistAcceptedUserRound(characterId, currentMode)
                            if (currentMode != "normal") {
                                startReplyRecoveryPolling("resend_accepted", currentMode, recoveryStartSeq, recoveryStartedAt)
                            }
                        }
                    }
                    is ChatDelta.ServerAssistantId -> {
                        serverAssistantMessageId = delta.messageId
                    }
                    is ChatDelta.ServerAssistantIds -> {
                        serverAssistantMessageIds = delta.messageIds
                        serverAssistantMessageId = delta.messageIds.lastOrNull()
                    }
                    is ChatDelta.GalgameStepProgress -> {
                        _state.value = _state.value.copy(galgameStreamingStep = delta.label)
                    }
                    is ChatDelta.GalgamePlan -> {
                        // 本段文案由 GalgameStepProgress / chunk / metadata / options 驱动
                    }
                    is ChatDelta.GalgameChunk -> {
                        _state.value = _state.value.copy(galgameStreamingStep = galgameChunkStepLabel(delta.field))
                    }
                    is ChatDelta.GalgameMetadata -> {
                        _state.value = _state.value.copy(galgameStreamingStep = "场景字段")
                        applyGalgameMetadataPreview(delta.payload)
                    }
                    is ChatDelta.GalgameOptions -> {
                        _state.value = _state.value.copy(galgameStreamingStep = "选项生成")
                    }
                    is ChatDelta.GalgameStreamResult -> {
                        applyGalgameSuccessFromResultMap(delta.galgameResult)
                        galgameStreamResultReceived = true
                    }
                    is ChatDelta.Cancelled -> {
                        if (currentMode == "normal") {
                            normalAcceptedRecoveryJob?.cancel()
                            normalAcceptedRecoveryJob = null
                            replyRecoveryPollJob?.cancel()
                            replyRecoveryPollJob = null
                            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
                            onNormalReplyRoundFinished()
                        } else {
                            removeGalgamePendingRoundSilently()
                        }
                        stopReplyTimer()
                        currentJobId = null
                    }
                    is ChatDelta.NoReply -> {
                        if (currentMode == "normal") {
                            noReplyReceived = true
                            doneReceived = true
                            normalAcceptedRecoveryJob?.cancel()
                            normalAcceptedRecoveryJob = null
                            replyRecoveryPollJob?.cancel()
                            replyRecoveryPollJob = null
                            _state.value = _state.value.copy(isStreaming = false, galgameStreamingStep = null)
                            stopReplyTimer()
                            onNormalReplyRoundFinished()
                            triggerAutoSave(character, saveIntent = "user_edit")
                        }
                    }
                    is ChatDelta.AssistantParagraph -> {
                        stopNormalRecoveryAfterAssistantArrived()
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
                        val paraId = delta.id ?: UUID.randomUUID().toString()
                        val isFirstPara = receivedNormalParagraphCount == 0
                        upsertRealtimeAssistantParagraph(delta, paraId, isFirstPara, characterId)
                        receivedNormalParagraphCount++
                        lastNormalParagraphId = paraId
                    }
                    is ChatDelta.AssistantAsset -> {
                        stopNormalRecoveryAfterAssistantArrived()
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
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
                        if (currentMode == "normal") {
                            markNormalUsersAcceptedByServer(acceptAllPendingOnServerSignal = true)
                        }
                        accumulatedContent += delta.text
                        if (!isNormalMode) {
                            val now = System.currentTimeMillis()
                            if (now - lastUiUpdateAt >= 80L) {
                                updateStreamingMessage(accumulatedContent)
                                lastUiUpdateAt = now
                            }
                        }
                    }
                    is ChatDelta.Done -> {
                        doneReceived = true
                        currentJobId = delta.jobId
                        if (isNormalMode && noReplyReceived) {
                            return@collect
                        }
                        // 用发送时捕获的 currentMode 而非当前状态，防止模式切换后旧流式响应串入新模式列表
                        val isGalgameMode = currentMode == "galgame" || currentMode == "galgame_lock"
                        if (isGalgameMode) {
                            if (!galgameStreamResultReceived) {
                                startReplyRecoveryPolling("resend_done_without_result", currentMode, null, recoveryStartedAt)
                            }
                        } else if (isNormalMode) {
                            if (receivedNormalParagraphCount > 0) {
                                _state.value = _state.value.copy(isStreaming = false)
                            } else {
                                insertFinalNormalModeMessages(accumulatedContent, serverAssistantMessageIds)
                            }
                            val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                                ?: System.currentTimeMillis()
                            prefs.setModeLastChatTime(characterId, currentMode, immediateMsgTs)
                            stopReplyTimer()
                            emitForegroundChatCompleted(
                                characterId,
                                currentMode,
                                immediateMsgTs,
                                lastNormalParagraphId
                                    ?: serverAssistantMessageId
                                    ?: sentMessages.lastOrNull { it.role == "assistant" }?.messageId,
                                messageCount = serverAssistantMessageIds.size.takeIf { it > 0 }
                                    ?: receivedNormalParagraphCount.takeIf { it > 0 }
                                    ?: 1,
                            )
                        } else {
                            finalizeAssistantMessage(accumulatedContent)
                            val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                                ?: System.currentTimeMillis()
                            prefs.setModeLastChatTime(characterId, currentMode, immediateMsgTs)
                            stopReplyTimer()
                            emitForegroundChatCompleted(
                                characterId,
                                currentMode,
                                immediateMsgTs,
                                serverAssistantMessageId
                                    ?: sentMessages.lastOrNull { it.role == "assistant" }?.messageId,
                            )
                        }
                        triggerAutoSave(character)
                    }
                    is ChatDelta.Error -> {
                        val parsed = parseErrorForDisplay(delta.message)
                        if (isNormalMode) {
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                galgameStreamingStep = null,
                                error = parsed.first,
                                errorDebug = parsed.second
                            )
                        } else {
                            updateLastAssistantMessage(
                                accumulatedContent.ifBlank { "⚠️ ${parsed.first}" },
                                isError = accumulatedContent.isBlank()
                            )
                            _state.value = _state.value.copy(
                                isStreaming = false,
                                galgameStreamingStep = null,
                                error = if (accumulatedContent.isBlank()) parsed.first else null,
                                errorDebug = parsed.second
                            )
                        }
                        incrementRetryCount()
                    }
                    is ChatDelta.QuotaExceeded -> {
                        if (isNormalMode) {
                            noReplyReceived = true
                            doneReceived = true
                        }
                        if (!isNormalMode) {
                            updateLastAssistantMessage(
                                accumulatedContent.ifBlank { "⚠️ ${delta.message}" },
                                isError = accumulatedContent.isBlank()
                            )
                        }
                        _state.value = _state.value.copy(
                            isStreaming = false,
                            error = null,
                            quotaExceeded = true,
                            quotaExceededMessage = delta.message
                        )
                        stopReplyTimer()
                        if (isNormalMode) {
                            onNormalReplyRoundFinished()
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
                }
            }
        if (isNormalMode && !streamFailed && !doneReceived) {
            DebugLog.w(
                TAG,
                "Normal resend stream completed without done; accepted=$acceptedByServer paragraphs=$receivedNormalParagraphCount"
            )
            if (normalAssistantVisible || receivedNormalParagraphCount > 0) {
                normalGenerationUserIds.clear()
                _state.value = _state.value.copy(isStreaming = false)
                stopReplyTimer()
                triggerAutoSave(character)
                onNormalReplyRoundFinished()
            } else if (acceptedByServer) {
                startReplyRecoveryPolling("resend_completed_without_done", currentMode, recoveryStartSeq, recoveryStartedAt)
            } else {
                val parsed = parseErrorForDisplay("normal_stream_completed_without_done")
                _state.value = _state.value.copy(
                    isStreaming = false,
                    galgameStreamingStep = null,
                    error = parsed.first,
                    errorDebug = parsed.second
                )
                stopReplyTimer()
                onNormalReplyRoundFinished()
            }
        } else if (!isNormalMode && !streamFailed && acceptedByServer && !galgameStreamResultReceived) {
            startReplyRecoveryPolling("resend_completed_without_result", currentMode, null, recoveryStartedAt)
        }
    }
}

/**
 * 游戏/锁分模式专用：发送隐藏的开始指令（与 Web triggerGalgameStart isHidden=true 一致）。
 * 用户消息不添加到 UI，但通过 sentMessages 传给后端并持久化（后端保存为 is_hidden=1）。
 */
