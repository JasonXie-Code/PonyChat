package top.ponychat.webview.device

import androidx.compose.runtime.compositionLocalOf

val LocalDeviceExperience = compositionLocalOf { false }
val LocalCompanionRuntimeReady = compositionLocalOf { false }
val LocalCompanionRuntimeState = compositionLocalOf<CompanionRuntimeState> {
    CompanionRuntimeState.Unavailable
}
