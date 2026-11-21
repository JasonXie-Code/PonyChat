package top.ponychat.webview.data.model

import com.google.gson.annotations.SerializedName

data class BooruSearchRequest(
    val username: String,
    val query: String,
    val mode: String,
    val rating: String,
    val sort: String,
    val page: Int,
)

data class BooruImage(
    val id: String,
    val source: String,
    val tags: List<String> = emptyList(),
    val url: String,
    @SerializedName("image_url") val imageUrl: String,
    @SerializedName("preview_url") val previewUrl: String? = null,
    val score: Int = 0,
    val rating: String,
    @SerializedName("published_at") val publishedAt: String? = null,
    val animated: Boolean = false,
    val video: Boolean = false,
)

data class BooruSearchResponse(
    val status: String,
    val tags: List<String> = emptyList(),
    val rating: String,
    val sort: String,
    val page: Int,
    @SerializedName("has_more") val hasMore: Boolean = true,
    val sources: List<String> = emptyList(),
    val images: List<BooruImage> = emptyList(),
)
