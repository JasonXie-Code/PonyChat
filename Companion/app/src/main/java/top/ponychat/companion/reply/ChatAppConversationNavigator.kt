package top.ponychat.companion.reply

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityNodeInfo
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.overlay.AgentOverlayController
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Returns a supported chat app from a conversation detail page to its conversation list. */
class ChatAppConversationNavigator(
    private val service: CompanionAccessibilityService,
) {
    data class AppSpec(
        val packageName: String,
        val editorViewIds: List<String>,
        val backViewIds: List<String>,
    )

    data class Result(val success: Boolean, val detail: String)

    fun returnToConversationList(app: AppSpec): Result {
        val lease = AgentOverlayController.acquireAgentInput(service)
            ?: return Result(false, "用户正在操作 Companion 悬浮窗")
        return try {
            val before = snapshot() ?: return Result(false, "无法读取当前界面")
            if (before.packageName?.toString() != app.packageName) {
                return Result(true, "聊天软件不在前台，无需返回会话列表")
            }
            if (!isConversationDetail(before, app)) {
                return Result(true, "已位于聊天软件的会话列表")
            }

            repeat(MAX_BACK_ATTEMPTS) {
                val root = snapshot() ?: return@repeat
                val explicitBack = app.backViewIds
                    .asSequence()
                    .flatMap { root.findAccessibilityNodeInfosByViewId(it).asSequence() }
                    .firstOrNull { it.isEnabled && it.isClickable }
                    ?: findNodes(root).firstOrNull {
                        it.isEnabled && it.isClickable &&
                            it.contentDescription?.toString().orEmpty().startsWith("返回")
                    }
                val submitted = explicitBack?.let(::click) ?: onMainThread {
                    service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                }
                if (!submitted) return Result(false, "聊天详情页返回操作失败")

                val after = waitForRoot(NAVIGATION_TIMEOUT_MS) { candidate ->
                    candidate.packageName?.toString() != app.packageName ||
                        !isConversationDetail(candidate, app)
                } ?: return@repeat
                if (after.packageName?.toString() != app.packageName) {
                    return Result(false, "返回操作离开了聊天软件，未停留在会话列表")
                }
                return Result(true, "已返回聊天软件会话列表")
            }
            Result(false, "发送完成，但仍停留在聊天详情页")
        } finally {
            lease.close()
        }
    }

    private fun isConversationDetail(root: AccessibilityNodeInfo, app: AppSpec): Boolean {
        val nodes = findNodes(root)
        val hasKnownEditor = app.editorViewIds.any {
            root.findAccessibilityNodeInfosByViewId(it).isNotEmpty()
        }
        val hasSemanticEditor = nodes.any { it.isEditable && it.isEnabled }
        val hasSemanticBack = nodes.any {
            it.isEnabled && it.isClickable &&
                it.contentDescription?.toString().orEmpty().startsWith("返回")
        }
        return ChatAppConversationNavigationPolicy.isConversationDetail(
            hasKnownEditor = hasKnownEditor,
            hasSemanticEditor = hasSemanticEditor,
            hasSemanticBack = hasSemanticBack,
        )
    }

    private fun snapshot(): AccessibilityNodeInfo? = onMainThread { service.rootInActiveWindow }

    private fun waitForRoot(
        timeoutMs: Long,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): AccessibilityNodeInfo? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            Thread.sleep(POLL_INTERVAL_MS)
            val root = snapshot() ?: continue
            if (predicate(root)) return root
        }
        return null
    }

    private fun click(node: AccessibilityNodeInfo): Boolean = onMainThread {
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    private fun findNodes(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val result = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            result += node
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        visit(root)
        return result
    }

    private fun <T> onMainThread(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return block()
        var value: kotlin.Result<T>? = null
        val latch = CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            value = runCatching(block)
            latch.countDown()
        }
        check(latch.await(MAIN_THREAD_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
            "等待无障碍主线程超时"
        }
        return checkNotNull(value).getOrThrow()
    }

    companion object {
        val QQ = AppSpec(
            packageName = "com.tencent.mobileqq",
            editorViewIds = listOf("com.tencent.mobileqq:id/input"),
            backViewIds = listOf("com.tencent.mobileqq:id/ivTitleBtnLeft"),
        )
        val WECHAT = AppSpec(
            packageName = "com.tencent.mm",
            // WeChat resource IDs change frequently; use editable + semantic back detection.
            editorViewIds = emptyList(),
            backViewIds = emptyList(),
        )

        private const val MAX_BACK_ATTEMPTS = 2
        private const val POLL_INTERVAL_MS = 150L
        private const val NAVIGATION_TIMEOUT_MS = 3_000L
        private const val MAIN_THREAD_TIMEOUT_MS = 3_000L
    }
}

internal object ChatAppConversationNavigationPolicy {
    fun isConversationDetail(
        hasKnownEditor: Boolean,
        hasSemanticEditor: Boolean,
        hasSemanticBack: Boolean,
    ): Boolean = hasKnownEditor || (hasSemanticEditor && hasSemanticBack)
}
