package top.ponychat.webview.util

import org.json.JSONArray
import org.json.JSONObject
import java.io.EOFException
import java.io.IOException
import java.net.ConnectException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.Locale
import javax.net.ssl.SSLException

data class DisplayError(
    val userMessage: String,
    val developerMessage: String? = null
) {
    fun asSingleLine(): String {
        val dev = developerMessage?.takeIf { it.isNotBlank() } ?: return userMessage
        return "$userMessage | $dev"
    }

    fun asMultiline(): String {
        val dev = developerMessage?.takeIf { it.isNotBlank() } ?: return userMessage
        return "$userMessage\n开发信息：$dev"
    }
}

object ErrorFormatter {
    fun format(
        raw: String?,
        fallback: String = "操作失败，请稍后重试",
        developerDetail: String? = null
    ): DisplayError {
        val trimmed = raw?.trim().orEmpty()
        if (trimmed.isBlank()) {
            return DisplayError(fallback, compactDeveloper(developerDetail))
        }

        parseJson(trimmed, fallback, developerDetail)?.let { return it }
        parseHtml(trimmed, fallback, developerDetail)?.let { return it }
        parseHttpStatus(trimmed)?.let { status ->
            return httpError(
                fallback = fallback,
                code = status.code,
                reason = status.reason,
                body = null,
                developerDetail = developerDetail
            )
        }

        val lower = trimmed.lowercase(Locale.getDefault())
        val networkMessage = when {
            lower == "timeout" ||
                "timed out" in lower ||
                "sockettimeoutexception" in lower ->
                "请求超时，请检查网络或稍后重试"
            "unable to resolve host" in lower ||
                "unknownhostexception" in lower ->
                "网络不可用或服务器地址无法解析，请检查网络和服务器地址"
            "connection refused" in lower ||
                "failed to connect" in lower ||
                "connectexception" in lower ->
                "无法连接到服务器，请检查服务器是否在线"
            "unexpected end of stream" in lower ||
                "end of stream" in lower ||
                "eofexception" in lower ->
                "服务器连接中断，请稍后重试"
            "ssl" in lower ||
                "certificate" in lower ->
                "安全连接失败，请检查证书或服务器地址"
            "debug_weak_network_offline_window" in lower ->
                "调试网络已模拟离线，请稍后重试"
            else -> null
        }
        if (networkMessage != null) {
            return DisplayError(
                networkMessage,
                compactDeveloper(listOf(trimmed, developerDetail).joinNonBlank(" | "))
            )
        }

        return DisplayError(
            compactUser(trimmed.ifBlank { fallback }),
            compactDeveloper(developerDetail)
        )
    }

    fun formatThrowable(
        throwable: Throwable,
        fallback: String = "操作失败，请稍后重试"
    ): DisplayError {
        val user = when (throwable) {
            is UnknownHostException -> "网络不可用或服务器地址无法解析，请检查网络和服务器地址"
            is SocketTimeoutException -> "请求超时，请检查网络或稍后重试"
            is ConnectException -> "无法连接到服务器，请检查服务器是否在线"
            is EOFException -> "服务器连接中断，请稍后重试"
            is SSLException -> "安全连接失败，请检查证书或服务器地址"
            is SocketException -> "网络连接中断，请检查网络后重试"
            is IOException -> "网络请求失败，请检查网络连接"
            else -> null
        }
        val dev = compactDeveloper(
            listOf(
                throwable::class.java.simpleName,
                throwable.message
            ).joinNonBlank(": ")
        )
        if (user != null) return DisplayError(user, dev)
        return format(throwable.message, fallback, dev)
    }

    fun httpError(
        fallback: String,
        code: Int,
        reason: String? = null,
        body: String? = null,
        developerDetail: String? = null
    ): DisplayError {
        val bodyError = if (!body.isNullOrBlank() && !looksLikeGenericHttpBody(body)) {
            format(body, fallback, developerDetail)
        } else {
            null
        }
        val normalizedReason = reason?.trim()?.takeIf { it.isNotBlank() } ?: defaultHttpReason(code)
        val user = when (code) {
            400 -> "请求内容格式不正确，请检查输入后重试"
            401 -> "登录已过期，请重新登录"
            403 -> "当前账号没有权限执行此操作"
            404 -> "请求的内容不存在，或服务器接口地址不正确"
            409 -> "当前操作和服务器状态冲突，请稍后重试"
            413 -> "上传内容过大，请压缩后重试"
            422 -> "提交内容不完整或格式不正确，请检查后重试"
            426 -> "当前版本已停止支持，请更新到最新版"
            429 -> bodyError?.userMessage ?: "请求太频繁或今日额度已用完，请稍后再试"
            500 -> "服务器内部错误，请稍后重试"
            502 -> "服务器网关错误，后端服务可能暂时不可用，请稍后重试"
            503 -> "服务器维护或过载，请稍后重试"
            504 -> "服务器响应超时，请稍后重试"
            in 400..499 -> bodyError?.userMessage ?: "请求失败，请检查输入或登录状态"
            in 500..599 -> bodyError?.userMessage ?: "服务器暂时不可用，请稍后重试"
            else -> bodyError?.userMessage ?: fallback
        }
        val devParts = listOf(
            "HTTP $code${normalizedReason?.let { " $it" }.orEmpty()}",
            bodyError?.developerMessage,
            extractServerSignature(body),
            developerDetail
        )
        return DisplayError(user, compactDeveloper(devParts.joinNonBlank(" | ")))
    }

    private fun parseJson(raw: String, fallback: String, developerDetail: String?): DisplayError? {
        if (!raw.startsWith("{") && !raw.startsWith("[")) return null
        return runCatching {
            val value: Any = if (raw.startsWith("{")) JSONObject(raw) else JSONArray(raw)
            val message = jsonMessage(value).ifBlank { fallback }
            val status = if (value is JSONObject) jsonInt(value, "status", "status_code", "code") else null
            val debugParts = mutableListOf<String>()
            if (value is JSONObject) {
                jsonString(value, "debugCode", "debug_code", "code", "error_code")?.let {
                    debugParts += "code=$it"
                }
                jsonString(value, "debugDetail", "debug_detail", "trace", "request_id")?.let {
                    debugParts += it
                }
            }
            developerDetail?.takeIf { it.isNotBlank() }?.let { debugParts += it }
            if (status != null && status in 400..599) {
                val fromStatus = httpError(
                    fallback = message,
                    code = status,
                    body = null,
                    developerDetail = debugParts.joinNonBlank(" | ")
                )
                fromStatus.copy(userMessage = compactUser(message.takeUnless { looksLikeRawStatus(it) } ?: fromStatus.userMessage))
            } else {
                val nested = if (looksLikeHtml(message) || looksLikeJson(message) || parseHttpStatus(message) != null) {
                    format(message, fallback, debugParts.joinNonBlank(" | "))
                } else {
                    null
                }
                nested ?: DisplayError(compactUser(message), compactDeveloper(debugParts.joinNonBlank(" | ")))
            }
        }.getOrNull()
    }

    private fun parseHtml(raw: String, fallback: String, developerDetail: String?): DisplayError? {
        if (!looksLikeHtml(raw)) return null
        val text = htmlToText(raw).ifBlank { fallback }
        val status = parseHttpStatus(text) ?: parseHttpStatus(raw)
        if (status != null) {
            return httpError(
                fallback = fallback,
                code = status.code,
                reason = status.reason,
                body = raw,
                developerDetail = developerDetail
            )
        }
        return DisplayError(
            compactUser(text),
            compactDeveloper(listOf(extractServerSignature(raw), developerDetail).joinNonBlank(" | "))
        )
    }

    private fun jsonMessage(value: Any?): String {
        return when (value) {
            is JSONObject -> {
                val direct = jsonString(value, "detail", "message", "error", "reason")
                if (!direct.isNullOrBlank()) direct else {
                    val detail = value.opt("detail")
                    when (detail) {
                        is JSONObject, is JSONArray -> jsonMessage(detail)
                        else -> value.toString()
                    }
                }
            }
            is JSONArray -> (0 until value.length())
                .asSequence()
                .mapNotNull { idx -> jsonMessage(value.opt(idx)).takeIf { it.isNotBlank() } }
                .joinToString("；")
            null -> ""
            JSONObject.NULL -> ""
            else -> value.toString()
        }
    }

    private fun jsonString(obj: JSONObject, vararg names: String): String? {
        for (name in names) {
            val value = obj.opt(name)
            val text = when (value) {
                is JSONObject, is JSONArray -> jsonMessage(value)
                null, JSONObject.NULL -> null
                else -> value.toString()
            }?.trim()
            if (!text.isNullOrBlank()) return text
        }
        return null
    }

    private fun jsonInt(obj: JSONObject, vararg names: String): Int? {
        for (name in names) {
            val value = obj.opt(name)
            when (value) {
                is Number -> return value.toInt()
                is String -> value.toIntOrNull()?.let { return it }
            }
        }
        return null
    }

    private data class HttpStatus(val code: Int, val reason: String?)

    private fun parseHttpStatus(text: String): HttpStatus? {
        val match = Regex(
            pattern = """(?i)\b(?:HTTP\s*)?([1-5]\d{2})\s*([A-Z][A-Z0-9 _.-]{2,48})?""",
        ).find(text) ?: return null
        val code = match.groupValues.getOrNull(1)?.toIntOrNull() ?: return null
        val reason = match.groupValues.getOrNull(2)
            ?.trim()
            ?.trim('-', '_', '.', ':')
            ?.lowercase(Locale.US)
            ?.split(Regex("\\s+"))
            ?.joinToString(" ") { part -> part.replaceFirstChar { ch -> ch.uppercase(Locale.US) } }
            ?.takeIf { it.isNotBlank() && it.any { ch -> ch.isLetter() } }
        return HttpStatus(code, reason)
    }

    private fun defaultHttpReason(code: Int): String? = when (code) {
        400 -> "Bad Request"
        401 -> "Unauthorized"
        403 -> "Forbidden"
        404 -> "Not Found"
        409 -> "Conflict"
        413 -> "Payload Too Large"
        422 -> "Unprocessable Entity"
        426 -> "Upgrade Required"
        429 -> "Too Many Requests"
        500 -> "Internal Server Error"
        502 -> "Bad Gateway"
        503 -> "Service Unavailable"
        504 -> "Gateway Timeout"
        else -> null
    }

    private fun looksLikeHtml(raw: String): Boolean {
        val lower = raw.take(300).lowercase(Locale.getDefault())
        return "<html" in lower || "<body" in lower || "<head" in lower || "<title" in lower || "<h1" in lower
    }

    private fun looksLikeJson(raw: String): Boolean {
        val trimmed = raw.trimStart()
        return trimmed.startsWith("{") || trimmed.startsWith("[")
    }

    private fun looksLikeRawStatus(text: String): Boolean {
        return parseHttpStatus(text) != null || looksLikeHtml(text)
    }

    private fun looksLikeGenericHttpBody(body: String?): Boolean {
        if (body.isNullOrBlank()) return true
        return looksLikeHtml(body) || parseHttpStatus(body) != null
    }

    private fun htmlToText(raw: String): String {
        return raw
            .replace(Regex("(?is)<script\\b.*?</script>"), " ")
            .replace(Regex("(?is)<style\\b.*?</style>"), " ")
            .replace(Regex("(?i)<br\\s*/?>"), "\n")
            .replace(Regex("(?i)</(p|div|h1|h2|h3|center)>"), "\n")
            .replace(Regex("(?is)<[^>]+>"), " ")
            .replace("&nbsp;", " ")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .lines()
            .joinToString(" ") { it.trim() }
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun extractServerSignature(raw: String?): String? {
        if (raw.isNullOrBlank()) return null
        return Regex("""(?i)\b(nginx/[^\s<]+(?:\s*\([^)]+\))?|cloudflare|uvicorn|gunicorn|fastapi)\b""")
            .find(raw)
            ?.value
            ?.trim()
    }

    private fun compactUser(raw: String): String {
        return raw
            .replace(Regex("\\s+"), " ")
            .trim()
            .takeIf { it.isNotBlank() }
            ?.let { if (it.length > 180) it.take(177).trimEnd() + "..." else it }
            ?: "操作失败，请稍后重试"
    }

    private fun compactDeveloper(raw: String?): String? {
        return raw
            ?.replace(Regex("\\s+"), " ")
            ?.trim()
            ?.takeIf { it.isNotBlank() }
            ?.let { if (it.length > 240) it.take(237).trimEnd() + "..." else it }
    }

    private fun List<String?>.joinNonBlank(separator: String): String? {
        return mapNotNull { it?.trim()?.takeIf(String::isNotBlank) }
            .distinct()
            .joinToString(separator)
            .takeIf { it.isNotBlank() }
    }
}

fun formatErrorForDisplay(
    raw: String?,
    fallback: String = "操作失败，请稍后重试",
    developerDetail: String? = null,
    compact: Boolean = false
): String {
    val error = ErrorFormatter.format(raw, fallback, developerDetail)
    return if (compact) error.asSingleLine() else error.asMultiline()
}

fun Throwable.toDisplayError(fallback: String = "操作失败，请稍后重试"): DisplayError {
    return ErrorFormatter.formatThrowable(this, fallback)
}

fun httpErrorForDisplay(
    fallback: String,
    code: Int,
    reason: String? = null,
    body: String? = null
): DisplayError {
    return ErrorFormatter.httpError(fallback, code, reason, body)
}
