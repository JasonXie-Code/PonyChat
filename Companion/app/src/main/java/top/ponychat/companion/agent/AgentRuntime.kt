package top.ponychat.companion.agent

class AgentRuntime(
    private val brain: BrainClient,
    private val device: DeviceAdapter,
    private val verifier: ResultVerifier,
    private val listener: AgentEventListener = AgentEventListener {},
) {
    fun run(task: AgentTask): AgentOutcome {
        val history = mutableListOf<AgentStep>()
        var feedback: String? = null
        CompanionExecutionControl.beginTask()

        return try {
            listener.onEvent(
                "任务开始：${task.instruction}｜最多${task.maxSteps}步｜设备：${device.adapterName}",
            )
            for (stepIndex in 1..task.maxSteps) {
                if (CompanionExecutionControl.awaitPermission() ==
                    CompanionExecutionControl.Permission.STOPPED
                ) return stoppedOutcome(task, history)
                val before = device.observe()
                listener.onEvent("[$stepIndex] 已观察当前界面")

                val decision = brain.decide(
                    task = task,
                    context = BrainContext(
                        step = stepIndex,
                        observation = before,
                        history = history.toList(),
                        previousFeedback = feedback,
                    ),
                )
                listener.onEvent("[$stepIndex] 决策：${decision.reasoning}")

                when (CompanionExecutionControl.awaitPermission()) {
                    CompanionExecutionControl.Permission.STOPPED -> return stoppedOutcome(task, history)
                    CompanionExecutionControl.Permission.RESUMED -> {
                        feedback = "用户接管后选择继续，需要重新观察当前界面"
                        continue
                    }
                    CompanionExecutionControl.Permission.CONTINUE -> Unit
                }

                val execution = device.execute(decision.action)
                listener.onEvent("[$stepIndex] 执行：${execution.detail}")
                if (CompanionExecutionControl.awaitPermission() ==
                    CompanionExecutionControl.Permission.STOPPED
                ) return stoppedOutcome(task, history)
                val after = device.observe()
                val verification = verifier.verify(task, before, decision, execution, after)
                listener.onEvent("[$stepIndex] 验证：${verification.feedback}")

                history += AgentStep(
                    index = stepIndex,
                    before = before,
                    decision = decision,
                    execution = execution,
                    after = after,
                    verification = verification,
                )

                if (verification.completed) {
                    listener.onEvent("任务完成：${verification.feedback}")
                    return AgentOutcome(
                        taskId = task.id,
                        status = OutcomeStatus.COMPLETED,
                        steps = history.toList(),
                        summary = verification.feedback,
                    )
                }
                feedback = verification.feedback
            }

            val summary = "达到最大步骤数 ${task.maxSteps}，任务尚未通过验证"
            listener.onEvent("任务停止：$summary")
            AgentOutcome(
                taskId = task.id,
                status = OutcomeStatus.MAX_STEPS_REACHED,
                steps = history.toList(),
                summary = summary,
            )
        } catch (error: Exception) {
            listener.onEvent("任务失败：${error.message ?: error::class.java.simpleName}")
            AgentOutcome(
                taskId = task.id,
                status = OutcomeStatus.FAILED,
                steps = history.toList(),
                summary = error.message ?: error::class.java.simpleName,
            )
        } finally {
            CompanionExecutionControl.finishTask()
        }
    }

    private fun stoppedOutcome(task: AgentTask, history: List<AgentStep>): AgentOutcome {
        listener.onEvent("任务停止：用户接管并停止了本次任务")
        return AgentOutcome(
            taskId = task.id,
            status = OutcomeStatus.USER_STOPPED,
            steps = history.toList(),
            summary = "用户已停止本次任务",
        )
    }
}
