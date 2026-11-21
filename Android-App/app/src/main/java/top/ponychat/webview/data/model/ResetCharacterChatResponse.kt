package top.ponychat.webview.data.model

import com.google.gson.annotations.SerializedName

data class ResetCharacterChatResponse(
    val status: String,
    val success: Boolean,
    @SerializedName("conversation_id") val conversationId: String? = null,
)
