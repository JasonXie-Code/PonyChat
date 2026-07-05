package top.ponychat.webview.util

import android.util.Log

/**
 * 将网络/IO 异常映射为用户友好的中文提示，保留应用层已有语义的错误消息。
 *
 * 规则：
 * - 网络层 IOException（连接失败、超时、EOF 等）→ 友好描述
 * - 其余 Exception（来自服务器或业务校验）→ 保留原 message
 * - message 为空 → 返回 fallback
 */
fun Throwable.toUserMessage(fallback: String = "操作失败，请稍后重试"): String {
    if (this is UserFacingException) {
        return message?.takeIf { it.isNotBlank() } ?: fallback
    }
    return ErrorFormatter.formatThrowable(this, fallback).asSingleLine()
}

/**
 * 调试日志工具：统一错误日志格式，便于 debug。
 * 所有报错均通过此工具打印，便于在 logcat 中过滤 [PonyChat]。
 */
object DebugLog {
    private const val PREFIX = "PonyChat"

    @JvmStatic
    fun e(tag: String, message: String, throwable: Throwable? = null) {
        if (throwable != null) {
            Log.e(PREFIX, "[$tag] $message", throwable)
        } else {
            Log.e(PREFIX, "[$tag] $message")
        }
    }

    @JvmStatic
    fun w(tag: String, message: String, throwable: Throwable? = null) {
        if (throwable != null) {
            Log.w(PREFIX, "[$tag] $message", throwable)
        } else {
            Log.w(PREFIX, "[$tag] $message")
        }
    }

    @JvmStatic
    fun i(tag: String, message: String) = Log.i(PREFIX, "[$tag] $message")

    @JvmStatic
    fun d(tag: String, message: String) = Log.d(PREFIX, "[$tag] $message")
}
