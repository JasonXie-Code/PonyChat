package top.ponychat.webview.data.model

import com.google.gson.annotations.SerializedName

data class AgentStatusResponse(
    val success: Boolean = false,
    val agent: AgentRunStatus? = null,
    val agents: List<AgentRunStatus> = emptyList(),
    @SerializedName("conversation_activity") val conversationActivity: ConversationActivity? = null,
)

data class ConversationActivity(
    val state: String = "unavailable",
    @SerializedName("server_now_ms") val serverNowMs: Long = 0,
    @SerializedName("due_at_ms") val dueAtMs: Long = 0,
    @SerializedName("expires_at_ms") val expiresAtMs: Long = 0,
    @SerializedName("proactive_enabled") val proactiveEnabled: Boolean? = null,
    @SerializedName("memory_enabled") val memoryEnabled: Boolean? = null,
    @SerializedName("cancel_if_user_replies") val cancelIfUserReplies: Boolean = true,
    @SerializedName("consecutive_count") val consecutiveCount: Int = 0,
    @SerializedName("consecutive_limit") val consecutiveLimit: Int = 0,
)

data class AgentRunStatus(
    @SerializedName("run_id") val runId: String = "",
    val status: String = "",
    val activity: String = "",
    val model: String = "",
    val phase: String = "foreground",
    val mode: String = "normal",
    @SerializedName("current_tools") val currentTools: List<String> = emptyList(),
    @SerializedName("recent_tools") val recentTools: List<String> = emptyList(),
    @SerializedName("model_calls") val modelCalls: Int = 0,
    @SerializedName("tool_calls") val toolCalls: Int = 0,
    val points: Int = 0,
    @SerializedName("elapsed_ms") val elapsedMs: Long = 0,
)
