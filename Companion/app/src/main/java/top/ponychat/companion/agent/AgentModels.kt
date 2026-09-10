package top.ponychat.companion.agent

data class AgentTask(
    val id: String,
    val instruction: String,
    val maxSteps: Int = 8,
) {
    init {
        require(id.isNotBlank()) { "Task id must not be blank" }
        require(instruction.isNotBlank()) { "Task instruction must not be blank" }
        require(maxSteps > 0) { "maxSteps must be greater than zero" }
    }
}

data class UiNode(
    val id: String? = null,
    val text: String? = null,
    val contentDescription: String? = null,
    val className: String? = null,
    val clickable: Boolean = false,
    val editable: Boolean = false,
)

data class Observation(
    val sequence: Long,
    val foregroundPackage: String? = null,
    val uiNodes: List<UiNode> = emptyList(),
    val screenshotAvailable: Boolean = false,
    val notes: Map<String, String> = emptyMap(),
)

sealed interface ActionTarget {
    data class Semantic(
        val viewId: String? = null,
        val text: String? = null,
        val contentDescription: String? = null,
    ) : ActionTarget

    data class Coordinate(val x: Int, val y: Int) : ActionTarget
    data class Visual(val label: String) : ActionTarget
}

sealed interface AgentAction {
    data class LaunchApp(val packageName: String) : AgentAction
    data class Tap(val target: ActionTarget) : AgentAction
    data class Swipe(
        val startX: Int,
        val startY: Int,
        val endX: Int,
        val endY: Int,
        val durationMs: Long = 300,
    ) : AgentAction

    data class InputText(val target: ActionTarget.Semantic, val text: String) : AgentAction
    data object Back : AgentAction
    data object Home : AgentAction
    data class Wait(val durationMs: Long) : AgentAction
    data class NoOp(val reason: String) : AgentAction
}

data class BrainContext(
    val step: Int,
    val observation: Observation,
    val history: List<AgentStep>,
    val previousFeedback: String? = null,
)

data class BrainDecision(
    val action: AgentAction,
    val reasoning: String,
)

data class ExecutionResult(
    val success: Boolean,
    val detail: String,
)

data class VerificationResult(
    val completed: Boolean,
    val confidence: Double,
    val feedback: String,
) {
    init {
        require(confidence in 0.0..1.0) { "confidence must be between 0 and 1" }
    }
}

data class AgentStep(
    val index: Int,
    val before: Observation,
    val decision: BrainDecision,
    val execution: ExecutionResult,
    val after: Observation,
    val verification: VerificationResult,
)

enum class OutcomeStatus {
    COMPLETED,
    MAX_STEPS_REACHED,
    USER_STOPPED,
    FAILED,
}

data class AgentOutcome(
    val taskId: String,
    val status: OutcomeStatus,
    val steps: List<AgentStep>,
    val summary: String,
)
