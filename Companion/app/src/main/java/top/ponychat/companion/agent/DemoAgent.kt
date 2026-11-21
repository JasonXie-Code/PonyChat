package top.ponychat.companion.agent

class DemoDeviceAdapter : DeviceAdapter {
    override val adapterName: String = "EmulatorDemoAdapter"
    private var sequence = 0L
    private var state = "launcher"

    override fun observe(): Observation = Observation(
        sequence = ++sequence,
        foregroundPackage = "top.ponychat.demo",
        uiNodes = listOf(
            UiNode(text = state, className = "DemoScreen", clickable = true),
        ),
        screenshotAvailable = true,
        notes = mapOf("demoState" to state),
    )

    override fun execute(action: AgentAction): ExecutionResult {
        state = when (action) {
            is AgentAction.Tap -> "task-complete"
            else -> state
        }
        return ExecutionResult(success = true, detail = "模拟器已执行 $action")
    }
}

class DemoBrainClient : BrainClient {
    override fun decide(task: AgentTask, context: BrainContext): BrainDecision = BrainDecision(
        action = AgentAction.Tap(ActionTarget.Semantic(text = "launcher")),
        reasoning = if (context.previousFeedback == null) {
            "通过语义 UI 节点点击演示入口"
        } else {
            "根据验证反馈重试语义点击：${context.previousFeedback}"
        },
    )
}

class DemoResultVerifier : ResultVerifier {
    override fun verify(
        task: AgentTask,
        before: Observation,
        decision: BrainDecision,
        execution: ExecutionResult,
        after: Observation,
    ): VerificationResult {
        val completed = execution.success && after.notes["demoState"] == "task-complete"
        return VerificationResult(
            completed = completed,
            confidence = if (completed) 1.0 else 0.2,
            feedback = if (completed) "已确认演示任务完成" else "目标状态尚未出现，需要纠错",
        )
    }
}

