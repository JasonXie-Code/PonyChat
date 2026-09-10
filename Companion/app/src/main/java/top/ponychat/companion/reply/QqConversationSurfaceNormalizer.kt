package top.ponychat.companion.reply

import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityNodeInfo
import top.ponychat.companion.android.CompanionAccessibilityService
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Converts QQ's ScaleAIO notification card into the normal full-screen conversation. */
class QqConversationSurfaceNormalizer(
    private val service: CompanionAccessibilityService,
) {
    data class Result(
        val success: Boolean,
        val changed: Boolean,
        val detail: String,
    )

    fun expandIfNeeded(root: AccessibilityNodeInfo): Result {
        if (root.packageName?.toString() != QQ_PACKAGE) {
            return Result(true, false, "QQ 不在前台")
        }
        val expand = findNodes(root).firstOrNull { node ->
            QqScaledConversationPolicy.isExpandControl(
                contentDescription = node.contentDescription?.toString().orEmpty(),
                enabled = node.isEnabled,
                clickable = node.isClickable,
            )
        } ?: return Result(true, false, "QQ 已是普通全屏会话")

        if (!onMainThread { expand.performAction(AccessibilityNodeInfo.ACTION_CLICK) }) {
            return Result(false, false, "QQ 半屏会话的全屏按钮点击失败")
        }
        val expanded = waitForRoot(EXPAND_TIMEOUT_MS) { candidate ->
            candidate.packageName?.toString() == QQ_PACKAGE &&
                findNodes(candidate).none { node ->
                    QqScaledConversationPolicy.isExpandControl(
                        contentDescription = node.contentDescription?.toString().orEmpty(),
                        enabled = node.isEnabled,
                        clickable = node.isClickable,
                    )
                }
        }
        return if (expanded != null) {
            Result(true, true, "已将 QQ 半屏会话展开为全屏")
        } else {
            Result(false, true, "已点击 QQ 全屏按钮，但半屏会话仍未关闭")
        }
    }

    private fun waitForRoot(
        timeoutMs: Long,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): AccessibilityNodeInfo? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            Thread.sleep(POLL_INTERVAL_MS)
            val root = onMainThread { service.rootInActiveWindow } ?: continue
            if (predicate(root)) return root
        }
        return null
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

    private companion object {
        const val QQ_PACKAGE = "com.tencent.mobileqq"
        const val POLL_INTERVAL_MS = 150L
        const val EXPAND_TIMEOUT_MS = 3_000L
        const val MAIN_THREAD_TIMEOUT_MS = 3_000L
    }
}

internal object QqScaledConversationPolicy {
    fun isExpandControl(
        contentDescription: String,
        enabled: Boolean,
        clickable: Boolean,
    ): Boolean = enabled && clickable && contentDescription.trim() == "全屏"
}
