package top.ponychat.webview.ui.chat

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import top.ponychat.webview.data.model.QuickMessage
import top.ponychat.webview.util.DebugLog

internal fun ChatViewModel.addQuickMessageImpl(title: String, content: String) {
    val username = prefs.username.takeIf { it.isNotBlank() } ?: return
    val body = content.trim()
    if (body.isBlank()) return
    viewModelScope.launch {
        chatRepo.addQuickMessage(username, title.trim(), body)
            .onSuccess { added ->
                val next = (_state.value.quickMessages + added).sortedWith(
                    compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id }
                )
                localCache.saveQuickMessages(username, next)
                _state.value = _state.value.copy(quickMessages = next)
            }
            .onFailure { error ->
                DebugLog.w(TAG, "addQuickMessage failed: ${error.message}", error)
                _state.value = _state.value.copy(error = error.message ?: "添加快捷消息失败")
            }
    }
}

internal fun ChatViewModel.updateQuickMessageImpl(message: QuickMessage) {
    val username = prefs.username.takeIf { it.isNotBlank() } ?: return
    if (message.content.isBlank() || message.id <= 0) return
    viewModelScope.launch {
        chatRepo.updateQuickMessage(message, username)
            .onSuccess {
                val next = _state.value.quickMessages.map {
                    if (it.id == message.id) message else it
                }.sortedWith(compareBy<QuickMessage> { it.sortOrder }.thenBy { it.id })
                localCache.saveQuickMessages(username, next)
                _state.value = _state.value.copy(quickMessages = next)
            }
            .onFailure { error ->
                DebugLog.w(TAG, "updateQuickMessage failed: ${error.message}", error)
                _state.value = _state.value.copy(error = error.message ?: "更新快捷消息失败")
            }
    }
}

internal fun ChatViewModel.deleteQuickMessageImpl(messageId: Int) {
    val username = prefs.username.takeIf { it.isNotBlank() } ?: return
    if (messageId <= 0) return
    viewModelScope.launch {
        chatRepo.deleteQuickMessage(username, messageId)
            .onSuccess {
                val next = _state.value.quickMessages.filterNot { it.id == messageId }
                localCache.saveQuickMessages(username, next)
                _state.value = _state.value.copy(quickMessages = next)
            }
            .onFailure { error ->
                DebugLog.w(TAG, "deleteQuickMessage failed: ${error.message}", error)
                _state.value = _state.value.copy(error = error.message ?: "删除快捷消息失败")
            }
    }
}
