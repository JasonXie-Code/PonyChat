package top.ponychat.companion.reply

import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import top.ponychat.companion.agent.CompanionExecutionControl
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.overlay.AgentOverlayController
import top.ponychat.companion.overlay.AgentOverlayPhase
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * QQ 前台不会稳定发布通知，因此用无障碍树发布已确认私聊的新消息事件。
 * 角色回复由设备内无障碍执行器输入、发送并回读；主机 Controller 不参与生产链路。
 */
class QqForegroundReplyController(
    private val service: CompanionAccessibilityService,
) : AutoCloseable {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val busy = AtomicBoolean(false)
    private val scanning = AtomicBoolean(false)
    private val replyClient = CompanionRoleReplyClient()
    private val onDeviceReplyExecutor = QqOnDeviceReplyExecutor(service)
    private val conversationNavigator = ChatAppConversationNavigator(service)
    private val conversationSurfaceNormalizer = QqConversationSurfaceNormalizer(service)
    // Accessibility may bind during direct boot before credential-encrypted storage is available.
    // Event de-duplication contains no account secret, so keep it in device-protected storage.
    private val preferences = service.createDeviceProtectedStorageContext()
        .getSharedPreferences(PREFERENCES, 0)
    private val observedConversationSignatures = mutableMapOf<String, String>()
    private var pendingSender: String? = null
    private var scanRunnable: Runnable? = null
    private var ignoreChangesUntil = 0L

    fun onServiceConnected() {
        scheduleScan(INITIAL_SCAN_DELAY_MS)
    }

    fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (event.packageName?.toString() != QQ_PACKAGE) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED,
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> scheduleScan(SCAN_DEBOUNCE_MS)
        }
    }

    fun onUserInteraction() {
        ignoreChangesUntil = System.currentTimeMillis() + USER_INTERACTION_SETTLE_MS
    }

    private fun scheduleScan(delayMs: Long) {
        scanRunnable?.let(mainHandler::removeCallbacks)
        Runnable {
            if (!scanning.compareAndSet(false, true)) return@Runnable
            runCatching {
                worker.execute {
                    try {
                        scanCurrentScreen()
                    } finally {
                        scanning.set(false)
                    }
                }
            }.onFailure { scanning.set(false) }
        }.also {
            scanRunnable = it
            mainHandler.postDelayed(it, delayMs)
        }
    }

    private fun scanCurrentScreen() {
        if (busy.get()) return
        // UI operations reflow QQ's message list. Never reinterpret that reflow as a new
        // incoming event while the current event lease is still active.
        if (CompanionExecutionControl.snapshot() != CompanionExecutionControl.Snapshot.IDLE) return
        val root = service.rootInActiveWindow ?: return
        if (root.packageName?.toString() != QQ_PACKAGE) return
        val notificationCandidate = QqNotificationVerificationStore.peek(service)
        if (notificationCandidate != null) {
            val normalized = conversationSurfaceNormalizer.expandIfNeeded(root)
            if (!normalized.success) {
                Log.w(TAG, normalized.detail)
                return
            }
            if (normalized.changed) {
                Log.i(TAG, normalized.detail)
                scheduleScan(CHAT_OPEN_DELAY_MS)
                return
            }
        }
        if (notificationCandidate != null && isConfirmedGroupChat(root)) {
            QqNotificationVerificationStore.consume(service, notificationCandidate)
            val navigation = conversationNavigator.returnToConversationList(
                ChatAppConversationNavigator.QQ,
            )
            Log.w(
                TAG,
                "Rejected QQ notification verification because it opened a group; ${navigation.detail}",
            )
            return
        }
        findUnreadConversation(root, notificationCandidate?.sender)?.let { unread ->
            pendingSender = unread.sender
            if (unread.node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                Log.i(TAG, "Opened unread QQ conversation for private verification")
                scheduleScan(CHAT_OPEN_DELAY_MS)
            }
            return
        }
        val incoming = inspectConfirmedPrivateChat(root) ?: return
        val previousSignature = observedConversationSignatures.put(
            incoming.sender,
            incoming.screenSignature,
        )
        val openedFromUnread = pendingSender == incoming.sender
        val openedFromNotification = notificationCandidate?.matches(
            incoming.sender,
            incoming.message,
        ) == true
        val changedWithoutUser = previousSignature != null &&
            previousSignature != incoming.screenSignature &&
            System.currentTimeMillis() >= ignoreChangesUntil
        if (!openedFromUnread && !openedFromNotification && !changedWithoutUser) return
        if (pendingSender != null && !openedFromUnread) return
        val replySurface = conversationSurfaceNormalizer.expandIfNeeded(root)
        if (!replySurface.success) {
            Log.w(TAG, "Stopped QQ reply before full-screen normalization: ${replySurface.detail}")
            return
        }
        if (replySurface.changed) Log.i(TAG, replySurface.detail)
        if (openedFromNotification) {
            QqNotificationVerificationStore.consume(service, checkNotNull(notificationCandidate))
            Log.i(TAG, "Confirmed QQ private chat from notification fingerprint")
        }
        pendingSender = null
        handleIncoming(incoming)
    }

    private fun findUnreadConversation(
        root: AccessibilityNodeInfo,
        expectedSender: String? = null,
    ): UnreadConversation? {
        return findNodes(root) { node ->
            val description = node.contentDescription?.toString().orEmpty()
            node.isClickable && UNREAD_PATTERN.containsMatchIn(description)
        }.mapNotNull { node ->
            val description = node.contentDescription?.toString().orEmpty()
            val fields = description.split(',').map(String::trim)
            val sender = fields.firstOrNull().orEmpty()
            if (
                sender.isBlank() ||
                (expectedSender != null && sender != expectedSender) ||
                QqForegroundSafety.hasGroupSignals(description) ||
                QqProtectedConversation.shouldPause(sender, description)
            ) null
            else UnreadConversation(sender, node)
        }.firstOrNull()
    }

    private fun inspectConfirmedPrivateChat(root: AccessibilityNodeInfo): IncomingMessage? {
        val title = findTitle(root)
        if (title.isBlank() || QqForegroundSafety.hasGroupSignals(title)) return null
        val hasPrivateStatus = findNodes(root) {
            QqForegroundSafety.isPrivateOnlineStatus(it.text?.toString().orEmpty())
        }.isNotEmpty()
        if (!hasPrivateStatus) return null
        val expectedProfile = "$title$PROFILE_SUFFIX"
        val profileNodes = findNodes(root) {
            it.contentDescription?.toString() == expectedProfile
        }
        if (profileNodes.isEmpty()) return null
        val identifiedMessages = findNodesByViewIds(root, MESSAGE_IDS)
        val semanticMessages = findNodes(root) { node ->
            node.text?.toString()?.isNotBlank() == true
        }
        val messages = (identifiedMessages + semanticMessages)
            .distinctBy(::nodeSignature)
            .filter { it.text?.toString()?.isNotBlank() == true }
            .filter { message -> profileNodes.any { profile -> isSameMessageRow(message, profile) } }
            .sortedBy(::bottom)
        val latest = messages.lastOrNull() ?: return null
        val message = latest.text?.toString()?.trim().orEmpty()
        if (QqProtectedConversation.shouldPause(title, message)) return null
        val signature = messages
            .takeLast(SIGNATURE_MESSAGE_COUNT)
            .joinToString("\u001f") { it.text?.toString().orEmpty() }
        return IncomingMessage(title, message, signature)
    }

    private fun isConfirmedGroupChat(root: AccessibilityNodeInfo): Boolean {
        val title = findTitle(root)
        return title.isNotBlank() && QqForegroundSafety.hasGroupSignals(title)
    }

    private fun findTitle(root: AccessibilityNodeInfo): String {
        findNodesByViewIds(root, TITLE_IDS).forEach { node ->
            node.text?.toString()?.trim()?.takeIf(String::isNotBlank)?.let { return it }
        }
        return findNodes(root) { node ->
            node.contentDescription?.toString()?.endsWith(PROFILE_SUFFIX) == true
        }.asSequence()
            .map { it.contentDescription?.toString().orEmpty().removeSuffix(PROFILE_SUFFIX).trim() }
            .filter(String::isNotBlank)
            .groupingBy { it }
            .eachCount()
            .maxByOrNull { it.value }
            ?.key
            .orEmpty()
    }

    private fun findNodesByViewIds(
        root: AccessibilityNodeInfo,
        viewIds: List<String>,
    ): List<AccessibilityNodeInfo> = viewIds
        .flatMap(root::findAccessibilityNodeInfosByViewId)
        .distinctBy(::nodeSignature)

    private fun nodeSignature(node: AccessibilityNodeInfo): String {
        val bounds = Rect().also(node::getBoundsInScreen)
        return listOf(
            node.viewIdResourceName.orEmpty(),
            node.text?.toString().orEmpty(),
            node.contentDescription?.toString().orEmpty(),
            bounds.flattenToString(),
        ).joinToString("\u001f")
    }

    private fun isSameMessageRow(
        message: AccessibilityNodeInfo,
        profile: AccessibilityNodeInfo,
    ): Boolean {
        val messageBounds = Rect().also(message::getBoundsInScreen)
        val profileBounds = Rect().also(profile::getBoundsInScreen)
        return QqForegroundSafety.isSameMessageRow(
            messageBounds.top,
            messageBounds.bottom,
            profileBounds.top,
            profileBounds.bottom,
        )
    }

    private fun handleIncoming(incoming: IncomingMessage) {
        val now = System.currentTimeMillis()
        if (QqForegroundSafety.isSameMessageWithinSettleWindow(
                preferences.getString(LAST_HANDLED_SENDER, null),
                preferences.getString(LAST_HANDLED_MESSAGE, null),
                preferences.getLong(LAST_HANDLED_AT, 0L),
                incoming.sender,
                incoming.message,
                now,
                MESSAGE_SETTLE_WINDOW_MS,
            )
        ) {
            Log.i(TAG, "Suppressed duplicate QQ layout-settle event for ${incoming.sender}")
            return
        }
        val eventId = QqReplyEventId.create(
            incoming.sender,
            incoming.message,
            incoming.screenSignature,
        )
        val previous = preferences.getString(LAST_HANDLED, null)
        if (previous == eventId) return
        val session = CompanionSessionStore.current
        if (session?.isReady != true) {
            Log.i(TAG, "Skipped QQ foreground reply because PonyChat session is not configured")
            return
        }
        if (!QqAutomaticReplyGate.tryAcquire(incoming.sender)) {
            Log.w(TAG, "Paused QQ foreground reply because the compliance rate limit was reached")
            AgentOverlayController.update(service) {
                it.copy(
                    goal = "QQ 自动回复已暂停",
                    phase = AgentOverlayPhase.FAILED,
                    decisionSummary = "短时间回复次数达到安全上限，请稍后再试",
                    action = "未输入、未发送",
                    verification = "合规限流已生效",
                    userPaused = true,
                )
            }
            return
        }
        if (!busy.compareAndSet(false, true)) return
        preferences.edit()
            .putString(LAST_HANDLED, eventId)
            .putString(LAST_HANDLED_SENDER, incoming.sender)
            .putString(LAST_HANDLED_MESSAGE, incoming.message)
            .putLong(LAST_HANDLED_AT, now)
            .commit()
        worker.execute {
            CompanionExecutionControl.beginTask()
            try {
                if (QqDeviceCommandDetector.isSupported(incoming.message)) {
                    error("该设备指令尚未接入 H618 内置执行器，未转交主机 Controller")
                }
                AgentOverlayController.update(service) {
                    it.copy(
                        goal = "回复 QQ 私聊：${incoming.sender}",
                        phase = AgentOverlayPhase.DECIDING,
                        decisionSummary = "正在以当前角色生成私聊回复",
                        action = "",
                        verification = "已通过标题、在线状态和来信头像确认私聊",
                        userPaused = false,
                    )
                }
                val response = replyClient.generate(
                    session,
                    incoming.message,
                )
                    ?: error("角色回复接口未返回内容")
                if (CompanionExecutionControl.awaitPermission() ==
                    CompanionExecutionControl.Permission.STOPPED
                ) return@execute
                AgentOverlayController.update(service) {
                    it.copy(
                        phase = AgentOverlayPhase.EXECUTING,
                        decisionSummary = "角色回复已生成，正在开发板内发送",
                        action = "设备内回复 QQ 私聊：${incoming.sender}",
                        verification = "已确认私聊事件 ID：${eventId.take(12)}",
                    )
                }
                var verification = ""
                response.parts.forEach { part ->
                    if (part.displayDelayMs > 0L) Thread.sleep(part.displayDelayMs)
                    if (CompanionExecutionControl.awaitPermission() ==
                        CompanionExecutionControl.Permission.STOPPED
                    ) return@execute
                    val result = onDeviceReplyExecutor.send(incoming.sender, part.text)
                    if (!result.success) error(result.detail)
                    verification = result.detail
                }
                val navigation = conversationNavigator.returnToConversationList(
                    ChatAppConversationNavigator.QQ,
                )
                if (!navigation.success) error(navigation.detail)
                AgentOverlayController.update(service) {
                    it.copy(
                        phase = AgentOverlayPhase.COMPLETED,
                        decisionSummary = "角色回复已由 H618 发送给 ${incoming.sender}",
                        action = "QQ 私聊回复：${response.displayText}",
                        verification = "${response.parts.size} 条消息；$verification；${navigation.detail}",
                    )
                }
                Log.i(TAG, "QQ foreground private reply completed on device")
            } catch (error: Exception) {
                Log.w(TAG, "QQ foreground private reply failed: ${error.message}")
                AgentOverlayController.update(service) {
                    it.copy(
                        phase = AgentOverlayPhase.FAILED,
                        decisionSummary = "QQ 私聊回复失败，未重复发送",
                    )
                }
            } finally {
                CompanionExecutionControl.finishTask()
                busy.set(false)
            }
        }
    }

    private fun findNodes(
        root: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean,
    ): List<AccessibilityNodeInfo> {
        val result = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            if (predicate(node)) result += node
            for (index in 0 until node.childCount) node.getChild(index)?.let(::visit)
        }
        visit(root)
        return result
    }

    private fun bottom(node: AccessibilityNodeInfo): Int = Rect().also(node::getBoundsInScreen).bottom

    override fun close() {
        scanRunnable?.let(mainHandler::removeCallbacks)
        worker.shutdownNow()
    }

    private data class UnreadConversation(
        val sender: String,
        val node: AccessibilityNodeInfo,
    )

    private data class IncomingMessage(
        val sender: String,
        val message: String,
        val screenSignature: String,
    )

    companion object {
        private const val TAG = "CompanionQqReply"
        private const val QQ_PACKAGE = "com.tencent.mobileqq"
        private val TITLE_IDS = listOf(
            "$QQ_PACKAGE:id/34v",
            "$QQ_PACKAGE:id/1yo",
        )
        private val MESSAGE_IDS = listOf(
            "$QQ_PACKAGE:id/mjo",
            "$QQ_PACKAGE:id/mj0",
        )
        private const val PROFILE_SUFFIX = "的资料卡"
        private const val PREFERENCES = "qq_foreground_reply"
        private const val LAST_HANDLED = "last_handled"
        private const val LAST_HANDLED_SENDER = "last_handled_sender"
        private const val LAST_HANDLED_MESSAGE = "last_handled_message"
        private const val LAST_HANDLED_AT = "last_handled_at"
        private const val INITIAL_SCAN_DELAY_MS = 800L
        private const val SCAN_DEBOUNCE_MS = 350L
        private const val CHAT_OPEN_DELAY_MS = 800L
        private const val SIGNATURE_MESSAGE_COUNT = 8
        private const val USER_INTERACTION_SETTLE_MS = 1_500L
        private const val MESSAGE_SETTLE_WINDOW_MS = 30_000L
        private val UNREAD_PATTERN = Regex("\\d+条未读")
    }
}
