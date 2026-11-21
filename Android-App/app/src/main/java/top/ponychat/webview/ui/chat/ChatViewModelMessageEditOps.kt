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
fun ChatViewModel.deleteMessage(messageId: String, conversationIdOverride: String? = null) {
    if (_state.value.isStreaming || messageId.isBlank()) return
    val stateNow = _state.value
    val character = stateNow.character ?: return
    val characterId = character.id?.takeIf { it.isNotBlank() } ?: return
    val username = prefs.username.takeIf { it.isNotBlank() } ?: return
    val target = stateNow.messages.firstOrNull { it.id == messageId || it.messageId == messageId }
    val serverMessageId = target?.messageId?.takeIf { it.isNotBlank() } ?: messageId
    val conversationId = conversationIdOverride?.takeIf { it.isNotBlank() }
        ?: stateNow.conversationId?.takeIf { it.isNotBlank() }
    val isLocalDebugMessage = target?.id?.startsWith("debug_") == true ||
        target?.messageId?.startsWith("debug_") == true ||
        messageId.startsWith("debug_")

    val previousMessages = stateNow.messages
    val previousSentById = sentMessages.mapNotNull { msg ->
        msg.messageId?.let { id -> id to msg }
    }.toMap()
    hideDeletedMessageLocally(
        requestedMessageId = messageId,
        serverMessageId = serverMessageId,
        characterId = characterId,
        conversationId = conversationId,
        persistLocalCache = stateNow.mode != "normal" || conversationId == null
    )

    if (isLocalDebugMessage) return
    if (stateNow.mode != "normal" || conversationId == null) return

    viewModelScope.launch {
        charRepo.hideMessage(username, characterId, conversationId, serverMessageId).fold(
            onSuccess = {
                hideDeletedMessageLocally(
                    requestedMessageId = messageId,
                    serverMessageId = serverMessageId,
                    characterId = characterId,
                    conversationId = conversationId,
                    persistLocalCache = true
                )
            },
            onFailure = { err ->
                if (target != null && _state.value.messages.none { it.id == target.id || it.messageId == serverMessageId }) {
                    _state.value = _state.value.copy(messages = previousMessages)
                }
                for (i in sentMessages.indices) {
                    val id = sentMessages[i].messageId
                    if (id == messageId || id == serverMessageId) {
                        previousSentById[id]?.let { sentMessages[i] = it }
                    }
                }
                _snackbarMessages.emit(err.toUserMessage("删除消息失败"))
            }
        )
    }
}

internal fun ChatViewModel.hideDeletedMessageLocally(
    requestedMessageId: String,
    serverMessageId: String,
    characterId: String,
    conversationId: String?,
    persistLocalCache: Boolean = true
) {
    _state.value = _state.value.copy(
        messages = _state.value.messages.filterNot {
            it.id == requestedMessageId ||
                it.id == serverMessageId ||
                it.messageId == requestedMessageId ||
                it.messageId == serverMessageId
        }
    )
    for (i in sentMessages.indices) {
        val msg = sentMessages[i]
        if (msg.messageId == requestedMessageId || msg.messageId == serverMessageId) {
            sentMessages[i] = msg.copy(isHidden = true)
        }
    }
    if (!persistLocalCache) return
    localCache.hideMessageLocally(
        username = prefs.username,
        characterId = characterId,
        mode = _state.value.mode,
        conversationId = conversationId,
        messageId = serverMessageId
    )
    if (requestedMessageId != serverMessageId) {
        localCache.hideMessageLocally(
            username = prefs.username,
            characterId = characterId,
            mode = _state.value.mode,
            conversationId = conversationId,
            messageId = requestedMessageId
        )
    }
}

/**
 * 撤回用户消息：
 * - UI：将消息标记为已撤回，显示「消息已撤回」占位，仅支持 2 分钟内的用户消息。
 * - 服务端/模型上下文：把同一条 user 消息的 content 替换为「（撤回了消息）」并重新发送，
 *   角色知道有消息被撤回但不知道内容，可以表现出好奇。
 */
fun ChatViewModel.retractMessage(messageId: String) {
    val stateNow = _state.value
    if (messageId.isBlank()) return
    val msgs = _state.value.messages.toMutableList()
    val idx = msgs.indexOfFirst { it.id == messageId || it.messageId == messageId }
    if (idx < 0) return
    val msg = msgs[idx]
    if (!msg.isUser() || msg.isRetracted) return
    if (System.currentTimeMillis() - msg.timestamp > 120_000L) return
    if (msgs.drop(idx + 1).any { it.isAssistant() }) return

    if (stateNow.isStreaming) {
        streamJob?.cancel()
        streamJob = null
        replyRecoveryPollJob?.cancel()
        replyRecoveryPollJob = null
        stopReplyTimer()
        val jobIdToCancel = currentJobId
        currentJobId = null
        val characterId = stateNow.character?.id?.takeIf { it.isNotBlank() }
        if (!characterId.isNullOrBlank()) {
            viewModelScope.launch {
                chatRepo.cancelGeneration(
                    username = prefs.username,
                    characterId = characterId,
                    conversationId = stateNow.conversationId,
                    clientId = clientId,
                    jobId = jobIdToCancel,
                )
            }
        }
    }
    normalGenerationStarted = false
    normalAssistantVisible = false

    msgs[idx] = msg.copy(isRetracted = true)
    _state.value = _state.value.copy(
        messages = msgs,
        isStreaming = false,
        galgameStreamingStep = null
    )

    val ids = setOfNotNull(msg.id, msg.messageId, messageId)
    val characterIdForOriginal = stateNow.character?.id?.takeIf { it.isNotBlank() }
    if (characterIdForOriginal != null) {
        ids.forEach { id ->
            localCache.saveRetractedMessageOriginal(
                username = prefs.username,
                characterId = characterIdForOriginal,
                mode = stateNow.mode,
                conversationId = stateNow.conversationId,
                messageId = id,
                content = msg.content
            )
        }
    }

    val pendingId = msg.messageId?.takeIf { it.isNotBlank() } ?: msg.id
    val retractedContent = RETRACTED_USER_MESSAGE_TEXT
    val sentIdx = sentMessages.indexOfFirst { it.messageId in ids }
        .takeIf { it >= 0 }
        ?: sentMessages.indexOfFirst { it.role == msg.role && it.content == msg.content }
    if (sentIdx >= 0) {
        sentMessages[sentIdx] = sentMessages[sentIdx].copy(content = retractedContent)
    } else if (pendingId.isNotBlank()) {
        sentMessages.add(
            ChatMessage(
                role = "user",
                content = retractedContent,
                messageId = pendingId,
                timestamp = msg.timestamp,
                quotedMessage = msg.quotedMessage
            )
        )
    }

    val character = _state.value.character ?: return
    if (_state.value.mode == "normal") {
        scheduleNormalReplyAfterUserInterrupt()
    } else {
        viewModelScope.launch { triggerAutoSave(character, saveIntent = "user_edit") }
    }
}

fun ChatViewModel.enterExportMode() {
    if (!_state.value.isStreaming)
        _state.value = _state.value.copy(isExportMode = true, exportSelectedIds = emptySet())
}

fun ChatViewModel.exitExportMode() {
    _state.value = _state.value.copy(isExportMode = false, exportSelectedIds = emptySet())
}

fun ChatViewModel.toggleExportSelection(messageId: String) {
    val ids = _state.value.exportSelectedIds
    _state.value = _state.value.copy(
        exportSelectedIds = if (messageId in ids) ids - messageId else ids + messageId
    )
}

/** 编辑指定消息内容 */
fun ChatViewModel.editMessage(messageId: String, newContent: String) {
    if (_state.value.isStreaming) return
    val updatedText = newContent.trim()
    if (updatedText.isBlank()) {
        _state.value = _state.value.copy(error = "消息不能为空")
        return
    }

    val msgs = _state.value.messages.toMutableList()
    val idx = msgs.indexOfFirst { it.id == messageId }
    if (idx < 0) return

    val old = msgs[idx]
    msgs[idx] = old.copy(content = updatedText, isError = false)

    // sentMessages 没有 UI messageId，按角色+内容做最佳努力同步
    val sentIdx = sentMessages.indexOfFirst {
        it.role == old.role && it.content == old.content
    }
    if (sentIdx >= 0) {
        sentMessages[sentIdx] = sentMessages[sentIdx].copy(content = updatedText)
    }

    _state.value = _state.value.copy(messages = msgs, error = null)

    val character = _state.value.character ?: return
    viewModelScope.launch { triggerAutoSave(character, saveIntent = "user_edit") }
}

/** 重新生成最后一条 AI 回复 */
fun ChatViewModel.regenerateLastResponse() {
    if (_state.value.isStreaming) return
    val msgs = _state.value.messages.toMutableList()

    val lastAssIdx = msgs.indexOfLast { it.isAssistant() }
    if (lastAssIdx < 0) return
    val removedAssistantId = msgs[lastAssIdx].id
    msgs.removeAt(lastAssIdx)

    val lastUserIdx = msgs.indexOfLast { it.isUser() }
    if (lastUserIdx < 0) return
    val removedUserId = msgs[lastUserIdx].id
    val userContent = msgs[lastUserIdx].content
    msgs.removeAt(lastUserIdx)

    // 软删除被重试的上一轮 user+assistant：保留在数据库用于审计/回溯；
    // 但后续不展示、也不应再次参与上下文发送。
    fun markSentMessageHidden(targetId: String, role: String) {
        val idxById = sentMessages.indexOfLast { it.messageId == targetId }
        val idx = if (idxById >= 0) idxById
        else sentMessages.indexOfLast { it.role == role && it.isHidden != true }
        if (idx >= 0) {
            val old = sentMessages[idx]
            sentMessages[idx] = old.copy(isHidden = true)
        }
    }
    markSentMessageHidden(removedAssistantId, "assistant")
    markSentMessageHidden(removedUserId, "user")

    _state.value = _state.value.copy(messages = msgs, inputText = userContent, error = null)
    // 先把「重试软删除」持久化，再发新一轮请求，减少异常中断导致的状态不一致。
    _state.value.character?.let { triggerAutoSave(it, saveIntent = "user_edit") }
    sendMessage()
}

// ==================== 对话管理 ====================

/** 新建对话（清空当前聊天） */
