package top.ponychat.webview.ui.chat

/** Only sending a new user message may allocate an ID; an empty history is not a new conversation. */
internal fun normalHistoryConversationId(serverId: String?, requestedId: String?): String? =
    serverId?.takeIf { it.isNotBlank() } ?: requestedId?.takeIf { it.isNotBlank() }

internal fun ChatUiState.afterNormalReset(serverConversationId: String?): ChatUiState = copy(
    messages = emptyList(),
    conversationId = serverConversationId?.takeIf { it.isNotBlank() },
    inputText = "",
    isStreaming = false,
    isLoadingHistory = false,
    isLoadingMoreHistory = false,
    isBackgroundRefreshing = false,
    minLoadedSeq = Int.MAX_VALUE,
    hasMoreHistory = false,
    error = null,
    errorDebug = null,
    quotedMessage = null,
    relationshipSnapshot = null,
    relationshipStageOverride = null,
    hasLoadedRelationshipSnapshot = false,
    isLoadingRelationshipSnapshot = false,
    relationshipSnapshotError = null,
)
