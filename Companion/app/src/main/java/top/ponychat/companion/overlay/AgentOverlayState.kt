package top.ponychat.companion.overlay

enum class AgentOverlayPhase {
    IDLE,
    OBSERVING,
    DECIDING,
    EXECUTING,
    VERIFYING,
    RECOVERING,
    COMPLETED,
    FAILED,
}

data class AgentOverlayState(
    val goal: String = "等待任务",
    val decisionSummary: String = "Companion 已就绪",
    val phase: AgentOverlayPhase = AgentOverlayPhase.IDLE,
    val currentStep: Int = 0,
    val totalSteps: Int = 0,
    val action: String = "",
    val verification: String = "",
    val model: String = "DeepSeek Flash",
    val agentInputActive: Boolean = false,
    val userPaused: Boolean = false,
    val overlayVisible: Boolean = true,
)

object AgentOverlayPresentation {
    fun phaseLabel(phase: AgentOverlayPhase): String = when (phase) {
        AgentOverlayPhase.IDLE -> "待命"
        AgentOverlayPhase.OBSERVING -> "观察界面"
        AgentOverlayPhase.DECIDING -> "规划下一步"
        AgentOverlayPhase.EXECUTING -> "执行操作"
        AgentOverlayPhase.VERIFYING -> "验证结果"
        AgentOverlayPhase.RECOVERING -> "自动恢复"
        AgentOverlayPhase.COMPLETED -> "任务完成"
        AgentOverlayPhase.FAILED -> "需要处理"
    }

    fun progressLabel(state: AgentOverlayState): String = when {
        state.currentStep <= 0 -> phaseLabel(state.phase)
        state.totalSteps > 0 -> "步骤 ${state.currentStep}/${state.totalSteps} · ${phaseLabel(state.phase)}"
        else -> "步骤 ${state.currentStep} · ${phaseLabel(state.phase)}"
    }

    fun planLines(state: AgentOverlayState): List<String> {
        val stages = listOf(
            AgentOverlayPhase.OBSERVING to "观察当前界面",
            AgentOverlayPhase.DECIDING to "选择下一步动作",
            AgentOverlayPhase.EXECUTING to "执行设备操作",
            AgentOverlayPhase.VERIFYING to "检查结果并纠错",
        )
        val currentIndex = stages.indexOfFirst { it.first == state.phase }
        return stages.mapIndexed { index, (_, label) ->
            val marker = when {
                state.phase == AgentOverlayPhase.COMPLETED -> "✓"
                currentIndex < 0 -> "○"
                index < currentIndex -> "✓"
                index == currentIndex -> "▶"
                else -> "○"
            }
            "$marker $label"
        }
    }

    fun safeSummary(value: String, maxChars: Int = 140): String {
        val compact = value
            .replace(Regex("(?i)(api[_ -]?key|token|authorization)\\s*[:=]\\s*\\S+"), "$1=[已隐藏]")
            .replace(Regex("\\s+"), " ")
            .trim()
        return if (compact.length <= maxChars) compact else compact.take(maxChars - 1) + "…"
    }
}
