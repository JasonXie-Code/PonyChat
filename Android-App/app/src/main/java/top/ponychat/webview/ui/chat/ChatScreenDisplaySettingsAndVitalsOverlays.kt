package top.ponychat.webview.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.SystemNavigationBarColorEffect

@Composable
internal fun ChatScreenDisplaySettingsAndVitalsOverlays(
    showDisplaySettingsState: MutableState<Boolean>,
    chatNavigationBarColor: Color,
    chatUseDarkNavigationBarIcons: Boolean,
    showVitalsPanel: Boolean,
    onDismissVitals: () -> Unit,
    prefs: AppPreferences,
    state: ChatUiState,
    galgameScore: Int?,
    viewModel: ChatViewModel,
    onThemeChanged: (Boolean) -> Unit,
    onPrefsSavedFromDisplaySettings: (AppPreferences) -> Unit,
    onDebugTriggerVictory: () -> Unit,
    onDebugResetVictory: () -> Unit,
) {
    // ==================== 显示设置页面（淡入淡出动画） ====================
    val displaySettingsTransition = remember { MutableTransitionState(false) }
    displaySettingsTransition.targetState = showDisplaySettingsState.value
    val isDisplaySettingsInWindow =
        displaySettingsTransition.currentState || displaySettingsTransition.targetState
    val settingsNavigationBarColor = MaterialTheme.colorScheme.background
    val activeNavigationBarColor =
        if (isDisplaySettingsInWindow) settingsNavigationBarColor else chatNavigationBarColor
    val activeUseDarkNavigationBarIcons =
        if (isDisplaySettingsInWindow) {
            settingsNavigationBarColor.luminance() > 0.5f
        } else {
            chatUseDarkNavigationBarIcons
        }

    SystemNavigationBarColorEffect(
        color = activeNavigationBarColor,
        useDarkIcons = activeUseDarkNavigationBarIcons
    )

    BackHandler(enabled = showDisplaySettingsState.value) {
        showDisplaySettingsState.value = false
    }
    AnimatedVisibility(
        visibleState = displaySettingsTransition,
        enter = fadeIn(animationSpec = tween(durationMillis = 220)),
        exit = fadeOut(animationSpec = tween(durationMillis = 180))
    ) {
        ChatDisplaySettingsScreen(
            prefs = prefs,
            onDismiss = { showDisplaySettingsState.value = false },
            onThemeChanged = onThemeChanged,
            onSave = onPrefsSavedFromDisplaySettings,
            currentMode = state.mode,
            currentCharacterId = state.character?.id.orEmpty(),
            currentGalgameScore = galgameScore,
            onDebugForceScore = { viewModel.debugApplyLocalGalgameScore(it, forceZeroInLock = true) },
            onDebugAdjustScore = { viewModel.debugAdjustLocalGalgameScore(it, forceZeroInLock = true) },
            onDebugTriggerVictory = onDebugTriggerVictory,
            onDebugResetVictory = onDebugResetVictory,
            onDebugTriggerError = { viewModel.debugTriggerError(it) },
            onDebugClearError = { viewModel.debugClearError() },
            onDebugInjectMessage = { viewModel.debugInjectAssistantMessage() },
            onDebugInjectPendingUserAccept = { viewModel.debugInjectPendingUserAcceptMessage(timedOut = false) },
            onDebugInjectTimedOutUserAccept = { viewModel.debugInjectPendingUserAcceptMessage(timedOut = true) },
            onDebugAcceptPendingUsers = { viewModel.debugAcceptPendingUserMessages() },
            onDebugInjectDelayedNormalSingle = { viewModel.debugInjectDelayedNormalSingleMessage() },
            onDebugInjectDelayedNormalInstantTriple = { viewModel.debugInjectDelayedNormalInstantTripleMessages() },
            onDebugInjectDelayedNormalIntervalTriple = { viewModel.debugInjectDelayedNormalIntervalTripleMessages() },
            onDebugInjectDelayedProactiveSingle = { viewModel.debugInjectDelayedProactiveSingleMessage() },
            onDebugInjectDelayedProactiveInstantTriple = { viewModel.debugInjectDelayedProactiveInstantTripleMessages() },
            onDebugInjectDelayedProactiveIntervalTriple = { viewModel.debugInjectDelayedProactiveIntervalTripleMessages() },
            onDebugInjectLongPressSamples = { viewModel.debugInjectLongPressMenuSamples() },
            onDebugInjectImagePreviewSamples = { viewModel.debugInjectImagePreviewSamples() },
            onDebugInjectVoiceMessage = { viewModel.debugInjectVoiceMessage() },
            onDebugInjectUserVoiceMessage = { viewModel.debugInjectUserVoiceMessage() },
            onDebugGenerateBackendVoice = { viewModel.debugGenerateBackendVoiceForLastAssistant() },
            onDebugInjectVoiceCacheMissing = { viewModel.debugInjectVoiceCacheMissingMessage() },
            onDebugInjectVoiceFailed = { viewModel.debugInjectVoiceFailedMessage() },
            currentQuotaInfo = state.quotaInfo,
            onDebugLoadQuota = { viewModel.debugLoadQuota() },
            onDebugSimulateQuotaExceeded = { viewModel.debugSimulateQuotaExceeded() },
            onDebugClearQuotaExceeded = { viewModel.debugClearQuotaExceeded() },
            onDebugForceSummarize = { viewModel.debugForceSummarize() },
            onDebugShowUsageReminder = { viewModel.debugTriggerUsageReminder() },
            onDebugCopyConvId = { viewModel.debugCopyConversationId() },
            onDebugPrintSnapshot = { viewModel.debugPrintStateSnapshot() },
            onDebugClearCache = { viewModel.debugClearLocalCache() },
            debugRelationshipStage = normalizeRelationshipStageKey(
                state.relationshipStageOverride ?: state.relationshipSnapshot?.stageKey ?: "uncertain"
            ),
            debugRelationshipUsesOverride = state.relationshipStageOverride != null,
            onDebugSetRelationshipStage = { viewModel.debugSetLocalRelationshipStage(it) },
            onDebugUseServerRelationshipStage = { viewModel.debugUseServerRelationshipStage() },
            debugConversationId = state.conversationId,
            debugMessageCount = state.messages.size,
            debugIsStreaming = state.isStreaming,
            debugIsBackgroundRefreshing = state.isBackgroundRefreshing,
        )
    }
    if (showVitalsPanel && state.mode == "galgame_lock") {
        LockVitalsPanelDialog(
            charVitals = state.lockCharVitals,
            charMood = state.lockCharMood,
            organFill = state.lockOrganFill,
            charGender = state.lockCharGender,
            charVitalsDelta = state.lockCharVitalsDelta,
            charMoodDelta = state.lockCharMoodDelta,
            organFillDelta = state.lockOrganFillDelta,
            onDismiss = onDismissVitals,
        )
    }
}
