package top.ponychat.webview.util

import top.ponychat.webview.BuildConfig

/**
 * 通知链路专用调试日志（仅 DEBUG 包输出）。
 *
 * Logcat 过滤示例（Windows PowerShell）：
 * ```
 * adb logcat -s PonyChat:D | Select-String "NotifyTrace"
 * ```
 * 或 Android Studio Logcat 搜索：`NotifyTrace`
 */
object NotificationTrace {

    private const val SUB = "NotifyTrace"

    @JvmStatic
    fun log(phase: String, detail: String) {
        if (BuildConfig.DEBUG) {
            DebugLog.d(SUB, "[$phase] $detail")
        }
    }
}
