package top.ponychat.companion.reply

import android.app.Notification
import android.app.PendingIntent
import android.app.Person
import android.app.RemoteInput
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONObject
import top.ponychat.companion.agent.CompanionExecutionControl
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.overlay.AgentOverlayController
import top.ponychat.companion.overlay.AgentOverlayPhase
import java.util.LinkedHashSet
import java.util.concurrent.Executors

class QqPrivateReplyService : NotificationListenerService() {
    private val worker = Executors.newSingleThreadExecutor()
    private val handled = LinkedHashSet<String>()
    private val replyClient = CompanionRoleReplyClient()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName != QQ_PACKAGE) return
        val parsed = parse(sbn) ?: return
        if (QqProtectedConversation.shouldPause(
                parsed.envelope.sender,
                parsed.envelope.conversationTitle.orEmpty(),
                parsed.envelope.text,
            )
        ) {
            Log.w(TAG, "Skipped protected QQ system or security notification")
            return
        }
        when (QqConversationClassifier.classify(parsed.envelope)) {
            QqConversationKind.GROUP -> Log.i(TAG, "Skipped confirmed QQ group notification")
            QqConversationKind.UNKNOWN -> requestForegroundVerification(parsed, sbn.postTime)
            QqConversationKind.PRIVATE -> handlePrivate(parsed, sbn.postTime)
        }
    }

    private fun requestForegroundVerification(parsed: ParsedNotification, postTime: Long) {
        if (!QqConversationClassifier.canVerifyInForeground(parsed.envelope)) {
            Log.i(TAG, "Skipped unsafe QQ notification verification candidate")
            return
        }
        val verificationSender =
            QqConversationClassifier.foregroundVerificationSender(parsed.envelope)
        if (verificationSender.isBlank()) return
        val contentIntent = parsed.contentIntent
        if (contentIntent == null) {
            Log.i(TAG, "Skipped unconfirmed QQ conversation because no safe open action exists")
            return
        }
        if (!QqNotificationVerificationStore.publish(
                this,
                verificationSender,
                parsed.envelope.text,
                postTime,
            )
        ) return
        worker.execute {
            try {
                val accessibility = CompanionAccessibilityService.instance
                if (accessibility != null) {
                    val navigation = ChatAppConversationNavigator(accessibility)
                        .returnToConversationList(ChatAppConversationNavigator.QQ)
                    if (!navigation.success) error(navigation.detail)
                    Log.i(TAG, "Prepared QQ conversation list before notification verification")
                }
                AgentOverlayController.update(this) {
                    it.copy(
                        goal = "验证 QQ 私聊：$verificationSender",
                        phase = AgentOverlayPhase.OBSERVING,
                        decisionSummary = "通知未声明会话类型，正在打开 QQ 进行页面内验证",
                        action = "只打开会话，尚未生成或发送回复",
                        verification = "必须通过标题、在线状态、来信头像和消息指纹校验",
                        userPaused = false,
                    )
                }
                contentIntent.send()
                Log.i(TAG, "Opened QQ notification for foreground private verification")
            } catch (_: PendingIntent.CanceledException) {
                Log.w(TAG, "QQ notification open action was canceled")
            } catch (error: Exception) {
                Log.w(TAG, "QQ notification verification preparation failed: ${error.message}")
                AgentOverlayController.update(this) {
                    it.copy(
                        phase = AgentOverlayPhase.FAILED,
                        decisionSummary = "QQ 私聊验证准备失败，未打开或发送",
                        action = "已停止，避免从错误会话打开半屏对话",
                        verification = error.message.orEmpty(),
                    )
                }
            }
        }
    }

    private fun handlePrivate(parsed: ParsedNotification, postTime: Long) {
        val dedupeKey = "${parsed.envelope.sender}|${parsed.envelope.text}|$postTime"
        synchronized(handled) {
            if (!handled.add(dedupeKey)) return
            while (handled.size > 100) handled.remove(handled.first())
        }
        val session = CompanionSessionStore.current
        if (session?.isReady != true) {
            Log.i(TAG, "Skipped QQ private reply because PonyChat session is not configured")
            return
        }
        val isDeviceCommand = QqDeviceCommandDetector.isSupported(parsed.envelope.text)
        val replyAction = parsed.replyAction
        if (replyAction == null) {
            requestForegroundVerification(parsed, postTime)
            return
        }
        if (!QqAutomaticReplyGate.tryAcquire(parsed.envelope.sender)) {
            Log.w(TAG, "Paused QQ notification reply because the compliance rate limit was reached")
            AgentOverlayController.update(this) {
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
        worker.execute {
            CompanionExecutionControl.beginTask()
            try {
                AgentOverlayController.update(this) {
                    it.copy(
                        goal = if (isDeviceCommand) {
                            "执行 QQ 私聊指令：${parsed.envelope.sender}"
                        } else {
                            "回复 QQ 私聊：${parsed.envelope.sender}"
                        },
                        phase = AgentOverlayPhase.DECIDING,
                        decisionSummary = if (isDeviceCommand) {
                            "正在确认指令并记录到当前角色经历"
                        } else {
                            "正在以当前角色生成私聊回复"
                        },
                        action = "",
                        verification = "已确认不是群聊",
                        userPaused = false,
                    )
                }
                val response = replyClient.generate(
                    session,
                    parsed.envelope.text,
                ) ?: return@execute
                if (isDeviceCommand) {
                    error("该设备指令尚未接入 H618 内置执行器，未转交主机 Controller")
                }
                response.parts.forEach { part ->
                    if (part.displayDelayMs > 0L) Thread.sleep(part.displayDelayMs)
                    if (CompanionExecutionControl.awaitPermission() ==
                        CompanionExecutionControl.Permission.STOPPED
                    ) return@execute
                    sendRemoteReply(checkNotNull(replyAction), part.text)
                }
                val navigation = CompanionAccessibilityService.instance?.let { accessibility ->
                    ChatAppConversationNavigator(accessibility).returnToConversationList(
                        ChatAppConversationNavigator.QQ,
                    )
                }
                if (navigation?.success == false) error(navigation.detail)
                AgentOverlayController.update(this) {
                    it.copy(
                        phase = AgentOverlayPhase.COMPLETED,
                        decisionSummary = "角色回复已发送给 ${parsed.envelope.sender}",
                        action = "QQ 私聊回复：${response.displayText}",
                        verification = buildString {
                            append("${response.parts.size} 条普通对话消息已通过 RemoteInput 提交")
                            navigation?.let { append("；${it.detail}") }
                        },
                    )
                }
            } catch (error: Exception) {
                Log.w(TAG, "QQ private reply failed: ${error.message}")
                AgentOverlayController.update(this) {
                    it.copy(
                        phase = AgentOverlayPhase.FAILED,
                        decisionSummary = "QQ 私聊回复失败，未重复发送",
                    )
                }
            } finally {
                CompanionExecutionControl.finishTask()
            }
        }
    }

    private fun parse(sbn: StatusBarNotification): ParsedNotification? {
        val notification = sbn.notification
        val extras = notification.extras
        val latest = extras.getParcelableArray(EXTRA_MESSAGES)
            ?.lastOrNull() as? Bundle
        @Suppress("DEPRECATION")
        val senderPerson = latest?.getParcelable<Person>(EXTRA_SENDER_PERSON)
        val sender = senderPerson?.name?.toString()
            ?: latest?.getCharSequence(EXTRA_SENDER)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = latest?.getCharSequence(EXTRA_TEXT)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        val conversationTitle = extras.getCharSequence(EXTRA_CONVERSATION_TITLE)?.toString()
        val isGroup = if (extras.containsKey(EXTRA_IS_GROUP)) extras.getBoolean(EXTRA_IS_GROUP) else null
        if (sender.isBlank() || text.isBlank()) return null
        return ParsedNotification(
            envelope = QqNotificationEnvelope(
                packageName = sbn.packageName,
                sender = sender,
                text = text,
                conversationTitle = conversationTitle,
                isGroupConversation = isGroup,
            ),
            replyAction = notification.actions?.firstOrNull { action ->
                !action.remoteInputs.isNullOrEmpty()
            },
            contentIntent = notification.contentIntent,
        )
    }

    private fun sendRemoteReply(action: Notification.Action, response: String) {
        val remoteInputs = action.remoteInputs ?: error("QQ reply action has no RemoteInput")
        val intent = Intent()
        val results = Bundle().apply {
            remoteInputs.forEach { putCharSequence(it.resultKey, response) }
        }
        RemoteInput.addResultsToIntent(remoteInputs, intent, results)
        action.actionIntent.send(this, 0, intent)
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private data class ParsedNotification(
        val envelope: QqNotificationEnvelope,
        val replyAction: Notification.Action?,
        val contentIntent: PendingIntent?,
    )

    companion object {
        private const val TAG = "CompanionQqReply"
        private const val QQ_PACKAGE = "com.tencent.mobileqq"
        private const val EXTRA_MESSAGES = "android.messages"
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_SENDER = "sender"
        private const val EXTRA_SENDER_PERSON = "sender_person"
        private const val EXTRA_CONVERSATION_TITLE = "android.conversationTitle"
        private const val EXTRA_IS_GROUP = "android.isGroupConversation"
    }
}
