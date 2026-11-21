package top.ponychat.companion.overlay

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OverlayVisibilityPolicyTest {
    @Test
    fun foregroundHostStaysHiddenDuringAgentInputAndNewTasks() {
        val policy = OverlayVisibilityPolicy().apply { hostAllowsOverlay = false }
        assertFalse(policy.apply(AgentOverlayState(agentInputActive = true)).overlayVisible)
        assertFalse(policy.apply(AgentOverlayState(phase = AgentOverlayPhase.OBSERVING)).overlayVisible)
    }

    @Test
    fun returningToBackgroundAllowsTaskOverlayAgain() {
        val policy = OverlayVisibilityPolicy().apply { hostAllowsOverlay = false }
        val hidden = policy.apply(AgentOverlayState())
        policy.hostAllowsOverlay = true
        assertTrue(policy.apply(hidden.copy(overlayVisible = true)).overlayVisible)
    }

    @Test
    fun backgroundDoesNotOverrideAnExplicitlyHiddenTask() {
        assertFalse(OverlayVisibilityPolicy().apply(AgentOverlayState(overlayVisible = false)).overlayVisible)
    }
}
