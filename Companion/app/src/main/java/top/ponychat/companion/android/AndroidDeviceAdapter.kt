package top.ponychat.companion.android

import android.content.Context
import android.content.Intent
import top.ponychat.companion.agent.AgentAction
import top.ponychat.companion.agent.ActionTarget
import top.ponychat.companion.agent.DeviceAdapter
import top.ponychat.companion.agent.ExecutionResult
import top.ponychat.companion.agent.NoOpVisionLocator
import top.ponychat.companion.agent.Observation
import top.ponychat.companion.agent.VisionLocator
import top.ponychat.companion.overlay.AgentOverlayController
import java.util.concurrent.atomic.AtomicLong

class AndroidDeviceAdapter(
    private val context: Context,
    private val visionLocator: VisionLocator = NoOpVisionLocator,
) : DeviceAdapter {
    override val adapterName: String = "AndroidAccessibilityAdapter"
    private val fallbackSequence = AtomicLong()

    override fun observe(): Observation = CompanionAccessibilityService.instance?.observe()
        ?: Observation(
            sequence = fallbackSequence.incrementAndGet(),
            notes = mapOf("error" to "AccessibilityService 尚未启用"),
        )

    override fun execute(action: AgentAction): ExecutionResult {
        if (action is AgentAction.LaunchApp) return launchApp(action.packageName)
        val service = CompanionAccessibilityService.instance
            ?: return ExecutionResult(false, "AccessibilityService 尚未启用")
        if (action is AgentAction.Tap && action.target is ActionTarget.Visual) {
            val visualTarget = action.target
            val coordinate = visionLocator.locate(observe(), visualTarget.label)
                ?: return ExecutionResult(false, "视觉目标 ${visualTarget.label} 定位失败")
            return executeInjectedGesture(service, AgentAction.Tap(coordinate))
        }
        if (action is AgentAction.Tap || action is AgentAction.Swipe) {
            return executeInjectedGesture(service, action)
        }
        return service.execute(action)
    }

    private fun executeInjectedGesture(
        service: CompanionAccessibilityService,
        action: AgentAction,
    ): ExecutionResult {
        val lease = AgentOverlayController.acquireAgentInput(context)
            ?: return ExecutionResult(false, "用户正在操作 Companion 悬浮窗，稍后重试")
        return try {
            service.execute(action)
        } finally {
            lease.close()
        }
    }

    private fun launchApp(packageName: String): ExecutionResult {
        val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: return ExecutionResult(false, "未安装 $packageName 或没有启动入口")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return ExecutionResult(true, "已启动 $packageName")
    }
}
