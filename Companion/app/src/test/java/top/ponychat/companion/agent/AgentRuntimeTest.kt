package top.ponychat.companion.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentRuntimeTest {
    @Test
    fun `completes after observing acting and verifying`() {
        val device = RecordingDeviceAdapter()
        val runtime = AgentRuntime(
            brain = FixedBrain(),
            device = device,
            verifier = ResultVerifier { _, _, _, execution, after ->
                VerificationResult(
                    completed = execution.success && after.sequence >= 2,
                    confidence = 1.0,
                    feedback = "done",
                )
            },
        )

        val outcome = runtime.run(AgentTask("task-1", "tap the target"))

        assertEquals(OutcomeStatus.COMPLETED, outcome.status)
        assertEquals(1, outcome.steps.size)
        assertEquals(1, device.actions.size)
    }

    @Test
    fun `passes verification feedback back to brain for correction`() {
        val feedbackSeen = mutableListOf<String?>()
        val brain = object : BrainClient {
            override fun decide(task: AgentTask, context: BrainContext): BrainDecision {
                feedbackSeen += context.previousFeedback
                return BrainDecision(AgentAction.NoOp("test"), "step ${context.step}")
            }
        }
        var verificationCount = 0
        val runtime = AgentRuntime(
            brain = brain,
            device = RecordingDeviceAdapter(),
            verifier = ResultVerifier { _, _, _, _, _ ->
                verificationCount += 1
                VerificationResult(
                    completed = verificationCount == 2,
                    confidence = if (verificationCount == 2) 1.0 else 0.2,
                    feedback = if (verificationCount == 2) "corrected" else "try another target",
                )
            },
        )

        val outcome = runtime.run(AgentTask("task-2", "correct failure", maxSteps = 3))

        assertEquals(OutcomeStatus.COMPLETED, outcome.status)
        assertEquals(listOf(null, "try another target"), feedbackSeen)
        assertEquals(2, outcome.steps.size)
    }

    @Test
    fun `stops safely at configured maximum steps`() {
        val runtime = AgentRuntime(
            brain = FixedBrain(),
            device = RecordingDeviceAdapter(),
            verifier = ResultVerifier { _, _, _, _, _ ->
                VerificationResult(false, 0.0, "not yet")
            },
        )

        val outcome = runtime.run(AgentTask("task-3", "bounded loop", maxSteps = 2))

        assertEquals(OutcomeStatus.MAX_STEPS_REACHED, outcome.status)
        assertEquals(2, outcome.steps.size)
        assertTrue(outcome.summary.contains("2"))
    }

    @Test
    fun `converts adapter exception into failed outcome`() {
        val runtime = AgentRuntime(
            brain = FixedBrain(),
            device = object : DeviceAdapter {
                override val adapterName = "BrokenAdapter"
                override fun observe(): Observation = error("camera unavailable")
                override fun execute(action: AgentAction) = ExecutionResult(true, "unused")
            },
            verifier = ResultVerifier { _, _, _, _, _ -> error("unused") },
        )

        val outcome = runtime.run(AgentTask("task-4", "fail safely"))

        assertEquals(OutcomeStatus.FAILED, outcome.status)
        assertTrue(outcome.summary.contains("camera unavailable"))
    }

    @Test
    fun `user can stop a running task while it is paused`() {
        CompanionExecutionControl.beginTask()
        assertTrue(CompanionExecutionControl.pauseByUser())
        CompanionExecutionControl.stopTask()

        assertEquals(
            CompanionExecutionControl.Permission.STOPPED,
            CompanionExecutionControl.awaitPermission(),
        )
        CompanionExecutionControl.finishTask()
    }

    private class FixedBrain : BrainClient {
        override fun decide(task: AgentTask, context: BrainContext) = BrainDecision(
            AgentAction.Tap(ActionTarget.Coordinate(10, 20)),
            "tap",
        )
    }

    private class RecordingDeviceAdapter : DeviceAdapter {
        override val adapterName = "RecordingAdapter"
        val actions = mutableListOf<AgentAction>()
        private var sequence = 0L

        override fun observe() = Observation(sequence = ++sequence)

        override fun execute(action: AgentAction): ExecutionResult {
            actions += action
            return ExecutionResult(true, "ok")
        }
    }
}
