package top.ponychat.webview.data.model

import androidx.compose.runtime.Immutable
import com.google.gson.annotations.SerializedName

// ==================== 用户相关 ====================

data class User(
    val username: String,
    val role: String = "user",
    val gender: String = "male",
    val nickname: String = "",
    val avatar: String = "",
    val createdAt: String = "",
    val birthDate: String = "",
    val species: String = "人类",
    val bio: String = "",
    val shareWithAi: Boolean = true
)

data class LoginRequest(
    @SerializedName("username") val username: String,
    @SerializedName("password") val password: String
)

data class RegisterRequest(
    @SerializedName("username") val username: String,
    @SerializedName("password") val password: String,
    @SerializedName("gender") val gender: String,
    @SerializedName("birth_date") val birthDate: String,
    @SerializedName("invite_code") val inviteCode: String,
    @SerializedName("avatar") val avatar: String? = null
)

data class LoginResponse(
    val status: String,
    val success: Boolean,
    @SerializedName("auth_token") val authToken: String? = null,
    val user: UserInfo? = null,
    val message: String? = null
)

data class UserInfo(
    val username: String,
    val role: String = "user",
    val gender: String = "male"
)

data class ProfileResponse(
    val status: String,
    val success: Boolean,
    val profile: ProfileData? = null
)

data class ProfileData(
    val username: String,
    val gender: String = "male",
    val nickname: String = "",
    val avatar: String = "",
    @SerializedName("created_at") val createdAt: String = "",
    @SerializedName("birth_date") val birthDate: String = "",
    val age: Int? = null,
    @SerializedName("species_preset") val speciesPreset: String = "人类",
    @SerializedName("species_custom") val speciesCustom: String = "",
    val species: String = "人类",
    val bio: String = "",
    @SerializedName("personal_setting") val personalSetting: String = "",
    @SerializedName("share_with_ai") val shareWithAi: Boolean = true
)

// ==================== 角色相关 ====================

@Immutable
data class QuickMessage(
    val id: Int = 0,
    val title: String = "",
    val content: String = "",
    @SerializedName("sort_order") val sortOrder: Int = 0,
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null
)

data class QuickMessageListResponse(
    val status: String = "ok",
    val messages: List<QuickMessage> = emptyList()
)

data class QuickMessageCreateRequest(
    val username: String,
    val title: String = "",
    val content: String
)

data class QuickMessageUpdateRequest(
    val username: String,
    val title: String = "",
    val content: String,
    @SerializedName("sort_order") val sortOrder: Int? = null
)

data class QuickMessageDeleteRequest(
    val username: String
)

@Immutable
data class Character(
    val id: String?,
    val name: String?,
    val description: String? = "",
    val bio: String? = "",
    val avatar: String? = "",
    val prompt: String? = "",
    val preview: String? = "",
    @SerializedName("profileCover") val profileCover: String? = "",
    @SerializedName("profilePhotos") val profilePhotos: List<String>? = emptyList(),
    @SerializedName(value = "profileGender", alternate = ["profile_gender"]) val profileGender: String? = "",
    @SerializedName(value = "profileSpecies", alternate = ["profile_species"]) val profileSpecies: String? = "",
    @SerializedName(value = "profileAge", alternate = ["profile_age"]) val profileAge: String? = "",
    @SerializedName("profilePersonality") val profilePersonality: String? = "",
    @SerializedName("profileInterests") val profileInterests: String? = "",
    @SerializedName(value = "profileIntro", alternate = ["profile_intro"]) val profileIntro: String? = "",
    @SerializedName("profileMbti") val profileMbti: String? = "",
    @SerializedName(value = "voiceEnabled", alternate = ["voice_enabled"]) val voiceEnabled: Boolean? = null,
    @SerializedName(value = "voiceId", alternate = ["voice_id"]) val voiceId: String? = "",
    @SerializedName(value = "voiceInstruct", alternate = ["voice_instruct"]) val voiceInstruct: String? = "",
    @SerializedName(value = "voiceDecisionPolicy", alternate = ["voice_decision_policy"]) val voiceDecisionPolicy: String? = "director",
    @SerializedName(value = "voiceSourceMode", alternate = ["voice_source_mode"]) val voiceSourceMode: String? = "voice_id",
    @SerializedName(value = "voiceBaseVoiceId", alternate = ["voice_base_voice_id"]) val voiceBaseVoiceId: String? = "",
    @SerializedName(value = "voiceReferenceAudioUrl", alternate = ["voice_reference_audio_url"]) val voiceReferenceAudioUrl: String? = "",
    @SerializedName(value = "voiceReferenceText", alternate = ["voice_reference_text"]) val voiceReferenceText: String? = "",
    @SerializedName(value = "voiceProfileId", alternate = ["voice_profile_id"]) val voiceProfileId: String? = "",
    @SerializedName(value = "voiceCloneStatus", alternate = ["voice_clone_status"]) val voiceCloneStatus: String? = "",
    /** 已废弃：服务端不再注入，同步时恒为空；仅保留键以兼容旧 JSON。 */
    val instruction: String? = "",
    val tags: List<String>? = emptyList(),
    @SerializedName("isDefault") val isDefault: Boolean = false,
    @SerializedName("isPublic") val isPublic: Boolean = false,
    @SerializedName("publishedAt") val publishedAt: String? = "",
    @SerializedName("timesAdded") val timesAdded: Int? = 0,
    @SerializedName("likeCount") val likeCount: Int? = 0,
    @SerializedName("likedToday") val likedToday: Boolean? = false,
    val owner: String? = "",
    @SerializedName("owner_raw") val ownerRaw: String? = "",
    @SerializedName("publicOwner") val publicOwner: String? = "",
    @SerializedName("addedFrom") val addedFrom: String? = "",
    val model: String? = null,
    val temperature: Double? = null,
    val updatedAt: String? = "",
    val jailbreak: Boolean = false,
    @SerializedName("lastChatTime") val lastChatTime: String? = null,
    /** 角色内容哈希，服务端计算，用于大厅「已添加」判断 */
    @SerializedName("contentHash") val contentHash: String? = null,
    /** 已发布到大厅时的大厅条目 ID */
    @SerializedName("hallId") val hallId: String? = null,
    /** 从大厅添加时的来源大厅条目 ID（服务端注入） */
    @SerializedName("sourceId") val sourceId: String? = null,
    @SerializedName("originalId") val originalId: String? = null,
    /** 源角色内容哈希快照，由服务端自动同步维护 */
    @SerializedName("sourceContentHash") val sourceContentHash: String? = null,
    /** 大厅源当前内容哈希；引用角色由服务端自动同步 */
    @SerializedName("latestSourceContentHash") val latestSourceContentHash: String? = null,
    /** 官方引用角色的 System 唯一源 ID，例如 twilight_sparkle */
    @SerializedName("officialSourceId") val officialSourceId: String? = null,
    /** true 表示该条目不能直接编辑，内容来自官方源 */
    @SerializedName("isOfficialReference") val isOfficialReference: Boolean = false,
    @SerializedName("canEdit") val canEdit: Boolean = true,
    /** 是否支持识图（主对话由服务端路由，默认视为支持；仅显式 false 时关闭） */
    @SerializedName("supports_vision") val supportsVision: Boolean? = null,
    /** 兼容旧缓存/管理接口中的隐藏标记。角色列表只应保留可见角色。 */
    @SerializedName(value = "isHidden", alternate = ["is_hidden"]) val isHidden: Boolean? = null,
    @SerializedName("hidden") val hidden: Boolean? = null
) {
    fun stableId(): String = id?.takeIf { it.isNotBlank() } ?: "character_${hashCode()}"
    fun displayName(): String = name?.takeIf { it.isNotBlank() } ?: "未命名角色"
    fun effectivePrompt(): String = prompt?.takeIf { it.isNotBlank() } ?: ""
    fun isSystemPublished(): Boolean =
        ownerRaw?.trim()?.equals("System", ignoreCase = true) == true ||
            owner?.trim()?.equals("System", ignoreCase = true) == true ||
            publicOwner?.trim()?.equals("System", ignoreCase = true) == true ||
            addedFrom?.trim()?.equals("System", ignoreCase = true) == true
    fun isEditBlockedFor(username: String): Boolean =
        !username.trim().equals("System", ignoreCase = true) &&
            (isSystemPublished() || isLockedOfficialReference())
    fun isLockedOfficialReference(): Boolean =
        isOfficialReference || officialSourceId?.isNotBlank() == true || canEdit == false
    fun displayDescription(): String {
        val previewText = preview?.takeIf { it.isNotBlank() } ?: ""
        val introText = profileIntro?.takeIf { it.isNotBlank() } ?: ""
        val bioText = bio?.takeIf { it.isNotBlank() } ?: ""
        val descText = description?.takeIf { it.isNotBlank() } ?: ""
        return previewText.ifBlank { introText }.ifBlank { bioText }.ifBlank { descText }.ifBlank { "暂无简介" }
    }
    /** 有效头像地址：空、null、以及服务端约定的默认图路径均视为无头像，由客户端用首字符展示。 */
    fun avatarUrl(): String = avatar?.takeIf {
        it.isNotBlank() &&
        !it.equals("null", ignoreCase = true) &&
        !it.lowercase().let { p -> p == "default.png" || p.endsWith("/default.png") }
    } ?: ""
    fun safeTags(): List<String> = tags?.filter { it.isNotBlank() } ?: emptyList()
    fun safeProfilePhotos(): List<String> = profilePhotos?.filter { it.isNotBlank() } ?: emptyList()
    /** 主对话经智能路由后默认可用视觉；仅后端/角色显式关闭时为 false */
    fun effectiveSupportsVision(): Boolean = supportsVision != false
}

data class LoadCharactersResponse(
    val status: String,
    val characters: List<Character> = emptyList(),
    val messages: Map<String, Any> = emptyMap()
)

// ==================== 消息/对话相关 ====================

@Immutable
data class MessageVoiceState(
    @SerializedName("voice_status") val status: String = "disabled",
    @SerializedName("voice_id") val voiceId: String? = null,
    @SerializedName("voice_job_id") val voiceJobId: String? = null,
    @SerializedName("voice_cache_key") val voiceCacheKey: String? = null,
    @SerializedName("tts_text") val ttsText: String? = null,
    val transcript: String? = null,
    @SerializedName("text_fragments") val textFragments: List<String> = emptyList(),
    @SerializedName("voice_error") val voiceError: String? = null,
    @SerializedName("duration_ms") val durationMs: Long? = null,
    @SerializedName("local_file") val localFile: String? = null,
    val waveform: List<Float> = emptyList(),
    @SerializedName("debug_playable") val debugPlayable: Boolean = false
) {
    fun hasLocalAudio(): Boolean =
        status.equals("ready", ignoreCase = true) &&
            (debugPlayable || !localFile.isNullOrBlank())

    fun readableText(fallback: String = ""): String =
        transcript?.takeIf { it.isNotBlank() }
            ?: ttsText?.takeIf { it.isNotBlank() }
            ?: fallback
}

/** UI 层消息模型，标记为 @Immutable 以允许 Compose 跳过未变化消息的重组（提升 LazyColumn 滚动性能）*/
@Immutable
data class Message(
    val id: String = java.util.UUID.randomUUID().toString(),
    val role: String, // "user" | "assistant"
    val content: String,
    val timestamp: Long = System.currentTimeMillis(),
    val isStreaming: Boolean = false,
    val isError: Boolean = false,
    @SerializedName("generation_duration_ms") val generationDurationMs: Long? = null,
    @SerializedName("message_id") val messageId: String? = null,
    @SerializedName("sequence_number") val sequenceNumber: Int? = null,
    /** 游戏/锁分模式：助手消息展示用 HTML，优先于 content */
    val displayContent: String? = null,
    /** 游戏/锁分模式：整轮结果 JSON，场景字段唯一真源（UI 与解析均优先从此取） */
    val rawContent: String? = null,
    @Deprecated("服务端不再返回；仅旧本地缓存 Gson 可能含此键，勿使用")
    val sceneMetadata: Map<String, Any?>? = null,
    /** 游戏/锁分模式：选项列表（与 Web galgameOptions 一致，label/type/tone） */
    val galgameOptions: List<GalgameOptionItem> = emptyList(),
    @SerializedName("quoted_message") val quotedMessage: QuotedMessage? = null,
    val attachments: List<MessageAttachment> = emptyList(),
    @SerializedName("voice_state") val voiceState: MessageVoiceState? = null,
    @SerializedName("speaker_character_id") val speakerCharacterId: String? = null,
    @SerializedName("speaker_name") val speakerName: String? = null,
    @SerializedName("speaker_avatar") val speakerAvatar: String? = null,
    /** 同一轮 normal 回复拆成多条可见气泡时的位置；用于避免同批后续气泡反复自动滚动。 */
    @SerializedName("auto_scroll_batch_index") val autoScrollBatchIndex: Int? = null,
    @SerializedName("auto_scroll_batch_total") val autoScrollBatchTotal: Int? = null,
    @SerializedName("allow_realtime_animation") val allowRealtimeAnimation: Boolean = true,
    /** UI-only：普通模式用户消息已本地显示，但尚未收到服务端 accepted 事件。 */
    val isPendingServerAccept: Boolean = false,
    /** UI-only：待服务端接受状态的起始时间，用于 10 秒超时提示。 */
    val pendingServerAcceptStartedAt: Long = 0L,
    /** 用户消息是否已被撤回：撤回后隐藏 UI 原文，后续上下文只保留「撤回了消息」提示。*/
    val isRetracted: Boolean = false
) {
    fun isUser() = role == "user"
    fun isAssistant() = role == "assistant"
}

@Immutable
data class QuotedMessage(
    @SerializedName("message_id") val messageId: String? = null,
    val role: String = "",
    val sender: String = "",
    val content: String = "",
    val timestamp: Long? = null,
    @SerializedName("speaker_character_id") val speakerCharacterId: String? = null,
    @SerializedName("speaker_name") val speakerName: String? = null,
    @SerializedName("speaker_avatar") val speakerAvatar: String? = null
)

/** 游戏/锁分模式单条选项（与 Web 端一致：label 必填，type 为 dialogue|action） */
@Immutable
data class GalgameOptionItem(
    val label: String = "",
    val type: String = "dialogue",
    val tone: String = ""
)

data class ChatMessage(
    val role: String,
    val content: String,
    @SerializedName("message_id") val messageId: String? = null,
    @SerializedName("sequence_number") val sequenceNumber: Int? = null,
    val timestamp: Long? = null,
    @SerializedName("generation_duration_ms") val generationDurationMs: Long? = null,
    /** 隐藏消息：发送给后端但不在 UI 中展示（与 Web isHidden 一致） */
    @SerializedName(value = "isHidden", alternate = ["is_hidden"]) val isHidden: Boolean? = null,
    /** 游戏/锁分模式：助手消息的完整 HTML 展示内容（含时间/地点标签），优先于 content 用于展示 */
    val displayContent: String? = null,
    /** 游戏/锁分模式：整轮结果 JSON，场景真源 */
    val rawContent: String? = null,
    @Deprecated("服务端不再返回；仅旧缓存反序列化")
    val sceneMetadata: Map<String, Any?>? = null,
    /** 游戏/锁分模式：选项列表，每项为 { "label", "type", "tone" }，后端键为 galgameOptions */
    val galgameOptions: List<Any>? = null,
    @SerializedName("quoted_message") val quotedMessage: QuotedMessage? = null,
    val attachments: List<MessageAttachment>? = null,
    @SerializedName("voice_state") val voiceState: MessageVoiceState? = null,
    @SerializedName("voice_status") val voiceStatus: String? = null,
    @SerializedName("voice_id") val voiceId: String? = null,
    @SerializedName("voice_job_id") val voiceJobId: String? = null,
    @SerializedName("voice_cache_key") val voiceCacheKey: String? = null,
    @SerializedName("tts_text") val ttsText: String? = null,
    val transcript: String? = null,
    @SerializedName("text_fragments") val textFragments: List<String>? = null,
    @SerializedName("voice_error") val voiceError: String? = null,
    @SerializedName("duration_ms") val voiceDurationMs: Long? = null,
    @SerializedName("local_file") val voiceLocalFile: String? = null,
    val waveform: List<Float>? = null,
    @SerializedName("debug_playable") val voiceDebugPlayable: Boolean? = null,
    @SerializedName("speaker_character_id") val speakerCharacterId: String? = null,
    @SerializedName("speaker_name") val speakerName: String? = null,
    @SerializedName("speaker_avatar") val speakerAvatar: String? = null
)

@Immutable
data class VoiceAudioTransfer(
    val kind: String = "",
    val mime: String? = null,
    val variant: String? = null,
    @SerializedName("data_base64") val dataBase64: String? = null,
    val url: String? = null,
    @SerializedName("expires_hint_seconds") val expiresHintSeconds: Int? = null
)

@Immutable
data class VoiceMessagePatch(
    @SerializedName("voice_status") val voiceStatus: String? = null,
    @SerializedName("voice_id") val voiceId: String? = null,
    @SerializedName("voice_job_id") val voiceJobId: String? = null,
    @SerializedName("voice_cache_key") val voiceCacheKey: String? = null,
    @SerializedName("tts_text") val ttsText: String? = null,
    val transcript: String? = null,
    @SerializedName("text_fragments") val textFragments: List<String>? = null,
    @SerializedName("voice_error") val voiceError: String? = null,
    @SerializedName("duration_ms") val durationMs: Long? = null,
    @SerializedName("local_file") val localFile: String? = null,
    val waveform: List<Float>? = null,
    @SerializedName("debug_playable") val debugPlayable: Boolean? = null,
    @SerializedName("audio_transfer") val audioTransfer: VoiceAudioTransfer? = null
) {
    fun toVoiceState(): MessageVoiceState = MessageVoiceState(
        status = voiceStatus?.takeIf { it.isNotBlank() } ?: "disabled",
        voiceId = voiceId,
        voiceJobId = voiceJobId,
        voiceCacheKey = voiceCacheKey,
        ttsText = ttsText,
        transcript = transcript,
        textFragments = textFragments.orEmpty(),
        voiceError = voiceError,
        durationMs = durationMs,
        localFile = localFile,
        waveform = waveform.orEmpty(),
        debugPlayable = debugPlayable == true
    )
}

@Immutable
data class MessageVoiceUpdate(
    @SerializedName("character_id") val characterId: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("message_id") val messageId: String? = null,
    @SerializedName("updated_at_ms") val updatedAtMs: Long? = null,
    val patch: VoiceMessagePatch? = null
)

data class VoiceSynthesizeResponse(
    val status: String = "",
    val success: Boolean = false,
    @SerializedName("voice_state") val voiceState: MessageVoiceState? = null,
    @SerializedName("audio_transfer") val audioTransfer: VoiceAudioTransfer? = null,
    val error: String? = null,
    val message: String? = null
)

@Immutable
data class MessageAttachment(
    val id: String = "",
    val type: String = "sticker",
    @SerializedName("asset_id") val assetId: String? = null,
    @SerializedName("user_sticker_id") val userStickerId: String? = null,
    val url: String? = null,
    val name: String = "",
    val width: Int? = null,
    val height: Int? = null,
    val metadata: Map<String, Any?>? = null
)

@Immutable
data class StickerAsset(
    val id: String = "",
    val source: String = "platform",
    @SerializedName("asset_id") val assetId: String? = null,
    @SerializedName("user_sticker_id") val userStickerId: String? = null,
    val name: String = "",
    val category: String = "sticker",
    @SerializedName("file_url") val fileUrl: String = "",
    val intro: String = "",
    val detail: String = "",
    @SerializedName("image_text") val imageText: String = "",
    @SerializedName("identified_entities") val identifiedEntities: List<String> = emptyList(),
    val depiction: String = "",
    @SerializedName("safety_notes") val safetyNotes: String = "",
    val uncertainty: String = "",
    val tagging: Map<String, Any?> = emptyMap(),
    @SerializedName("custom_tags") val customTags: List<String> = emptyList(),
    @SerializedName("is_animated") val isAnimated: Boolean = false,
    @SerializedName("allow_user_save") val allowUserSave: Boolean = true,
    val emotions: List<String> = emptyList(),
    val scenes: List<String> = emptyList(),
    val intensity: String = "moderate",
    @SerializedName("age_rating") val ageRating: String = "all",
    @SerializedName("flirt_level") val flirtLevel: Int = 0,
    @SerializedName("send_policy") val sendPolicy: String = "response_only",
    @SerializedName("min_relationship_stage") val minRelationshipStage: String = "stranger",
    @SerializedName("sender_archetypes") val senderArchetypes: List<String> = emptyList(),
    @SerializedName("blocked_archetypes") val blockedArchetypes: List<String> = emptyList()
) {
    fun toAttachment(): MessageAttachment = MessageAttachment(
        type = "sticker",
        assetId = assetId,
        userStickerId = userStickerId,
        url = fileUrl,
        name = name
    )
}

data class StickerListResponse(
    val status: String = "ok",
    val items: List<StickerAsset> = emptyList(),
    val page: Int = 1,
    @SerializedName("page_size") val pageSize: Int = 60
)

data class StickerSaveRequest(
    @SerializedName("asset_id") val assetId: String
)

data class StickerSaveResponse(
    val status: String = "ok",
    val item: StickerAsset? = null,
    val deduped: Boolean = false
)

data class Conversation(
    val id: String,
    @SerializedName("character_id") val characterId: String,
    val title: String = "",
    val messages: List<Message> = emptyList(),
    @SerializedName("context_summary") val contextSummary: String = "",
    @SerializedName("updated_at") val updatedAt: String = ""
)

data class ConversationDetailResponse(
    val status: String,
    val success: Boolean,
    val conversation: ConversationDetailData? = null,
    val conversations: List<ConversationDetailData>? = null,
    /** 游戏/锁分模式时后端在顶层返回 messages，不放在 conversation 里 */
    val messages: List<ChatMessage>? = null,
    val usage: ConversationUsage? = null,
    /** 游戏/锁分模式时后端在顶层返回当前好感度分数 (0-100) */
    val score: Int? = null,
    /** 1=已向用户展示过满分庆祝弹窗（跨设备持久） */
    @SerializedName("victory_celebration_ack") val victoryCelebrationAck: Int? = null,
    /** 游戏/锁分模式：playing | win | lose */
    @SerializedName("game_status") val gameStatus: String? = null,
    /** 锁分模式专属：生命体征（初始加载时填充面板） */
    @SerializedName("char_vitals")       val charVitals:      Map<String, Int>? = null,
    @SerializedName("char_mood")         val charMood:        Map<String, Int>? = null,
    @SerializedName("organ_fill")        val organFill:       Map<String, Int>? = null,
    @SerializedName("character_gender")  val characterGender: String? = null
)

data class ConversationUsage(
    @SerializedName("total_tokens") val totalTokens: Int = 0,
    @SerializedName("limit_tokens") val limitTokens: Int = 256000
)

data class ConversationDetailData(
    val id: String = "",
    @SerializedName("character_id") val characterId: String = "",
    val title: String = "",
    @SerializedName("timestamp") val timestamp: Long = 0L,
    val messages: List<ChatMessage> = emptyList(),
    @SerializedName("context_summary") val contextSummary: String = "",
    @SerializedName("contextSummary") val contextSummary2: String = "",
    @SerializedName("updated_at") val updatedAt: String = ""
) {
    fun effectiveSummary() = contextSummary.ifBlank { contextSummary2 }
}

// ==================== 客户端环境上下文 ====================

/**
 * 每次聊天/陪玩请求时随请求上报，供后端注入 AI 系统提示。
 * 所有字段均为 nullable：客户端能收集到什么就发什么，后端忽略 null 字段。
 */
data class ClientContext(
    /** ISO 8601 带时区，e.g. "2026-03-05T19:34:00+08:00" */
    @SerializedName("time_iso") val timeIso: String? = null,
    /** 设备型号，e.g. "小米 14 Pro" */
    @SerializedName("device_model") val deviceModel: String? = null,
    /** Android 版本，e.g. "Android 15" */
    @SerializedName("os_version") val osVersion: String? = null,
    /** 电量百分比 0-100 */
    val battery: Int? = null,
    /** 连接类型，e.g. "WiFi", "移动网络" */
    val network: String? = null,
    /** 逆地理编码地名，e.g. "北京市朝阳区" */
    @SerializedName("location_name") val locationName: String? = null,
    /** 天气描述，e.g. "晴", "多云", "小雨" */
    @SerializedName("weather_desc") val weatherDesc: String? = null,
    /** 气温（摄氏度） */
    val temperature: Int? = null,
    /** 厂商UI系统，e.g. "MIUI 14", "HyperOS 2.0", "OneUI 6.1", "ColorOS 14" */
    @SerializedName("os_flavor") val osFlavor: String? = null,
    /** 导航方式："gesture"（全面屏手势）| "3button"（三键）| "2button"（两键） */
    @SerializedName("nav_mode") val navMode: String? = null
)

// ==================== 聊天请求 ====================

data class ChatRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("messages") val messages: List<ChatMessage>,
    @SerializedName("mode") val mode: String = "normal",
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("context_summary") val contextSummary: String? = null,
    @SerializedName("is_summary_request") val isSummaryRequest: Boolean = false,
    @SerializedName("client_id") val clientId: String? = null,
    // 长期记忆功能开关（用户可在设置中关闭）
    @SerializedName("memory_enabled") val memoryEnabled: Boolean? = true,
    // 危机热线显示开关
    @SerializedName("crisis_hotline_enabled") val crisisHotlineEnabled: Boolean? = true,
    // 客户端环境上下文（时间/设备/位置/天气）
    @SerializedName("client_context") val clientContext: ClientContext? = null,
    @SerializedName("reply_character_id") val replyCharacterId: String? = null,
    @SerializedName("reply_character_ids") val replyCharacterIds: List<String>? = null
)

// ==================== 版本更新 ====================

data class AppVersionResponse(
    @SerializedName("version_name") val versionName: String,
    @SerializedName("version_code") val versionCode: Int,
    @SerializedName("download_url") val downloadUrl: String
)

// SSE chunk: {"choices":[{"delta":{"content":"..."}}]}
data class SseChunk(
    val choices: List<SseChoice>? = null,
    val error: String? = null,
    val metadata: Map<String, Any?>? = null,
    @SerializedName("job_id") val jobId: String? = null
)

data class SseChoice(
    val delta: SseDelta? = null,
    val index: Int = 0
)

data class SseDelta(
    val content: String? = null,
    val role: String? = null
)

// ==================== 网络连接信息 ====================

data class ConnectionInfo(
    @SerializedName("lan_url") val lanUrl: String? = null,
    @SerializedName("lan_ip") val lanIp: String? = null,
    val port: Int? = null
)

/** POST /api/chat_images 成功响应，用于聊天前上传图片、消息内只带短 URL */
data class ChatImageUploadResponse(
    val url: String
)

/** POST /api/character_voice/reference_audio 成功响应，用于角色音色参考音频资产 */
data class CharacterVoiceReferenceUploadResponse(
    val url: String,
    val filename: String? = null,
    @SerializedName("mime_type") val mimeType: String? = null,
    @SerializedName("size_bytes") val sizeBytes: Long? = null,
    val transcript: String? = null,
    @SerializedName(value = "voiceId", alternate = ["voice_id"]) val voiceId: String? = null,
    @SerializedName(value = "voiceProfileId", alternate = ["voice_profile_id"]) val voiceProfileId: String? = null,
    @SerializedName(value = "cloneStatus", alternate = ["clone_status"]) val cloneStatus: String? = null,
    @SerializedName(value = "cloneError", alternate = ["clone_error"]) val cloneError: String? = null
)

data class CharacterVoiceDesignRequest(
    @SerializedName("character_id") val characterId: String = "",
    @SerializedName("character_name") val characterName: String = "",
    @SerializedName("voice_id") val voiceId: String = "",
    val instruct: String = "",
    val action: String = "preview"
)

data class CharacterVoiceDesignResponse(
    val status: String = "",
    val success: Boolean = false,
    @SerializedName(value = "voiceId", alternate = ["voice_id"]) val voiceId: String? = null,
    @SerializedName(value = "voiceProfileId", alternate = ["voice_profile_id"]) val voiceProfileId: String? = null,
    @SerializedName(value = "voiceInstruct", alternate = ["voice_instruct"]) val voiceInstruct: String? = null,
    @SerializedName(value = "designStatus", alternate = ["design_status"]) val designStatus: String? = null,
    val generated: Boolean? = null,
    @SerializedName(value = "testText", alternate = ["test_text"]) val testText: String? = null,
    @SerializedName(value = "audioTransfer", alternate = ["audio_transfer"]) val audioTransfer: VoiceAudioTransfer? = null,
    @SerializedName(value = "previewError", alternate = ["preview_error"]) val previewError: String? = null,
    val message: String? = null
)

// ==================== 角色大厅 ====================

data class CharacterHallResponse(
    val status: String,
    val characters: List<Character> = emptyList()
)

data class CharacterLikeResponse(
    val status: String = "success",
    val message: String? = null,
    @SerializedName("likeCount") val likeCount: Int = 0,
    @SerializedName("likedToday") val likedToday: Boolean = false
)

// ==================== 保存角色 ====================

/** 单条对话的保存结构，与后端 save_characters 期望的格式一致 */
data class ConversationSavePayload(
    val id: String,
    val messages: List<ChatMessage>,
    val title: String = "",
    val timestamp: Long = System.currentTimeMillis()
)

data class SaveCharactersRequest(
    @SerializedName("username") val username: String,
    @SerializedName("characters") val characters: List<Character>,
    @SerializedName("conversations") val conversations: Map<String, List<ConversationSavePayload>>? = null,
    @SerializedName("partially_synced_characters") val partiallySyncedCharacters: List<String>? = null,
    /** 明确要删除的角色 ID 列表，与 save_intent=user_edit 配合，后端只删这些 ID（绕过数量差量保护） */
    @SerializedName("deleted_characters") val deletedCharacters: List<String>? = null,
    @SerializedName("_integrity") val integrity: String = "ok",
    @SerializedName("save_intent") val saveIntent: String = "auto_sync"
)

// ==================== 通用响应 ====================

data class ApiResponse(
    val status: String,
    val success: Boolean,
    val message: String? = null,
    val username: String? = null,
    @SerializedName("auth_token") val authToken: String? = null
)

// ==================== 用户资料更新 ====================

data class UpdateProfileRequest(
    @SerializedName("username") val username: String,
    @SerializedName("current_password") val currentPassword: String? = null,
    val nickname: String? = null,
    val avatar: String? = null,
    val bio: String? = null,
    @SerializedName("personal_setting") val personalSetting: String? = null,
    @SerializedName("species_preset") val speciesPreset: String? = null,
    @SerializedName("species_custom") val speciesCustom: String? = null,
    @SerializedName("birth_date") val birthDate: String? = null,
    @SerializedName("share_with_ai") val shareWithAi: Boolean? = null
)

// ==================== 对话删除 ====================

data class DeleteConversationRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("conversation_id") val conversationId: String
)

// ==================== 角色数据重置（对话+陪玩，不含游戏/锁分） ====================

data class HideMessageRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("conversation_id") val conversationId: String,
    @SerializedName("message_id") val messageId: String,
    @SerializedName("reason") val reason: String? = null
)

data class ResetCharacterChatRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String
)

// ==================== 聊天参数设置 ====================

@Immutable
data class ChatSettings(
    val temperature: Float = 0.7f,
    val maxTokens: Int = 1024,
    val topP: Float = 0.9f,
    val repeatPenalty: Float = 1.1f,
    val topK: Int = 40,
    val reasoningEffort: String = "medium"
)

@Immutable
data class ModelConfigOption(
    val value: String,
    val label: String
)

@Immutable
data class ModelConfigField(
    val key: String,
    val label: String,
    val description: String? = null,
    val type: String,
    val min: Float? = null,
    val max: Float? = null,
    val step: Float? = null,
    @SerializedName("default_bool") val defaultBool: Boolean? = null,
    @SerializedName("default_int") val defaultInt: Int? = null,
    @SerializedName("default_float") val defaultFloat: Float? = null,
    @SerializedName("default_string") val defaultString: String? = null,
    val options: List<ModelConfigOption> = emptyList(),
    val group: String? = null
)

data class ModelOverrideConfig(
    val temperature: Float? = null,
    @SerializedName("max_tokens") val maxTokens: Int? = null,
    @SerializedName("reasoning_effort") val reasoningEffort: String? = null,
    @SerializedName("enable_thinking") val enableThinking: Boolean? = null,
    @SerializedName("thinking_budget") val thinkingBudget: String? = null,
    @SerializedName("web_search") val webSearch: Boolean? = null
)

data class UserModelSettings(
    @SerializedName("model_visibility") val modelVisibility: Map<String, Boolean> = emptyMap(),
    @SerializedName("model_overrides") val modelOverrides: Map<String, ModelOverrideConfig> = emptyMap()
)

// ==================== 绘图 ====================

data class DrawContextMessage(
    val role: String,
    val content: String? = null,
    val image: String? = null
)

data class DrawRequest(
    @SerializedName("prompt") val prompt: String,
    @SerializedName("resolution") val resolution: String = "2K",
    @SerializedName("aspect_ratio") val aspectRatio: String = "16:9",
    @SerializedName("model_id") val modelId: String? = null,
    @SerializedName("reference_image") val referenceImage: String? = null,
    @SerializedName("context_messages") val contextMessages: List<DrawContextMessage> = emptyList()
)

data class DrawResponse(
    val choices: List<DrawChoice> = emptyList(),
    val error: String? = null
)

data class DrawChoice(
    val message: DrawMessage? = null
)

data class DrawMessage(
    val content: String? = null
)

@Immutable
data class ModelInfo(
    val id: String,
    val name: String,
    val modelName: String? = null,
    val description: String? = null,
    val hidden: Boolean = false,
    val isDraw: Boolean = false,
    @SerializedName("supports_vision") val supportsVision: Boolean = false,
    @SerializedName("supports_reasoning") val supportsReasoning: Boolean = false,
    @SerializedName("supports_tools") val supportsTools: Boolean = false,
    @SerializedName("supports_web_search") val supportsWebSearch: Boolean = false,
    @SerializedName("config_schema") val configSchema: List<ModelConfigField> = emptyList()
)

data class SecurityUpdateRequest(
    @SerializedName("username") val username: String,
    @SerializedName("current_password") val currentPassword: String,
    @SerializedName("new_username") val newUsername: String? = null,
    @SerializedName("new_password") val newPassword: String? = null
)

// ==================== 长期记忆 ====================

data class MemoryItem(
    val id: Int,
    @SerializedName("memory_type") val memoryType: String,
    val content: String,
    val source: String,
    val importance: Int,
    @SerializedName("is_active") val isActive: Boolean = true,
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("last_recalled_at") val lastRecalledAt: String? = null,
    @SerializedName("recall_count") val recallCount: Int = 0,
    val layer: Int = 0,
    val period: String? = null
) {
    fun typeLabel(): String = when (memoryType) {
        "preference"   -> "偏好"
        "episode"      -> "经历"
        "relationship" -> "关系"
        "activity"     -> "活动"
        "summary"      -> "摘要"
        else           -> "记忆"
    }

    fun layerLabel(): String = when (layer) {
        0 -> "碎片"
        1 -> "日摘要"
        2 -> "周摘要"
        3 -> "月摘要"
        4 -> "年意识"
        else -> "记忆"
    }

    /** 格式化 period 为可读时间标签（仅 layer>=1 有意义） */
    fun periodLabel(): String {
        if (period == null) return ""
        return when (layer) {
            1 -> period  // "2026-03-05" 直接显示
            2 -> period.replace(Regex("(\\d{4})-W(\\d+)"), "$1年 第$2周")
            3 -> period.replace(Regex("(\\d{4})-(\\d{2})"), "$1年$2月")
            4 -> "${period}年"
            else -> period
        }
    }
}

data class MemoryListResponse(
    val status: String,
    val memories: List<MemoryItem> = emptyList(),
    val total: Int = 0
)

data class RelationshipStateResponse(
    val status: String = "ok",
    @SerializedName("username") val username: String = "",
    @SerializedName("character_id") val characterId: String = "",
    @SerializedName("conversation_id") val conversationId: String = "",
    @SerializedName("relationship_stage") val relationshipStage: String = "uncertain",
    @SerializedName("relationship_page") val relationshipPage: RelationshipPageContent? = null,
    @SerializedName("relationship_page_updated_at_ms") val relationshipPageUpdatedAtMs: Long = 0L,
    @SerializedName("updated_at_ms") val updatedAtMs: Long = 0L
)

data class RelationshipPageContent(
    val version: Int = 1,
    @SerializedName("stage_label") val stageLabel: String = "",
    val overview: String = "",
    val mood: String = "",
    val chips: List<String> = emptyList(),
    @SerializedName("self_portrait") val selfPortrait: String = "",
    @SerializedName("between_portrait") val betweenPortrait: String = "",
    @SerializedName("remembered_items") val rememberedItems: List<String> = emptyList(),
    @SerializedName("timeline_items") val timelineItems: List<String> = emptyList(),
    val suggestions: List<String> = emptyList()
)

data class RelationshipRefreshRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("conversation_id") val conversationId: String? = null
)

data class AddMemoryRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("memory_type") val memoryType: String = "episode",
    @SerializedName("content") val content: String,
    @SerializedName("importance") val importance: Int = 5,
    @SerializedName("source") val source: String = "manual"
)

data class UpdateMemoryRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("content") val content: String? = null,
    @SerializedName("importance") val importance: Int? = null,
    @SerializedName("memory_type") val memoryType: String? = null
)

data class DeleteMemoryRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String
)

// ==================== 陪玩会话历史 ====================

data class CompanionMessage(
    val role: String,           // "user" | "assistant"
    val content: String,
    @SerializedName("timestamp_ms") val timestampMs: Long = 0L
)

data class CompanionSessionSummary(
    val id: String,
    @SerializedName("character_name") val characterName: String,
    @SerializedName("started_at") val startedAt: String,
    @SerializedName("ended_at") val endedAt: String,
    @SerializedName("duration_seconds") val durationSeconds: Int,
    @SerializedName("frame_count") val frameCount: Int,
    @SerializedName("message_count") val messageCount: Int
)

data class CompanionSessionsResponse(
    val status: String,
    val sessions: List<CompanionSessionSummary> = emptyList()
)

data class CompanionSessionMessagesResponse(
    val status: String,
    val messages: List<CompanionMessage> = emptyList()
)

// ==================== 会员积分 ====================

data class QuotaInfo(
    val membershipType: String = "free",   // free / pro / pro_plus / developer / admin
    val membershipLabel: String = "免费",
    val dailyLimit: Int = 100,
    val usedToday: Int = 0,
    val remaining: Int = 100,
    val expireAt: String? = null
)

// ==================== 消息全文搜索 ====================

data class MessageSearchResponse(
    val results: List<SearchMessageResult>,
    val total: Int,
    @SerializedName("has_more") val hasMore: Boolean
)

data class MessageCountResponse(
    val status: String = "ok",
    val total: Int = 0
)

data class SearchMessageResult(
    @SerializedName("message_id") val messageId: String,
    @SerializedName("sequence_number") val sequenceNumber: Int,
    @SerializedName("conversation_id") val conversationId: String,
    val role: String,
    val content: String,
    val timestamp: Long,
    val attachments: List<MessageAttachment>? = null
)

// ==================== 分页加载消息 ====================

data class PagedMessagesResponse(
    val messages: List<ChatMessage>,
    @SerializedName("has_more") val hasMore: Boolean,
    @SerializedName("min_seq") val minSeq: Int? = null,
    @SerializedName("max_seq") val maxSeq: Int? = null,
    @SerializedName("conversation_id") val conversationId: String? = null
)

// ==================== 定时任务 ====================

data class ProactiveTaskListResponse(
    val status: String,
    val tasks: List<ProactiveTask> = emptyList()
)

data class ProactiveTask(
    val id: String,
    @SerializedName("character_id") val characterId: String,
    @SerializedName("conversation_id") val conversationId: String = "",
    val title: String = "",
    @SerializedName("task_type") val taskType: String = "custom",
    @SerializedName("schedule_type") val scheduleType: String = "once",
    val source: String = "user",
    val status: String = "active",
    val enabled: Boolean = true,
    @SerializedName("due_at_ms") val dueAtMs: Long = 0L,
    @SerializedName("interval_seconds") val intervalSeconds: Int = 0,
    @SerializedName("time_of_day") val timeOfDay: String = "",
    val timezone: String = "Asia/Shanghai",
    val days: List<Int> = emptyList(),
    @SerializedName("jitter_minutes") val jitterMinutes: Int = 0,
    val prompt: String = "",
    val style: String = "gentle",
    @SerializedName("last_run_at_ms") val lastRunAtMs: Long? = null,
    @SerializedName("run_count") val runCount: Int = 0
)

data class ProactiveTaskRequest(
    @SerializedName("character_id") val characterId: String,
    @SerializedName("conversation_id") val conversationId: String = "",
    val title: String = "",
    @SerializedName("task_type") val taskType: String = "custom",
    @SerializedName("schedule_type") val scheduleType: String = "once",
    @SerializedName("due_at_ms") val dueAtMs: Long? = null,
    @SerializedName("interval_seconds") val intervalSeconds: Int = 0,
    @SerializedName("time_of_day") val timeOfDay: String = "",
    val timezone: String = "Asia/Shanghai",
    val days: List<Int> = emptyList(),
    @SerializedName("jitter_minutes") val jitterMinutes: Int = 0,
    val prompt: String = "",
    val style: String = "gentle",
    val enabled: Boolean = true,
    @SerializedName("cancel_if_user_replies") val cancelIfUserReplies: Boolean = false
)

data class ProactiveTaskMutationResponse(
    val status: String,
    val id: String? = null,
    val message: String? = null
)

// ==================== 小游戏：中国象棋 ====================

data class XiangqiPrepareRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("character_name") val characterName: String,
    @SerializedName("user_name") val userName: String,
    @SerializedName("player_side") val playerSide: String,
    @SerializedName("game_memory") val gameMemory: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    @SerializedName("voice_reply_enabled") val voiceReplyEnabled: Boolean = false,
    @SerializedName("client_context") val clientContext: ClientContext? = null
)

data class XiangqiEntryCard(
    @SerializedName("schema_version") val schemaVersion: Int = 2,
    @SerializedName("power_tier") val powerTier: String? = null,
    @SerializedName("power_tier_label") val powerTierLabel: String? = null,
    @SerializedName("power_tier_reason") val powerTierReason: String? = null,
    val relationship: Map<String, Any?> = emptyMap(),
    val speech: Map<String, Any?> = emptyMap(),
    @SerializedName("chess_style") val chessStyle: Map<String, Any?> = emptyMap(),
    val reaction: Map<String, Any?> = emptyMap(),
    @SerializedName("execution_policy") val executionPolicy: Map<String, Any?> = emptyMap(),
    @SerializedName("memory_hooks") val memoryHooks: List<Map<String, Any?>> = emptyList()
)

data class XiangqiPrepareResponse(
    val status: String = "",
    val step: String = "",
    @SerializedName("entry_card") val entryCard: XiangqiEntryCard? = null,
    @SerializedName("card_text") val cardText: String? = null,
    val fallback: Boolean = false,
    val error: String? = null,
    @SerializedName("duration_ms") val durationMs: Long? = null
)

data class XiangqiPoint(
    val x: Int = 0,
    val y: Int = 0
)

data class XiangqiExecuteMove(
    val from: XiangqiPoint = XiangqiPoint(),
    val to: XiangqiPoint = XiangqiPoint(),
    val piece: String = "",
    val notation: String = "",
    val intent: String = "",
    val confidence: Double = 0.0
)

data class XiangqiMoveCandidate(
    val id: String,
    @SerializedName("quality_tag") val qualityTag: String,
    val move: XiangqiExecuteMove,
    val score: Int = 0,
    @SerializedName("score_delta") val scoreDelta: Int = 0,
    @SerializedName("is_capture") val isCapture: Boolean = false,
    @SerializedName("is_check") val isCheck: Boolean = false,
    @SerializedName("is_terminal_win") val isTerminalWin: Boolean = false,
    @SerializedName("result_after_move") val resultAfterMove: String = "ongoing",
    @SerializedName("captured_piece") val capturedPiece: String? = null,
    val side: String = "",
    val direction: String = "",
    @SerializedName("river_event") val riverEvent: String = "none",
    @SerializedName("move_summary") val moveSummary: String = "",
    @SerializedName("reply_hint") val replyHint: String = "",
    @SerializedName("tactical_reason") val tacticalReason: String = "",
    @SerializedName("tactical_caution") val tacticalCaution: String = "",
    @SerializedName("speech_hooks") val speechHooks: Map<String, String> = emptyMap(),
    val note: String = ""
)

data class XiangqiExecuteRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("game_id") val gameId: String,
    @SerializedName("character_name") val characterName: String,
    @SerializedName("user_name") val userName: String,
    @SerializedName("player_side") val playerSide: String,
    val turn: String,
    @SerializedName("board_state") val boardState: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    @SerializedName("move_history") val moveHistory: List<Map<String, @JvmSuppressWildcards Any?>> = emptyList(),
    @SerializedName("dialogue_history") val dialogueHistory: List<Map<String, @JvmSuppressWildcards Any?>> = emptyList(),
    @SerializedName("move_candidates") val moveCandidates: List<XiangqiMoveCandidate> = emptyList(),
    @SerializedName("user_message") val userMessage: String = "",
    @SerializedName("event_context") val eventContext: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    @SerializedName("entry_card") val entryCard: XiangqiEntryCard? = null,
    @SerializedName("game_memory") val gameMemory: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    @SerializedName("voice_reply_enabled") val voiceReplyEnabled: Boolean = false,
    @SerializedName("client_context") val clientContext: ClientContext? = null
)

data class XiangqiMemoryCommitRequest(
    @SerializedName("username") val username: String,
    @SerializedName("character_id") val characterId: String? = null,
    @SerializedName("conversation_id") val conversationId: String? = null,
    @SerializedName("character_name") val characterName: String,
    @SerializedName("user_name") val userName: String,
    @SerializedName("reason") val reason: String,
    @SerializedName("game_record") val gameRecord: Map<String, @JvmSuppressWildcards Any?> = emptyMap(),
    @SerializedName("client_context") val clientContext: ClientContext? = null
)

data class XiangqiCharacterReply(
    @SerializedName("reaction_text") val reactionText: String = "",
    @SerializedName("move_reason_text") val moveReasonText: String = "",
    @SerializedName("casual_chat_text") val casualChatText: String = "",
    val text: String = "",
    @SerializedName("tts_text") val ttsText: String = "",
    val emotion: String = "",
    @SerializedName("style_tags") val styleTags: List<String> = emptyList()
)

data class XiangqiExecuteResult(
    @SerializedName("schema_version") val schemaVersion: Int = 2,
    val action: String = "chat_only",
    @SerializedName("selected_move_id") val selectedMoveId: String? = null,
    @SerializedName(value = "近期重复词", alternate = ["recent_repeated_terms"])
    val recentRepeatedTerms: List<String> = emptyList(),
    @SerializedName("character_reply") val characterReply: XiangqiCharacterReply? = null,
    val move: XiangqiExecuteMove? = null,
    @SerializedName("next_plan") val nextPlan: Map<String, Any?> = emptyMap(),
    val ui: Map<String, Any?> = emptyMap(),
    val safety: Map<String, Any?> = emptyMap()
)

data class XiangqiExecuteResponse(
    val status: String = "",
    val step: String = "",
    val result: XiangqiExecuteResult? = null,
    val fallback: Boolean = false,
    val error: String? = null,
    @SerializedName("duration_ms") val durationMs: Long? = null
)
