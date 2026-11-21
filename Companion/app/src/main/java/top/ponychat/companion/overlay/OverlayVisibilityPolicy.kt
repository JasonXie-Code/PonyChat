package top.ponychat.companion.overlay

/** Host lifecycle visibility remains authoritative over task/input status updates. */
internal class OverlayVisibilityPolicy {
    var hostAllowsOverlay: Boolean = true

    fun apply(state: AgentOverlayState): AgentOverlayState =
        state.copy(overlayVisible = state.overlayVisible && hostAllowsOverlay)
}
