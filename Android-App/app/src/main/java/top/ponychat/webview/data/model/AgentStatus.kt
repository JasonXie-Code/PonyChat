package top.ponychat.webview.data.model

import com.google.gson.annotations.SerializedName

data class AgentStatusResponse(
    val success: Boolean = false,
    val agent: AgentRunStatus? = null,
    val agents: List<AgentRunStatus> = emptyList(),
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
