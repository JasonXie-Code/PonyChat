package top.ponychat.companion.agent

interface BrainClient {
    fun decide(task: AgentTask, context: BrainContext): BrainDecision
}

interface DeviceAdapter {
    val adapterName: String
    fun observe(): Observation
    fun execute(action: AgentAction): ExecutionResult
}

fun interface VisionLocator {
    fun locate(observation: Observation, label: String): ActionTarget.Coordinate?
}

object NoOpVisionLocator : VisionLocator {
    override fun locate(observation: Observation, label: String): ActionTarget.Coordinate? = null
}

fun interface ResultVerifier {
    fun verify(
        task: AgentTask,
        before: Observation,
        decision: BrainDecision,
        execution: ExecutionResult,
        after: Observation,
    ): VerificationResult
}

fun interface AgentEventListener {
    fun onEvent(message: String)
}
