package top.ponychat.companion.reply

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import top.ponychat.companion.agent.CompanionExecutionControl
import top.ponychat.companion.overlay.AgentOverlayController

class QqReplyResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val eventId = intent.getStringExtra("event_id").orEmpty()
        val ackToken = intent.getStringExtra("ack_token").orEmpty()
        if (intent.action in setOf(
                ACTION_INPUT_BEGIN,
                ACTION_INPUT_END,
                ACTION_PHYSICAL_TOUCH,
                ACTION_QUERY_CONTROL,
            )
        ) {
            if (!PendingQqReplyRegistry.matches(eventId, ackToken)) return
            if (intent.action == ACTION_PHYSICAL_TOUCH) {
                Log.i("CompanionInput", "Physical touchscreen event detected")
                AgentOverlayController.pauseForUser(context)
                return
            }
            if (intent.action == ACTION_QUERY_CONTROL) {
                resultCode = when (CompanionExecutionControl.snapshot()) {
                    CompanionExecutionControl.Snapshot.RUNNING -> CONTROL_RUNNING
                    CompanionExecutionControl.Snapshot.PAUSED -> CONTROL_PAUSED
                    CompanionExecutionControl.Snapshot.STOPPED -> CONTROL_STOPPED
                    CompanionExecutionControl.Snapshot.IDLE -> CONTROL_IDLE
                }
                return
            }
            val leaseToken = "$eventId:$ackToken"
            if (intent.action == ACTION_INPUT_BEGIN) {
                Log.i("CompanionInput", "Controller input lease started")
                AgentOverlayController.beginExternalAgentInput(
                    context,
                    leaseToken,
                    intent.getIntExtra("timeout_ms", 8_000).toLong(),
                )
            } else {
                Log.i("CompanionInput", "Controller input lease settling")
                AgentOverlayController.endExternalAgentInput(leaseToken)
            }
            return
        }
        if (intent.action != ACTION) return
        PendingQqReplyRegistry.acknowledge(
            context,
            eventId = eventId,
            ackToken = ackToken,
            success = intent.getStringExtra("status") == "completed",
            detail = intent.getStringExtra("detail").orEmpty(),
            operation = intent.getStringExtra("operation").orEmpty().ifBlank { "chat_reply" },
        )
    }

    companion object {
        const val ACTION = "top.ponychat.companion.action.QQ_REPLY_RESULT"
        const val ACTION_INPUT_BEGIN = "top.ponychat.companion.action.AGENT_INPUT_BEGIN"
        const val ACTION_INPUT_END = "top.ponychat.companion.action.AGENT_INPUT_END"
        const val ACTION_PHYSICAL_TOUCH = "top.ponychat.companion.action.PHYSICAL_TOUCH"
        const val ACTION_QUERY_CONTROL = "top.ponychat.companion.action.QUERY_CONTROL"
        private const val CONTROL_IDLE = 0
        private const val CONTROL_RUNNING = 1
        private const val CONTROL_PAUSED = 2
        private const val CONTROL_STOPPED = 3
    }
}
