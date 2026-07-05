package top.ponychat.webview.data.api

import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.*
import top.ponychat.webview.data.prefs.AppPreferences
import java.net.URL

data class RouteState(
    val mode: String = "auto",
    val activeBase: String = "",
    val lanBase: String = "",
    val wanBase: String = "",
    val lastSwitchAt: Long = 0L,
    val recommendation: String? = null // 网络连接模式切换时的建议内容
)

object SmartRouteManager {
    private const val TAG = "SmartRouteManager"
    private const val AUTO_SWITCH_COOLDOWN_MS = 12_000L
    private val _state = MutableStateFlow(RouteState())
    val state: StateFlow<RouteState> = _state.asStateFlow()

    @Volatile
    private var initialized = false

    fun init(prefs: AppPreferences) {
        if (initialized) return
        initialized = true
        refreshFromPrefs(prefs)
    }

    fun refreshFromPrefs(prefs: AppPreferences) {
        val active = prefs.effectiveApiBase()
        prefs.activeApiBase = active
        _state.value = RouteState(
            mode = "wan",
            activeBase = active,
            lanBase = "",
            wanBase = active,
            lastSwitchAt = System.currentTimeMillis()
        )
    }

    /** 检测固定公网连接质量。 */
    fun runDiagnostic(prefs: AppPreferences, onComplete: () -> Unit = {}) {
        val candidates = listOf(AppPreferences.DEFAULT_WAN_URL)
        _state.value = _state.value.copy(recommendation = "正在检测公网连接...")

        MainScope().launch(Dispatchers.IO) {
            if (candidates.isEmpty()) {
                _state.value = _state.value.copy(recommendation = "未配置地址，请先在设置中填写服务器地址。")
                withContext(Dispatchers.Main) { onComplete() }
                return@launch
            }

            val results = candidates.map { base ->
                base to async { testConnection(base) }
            }.map { (base, def) -> base to def.await() }

            val successResults = results.filter { it.second.isSuccess }.map { (base, res) -> base to res.ping }
            val best = successResults.minByOrNull { it.second }

            val rec = when {
                best != null && successResults.size > 1 -> {
                    val label = urlToLabel(best.first)
                    "当前最快：$label (${best.second}ms)，已自动选用。"
                }
                best != null -> {
                    val label = urlToLabel(best.first)
                    "连接正常：$label (${best.second}ms)。"
                }
                else -> "公网连接失败，请检查网络或稍后再试。"
            }

            if (best != null) {
                switchTo(prefs, best.first, "diagnostic_wan")
            }

            _state.value = _state.value.copy(recommendation = rec)
            withContext(Dispatchers.Main) { onComplete() }
        }
    }

    private fun buildSpeedTestCandidates(prefs: AppPreferences): List<String> {
        return listOf(AppPreferences.DEFAULT_WAN_URL)
    }

    private fun urlToLabel(baseUrl: String): String {
        return try {
            URL(baseUrl).host
        } catch (_: Exception) {
            baseUrl
        }
    }

    private data class TestResult(val isSuccess: Boolean, val ping: Long)

    private suspend fun testConnection(baseUrl: String): TestResult {
        val start = System.currentTimeMillis()
        return try {
            val api = NetworkClient.createDirectApiService(baseUrl)
            val resp = api.getStatus()
            if (resp.isSuccessful) TestResult(true, System.currentTimeMillis() - start)
            else TestResult(false, 9999)
        } catch (e: Exception) {
            top.ponychat.webview.util.DebugLog.w("SmartRoute", "testConnection failed for $baseUrl: ${e.message}", e)
            TestResult(false, 9999)
        }
    }

    /** 前台/网络恢复时清理旧连接池并探测固定公网。 */
    suspend fun recoverAfterNetworkResume(prefs: AppPreferences, reason: String) {
        refreshFromPrefs(prefs)
        NetworkClient.resetConnectionPools("resume:$reason")
        val active = prefs.effectiveApiBase()
        if (active.isBlank()) return

        val activeResult = testConnection(active)
        if (activeResult.isSuccess) {
            Log.i(TAG, "resume route ok: $active (${activeResult.ping}ms), reason=$reason")
            return
        }
        Log.w(TAG, "resume public route probe failed: active=$active reason=$reason")
    }

    fun activeBase(prefs: AppPreferences): String {
        val current = _state.value.activeBase
        if (current.isNotBlank()) return current
        refreshFromPrefs(prefs)
        return _state.value.activeBase
    }

    fun rewriteUrlToActive(inputUrl: String, prefs: AppPreferences): String {
        val active = activeBase(prefs).takeIf { it.isNotBlank() } ?: return inputUrl
        return try {
            val src = URL(inputUrl)
            val dst = URL(active)
            URL(dst.protocol, dst.host, dst.port, src.file).toString()
        } catch (e: Exception) {
            top.ponychat.webview.util.DebugLog.w("SmartRoute", "rewriteUrlToActive failed: ${e.message}", e)
            inputUrl
        }
    }

    fun onRequestFailure(prefs: AppPreferences, failedBase: String? = null, force: Boolean = false): String? {
        return null
    }

    fun switchTo(prefs: AppPreferences, nextBase: String, reason: String) {
        val next = prefs.effectiveApiBase()
        if (next.isBlank()) return
        val cur = _state.value.activeBase
        if (cur == next) return
        prefs.activeApiBase = next
        _state.value = _state.value.copy(
            activeBase = next,
            mode = "wan",
            lanBase = "",
            wanBase = next,
            lastSwitchAt = System.currentTimeMillis()
        )
        NetworkClient.resetConnectionPools("route_switch:$reason")
        Log.i(TAG, "Switched route: $cur -> $next, reason=$reason")
    }
}
