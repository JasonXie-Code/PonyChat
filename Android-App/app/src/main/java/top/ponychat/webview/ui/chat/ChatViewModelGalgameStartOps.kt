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
fun ChatViewModel.sendGalgameStartMessage(season: String, time: String, location: String, customPrompt: String) {
    if (_state.value.isStreaming) return

    val character = _state.value.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: run {
        _state.value = _state.value.copy(error = "角色数据异常：缺少角色 ID")
        return
    }
    val username = prefs.username

    val customBlock = if (customPrompt.isNotBlank())
        "\n【玩家自定义开局设定】\n$customPrompt"
    else ""

    val startContent = buildString {
        append("【核心指令】游戏开始。请按以下开局设定进入剧情：")
        append("\ntime=$time, location=$location, season=$season")
        if (customPrompt.isNotBlank()) append(customBlock)
        append("\nPlease naturally reflect the above setting in the opening scene.")
    }

    val hiddenUserMsgId = UUID.randomUUID().toString()
    val assistantMsg = Message(
        id = UUID.randomUUID().toString(),
        role = "assistant",
        content = "",
        timestamp = System.currentTimeMillis(),
        isStreaming = true
    )

    _state.value = _state.value.copy(
        messages = _state.value.messages + assistantMsg,
        inputText = "",
        isStreaming = true,
        error = null,
        errorDebug = null,
        // 开局重置体征基准，确保首轮不因残留旧局数据而显示错误的 delta 标签
        lockCharVitals      = emptyMap(),
        lockCharMood        = emptyMap(),
        lockOrganFill       = emptyMap(),
        lockCharVitalsDelta = emptyMap(),
        lockCharMoodDelta   = emptyMap(),
        lockOrganFillDelta  = emptyMap()
    )

    sentMessages.add(
        ChatMessage(
            role = "user",
            content = startContent,
            messageId = hiddenUserMsgId,
            timestamp = System.currentTimeMillis(),
            isHidden = true
        )
    )

    val currentMode = _state.value.mode
    val request = ChatRequest(
        username = username,
        characterId = characterId,
        messages = latestUserMessageForServer(includeHidden = true),
        mode = currentMode,
        conversationId = _state.value.conversationId,
        clientId = clientId,
        memoryEnabled = prefs.memoryEnabled,
        crisisHotlineEnabled = prefs.crisisHotlineEnabled,
        clientContext = null  // 游戏开局，不注入环境上下文
    )

    startReplyTimer()

    streamJob?.cancel()
    streamJob = viewModelScope.launch {
        var accumulatedContent = ""
        var lastUiUpdateAt = 0L
        var galgameStreamResultReceived = false
        var acceptedByServer = false
        val recoveryStartedAt = System.currentTimeMillis()

        chatRepo.sendMessage(request)
            .catch { err ->
                DebugLog.e(TAG, "GalgameStart stream error: ${err.message}", err)
                if (acceptedByServer) {
                    startReplyRecoveryPolling("start_stream_error", currentMode, null, recoveryStartedAt)
                } else {
                    updateLastAssistantMessage(accumulatedContent, isError = true)
                    val parsed = parseErrorForDisplay(err.message)
                    _state.value = _state.value.copy(
                        isStreaming = false,
                        galgameStreamingStep = null,
                        error = parsed.first,
                        errorDebug = parsed.second
                    )
                    stopReplyTimer()
                }
            }
            .collect { delta ->
                when (delta) {
                    is ChatDelta.Accepted -> {
                        acceptedByServer = true
                        currentJobId = delta.jobId
                        if (currentMode == "normal") {
                            _state.value = _state.value.copy(
                                quotaExceeded = false,
                                quotaExceededMessage = "",
                            )
                        }
                        if (currentMode != "normal") {
                            startReplyRecoveryPolling("start_accepted", currentMode, null, recoveryStartedAt)
                        }
                    }
                    is ChatDelta.ServerAssistantId -> { }
                    is ChatDelta.ServerAssistantIds -> { }
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
                        removeGalgamePendingRoundSilently()
                        stopReplyTimer()
                        currentJobId = null
                    }
                    is ChatDelta.NoReply -> { }
                    is ChatDelta.AssistantParagraph -> { }
                    is ChatDelta.AssistantAsset -> { }
                    is ChatDelta.Token -> {
                        accumulatedContent += delta.text
                        val now = System.currentTimeMillis()
                        if (now - lastUiUpdateAt >= 16L) {
                            updateStreamingMessage(accumulatedContent)
                            lastUiUpdateAt = now
                        }
                    }
                    is ChatDelta.Done -> {
                        currentJobId = delta.jobId
                        if (!galgameStreamResultReceived) {
                            startReplyRecoveryPolling("start_done_without_result", currentMode, null, recoveryStartedAt)
                        }
                        val immediateMsgTs = sentMessages.lastOrNull { it.isHidden != true }?.timestamp?.takeIf { it > 0L }
                            ?: System.currentTimeMillis()
                        prefs.setModeLastChatTime(characterId, currentMode, immediateMsgTs)
                        triggerAutoSave(character)
                    }
                    is ChatDelta.Error -> {
                        val parsed = parseErrorForDisplay(delta.message)
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
                        incrementRetryCount()
                    }
                    is ChatDelta.QuotaExceeded -> {
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
        if (acceptedByServer && !galgameStreamResultReceived) {
            startReplyRecoveryPolling("start_completed_without_result", currentMode, null, recoveryStartedAt)
        }
    }
}

// ==================== 消息操作 ====================

