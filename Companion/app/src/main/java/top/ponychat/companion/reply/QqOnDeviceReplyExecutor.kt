package top.ponychat.companion.reply

import android.graphics.Rect
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityNodeInfo
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.overlay.AgentOverlayController

class QqOnDeviceReplyExecutor(
    private val service: CompanionAccessibilityService,
) {
    data class Result(val success: Boolean, val detail: String)

    fun send(expectedSender: String, response: String): Result {
        if (response.isBlank()) return Result(false, "角色回复为空")
        val lease = AgentOverlayController.acquireAgentInput(service)
            ?: return Result(false, "用户正在操作 Companion 悬浮窗")
        return try {
            val before = snapshot() ?: return Result(false, "QQ 不在前台")
            if (!isConfirmedPrivateChat(before, expectedSender)) {
                return Result(false, "当前 QQ 页面未通过私聊联系人校验")
            }
            val beforeConversationSignature = conversationSignature(before)
            val editor = findEditor(before)
                ?: return Result(false, "未找到 QQ 消息输入框")
            if (!setText(editor, response)) {
                return Result(false, "无法写入 QQ 消息输入框")
            }
            val ready = waitForRoot(INPUT_SETTLE_TIMEOUT_MS) { root ->
                isConfirmedPrivateChat(root, expectedSender) &&
                    findEditor(root)?.text?.toString() == response &&
                    findSendButton(root) != null
            } ?: return Result(false, "消息已写入，但发送按钮未就绪")
            val send = findSendButton(ready)
                ?: return Result(false, "未找到 QQ 发送按钮")
            if (!click(send)) return Result(false, "QQ 发送按钮点击失败")

            val verified = waitForRoot(SEND_VERIFY_TIMEOUT_MS) { root ->
                if (!isConfirmedPrivateChat(root, expectedSender)) return@waitForRoot false
                QqForegroundSafety.isSentMessageVerified(
                    editorCleared = findEditor(root)?.text?.toString().orEmpty() != response,
                    exactOutgoingTextVisible = hasOutgoingMessage(root, response),
                    ownProfileVisible = ownProfileNodes(root).isNotEmpty(),
                    conversationSignatureChanged =
                        conversationSignature(root) != beforeConversationSignature,
                )
            }
            if (verified == null) {
                Result(false, "已点击发送，但未在当前私聊回读到发出的消息")
            } else {
                Result(true, "已在开发板 QQ 当前私聊中回读验证")
            }
        } finally {
            lease.close()
        }
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

    private fun isConfirmedPrivateChat(root: AccessibilityNodeInfo, sender: String): Boolean {
        if (root.packageName?.toString() != QQ_PACKAGE) return false
        val titles = TITLE_IDS.flatMap(root::findAccessibilityNodeInfosByViewId)
        if (titles.none { it.text?.toString()?.trim() == sender }) return false
        return findNodes(root).any {
            QqForegroundSafety.isPrivateOnlineStatus(it.text?.toString().orEmpty())
        }
    }

    private fun findEditor(root: AccessibilityNodeInfo): AccessibilityNodeInfo? =
        root.findAccessibilityNodeInfosByViewId(EDITOR_ID)
            .firstOrNull { it.isEditable && it.isEnabled }
            ?: findNodes(root).firstOrNull { it.isEditable && it.isEnabled }

    private fun findSendButton(root: AccessibilityNodeInfo): AccessibilityNodeInfo? =
        root.findAccessibilityNodeInfosByViewId(SEND_BUTTON_ID)
            .firstOrNull { it.isEnabled && it.isClickable && it.text?.toString() == SEND_TEXT }
            ?: findNodes(root).firstOrNull {
                it.isEnabled && it.isClickable && it.text?.toString() == SEND_TEXT
            }

    private fun setText(node: AccessibilityNodeInfo, text: String): Boolean = onMainThread {
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
    }

    private fun click(node: AccessibilityNodeInfo): Boolean = onMainThread {
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    private fun hasOutgoingMessage(root: AccessibilityNodeInfo, response: String): Boolean {
        val screenMidpoint = rootBounds(root).centerX()
        val ownAvatars = ownProfileNodes(root)
            .filter { rootBounds(it).centerX() > screenMidpoint }
        val messages = MESSAGE_IDS
            .flatMap(root::findAccessibilityNodeInfosByViewId)
            .filter { it.text?.toString() == response }
        return messages.any { message ->
            val messageBounds = rootBounds(message)
            ownAvatars.any { avatar ->
                val avatarBounds = rootBounds(avatar)
                QqForegroundSafety.isOwnOutgoingMessageRow(
                    screenMidpoint,
                    avatarBounds.centerX(),
                    messageBounds.top,
                    messageBounds.bottom,
                    avatarBounds.top,
                    avatarBounds.bottom,
                )
            }
        }
    }

    private fun ownProfileNodes(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> =
        (root.findAccessibilityNodeInfosByViewId(AVATAR_ID) + findNodes(root).filter {
            it.contentDescription?.toString() == OWN_PROFILE_DESCRIPTION
        }).distinctBy { node ->
            val bounds = rootBounds(node)
            "${node.viewIdResourceName}|${node.contentDescription}|${bounds.flattenToString()}"
        }

    private fun conversationSignature(root: AccessibilityNodeInfo): String = findNodes(root)
        .mapNotNull { node ->
            val text = node.text?.toString().orEmpty()
            val description = node.contentDescription?.toString().orEmpty()
            if (
                text.isBlank() &&
                !description.endsWith(PROFILE_SUFFIX) &&
                description != OWN_PROFILE_DESCRIPTION
            ) return@mapNotNull null
            val bounds = rootBounds(node)
            "$text|$description|${bounds.flattenToString()}"
        }
        .joinToString("\u001f")

    private fun findNodes(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val result = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            result += node
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        visit(root)
        return result
    }

    private fun rootBounds(node: AccessibilityNodeInfo): Rect = Rect().also(node::getBoundsInScreen)

    private fun <T> onMainThread(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return block()
        var value: kotlin.Result<T>? = null
        val latch = java.util.concurrent.CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            value = runCatching(block)
            latch.countDown()
        }
        check(latch.await(MAIN_THREAD_TIMEOUT_MS, java.util.concurrent.TimeUnit.MILLISECONDS)) {
            "等待无障碍主线程超时"
        }
        return checkNotNull(value).getOrThrow()
    }

    companion object {
        private const val QQ_PACKAGE = "com.tencent.mobileqq"
        private const val EDITOR_ID = "$QQ_PACKAGE:id/input"
        private const val SEND_BUTTON_ID = "$QQ_PACKAGE:id/send_btn"
        private const val AVATAR_ID = "$QQ_PACKAGE:id/mgo"
        private const val SEND_TEXT = "发送"
        private const val PROFILE_SUFFIX = "的资料卡"
        private const val OWN_PROFILE_DESCRIPTION = "我的资料卡"
        private val TITLE_IDS = listOf("$QQ_PACKAGE:id/34v", "$QQ_PACKAGE:id/1yo")
        private val MESSAGE_IDS = listOf("$QQ_PACKAGE:id/mjo", "$QQ_PACKAGE:id/mj0")
        private const val POLL_INTERVAL_MS = 150L
        private const val INPUT_SETTLE_TIMEOUT_MS = 3_000L
        private const val SEND_VERIFY_TIMEOUT_MS = 5_000L
        private const val MAIN_THREAD_TIMEOUT_MS = 3_000L
    }
}
