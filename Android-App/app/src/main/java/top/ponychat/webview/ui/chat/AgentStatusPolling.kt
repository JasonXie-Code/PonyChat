package top.ponychat.webview.ui.chat

import android.os.SystemClock
import androidx.compose.runtime.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import top.ponychat.webview.data.api.ApiService
import top.ponychat.webview.data.model.AgentRunStatus

internal data class AgentStatusScope(
    val username: String,
    val baseUrl: String,
    val characterId: String,
    val mode: String,
    val conversationId: String?,
)

internal data class AgentStatusSnapshot(
    val agent: AgentRunStatus?,
    val notice: String?,
    val elapsedMs: Long,
    val agents: List<AgentRunStatus> = emptyList(),
    val elapsedSinceReceivedMs: Long = 0L,
)

/** One request loop per visible conversation; recomposition must not restart it. */
@Composable
internal fun rememberAgentStatus(
    scope: AgentStatusScope,
    lifecycleOwner: LifecycleOwner,
    api: ApiService,
): AgentStatusSnapshot {
    var agent by remember(scope) { mutableStateOf<AgentRunStatus?>(null) }
    var agents by remember(scope) { mutableStateOf<List<AgentRunStatus>>(emptyList()) }
    var notice by remember(scope) { mutableStateOf<String?>("正在读取运行状态…") }
    var receivedAt by remember(scope) { mutableLongStateOf(0L) }
    var now by remember(scope) { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    // Retrofit 2.11 service proxies have non-reflexive equals(). Using api as
    // an effect key cancels/restarts requests whenever a response or clock tick
    // recomposes this function, bypassing the polling delay and causing storms.
    LaunchedEffect(scope, lifecycleOwner) {
        if (scope.username.isBlank() || scope.characterId.isBlank()) {
            notice = "登录并选择角色后可查看运行状态"
            return@LaunchedEffect
        }
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch {
                while (isActive) {
                    now = SystemClock.elapsedRealtime()
                    delay(1000)
                }
            }
            while (isActive) {
                try {
                    val response = withTimeout(5000) {
                        api.getAgentStatus(scope.characterId, scope.mode, scope.conversationId)
                    }
                    val body = response.body()
                    if (response.isSuccessful && body?.success == true) {
                        agent = body.agent
                        agents = body.agents.ifEmpty { listOfNotNull(body.agent) }
                        receivedAt = SystemClock.elapsedRealtime()
                        now = receivedAt
                        notice = null
                    } else {
                        notice = when (response.code()) {
                            401 -> "登录已失效，请重新登录"
                            404 -> "服务器尚未支持 Agent 状态展示"
                            else -> "暂时无法刷新运行状态"
                        }
                    }
                } catch (_: TimeoutCancellationException) {
                    notice = "状态读取超时，正在重试"
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    notice = "暂时无法连接服务器，正在重试"
                }
                delay(if (agents.any { it.status == "running" }) 1000 else 3000)
            }
        }
    }
    val running = agent?.status == "running" && notice == null
    val elapsed = (agent?.elapsedMs ?: 0L) + if (running) (now - receivedAt).coerceAtLeast(0L) else 0L
    return AgentStatusSnapshot(agent, notice, elapsed, agents,
        if (notice == null) (now - receivedAt).coerceAtLeast(0L) else 0L)
}
