package top.ponychat.companion.reply

import android.content.Context
import android.os.Handler
import android.os.Looper
import top.ponychat.companion.agent.CompanionExecutionControl
import top.ponychat.companion.overlay.AgentOverlayController
import top.ponychat.companion.overlay.AgentOverlayPhase
import java.util.UUID

object PendingQqReplyRegistry {
    data class PendingReply(
        val eventId: String,
        val ackToken: String,
        val sender: String,
        val response: String,
        val instruction: String,
    )

    private val handler = Handler(Looper.getMainLooper())
    private val lock = Any()
    private var current: PendingReply? = null

    fun publish(
        context: Context,
        eventId: String,
        sender: String,
        response: String,
        instruction: String = "",
    ): PendingReply {
        val pending = PendingReply(eventId, UUID.randomUUID().toString(), sender, response, instruction)
        synchronized(lock) { current = pending }
        handler.postDelayed({ acknowledge(context, eventId, pending.ackToken, false, "执行器超时") }, TIMEOUT_MS)
        return pending
    }

    fun acknowledge(
        context: Context,
        eventId: String,
        ackToken: String,
        success: Boolean,
        detail: String,
        operation: String = "chat_reply",
    ): Boolean {
        val pending = synchronized(lock) {
            val value = current
            if (value?.eventId != eventId || value.ackToken != ackToken) return false
            current = null
            value
        }
        AgentOverlayController.update(context) {
            val isDeviceCommand = operation == "device_command"
            it.copy(
                phase = if (success) AgentOverlayPhase.COMPLETED else AgentOverlayPhase.FAILED,
                decisionSummary = if (success) {
                    if (isDeviceCommand) "QQ 指令执行完成" else "角色回复已发送给 ${pending.sender}"
                } else {
                    if (isDeviceCommand) "QQ 指令执行失败：$detail" else "QQ 私聊回复未发送：$detail"
                },
                action = if (!success) "" else if (isDeviceCommand) {
                    "设备指令：${pending.instruction}"
                } else {
                    "QQ 私聊回复：${pending.response}"
                },
                verification = detail,
            )
        }
        CompanionExecutionControl.finishTask()
        return true
    }

    fun matches(eventId: String, ackToken: String): Boolean = synchronized(lock) {
        current?.eventId == eventId && current?.ackToken == ackToken
    }

    fun hasPending(): Boolean = synchronized(lock) { current != null }

    private const val TIMEOUT_MS = 600_000L
}
