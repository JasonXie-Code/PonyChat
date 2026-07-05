package top.ponychat.webview.util

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import top.ponychat.webview.data.prefs.AppPreferences

object MessageVibrationHelper {
    private val DOUBLE_SHORT_PATTERN = longArrayOf(0L, 45L, 60L, 45L)

    fun vibrateForMessage(context: Context, prefs: AppPreferences? = null) {
        val app = context.applicationContext
        val preferences = prefs ?: AppPreferences(app)
        if (!preferences.messageVibrationEnabled) return
        try {
            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                app.getSystemService(VibratorManager::class.java)?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                app.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            } ?: return
            if (!vibrator.hasVibrator()) return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(
                    VibrationEffect.createWaveform(
                        DOUBLE_SHORT_PATTERN,
                        intArrayOf(0, VibrationEffect.DEFAULT_AMPLITUDE, 0, VibrationEffect.DEFAULT_AMPLITUDE),
                        -1
                    )
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(DOUBLE_SHORT_PATTERN, -1)
            }
        } catch (e: Throwable) {
            DebugLog.w("MessageVibration", "vibrateForMessage failed: ${e.message}", e)
        }
    }
}
