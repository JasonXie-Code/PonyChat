package top.ponychat.webview.ui.creation

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.compose.runtime.*
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.ponychat.webview.data.prefs.AppPreferences

internal const val CREATION_PULSE_INTERVAL_MS = 83L

/** A single cancellable timer; token updates must never restart or multiply it. */
internal class CreationPulseController(private val scope: CoroutineScope, private val pulse: () -> Unit) {
    private var job: Job? = null
    fun setActive(active: Boolean) {
        if (!active) { job?.cancel(); job = null; return }
        if (job?.isActive == true) return
        job = scope.launch {
            while (true) { pulse(); delay(CREATION_PULSE_INTERVAL_MS) }
        }
    }
}

@Composable
internal fun creationHapticAction(): (() -> Unit) -> Unit {
    val haptic = LocalHapticFeedback.current
    return { action -> haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove); action() }
}

@Composable
internal fun CreationStreamingHaptics(active: Boolean, prefs: AppPreferences) {
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val controller = remember(scope, prefs) {
        val context = prefs.applicationContext
        val vibrator = if (Build.VERSION.SDK_INT >= 31)
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        else @Suppress("DEPRECATION") (context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator)
        CreationPulseController(scope) {
            if (prefs.messageVibrationEnabled && vibrator?.hasVibrator() == true) {
                try {
                    if (Build.VERSION.SDK_INT >= 26) vibrator.vibrate(VibrationEffect.createOneShot(12,
                        if (vibrator.hasAmplitudeControl()) 70 else VibrationEffect.DEFAULT_AMPLITUDE))
                    else @Suppress("DEPRECATION") vibrator.vibrate(12)
                } catch (_: RuntimeException) { /* Missing vibration hardware or permission is nonfatal. */ }
            }
        }
    }
    DisposableEffect(controller, active, lifecycle) {
        fun update() = controller.setActive(active && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
        val observer = LifecycleEventObserver { _, _ -> update() }
        lifecycle.addObserver(observer)
        update()
        onDispose { lifecycle.removeObserver(observer); controller.setActive(false) }
    }
}
