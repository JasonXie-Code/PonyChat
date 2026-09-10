package top.ponychat.webview.ui.chat

internal fun ChatViewModel.relationshipControlChanged() {
    relationshipSnapshotJob?.cancel()
    _state.value = _state.value.copy(
        relationshipSnapshot = null,
        relationshipStageOverride = null,
        hasLoadedRelationshipSnapshot = false,
        isLoadingRelationshipSnapshot = false,
        relationshipSnapshotError = null,
    )
    loadRelationshipSnapshot()
}
