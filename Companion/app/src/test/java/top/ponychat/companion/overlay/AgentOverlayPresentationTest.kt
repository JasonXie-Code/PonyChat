package top.ponychat.companion.overlay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentOverlayPresentationTest {
    @Test
    fun `agent input state is independent from planning phase`() {
        val observing = AgentOverlayState(
            phase = AgentOverlayPhase.OBSERVING,
            agentInputActive = false,
        )
        val idleGesture = AgentOverlayState(
            phase = AgentOverlayPhase.IDLE,
            agentInputActive = true,
        )

        assertFalse(observing.agentInputActive)
        assertTrue(idleGesture.agentInputActive)
    }

    @Test
    fun `presentation exposes auditable stages instead of raw hidden reasoning`() {
        val state = AgentOverlayState(
            phase = AgentOverlayPhase.EXECUTING,
            currentStep = 2,
            totalSteps = 5,
        )

        assertEquals("步骤 2/5 · 执行操作", AgentOverlayPresentation.progressLabel(state))
        assertEquals(
            listOf("✓ 观察当前界面", "✓ 选择下一步动作", "▶ 执行设备操作", "○ 检查结果并纠错"),
            AgentOverlayPresentation.planLines(state),
        )
    }

    @Test
    fun `summary redacts secrets and limits unbounded model text`() {
        val summary = AgentOverlayPresentation.safeSummary("api_key=secret-value " + "a".repeat(300))

        assertFalse(summary.contains("secret-value"))
        assertTrue(summary.endsWith("…"))
        assertTrue(summary.length <= 140)
    }
}
