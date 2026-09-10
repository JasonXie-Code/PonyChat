package top.ponychat.webview.data.model

import com.google.gson.annotations.SerializedName

data class RelationshipControlRequest(
    val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("relationship_mode") val relationshipMode: String,
    @SerializedName("relationship_stage") val relationshipStage: String? = null,
)
