package top.ponychat.companion.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import top.ponychat.companion.agent.ActionTarget
import top.ponychat.companion.agent.AgentAction
import top.ponychat.companion.agent.ExecutionResult
import top.ponychat.companion.agent.Observation
import top.ponychat.companion.agent.UiNode
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import top.ponychat.companion.overlay.AgentOverlayController
import top.ponychat.companion.reply.QqForegroundReplyController

class CompanionAccessibilityService : AccessibilityService() {
    private lateinit var qqForegroundReplyController: QqForegroundReplyController

    override fun onServiceConnected() {
        instance = this
        AgentOverlayController.ensureStarted(this)
        qqForegroundReplyController = QqForegroundReplyController(this)
        qqForegroundReplyController.onServiceConnected()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType == AccessibilityEvent.TYPE_TOUCH_INTERACTION_START &&
            !AgentOverlayController.isAgentInputActive()
        ) {
            if (::qqForegroundReplyController.isInitialized) {
                qqForegroundReplyController.onUserInteraction()
            }
            AgentOverlayController.pauseForUser(this)
        }
        if (::qqForegroundReplyController.isInitialized && event != null) {
            qqForegroundReplyController.onAccessibilityEvent(event)
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (::qqForegroundReplyController.isInitialized) qqForegroundReplyController.close()
        if (instance === this) instance = null
        super.onDestroy()
    }

    fun observe(): Observation {
        val nodes = mutableListOf<UiNode>()
        rootInActiveWindow?.let { collectNodes(it, nodes) }
        return Observation(
            sequence = observationSequence.incrementAndGet(),
            foregroundPackage = rootInActiveWindow?.packageName?.toString(),
            uiNodes = nodes,
            screenshotAvailable = false,
            notes = mapOf("source" to "AccessibilityService"),
        )
    }

    fun execute(action: AgentAction): ExecutionResult = when (action) {
        is AgentAction.Tap -> tap(action.target)
        is AgentAction.Swipe -> swipe(action)
        is AgentAction.InputText -> inputText(action.target, action.text)
        AgentAction.Back -> globalAction(GLOBAL_ACTION_BACK, "返回")
        AgentAction.Home -> globalAction(GLOBAL_ACTION_HOME, "主页")
        is AgentAction.Wait -> {
            Thread.sleep(action.durationMs.coerceIn(0, 2_000))
            ExecutionResult(true, "等待 ${action.durationMs.coerceIn(0, 2_000)}ms")
        }
        is AgentAction.NoOp -> ExecutionResult(true, "跳过：${action.reason}")
        is AgentAction.LaunchApp -> ExecutionResult(false, "启动 App 由 AndroidDeviceAdapter 处理")
    }

    private fun tap(target: ActionTarget): ExecutionResult = when (target) {
        is ActionTarget.Semantic -> {
            val node = findNode(target)
            val clickable = generateSequence(node) { it.parent }.firstOrNull { it.isClickable }
            val success = clickable?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
            ExecutionResult(success, if (success) "语义节点点击成功" else "未找到可点击的语义节点")
        }
        is ActionTarget.Coordinate -> dispatchTap(target.x, target.y)
        is ActionTarget.Visual -> ExecutionResult(
            false,
            "视觉目标 ${target.label} 尚未定位；请接入 VisionLocator 后转为坐标目标",
        )
    }

    private fun inputText(target: ActionTarget.Semantic, text: String): ExecutionResult {
        val node = findNode(target)
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val success = node?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments) == true
        return ExecutionResult(success, if (success) "文本输入成功" else "未找到可编辑语义节点")
    }

    private fun swipe(action: AgentAction.Swipe): ExecutionResult {
        val path = Path().apply {
            moveTo(action.startX.toFloat(), action.startY.toFloat())
            lineTo(action.endX.toFloat(), action.endY.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, action.durationMs))
            .build()
        return dispatchGestureAndAwait(gesture, "坐标滑动")
    }

    private fun dispatchTap(x: Int, y: Int): ExecutionResult {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 80))
            .build()
        return dispatchGestureAndAwait(gesture, "坐标点击")
    }

    private fun dispatchGestureAndAwait(
        gesture: GestureDescription,
        label: String,
    ): ExecutionResult {
        val completed = CountDownLatch(1)
        var succeeded = false
        val callback = object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                succeeded = true
                completed.countDown()
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                AgentOverlayController.pauseForUser(this@CompanionAccessibilityService)
                completed.countDown()
            }
        }
        val accepted = dispatchGesture(gesture, callback, Handler(Looper.getMainLooper()))
        if (!accepted) return ExecutionResult(false, "$label 提交失败")
        val callbackReceived = completed.await(2, TimeUnit.SECONDS)
        return ExecutionResult(
            callbackReceived && succeeded,
            when {
                !callbackReceived -> "$label 等待系统确认超时"
                succeeded -> "$label 已完成"
                else -> "$label 被用户触摸中断，Companion 已暂停"
            },
        )
    }

    private fun globalAction(action: Int, label: String): ExecutionResult {
        val success = performGlobalAction(action)
        return ExecutionResult(success, if (success) "$label 操作成功" else "$label 操作失败")
    }

    private fun findNode(target: ActionTarget.Semantic): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        target.viewId?.let { viewId ->
            root.findAccessibilityNodeInfosByViewId(viewId).firstOrNull()?.let { return it }
        }
        return findNodeRecursively(root) { node ->
            (target.text != null && node.text?.toString() == target.text) ||
                (target.contentDescription != null &&
                    node.contentDescription?.toString() == target.contentDescription)
        }
    }

    private fun findNodeRecursively(
        node: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): AccessibilityNodeInfo? {
        if (predicate(node)) return node
        for (index in 0 until node.childCount) {
            val child = node.getChild(index) ?: continue
            findNodeRecursively(child, predicate)?.let { return it }
        }
        return null
    }

    private fun collectNodes(node: AccessibilityNodeInfo, result: MutableList<UiNode>) {
        result += UiNode(
            id = node.viewIdResourceName,
            text = node.text?.toString(),
            contentDescription = node.contentDescription?.toString(),
            className = node.className?.toString(),
            clickable = node.isClickable,
            editable = node.isEditable,
        )
        for (index in 0 until node.childCount) {
            node.getChild(index)?.let { collectNodes(it, result) }
        }
    }

    companion object {
        @Volatile
        var instance: CompanionAccessibilityService? = null
            private set

        private val observationSequence = AtomicLong()
    }
}
