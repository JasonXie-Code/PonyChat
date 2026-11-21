package top.ponychat.webview.data.repo

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.XiangqiExecuteRequest
import top.ponychat.webview.data.model.XiangqiExecuteResponse
import top.ponychat.webview.data.model.XiangqiMemoryCommitRequest
import top.ponychat.webview.data.model.XiangqiPrepareRequest
import top.ponychat.webview.data.model.XiangqiPrepareResponse
import top.ponychat.webview.data.prefs.AppPreferences

class MinigameRepository(private val prefs: AppPreferences) {
    private fun api() = NetworkClient.createApiService(prefs)

    suspend fun prepareXiangqi(request: XiangqiPrepareRequest): Result<XiangqiPrepareResponse> =
        withContext(Dispatchers.IO) {
            runCatching {
                val response = api().prepareXiangqi(request)
                if (!response.isSuccessful) {
                    val error = response.errorBody()?.string()?.takeIf { it.isNotBlank() }
                    throw IllegalStateException(error ?: "准备步骤失败 (${response.code()})")
                }
                response.body() ?: throw IllegalStateException("准备步骤返回为空")
            }
        }

    suspend fun executeXiangqi(request: XiangqiExecuteRequest): Result<XiangqiExecuteResponse> =
        withContext(Dispatchers.IO) {
            runCatching {
                val response = api().executeXiangqi(request)
                if (!response.isSuccessful) {
                    val error = response.errorBody()?.string()?.takeIf { it.isNotBlank() }
                    throw IllegalStateException(error ?: "执行步骤失败 (${response.code()})")
                }
                response.body() ?: throw IllegalStateException("执行步骤返回为空")
            }
        }

    suspend fun commitXiangqiMemory(request: XiangqiMemoryCommitRequest): Result<Map<String, Any?>> =
        withContext(Dispatchers.IO) {
            runCatching {
                val response = api().commitXiangqiMemory(request)
                if (!response.isSuccessful) {
                    val error = response.errorBody()?.string()?.takeIf { it.isNotBlank() }
                    throw IllegalStateException(error ?: "象棋记忆写回失败 (${response.code()})")
                }
                response.body() ?: emptyMap()
            }
        }
}
