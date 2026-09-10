package top.ponychat.companion.overlay

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import top.ponychat.companion.android.DeviceProvisioningPolicy
import top.ponychat.companion.agent.AgentEventListener
import top.ponychat.companion.agent.CompanionExecutionControl
import java.util.concurrent.CountDownLatch
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.TimeUnit

object AgentOverlayController {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArraySet<(AgentOverlayState) -> Unit>()
    private val stateLock = Any()
    private val inputLock = Object()
    private var agentInputLeaseCount = 0
    private val externalAgentInputGenerations = mutableMapOf<String, Long>()
    private var externalAgentInputGeneration = 0L
    private var userInteracting = false
    private val visibilityPolicy = OverlayVisibilityPolicy()

    @Volatile
    var state: AgentOverlayState = AgentOverlayState()
        private set

    fun ensureStarted(context: Context) {
        if (!DeviceProvisioningPolicy.isProvisioned(context)) return
        val appContext = context.applicationContext
        val intent = Intent(appContext, AgentStatusOverlayService::class.java)
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                appContext.startForegroundService(intent)
            } else {
                appContext.startService(intent)
            }
        }.onFailure { error ->
            Log.w(TAG, "Foreground overlay start failed", error)
        }

        // Some vendor Android 12 builds accept startForegroundService() but silently drop the
        // request. Verify that the service really reached onCreate(), then retry through the
        // ordinary start path while our process is foreground-bound to PonyChat.
        mainHandler.postDelayed({
            if (AgentStatusOverlayService.isRunning) return@postDelayed
            runCatching { appContext.startService(intent) }
                .onSuccess { Log.w(TAG, "Overlay start required vendor fallback") }
                .onFailure { error -> Log.e(TAG, "Overlay fallback start failed", error) }
        }, OVERLAY_START_VERIFY_DELAY_MS)
    }

    fun update(context: Context, transform: (AgentOverlayState) -> AgentOverlayState) {
        ensureStarted(context)
        publish(mutateState(transform))
    }

    fun setOverlayVisible(context: Context, visible: Boolean) {
        val next = synchronized(stateLock) {
            visibilityPolicy.hostAllowsOverlay = visible
            state.copy(overlayVisible = visible).also { state = it }
        }
        // Hiding the host's overlay must not start a new foreground UI service.
        publish(next)
        if (visible) ensureStarted(context)
    }

    /**
     * Companion 注入手势的唯一入口。租约存续期间悬浮窗会变为不可触摸，
     * 因此系统输入分发会把注入手势直接交给下层应用。
     */
    fun acquireAgentInput(context: Context, timeoutMs: Long = 1_200): AgentInputLease? {
        ensureStarted(context)
        val deadline = System.currentTimeMillis() + timeoutMs
        synchronized(inputLock) {
            while (userInteracting) {
                val remaining = deadline - System.currentTimeMillis()
                if (remaining <= 0) return null
                inputLock.wait(remaining)
            }
            agentInputLeaseCount += 1
        }
        publish(
            mutateState { it.copy(agentInputActive = true, overlayVisible = true) },
            awaitDelivery = true,
        )
        return AgentInputLease(::releaseAgentInput)
    }

    fun isAgentInputActive(): Boolean = synchronized(inputLock) {
        agentInputLeaseCount > 0 || externalAgentInputGenerations.isNotEmpty()
    }

    fun beginExternalAgentInput(context: Context, token: String, timeoutMs: Long = 8_000) {
        if (token.isBlank()) return
        val generation = synchronized(inputLock) {
            externalAgentInputGeneration += 1
            externalAgentInputGeneration.also { externalAgentInputGenerations[token] = it }
        }
        publish(
            mutateState { it.copy(agentInputActive = true, overlayVisible = true) },
            awaitDelivery = true,
        )
        mainHandler.postDelayed(
            { releaseExternalAgentInput(token, generation) },
            timeoutMs.coerceIn(1_000, 30_000),
        )
        ensureStarted(context)
    }

    fun endExternalAgentInput(token: String, settleMs: Long = 500) {
        val generation = synchronized(inputLock) { externalAgentInputGenerations[token] } ?: return
        mainHandler.postDelayed(
            { releaseExternalAgentInput(token, generation) },
            settleMs.coerceIn(0, 2_000),
        )
    }

    fun pauseForUser(context: Context): Boolean {
        if (!CompanionExecutionControl.pauseByUser()) return false
        update(context) {
            it.copy(
                userPaused = true,
                decisionSummary = "检测到用户触摸，Companion 已暂停操作",
                agentInputActive = false,
            )
        }
        return true
    }

    fun continueAfterUser(context: Context) {
        CompanionExecutionControl.continueTask()
        update(context) {
            it.copy(
                userPaused = false,
                phase = AgentOverlayPhase.OBSERVING,
                decisionSummary = "用户已允许继续，正在重新观察当前界面",
            )
        }
    }

    fun stopAfterUser(context: Context) {
        CompanionExecutionControl.stopTask()
        update(context) {
            it.copy(
                userPaused = false,
                phase = AgentOverlayPhase.FAILED,
                decisionSummary = "用户已停止本次任务",
                action = "",
            )
        }
    }

    internal fun beginUserInteraction(): Boolean = synchronized(inputLock) {
        if (agentInputLeaseCount > 0 || externalAgentInputGenerations.isNotEmpty()) {
            return@synchronized false
        }
        userInteracting = true
        true
    }

    internal fun endUserInteraction() {
        synchronized(inputLock) {
            userInteracting = false
            inputLock.notifyAll()
        }
    }

    internal fun subscribe(listener: (AgentOverlayState) -> Unit) {
        listeners += listener
        listener(state)
    }

    internal fun unsubscribe(listener: (AgentOverlayState) -> Unit) {
        listeners -= listener
    }

    private fun releaseAgentInput() {
        val inactive = synchronized(inputLock) {
            agentInputLeaseCount = (agentInputLeaseCount - 1).coerceAtLeast(0)
            agentInputLeaseCount == 0 && externalAgentInputGenerations.isEmpty()
        }
        if (inactive) publish(mutateState { it.copy(agentInputActive = false) })
    }

    private fun releaseExternalAgentInput(token: String, generation: Long) {
        val inactive = synchronized(inputLock) {
            if (externalAgentInputGenerations[token] != generation) return@synchronized false
            externalAgentInputGenerations.remove(token)
            agentInputLeaseCount == 0 && externalAgentInputGenerations.isEmpty()
        }
        if (inactive) publish(mutateState { it.copy(agentInputActive = false) })
    }

    private fun mutateState(transform: (AgentOverlayState) -> AgentOverlayState): AgentOverlayState =
        synchronized(stateLock) {
            visibilityPolicy.apply(transform(state)).also { state = it }
        }

    private fun publish(next: AgentOverlayState, awaitDelivery: Boolean = false) {
        // A queued task event must not undo a newer host-foreground visibility change.
        val deliver = { if (next == state) listeners.forEach { it(next) } }
        if (Looper.myLooper() == Looper.getMainLooper()) {
            deliver()
            return
        }
        if (!awaitDelivery) {
            mainHandler.post(deliver)
            return
        }
        val delivered = CountDownLatch(1)
        mainHandler.post {
            deliver()
            delivered.countDown()
        }
        delivered.await(500, TimeUnit.MILLISECONDS)
    }

    private const val TAG = "AgentOverlayController"
    private const val OVERLAY_START_VERIFY_DELAY_MS = 350L
}

class AgentInputLease internal constructor(private val release: () -> Unit) : AutoCloseable {
    private var closed = false

    override fun close() {
        if (closed) return
        closed = true
        release()
    }
}

class OverlayAgentEventListener(private val context: Context) : AgentEventListener {
    override fun onEvent(message: String) {
        val safe = AgentOverlayPresentation.safeSummary(message)
        AgentOverlayController.update(context) { previous ->
            when {
                message.startsWith("任务开始：") -> previous.copy(
                    goal = AgentOverlayPresentation.safeSummary(
                        message.substringAfter("任务开始：").substringBefore("｜"),
                    ),
                    decisionSummary = "正在分析任务并建立执行计划",
                    phase = AgentOverlayPhase.OBSERVING,
                    currentStep = 1,
                    totalSteps = Regex("最多(\\d+)步").find(message)
                        ?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0,
                    action = "",
                    verification = "",
                    userPaused = false,
                    overlayVisible = true,
                )
                message.startsWith("任务 ") && "开始" in message -> previous.copy(
                    goal = safe.substringAfter("任务 ").substringBefore(" 开始"),
                    decisionSummary = "正在分析任务并建立执行计划",
                    phase = AgentOverlayPhase.OBSERVING,
                    currentStep = 1,
                    action = "",
                    verification = "",
                    userPaused = false,
                    overlayVisible = true,
                )
                "已观察当前界面" in message -> previous.copy(
                    phase = AgentOverlayPhase.OBSERVING,
                    currentStep = stepNumber(message) ?: previous.currentStep,
                    decisionSummary = "已读取前台应用、UI 元素和当前状态",
                )
                "决策：" in message -> previous.copy(
                    phase = AgentOverlayPhase.DECIDING,
                    currentStep = stepNumber(message) ?: previous.currentStep,
                    decisionSummary = AgentOverlayPresentation.safeSummary(message.substringAfter("决策：")),
                )
                "执行：" in message -> previous.copy(
                    phase = AgentOverlayPhase.EXECUTING,
                    action = AgentOverlayPresentation.safeSummary(message.substringAfter("执行：")),
                )
                "验证：" in message -> {
                    val feedback = AgentOverlayPresentation.safeSummary(message.substringAfter("验证："))
                    previous.copy(
                        phase = if ("未" in feedback || "失败" in feedback) {
                            AgentOverlayPhase.RECOVERING
                        } else {
                            AgentOverlayPhase.VERIFYING
                        },
                        verification = feedback,
                    )
                }
                message.startsWith("任务失败") -> previous.copy(
                    phase = AgentOverlayPhase.FAILED,
                    decisionSummary = safe,
                )
                message.startsWith("任务完成：") -> previous.copy(
                    phase = AgentOverlayPhase.COMPLETED,
                    decisionSummary = AgentOverlayPresentation.safeSummary(
                        message.substringAfter("任务完成："),
                    ),
                )
                message.startsWith("任务停止：") -> previous.copy(
                    phase = AgentOverlayPhase.FAILED,
                    decisionSummary = AgentOverlayPresentation.safeSummary(
                        message.substringAfter("任务停止："),
                    ),
                )
                else -> previous.copy(decisionSummary = safe)
            }
        }
    }

    private fun stepNumber(message: String): Int? =
        Regex("^\\[(\\d+)]").find(message)?.groupValues?.getOrNull(1)?.toIntOrNull()
}
