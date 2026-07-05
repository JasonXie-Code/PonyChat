package top.ponychat.webview.data.api

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import top.ponychat.webview.data.prefs.AppPreferences

data class NetworkQualityState(
    val quality: String = "unknown", // good | poor | bad | unknown
    val pingMs: Long? = null,
    val routeMode: String = "wan",
    val activeBase: String = "",
    val networkType: String = "未知",
    val lastUpdatedAt: Long = 0L
)

object NetworkQualityCenter {
    private const val TAG = "NetworkQualityCenter"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _state = MutableStateFlow(NetworkQualityState())
    val state: StateFlow<NetworkQualityState> = _state.asStateFlow()

    @Volatile
    private var started = false
    private var loopJob: Job? = null

    fun start(prefs: AppPreferences) {
        if (started) return
        started = true
        SmartRouteManager.init(prefs)
        loopJob = scope.launch {
            while (true) {
                runCatching { testNow(prefs) }
                delay(30_000)
            }
        }
    }

    suspend fun testNow(prefs: AppPreferences): NetworkQualityState {
        val startedAt = System.currentTimeMillis()
        val active = SmartRouteManager.activeBase(prefs)
        val result = runCatching {
            NetworkClient.createDirectApiService(
                baseUrl = active,
                connectTimeoutMs = 6_000L,
                readTimeoutMs = 8_000L
            ).getStatus()
        }
        val elapsed = System.currentTimeMillis() - startedAt
        val netType = "公网"
        val next = if (result.isSuccess && result.getOrNull()?.isSuccessful == true) {
            val q = when {
                elapsed < 120 -> "good"
                elapsed < 500 -> "poor"
                else -> "bad"
            }
            NetworkQualityState(
                quality = q,
                pingMs = elapsed,
                routeMode = prefs.routeMode,
                activeBase = active,
                networkType = netType,
                lastUpdatedAt = System.currentTimeMillis()
            )
        } else {
            val fallback = SmartRouteManager.onRequestFailure(prefs, active)
            if (!fallback.isNullOrBlank()) {
                Log.i(TAG, "Probe failed, switched to fallback: $fallback")
            }
            NetworkQualityState(
                quality = "bad",
                pingMs = null,
                routeMode = prefs.routeMode,
                activeBase = SmartRouteManager.activeBase(prefs),
                networkType = netType,
                lastUpdatedAt = System.currentTimeMillis()
            )
        }
        _state.value = next
        return next
    }
}
