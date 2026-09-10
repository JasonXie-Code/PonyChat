package top.ponychat.webview.data.repo

import top.ponychat.webview.util.DebugLog
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.*
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.util.ErrorFormatter
import top.ponychat.webview.util.UserFacingException
import top.ponychat.webview.util.httpErrorForDisplay

class AuthRepository(private val prefs: AppPreferences) {

    private val TAG = "AuthRepository"

    private fun api() = NetworkClient.createApiService(prefs)

    suspend fun login(username: String, password: String): Result<LoginResponse> {
        return runCatching {
            val resp = api().login(LoginRequest(username, password))
            if (resp.isSuccessful) {
                val body = resp.body()
                if (body?.success == true) {
                    body
                } else {
                    throw UserFacingException(body?.message ?: "登录失败")
                }
            } else if (resp.code() == 426) {
                throw UserFacingException("当前版本已停止支持，请前往官网下载最新版 PonyChat")
            } else {
                val errBody = resp.errorBody()?.string()
                val msg = authFormErrorMessage(
                    fallback = "登录失败，请稍后重试",
                    code = resp.code(),
                    body = errBody,
                    unauthorizedFallback = "用户名或密码错误"
                )
                throw UserFacingException(msg)
            }
        }.also { result ->
            result.exceptionOrNull()?.let { e ->
                DebugLog.w(TAG, "Login failed: ${e.message}", e)
            }
        }
    }

    suspend fun register(
        username: String,
        password: String,
        gender: String,
        birthDate: String,
        inviteCode: String,
        avatar: String? = null
    ): Result<Unit> {
        return runCatching {
            val resp = api().register(
                RegisterRequest(
                    username = username,
                    password = password,
                    gender = gender,
                    birthDate = birthDate,
                    inviteCode = inviteCode,
                    avatar = avatar
                )
            )
            if (resp.isSuccessful) {
                val body = resp.body()
                if (body?.success == true) Unit
                else throw UserFacingException(body?.message ?: "注册失败")
            } else {
                val errBody = resp.errorBody()?.string()
                val msg = authFormErrorMessage(
                    fallback = "注册失败，请稍后重试",
                    code = resp.code(),
                    body = errBody
                )
                throw UserFacingException(msg)
            }
        }
    }

    suspend fun getProfile(username: String): Result<ProfileData> {
        return runCatching {
            val resp = api().getProfile(username)
            if (resp.isSuccessful) {
                resp.body()?.profile ?: throw Exception("获取资料失败")
            } else {
                throw Exception("获取资料失败 (${resp.code()})")
            }
        }
    }

    suspend fun getUserUsage(username: String): Result<Map<String, Any>> {
        return runCatching {
            val resp = api().getUserUsage(username)
            if (resp.isSuccessful) {
                val body = resp.body() ?: emptyMap<String, Any>()
                @Suppress("UNCHECKED_CAST")
                (body["usage"] as? Map<String, Any>) ?: body
            } else {
                throw Exception("获取用量失败 (${resp.code()})")
            }
        }
    }

    suspend fun getUserQuota(username: String): Result<Map<String, Any>> {
        return runCatching {
            val resp = api().getUserQuota(username)
            if (resp.isSuccessful) {
                resp.body() ?: emptyMap()
            } else {
                throw Exception("获取配额失败 (${resp.code()})")
            }
        }
    }

    suspend fun discoverLanUrl() {
        // 兼容旧调用点：正式连接使用 AppPreferences 中的 Server-CN IP 入口。
    }

    private fun parseErrorMessage(errorBody: String?): String? {
        if (errorBody.isNullOrBlank()) return null
        return ErrorFormatter.format(errorBody).asSingleLine()
    }

    private fun authFormErrorMessage(
        fallback: String,
        code: Int,
        body: String?,
        unauthorizedFallback: String? = null
    ): String {
        val parsed = parseErrorMessage(body)
            ?.takeUnless { code == 401 && unauthorizedFallback != null && it.isGenericUnauthorizedMessage() }
        if (!parsed.isNullOrBlank()) return parsed
        if (code == 401 && unauthorizedFallback != null) return unauthorizedFallback
        return httpErrorForDisplay(fallback, code, body = body).userMessage
    }

    private fun String.isGenericUnauthorizedMessage(): Boolean {
        return contains("HTTP 401", ignoreCase = true) ||
            contains("Unauthorized", ignoreCase = true) ||
            contains("登录已过期")
    }
}
