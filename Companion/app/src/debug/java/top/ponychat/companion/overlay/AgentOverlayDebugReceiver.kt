package top.ponychat.companion.overlay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import top.ponychat.companion.agent.CompanionExecutionControl

/** Emulator-only hook for exercising takeover controls without exposing a production API. */
class AgentOverlayDebugReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getStringExtra("command")) {
            "pause" -> {
                CompanionExecutionControl.beginTask()
                AgentOverlayController.pauseForUser(context)
            }
            "continue" -> AgentOverlayController.continueAfterUser(context)
            "stop" -> AgentOverlayController.stopAfterUser(context)
        }
    }
}
