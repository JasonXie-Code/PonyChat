package top.ponychat.webview.ui.chat

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

internal fun ChatViewModel.startUsageTracking() {
    if (_sessionStartMs.value == 0L) {
        _sessionStartMs.value = System.currentTimeMillis()
    }
    usageReminderJob?.cancel()
    usageReminderJob = viewModelScope.launch {
        val elapsed = System.currentTimeMillis() - _sessionStartMs.value
        val remaining = TWO_HOURS_MS - elapsed
        if (remaining > 0) {
            delay(remaining)
            _showUsageReminder.value = true
        }
    }
}

fun ChatViewModel.dismissUsageReminder() {
    _showUsageReminder.value = false
}

fun ChatViewModel.debugTriggerUsageReminder() {
    _showUsageReminder.value = true
}

fun ChatViewModel.dismissCrisisHotlineDialog() {
    _showCrisisHotlineDialog.value = false
}

fun ChatViewModel.debugTriggerCrisisHotlineDialog() {
    _showCrisisHotlineDialog.value = true
}
